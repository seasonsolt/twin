"""The recording library's proofreading by the language model, and the batch quota on what the library spends."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from test_library import FakeTranscriber, needs_ffmpeg, settled, upload, wav_bytes
from test_team import decide, meeting, until, wanted_done

from twin.config import ASRSettings, LibrarySettings, Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.clean import Edits
from twin.media.library import Cleaned, Library
from twin.media.team import Team
from twin.persona.store import PersonaStore
from twin.usage import CallRow, attempt, model_tokens, tracked
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

HEADERS = {"X-Twin": "1"}
# What the speech recognizer heard, and what the model corrects it to.
HEARD, MEANT = "我反对牙缩研发。", "我反对压缩研发。"


def misheard(library: Library) -> str:
    recording_id = meeting(library)
    transcript = library.transcript(library.get(recording_id))  # type: ignore[arg-type]
    assert transcript is not None
    segments = [s.model_copy(update={"text": HEARD}) if s.text == MEANT else s for s in transcript.segments]
    path = library.folder(recording_id) / f"transcript-{transcript.id}.json"
    path.write_text(json.dumps(transcript.model_copy(update={"segments": segments}).model_dump(mode="json")))
    return recording_id


def corrected(library: Library, recording_id: str, **changes: Any) -> Cleaned:
    recording = library.get(recording_id)
    transcript = library.transcript(recording) if recording else None
    assert transcript is not None
    segments = [s.model_copy(update={"text": MEANT}) if s.text == HEARD else s for s in transcript.segments]
    return Cleaned(transcript_id=transcript.id, created_at="2026-10-17T00:00:00+00:00", changed=1, segments=segments)


# ------------------------------------------------------------------ library and team


def test_proofreading_waits_until_someone_in_the_recording_is_confirmed(tmp_path: Path) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    rec = misheard(library)
    assert library.unproofread() == ()
    zhang = team.add_person("张总").id
    decide(team, rec, "S2", "reject", zhang)
    assert library.unproofread() == ()
    decide(team, rec, "S2", "confirm", zhang)
    assert [r.id for r in library.unproofread()] == [rec]
    transcript_id = library.get(rec).transcript_id  # type: ignore[union-attr]
    assert team.proofread(rec, transcript_id, changed=False)  # type: ignore[arg-type]
    assert library.unproofread() == ()
    assert not team.proofread(rec, "another-transcript", changed=False)


def test_a_filed_proofreading_is_never_rewritten(tmp_path: Path) -> None:
    library = Library(tmp_path / "library")
    rec = misheard(library)
    recording = library.get(rec)
    assert recording is not None
    assert library.write_cleaned(recording, corrected(library, rec)) is True
    path = library.clean_path(recording)
    assert path is not None
    before = (path.stat().st_ino, path.read_bytes())
    other = corrected(library, rec)
    other.segments[2] = other.segments[2].model_copy(update={"text": "别的字。"})
    assert library.write_cleaned(recording, other) is False
    assert (path.stat().st_ino, path.read_bytes()) == before
    assert [p.name for p in library.folder(rec).iterdir() if p.name.startswith(".")] == []
    assert [s.text for s in library.cleaned(recording).segments][2] == MEANT  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "change",
    [
        lambda segments: segments[:-1],
        lambda segments: [segments[0].model_copy(update={"speaker": "S2"}), *segments[1:]],
        lambda segments: [segments[0].model_copy(update={"end": 5}), *segments[1:]],
    ],
    ids=["a segment fewer", "another speaker", "other times"],
)
def test_proofreading_that_does_not_match_the_transcript_is_dropped(tmp_path: Path, change: Any) -> None:
    library = Library(tmp_path / "library")
    rec = misheard(library)
    recording = library.get(rec)
    assert recording is not None
    clean = corrected(library, rec)
    broken = clean.model_copy(update={"segments": change(clean.segments)})
    with pytest.raises(ValueError):
        library.write_cleaned(recording, broken)
    # A file that went wrong some other way is read as nothing: the twin keeps the recognized words.
    path = library.clean_path(recording)
    assert path is not None
    path.write_text(broken.model_dump_json())
    assert library.cleaned(recording) == library.transcript(recording)
    team = Team(library)
    zhang = team.add_person("张总").id
    decide(team, rec, "S2", "confirm", zhang)
    assert [line for _, line, own in team.sources(zhang, "张总")[0].lines if own and line] == [f"[00:06] {HEARD}"]


def test_twin_sources_read_the_proofread_words_and_proofreading_reopens_them(tmp_path: Path) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    rec = misheard(library)
    zhang, li = team.add_person("张总").id, team.add_person("李总").id
    decide(team, rec, "S2", "confirm", zhang)
    decide(team, rec, "S1", "confirm", li)
    team.link(zhang, "p_zhang")
    team.link(li, "p_li")
    before = team.sources(zhang, "张总")[0]
    recording = library.get(rec)
    assert recording is not None and recording.transcript_id is not None
    assert library.write_cleaned(recording, corrected(library, rec))
    assert team.proofread(rec, recording.transcript_id, changed=True)
    # Everyone identified in the recording waits for a rebuild, which reads the corrected words.
    assert wanted_done(library, "p_zhang") == (2, 0) and wanted_done(library, "p_li") == (2, 0)
    after = team.sources(zhang, "张总")[0]
    assert after.source_id == before.source_id
    assert [line for _, line, own in after.lines if own and line] == [f"[00:06] {MEANT}"]


def test_model_tokens_leave_embeddings_out_and_count_unreported_usage_by_characters() -> None:
    rows = [
        CallRow("x", "openai_compat", "m", "", input_tokens=100, output_tokens=20),
        CallRow("x", "openai_compat_embed", "e", "", input_tokens=500),
        CallRow("x", "openai_compat", "m", "", characters=300, unknown_usage_attempts=1),
        CallRow("x", "hashing", "h", "", input_tokens=0),
    ]
    assert model_tokens(rows) == 420


# ------------------------------------------------------------------ the web app


class Model(FakeLLM):
    """Corrects the misheard sentence when asked to proofread, extracts nothing otherwise, and reports one token
    per character sent, like a provider that does not report usage."""

    def __init__(self) -> None:
        super().__init__(self.answer)
        self.proofreads = 0
        self.lock = threading.Lock()

    def answer(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is not Edits:
            return {"items": []}
        with self.lock:
            self.proofreads += 1
        meeting = json.loads(user)["meeting"]
        return {"edits": [{"id": s["id"], "text": MEANT} for s in meeting if s["text"] == HEARD]}

    @tracked("counting")
    def structured(self, *, system: str, user: str, schema: type[Any], **options: Any) -> Any:
        unwrapped = FakeLLM.structured.__wrapped__  # type: ignore[attr-defined]
        return attempt(
            lambda: unwrapped(self, system=system, user=user, schema=schema, **options),
            characters=len(system) + len(user),
        )


@pytest.fixture
def model() -> Model:
    return Model()


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model: Model) -> Iterator[TestClient]:
    def soon(delay: float, fn: Any) -> threading.Timer:
        timer = threading.Timer(0.01, fn)
        timer.daemon = True
        timer.start()
        return timer

    FakeTranscriber.fail = False
    monkeypatch.setattr(PersonaProcessing, "_timer", staticmethod(soon))
    monkeypatch.setattr("twin.web.library.make_transcriber", lambda _: FakeTranscriber())
    settings = Settings(
        db_path=tmp_path / "twin.db",
        asr=ASRSettings(provider="command", command="unused"),
        library=LibrarySettings(headroom_gb=0, max_pending=3),
    )
    app = create_app(settings, llm_factory=lambda: model, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def library_of(tmp_path: Path) -> Library:
    return Library(tmp_path / "library" / "team")


def limit(web: TestClient, tokens: int) -> None:
    web.app.state.libraries.settings.library.batch_tokens = tokens  # type: ignore[attr-defined]


def confirm(web: TestClient, rec: str, speaker: str, **choice: Any) -> Any:
    detail = web.get(f"/api/library/recordings/{rec}").json()
    body = {"transcript_id": detail["transcript_id"], "revision": detail["revision"], "action": "confirm", **choice}
    put = web.put(f"/api/library/recordings/{rec}/speakers/{speaker}", json=body, headers=HEADERS)
    assert put.status_code == 200, put.text
    return put.json()


def own_words(tmp_path: Path, persona_id: str) -> list[str]:
    with PersonaStore(tmp_path / "personas" / persona_id / "twin.db") as store:
        return [e.text for e in store.list_expressions() if e.is_target]


def recording_state(web: TestClient, rec: str) -> str:
    return str(next(r for r in web.get("/api/library").json()["recordings"] if r["id"] == rec)["proofread"])


def open_twin(web: TestClient, persona_id: str) -> bool:
    return web.get("/api/status", headers={"X-Twin-Persona": persona_id}).json()["memory_updating"] is False


def spending(library: Library) -> dict[str, int]:
    with library.read() as db:
        return dict(db.execute("SELECT kind, SUM(tokens) FROM spending GROUP BY kind").fetchall())


def test_a_twin_is_rebuilt_from_the_proofread_words_once(web: TestClient, tmp_path: Path, model: Model) -> None:
    library = library_of(tmp_path)
    rec = misheard(library)
    assert recording_state(web, rec) == "" and model.proofreads == 0
    zhang = confirm(web, rec, "S2", new_person="张总")["person_id"]
    pid = web.post(f"/api/library/people/{zhang}/persona", headers=HEADERS).json()["persona_id"]
    until(lambda: recording_state(web, rec) == "done")
    until(lambda: open_twin(web, pid) and own_words(tmp_path, pid) == [f"[00:06] {MEANT}"])
    # A build's spending is recorded just after the twin opens.
    until(lambda: "rebuild" in spending(library))
    built = spending(library)["rebuild"]
    assert model.proofreads == 1
    detail = web.get(f"/api/library/recordings/{rec}").json()
    assert detail["proofread"] == "done" and detail["segments"][2]["text"] == MEANT
    recording = library.get(rec)
    assert recording is not None
    assert sorted(p.name for p in library.folder(rec).iterdir()) == [
        f"clean-{recording.transcript_id}.json",
        f"transcript-{recording.transcript_id}.json",
    ]
    # The transcript itself is as recognized; only the proofreading next to it has the correction.
    assert library.transcript(recording).segments[2].text == HEARD  # type: ignore[union-attr]

    # Another decision about the same recording does not proofread it again.
    confirm(web, rec, "S1", new_person="李总")
    until(lambda: open_twin(web, pid) and spending(library)["rebuild"] > built)
    web.get("/api/library")
    assert model.proofreads == 1
    spent = spending(library)
    assert spent["proofread"] > 0 and spent["rebuild"] > 0
    assert web.get("/api/library").json()["quota"]["used"] == sum(spent.values())


def test_a_spent_quota_holds_proofreading_and_rebuilds_and_says_so(
    web: TestClient, tmp_path: Path, model: Model
) -> None:
    library = library_of(tmp_path)
    rec = misheard(library)
    limit(web, 1000)
    library.spend("proofread", 1000)
    quota = web.get("/api/library").json()["quota"]
    assert quota["exhausted"] is True and quota["used"] == 1000 and quota["resets_at"]

    zhang = confirm(web, rec, "S2", new_person="张总")["person_id"]
    pid = web.post(f"/api/library/people/{zhang}/persona", headers=HEADERS).json()["persona_id"]
    until(lambda: web.get("/api/library").json()["quota"]["waiting_twins"] == 1)
    status = web.get("/api/library").json()
    assert status["quota"]["waiting_proofread"] == 1 and recording_state(web, rec) == "waiting"
    assert model.proofreads == 0 and not open_twin(web, pid)
    assert own_words(tmp_path, pid) == []

    # More room: proofreading and the held rebuild go on by themselves.
    limit(web, 0)
    until(lambda: recording_state(web, rec) == "done")
    until(lambda: open_twin(web, pid) and own_words(tmp_path, pid) == [f"[00:06] {MEANT}"])
    assert web.get("/api/library").json()["quota"]["waiting_twins"] == 0

    # Spent again: a later change closes the twin, and its rebuild waits.
    limit(web, sum(spending(library).values()))
    confirm(web, rec, "S1", new_person="李总")
    until(lambda: web.get("/api/library").json()["quota"]["waiting_twins"] == 1)
    assert not open_twin(web, pid)
    assert wanted_done(library, pid)[0] != wanted_done(library, pid)[1]


@pytest.fixture
def fast_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin.web.library.WAKE_SECONDS", 0.05)


def test_held_work_goes_on_when_the_quota_frees_up_without_anyone_looking(
    fast_wake: None, web: TestClient, tmp_path: Path, model: Model
) -> None:
    library = library_of(tmp_path)
    rec = misheard(library)
    limit(web, 1000)
    library.spend("proofread", 1000)
    zhang = confirm(web, rec, "S2", new_person="张总")["person_id"]
    pid = web.post(f"/api/library/people/{zhang}/persona", headers=HEADERS).json()["persona_id"]
    until(lambda: web.get("/api/library").json()["quota"]["waiting_twins"] == 1)
    assert model.proofreads == 0 and not open_twin(web, pid)

    # Room again, and nobody opens the library page: only the twin's own status is read below.
    limit(web, 0)
    until(lambda: open_twin(web, pid) and own_words(tmp_path, pid) == [f"[00:06] {MEANT}"])
    recording = library.get(rec)
    assert recording is not None and recording.proofread == recording.transcript_id and model.proofreads == 1


@needs_ffmpeg
def test_a_retried_recording_waits_for_the_quota_before_proofreading(
    web: TestClient, tmp_path: Path, model: Model
) -> None:
    FakeTranscriber.fail = True
    upload(web, wav_bytes())
    failed = settled(web)["recordings"][0]
    assert failed["status"] == "failed"
    library = library_of(tmp_path)
    limit(web, 10)
    library.spend("proofread", 10)
    FakeTranscriber.fail = False
    assert web.post(f"/api/library/recordings/{failed['id']}/retry", headers=HEADERS).status_code == 202
    assert settled(web)["recordings"][0]["status"] == "ready"
    confirm(web, failed["id"], "S1", new_person="张总")
    assert recording_state(web, failed["id"]) == "waiting" and model.proofreads == 0
    limit(web, 0)
    until(lambda: recording_state(web, failed["id"]) == "done")
    assert model.proofreads == 1


def test_a_model_failing_on_every_batch_leaves_the_words_as_heard(web: TestClient, tmp_path: Path) -> None:
    library = library_of(tmp_path)
    rec = misheard(library)
    web.app.state.libraries.llm = lambda: FakeLLM(lambda *_: {"items": []})  # type: ignore[attr-defined]
    zhang = confirm(web, rec, "S2", new_person="张总")["person_id"]
    until(lambda: recording_state(web, rec) == "failed")
    recording = library.get(rec)
    assert recording is not None and library.clean_path(recording).is_file() is False  # type: ignore[union-attr]
    assert [line for _, line, own in Team(library).sources(zhang, "张总")[0].lines if own and line] == [
        f"[00:06] {HEARD}"
    ]
