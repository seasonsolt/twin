"""Profile photos from the company's WeCom contacts for twins made for an employee number.

The company sign-in gives no photo, so a twin made for an employee number (its ``claim``, which is the member's WeCom
user ID) wears the photo WeCom has of that member, whether or not they have signed in yet. The photo is worn the way
the sign-in's would be (``Personas.offer``): never over a portrait or illustration someone chose, and a newer one
replaces it. Looked up at start-up, once a day, and as soon as an employee number is given to a twin. The secret and
the access token never leave this module: not in logs, errors or the page.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..config import Settings
from ..util import key_from_env
from .auth import photo_url

if TYPE_CHECKING:
    from .personas import Personas

logger = logging.getLogger(__name__)

# How often the photos are looked up again, for members who changed theirs.
REFRESH_SECONDS = 24 * 3600
# Errors WeCom gives for an access token gone stale: a new one is fetched once.
STALE_TOKEN = {40001, 40014, 42001}
# Errors about one member: the others are still looked up.
NO_MEMBER = 60111  # no member has this user ID
HIDDEN_MEMBER = 60011  # the member is outside the app's visible range
# What the administrator is told for errors that stop every lookup.
SETUP_ERRORS = {
    60020: "企业微信不认这台服务器的 IP，请在企业微信管理后台把服务器出口 IP 加进企业可信 IP",
    40013: "企业微信企业 ID（[wecom] corp_id）不对",
    40091: "企业微信通讯录密钥不对",
    48002: "这个企业微信密钥没有读成员的权限",
}


class WeComError(Exception):
    def __init__(self, code: int, what: str) -> None:
        super().__init__(f"{what}（errcode {code}）")
        self.code = code


Fetch = Callable[[str], dict[str, Any]]


def fetch_json(url: str) -> dict[str, Any]:
    """GET ``url`` and read its JSON; raises OSError when WeCom cannot be reached now."""
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as response:
        data = json.loads(response.read(1 << 20))
    return data if isinstance(data, dict) else {}


class Contacts:
    """Members of the company's WeCom, read with an app's secret."""

    def __init__(
        self,
        api: str,
        corp_id: str,
        secret: str,
        *,
        fetch: Fetch | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.api, self.corp_id, self.secret = api.rstrip("/"), corp_id, secret
        self.fetch, self.clock = fetch or fetch_json, clock
        self._token: tuple[str, float] | None = None

    def _get(self, path: str, query: dict[str, str]) -> dict[str, Any]:
        try:
            return self.fetch(f"{self.api}{path}?{urllib.parse.urlencode(query)}")
        except (OSError, ValueError) as error:
            # The address carries the secret or the token: only the kind of failure is told.
            raise OSError(f"连不上企业微信（{type(error).__name__}）") from None

    def token(self) -> str:
        if self._token is not None and self.clock() < self._token[1]:
            return self._token[0]
        data = self._get("/cgi-bin/gettoken", {"corpid": self.corp_id, "corpsecret": self.secret})
        code = int(data.get("errcode") or 0)
        if code or not data.get("access_token"):
            raise WeComError(code, SETUP_ERRORS.get(code, "企业微信没有给出访问令牌"))
        # Fetched again five minutes before WeCom says it expires.
        self._token = str(data["access_token"]), self.clock() + max(int(data.get("expires_in") or 7200) - 300, 60)
        return self._token[0]

    def photo(self, user_id: str) -> str | None:
        """The address of the member's profile photo; "" when WeCom gives none (apps made after June 2022 are not
        given members' photos), None when there is no such member or the app may not see them."""
        for attempt in range(2):
            data = self._get("/cgi-bin/user/get", {"access_token": self.token(), "userid": user_id})
            code = int(data.get("errcode") or 0)
            if code in STALE_TOKEN and attempt == 0:
                self._token = None
                continue
            if code in (NO_MEMBER, HIDDEN_MEMBER):
                return None
            if code:
                raise WeComError(code, SETUP_ERRORS.get(code, "企业微信读成员失败"))
            return photo_url(data.get("avatar")) or ""
        raise WeComError(0, "企业微信访问令牌一直失效")


class WeComPhotos:
    """Offers each twin made for an employee number its member's WeCom profile photo."""

    def __init__(self, registry: Personas, contacts: Contacts) -> None:
        self.registry, self.contacts = registry, contacts
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None
        # One lookup at a time: a twin given an employee number while the daily one runs waits for it.
        self.running = threading.Lock()

    def wanted(self, persona_id: str | None = None) -> list[tuple[str, str]]:
        """(twin, employee number) of each live twin made for an employee number; e-mail addresses are not WeCom
        user IDs and are left out."""
        with self.registry.lock:
            return [
                (entry["id"], entry["claim"])
                for entry in self.registry.data["personas"]
                if entry.get("claim")
                and "@" not in entry["claim"]
                and not entry.get("deleted_at")
                and entry["id"] not in self.registry.removing
                and persona_id in (None, entry["id"])
            ]

    def sync(self, persona_id: str | None = None) -> dict[str, int]:
        """Look the photos up and offer them; returns how many twins were offered one, how many employee numbers
        WeCom does not know or let the app see, and how many came without a photo. Stops at the first error that
        would stop every lookup, saying so in the log."""
        counts = {"offered": 0, "unknown": 0, "no_photo": 0}
        with self.running:
            wanted = self.wanted(persona_id)
            for twin, user_id in wanted:
                if self.stopping.is_set():
                    break
                try:
                    url = self.contacts.photo(user_id)
                except WeComError as error:
                    logger.warning("企业微信头像没取成：%s", error)
                    return counts
                except OSError as error:
                    logger.warning("企业微信头像没取成：%s，稍后再试", error)
                    return counts
                if not url:
                    counts["unknown" if url is None else "no_photo"] += 1
                    continue
                with self.registry.lock:
                    entry = self.registry.entry(twin)
                    if entry is not None and entry.get("claim") == user_id:
                        self.registry.offer(entry, url)
                        counts["offered"] += 1
        if wanted:
            logger.info(
                "企业微信头像：查了 %d 个工号，%d 个分身拿到头像，%d 个工号查不到，%d 个没给头像",
                len(wanted),
                counts["offered"],
                counts["unknown"],
                counts["no_photo"],
            )
        return counts

    def kick(self, persona_id: str) -> None:
        """A twin was just given an employee number: look its photo up in the background."""
        threading.Thread(target=self.sync, args=(persona_id,), name="wecom-photo", daemon=True).start()

    def _loop(self) -> None:
        while not self.stopping.is_set():
            try:
                self.sync()
            except Exception:
                logger.warning("企业微信头像查找出错", exc_info=True)
            self.stopping.wait(REFRESH_SECONDS)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="wecom-photos", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(15)


def wecom_photos(settings: Settings, registry: Personas) -> WeComPhotos | None:
    """Photos from WeCom when ``[wecom] corp_id`` and the secret's environment variable are both set; the twin
    registry then has a twin's photo looked up as soon as it is given an employee number. None otherwise."""
    config = settings.wecom
    if not config.corp_id:
        return None
    secret = key_from_env(config.contacts_secret_env)
    if not secret:
        logger.warning(
            "配置了 [wecom] corp_id，但环境变量 %s 没有通讯录密钥，不取企业微信头像", config.contacts_secret_env
        )
        return None
    photos = WeComPhotos(registry, Contacts(config.api, config.corp_id, secret))
    registry.on_claimed = photos.kick
    return photos
