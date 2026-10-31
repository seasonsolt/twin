"""预演 (P2.6): the person rehearses an heir's conversation from the will. The answers draw only on what the will gives
that heir, a topic not to be talked about is stopped as it would be, what the rehearsal left out is named to the
person, and nothing of it is kept anywhere. Only the person may rehearse, only of an heir the will names, and only
while the memory is not sealed."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_heirs import (
    CSRF,
    FAMILY,
    GIVEN,
    WITHHELD,
    WORK,
    AsHeir,
    Recorder,
    markers,
    name_heir,
    seed,
)

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.persona import lifecycle, will
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

QUESTION = "家里、回款、原则、身体，你都说说"


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Recorder, dict[str, Any]]]:
    monkeypatch.setenv("TWIN_EDITION", "persona")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    path = tmp_path / "twin.db"
    with PersonaStore(path) as s:
        said = seed(s)
        heir_id = name_heir(s)
    llm = Recorder()
    app = create_app(
        Settings(db_path=path, target_name="张三"), llm_factory=lambda: llm, embedder_factory=HashingEmbedder
    )
    with TestClient(AsHeir(app), base_url="http://localhost") as client:
        yield client, llm, {"said": said, "heir_id": heir_id, "path": path}


def rehearse(client: TestClient, heir_id: str, *turns: str, headers: dict[str, str] = CSRF) -> Any:
    messages = [{"role": "user" if n % 2 == 0 else "twin", "content": t} for n, t in enumerate(turns)]
    body = {"messages": messages, "preview": True, "heir": heir_id}
    return client.post("/api/persona/chat/stream", json=body, headers=headers)


def final(response: Any) -> dict[str, Any]:
    assert response.status_code == 200 and "event: final" in response.text, response.text
    return json.loads(response.text.split("event: final\ndata: ", 1)[1].split("\n\n", 1)[0])  # type: ignore[no-any-return]


def rows(path: Path) -> dict[str, int]:
    """How many rows each table of the store holds, to show that a rehearsal wrote nothing."""
    with sqlite3.connect(path) as db:
        tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def test_a_rehearsal_answers_only_from_what_the_will_gives_and_names_what_it_left_out(
    web: tuple[TestClient, Recorder, dict[str, Any]],
) -> None:
    client, llm, ctx = web
    answer = final(rehearse(client, ctx["heir_id"], QUESTION))
    shown = markers("\n".join(llm.seen))
    assert {WORK, FAMILY} <= shown and not shown & WITHHELD
    given = {"pi_work", "pi_family", *(ctx["said"][m] for m in GIVEN if m in ctx["said"])}
    assert {c["id"] for c in answer["cited"]} <= given
    # What the person's own retrieval found that this heir is not given, by facet, for changing the will.
    left_out = answer["preview"]["withheld"]
    assert left_out and {w["id"] for w in left_out} <= {"pi_closed", "pi_marriage", "pi_health"}
    assert all(w["facet"] and w["text"] for w in left_out)
    # The same question in the heir's own conversation is shown the same, and nothing more.
    llm.seen.clear()
    heir = {**CSRF, "X-Test-Heir": ctx["heir_id"]}
    theirs = client.post("/api/conversations", json={}, headers=heir).json()["id"]
    body = {"messages": [{"role": "user", "content": QUESTION}], "conversation_id": theirs}
    real = final(client.post("/api/persona/chat/stream", json=body, headers=heir))
    assert markers("\n".join(llm.seen)) == shown
    assert [c["id"] for c in real["cited"]] == [c["id"] for c in answer["cited"]]
    assert "preview" not in real


def test_a_rehearsal_carries_on_the_conversation_and_a_topic_not_to_be_talked_about_is_stopped(
    web: tuple[TestClient, Recorder, dict[str, Any]],
) -> None:
    client, llm, ctx = web
    asked = llm.asked
    answer = final(rehearse(client, ctx["heir_id"], "说说你前一段婚姻"))
    assert answer["reply"].startswith("这件事张三") and llm.asked == asked
    # A follow-up after something else is stopped too: the rehearsal is sent whole, as the heir's would be.
    answer = final(rehearse(client, ctx["heir_id"], "回款的事呢", "我回答了。", "那段婚姻呢？"))
    assert answer["reply"].startswith("这件事张三") and llm.asked == asked
    # The crisis guard first, as ever.
    answer = final(rehearse(client, ctx["heir_id"], "说说你前一段婚姻，我不想活了"))
    assert answer.get("crisis") and llm.asked == asked


def test_a_rehearsal_keeps_nothing(web: tuple[TestClient, Recorder, dict[str, Any]]) -> None:
    client, _, ctx = web
    before = rows(ctx["path"])
    final(rehearse(client, ctx["heir_id"], QUESTION))
    final(rehearse(client, ctx["heir_id"], "说说你前一段婚姻"))
    final(rehearse(client, ctx["heir_id"], "我不想活了"))
    # No conversation, no question asked of the twin, no change to the will, nothing sealed.
    assert rows(ctx["path"]) == before
    assert client.get("/api/conversations").json() == []
    with PersonaStore(ctx["path"]) as store:
        assert not lifecycle.sealed(store)


def test_a_rehearsal_of_an_heir_past_their_day_shows_the_goodbye_and_keeps_nothing(
    web: tuple[TestClient, Recorder, dict[str, Any]],
) -> None:
    client, llm, ctx = web
    with PersonaStore(ctx["path"]) as store:
        heir = will.get(store, ctx["heir_id"])
        draft = will.HeirDraft.model_validate(heir.model_dump(include=set(will.HeirDraft.model_fields)))
        draft = draft.model_copy(update={"retire_on": dt.date.today(), "farewell": "阿明，往后要好好的。"})
        will.update(store, ctx["heir_id"], draft, None, "person", dt.datetime.now(dt.UTC))
    before = rows(ctx["path"])
    for _ in range(2):
        said = final(rehearse(client, ctx["heir_id"], QUESTION))
        assert said["reply"] == "阿明，往后要好好的。" and said["farewell"] is True
    assert not llm.seen and rows(ctx["path"]) == before


def test_only_the_person_rehearses_only_an_heir_the_will_names_and_not_once_sealed(
    web: tuple[TestClient, Recorder, dict[str, Any]],
) -> None:
    client, llm, ctx = web
    heir_id = ctx["heir_id"]
    # The heir themself cannot rehearse anyone, themself included.
    as_heir = rehearse(client, heir_id, QUESTION, headers={**CSRF, "X-Test-Heir": heir_id})
    assert as_heir.status_code == 403
    # An heir the will does not name, or no longer does.
    assert rehearse(client, "nobody", QUESTION).status_code == 404
    client.delete(f"/api/persona/will/heirs/{heir_id}", headers=CSRF)
    assert rehearse(client, heir_id, QUESTION).status_code == 404
    # Naming an heir without asking for a rehearsal answers nothing.
    plain = {"messages": [{"role": "user", "content": QUESTION}], "heir": heir_id}
    assert client.post("/api/persona/chat/stream", json=plain, headers=CSRF).status_code == 400
    assert not llm.seen
    # Once sealed, the will cannot change for what a rehearsal would show; in the persona edition the person's own
    # computer is then the heirs' way in alone, and refuses before the rehearsal is looked at.
    with PersonaStore(ctx["path"]) as store:
        other = name_heir(store, "小红")
        lifecycle.seal(store)
    sealed = rehearse(client, other, QUESTION)
    assert sealed.status_code == 423 and sealed.json()["code"] == "heirs_only"
    assert not llm.seen
