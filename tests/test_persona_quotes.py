from __future__ import annotations

import pytest

from twin.persona.quotes import remove_unverified_quotes


@pytest.mark.parametrize(
    ("text", "materials", "expected", "removed"),
    [
        ("我说「虚构飞船旅行」，不改别的。", [], "我说虚构飞船旅行，不改别的。", 1),
        ("「先核对数据」", ["我总是先核对数据再决定"], "「先核对数据」", 0),
        ('“ＡＢＣＤ，ＥＦ” "café words"', ["abcdef CAFÉ WORDS"], '“ＡＢＣＤ，ＥＦ” "café words"', 0),
        ("「外层『先核对数据』然后“虚构飞船旅行”」", ["先核对数据"], "外层『先核对数据』然后虚构飞船旅行", 2),
        ("「外层『先核对数据』后面」", ["外层先核对数据后面"], "「外层『先核对数据』后面」", 0),
        ("「重复四字」「重复四字」", [], "重复四字重复四字", 2),
        ('「术语」『三个字』“Ａ，Ｂ Ｃ”"...."', [], '「术语」『三个字』“Ａ，Ｂ Ｃ”"...."', 0),
        ('"ASCII Words"', [], "ASCII Words", 1),
        ('"ﬃx"', [], "ﬃx", 1),
        (r'\"不是引号\" "真实四字"', [], r"\"不是引号\" 真实四字", 1),
        (r'"他说\"先核对数据\"再决定"', [], r"他说\"先核对数据\"再决定", 1),
        ("「未关闭『完整四字』", [], "「未关闭完整四字", 1),
        ("」未打开』没打开” 「错配四字』", [], "」未打开』没打开” 「错配四字』", 0),
        ("\t  前文\n「  虚构，飞船！旅行  」\r\n后文  ", [], "\t  前文\n  虚构，飞船！旅行  \r\n后文  ", 1),
        ("没有引用，'单引号不算引用'。", [], "没有引用，'单引号不算引用'。", 0),
        ("「跨越材料边界」", ["跨越材料", "边界"], "跨越材料边界", 1),
        (
            "**「虚构飞船旅行」**\n\n> 「先核对数据」\n\n[来源](https://example.com)\n\n```text\n「虚构飞船旅行」\n```",
            ["先核对数据"],
            "**虚构飞船旅行**\n\n> 「先核对数据」\n\n[来源](https://example.com)\n\n```text\n虚构飞船旅行\n```",
            2,
        ),
    ],
)
def test_remove_unverified_quotes(text: str, materials: list[str], expected: str, removed: int) -> None:
    assert remove_unverified_quotes(text, materials) == (expected, removed)
