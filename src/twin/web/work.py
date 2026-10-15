"""Web routes of work mode (``/api/persona/work...``): start or continue a task, follow it, download what it wrote.

A task belongs to whoever started it, in the role they started it in: the person's own tasks, and each visitor's
of a public twin, are only listed and opened by them. A turn runs as a background job; the task records its
progress lines while it runs and the reply with its files once it ends.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import Settings
from ..persona.store import stored_identity
from ..persona.work import MAX_TEXT, WorkStore, WorkTask, WorkTurn, now, run_turn, summary_view, task_view
from .backends import Backends, BackendUnavailable
from .conversations import owner
from .jobs import Job, JobManager, Log


class WorkBody(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    task_id: str | None = None


def register(app: FastAPI, settings: Settings, backends: Backends, jobs: JobManager) -> None:
    store = WorkStore(settings.db_path)
    # Starting a turn checks and marks the task running in one step, so a task never runs two turns at once.
    admission = threading.Lock()

    def who(request: Request) -> tuple[str | None, bool]:
        return owner(request), bool(request.scope.get("twin_visitor"))

    def mine(request: Request, task_id: str) -> WorkTask:
        task = store.get(task_id)
        if task is None or (task.by, task.visitor) != who(request):
            raise HTTPException(404, "找不到这个任务")
        return task

    def view(task: WorkTask) -> dict[str, Any]:
        data = task_view(store, task)
        snapshot = jobs.snapshot(task.job_id) if task.job_id and task.status == "running" else None
        data["progress"] = snapshot["progress"] if snapshot else []
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
                if view(task)["status"] == "running":
                    raise HTTPException(409, "上一句还在做，等它做完再说")
            history = task.model_copy(deep=True)

            def prepare(job: Job) -> None:
                # Marked running with its job before the job starts, so a reader never sees a running task
                # without a job to follow.
                task.turns.append(WorkTurn(role="user", content=text, at=now()))
                task.status, task.error, task.job_id = "running", None, job.job_id
                task.updated_at = task.turns[-1].at
                store.save(task)

            def finish(update: Callable[[WorkTask], None]) -> None:
                with admission:
                    current = store.get(task.task_id)
                    if current is not None:  # None: deleted while it ran
                        update(current)
                        store.save(current)

            def work(log: Log) -> dict[str, Any]:
                files = store.files_dir(task.task_id)
                try:
                    turn = run_turn(history, text, settings, model, llm, embedder, files, log, name=name)
                except Exception:

                    def failed(current: WorkTask) -> None:
                        current.status, current.error = "failed", "这件事没做成，可以换个说法再试一次"

                    finish(failed)
                    raise

                def done(current: WorkTask) -> None:
                    current.turns.append(turn)
                    current.status, current.updated_at = "idle", turn.at

                finish(done)
                return {"task_id": task.task_id}

            try:
                job = jobs.submit("work", task.title, work, prepare=prepare)
            except BaseException:
                if body.task_id is None:  # not admitted: a new task would stay behind empty
                    store.delete(task.task_id)
                raise
        return {"task": summary_view(task), "job_id": job.job_id}

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
