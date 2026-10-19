"""Work mode's web search: which key it uses, how DeepSeek's results and pages reach the model, and how failures
read, so the agent can rephrase, pick another page or go on without."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from twin.config import LLMSettings, SearchSettings, Settings
from twin.egress import egress_status
from twin.websearch import MAX_PAGE_TEXT, UNTRUSTED, SearchError, WebSearch, make_web_search, search_key

DEEPSEEK = LLMSettings(model="deepseek-chat", base_url="https://api.deepseek.com/v1", api_key_env="TWIN_CHAT_KEY")


def client(handler: Callable[[httpx.Request], httpx.Response], seen: list[httpx.Request]) -> httpx.Client:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(record))


def searcher(handler: Callable[[httpx.Request], httpx.Response], seen: list[httpx.Request]) -> WebSearch:
    return WebSearch(SearchSettings(count=5), "sk-test", client(handler, seen))


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin.websearch.RETRY_WAIT_S", 0)


# ── which key ──


def test_search_reuses_the_key_of_a_chat_model_on_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_CHAT_KEY", "sk-chat")
    assert search_key(Settings(chat_llm=DEEPSEEK)) == "sk-chat"
    assert search_key(Settings(llm=DEEPSEEK)) == "sk-chat"
    # Its own variable wins; a model on another host never lends its key; turned off means no key at all.
    monkeypatch.setenv("TWIN_SEARCH_KEY", "sk-search")
    assert search_key(Settings(chat_llm=DEEPSEEK)) == "sk-search"
    monkeypatch.delenv("TWIN_SEARCH_KEY")
    other = DEEPSEEK.model_copy(update={"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"})
    assert search_key(Settings(chat_llm=other)) is None
    assert make_web_search(Settings(chat_llm=other)) is None
    assert search_key(Settings(chat_llm=DEEPSEEK, search=SearchSettings(enabled=False))) is None
    # The same host behind another port or scheme is another server: the chat key stays with the chat model.
    for url in ("https://api.deepseek.com:8443", "http://localhost:8000"):
        assert search_key(Settings(chat_llm=DEEPSEEK, search=SearchSettings(base_url=url))) is None
    # A model that takes its endpoint from OPENAI_BASE_URL lends its key the same way.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
    assert search_key(Settings(chat_llm=DEEPSEEK.model_copy(update={"base_url": None}))) == "sk-chat"


@pytest.mark.parametrize("url", ["http://api.deepseek.com", "ftp://api.deepseek.com", "api.deepseek.com"])
def test_the_key_never_goes_out_unencrypted(url: str) -> None:
    with pytest.raises(ValueError, match="必须是 https"):
        SearchSettings(base_url=url)
    assert SearchSettings(base_url="http://127.0.0.1:9000").base_url == "http://127.0.0.1:9000"


def test_external_services_list_search_only_while_it_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not any(row["kind"] == "search" for row in egress_status(Settings()))
    monkeypatch.setenv("TWIN_SEARCH_KEY", "sk-search")
    (row,) = [row for row in egress_status(Settings(), external_only=True) if row["kind"] == "search"]
    assert row == {
        "kind": "search",
        "provider": "deepseek",
        "host": "api.deepseek.com",
        "external": True,
        "declared": False,
    }


# ── search ──


def test_results_come_back_numbered_with_link_date_and_summary() -> None:
    seen: list[httpx.Request] = []
    rows = [
        {
            "title": "DeepSeek 发布新模型",
            "url": "https://a.example/1",
            "site_name": "A 站",
            "date": "2026-10-18T08:00:00Z",
            "summary": "发布了新模型。",
            "snippet": "片段",
        },
        {"title": "", "url": "https://b.example/2", "snippet": "只有片段"},
    ]
    search = searcher(lambda _: httpx.Response(200, json={"results": rows}), seen)
    text, links = search.search("  DeepSeek   新模型\n")
    assert links == ["https://a.example/1", "https://b.example/2"]
    assert text == UNTRUSTED + (
        "[1] DeepSeek 发布新模型\nhttps://a.example/1\nA 站 · 2026-10-18\n发布了新模型。\n\n"
        "[2] （无标题）\nhttps://b.example/2\n只有片段"
    )
    (request,) = seen
    assert request.url == "https://api.deepseek.com/v1/tools/search"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert json.loads(request.content) == {"query": "DeepSeek 新模型", "count": 5}


def test_a_long_query_is_cut_and_many_results_stay_within_bounds() -> None:
    seen: list[httpx.Request] = []
    rows = [{"title": f"t{i}", "url": f"https://x.example/{i}", "summary": "字" * 3000} for i in range(10)]
    text, _ = searcher(lambda _: httpx.Response(200, json={"results": rows}), seen).search("查" * 300)
    assert len(json.loads(seen[0].content)["query"]) == 128
    # Each summary is cut so several results fit; past what one call may hand the model, the rest are left out.
    assert text.count("字" * 1200 + "……") == 6 and "[6] t5" in text and "[7]" not in text and len(text) <= 8000


def test_no_results_says_to_rephrase() -> None:
    text, links = searcher(lambda _: httpx.Response(200, json={"results": []}), []).search("不存在的东西")
    assert "没有搜到「不存在的东西」" in text and links == []
    with pytest.raises(SearchError, match="搜索词是空的"):
        searcher(lambda _: httpx.Response(200, json={}), []).search("   ")


def test_a_busy_service_is_tried_once_more() -> None:
    seen: list[httpx.Request] = []
    replies = iter([httpx.Response(503), httpx.Response(200, json={"results": [{"title": "t", "url": "u"}]})])
    assert searcher(lambda _: next(replies), seen).search("q")[0].startswith(UNTRUSTED + "[1] t")
    assert len(seen) == 2


@pytest.mark.parametrize(
    ("status", "words"),
    [
        (401, "密钥不对"),
        (402, "余额用完"),
        (429, "太频繁"),
        (400, "换个更短"),
        (500, "出错了（500）"),
        (522, "（522）"),
    ],
)
def test_failures_read_as_what_to_do(status: int, words: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(SearchError, match=words):
        searcher(lambda _: httpx.Response(status, json={"error": {"message": "x"}}), seen).search("q")
    assert len(seen) == (2 if status in {429, 500, 522} else 1)


def test_an_unreachable_service_says_so() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(SearchError, match="连不上"):
        searcher(down, []).search("q")


# ── pages ──


def test_a_page_comes_back_as_markdown_cut_to_length() -> None:
    seen: list[httpx.Request] = []
    page: dict[str, Any] = {"title": "标题", "content": "正" * (MAX_PAGE_TEXT + 50)}
    text = searcher(lambda _: httpx.Response(200, json=page), seen).fetch(" https://a.example/p?q=1 ")
    assert text.startswith(UNTRUSTED + "# 标题\n\n正") and text.endswith("（后面还有，已截断）")
    assert seen[0].url == "https://api.deepseek.com/v1/tools/fetch"
    assert json.loads(seen[0].content) == {"url": "https://a.example/p?q=1"}


@pytest.mark.parametrize("url", ["file:///etc/passwd", "a.example/p", "https://user:pw@a.example/", "http://"])
def test_only_plain_web_links_are_opened(url: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(SearchError):
        searcher(lambda _: httpx.Response(200, json={"content": "x"}), seen).fetch(url)
    assert not seen


@pytest.mark.parametrize("reply", [httpx.Response(403), httpx.Response(404), httpx.Response(200, json={"title": "t"})])
def test_a_page_that_cannot_be_read_says_to_pick_another(reply: httpx.Response) -> None:
    with pytest.raises(SearchError, match="换一个来源"):
        searcher(lambda _: reply, []).fetch("https://a.example/")
