"""In-memory background jobs of the web UI.

Each job runs in its own daemon thread, so stopping the server never waits for a long build.
Profile builds are exclusive (a second submission raises ``JobConflict``).
Chats run side by side, at most ``answer_workers`` at once, the rest stay queued, and at most
``MAX_PENDING_ANSWERS`` of them may be unfinished (one more raises ``TooManyJobs``). Jobs live only in memory.

Besides the last ``MAX_PROGRESS_LINES`` progress lines, a job keeps its stage (from the ``[n/N]`` lines), a tally of the
``ok`` / ``FAILED`` lines of the current stage and, separately, its milestones (stage markers and Chinese summaries).
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..embed import EmbedError
from ..llm import LLMError

JobKind = Literal["persona_build", "chat", "video", "media_ingest"]
JobStatus = Literal["queued", "running", "done", "failed"]
Log = Callable[[str], None]
JobFn = Callable[[Log], object]

JOB_LABELS: dict[JobKind, str] = {
    "persona_build": "构建人格档案",
    "chat": "和分身聊天",
    "video": "生成视频",
    "media_ingest": "转写音视频",
}
EXCLUSIVE_KINDS: frozenset[JobKind] = frozenset({"persona_build"})
MAX_PROGRESS_LINES = 500
MAX_MILESTONES = 2000
MAX_PENDING_ANSWERS = 20
LISTED_JOBS = 50
KEPT_JOBS = 200

logger = logging.getLogger(__name__)

# "[2/4] 抽取候选条目": the start of a pipeline stage.
STAGE_LINE = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*)$")

CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_HOME_SEP = r"(?=[/\\]|$|[^\w.-])"


def hide_home(text: str) -> str:
    """``text`` with this account's home directory written as ``~``, so no absolute local path reaches the page."""
    try:
        home = str(Path.home()).rstrip("/\\")
    except RuntimeError:
        return text
    if not home:
        return text
    return re.sub(re.escape(home) + _HOME_SEP, "~", text)


def is_milestone(line: str) -> bool:
    """Stage markers and the Chinese summary lines the web jobs write themselves (the library's own per-call lines
    such as ``ok ...`` / ``FAILED ...`` are English)."""
    return STAGE_LINE.match(line) is not None or CJK.match(line.lstrip()) is not None


class JobError(Exception):
    """A job failure whose message already explains, in Chinese, what went wrong and what to do."""


class TooManyJobs(Exception):
    """Too many chats are waiting or running (answered with 429)."""


class JobConflict(Exception):
    def __init__(self, job: Job, message: str | None = None) -> None:
        label = JOB_LABELS[job.kind]
        super().__init__(
            message or f"已有{label}任务在运行（{job.job_id}），同一时间只能运行一个人格构建任务，请等它结束后再提交"
        )
        self.job = job


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(eq=False)
class Job:
    job_id: str
    kind: JobKind
    title: str
    created: dt.datetime
    persona_id: str = "default"
    status: JobStatus = "queued"
    started: dt.datetime | None = None
    finished: dt.datetime | None = None
    progress: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_PROGRESS_LINES))
    milestones: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_MILESTONES))
    stage: dict[str, Any] | None = None
    tally_done: int = 0
    tally_failed: int = 0
    tally_total: int | None = None
    result: object = None
    error: str | None = None
    done: threading.Event = field(default_factory=threading.Event)

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")


class JobManager:
    """``describe_error`` turns an exception raised by a job into the Chinese explanation stored in ``error``."""

    def __init__(self, answer_workers: int, describe_error: Callable[[Exception], str]) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._exclusive_slot: list[Job | None] = [None]
        self._answer_slots = threading.BoundedSemaphore(max(1, answer_workers))
        self._media_slot = threading.BoundedSemaphore(1)
        self._video_slot = threading.BoundedSemaphore(1)
        self._describe_error = describe_error
        self.persona_id: str | None = None

    def scoped(self, persona_id: str) -> JobManager:
        """A persona-filtered view sharing admission locks, job records and worker slots."""
        scoped = copy.copy(self)
        scoped.persona_id = persona_id
        return scoped

    def has_active(self, persona_id: str) -> bool:
        with self._lock:
            return any(j.active and j.persona_id == persona_id for j in self._jobs.values())

    def submit(
        self,
        kind: JobKind,
        title: str,
        fn: JobFn,
        *,
        prepare: Callable[[Job], None] | None = None,
        require_idle: bool = False,
    ) -> Job:
        """Accept a bounded background job; profile builds are mutually exclusive."""
        exclusive = kind in EXCLUSIVE_KINDS
        with self._lock:
            if (exclusive or require_idle) and self._exclusive_slot[0] is not None and self._exclusive_slot[0].active:
                raise JobConflict(self._exclusive_slot[0])
            if not exclusive:
                pending = sum(1 for j in self._jobs.values() if j.active and j.kind not in EXCLUSIVE_KINDS)
                if pending >= MAX_PENDING_ANSWERS:
                    raise TooManyJobs(
                        f"已有 {pending} 个聊天任务在排队或运行（上限 {MAX_PENDING_ANSWERS} 个），"
                        "请等前面的任务完成后再提交"
                    )
            job = Job(
                job_id=self._new_id(), kind=kind, title=title, created=_now(), persona_id=self.persona_id or "default"
            )
            # Capture input and persist acceptance before a worker can run, under the same admission lock as builds.
            if prepare is not None:
                prepare(job)
            self._jobs[job.job_id] = job
            if exclusive:
                self._exclusive_slot[0] = job
            self._evict()
        try:
            threading.Thread(target=self._run, args=(job, fn), name=f"twin-{job.job_id}", daemon=True).start()
        except BaseException:
            with self._lock:
                job.status, job.finished = "failed", _now()
                job.error = "无法启动后台任务，请稍后重试"
            job.done.set()
            raise
        return job

    def active_exclusive(self, kinds: frozenset[JobKind] = EXCLUSIVE_KINDS) -> Job | None:
        """The running (or queued) exclusive job whose kind is in ``kinds``, if any."""
        with self._lock:
            job = self._exclusive_slot[0]
            return job if job is not None and job.active and job.kind in kinds else None

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return (
                self._view(job, with_result=True)
                if job is not None and (self.persona_id is None or job.persona_id == self.persona_id)
                else None
            )

    def recent(self, n: int = LISTED_JOBS) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if self.persona_id is None or j.persona_id == self.persona_id][-n:]
            return [self._view(job, with_result=False) for job in reversed(jobs)]

    def wait(self, job_id: str, timeout: float | None = None) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        return job is not None and job.done.wait(timeout)

    def _new_id(self) -> str:
        while True:
            job_id = f"j_{_now():%Y%m%d_%H%M%S}_{secrets.token_hex(2)}"
            if job_id not in self._jobs:
                return job_id

    def _evict(self) -> None:
        excess = len(self._jobs) - KEPT_JOBS
        for job_id in [j.job_id for j in self._jobs.values() if not j.active][: max(0, excess)]:
            del self._jobs[job_id]

    @staticmethod
    def _view(job: Job, *, with_result: bool) -> dict[str, Any]:
        view: dict[str, Any] = {
            "job_id": job.job_id,
            "persona_id": job.persona_id,
            "kind": job.kind,
            "kind_label": JOB_LABELS[job.kind],
            "title": job.title,
            "status": job.status,
            "created": _iso(job.created),
            "started": _iso(job.started),
            "finished": _iso(job.finished),
            "progress": list(job.progress),
            "milestones": list(job.milestones),
            "stage": dict(job.stage) if job.stage is not None else None,
            "tally": {"done": job.tally_done, "failed": job.tally_failed, "total": job.tally_total},
            "error": job.error,
        }
        if with_result:
            view["result"] = job.result
        return view

    def _log(self, job: Job, message: str) -> None:
        lines = [line for line in hide_home(str(message)).splitlines() if line.strip()]
        with self._lock:
            for line in lines:
                job.progress.append(line)
                self._track(job, line)

    @staticmethod
    def _track(job: Job, line: str) -> None:
        """Stage, per-stage tally of ``ok`` / ``FAILED`` calls and milestones, from one progress line."""
        if is_milestone(line):
            job.milestones.append(line)
        stage = STAGE_LINE.match(line)
        if stage is not None:
            job.stage = {"current": int(stage[1]), "total": int(stage[2]), "label": stage[3].strip()}
            job.tally_done = job.tally_failed = 0
            job.tally_total = None
        elif line.startswith("ok "):
            job.tally_done += 1
        elif line.startswith("FAILED "):
            job.tally_failed += 1

    def _run(self, job: Job, fn: JobFn) -> None:
        slot = (
            self._media_slot
            if job.kind == "media_ingest"
            else self._video_slot
            if job.kind == "video"
            else (None if job.kind in EXCLUSIVE_KINDS else self._answer_slots)
        )
        if slot is not None:
            slot.acquire()
        try:
            with self._lock:
                job.status, job.started = "running", _now()
            try:
                result = fn(lambda message: self._log(job, message))
            except Exception as e:
                logger.exception("job %s (%s) failed", job.job_id, job.kind)
                error = hide_home(f"{JOB_LABELS[job.kind]}失败：{self._describe_error(e)}")
                with self._lock:
                    job.status, job.error, job.finished = "failed", error, _now()
            else:
                with self._lock:
                    job.status, job.result, job.finished = "done", result, _now()
        finally:
            # A BaseException (SystemExit raised inside a job) must not leave the job running for ever, which would
            # block every later profile build with 409.
            with self._lock:
                if job.active:
                    job.status, job.finished = "failed", _now()
                    job.error = f"{JOB_LABELS[job.kind]}失败：任务意外中断（详细信息见运行 twin ui 的终端）"
            if slot is not None:
                slot.release()
            job.done.set()


class PersonaProcessing:
    """Debounced builds with one coalesced follow-up, including builds submitted elsewhere."""

    def __init__(
        self,
        jobs: JobManager,
        build: JobFn,
        finished: Callable[[dict[str, Any]], None],
        *,
        schedule: Callable[[float, Callable[[], None]], Any] | None = None,
        delay: float = 3.0,
    ) -> None:
        self.jobs, self.build, self.finished = jobs, build, finished
        self.delay = delay
        self._schedule = schedule or self._timer
        self._lock = threading.RLock()
        self._pending = False
        self._timer_handle: Any = None
        self._job: Job | None = None
        self._last: dict[str, Any] = {}
        self._generation = 0
        self._closed = False

    @staticmethod
    def _timer(delay: float, fn: Callable[[], None]) -> threading.Timer:
        timer = threading.Timer(delay, fn)
        timer.daemon = True
        timer.start()
        return timer

    def queue(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._pending = True
            self._generation += 1
            if self._timer_handle is not None:
                self._timer_handle.cancel()
                self._timer_handle = None
            active = self.jobs.active_exclusive()
            if active is not None:
                self._watch(active)
            else:
                generation = self._generation
                self._timer_handle = self._schedule(self.delay, lambda: self._launch(generation))

    def start(self) -> Job:
        with self._lock:
            self._generation += 1
            if self._timer_handle is not None:
                self._timer_handle.cancel()
                self._timer_handle = None
            active = self.jobs.active_exclusive()
            if active is not None:
                self._pending = True
                self._watch(active)
                if self.jobs.persona_id is not None and active.persona_id != self.jobs.persona_id:
                    raise JobConflict(active, "另一个分身正在处理记忆，这个分身已排队")
                return active
            self._pending = False
            job = self.jobs.submit("persona_build", "重新处理记忆", self.build)
            self._watch(job)
            return job

    def _launch(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or not self._pending:
                return
            self._timer_handle = None
            try:
                self.start()
            except JobConflict as conflict:
                self._pending = True
                self._watch(conflict.job)

    def _watch(self, job: Job) -> None:
        if self._job is job:
            return
        self._job = job
        threading.Thread(target=self._complete, args=(job,), daemon=True).start()

    def _complete(self, job: Job) -> None:
        job.done.wait()
        with self._lock:
            snapshot = self.jobs.snapshot(job.job_id)
            if snapshot is not None:
                self._last = snapshot
                self.finished(snapshot)
            if self._job is job:
                self._job = None
            if self._pending and not self._closed and self.jobs.active_exclusive() is None:
                if self._timer_handle is not None:
                    self._timer_handle.cancel()
                generation = self._generation
                self._timer_handle = self._schedule(self.delay, lambda: self._launch(generation))

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending = False
            self._generation += 1
            if self._timer_handle is not None:
                self._timer_handle.cancel()

    def close_if_idle(self) -> bool:
        with self._lock:
            if self.jobs.has_active(self.jobs.persona_id or "default"):
                return False
            self.close()
            return True

    def view(self) -> dict[str, Any]:
        with self._lock:
            active = self.jobs.active_exclusive()
            if active is not None and self.jobs.persona_id is not None and active.persona_id != self.jobs.persona_id:
                active = None
            return {
                "state": "running" if active is not None else "queued" if self._pending else "idle",
                "job_id": active.job_id if active is not None else None,
                "last_finished_at": self._last.get("finished"),
                "last_error": self._last.get("error"),
            }


def _backend_errors() -> tuple[type[Exception], ...]:
    """Base exceptions of the model / embedding SDKs and of the claude CLI subprocess; an SDK exception can only exist
    if its module was imported, so they are looked up in ``sys.modules``."""
    errors: list[type[Exception]] = [subprocess.SubprocessError]
    for module, name in (("anthropic", "AnthropicError"), ("openai", "OpenAIError")):
        if module in sys.modules:
            errors.append(getattr(sys.modules[module], name))
    return tuple(errors)


def describe_error(e: Exception) -> str:
    """Chinese explanation of an exception raised by a job, the home directory written as ``~``."""
    return hide_home(_describe(e))


def _describe(e: Exception) -> str:
    if isinstance(e, JobError):
        return str(e)
    if isinstance(e, LLMError):
        return f"调用大模型失败：{e}。请检查模型服务地址、密钥、网络和限流情况"
    if isinstance(e, EmbedError):
        return f"调用向量化服务失败：{e}。请检查 [embed] 配置和向量服务"
    if isinstance(e, sqlite3.Error):
        return f"资料库读写失败：{e}"
    if isinstance(e, OSError):
        return f"文件读写失败：{e}"
    if isinstance(e, ValueError):
        return f"数据或参数有误：{e}"
    if isinstance(e, _backend_errors()):
        return f"调用模型服务失败：{type(e).__name__}: {e}"
    return f"内部错误：{type(e).__name__}: {e}（详细信息见运行 twin ui 的终端）"
