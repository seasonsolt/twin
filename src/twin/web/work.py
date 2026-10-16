"""Web routes of work mode (``/api/persona/work...``): start or continue a task, follow it, download what it wrote.

A task belongs to whoever started it, in the role they started it in: the person's own tasks, and each visitor's
of a public twin, are only listed and opened by them. A turn runs as a background job; the task records its
progress lines while it runs and the reply with its files once it ends; a reply answered on chat's path shows
what it rests on, as chat does. While it runs, a new message goes to the
agent at its next step instead of waiting, and a stop ends it at the next step.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import Settings
from ..persona.store import PersonaStore, stored_identity
from ..persona.work import (
    MAX_TEXT,
    Steering,
    WorkStore,
    WorkTask,
    WorkTurn,
    now,
    run_turn,
    summary_view,
    task_view,
)
from .backends import Backends, BackendUnavailable
from .conversations import owner
from .jobs import Job, JobManager, Log


class WorkBody(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    task_id: str | None = None


CitedView = Callable[[PersonaStore, Sequence[str]], list[dict[str, Any]]]


def register(app: FastAPI, settings: Settings, backends: Backends, jobs: JobManager, cited: CitedView) -> None:
    """``cited`` says what a turn's citations are, as chat shows them."""
    store = WorkStore(settings.db_path)
    # Starting a turn checks and marks the task running in one step, so a task never runs two turns at once.
    admission = threading.Lock()
    # The turn in flight of each running task, to say more to it or stop it; guarded by ``admission``.
    steerings: dict[str, Steering] = {}

    def who(request: Request) -> tuple[str | None, bool]:
        return owner(request), bool(request.scope.get("twin_visitor"))

    def mine(request: Request, task_id: str) -> WorkTask:
        task = store.get(task_id)
        if task is None or (task.by, task.visitor) != who(request):
            raise HTTPException(404, "找不到这个任务")
        return task

    def view(task: WorkTask) -> dict[str, Any]:
        data = task_view(store, task)
        if any(t.citations for t in task.turns):
            with PersonaStore(settings.db_path) as persona:
                for turn, shown in zip(task.turns, data["turns"], strict=True):
                    if turn.citations:
                        shown["cited"] = cited(persona, turn.citations)
        snapshot = jobs.snapshot(task.job_id) if task.job_id and task.status == "running" else None
        data["progress"] = snapshot["progress"] if snapshot else []
        steering = steerings.get(task.task_id)
        data["stopping"] = task.status == "running" and steering is not None and steering.stopped
        if task.status == "running" and snapshot is None:
            # The server restarted during the turn: the job is gone, so the turn is too.
            data["status"], data["error"] = "failed", "上次没做完就中断了，可以再说一次"
        return data

    @app.get("/api/persona/work")
    def list_work(request: Request) -> dict[str, Any]:
        by, visitor = who(request)
        return {"tasks": [summary_view(t) for t in store.list_tasks(by, visitor)]}

    @app.get("/api/persona/work/{task_id}")
    def get_work(task_id: str, request: Request) -> dict[str, Any]:
        return view(mine(request, task_id))

    @app.post("/api/persona/work", status_code=202)
    def start_work(body: WorkBody, request: Request) -> dict[str, Any]:
        """Start a task, continue one, or, while it runs, say something more to it."""
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "说一下要做什么")
        by, visitor = who(request)
        try:
            model = backends.work_model()
            llm, embedder = backends.chat_llm(), backends.embedder()
        except BackendUnavailable as e:
            raise HTTPException(503, str(e)) from e
        name = stored_identity(settings.db_path)[0] or settings.target_name
        with admission:
            if body.task_id is None:
                task = store.create(text, by, visitor)
            else:
                task = mine(request, body.task_id)
                steering = steerings.get(task.task_id)
                if steering is not None and view(task)["status"] == "running":
                    task.turns.append(WorkTurn(role="user", content=text, at=now()))
                    task.updated_at = task.turns[-1].at
                    store.save(task)
                    steering.say(text)
                    return {"task": summary_view(task), "job_id": task.job_id, "steered": True}
            history = task.model_copy(deep=True)
            steering = Steering()

            def prepare(job: Job) -> None:
                # Marked running with its job before the job starts, so a reader never sees a running task
                # without a job to follow.
                task.turns.append(WorkTurn(role="user", content=text, at=now()))
                task.status, task.error, task.job_id = "running", None, job.job_id
                task.updated_at = task.turns[-1].at
                store.save(task)
                steerings[task.task_id] = steering

            def work(log: Log) -> dict[str, Any]:
                files = store.files_dir(task.task_id)
                snapshot, request_text = history, text
                try:
                    while True:
                        turn = run_turn(
                            snapshot,
                            request_text,
                            settings,
                            model,
                            llm,
                            embedder,
                            files,
                            log,
                            name=name,
                            steering=steering,
                        )
                        with admission:
                            current = store.get(task.task_id)
                            if current is None:  # deleted while it ran
                                steerings.pop(task.task_id, None)
                                return {"task_id": task.task_id}
                            # Messages that came in after the agent last looked are the newest user turns; the
                            # reply goes before them, and they get a turn of their own.
                            unread = steering.take()
                            at = len(current.turns) - len(unread)
                            current.turns.insert(at, turn)
                            current.updated_at = now()
                            if not unread:
                                current.status = "idle"
                                steerings.pop(task.task_id, None)
                            store.save(current)
                        if not unread:
                            return {"task_id": task.task_id}
                        steering.resume()
                        snapshot = current.model_copy(update={"turns": current.turns[: at + 1]}, deep=True)
                        request_text = "\n\n".join(unread)
                except Exception:
                    with admission:
                        steerings.pop(task.task_id, None)
                        failed = store.get(task.task_id)
                        if failed is not None:
                            failed.status, failed.error = "failed", "这件事没做成，可以换个说法再试一次"
                            store.save(failed)
                    raise

            try:
                job = jobs.submit("work", task.title, work, prepare=prepare)
            except BaseException:
                if body.task_id is None:  # not admitted: a new task would stay behind empty
                    store.delete(task.task_id)
                raise
        return {"task": summary_view(task), "job_id": job.job_id, "steered": False}

    @app.post("/api/persona/work/{task_id}/stop", status_code=202)
    def stop_work(task_id: str, request: Request) -> dict[str, bool]:
        """Stop the turn in flight at its next step; what it already wrote stays."""
        task = mine(request, task_id)
        with admission:
            steering = steerings.get(task.task_id)
            if steering is None or view(task)["status"] != "running":
                raise HTTPException(409, "现在没有在做的事")
            steering.stop()
        return {"stopping": True}

    @app.get("/api/persona/work/{task_id}/files/{path:path}")
    def download_work_file(task_id: str, path: str, request: Request) -> FileResponse:
        task = mine(request, task_id)
        target = store.file(task.task_id, path)
        if target is None:
            raise HTTPException(404, "找不到这个文件")
        return FileResponse(target, filename=target.name)

    @app.delete("/api/persona/work/{task_id}")
    def delete_work(task_id: str, request: Request) -> dict[str, bool]:
        task = mine(request, task_id)
        with admission:
            if view(task)["status"] == "running":
                raise HTTPException(409, "任务还在做，做完再删")
            store.delete(task.task_id)
        return {"deleted": True}
