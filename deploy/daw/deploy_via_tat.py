#!/usr/bin/env python3
"""Ship a twin release archive to daw through Tencent Cloud TAT and run deploy/daw/deploy.sh there.

Runs in the cnb pipeline (see .cnb.yml): daw accepts no inbound deploy connection, but TAT can run root commands
on it. A command is at most 64 KB, so the archive goes up in base64 chunks, then one command joins, verifies and
deploys it. Same approach as the audiostudio project, which deploys to the same machine.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import shlex
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

MAX_TAT_CONTENT_BYTES = 64 * 1024
ARCHIVE_CHUNK_BYTES = 30_000
# Each chunk is one TAT round trip (dispatch plus 2 s polls); chunks are independent files, so upload in parallel.
UPLOAD_PARALLELISM = 8
FINISHED = {"CANCELLED", "DELIVER_FAILED", "FAILED", "START_FAILED", "SUCCESS", "TASK_TIMEOUT", "TERMINATED", "TIMEOUT"}


def encoded_command(command: str) -> str:
    content = base64.b64encode(command.encode()).decode()
    if len(content) > MAX_TAT_CONTENT_BYTES:
        raise ValueError("TAT command exceeds the 64 KB encoded-content limit")
    return content


def chunk_names(archive: bytes, remote_dir: str) -> list[str]:
    return [f"{remote_dir}/part-{index:04d}" for index in range(len(range(0, len(archive), ARCHIVE_CHUNK_BYTES)))]


def upload_commands(archive: bytes, remote_dir: str) -> list[str]:
    """The first command makes a private staging directory; each of the rest writes one chunk."""
    commands = [f"umask 077; rm -rf {shlex.quote(remote_dir)}; mkdir -p {shlex.quote(remote_dir)}"]
    for name, offset in zip(chunk_names(archive, remote_dir), range(0, len(archive), ARCHIVE_CHUNK_BYTES), strict=True):
        chunk = base64.b64encode(archive[offset : offset + ARCHIVE_CHUNK_BYTES]).decode()
        commands.append(f"printf %s {shlex.quote(chunk)} | base64 --decode > {shlex.quote(name)}")
    for command in commands:
        encoded_command(command)
    return commands


def final_command(archive: bytes, remote_dir: str) -> str:
    """Join the chunks, check the digest, and run the deploy script from inside the release itself."""
    digest = hashlib.sha256(archive).hexdigest()
    staging = shlex.quote(remote_dir)
    release = shlex.quote(f"{remote_dir}/release.tar.gz")
    script = shlex.quote(f"{remote_dir}/deploy.sh")
    parts = " ".join(shlex.quote(name) for name in chunk_names(archive, remote_dir))
    return f"""set -euo pipefail
trap 'rm -rf {staging}' EXIT
cat {parts} > {release}
test "$(sha256sum < {release} | cut -d' ' -f1)" = {shlex.quote(digest)}
tar -xOf {release} deploy/daw/deploy.sh > {script}
chmod 700 {script}
{script} {release}
"""


def run_tat(client: Any, instance_id: str, command: str, timeout: int = 600) -> str:
    response = client.call_json(
        "RunCommand",
        {
            "CommandName": "twin-cnb-deploy",
            "CommandType": "SHELL",
            "Content": encoded_command(command),
            "InstanceIds": [instance_id],
            "Timeout": timeout,
            "Username": "root",
            "WorkingDirectory": "/root",
        },
    ).get("Response", {})
    invocation_id = response.get("InvocationId")
    if not invocation_id:
        raise RuntimeError(f"TAT did not return an invocation id: {response}")
    deadline = time.monotonic() + timeout + 30
    while time.monotonic() < deadline:
        result = client.call_json(
            "DescribeInvocationTasks",
            {"Filters": [{"Name": "invocation-id", "Values": [invocation_id]}], "HideOutput": False, "Limit": 1},
        ).get("Response", {})
        tasks = result.get("InvocationTaskSet") or []
        if not tasks or tasks[0].get("TaskStatus") not in FINISHED:
            time.sleep(2)
            continue
        task = tasks[0]
        output = base64.b64decode((task.get("TaskResult") or {}).get("Output") or b"").decode(errors="replace")
        if task.get("TaskStatus") != "SUCCESS":
            outcome = task.get("TaskResult") or {}
            dropped = outcome.get("Dropped") or 0
            note = f" [{dropped} bytes of output dropped by TAT]" if dropped else ""
            raise RuntimeError(
                f"TAT command {task.get('TaskStatus')} (exit {outcome.get('ExitCode')}):{note} "
                f"{task.get('ErrorInfo') or output}"
            )
        return output
    raise TimeoutError(f"Timed out waiting for TAT invocation {invocation_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    secret_id = os.environ.get("CNB_TKE_DEV_SECRET_ID") or os.environ.get("TENCENTCLOUD_SECRET_ID")
    secret_key = os.environ.get("CNB_TKE_DEV_SECRET_KEY") or os.environ.get("TENCENTCLOUD_SECRET_KEY")
    region = os.environ.get("TWIN_TAT_REGION", "ap-nanjing")
    instance_id = os.environ.get("TWIN_TAT_INSTANCE_ID", "ins-mgz1lxik")
    if not secret_id or not secret_key:
        raise SystemExit("Tencent Cloud credentials are not available")

    from tencentcloud.common import credential
    from tencentcloud.common.common_client import CommonClient
    from tencentcloud.common.profile.client_profile import ClientProfile

    archive = args.archive.read_bytes()
    if not archive:
        raise SystemExit("Release archive is empty")
    remote_dir = f"/tmp/twin-cnb-{hashlib.sha256(archive).hexdigest()[:16]}"

    def make_client() -> Any:
        return CommonClient("tat", "2020-10-28", credential.Credential(secret_id, secret_key), region, ClientProfile())

    client = make_client()
    local = threading.local()  # the SDK does not promise a thread-safe client

    def upload(command: str) -> str:
        if not hasattr(local, "client"):
            local.client = make_client()
        return run_tat(local.client, instance_id, command, timeout=120)

    mkdir, *chunks = upload_commands(archive, remote_dir)
    run_tat(client, instance_id, mkdir, timeout=120)
    with ThreadPoolExecutor(max_workers=UPLOAD_PARALLELISM) as pool:
        for done, _ in enumerate(pool.map(upload, chunks), start=1):
            if done % 20 == 0 or done == len(chunks):
                print(f"Uploaded release chunk {done}/{len(chunks)}", flush=True)
    print(run_tat(client, instance_id, final_command(archive, remote_dir), timeout=1500).strip())


if __name__ == "__main__":
    main()
