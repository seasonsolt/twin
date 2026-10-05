"""Append-only avatar contracts, offline rendering, HTTP and browser lifecycle."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from twin.cli import CONFIG_TEMPLATE, app
from twin.config import AvatarSettings, Settings
from twin.identity import Identity
from twin.media.render import render_audio
from twin.media.schema import (
    AVATAR_PRESETS,
    EXPLICIT_LABEL,
    AudioManifest,
    AudioPart,
    AvatarSpec,
    LipSyncTrack,
    MediaScript,
    Segment,
    SpeechRequest,
    SpeechResult,
    WordTiming,
)
from twin.media.tts import SilentSynthesizer
from twin.web import create_app

STATIC = Path(__file__).resolve().parents[1] / "src" / "twin" / "web" / "static"


@pytest.fixture(autouse=True)
def own_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("TWIN_CONFIG", "DTWIN_CONFIG", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "values",
    [
        {"fps": 0},
        {"fps": -1},
        {"fps": 1.5},
        {"levels": [-1]},
        {"levels": [4]},
        {"levels": [1.5]},
        {"levels": [True]},
        {"source": "vendor"},
        {"extra": 1},
    ],
)
def test_track_ranges(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        LipSyncTrack.model_validate({"source": "pattern", **values})


def test_track_length_cap_frozen_and_roundtrip() -> None:
    track = LipSyncTrack(fps=2, levels=[0, 1, 2, 3] * 300, source="pattern")
    assert LipSyncTrack.model_validate_json(track.model_dump_json()) == track
    assert LipSyncTrack(source="energy").fps == 25
    with pytest.raises(ValidationError):
        LipSyncTrack(fps=2, levels=[0] * 1201, source="energy")
    with pytest.raises(ValidationError):
        track.fps = 3


def test_avatar_presets_fields_and_label() -> None:
    assert set(AVATAR_PRESETS) == {"default", "ink", "dawn"}
    assert set(AvatarSpec.model_fields) == {
        "schema_version",
        "avatar_id",
        "label",
        "palette",
        "mouth_states",
        "stylized",
    }
    assert AvatarSpec.model_fields["label"].annotation == MediaScript.model_fields["explicit_label"].annotation
    for name, preset in AVATAR_PRESETS.items():
        assert preset.avatar_id == name and preset.label == EXPLICIT_LABEL
        assert preset.stylized is True and preset.mouth_states == 4
        assert AvatarSpec.model_validate_json(preset.model_dump_json()) == preset
        with pytest.raises(ValidationError):
            preset.avatar_id = "changed"
        for extra in ("url", "path", "image"):
            with pytest.raises(ValidationError):
                AvatarSpec.model_validate({**preset.model_dump(), extra: "input"})
        for fields in (
            {"label": "unlabelled"},
            {"stylized": False},
            {"mouth_states": 5},
            {"palette": {"skin": "#ffffff"}},
            {"palette": {**preset.palette, "skin": "url(example)"}},
        ):
            with pytest.raises(ValidationError):
                AvatarSpec.model_validate({**preset.model_dump(), **fields})


def test_old_part_manifest_and_identity_load() -> None:
    part = AudioPart.model_validate_json('{"text":"合成","file_name":"old.wav"}')
    assert part.lipsync is None and part.model_dump(mode="json")["lipsync"] is None
    manifest = AudioManifest.model_validate_json(
        json.dumps(
            {
                "source_fingerprint": "invented",
                "created_at": "2026-01-01T00:00:00Z",
                "segments": [{"parts": [{"text": "合成", "file_name": "old.wav"}]}],
            }
        )
    )
    assert manifest.segments[0].parts[0].lipsync is None
    identity = Identity.model_validate_json('{"name":"合成人物","aliases":[],"consents":{}}')
    assert identity.avatar is None
    assert Identity.from_parts("合成人物", [], [], avatar="ink").avatar == "ink"


@pytest.mark.parametrize(
    "preset", ["unknown", "/photo.png", "https://example.invalid/face", "data:image/png;base64,abc"]
)
def test_config_rejects_nonpreset(preset: str) -> None:
    with pytest.raises(ValidationError) as error:
        AvatarSettings(preset=preset)
    message = str(error.value)
    assert all(name in message for name in AVATAR_PRESETS)
    assert "不支持照片或视频输入" in message and "M4" in message
    assert Settings().avatar.preset == "default"


class TimedSynthesizer(SilentSynthesizer):
    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        result = super().synthesize(request)
        return result.model_copy(update={"timings": [WordTiming(text="合成", start_s=0, end_s=result.duration_s or 1)]})


@pytest.mark.parametrize("timed", [False, True])
def test_render_attaches_tracks_to_every_part_and_cache(tmp_path: Path, timed: bool) -> None:
    synth = TimedSynthesizer(max_chars=8) if timed else SilentSynthesizer(max_chars=8)
    script = MediaScript(
        source_kind="chat_reply",
        source_fingerprint="invented",
        persona_name="合成人物",
        as_of=None,
        confidence=0.8,
        abstain=False,
        segments=[
            Segment(index=0, kind="notice", text="合成提示。"),
            Segment(index=1, kind="speech", text="先验证生成内容。再继续推进。"),
        ],
        citations=[],
    )
    output = render_audio(script, synth, tmp_path / "cache")
    parts = [part for segment in output.segments for part in segment.parts]
    assert len(parts) > 2
    for part in parts:
        assert part.lipsync is not None
        assert part.lipsync.source == ("timings" if timed else "energy")
        assert any(part.lipsync.levels) is timed
    manifest = AudioManifest.model_validate_json((tmp_path / "cache" / output.manifest_file).read_bytes())
    assert manifest.segments == output.segments
    assert render_audio(script, synth, tmp_path / "cache").segments == output.segments


def test_http_avatar_audio_and_identity(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", avatar=AvatarSettings(preset="dawn"))
    body = {
        "kind": "chat_reply",
        "answer": {
            "reply": "先验证。",
            "citations": [],
            "confidence": 0.8,
            "abstain": False,
            "abstain_reason": "",
            "retrieved_ids": [],
        },
    }
    with TestClient(create_app(settings, synthesizer_factory=SilentSynthesizer), base_url="http://localhost") as client:
        capabilities = client.get("/api/media/capabilities").json()
        assert capabilities["available"] is False
        assert capabilities["avatar"] == AVATAR_PRESETS["dawn"].model_dump(mode="json")
        assert client.get("/api/identity").json()["avatar"] == "dawn"
        response = client.post("/api/media/audio", json=body, headers={"X-Twin": "1"})
        assert response.status_code == 200
        result = response.json()
        assert result["segments"]
        for segment in result["segments"]:
            assert segment["lipsync"]["source"] == "energy"
            assert set(segment["lipsync"]["levels"]) == {0}


def test_avatar_remains_available_when_speech_fails(tmp_path: Path) -> None:
    def factory() -> SilentSynthesizer:
        raise ValueError("invalid offline config")

    with TestClient(
        create_app(Settings(db_path=tmp_path / "twin.db"), synthesizer_factory=factory), base_url="http://localhost"
    ) as client:
        result = client.get("/api/media/capabilities").json()
        assert result["available"] is False
        assert result["avatar"] == AVATAR_PRESETS["default"].model_dump(mode="json")


def test_identity_show_and_init_template(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text(f'db_path = "{tmp_path / "twin.db"}"\n[avatar]\npreset = "ink"\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["--config", str(config), "identity", "show"])
    assert result.exit_code == 0, result.output
    assert "形象：ink（风格化插画，不使用照片）" in result.output
    example = (STATIC.parents[3] / "twin.toml.example").read_text(encoding="utf-8")
    for template in (CONFIG_TEMPLATE, example):
        assert (
            "# [avatar] # 风格化插画，不支持照片或视频输入（M4 门槛）。\n"
            '# preset = "default" # 可选 default、ink、dawn。' in template
        )


def test_avatar_static_has_no_assets_or_copied_label() -> None:
    source = (STATIC / "avatar.js").read_text(encoding="utf-8")
    for forbidden in ("<image", "url(", "http", "data:", "innerHTML", EXPLICIT_LABEL):
        assert forbidden not in source
    assert "spec.label" in source


AVATAR_HARNESS = r"""
import assert from 'node:assert/strict';
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.events = new Map(); this.text = ''; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...items) {
    for (const item of items) { this.children.push(item); if (item instanceof Element) item.parent = this; }
  }
  replaceChildren(...items) { this.children = []; this.text = ''; this.append(...items); }
  addEventListener(k, fn) { if (!this.events.has(k)) this.events.set(k, new Set()); this.events.get(k).add(fn); }
  removeEventListener(k, fn) { this.events.get(k)?.delete(fn); }
  emit(k, e = {}) { for (const fn of this.events.get(k) ?? []) fn({target: this, currentTarget: this, ...e}); }
  get textContent() { return this.text + this.children.map(c => c instanceof Element ? c.textContent : c).join(''); }
  set textContent(v) { this.text = v; this.children = []; }
  get isConnected() { return this === document.body || Boolean(this.parent?.isConnected); }
  focus() { document.focused = this; }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit('close'); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); this.parent = null; }
  click() { this.emit('click'); }
}
let audio;
class Audio extends Element {
  constructor() { super('audio'); this.paused = true; this.currentTime = 0; this.ended = false; }
  play() { this.paused = false; this.ended = false; this.emit('playing'); return Promise.resolve(); }
  pause() { this.paused = true; this.emit('pause'); }
  load() {}
}
globalThis.Node = Element;
globalThis.document = {body: new Element('body'),
  createElement: tag => tag === 'audio' ? (audio = new Audio()) : new Element(tag),
  createElementNS: (ns, tag) => { assert.equal(ns, 'http://www.w3.org/2000/svg'); return new Element(tag); }};
const media = new Element('media'); media.matches = false;
globalThis.window = {matchMedia: () => media};
let sequence = 0;
const timers = new Map(), frames = new Map();
globalThis.setTimeout = (fn, ms) => { const id = ++sequence; timers.set(id, {fn, ms}); return id; };
globalThis.clearTimeout = id => timers.delete(id);
globalThis.requestAnimationFrame = fn => { const id = ++sequence; frames.set(id, fn); return id; };
globalThis.cancelAnimationFrame = id => frames.delete(id);
const descendants = node => [node, ...node.children.filter(c => c instanceof Element).flatMap(descendants)];
const mouths = root => descendants(root).filter(e => e.attrs.visibility !== undefined);
const mouth = root => mouths(root).findIndex(e => e.attrs.visibility === 'visible');
const eyes = root => descendants(root).filter(e => e.attrs.cy === '103');
const {createAvatar} = await import('./avatar.js');
const spec = JSON.parse(process.env.TEST_AVATAR_SPEC);
let avatar = createAvatar(spec); document.body.append(avatar);
assert.equal(mouth(avatar), 0);
assert.ok(avatar.textContent.includes(spec.label));
assert.equal(mouths(avatar).length, 4);
assert.equal(descendants(avatar).some(e => e.tag === 'image'), false);
for (let i = 0; i < 4; i++) { avatar.setMouth(i); assert.equal(mouth(avatar), i); }
avatar.setMouth(100); assert.equal(mouth(avatar), 3);
avatar.setMouth(-5); assert.equal(mouth(avatar), 0);
let [id, timer] = [...timers][0];
assert.ok(timer.ms >= 3000 && timer.ms <= 6000); timers.delete(id); timer.fn();
assert.ok(eyes(avatar).every(e => e.attrs.ry === '1'));
media.matches = true; media.emit('change');
assert.equal(timers.size, 0); assert.ok(eyes(avatar).every(e => e.attrs.ry === '7'));
avatar.setMouth(3); assert.equal(mouth(avatar), 1);
avatar.setMouth(0); assert.equal(mouth(avatar), 0);
assert.ok(avatar.textContent.includes(spec.label));
media.matches = false; media.emit('change'); assert.equal(timers.size, 1);
avatar.destroy(); assert.equal(timers.size, 0); assert.equal(media.events.get('change').size, 0);
const script = {persona_name: '合成人物', explicit_label: spec.label, abstain: false,
  segments: [{index: 0, kind: 'notice', text: '提示'}, {index: 1, kind: 'speech', text: '正文'}], citations: []};
const parts = [{index: 0, url: '/api/media/audio/notice.wav', lipsync: {fps: 10, levels: [0, 2, 3, 1]}},
  {index: 1, url: '/api/media/audio/body.wav', lipsync: {fps: 10, levels: [3, 2]}},
  {index: 1, url: '/api/media/audio/old.wav', lipsync: null}];
globalThis.fetch = async path => ({ok: true, text: async () => JSON.stringify(
  path.endsWith('capabilities') ? {available: true, avatar: spec}
    : path.endsWith('audio') ? {segments: parts} : script)});
const {playbackAction, closePlayback} = await import('./playback.js');
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise(resolve => setImmediate(resolve)); };
const button = (panel, text) => descendants(panel).find(e => e.tag === 'button' && e.textContent === text);
const runFrame = () => { const [id, fn] = [...frames][0]; frames.delete(id); fn(); };
async function open() {
  const trigger = playbackAction({}, '合成人物'); document.body.append(trigger); trigger.click(); await settle();
  const panel = document.body.children.find(e => e.tag === 'dialog');
  avatar = descendants(panel).find(e => e.className === 'playback-avatar');
  assert.ok(avatar); assert.ok(avatar.textContent.includes(spec.label)); return panel;
}
let panel = await open();
assert.equal(mouth(avatar), 0);
button(panel, '播放').click(); assert.equal(mouth(avatar), 0); assert.equal(frames.size, 0);
button(panel, '暂停').click();
button(panel, '朗读').click(); await settle();
assert.equal(frames.size, 1);
audio.currentTime = 0.1; runFrame(); assert.equal(mouth(avatar), 2);
audio.currentTime = 0.2; runFrame(); assert.equal(mouth(avatar), 3);
button(panel, '暂停').click(); assert.equal(mouth(avatar), 0); assert.equal(frames.size, 0);
assert.equal(audio.currentTime, 0.2);
button(panel, '播放').click(); assert.equal(mouth(avatar), 3); assert.equal(frames.size, 1);
audio.emit('waiting'); assert.equal(frames.size, 0); assert.equal(mouth(avatar), 0);
audio.emit('playing'); assert.equal(mouth(avatar), 3);
audio.currentTime = 10; runFrame(); assert.equal(mouth(avatar), 0);
audio.emit('ended'); assert.equal(audio.getAttribute('src'), parts[1].url);
assert.equal(mouth(avatar), 3); assert.equal(frames.size, 1);
audio.emit('ended'); assert.equal(audio.getAttribute('src'), parts[2].url);
assert.equal(mouth(avatar), 0); assert.equal(frames.size, 0);
closePlayback(); assert.equal(timers.size, 0); assert.equal(frames.size, 0);
assert.equal(media.events.get('change').size, 0);
media.matches = true; panel = await open();
assert.equal(timers.size, 0);
button(panel, '朗读').click(); await settle(); audio.currentTime = 0.2; runFrame();
assert.equal(mouth(avatar), 1); assert.equal(timers.size, 0);
media.matches = false; media.emit('change');
assert.equal(mouth(avatar), 0); assert.equal(frames.size, 0);
button(panel, '播放').click(); assert.equal(mouth(avatar), 3);
closePlayback(); assert.equal(frames.size, 0); assert.equal(timers.size, 0);
// Closing while the API is pending must never create an avatar or animation.
let finish;
fetch = async path => ({ok: true, text: async () => path.endsWith('capabilities')
  ? await new Promise(resolve => {finish = resolve;}) : JSON.stringify(script)});
const trigger = playbackAction({}, '合成人物'); document.body.append(trigger); trigger.click(); await settle();
closePlayback(); finish(JSON.stringify({available: true, avatar: spec})); await settle();
assert.equal(timers.size, 0); assert.equal(frames.size, 0);
console.log('Avatar and playback lifecycle checks passed');
"""


def test_avatar_and_playback_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for offline browser checks")
    for name in ("avatar.js", "playback.js", "api.js", "dom.js", "state.js"):
        shutil.copyfile(STATIC / name, tmp_path / name)
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (tmp_path / "harness.mjs").write_text(AVATAR_HARNESS, encoding="utf-8")
    monkeypatch.setenv("TEST_AVATAR_SPEC", AVATAR_PRESETS["ink"].model_dump_json())
    result = subprocess.run([node, "harness.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
