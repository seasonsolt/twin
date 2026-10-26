from __future__ import annotations

import io
import threading
import urllib.parse
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from twin.assets import AssetStore
from twin.config import Settings, WeComSettings
from twin.web import assets as web_assets
from twin.web import create_app
from twin.web import wecom_photos as module
from twin.web.jobs import JobManager, PersonaProcessing, describe_error
from twin.web.personas import Personas
from twin.web.wecom_photos import Contacts, WeComError, WeComPhotos

CSRF = {"X-Twin": "1"}
SECRET = "contacts-secret"
PHOTO = "https://wework.qpic.cn/wwpic/aibo/0"


class FakeWeCom:
    """WeCom's gettoken and user/get, with members by user ID: a photo address, or "" for one it gives no photo."""

    def __init__(self, members: dict[str, str]) -> None:
        self.members = members
        self.tokens = 0
        self.stale: set[str] = set()
        self.error: int | None = None
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict[str, Any]:
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append(parts.path)
        if parts.path == "/cgi-bin/gettoken":
            if self.error is not None:
                return {"errcode": self.error, "errmsg": "no"}
            assert query == {"corpid": "corp", "corpsecret": SECRET}
            self.tokens += 1
            return {"errcode": 0, "access_token": f"token-{self.tokens}", "expires_in": 7200}
        assert parts.path == "/cgi-bin/user/get"
        if query["access_token"] in self.stale:
            return {"errcode": 42001, "errmsg": "expired"}
        if query["userid"] not in self.members:
            return {"errcode": 60111, "errmsg": "userid not found"}
        return {"errcode": 0, "userid": query["userid"], "avatar": self.members[query["userid"]]}


def contacts(wecom: FakeWeCom) -> Contacts:
    return Contacts("https://qyapi.weixin.qq.com/", "corp", SECRET, fetch=wecom)


def test_contacts_give_a_members_photo_and_fetch_a_new_token_only_when_the_old_one_went_stale() -> None:
    wecom = FakeWeCom({"aibo": PHOTO, "77845": ""})
    book = contacts(wecom)
    assert book.photo("aibo") == PHOTO
    assert book.photo("77845") == ""  # a member WeCom gives no photo of
    assert book.photo("nobody") is None
    assert wecom.tokens == 1  # one token for all three
    wecom.stale.add("token-1")
    assert book.photo("aibo") == PHOTO and wecom.tokens == 2


def test_contacts_say_what_to_fix_without_the_secret() -> None:
    wecom = FakeWeCom({})
    wecom.error = 60020
    with pytest.raises(WeComError) as refused:
        contacts(wecom).photo("aibo")
    assert "企业可信 IP" in str(refused.value) and SECRET not in str(refused.value)

    def unreachable(url: str) -> dict[str, Any]:
        raise OSError(f"cannot reach {url}")

    with pytest.raises(OSError) as failed:
        Contacts("https://qyapi.weixin.qq.com", "corp", SECRET, fetch=unreachable).photo("aibo")
    assert SECRET not in str(failed.value)


def picture() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (640, 640), "navy").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def fetched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The photo addresses fetched, each answered with a usable photo."""
    seen: list[str] = []
    monkeypatch.setattr(web_assets, "fetch_photo", lambda url: seen.append(url) or picture())
    return seen


@pytest.fixture
def registry(tmp_path: Path, fetched: list[str]) -> Personas:
    return Personas(Settings(db_path=tmp_path / "twin.db"), JobManager(1, describe_error))


def worn(registry: Personas, persona_id: str) -> dict[str, Any] | None:
    if (job := registry.photo_jobs.get(persona_id)) is not None:
        job.join(10)
    portrait: dict[str, Any] | None = AssetStore(registry.settings_for(persona_id).db_path).profile()["portrait"]
    return portrait


def test_twins_made_for_an_employee_number_wear_its_wecom_photo_before_anyone_signs_in(
    registry: Personas, fetched: list[str]
) -> None:
    admin = {"email": "sso:19538", "admin": True}
    aibo, mailed, nobody, unknown = (registry.create(name, admin)["id"] for name in ("艾总", "夏总", "空", "查无"))
    with registry.lock:
        registry.entry(aibo)["claim"] = "aibo"
        registry.entry(mailed)["claim"] = "xia@xjjk.com"  # an address is not a WeCom user ID
        registry.entry(unknown)["claim"] = "nobody"
    wecom = FakeWeCom({"aibo": PHOTO})
    photos = WeComPhotos(registry, contacts(wecom))
    assert photos.sync() == {"offered": 1, "unknown": 1, "no_photo": 0}
    portrait = worn(registry, aibo)
    assert portrait is not None and portrait["source"] == "sso"
    assert registry.entry(aibo)["photo"] == PHOTO and fetched == [PHOTO]
    for other in (mailed, nobody, unknown):
        assert worn(registry, other) is None
    # The same photo again is not fetched again; a newer one replaces it.
    photos.sync()
    assert fetched == [PHOTO]
    wecom.members["aibo"] = PHOTO + "?v=2"
    photos.sync()
    worn(registry, aibo)
    assert registry.entry(aibo)["photo"] == PHOTO + "?v=2"


def test_a_portrait_someone_chose_is_kept(registry: Personas) -> None:
    persona = registry.create("艾总", {"email": "sso:19538", "admin": True})["id"]
    with registry.lock:
        registry.entry(persona)["claim"] = "aibo"
    store = AssetStore(registry.settings_for(persona).db_path)
    store.prepare()
    store.save("portrait", picture(), source="upload")
    WeComPhotos(registry, contacts(FakeWeCom({"aibo": PHOTO}))).sync()
    portrait = worn(registry, persona)
    assert portrait is not None and portrait["source"] == "upload"


def test_giving_a_twin_an_employee_number_looks_its_photo_up_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fetched: list[str]
) -> None:
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    monkeypatch.setenv("TWIN_WECOM_CONTACTS_SECRET", SECRET)
    wecom = FakeWeCom({"aibo": PHOTO})
    monkeypatch.setattr(module, "fetch_json", wecom)
    monkeypatch.setattr(module, "REFRESH_SECONDS", 3600)
    settings = Settings(db_path=tmp_path / "twin.db", wecom=WeComSettings(corp_id="corp"))
    with TestClient(create_app(settings), base_url="http://localhost") as web:
        persona = web.post("/api/personas", json={"name": "艾总"}, headers=CSRF).json()["id"]
        assert web.put(f"/api/personas/{persona}/claim", json={"claim": "aibo"}, headers=CSRF).status_code == 200
        registry: Personas = web.app.state.personas  # type: ignore[attr-defined]
        for _ in range(200):  # looked up on its own thread
            if registry.photo_jobs.get(persona) is not None:
                break
            threading.Event().wait(0.05)
        portrait = worn(registry, persona)
        assert portrait is not None and portrait["source"] == "sso"
        assert SECRET not in web.get("/api/personas").text


def test_without_the_secret_no_photo_is_looked_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWIN_WECOM_CONTACTS_SECRET", raising=False)
    settings = Settings(db_path=tmp_path / "twin.db", wecom=WeComSettings(corp_id="corp"))
    registry = Personas(settings, JobManager(1, describe_error))
    assert module.wecom_photos(settings, registry) is None
    assert module.wecom_photos(Settings(db_path=tmp_path / "twin.db"), registry) is None
