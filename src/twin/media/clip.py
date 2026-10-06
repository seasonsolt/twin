"""Minimal labelled MP4 presentation, with no content generation or upstream types."""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .render import render_audio
from .schema import EXPLICIT_LABEL, OPENING_NOTICE, AvatarSpec, MediaScript
from .tts import MediaError, MediaInputTooLong, SpeechSynthesizer

FONT_PATHS = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)
OPENING_SECONDS = 2
ENDING_SECONDS = 3


def _font_path(font_path: str | Path | None) -> Path:
    candidates = [Path(font_path).expanduser()] if font_path is not None else [Path(p) for p in FONT_PATHS]
    for path in candidates:
        if path.is_file():
            return path
    if font_path is None and (fc_match := shutil.which("fc-match")):
        for pattern in ("Noto Sans CJK SC:style=Regular", ":lang=zh"):
            try:
                result = subprocess.run(
                    [fc_match, "-f", "%{file}", pattern],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=2,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            filename = result.stdout.strip()
            if filename:
                path = Path(filename)
                if path.exists() and path.is_file():
                    return path
    raise MediaError("找不到中文字体，请设置 [media] font_path 指向中文字体文件")


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    lines: list[str] = []
    line = ""
    for char in text:
        if char == "\n":
            lines.append(line)
            line = ""
        else:
            if line and font.getlength(line + char) > width:
                lines.append(line)
                line = ""
            line += char
    return [*lines, line]


def _avatar(image: Image.Image, avatar: AvatarSpec, mouth: int) -> None:
    # Avatar.tsx's 220 × 240 flat geometry; quadratic paths sampled deterministically.
    scale = min(image.width * 0.32 / 220, image.height * 0.65 / 240)
    ox, oy = image.width * 0.045, image.height * 0.24
    draw = ImageDraw.Draw(image)
    palette = avatar.palette

    def point(x: float, y: float) -> tuple[float, float]:
        return ox + x * scale, oy + y * scale

    def curve(a: tuple[int, int], b: tuple[int, int], c: tuple[int, int]) -> list[tuple[float, float]]:
        return [
            point(
                (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * b[0] + t * t * c[0],
                (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * b[1] + t * t * c[1],
            )
            for t in (i / 32 for i in range(33))
        ]

    def ellipse(cx: int, cy: int, rx: int, ry: int, color: str) -> None:
        draw.ellipse((*point(cx - rx, cy - ry), *point(cx + rx, cy + ry)), fill=palette[color])

    draw.polygon(
        curve((25, 240), (25, 164), (110, 164)) + curve((110, 164), (195, 164), (195, 240)), fill=palette["outfit"]
    )
    draw.line(
        [point(90, 177), point(110, 204), point(130, 177)], fill=palette["accent"], width=max(1, round(8 * scale))
    )
    ellipse(110, 96, 68, 76, "hair")
    draw.rounded_rectangle((*point(94, 142), *point(126, 180)), radius=12 * scale, fill=palette["skin"])
    ellipse(110, 106, 57, 64, "skin")
    draw.polygon(
        curve((51, 86), (44, 23), (110, 24))
        + curve((110, 24), (179, 24), (170, 84))
        + [point(139, 61), point(119, 82), point(93, 57)],
        fill=palette["hair"],
    )
    for cx in (85, 135):
        ellipse(cx, 103, 5, 7, "hair")
    draw.line(curve((105, 119), (110, 126), (115, 119)), fill=palette["accent"], width=max(1, round(3 * scale)))
    if mouth == 0:
        draw.line(curve((96, 138), (110, 143), (124, 138)), fill=palette["hair"], width=max(1, round(3 * scale)))
    else:
        ellipse(110, (140, 141, 143)[mouth - 1], 11 + mouth, (3, 7, 12)[mouth - 1], "hair")


def ffmpeg_path() -> str:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise MediaError("找不到 ffmpeg，请用 brew install ffmpeg 或 sudo apt-get install ffmpeg 安装")
    return executable


def label_metadata(script: MediaScript) -> list[str]:
    return [
        "-metadata",
        f"comment=AI-generated; twin; source {script.source_fingerprint}",
        "-metadata",
        f"title={EXPLICIT_LABEL}",
    ]


def draw_badge(image: Image.Image, font_path: Path, color: str, *, bottom: bool = False) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    font = ImageFont.truetype(str(font_path), max(10, round(height * 0.028)))
    pad = max(1, round(width * 0.02))
    while font.size > 10 and font.getlength(EXPLICIT_LABEL) + 4 * pad > width:
        font = ImageFont.truetype(str(font_path), font.size - 1)
    if font.getlength(EXPLICIT_LABEL) + 4 * pad > width or font.size * 2 + 2 * pad > height:
        raise MediaError("视频尺寸过小，无法完整显示 AI 标识")
    badge_width = math.ceil(font.getlength(EXPLICIT_LABEL)) + 2 * pad
    top = height - pad - font.size * 2 if bottom else pad
    draw.rounded_rectangle((pad, top, pad + badge_width, top + font.size * 2), radius=pad / 3, fill=color)
    draw.text((pad * 2, top + font.size * 0.3), EXPLICIT_LABEL, font=font, fill="white")


def _draw_frame(
    avatar: AvatarSpec,
    text: str,
    mouth: int,
    font_path: Path,
    size: tuple[int, int],
    *,
    card: bool = False,
    show_avatar: bool = True,
) -> Image.Image:
    image = Image.new("RGB", size, avatar.palette["background"])
    if not card and show_avatar:
        _avatar(image, avatar, mouth)
    draw = ImageDraw.Draw(image)
    width, height = size
    draw_badge(image, font_path, avatar.palette["hair"])
    left = width * (0.08 if card or not show_avatar else 0.42)
    top, available_height = height * 0.25, height * 0.65
    font_size = max(10, round(height * 0.045))
    while True:
        font = ImageFont.truetype(str(font_path), font_size)
        lines = _wrap(text, font, width * 0.94 - left)
        if len(lines) * font_size * 1.5 <= available_height or font_size == 10:
            break
        font_size -= 1
    draw.multiline_text((left, top), "\n".join(lines), font=font, fill=avatar.palette["hair"], spacing=font_size // 2)
    return image


def _silence(path: Path, seconds: int) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\0\0" * 48000 * seconds)


def render_clip(
    script: MediaScript,
    synthesizer: SpeechSynthesizer,
    avatar: AvatarSpec,
    out_path: Path,
    *,
    font_path: str | Path | None = None,
    size: tuple[int, int] = (1280, 720),
    fps: int = 25,
) -> Path:
    ffmpeg = ffmpeg_path()
    font = _font_path(font_path)
    if fps <= 0 or any(n <= 0 or n % 2 for n in size):
        raise MediaError("视频尺寸须为正偶数，帧率须为正数")
    if sum(len(segment.text) for segment in script.segments) > 100_000:
        raise MediaInputTooLong("视频内容过长，请缩短回答")
    try:
        ImageFont.truetype(str(font), 20)
    except OSError:
        raise MediaError("无法读取中文字体，请检查 [media] font_path") from None
    out_path = Path(out_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cache_dir = out_path.parent / "media-cache"
        rendered = render_audio(script, synthesizer, cache_dir)
        with tempfile.TemporaryDirectory(dir=out_path.parent, prefix=".clip-") as directory:
            work = Path(directory)
            opening_seconds = (
                0
                if script.segments and script.segments[0].kind == "notice" and script.segments[0].text == OPENING_NOTICE
                else OPENING_SECONDS
            )
            ending = work / "ending.wav"
            _silence(ending, ENDING_SECONDS)
            files = []
            if opening_seconds:
                opening = work / "opening.wav"
                _silence(opening, opening_seconds)
                files.append(opening)
            timeline = []
            end = float(opening_seconds)
            texts = {segment.index: segment.text for segment in script.segments}
            for segment in rendered.segments:
                for part in segment.parts:
                    path = work / f"part-{len(files)}.wav"
                    subprocess.run(
                        [
                            ffmpeg,
                            "-v",
                            "error",
                            "-y",
                            "-i",
                            str(cache_dir / part.file_name),
                            "-vn",
                            "-ar",
                            "48000",
                            "-ac",
                            "1",
                            "-c:a",
                            "pcm_s16le",
                            str(path),
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    with wave.open(str(path), "rb") as audio:
                        duration = audio.getnframes() / audio.getframerate()
                    start = end
                    end += duration
                    if end + ENDING_SECONDS > 600:
                        raise MediaInputTooLong("视频不能超过 600 秒，请缩短回答")
                    timeline.append((start, end, texts[segment.index], part.lipsync))
                    files.append(path)
            files.append(ending)
            # Relative, generated filenames only: no quoting of user paths in the concat list.
            concat = work / "audio.txt"
            concat.write_text("".join(f"file '{path.name}'\n" for path in files), encoding="utf-8")
            frame_count = math.ceil((end + ENDING_SECONDS) * fps)
            temporary = work / "clip.mp4"
            command = [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{size[0]}x{size[1]}",
                "-r",
                str(fps),
                "-i",
                "-",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(concat),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-af",
                "apad",
                "-t",
                str(frame_count / fps),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "23",
                "-preset",
                "veryfast",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                *label_metadata(script),
                str(temporary),
            ]
            # A file captures stderr without filling a pipe while RGB frames are written.
            with (
                tempfile.TemporaryFile() as errors,
                subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=errors,
                ) as process,
            ):
                assert process.stdin is not None
                position = 0
                previous: tuple[str, int, bool] | None = None
                pixels = b""
                try:
                    for frame in range(frame_count):
                        time = frame / fps
                        while position < len(timeline) and time >= timeline[position][1]:
                            position += 1
                        card = time < opening_seconds or position == len(timeline)
                        mouth = 0
                        if time < opening_seconds:
                            text = OPENING_NOTICE
                        elif position == len(timeline):
                            # The current script contract carries no verbatim quotes or citation dates.
                            text = f"回答依据\n{EXPLICIT_LABEL}"
                        else:
                            start, _, text, track = timeline[position]
                            if track is not None:
                                index = math.floor((time - start) * track.fps)
                                mouth = track.levels[index] if 0 <= index < len(track.levels) else 0
                        key = (text, mouth, card)
                        if key != previous:
                            pixels = _draw_frame(
                                avatar, text, mouth, font, size, card=card, show_avatar=not script.abstain
                            ).tobytes()
                            previous = key
                        process.stdin.write(pixels)
                    process.stdin.close()
                    if process.wait() != 0:
                        raise MediaError("视频合成失败，请检查 ffmpeg 和媒体配置")
                finally:
                    process.stdin.close()
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            temporary.chmod(0o600)
            temporary.replace(out_path)
        return out_path
    except (OSError, subprocess.SubprocessError, wave.Error):
        raise MediaError("视频合成失败，请检查 ffmpeg、输出目录和媒体配置") from None
