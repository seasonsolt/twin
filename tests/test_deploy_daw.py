"""daw deployment tooling: TAT chunking, the remote handoff, and the pieces that must agree with each other."""

from __future__ import annotations

import getpass
import importlib.util
import io
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
DAW = ROOT / "deploy/daw"


@pytest.fixture
def tat() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deploy_via_tat", DAW / "deploy_via_tat.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release(deploy_script: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        # Incompressible padding, so the release spans several TAT chunks.
        for name, data in {"deploy/daw/deploy.sh": deploy_script.encode(), "padding.bin": os.urandom(70_000)}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_chunks_fit_tat_and_reassemble_into_a_verified_deploy(tat: ModuleType, tmp_path: Path) -> None:
    marker = tmp_path / "ran-with"
    archive = release(f'#!/usr/bin/env bash\nprintf %s "$1" > {marker}\ntest -f "$1"\n')
    staging = str(tmp_path / "staging")
    commands = tat.upload_commands(archive, staging)
    assert len(commands) == 1 + len(tat.chunk_names(archive, staging)) >= 4
    for command in commands:
        assert len(tat.encoded_command(command)) <= tat.MAX_TAT_CONTENT_BYTES
        subprocess.run(["bash", "-c", command], check=True)
    subprocess.run(["bash", "-c", tat.final_command(archive, staging)], check=True)
    assert marker.read_text() == f"{staging}/release.tar.gz"
    assert not Path(staging).exists()


def test_corrupted_chunk_stops_before_deploying(tat: ModuleType, tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    archive = release(f"#!/usr/bin/env bash\ntouch {marker}\n")
    staging = str(tmp_path / "staging")
    for command in tat.upload_commands(archive, staging):
        subprocess.run(["bash", "-c", command], check=True)
    first = Path(tat.chunk_names(archive, staging)[0])
    first.write_bytes(b"tampered" + first.read_bytes()[8:])
    result = subprocess.run(["bash", "-c", tat.final_command(archive, staging)], capture_output=True)
    assert result.returncode != 0 and not marker.exists()


def test_oversized_command_is_refused(tat: ModuleType) -> None:
    with pytest.raises(ValueError, match="64 KB"):
        tat.encoded_command("x" * tat.MAX_TAT_CONTENT_BYTES)


def test_scripts_parse() -> None:
    for script in (DAW / "deploy.sh", ROOT / "deploy/gpu/install.sh"):
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_a_release_that_migrates_the_data_one_way_is_not_switched_back() -> None:
    deploy = (DAW / "deploy.sh").read_text()
    probe = re.search(r"migrations\(\) \{\n.*?-c '\n(.*?)'\n\}", deploy, re.S)
    assert probe, "deploy.sh counts each database's migrations"
    from twin import teamdb
    from twin.persona import store

    counted = subprocess.run([sys.executable, "-c", probe[1]], capture_output=True, text=True, check=True)
    assert counted.stdout.split() == [str(len(store._MIGRATIONS)), str(len(teamdb._MIGRATIONS))]
    # Past a one-way migration, a failed check stops with the backup to go back from, never the previous code.
    failed = deploy[deploy.index('switch_to "$target"') :]
    assert failed.index('if [[ -n "$one_way" ]]') < failed.index('switch_to "$previous"')
    assert "${backup:-" in failed


def test_port_prefix_and_host_agree_across_files() -> None:
    service = (DAW / "twin.service").read_text()
    nginx = (DAW / "nginx-twin.conf").read_text()
    deploy = (DAW / "deploy.sh").read_text()
    port = re.search(r"--port (\d+)", service)
    assert port and f"proxy_pass http://127.0.0.1:{port[1]}/;" in nginx and f"PORT={port[1]}" in deploy
    assert "--host 127.0.0.1" in service and "--allow-host daw.xjjk.com" in service
    assert "location ^~ /twin/" in nginx and "proxy_set_header X-Forwarded-Prefix /twin;" in nginx
    assert "proxy_buffering off;" in nginx
    cnb = (ROOT / ".cnb.yml").read_text()
    assert "deploy/daw deploy/compute" in cnb and "deploy/daw/deploy_via_tat.py" in cnb


def test_gpu_install_dry_run_writes_no_files(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "deploy/gpu/install.sh"),
            "--user",
            getpass.getuser(),
            "--python",
            sys.executable,
            "--daw",
            "ubuntu@daw.example",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        f"ExecStart={sys.executable}" in result.stdout
        and "run.py --serve --host 127.0.0.1 --port 18790" in result.stdout
    )
    assert "-R 127.0.0.1:18790:127.0.0.1:18790 ubuntu@daw.example" in result.stdout
    assert "ExitOnForwardFailure=yes" in result.stdout
    # asr-funasr 1.4: the modules run.py imports and the bundled weights go along.
    assert "overlap.py" in result.stdout and "weights/segmentation-community-1.safetensors" in result.stdout
    missing = subprocess.run(["bash", str(ROOT / "deploy/gpu/install.sh"), "--dry-run"], capture_output=True, text=True)
    assert missing.returncode == 2 and "--user" in missing.stderr


def test_gpu_install_adds_the_embedding_service_to_the_same_tunnel(tmp_path: Path) -> None:
    model = tmp_path / "bge-m3"
    model.mkdir()
    (model / "config.json").write_text("{}")
    command = ["bash", str(ROOT / "deploy/gpu/install.sh"), "--user", getpass.getuser(), "--python", sys.executable]
    command += ["--daw", "ubuntu@daw.example", "--embed-model", str(model), "--dry-run"]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    assert f"embed.py --model {model} --host 127.0.0.1 --port 18791" in result.stdout
    assert "-R 127.0.0.1:18790:127.0.0.1:18790 -R 127.0.0.1:18791:127.0.0.1:18791 ubuntu@daw.example" in result.stdout
    assert "After=network-online.target twin-asr.service twin-embed.service" in result.stdout
    command[command.index(str(model))] = str(tmp_path / "missing")
    missing = subprocess.run(command, capture_output=True, text=True)
    assert missing.returncode == 2 and "不是模型目录" in missing.stderr


@pytest.fixture
def embed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gpu_embed", ROOT / "deploy/gpu/embed.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embedding_passes_bound_padded_tokens(embed: ModuleType) -> None:
    assert embed.passes([10, 5000, 30, 9000], budget=10000) == [[3], [1, 2], [0]]
    groups = embed.passes([100] * 250, budget=16384)
    assert [len(g) for g in groups] == [163, 87] and sorted(i for g in groups for i in g) == list(range(250))
    assert embed.passes([]) == []


def test_embedding_requests_follow_the_openai_shape(embed: ModuleType) -> None:
    import json
    import threading
    import urllib.request

    seen: list[list[str]] = []

    def encode(texts: list[str]) -> list[list[float]]:
        seen.append(texts)
        return [[1.0, 0.0] for _ in texts]

    status, body = embed.embeddings(encode, "BAAI/bge-m3", {"model": "BAAI/bge-m3", "input": ["你好", ""]})
    assert status == 200 and [d["index"] for d in body["data"]] == [0, 1] and seen == [["你好", " "]]
    assert embed.embeddings(encode, "m", {"input": "单条"})[1]["data"][0]["embedding"] == [1.0, 0.0]
    for bad in ({"input": []}, {"input": [1]}, {"input": ["x"] * 257}, {"input": "x", "encoding_format": "int8"}, []):
        assert embed.embeddings(encode, "m", bad)[0] == 400

    # twin's own client, which asks for base64, reads the same vectors back.
    from twin.embed import OpenAICompatEmbedder

    server = embed.serve(encode, "BAAI/bge-m3", "127.0.0.1", 0, "cpu")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert json.load(urllib.request.urlopen(f"{base}/health"))["model"] == "BAAI/bge-m3"
        request = urllib.request.Request(
            f"{base}/v1/embeddings", data=json.dumps({"input": ["a"]}).encode(), method="POST"
        )
        assert json.load(urllib.request.urlopen(request))["data"][0]["embedding"] == [1.0, 0.0]
        client = OpenAICompatEmbedder("BAAI/bge-m3", base_url=f"{base}/v1", api_key_env="TWIN_TEST_UNSET_KEY")
        assert client.embed(["甲", "乙"]).tolist() == [[1.0, 0.0], [1.0, 0.0]]
    finally:
        server.shutdown()


def test_release_archive_names_its_commit(tmp_path: Path) -> None:
    """The deploy job's `git archive` fills src/twin/web/RELEASE in, which the web page then reports to check_live."""
    work = tmp_path / "work"
    (work / "src/twin/web").mkdir(parents=True)
    for name in (".gitattributes", "src/twin/web/RELEASE"):
        (work / name).write_bytes((ROOT / name).read_bytes())
    run = {"cwd": work, "check": True, "capture_output": True}
    subprocess.run(["git", "init", "-q"], **run)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A"], **run)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "r"], **run)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], **run).stdout.decode().strip()
    archive = subprocess.run(["git", "archive", "HEAD", "--", "src"], **run).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        member = tar.extractfile("src/twin/web/RELEASE")
        assert member and member.read().decode().strip() == commit
    cnb = (ROOT / ".cnb.yml").read_text()
    assert "git archive --format=tar.gz --output=/tmp/twin-release.tar.gz HEAD" in cnb
    assert 'deploy/daw/check_live.py "$CNB_COMMIT"' in cnb


def test_check_live_is_red_until_daw_runs_the_release(tmp_path: Path) -> None:
    import http.server
    import threading

    serving: dict[str, str] = {}

    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            for name, value in serving.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(b"<title>twin</title>")

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    check = [sys.executable, str(DAW / "check_live.py"), "a" * 40, "--url", url, "--attempts", "2", "--interval", "0"]
    try:
        missing = subprocess.run(check, capture_output=True, text=True)
        assert missing.returncode != 0 and "没有 X-Twin-Release" in missing.stderr
        serving["X-Twin-Release"] = "b" * 40
        old = subprocess.run(check, capture_output=True, text=True)
        assert old.returncode != 0 and "b" * 40 in old.stderr
        serving["X-Twin-Release"] = "a" * 40
        assert "已切换" in subprocess.run(check, capture_output=True, text=True, check=True).stdout
    finally:
        server.shutdown()
    down = subprocess.run([*check[:3], "--url", url, "--attempts", "1"], capture_output=True, text=True)
    assert down.returncode != 0 and "无法访问" in down.stderr
