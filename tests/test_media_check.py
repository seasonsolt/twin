"""CER arithmetic and end-to-end speech evaluation without models or network."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from typer.testing import CliRunner

from twin.cli import CONFIG_TEMPLATE, app
from twin.media.check import (
    DEFAULT_SENTENCES,
    INCOMPLETE_LENGTH_RATIO,
    SIMPLIFIED_PROMPT,
    calculate_cer,
    edit_distance,
    load_sentences,
    run_check,
    traditional_characters,
)
from twin.media.schema import ASRCapabilities, SpeechRequest, SpeechResult, Transcription, TranscriptionRequest
from twin.media.speech_text import SPEECH_TEXT_VERSION, speech_text
from twin.media.tts import SilentSynthesizer
from twin.util import fingerprint


class EchoRecognizer:
    def __init__(self, texts: list[str]) -> None:
        self.name = "fake"
        self.capabilities = ASRCapabilities()
        self.texts = iter(texts)
        self.requests: list[TranscriptionRequest] = []

    @property
    def identity(self) -> str:
        return fingerprint({"backend": "fake"})

    def transcribe(self, request: TranscriptionRequest) -> Transcription:
        assert request.audio.startswith(b"RIFF")
        self.requests.append(request)
        return Transcription(text=next(self.texts))


@pytest.mark.parametrize(
    ("reference", "hypothesis", "edits", "chars", "cer"),
    [
        ("你好", "你好", 0, 2, 0.0),
        ("你好", "您好", 1, 2, 0.5),
        ("你好", "你", 1, 2, 0.5),
        ("你好", "你好啊", 1, 2, 0.5),
        ("你", "你好啊", 2, 1, 2.0),
        ("", "", 0, 0, 0.0),
        ("， ！", "你好", 2, 0, 2.0),
        ("ＡＢＣ， 你好！", "abc你好", 0, 5, 0.0),
        ("你\n好。", "你\t好", 0, 2, 0.0),
    ],
)
def test_cer_math(reference: str, hypothesis: str, edits: int, chars: int, cer: float) -> None:
    result = calculate_cer(reference, hypothesis)
    assert result.edits == edits
    assert result.reference_chars == chars
    assert result.cer == pytest.approx(cer)


@pytest.mark.parametrize(("left", "right", "distance"), [("", "abc", 3), ("kitten", "sitting", 3), ("甲乙", "乙甲", 2)])
def test_edit_distance_is_symmetric(left: str, right: str, distance: int) -> None:
    assert edit_distance(left, right) == edit_distance(right, left) == distance


def test_normalizer_applies_to_both_sides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def normalizer(text: str, language: str) -> str:
        calls.append((text, language))
        return speech_text(text, language)

    monkeypatch.setattr("twin.media.check.speech_text", normalizer)
    score = calculate_cer("3.5%", "百分之三点五")
    assert score.cer == 0
    assert score.reference_normalized == score.hypothesis_normalized == "百分之三点五"
    assert calls == [("3.5%", "zh"), ("百分之三点五", "zh")]
    calls.clear()
    report = run_check(SilentSynthesizer(), EchoRecognizer(["百分之三点五"]), tmp_path, ["3.5%"])
    assert report.cer == 0
    assert calls == [("3.5%", "zh"), ("百分之三点五", "zh")]
    assert report.speech_text_version == SPEECH_TEXT_VERSION
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["speech_text_version"] == SPEECH_TEXT_VERSION
    assert "speech_text_applied" not in data
    assert "speech_text_applied" not in data["sentences"][0]["score"]
    assert f"朗读文本规范化版本：{SPEECH_TEXT_VERSION}" in (tmp_path / "report.md").read_text()


def test_traditional_characters_are_flagged_not_converted() -> None:
    assert traditional_characters("这是普通话，我们讨论风险。") == []
    flagged = traditional_characters("這是普通話，我們討論風險。這")
    assert "這" in flagged and "話" in flagged and "風" in flagged
    assert len(flagged) == len(set(flagged))
    assert "台" not in traditional_characters("台、后、里")
    score = calculate_cer("这", "這")
    assert score.cer == 1 and score.hypothesis_normalized == "這"


def test_end_to_end_split_order_weighted_cer_permissions(tmp_path: Path) -> None:
    out = tmp_path / "report"
    out.mkdir(mode=0o755)
    for name in ("report.json", "report.md"):
        (out / name).write_text("old")
        (out / name).chmod(0o644)
    synth = SilentSynthesizer(max_chars=2)
    recognizer = EchoRecognizer(["你啊", "世界", "這"])
    report = run_check(synth, recognizer, out, ["你好世界", "这"])
    assert [row.parts for row in report.sentences] == [2, 1]
    assert report.sentences[0].hypothesis == "你啊世界"
    assert report.cer == pytest.approx(2 / 5)
    assert report.edits == 2 and report.reference_chars == 5
    assert report.traditional_sentence_count == 1
    assert report.sentences[1].hypothesis == "這"
    assert report.audio_duration_s == pytest.approx(5 * 0.08)
    assert report.synthesis_wall_per_audio_s == pytest.approx(report.synthesis_wall_s / (5 * 0.08))
    assert all(request.prompt == SIMPLIFIED_PROMPT and request.language == "zh" for request in recognizer.requests)
    assert out.stat().st_mode & 0o777 == 0o700
    for name in ("report.json", "report.md"):
        assert (out / name).stat().st_mode & 0o777 == 0o600
    data = json.loads((out / "report.json").read_text())
    assert data["synth_fingerprint"] == synth.identity
    assert data["asr_fingerprint"] == recognizer.identity
    assert data["cer"] == pytest.approx(2 / 5)
    assert "语音回听评测" in (out / "report.md").read_text()
    assert set(path.name for path in out.iterdir()) == {"report.json", "report.md"}


def test_repeats_always_synthesize_and_recognize_with_full_statistics(tmp_path: Path) -> None:
    class CountingSynth(SilentSynthesizer):
        def __init__(self) -> None:
            super().__init__()
            self.requests: list[SpeechRequest] = []

        def synthesize(self, request: SpeechRequest) -> SpeechResult:
            self.requests.append(request)
            return super().synthesize(request)

    synth = CountingSynth()
    recognizer = EchoRecognizer(["甲乙丙丁戊", "甲乙丙丁", "甲乙丙", "", "己", "己啊"])
    report = run_check(synth, recognizer, tmp_path, ["甲乙丙丁戊", "己"], repeats=3)
    assert [request.text for request in synth.requests] == ["甲乙丙丁戊"] * 3 + ["己"] * 3
    assert len(recognizer.requests) == 6
    assert report.schema_version == 3 and report.repeats == 3
    first, second = report.sentences
    assert first.hypothesis == "甲乙丙丁戊" and first.score.cer == 0  # Legacy first-repeat fields.
    assert first.mean_cer == pytest.approx(0.2) and first.worst_cer == pytest.approx(0.4)
    assert first.incomplete_repeats == second.incomplete_repeats == 1
    assert [check.incomplete for check in first.repeat_checks] == [False, False, True]
    assert [check.repeat_index for check in first.repeat_checks] == [0, 1, 2]
    assert report.incomplete_length_ratio == INCOMPLETE_LENGTH_RATIO == 0.8
    assert report.repeat_cers == pytest.approx([1 / 6, 1 / 6, 3 / 6])
    assert report.mean_cer == pytest.approx(5 / 18)
    assert report.cer == pytest.approx(5 / 18)
    assert report.worst_repeat_cer == pytest.approx(3 / 6)
    assert report.worst_sentence_repeat_cer == 1.0 and report.incomplete_repeats == 2
    assert report.edits == 5 and report.reference_chars == 18
    assert report.audio_duration_s == pytest.approx(18 * 0.08)
    data = json.loads((tmp_path / "report.json").read_text())
    assert len(data["sentences"][0]["repeat_checks"]) == 3
    assert data["sentences"][0]["repeat_checks"][2]["incomplete"] is True
    markdown = (tmp_path / "report.md").read_text()
    assert "80%" in markdown and "不完整重复：2" in markdown and "重复 3" in markdown


def test_check_counts_warned_parts_in_each_repeat_sentence_and_report(tmp_path: Path) -> None:
    class WarningSynth(SilentSynthesizer):
        calls = 0

        def synthesize(self, request: SpeechRequest) -> SpeechResult:
            self.calls += 1
            result = super().synthesize(request)
            return result.model_copy(update={"warnings": ["possibly-truncated"]}) if self.calls in (2, 3) else result

    report = run_check(
        WarningSynth(max_chars=2), EchoRecognizer(["你好", "世界"] * 2), tmp_path, ["你好世界"], repeats=2
    )
    assert report.warning_parts == report.sentences[0].warning_parts == 2
    assert [check.warning_parts for check in report.sentences[0].repeat_checks] == [1, 1]
    assert report.incomplete_repeats == 0  # Backend warnings and ASR-length heuristic are independent.
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["warning_parts"] == 2 and data["schema_version"] == 3
    assert "警告的分片：2" in (tmp_path / "report.md").read_text()


def test_repeated_split_parts_and_duplicate_sentences_have_fresh_caches(tmp_path: Path) -> None:
    class CountingSynth(SilentSynthesizer):
        calls = 0

        def synthesize(self, request: SpeechRequest) -> SpeechResult:
            self.calls += 1
            return super().synthesize(request)

    synth = CountingSynth(max_chars=2)
    recognizer = EchoRecognizer(["你好", "世界"] * 4)
    report = run_check(synth, recognizer, tmp_path, ["你好世界", "你好世界"], repeats=2)
    assert synth.calls == len(recognizer.requests) == 8
    assert report.mean_cer == report.worst_repeat_cer == 0
    assert all(check.parts == 2 for row in report.sentences for check in row.repeat_checks)


def test_incomplete_uses_normalized_lengths_and_empty_reference_is_complete(tmp_path: Path) -> None:
    report = run_check(
        SilentSynthesizer(), EchoRecognizer(["ＡＢＣＤ ！", "百分之三点五", ""]), tmp_path, ["ABCDE", "3.5%", "！"]
    )
    assert report.incomplete_repeats == 0  # Exactly 80%, expanded numbers, and empty references.


@pytest.mark.parametrize("repeats", [0, -1])
def test_invalid_repeats_rejected_before_io(repeats: int, tmp_path: Path) -> None:
    out = tmp_path / "unused"
    recognizer = EchoRecognizer([])
    with pytest.raises(ValueError, match="重复次数"):
        run_check(SilentSynthesizer(), recognizer, out, ["你好"], repeats=repeats)
    assert not out.exists() and not recognizer.requests


def test_no_chinese_prompt_for_other_languages(tmp_path: Path) -> None:
    recognizer = EchoRecognizer(["Hello!"])
    report = run_check(SilentSynthesizer(), recognizer, tmp_path, ["Hello!"], language="en")
    assert report.cer == 0
    assert recognizer.requests[0].prompt is None


def test_prompt_capability_is_respected(tmp_path: Path) -> None:
    recognizer = EchoRecognizer(["你好"])
    recognizer.capabilities = ASRCapabilities(supports_prompt=False)
    report = run_check(SilentSynthesizer(), recognizer, tmp_path, ["你好"])
    assert report.cer == 0 and recognizer.requests[0].prompt is None


def test_unknown_duration_does_not_report_partial_latency(tmp_path: Path) -> None:
    class UnknownDurationSynth(SilentSynthesizer):
        def synthesize(self, request: SpeechRequest) -> SpeechResult:
            result = super().synthesize(request)
            return result.model_copy(update={"duration_s": None}) if request.text == "世界" else result

    report = run_check(UnknownDurationSynth(), EchoRecognizer(["你好", "世界"]), tmp_path, ["你好", "世界"])
    assert report.sentences[0].audio_duration_s is not None
    assert report.sentences[1].audio_duration_s is None
    assert report.audio_duration_s is None and report.synthesis_wall_per_audio_s is None
    assert json.loads((tmp_path / "report.json").read_text())["synthesis_wall_per_audio_s"] is None


def test_default_fixture_matches_packaged_sentence_set() -> None:
    path = Path(__file__).parent / "fixtures" / "media" / "speech_check_zh.jsonl"
    assert load_sentences(path) == list(DEFAULT_SENTENCES)
    assert len(DEFAULT_SENTENCES) == 25


@pytest.mark.parametrize("content", ["", "{", "{}\n", '{"text": " "}\n', '{"text": 7}\n'])
def test_invalid_sentence_files(content: str, tmp_path: Path) -> None:
    path = tmp_path / "sentences.jsonl"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_sentences(path)


@pytest.mark.parametrize("repeats", [1, 3])
def test_cli_check_writes_reports_and_exits_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repeats: int) -> None:
    path = tmp_path / "sentences.jsonl"
    path.write_text('{"text":"你好"}\n')
    monkeypatch.setattr("twin.config.make_synthesizer", lambda _: SilentSynthesizer())
    monkeypatch.setattr("twin.config.make_recognizer", lambda _: EchoRecognizer(["你好"] * repeats))
    out = tmp_path / "output"
    config = tmp_path / "config.toml"
    config.write_text("")
    args = ["--config", str(config), "media", "check", "--sentences", str(path), "--out", str(out)]
    if repeats != 1:
        args.extend(["--repeats", str(repeats)])
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "CER 0.0000" in result.output
    assert json.loads((out / "report.json").read_text())["repeats"] == repeats
    assert (out / "report.json").stat().st_mode & 0o777 == 0o600
    assert (out / "report.md").stat().st_mode & 0o777 == 0o600


def test_cli_rejects_zero_repeats_before_backend_construction(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("")
    out = tmp_path / "out"
    result = CliRunner().invoke(app, ["--config", str(config), "media", "check", "--out", str(out), "--repeats", "0"])
    # Rich colours usage errors when it detects CI, which splits the option name with escape codes.
    assert result.exit_code != 0 and "--repeats" in click.unstyle(result.output)
    assert not out.exists()


def test_cli_check_requires_asr_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWIN_ASR_KEY", raising=False)
    config = tmp_path / "config.toml"
    config.write_text("")
    result = CliRunner().invoke(app, ["--config", str(config), "media", "check", "--out", str(tmp_path / "out")])
    assert result.exit_code != 0
    assert "[asr]" in result.output


def test_config_examples_are_identical() -> None:
    example = (Path(__file__).parents[1] / "twin.toml.example").read_text()
    assert example == CONFIG_TEMPLATE
