"""Offline registry, request, media and background-job isolation contracts."""

from __future__ import annotations

import io
import json
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from twin.assets import AssetStore
from twin.config import AvatarSettings, Settings, TTSSettings, VideoSettings, make_video_synthesizer
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.ingest import Segment
from twin.media.schema import MediaScript, VideoResult, VoiceSpec
from twin.media.tts import MediaUnavailable, SilentSynthesizer
from twin.persona.items import PersonaItem
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import JobConflict, JobManager, PersonaProcessing, describe_error
from twin.web.personas import Personas

CSRF = {"X-Twin": "1"}
MEDIA = {
    "kind": "chat_reply",
    "answer": {
        "reply": "这是测试回答。",
        "citations": [],
        "confidence": 0.5,
        "abstain": False,
        "abstain_reason": "",
        "retrieved_ids": [],
    },
}


def headers(persona_id: str) -> dict[str, str]:
    return {**CSRF, "X-Twin-Persona": persona_id}


def create(web: TestClient, name: str = "另一个人") -> str:
    response = web.post("/api/personas", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    app = create_app(
        Settings(db_path=tmp_path / "old-name.db", target_name="原主人"),
        llm_factory=lambda: FakeLLM(
            lambda *_: {
                "reply": "测试回复",
                "mode": "general",
                "citations": [],
                "confidence": 0.5,
            }
        ),
        embedder_factory=HashingEmbedder,
    )
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def registry(web: TestClient) -> Personas:
    return web.app.state.personas  # type: ignore[union-attr,no-any-return]


def test_registry_and_default_paths_remain_unchanged(web: TestClient, tmp_path: Path) -> None:
    resolved = registry(web).settings_for("default")
    assert resolved.db_path == tmp_path / "old-name.db"
    for folder in ("assets", "media-cache", "media-sources", "uploads"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "sentinel").write_text("original")
    entries = web.get("/api/personas").json()
    assert entries[0] == {
        "id": "default",
        "owner": None,
        "name": "原主人",
        "avatar_url": None,
        "sources": 0,
        "created_at": entries[0]["created_at"],
        "is_default": True,
    }
    persona = create(web)
    assert re.fullmatch(r"p-[0-9a-f]{10}", persona)
    settings = registry(web).settings_for(persona)
    assert settings.db_path == tmp_path / "personas" / persona / "twin.db"
    assert settings.db_path.is_file()
    assert settings.db_path.parent.stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "personas.json").stat().st_mode & 0o777 == 0o600
    assert "另一个人" not in (tmp_path / "personas.json").read_text()
    assert web.get("/api/identity", headers=headers(persona)).json()["onboarding_pending"]
    web.post("/api/identity/onboarding-complete", headers=headers(persona))
    assert not web.get("/api/identity", headers=headers(persona)).json().get("onboarding_pending")
    changed = web.put("/api/identity", json={"name": "改名", "about": ""}, headers=headers(persona))
    assert changed.json()["name"] == "改名"
    assert web.get("/api/personas").json()[1]["name"] == "改名"
    with TestClient(create_app(resolved), base_url="http://localhost") as reopened:
        assert reopened.get("/api/personas").json()[1]["name"] == "改名"
    assert web.delete("/api/personas/default", headers=CSRF).status_code == 400
    assert web.delete(f"/api/personas/{persona}", headers=CSRF).json() == {"deleted": True}
    assert not settings.db_path.parent.exists()
    assert len(web.get("/api/personas").json()) == 1
    for folder in ("assets", "media-cache", "media-sources", "uploads"):
        assert (tmp_path / folder / "sentinel").read_text() == "original"
    assert json.loads((tmp_path / "personas.json").read_text())["default"] == "default"


@pytest.mark.parametrize("name", ["", "  ", "字" * 21])
def test_registry_name_validation(web: TestClient, name: str) -> None:
    assert web.post("/api/personas", json={"name": name}, headers=CSRF).status_code == 400
    assert len(web.get("/api/personas").json()) == 1


@pytest.mark.parametrize(
    "path",
    [
        "/api/status",
        "/api/identity",
        "/api/persona/sources",
        "/api/persona/processing",
        "/api/me/assets",
        "/api/media/capabilities",
        "/api/uploads/abc",
        "/api/personas",
    ],
)
def test_unknown_persona_is_not_default(web: TestClient, path: str) -> None:
    for url, selected in [(path, headers("missing")), (path + "?persona=missing", CSRF)]:
        response = web.get(url, headers=selected)
        assert response.status_code == 404
        assert response.json() == {"detail": "分身不存在"}
        assert response.headers["x-content-type-options"] == "nosniff"
    with pytest.raises(HTTPException, match="分身不存在"):
        registry(web).settings_for("../outside")


def test_identity_memories_and_questionnaire_are_isolated(web: TestClient) -> None:
    a, b = create(web, "甲"), create(web, "乙")
    note = web.post("/api/persona/notes", json={"text": "甲的独有记忆"}, headers=headers(a)).json()
    source_id = note["source_id"]
    assert len(web.get("/api/persona/sources", headers=headers(a)).json()) == 1
    assert web.get("/api/persona/sources", headers=headers(b)).json() == []
    assert web.get("/api/persona/sources").json() == []
    assert web.get(f"/api/persona/sources/{source_id}/text", headers=headers(b)).status_code == 404
    assert web.get("/api/identity?persona=" + a).json()["name"] == "甲"
    assert web.get("/api/identity?persona=" + a, headers=headers(b)).json()["name"] == "乙"
    assert web.get("/api/identity?persona=").status_code == 404
    assert web.delete(f"/api/persona/sources/{source_id}", headers=headers(b)).status_code == 404
    with PersonaStore(registry(web).settings_for(a).db_path) as store:
        assert store.list_expressions()[0].speaker == "甲"
    body = {"round": "initial", "answers": {"q01": "甲的答案"}}
    assert web.put("/api/persona/questionnaire/draft", json=body, headers=headers(a)).status_code == 200
    assert web.get("/api/persona/questionnaire", headers=headers(b)).json()["answers"] == {}


def test_portrait_voice_and_media_cache_isolation(web: TestClient) -> None:
    a, b = create(web, "甲"), create(web, "乙")
    picture = io.BytesIO()
    Image.new("RGB", (600, 800), "red").save(picture, format="PNG")
    assert (
        web.put("/api/me/portrait", files={"file": ("face.png", picture.getvalue())}, headers=headers(a)).status_code
        == 200
    )
    path = registry(web).settings_for(a).db_path
    AssetStore(path).save("voice", b"own reference", 6)
    assert web.get("/api/media/avatar-image?persona=" + a).status_code == 200
    assert web.get("/api/me/voice/reference?persona=" + a).content == b"own reference"
    for selected in (b, "default"):
        assert web.get("/api/me/assets", headers=headers(selected)).json()["portrait"] is None
        assert web.get("/api/media/avatar-image?persona=" + selected).status_code == 404
        assert web.get("/api/me/voice/reference?persona=" + selected).status_code == 404
    audio = web.post("/api/media/audio", json=MEDIA, headers=headers(a))
    assert audio.status_code == 200, audio.text
    url = audio.json()["segments"][0]["url"]
    assert web.get(url + "?persona=" + a).status_code == 200
    assert web.get(url + "?persona=" + b).status_code == 404
    assert web.get(url).status_code == 404
    assert web.get("/api/personas").json()[1]["avatar_url"].endswith("persona=" + a)


def test_non_default_fallbacks_and_preset_voice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def speech(config: TTSSettings) -> SilentSynthesizer:
        synth = SilentSynthesizer()
        synth.voice = VoiceSpec(voice_id=config.voice)
        synth.capabilities = synth.capabilities.model_copy(update={"voices": None})
        return synth

    monkeypatch.setattr("twin.web.media.make_synthesizer", speech)
    picture = tmp_path / "owner.png"
    Image.new("RGB", (600, 800), "red").save(picture)
    settings = Settings(
        db_path=tmp_path / "twin.db",
        avatar=AvatarSettings(image_path=str(picture)),
        tts=TTSSettings(voice="preset", voice_dir=tmp_path / "voices"),
        video=VideoSettings(provider="remote", command="unused"),
    )
    AssetStore(settings.db_path).save("voice", b"owner reference", 6)
    with TestClient(create_app(settings), base_url="http://localhost") as web:
        persona = create(web)
        resolved = registry(web).settings_for(persona)
        assert resolved.avatar.image_path is None and settings.avatar.image_path is not None
        assert resolved.video.require_assets and not settings.video.require_assets
        with pytest.raises(MediaUnavailable, match="上传形象和声音"):
            make_video_synthesizer(resolved)
        assert resolved.tts.voice == "preset"
        assert web.get("/api/media/avatar-image").status_code == 200
        assert web.get("/api/media/capabilities").json()["video"]["available"]
        capabilities = web.get("/api/media/capabilities", headers=headers(persona)).json()
        assert capabilities["avatar_image"] is None
        assert capabilities["video"] == {"available": False, "reason": "先在「关于你」上传形象和声音"}
        assert web.post("/api/media/video", json=MEDIA, headers=headers(persona)).status_code == 503
        audio = web.post("/api/media/audio", json=MEDIA, headers=headers(persona)).json()
        assert audio["manifest"]["voice"]["voice_id"] == "preset"
        assets = AssetStore(resolved.db_path)
        assets.save("portrait", picture.read_bytes())
        assert not web.get("/api/media/capabilities", headers=headers(persona)).json()["video"]["available"]
        assets.save("voice", b"other reference", 6)
        assert web.get("/api/media/capabilities", headers=headers(persona)).json()["video"]["available"]
        assert (
            web.post("/api/media/audio", json=MEDIA, headers=headers(persona)).json()["manifest"]["voice"]["voice_id"]
            != "preset"
        )
        default_audio = web.post("/api/media/audio", json=MEDIA, headers=CSRF)
        assert default_audio.status_code == 200, default_audio.text
        assert default_audio.json()["manifest"]["voice"]["voice_id"] != "preset"
        assert (
            default_audio.json()["manifest"]["voice"]["voice_id"]
            != web.post("/api/media/audio", json=MEDIA, headers=headers(persona)).json()["manifest"]["voice"][
                "voice_id"
            ]
        )
        assets.update("voice", None)
        assert (
            web.post("/api/media/audio", json=MEDIA, headers=headers(persona)).json()["manifest"]["voice"]["voice_id"]
            == "preset"
        )


def test_chat_history_and_jobs_are_attributed(web: TestClient) -> None:
    a, b = create(web, "甲"), create(web, "乙")
    for persona in (a, b):
        with PersonaStore(registry(web).settings_for(persona).db_path) as store:
            store.replace_facet_items(
                "2.1", [PersonaItem(item_id="same", facet_id="2.1", statement="测试", evidence=[])]
            )
    response = web.post(
        "/api/persona/chat", json={"messages": [{"role": "user", "content": "甲的问题"}]}, headers=headers(a)
    )
    job_id = response.json()["job_id"]
    assert registry(web).jobs.wait(job_id, 5)
    job = web.get(f"/api/jobs/{job_id}", headers=headers(a)).json()
    assert job["status"] == "done" and job["persona_id"] == a
    assert web.get(f"/api/jobs/{job_id}", headers=headers(b)).status_code == 404
    assert web.get("/api/jobs", headers=headers(b)).json() == []
    for persona, count in [(a, 1), (b, 0)]:
        with sqlite3.connect(registry(web).settings_for(persona).db_path) as db:
            assert db.execute("SELECT count(*) FROM p_chat_log").fetchone()[0] == count


def test_builds_share_capacity_without_sharing_status() -> None:
    jobs = JobManager(1, describe_error)
    release = threading.Event()
    a = PersonaProcessing(jobs.scoped("a"), lambda _: release.wait(5), lambda _: None, delay=0.01)
    b = PersonaProcessing(jobs.scoped("b"), lambda _: {"owner": "b"}, lambda _: None, delay=0.01)
    try:
        job = a.start()
        with pytest.raises(JobConflict):
            b.start()
        assert a.view()["state"] == "running"
        assert b.view()["state"] == "queued" and b.view()["job_id"] is None
        release.set()
        assert jobs.wait(job.job_id, 5)
        for _ in range(100):
            own = jobs.scoped("b").recent()
            if own and own[0]["status"] == "done":
                break
            time.sleep(0.01)
        assert own[0]["persona_id"] == "b" and own[0]["status"] == "done"
        assert b.view()["last_error"] is None
    finally:
        release.set()
        a.close()
        b.close()


def test_uploads_and_ingestion_jobs_keep_their_persona(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    release, started = threading.Event(), threading.Event()
    a, b = create(web, "甲"), create(web, "乙")

    class Transcriber:
        def transcribe(self, audio: Path, duration: float, progress: Any) -> list[Segment]:
            started.set()
            assert release.wait(5)
            progress(duration, duration)
            return [Segment(start=0, end=1, text="测试转写")]

    monkeypatch.setattr("twin.web.uploads.make_transcriber", lambda _: Transcriber())
    monkeypatch.setattr("twin.web.uploads.extract_audio", lambda path: (path.with_name("audio.wav"), 1, None))
    upload = web.post("/api/uploads", json={"filename": "test.mp3", "size": 4}, headers=headers(a)).json()["id"]
    assert web.get(f"/api/uploads/{upload}", headers=headers(b)).status_code == 404
    assert web.put(f"/api/uploads/{upload}?offset=0", content=b"data", headers=headers(a)).status_code == 200
    accepted = web.post(f"/api/uploads/{upload}/finish", headers=headers(a)).json()
    try:
        assert started.wait(2)
        assert web.delete(f"/api/personas/{a}", headers=CSRF).status_code == 409
        assert web.get("/api/jobs", headers=headers(b)).json() == []
        assert web.get("/api/persona/sources", headers=headers(b)).json() == []
        release.set()
        assert registry(web).jobs.wait(accepted["job_id"], 5)
        source = web.get("/api/persona/sources", headers=headers(a)).json()[0]
        assert source["media_status"] == "ready"
        assert "测试转写" in web.get(f"/api/persona/sources/{source['source_id']}/text", headers=headers(a)).text
        original = registry(web).settings_for(a).db_path.parent / "media-sources" / source["media_sha"] / "original.mp3"
        assert original.read_bytes() == b"data"
        assert original.parent.stat().st_mode & 0o777 == 0o700
        assert original.parent.parent.stat().st_mode & 0o777 == 0o700
        assert web.delete(f"/api/personas/{a}", headers=CSRF).status_code == 200
        assert not original.exists()
    finally:
        release.set()


def test_video_jobs_cannot_be_read_or_deleted_from_another_persona(
    web: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = create(web, "甲"), create(web, "乙")
    release = threading.Event()
    settings = registry(web).settings_for(a)
    AssetStore(settings.db_path).save("portrait", b"portrait")
    AssetStore(settings.db_path).save("voice", b"voice", 6)
    # Configure before lazily creating A's isolated media context.
    registry(web).settings.video = VideoSettings(provider="remote", command="unused")
    captured: list[Path] = []

    class Video:
        name = "test"

        def synthesize(self, script: MediaScript, out_path: Path) -> VideoResult:
            assert release.wait(5)
            out_path.write_bytes(b"private video")
            return VideoResult(output=out_path, duration_s=1, warnings=[])

    def factory(resolved: Settings) -> Video:
        captured.append(resolved.db_path)
        return Video()

    monkeypatch.setattr("twin.web.media.make_video_synthesizer", factory)
    result = web.post("/api/media/video", json=MEDIA, headers=headers(a))
    assert result.status_code == 200, result.text
    job_id = result.json()["job_id"]
    try:
        assert captured == [settings.db_path]
        assert web.get(f"/api/media/video/jobs/{job_id}", headers=headers(b)).status_code == 404
        assert web.delete(f"/api/personas/{a}", headers=CSRF).status_code == 409
        release.set()
        assert registry(web).jobs.wait(job_id, 5)
        result = web.get(f"/api/media/video/jobs/{job_id}", headers=headers(a)).json()["result"]
        assert web.get(f"/api/media/video/{result['file']}?persona={a}").content == b"private video"
        assert web.get(f"/api/media/video/{result['file']}?persona={b}").status_code == 404
    finally:
        release.set()


def test_video_asset_removal_race_never_selects_driver_defaults(
    web: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    persona = create(web)
    registry(web).settings.video = VideoSettings(provider="remote", command="unused")
    assets = AssetStore(registry(web).settings_for(persona).db_path)
    assets.save("portrait", b"own portrait")
    assets.save("voice", b"own voice", 6)

    def removed(resolved: Settings) -> Any:
        assets.update("portrait", None)
        return make_video_synthesizer(resolved)

    monkeypatch.setattr("twin.web.media.make_video_synthesizer", removed)
    response = web.post("/api/media/video", json=MEDIA, headers=headers(persona))
    assert response.status_code == 503
    assert response.json()["detail"] == "先在「关于你」上传形象和声音"
    assert web.get("/api/jobs", headers=headers(persona)).json() == []


@pytest.mark.parametrize("kind", ["persona_build", "chat", "video", "media_ingest"])
def test_delete_refuses_active_or_queued_jobs(web: TestClient, kind: Any) -> None:
    persona = create(web)
    release = threading.Event()
    jobs = registry(web).jobs.scoped(persona)
    job = jobs.submit(kind, "test", lambda _: release.wait(5))
    try:
        assert web.delete(f"/api/personas/{persona}", headers=CSRF).status_code == 409
        assert registry(web).settings_for(persona).db_path.exists()
        release.set()
        assert jobs.wait(job.job_id, 5)
        assert web.delete(f"/api/personas/{persona}", headers=CSRF).status_code == 200
    finally:
        release.set()
