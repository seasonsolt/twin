from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner, Result

from twin import cli
from twin.identity import Decision
from twin.llm import FakeLLM
from twin.persona import profile as pf
from twin.persona.schema import ChatDraft
from twin.persona.store import PersonaStore

QUESTIONNAIRE = """**4. 排序。**　*偏好 · 2.1*

回答：结果第一，钱进了账户才算数。

**33.【可跳过】爱好？**　*开放 · 9.1*

回答：
"""

CHAT = "2026-09-01 10:02 李四：首付 10%\n2026-09-01 10:05 张明：说白了钱进了账户才叫收入\n"


def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    if schema is pf.ExtractDraft:
        n = re.findall(r"\[(\d+)\]", user)
        return {
            "items": [
                {"facet_id": "2.1", "statement": "他看重回款", "quotes": [{"n": int(n[0]), "quote": "钱进了账户"}]}
            ]
        }
    if schema is pf.MergeDraft:
        return {"items": [{"statement": "他认为回款第一", "candidate_ids": re.findall(r"\[(pc_[0-9a-f]+)\]", user)}]}
    if schema is ChatDraft:
        item = re.search(r"\[(pi_[0-9a-f]+)\]", system + user)
        return {"reply": "钱到账才算。", "citations": [item[1]] if item else [], "confidence": 0.8, "abstain": False}
    raise AssertionError(schema)


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("TWIN_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "make_llm", lambda _: FakeLLM(handler))
    path = tmp_path / "twin.toml"
    path.write_text('target_name = "张明"\ndb_path = "twin.db"\nmax_workers = 2\n', encoding="utf-8")
    with PersonaStore(tmp_path / "twin.db") as store:
        store.append_consent("egress:llm", Decision.GRANT, "cli")
    (tmp_path / "问卷_2026-08-30.md").write_text(QUESTIONNAIRE, encoding="utf-8")
    (tmp_path / "群聊.txt").write_text(CHAT, encoding="utf-8")
    return path


def run(config: Path, *args: str, code: int = 0) -> Result:
    result = CliRunner().invoke(cli.app, ["--config", str(config), "persona", *args])
    assert result.exit_code == code, (result.stdout, result.stderr, result.exception)
    return result


def test_import_build_coverage_and_chat_end_to_end(config: Path, tmp_path: Path) -> None:
    out = run(config, "import", "问卷_2026-08-30.md", "--kind", "questionnaire").stdout
    assert "导入 问卷_2026-08-30.md（问卷）：1 条，本人 1 条" in out and "未授权细项 9.1" in out
    assert "导入 群聊.txt（聊天记录）：2 条，本人 1 条" in run(config, "import", "群聊.txt", "--kind", "chat").stdout
    assert "已更新 群聊.txt" in run(config, "import", "群聊.txt", "--kind", "chat").stdout
    assert len(run(config, "sources").stdout.splitlines()) == 2
    built = run(config, "build").stdout
    assert "资料 2 份" in built and "档案条目 1 条" in built
    cov = run(config, "coverage", "--as-of", "2026-10-03", "--out", "cov.md").stdout
    assert "已写入 cov.md" in cov
    md = (tmp_path / "cov.md").read_text(encoding="utf-8")
    assert "| 2.1 核心价值排序 | 充分 | 0.83 |  |  | 1 |  | 1 |  |" in md  # questionnaire + chat, two occasions
    assert "| 9.1 兴趣爱好 | 未授权 |" in md
    reply = run(config, "chat", "你看重什么？").stdout
    assert (
        "张明的分身：钱到账才算。" in reply and "置信度 0.60" in reply and "依据 pi_" in reply
    )  # cites an unreviewed item only


def test_import_reports_unparseable_files(config: Path, tmp_path: Path) -> None:
    (tmp_path / "空.md").write_text("没有题目", encoding="utf-8")
    result = run(config, "import", "空.md", "--kind", "questionnaire", code=1)
    assert "no questionnaire question" in result.stderr
    assert "找不到文件" in run(config, "import", "无.txt", "--kind", "chat", code=1).stderr
