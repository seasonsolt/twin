"""Offline pronunciation normalization, opaque identifiers and span provenance."""

from __future__ import annotations

import pytest

from twin.media.schema import SynthCapabilities
from twin.media.speech_text import SPEECH_TEXT_VERSION, speech_text, speech_text_spans

CASES = [
    ("", ""),
    ("原话不改。", "原话不改。"),
    ("3.5%", "百分之三点五"),
    ("12%", "百分之十二"),
    ("-2%", "负百分之二"),
    ("0%", "百分之零"),
    ("100%", "百分之一百"),
    ("0.05%", "百分之零点零五"),
    ("1,200%", "百分之一千二百"),
    ("增长3.5%，下降-2%。", "增长百分之三点五，下降负百分之二。"),
    ("3.14", "三点一四"),
    ("2.01", "二点零一"),
    ("-0.5", "负零点五"),
    ("12.00", "十二点零零"),
    ("0", "零"),
    ("2", "两"),
    ("2个", "两个"),
    ("2人", "两人"),
    ("2台", "两台"),
    ("2份", "两份"),
    ("2小时", "两小时"),
    ("2分钟", "两分钟"),
    ("2年", "两年"),
    ("2公斤", "两公斤"),
    ("2公里", "两公里"),
    ("第2个", "第二个"),
    ("第3", "第三"),
    ("第12位", "第十二位"),
    ("10", "十"),
    ("11", "十一"),
    ("20", "二十"),
    ("102", "一百零二"),
    ("12000", "一万两千"),
    ("20000", "两万"),
    ("10001", "一万零一"),
    ("10010", "一万零一十"),
    ("100000001", "一亿零一"),
    ("100010001", "一亿零一万零一"),
    ("200000000", "两亿"),
    ("1,200", "一千二百"),
    ("1,234,567", "一百二十三万四千五百六十七"),
    ("2026年", "二零二六年"),
    ("1999年", "一九九九年"),
    ("2026年10月4日", "二零二六年十月四日"),
    ("2月2日", "二月二日"),
    ("18:30", "十八点三十分"),
    ("08:05", "八点五分"),
    ("0:00", "零点零分"),
    ("23:59", "二十三点五十九分"),
    ("3-5个", "三到五个"),
    ("2-3台", "两到三台"),
    ("1.5-2.5米", "一点五到二点五米"),
    ("-3--1", "负三到负一"),
    ("第3-5项", "第三到五项"),
    ("¥1,200", "一千二百元"),
    ("￥3.5", "三点五元"),
    ("¥-2", "负二元"),
    ("¥2万", "两万元"),
    ("¥3.5万元", "三点五万元"),
    ("￥2亿元", "两亿元"),
    ("12元", "十二元"),
    ("2万元", "两万元"),
    ("3.5亿元", "三点五亿元"),
    ("¥0.50", "零点五零元"),
    ("13812345678", "一三八一二三四五六七八"),
    ("010-12345678", "零一零-一二三四五六七八"),
    ("400-123-4567", "四零零-一二三-四五六七"),
    ("+86 13812345678", "+八六 一三八一二三四五六七八"),
    ("1234567", "一二三四五六七"),
    ("12345678", "一二三四五六七八"),
    ("12345678元", "一千二百三十四万五千六百七十八元"),
    ("13812345678元", "一百三十八亿一千二百三十四万五千六百七十八元"),
    ("0012", "零零一二"),
    ("AI", "AI"),
    ("API与HTTP", "API 与 HTTP"),
    ("OpenAI", "OpenAI"),
    ("v1.2", "v1.2"),
    ("v1.2.3", "v1.2.3"),
    ("1.2.3", "1.2.3"),
    ("A3", "A3"),
    ("3D", "3D"),
    ("3.5GHz", "3.5GHz"),
    ("ABC-123", "ABC-123"),
    ("build_2026", "build_2026"),
    ("2026-10-04", "二零二六年十月四日"),
    ("2026/10/04", "二零二六年十月四日"),
    ("截至2026-10-04.", "截至二零二六年十月四日."),
    ("截至2026/10/04.", "截至二零二六年十月四日."),
    ("截至2026-13-40.", "截至 2026-13-40."),
    ("请在2026-10-04前提交报告。", "请在二零二六年十月四日前提交报告。"),
    ("资料于2026/10/04截止，再核对3项。", "资料于二零二六年十月四日截止，再核对三项。"),
    ("2026-10-04日", "二零二六年十月四日"),
    ("2024-02-29", "二零二四年二月二十九日"),
    ("2026-02-29", "2026-02-29"),
    ("2026-13-40", "2026-13-40"),
    ("2026/13/40", "2026/13/40"),
    ("请在2026-04-31前核对。", "请在 2026-04-31 前核对。"),
    ("0000-10-04", "0000-10-04"),
    ("10/4前提交", "十月四日前提交"),
    ("10/4后提交", "十月四日后提交"),
    ("10/4起执行", "十月四日起执行"),
    ("10/4截止", "十月四日截止"),
    ("10/4日开会", "十月四日开会"),
    ("请于10/4提交。", "请于十月四日提交。"),
    ("请在10/4提交。", "请在十月四日提交。"),
    ("延期到10/4。", "延期到十月四日。"),
    ("有效至10/4。", "有效至十月四日。"),
    ("在02/09核对", "在二月九日核对"),
    ("在2/29核对", "在二月二十九日核对"),
    ("在4/31核对", "在 4/31 核对"),
    ("13/40前", "13/40 前"),
    ("10/4", "十/四"),
    ("比例3/4，10/4个", "比例三/四，十/四个"),
    ("2026.10.04", "2026.10.04"),
    ("v2026-10-04", "v2026-10-04"),
    ("v2026/10/04", "v2026/10/04"),
    ("build_2026-10-04", "build_2026-10-04"),
    ("在v10/4前核对", "在 v10/4 前核对"),
    ("https://example.test/2026-10-04", "https://example.test/2026-10-04"),
    ("2026-10-04T18:30:00Z", "2026-10-04T18:30:00Z"),
    ("https://example.test/v1.2?q=3.5%", "https://example.test/v1.2?q=3.5%"),
    ("www.example.test/2026/3", "www.example.test/2026/3"),
    ("user3@example.test", "user3@example.test"),
    ("A3与3个，v1.2与3.14。", "A3 与三个，v1.2 与三点一四。"),
    ("甲\n3.5%\t乙，3-5个；丙。", "甲\n百分之三点五\t乙，三到五个；丙。"),
    ("请用AI辅助整理，但不要生成新的事实。", "请用 AI 辅助整理，但不要生成新的事实。"),
    ("API和GPU只是工具，不是决策依据。", "API 和 GPU 只是工具，不是决策依据。"),
    ("使用OpenAI模型", "使用 OpenAI 模型"),
    ("中文ABC123中文", "中文 ABC123 中文"),
    ("中文v1.2.3版本", "中文 v1.2.3 版本"),
    ("中文1.2.3版本", "中文 1.2.3 版本"),
    ("中文 AI 中文", "中文 AI 中文"),
    ("中文\tAI\n中文", "中文\tAI\n中文"),
    ("中文ＡＩ中文", "中文 ＡＩ 中文"),
    ("中文１２中文", "中文 １２ 中文"),
    ("中文café中文", "中文 café 中文"),
    ("𠀀AI𠀀", "𠀀 AI 𠀀"),
    ("链接https://example.test/中文AI路径", "链接 https://example.test/中文AI路径"),
    ("网址www.example.test/中文3D", "网址 www.example.test/中文3D"),
]


@pytest.mark.parametrize(("original", "expected"), CASES)
def test_numeric_rules_and_idempotence(original: str, expected: str) -> None:
    assert speech_text(original, "zh") == expected
    assert speech_text(expected, "zh") == expected
    assert SPEECH_TEXT_VERSION == 3


@pytest.mark.parametrize(("original", "expected"), CASES)
def test_span_provenance_preserves_untouched_characters(original: str, expected: str) -> None:
    spans = speech_text_spans(original, "zh")
    assert "".join(source for source, _ in spans) == original
    assert "".join(spoken for _, spoken in spans) == expected
    for source, spoken in spans:
        if source != spoken:
            if not source:
                assert spoken == " "  # Boundary hints never consume display characters.
                continue
            assert any(char in "0123456789" for char in source)
            preserved = "".join(char for char in source if char not in "0123456789.,%:/-¥￥万亿元")
            offset = 0
            for char in preserved:
                offset = spoken.index(char, offset) + 1


@pytest.mark.parametrize("language", ["en", "en-US", "ja", "zh-CN", ""])
def test_other_languages_are_unchanged(language: str) -> None:
    original = "AI 3.5%，2026年，18:30，¥1,200，v1.2。"
    assert speech_text(original, language) == original
    assert speech_text(original, language, capabilities=SynthCapabilities(reads_latin_acronyms=False)) == original


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("AI", "A I"),
        ("API与HTTP", "A P I 与 H T T P"),
        ("ABCDE", "A B C D E"),
        ("A ABCDEF ai Ai OpenAI", "A ABCDEF ai Ai OpenAI"),
        ("AI3 A3 3AI AI_3 AI-3", "AI3 A3 3AI AI_3 AI-3"),
        ("https://AI.test/API", "https://AI.test/API"),
        ("AI增长3.5%。", "A I 增长百分之三点五。"),
    ],
)
def test_acronyms_are_only_spelled_by_declared_capability(original: str, expected: str) -> None:
    capabilities = SynthCapabilities(reads_latin_acronyms=False)
    assert speech_text(original, "zh", capabilities=capabilities) == expected
    assert speech_text(expected, "zh", capabilities=capabilities) == expected
    assert speech_text(original, "zh") == speech_text(original, "zh", capabilities=SynthCapabilities())


def test_original_non_number_characters_remain_in_order() -> None:
    original = "甲【3.5%】乙\n（12元）丙！第3项，2个；2026年10月4日？丁"
    spoken = speech_text(original, "zh")
    untouched = "".join(char for char in original if char not in "0123456789.%")
    offset = 0
    for char in untouched:
        offset = spoken.index(char, offset) + 1
