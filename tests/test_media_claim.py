from __future__ import annotations

import io
import json
import math
import shlex
import struct
import time
import wave
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from twin.assets import AssetStore
from twin.config import ASRSettings, Settings, VisionSettings
from twin.egress import egress_status
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.claim import Analysis, analyse, intervals, sample_windows, vision_candidates, voice_windows
from twin.media.ingest import CommandTranscriber, Segment, Speaker
from twin.persona.profile import build_profile
from twin.persona.schema import Source, SourceKind
from twin.persona.sources import parse_media
from twin.persona.store import PersonaStore
from twin.web import create_app


def tone(seconds: int = 24) -> bytes:
    output = io.BytesIO()
    frames = b"".join(struct.pack("<h", int(8000 * math.sin(i * 2 * math.pi * 440 / 16000))) for i in range(16000))
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(frames * seconds)
    return output.getvalue()


def segments() -> list[Segment]:
    return [
        Segment(start=0, end=12, speaker="S1", text="我喜欢读书。"),
        Segment(start=12, end=24, speaker="S2", text="我喜欢散步。"),
    ]


@pytest.mark.parametrize(
    ("scores", "reference", "chosen"),
    [
        ([0.73, 0.5], True, "S1"),
        ([0.6, 0.5], True, "S1"),
        ([0.59, 0.2], True, None),
        ([0.7, 0.61], True, None),
        ([0.7, 0.7], True, None),
        ([0.9, 0.1], False, None),
        ([None, None], True, None),
        ([0.8, None], True, None),
        ([0.2, 0.8], True, "S2"),
    ],
)
def test_auto_pick(scores: list[float | None], reference: bool, chosen: str | None) -> None:
    analysis = analyse(
        segments(), [Speaker(id=f"S{i + 1}", seconds=12, similarity=score) for i, score in enumerate(scores)], reference
    )
    assert analysis.speaker == chosen
    assert analysis.confirmed == (chosen is not None)
    single = analyse(segments()[:1], [], False)
    assert single.confirmed and single.speaker == "S1"


def test_command_diarization_contract(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(tone(1))
    reference = tmp_path / "reference.wav"
    reference.write_bytes(tone(1))
    script = tmp_path / "driver.py"
    script.write_text(
        'import json,sys\nr=json.load(sys.stdin)\nassert r["diarize"] is True\nassert r["reference"] == '
        + repr(str(reference.resolve()))
        + '\nprint("log")\nprint(json.dumps('
        + repr(
            {
                "ok": True,
                "segments": [s.model_dump() for s in segments()],
                "speakers": [
                    {"id": "S1", "seconds": 12, "similarity": 0.73},
                    {"id": "S2", "seconds": 12, "similarity": None},
                ],
            }
        )
        + "))\n"
    )
    transcriber = CommandTranscriber(f"python3 {shlex.quote(str(script))}")
    transcriber.diarize, transcriber.reference = True, reference
    assert transcriber.transcribe(audio, 24, lambda *_: None) == segments()
    assert transcriber.speakers[0].similarity == 0.73
    assert transcriber.speakers[1].similarity is None
    legacy = CommandTranscriber('echo \'{"ok":true,"segments":[{"start":0,"end":1,"text":"旧驱动"}]}\'')
    assert legacy.transcribe(audio, 1, lambda *_: None)[0].speaker == "S1"
    assert legacy.speakers == []
    for speakers in [
        [{"id": "S1", "seconds": 1, "similarity": 2}],
        [{"id": "S1", "seconds": -1}],
        [{"id": "S1", "seconds": 1}] * 2,
    ]:
        payload = {"ok": True, "segments": [segments()[0].model_dump()], "speakers": speakers}
        with pytest.raises(RuntimeError, match="语音识别失败"):
            CommandTranscriber("echo " + shlex.quote(json.dumps(payload))).transcribe(audio, 1, lambda *_: None)


def source() -> Source:
    return Source(
        source_id="s",
        kind=SourceKind.AUDIO,
        title="录音",
        origin="a.wav",
        imported_at="now",
        n_expressions=0,
        n_target=0,
        media_status="needs_speaker",
        text_state="raw",
    )


def test_attribution_and_build_gate(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", pseudonymize_others=False)
    analysis = analyse(segments(), [], False)
    analysis.speaker, analysis.confirmed = "S2", True
    parsed = parse_media(source(), analysis.lines("本人"))
    assert parsed.source.n_target == 1 and parsed.source.n_expressions == 2
    assert parsed.expressions[0].speaker == "其他人1" and not parsed.expressions[0].is_target
    assert parsed.expressions[1].speaker == "本人" and parsed.expressions[1].is_target
    assert "我喜欢读书" in parsed.expressions[1].context
    with PersonaStore(settings.db_path) as store:
        # Even a previously attributed source must not build while awaiting a new decision.
        store.put_source(parsed)
        report = build_profile(store, FakeLLM(lambda *_: pytest.fail("unconfirmed source sent to model")), settings)
        assert report.sources == 0 and report.chunks_total == 0
        analysis.speaker = None
        observers = parse_media(source().model_copy(update={"media_status": "ready"}), analysis.lines("本人"))
        store.put_source(observers)
        assert observers.source.n_target == 0
        assert all(not e.is_target for e in store.list_expressions())


def test_voice_window_merging_overlap_length_and_samples(tmp_path: Path) -> None:
    analysis = analyse(
        [
            Segment(start=0, end=6, text="a"),
            Segment(start=6.5, end=15, text="b"),
            Segment(start=10, end=12, text="other", speaker="S2"),
            Segment(start=20, end=50, text="c"),
            Segment(start=60, end=68, text="d"),
        ],
        [],
        False,
    )
    analysis.speaker = "S1"
    assert intervals(analysis, "S1") == [(0, 10), (12, 15), (20, 50), (60, 68)]
    windows = voice_windows(analysis)
    assert len(windows) == 3 and windows[0][1] - windows[0][0] == pytest.approx(20)
    assert all(8 - 1e-9 <= end - start <= 20 + 1e-9 for start, end in windows)
    assert all(not (start < 12 and end > 10) for start, end in windows)
    assert len(sample_windows(analysis, "S1")) == 3
    assert all(end - start == 5 for start, end in sample_windows(analysis, "S1"))
    audio = tmp_path / "short.wav"
    audio.write_bytes(tone(4))
    assert voice_windows(analysis, audio) == []
    analysis.speaker = None
    assert voice_windows(analysis) == []


@pytest.mark.parametrize("attack", ["outside", "symlink", "parent_symlink", "invalid_image", "valid"])
def test_vision_contract(tmp_path: Path, attack: str) -> None:
    folder = tmp_path / "media"
    folder.mkdir()
    image = tmp_path / "outside.png"
    Image.new("RGB", (1600, 2000), "red").save(image)
    script = tmp_path / "vision.py"
    script.write_text(
        "import json,sys,pathlib,shutil\nr=json.load(sys.stdin)\n"
        'assert pathlib.Path(r["video"]).is_absolute()\nassert r["intervals"] == [[0.0,12.0]]\n'
        'assert r["max_candidates"] == 6\nout=pathlib.Path(r["out_dir"])\np=out/"face.png"\nattack='
        + repr(attack)
        + "\nsource=pathlib.Path("
        + repr(str(image))
        + ')\nif attack=="outside": p=source\nelif attack=="symlink": p.symlink_to(source)\n'
        'elif attack=="parent_symlink":\n'
        ' (out/"link").symlink_to(source.parent, target_is_directory=True); p=out/"link"/source.name\n'
        'elif attack=="invalid_image": p.write_text("not image")\nelse: shutil.copyfile(source,p)\nprint("log")\n'
        'print(json.dumps({"ok":True,"candidates":[{"time":1.5,"image":str(p),'
        '"score":0.83,"face_box":[0.2,0.1,0.4,0.4]}]}))\n'
    )
    analysis = analyse(segments()[:1], [], False)
    settings = VisionSettings(command=f"python3 {shlex.quote(str(script))}")
    if attack != "valid":
        with pytest.raises((ValueError, OSError)):
            vision_candidates(analysis, tmp_path / "video.mp4", folder, settings)
        assert not list(folder.glob("*-portrait-*.png"))
    else:
        candidates = vision_candidates(analysis, tmp_path / "video.mp4", folder, settings)
        assert len(candidates) == 1 and candidates[0].start == 1.5
        path = folder / candidates[0].file
        with Image.open(path) as saved:
            assert max(saved.size) <= 1024 and not saved.info
        assert path.stat().st_mode & 0o777 == 0o600
    assert vision_candidates(analysis, tmp_path / "video.mp4", folder, VisionSettings()) == []
    assert (
        egress_status(Settings(vision=settings.model_copy(update={"egress": "external"})), external_only=True)[-1][
            "kind"
        ]
        == "vision"
    )


def test_voice_window_prefers_loud_consistent_audio(tmp_path: Path) -> None:
    analysis = analyse([Segment(start=0, end=20, text="quiet"), Segment(start=25, end=45, text="loud")], [], False)
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(struct.pack("<h", 500) * (25 * 16000) + struct.pack("<h", 8000) * (20 * 16000))
    assert voice_windows(analysis, path)[0][0] == pytest.approx(25.2)


@pytest.mark.parametrize("with_reference", [False, True])
def test_ingestion_sends_diarization_and_persona_reference(tmp_path: Path, with_reference: bool) -> None:
    payload = {
        "ok": True,
        "segments": [s.model_dump() for s in segments()],
        "speakers": [{"id": "S1", "seconds": 12, "similarity": 0.73}, {"id": "S2", "seconds": 12, "similarity": 0.5}],
    }
    reference = None
    if with_reference:
        assets = AssetStore(tmp_path / "twin.db")
        assets.save("voice", tone(), 24)
        reference = str(assets.path("voice"))
    driver = tmp_path / "asr.py"
    driver.write_text(
        "import json,sys,pathlib\nr=json.load(sys.stdin)\n"
        'assert r["diarize"] is True\nassert pathlib.Path(r["audio"]).is_absolute()\n'
        f'assert r.get("reference") == {reference!r}\nprint("log")\n'
        f"print(json.dumps({payload!r}))\n"
    )
    settings = Settings(
        db_path=tmp_path / "twin.db", asr=ASRSettings(provider="command", command=f"python3 {shlex.quote(str(driver))}")
    )
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        result = upload(client, tone())
        claim = client.get(f"/api/persona/sources/{result['source_id']}/speakers").json()
        assert claim["confirmed"] == with_reference
        assert claim["automatic"] == with_reference
        assert claim["speaker"] == ("S1" if with_reference else None)
        assert claim["speakers"][0]["suggested"] == with_reference
        assert claim["portraits"] == []
        analysis = Analysis.load(tmp_path / "media-sources" / result["media_sha"])
        assert analysis.speakers[0].similarity == 0.73 and analysis.segments[1].speaker == "S2"
        with PersonaStore(settings.db_path) as store:
            source = store.get_source(result["source_id"])
            assert source and source.media_status == ("ready" if with_reference else "needs_speaker")
            assert source.n_target == int(with_reference)


def wait_job(client: TestClient, job_id: str, persona: str = "default") -> dict[str, Any]:
    for _ in range(300):
        job = client.get(f"/api/jobs/{job_id}?persona={persona}").json()
        if job["status"] in {"done", "failed"}:
            assert job["status"] == "done", job
            return dict(job)
        time.sleep(0.02)
    raise AssertionError("job timeout")


def wait_processing(client: TestClient) -> None:
    for _ in range(300):
        if client.get("/api/persona/processing").json()["state"] == "idle":
            return
        time.sleep(0.02)
    raise AssertionError("processing timeout")


def upload(client: TestClient, data: bytes, persona: str = "default") -> dict[str, Any]:
    headers = {"X-Twin": "1", "X-Twin-Persona": persona}
    info = client.post("/api/uploads", json={"filename": "录音.mp4", "size": len(data)}, headers=headers).json()
    assert client.put(f"/api/uploads/{info['id']}?offset=0", content=data, headers=headers).status_code == 200
    result = client.post(f"/api/uploads/{info['id']}/finish", headers=headers).json()
    wait_job(client, result["job_id"], persona)
    return dict(result)


def test_confirm_rebuild_adopt_and_persona_media_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "face.png"
    Image.new("RGB", (800, 1000), "red").save(image)
    driver = tmp_path / "vision.py"
    driver.write_text(
        "import json,sys,pathlib,shutil\nr=json.load(sys.stdin)\n"
        'p=pathlib.Path(r["out_dir"])/"face.png"\nshutil.copyfile('
        + repr(str(image))
        + ',p)\nprint(json.dumps({"ok":True,"candidates":[{"time":2,"image":str(p),'
        '"score":0.8,"face_box":[0.2,0.1,0.4,0.4]}]}))'
    )
    settings = Settings(
        db_path=tmp_path / "twin.db", vision=VisionSettings(command=f"python3 {shlex.quote(str(driver))}")
    )
    builds: list[list[bool]] = []

    def build(settings: Settings, *args: Any) -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            builds.append([e.is_target for e in store.list_expressions()])
        return {"failures": []}

    monkeypatch.setattr("twin.web.persona.run_persona_build", build)

    class Transcriber:
        def transcribe(self, audio: Path, duration: float, progress: Any) -> list[Segment]:
            return segments()

    monkeypatch.setattr("twin.web.uploads.make_transcriber", lambda _: Transcriber())
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        data = tone()
        result = upload(client, data)
        sid = result["source_id"]
        base = f"/api/persona/sources/{sid}"
        assert not builds
        row = client.get("/api/persona/sources").json()[0]
        assert row["status"] == "needs_speaker" and row["n_target"] == 0
        initial = client.get(base + "/speakers").json()
        assert not initial["confirmed"] and len(initial["speakers"]) == 2
        assert len(initial["speakers"][0]["samples"]) == 3
        sample = initial["speakers"][0]["samples"][0]
        assert client.get(sample + "&persona=default").headers["content-type"] == "audio/wav"
        assert client.put(base + "/speaker", json={"speaker": "missing"}, headers={"X-Twin": "1"}).status_code == 400
        assert client.put(base + "/speaker", json={"speaker": "S1"}).status_code == 403
        chosen = client.put(base + "/speaker", json={"speaker": "S1"}, headers={"X-Twin": "1"}).json()
        wait_job(client, chosen["job_id"])
        wait_processing(client)
        claim = client.get(base + "/speakers").json()
        assert claim["confirmed"] and claim["speaker"] == "S1" and not claim["automatic"]
        assert len(claim["voices"]) == len(claim["portraits"]) == 1 and not claim["pending"]
        text = client.get(base + "/text").text
        assert "本人：[00:00] 我喜欢读书" in text and "其他人1：[00:12] 我喜欢散步" in text
        row = client.get("/api/persona/sources").json()[0]
        assert row["n_target"] == 1 and row["expressions_others"] == 1
        for kind, plural in [("voice", "voices"), ("portrait", "portraits")]:
            candidate = claim[plural][0]
            assert client.get(candidate["url"] + "?persona=default").status_code == 200
            response = client.post(
                base + f"/adopt-{kind}", json={"candidate": candidate["id"]}, headers={"X-Twin": "1"}
            )
            assert response.status_code == 200, response.text
            assert response.json()[kind] is not None
        assets = AssetStore(settings.db_path)
        with wave.open(str(assets.path("voice"))) as wav:
            assert wav.getframerate() == 24000 and wav.getnchannels() == 1
        with Image.open(assets.path("portrait")) as photo:
            assert abs(photo.width / photo.height - 0.75) < 0.01 and not photo.info
        persona = client.post("/api/personas", json={"name": "另一位"}, headers={"X-Twin": "1"}).json()["id"]
        assert client.get(base + f"/speakers?persona={persona}").status_code == 404
        assert client.get(sample + f"&persona={persona}").status_code == 404
        other = upload(client, data, persona)
        assert other["source_id"] == sid
        assert client.get(base + f"/speakers?persona={persona}").json()["confirmed"] is False
        candidate = claim["voices"][0]
        assert client.get(candidate["url"] + f"?persona={persona}").status_code == 404
        assert (
            client.post(
                base + "/adopt-voice",
                json={"candidate": candidate["id"]},
                headers={"X-Twin": "1", "X-Twin-Persona": persona},
            ).status_code
            == 409
        )
        assert client.get(f"/api/me/assets?persona={persona}").json()["voice"] is None
        changed = client.put(base + "/speaker", json={"speaker": "S2"}, headers={"X-Twin": "1"}).json()
        wait_job(client, changed["job_id"])
        wait_processing(client)
        with PersonaStore(settings.db_path) as store:
            expressions = store.list_expressions(source_id=sid)
            assert [e.is_target for e in expressions] == [False, True]
            assert "我喜欢读书" in expressions[1].context
        assert client.get(candidate["url"]).status_code == 404
        assert client.get(sample).status_code == 404
        observer = client.put(base + "/speaker", json={"speaker": None}, headers={"X-Twin": "1"}).json()
        wait_job(client, observer["job_id"])
        assert client.get(base + "/speakers").json()["voices"] == []
        assert client.get("/api/persona/sources").json()[0]["n_target"] == 0
        wait_processing(client)
        assert [True, False] in builds and [False, True] in builds and [False, False] in builds
