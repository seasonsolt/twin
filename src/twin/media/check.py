"""Cross-cutting synthetic speech evaluation; recognition never feeds runtime answers."""

from __future__ import annotations

import json
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from ..util import fingerprint, open_private, private_directory
from .asr import SpeechRecognizer
from .render import render_audio
from .schema import MediaScript, Segment, TranscriptionRequest
from .speech_text import SPEECH_TEXT_VERSION, speech_text
from .tts import SpeechSynthesizer

# Strict inequality: exactly 80% is not incomplete; empty references never are.
INCOMPLETE_LENGTH_RATIO = 0.8

SIMPLIFIED_PROMPT = "以下是普通话句子。请使用简体中文转写。"
TRADITIONAL_ONLY = frozenset(
    "這個們來說話語聽聲識別開關會議為與時間國體學習經濟業務發現應該實際數據問題風險萬億點後臺灣龍讓選擇無從對於過還進麼"
)
DEFAULT_SENTENCES: tuple[str, ...] = (
    "今天我们先核对材料，再讨论下一步安排。",
    "请把结论和依据分别说明。",
    "我们需要2个方案和3位同事。",
    "库存有12000件，今天发出250件。",
    "本月完成率是3.5%。",
    "预算增加12%，成本下降2%。",
    "增长率从-2%变为5%。",
    "测量结果是3.14米。",
    "总金额为1,200元。",
    "这个项目预算是¥300万元。",
    "资料截至2026年10月4日。",
    "请在2026-10-04前提交报告。",
    "会议从18:30开始。",
    "明天9:05我们再核对一次。",
    "预计需要3-5个工作日。",
    "请检查第3项任务。",
    "这个判断有足够的证据吗？",
    "如果条件改变，我们应该如何调整？",
    "请用AI辅助整理，但不要生成新的事实。",
    "API和GPU只是工具，不是决策依据。",
    "请核对KPI，但不要只看单一指标。",
    "版本v1.2与编号A3需要保持原样。",
    "一方面要控制风险，另一方面要保留选择。",
    "目前证据不足，暂时不能给出确定结论。",
)


def _normalize(text: str, language: str) -> str:
    text = speech_text(text, language)
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(char for char in text if not char.isspace() and not unicodedata.category(char).startswith("P"))


def edit_distance(reference: str, hypothesis: str) -> int:
    """Character Levenshtein distance with linear auxiliary space."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class CERResult:
    reference_normalized: str
    hypothesis_normalized: str
    edits: int
    reference_chars: int
    cer: float


def _score(reference: str, hypothesis: str, language: str) -> CERResult:
    left, right = _normalize(reference, language), _normalize(hypothesis, language)
    edits = edit_distance(left, right)
    return CERResult(left, right, edits, len(left), edits / max(1, len(left)))


def calculate_cer(reference: str, hypothesis: str, language: str = "zh") -> CERResult:
    """Normalize both sides equally; empty references use denominator one, and CER may exceed one."""
    return _score(reference, hypothesis, language)


def traditional_characters(text: str) -> list[str]:
    """Flag common Traditional-only characters without conversion; this list is not exhaustive."""
    return sorted(set(text) & TRADITIONAL_ONLY)


def load_sentences(path: Path) -> list[str]:
    """Read JSONL objects with a nonempty text field, allowing additional fixture metadata."""
    sentences: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            raise ValueError(f"评测句集第 {number} 行不是有效 JSON") from None
        if not isinstance(value, dict) or not isinstance(value.get("text"), str) or not value["text"].strip():
            raise ValueError(f"评测句集第 {number} 行必须包含非空 text")
        sentences.append(value["text"])
    if not sentences:
        raise ValueError("评测句集不能为空")
    return sentences


@dataclass(frozen=True)
class RepeatCheck:
    reference: str
    hypothesis: str
    score: CERResult
    traditional_characters: list[str]
    parts: int
    synthesis_wall_s: float
    audio_duration_s: float | None
    synthesis_wall_per_audio_s: float | None
    recognition_wall_s: float
    repeat_index: int = 0
    incomplete: bool = False
    warning_parts: int = 0


@dataclass(frozen=True)
class SentenceCheck(RepeatCheck):
    # Legacy fields describe the first repeat; all observations remain available here.
    repeat_checks: list[RepeatCheck] = field(default_factory=list)
    mean_cer: float = 0.0
    worst_cer: float = 0.0
    incomplete_repeats: int = 0


@dataclass(frozen=True)
class CheckReport:
    schema_version: int
    synth_fingerprint: str
    asr_fingerprint: str
    language: str
    speech_text_version: int
    sentences: list[SentenceCheck]
    edits: int
    reference_chars: int
    cer: float
    synthesis_wall_s: float
    audio_duration_s: float | None
    synthesis_wall_per_audio_s: float | None
    traditional_sentence_count: int
    repeats: int = 1
    incomplete_length_ratio: float = INCOMPLETE_LENGTH_RATIO
    repeat_cers: list[float] = field(default_factory=list)
    mean_cer: float = 0.0
    worst_repeat_cer: float = 0.0
    worst_sentence_repeat_cer: float = 0.0
    incomplete_repeats: int = 0
    warning_parts: int = 0


def _duration(values: Sequence[float | None]) -> float | None:
    if not values or any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _ratio(wall: float, duration: float | None) -> float | None:
    return wall / duration if duration is not None and duration > 0 else None


def report_markdown(report: CheckReport) -> str:
    """A human-readable report with unmodified reference and hypothesis text."""
    ratio = report.synthesis_wall_per_audio_s
    lines = [
        "# 语音回听评测",
        "",
        "仅用于合成句子的展示评测，不参与分身推理。",
        f"- 合成指纹：`{report.synth_fingerprint}`",
        f"- 识别指纹：`{report.asr_fingerprint}`",
        f"- 朗读文本规范化版本：{report.speech_text_version}",
        f"- 总字错率 CER：{report.cer:.4f}（{report.edits}/{report.reference_chars}）",
        f"- 每句重复次数：{report.repeats}；整轮平均 CER：{report.mean_cer:.4f}；"
        f"最差整轮 CER：{report.worst_repeat_cer:.4f}",
        f"- 最差单句重复 CER：{report.worst_sentence_repeat_cer:.4f}；不完整重复：{report.incomplete_repeats}",
        f"- 携带 possibly-truncated 警告的分片：{report.warning_parts}",
        f"- 合成墙钟秒 / 音频秒：{ratio:.4f}" if ratio is not None else "- 合成墙钟秒 / 音频秒：时长未知",
        f"- 疑似繁体输出：{report.traditional_sentence_count} 句（常见字表，非穷尽检测；未转换）",
        "",
        "每句每次重复使用独立空缓存，包含渲染与文件写入；总 CER 按全部重复的参考字符数加权。",
        "整轮 CER 按参考字符数加权；整轮平均/最差为各轮 CER 的算术平均/最大值。",
        "旧逐句识别、score 与计时字段保留第一次重复；总体计时包含全部重复。",
        f"不完整：规范化识别长度 < {report.incomplete_length_ratio:.0%} × 规范化参考长度（严格小于）。",
        "CER：双方先经朗读文本规范化，再经 NFKC、小写、去标点与空白；空参考分母为一。",
    ]
    for index, sentence in enumerate(report.sentences, 1):
        lines.extend(
            [
                "",
                f"## 句子 {index}",
                f"参考（JSON）：{json.dumps(sentence.reference, ensure_ascii=False)}",
                f"识别（JSON）：{json.dumps(sentence.hypothesis, ensure_ascii=False)}",
                f"CER：{sentence.score.cer:.4f}；平均：{sentence.mean_cer:.4f}；最差：{sentence.worst_cer:.4f}；"
                f"不完整重复：{sentence.incomplete_repeats}；分片：{sentence.parts}；"
                f"警告分片：{sentence.warning_parts}；"
                f"疑似繁体字：{''.join(sentence.traditional_characters) or '无'}",
            ]
        )
        for repeat in sentence.repeat_checks:
            lines.append(
                f"- 重复 {repeat.repeat_index + 1}：CER {repeat.score.cer:.4f}；不完整：{repeat.incomplete}；"
                f"警告分片：{repeat.warning_parts}；"
                f"识别（JSON）：{json.dumps(repeat.hypothesis, ensure_ascii=False)}"
            )
    return "\n".join(lines) + "\n"


def run_check(
    synthesizer: SpeechSynthesizer,
    recognizer: SpeechRecognizer,
    out: Path,
    sentences: Sequence[str] = DEFAULT_SENTENCES,
    *,
    language: str = "zh",
    repeats: int = 1,
) -> CheckReport:
    """Render and recognize each ordered part, then write owner-only JSON and Markdown reports."""
    if repeats < 1:
        raise ValueError("重复次数必须至少为 1")
    if not sentences or any(not sentence.strip() for sentence in sentences):
        raise ValueError("评测句子不能为空")
    private_directory(out)
    out.chmod(0o700)
    rows: list[SentenceCheck] = []
    with TemporaryDirectory(prefix=".speech-check-", dir=out) as temporary:
        for index, text in enumerate(sentences):
            script = MediaScript(
                source_kind="chat_reply",
                source_fingerprint=fingerprint({"synthetic_check": text}),
                persona_name="合成评测",
                as_of=None,
                confidence=1.0,
                abstain=False,
                segments=[Segment(index=0, kind="speech", text=text)],
                citations=[],
            )
            checks: list[RepeatCheck] = []
            for repeat_index in range(repeats):
                # Each rendering owns a fresh cache, even for duplicate fixture sentences.
                directory = Path(temporary) / str(index) / str(repeat_index)
                start = time.perf_counter()
                rendered = render_audio(script, synthesizer, directory)
                wall = time.perf_counter() - start
                parts = [part for segment in rendered.segments for part in segment.parts]
                hypotheses: list[str] = []
                recognition_start = time.perf_counter()
                for part in parts:
                    result = recognizer.transcribe(
                        TranscriptionRequest(
                            audio=(directory / part.file_name).read_bytes(),
                            audio_format=part.audio_format,
                            language=language,
                            prompt=(
                                SIMPLIFIED_PROMPT
                                if language.lower().startswith("zh") and recognizer.capabilities.supports_prompt
                                else None
                            ),
                        )
                    )
                    hypotheses.append(result.text)
                recognition_wall = time.perf_counter() - recognition_start
                hypothesis = "".join(hypotheses)
                duration = _duration([part.duration_s for part in parts])
                score = _score(text, hypothesis, language)
                checks.append(
                    RepeatCheck(
                        reference=text,
                        hypothesis=hypothesis,
                        score=score,
                        traditional_characters=traditional_characters(hypothesis),
                        parts=len(parts),
                        synthesis_wall_s=wall,
                        audio_duration_s=duration,
                        synthesis_wall_per_audio_s=_ratio(wall, duration),
                        recognition_wall_s=recognition_wall,
                        repeat_index=repeat_index,
                        warning_parts=sum("possibly-truncated" in part.warnings for part in parts),
                        incomplete=len(score.hypothesis_normalized) < INCOMPLETE_LENGTH_RATIO * score.reference_chars,
                    )
                )
            first = checks[0]
            rows.append(
                SentenceCheck(
                    reference=first.reference,
                    hypothesis=first.hypothesis,
                    score=first.score,
                    traditional_characters=first.traditional_characters,
                    parts=first.parts,
                    synthesis_wall_s=first.synthesis_wall_s,
                    audio_duration_s=first.audio_duration_s,
                    synthesis_wall_per_audio_s=first.synthesis_wall_per_audio_s,
                    recognition_wall_s=first.recognition_wall_s,
                    incomplete=first.incomplete,
                    warning_parts=sum(check.warning_parts for check in checks),
                    repeat_checks=checks,
                    mean_cer=sum(check.score.cer for check in checks) / repeats,
                    worst_cer=max(check.score.cer for check in checks),
                    incomplete_repeats=sum(check.incomplete for check in checks),
                )
            )
    all_checks = [check for row in rows for check in row.repeat_checks]
    edits = sum(check.score.edits for check in all_checks)
    reference_chars = sum(check.score.reference_chars for check in all_checks)
    wall = sum(check.synthesis_wall_s for check in all_checks)
    duration = _duration([check.audio_duration_s for check in all_checks])
    repeat_cers = [
        sum(row.repeat_checks[i].score.edits for row in rows)
        / max(1, sum(row.repeat_checks[i].score.reference_chars for row in rows))
        for i in range(repeats)
    ]
    report = CheckReport(
        schema_version=3,
        synth_fingerprint=synthesizer.identity,
        asr_fingerprint=recognizer.identity,
        language=language,
        speech_text_version=SPEECH_TEXT_VERSION,
        sentences=rows,
        edits=edits,
        reference_chars=reference_chars,
        cer=edits / max(1, reference_chars),
        synthesis_wall_s=wall,
        audio_duration_s=duration,
        synthesis_wall_per_audio_s=_ratio(wall, duration),
        traditional_sentence_count=sum(
            any(check.traditional_characters for check in row.repeat_checks) for row in rows
        ),
        repeats=repeats,
        repeat_cers=repeat_cers,
        mean_cer=sum(repeat_cers) / repeats,
        worst_repeat_cer=max(repeat_cers),
        worst_sentence_repeat_cer=max(check.score.cer for check in all_checks),
        incomplete_repeats=sum(check.incomplete for check in all_checks),
        warning_parts=sum(check.warning_parts for check in all_checks),
    )
    with open_private(out / "report.json") as stream:
        stream.write(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n")
    with open_private(out / "report.md") as stream:
        stream.write(report_markdown(report))
    return report
