"""Offline JS unit test of playback controls, timing, lifecycle and reduced motion."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "twin" / "web" / "static"

HARNESS = r"""
import assert from 'node:assert/strict';
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.events = {}; this.text = ''; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...children) {
    for (const child of children) { this.children.push(child); if (child instanceof Element) child.parent = this; }
  }
  replaceChildren(...children) { this.children = []; this.text = ''; this.append(...children); }
  addEventListener(k, fn) { (this.events[k] ??= []).push(fn); }
  emit(k, event = {}) { for (const fn of this.events[k] ?? []) fn({ target: this, currentTarget: this, ...event }); }
  get textContent() { return this.text + this.children.map(c => c instanceof Element ? c.textContent : c).join(''); }
  set textContent(v) { this.text = v; this.children = []; }
  get isConnected() { return this === document.body || Boolean(this.parent?.isConnected); }
  focus() { document.focused = this; }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit('close'); }
  remove() { this.parent.children = this.parent.children.filter(c => c !== this); this.parent = null; }
  click() { this.emit('click'); }
}
globalThis.Node = Element;
globalThis.document = { body: new Element('body'), createElement: tag => new Element(tag) };
let reduced = false;
const media = { get matches() { return reduced; }, addEventListener(k, fn) { this.fn = fn; },
  removeEventListener() { this.fn = null; } };
globalThis.window = { matchMedia: () => media };
let sequence = 0;
const timers = new Map();
globalThis.setTimeout = (fn, ms) => { timers.set(++sequence, {fn, ms}); return sequence; };
globalThis.clearTimeout = id => timers.delete(id);
const script = { persona_name: '合成人物', explicit_label: 'AI 合成 · 模拟推演，不代表本人意见', abstain: false,
  segments: [{text: '合成提示', kind: 'notice'}, {text: '<script>alert(1)</script>。', kind: 'speech'},
    {text: '很长的句子'.repeat(20), kind: 'speech'}], citations: [{ref_id: 'it_example', reason: '理由'}] };
const requests = [];
globalThis.fetch = async (path, init) => {
  requests.push([path, init]);
  return { ok: true, text: async () => path.endsWith('export')
    ? '<!doctype html><p>导出</p>' : JSON.stringify(script) };
};
const blobs = [];
URL.createObjectURL = blob => { blobs.push(blob); return 'blob:example'; };
URL.revokeObjectURL = () => {};
const {state} = await import('./state.js');
state.status = {labels: {explicit: '服务端提供的统一标识'}};
const {playbackAction, closePlayback} = await import('./playback.js');
const settle = () => new Promise(resolve => setImmediate(resolve));
const descendants = node => [node, ...node.children.filter(c => c instanceof Element).flatMap(descendants)];
const button = (panel, text) => descendants(panel).find(e => e.tag === 'button' && e.textContent === text);
const current = panel => descendants(panel).find(e => e.className === 'playback-current');
const transcript = panel => descendants(panel).find(e => e.className === 'playback-transcript');
const key = (panel, value) => panel.emit('keydown', {key: value, preventDefault() {}});
async function open() {
  const action = playbackAction({in_voice: '原回答'}, '合成人物');
  document.body.append(action); action.click(); await settle();
  return [action, document.body.children.find(e => e.tag === 'dialog')];
}
let [action, panel] = await open();
assert.equal(panel.open, true);
assert.ok(panel.textContent.includes(state.status.labels.explicit));
assert.equal(panel.textContent.includes(script.explicit_label), false);
assert.ok(panel.textContent.includes(script.persona_name));
assert.ok(panel.textContent.includes(script.citations[0].ref_id));
assert.ok(panel.textContent.includes(script.citations[0].reason));
assert.equal(current(panel).attrs['aria-live'], 'polite');
assert.equal(current(panel).textContent, '合成提示');
assert.equal(transcript(panel).children.length, 1);
assert.equal(button(panel, '上一句').disabled, true);
assert.equal(timers.size, 0);
key(panel, 'ArrowRight');
assert.equal(current(panel).textContent, script.segments[1].text);
assert.equal(transcript(panel).children.length, 2);
assert.equal(transcript(panel).children.at(-1).attrs['aria-current'], 'step');
assert.equal(descendants(panel).some(e => e.tag === 'script'), false);
key(panel, ' ');
assert.ok(button(panel, '暂停'));
let [id, timer] = [...timers][0];
assert.equal(timer.ms, Math.max(1500, Array.from(script.segments[1].text).length * 240));
timers.delete(id); timer.fn();
assert.equal(current(panel).textContent, script.segments[2].text);
assert.equal(button(panel, '下一句').disabled, true);
assert.equal([...timers.values()][0].ms, Array.from(script.segments[2].text).length * 240);
button(panel, '暂停').click(); assert.equal(timers.size, 0);
button(panel, '上一句').click(); assert.equal(current(panel).textContent, script.segments[1].text);
button(panel, '导出').click(); await settle();
assert.equal(blobs.length, 1);
assert.ok((await blobs[0].text()).includes('导出'));
for (const timer of timers.values()) timer.fn();
timers.clear();
button(panel, '播放').click();
reduced = true; media.fn();
assert.equal(timers.size, 0);
assert.equal(button(panel, '手动逐句回放').disabled, true);
reduced = false; media.fn();
assert.equal(button(panel, '播放').disabled, false);
for (const [path, init] of requests) {
  if (init.method === 'GET') { assert.equal(path, '/api/media/capabilities'); continue; }
  assert.equal(init.headers['X-Twin'], '1'); assert.equal(init.cache, 'no-store');
  assert.equal(JSON.parse(init.body).persona_name, '合成人物');
}
closePlayback(); assert.equal(panel.isConnected, false); assert.equal(document.focused, action);
reduced = true;
[action, panel] = await open();
assert.equal(button(panel, '手动逐句回放').disabled, true);
key(panel, ' '); assert.equal(timers.size, 0);
key(panel, 'ArrowRight'); assert.equal(current(panel).textContent, script.segments[1].text);
closePlayback();
script.abstain = true;
script.segments = [{text: '合成提示', kind: 'notice'}, {text: '依据不足', kind: 'notice'}];
[action, panel] = await open();
key(panel, 'ArrowRight'); assert.equal(current(panel).textContent, '依据不足');
assert.equal(button(panel, '下一句').disabled, true);
assert.ok(panel.textContent.includes('分身弃权，仅展示提示'));
closePlayback();
console.log('Playback unit checks passed');

const audios = [];
let rejectPlay = false;
class AudioElement extends Element {
  constructor() { super('audio'); this.currentTime = 0; this.playCalls = 0; this.paused = true; audios.push(this); }
  getAttribute(key) { return this.attrs[key]; }
  removeAttribute(key) { delete this.attrs[key]; }
  play() {
    this.playCalls++; this.paused = false;
    return rejectPlay ? Promise.reject(new Error('offline')) : Promise.resolve();
  }
  pause() { this.paused = true; }
  load() { this.loaded = true; }
}
document.createElement = tag => tag === 'audio' ? new AudioElement() : new Element(tag);
let speechRequests = 0;
let audioFailure = false;
const audioParts = [
  {index: 0, url: '/api/media/audio/notice.wav'},
  {index: 1, url: '/api/media/audio/part1.wav'},
  {index: 1, url: '/api/media/audio/part2.wav'},
  {index: 2, url: '/api/media/audio/last.wav'},
];
fetch = async (path, init) => {
  requests.push([path, init]);
  let value = script;
  if (path.endsWith('capabilities')) value = {available: true, backend: 'test-speech'};
  if (path.endsWith('audio')) {
    speechRequests++;
    if (audioFailure) throw new Error('offline');
    value = {segments: audioParts};
  }
  return {ok: true, text: async () => JSON.stringify(value)};
};
script.abstain = false;
script.segments = [{index: 0, kind: 'notice', text: '合成提示'},
  {index: 1, kind: 'speech', text: '第一句。'}, {index: 2, kind: 'speech', text: '第二句。'}];
reduced = true;
[action, panel] = await open();
assert.ok(panel.textContent.includes('语音由 AI 合成（test-speech）'));
assert.equal(speechRequests, 0);
button(panel, '朗读').click(); await settle();
let audio = audios.at(-1);
assert.equal(speechRequests, 1);
assert.equal(audio.getAttribute('src'), audioParts[0].url);
assert.equal(current(panel).textContent, '合成提示');
assert.ok(button(panel, '暂停'));
assert.equal(timers.size, 0);
audio.emit('ended');
assert.equal(current(panel).textContent, '第一句。');
assert.equal(audio.getAttribute('src'), audioParts[1].url);
audio.emit('ended');
assert.equal(current(panel).textContent, '第一句。');
assert.equal(audio.getAttribute('src'), audioParts[2].url);
audio.currentTime = 0.7;
key(panel, ' ');
assert.equal(audio.paused, true);
assert.equal(audio.currentTime, 0.7);
key(panel, ' ');
assert.equal(audio.currentTime, 0.7);
audio.emit('ended');
assert.equal(current(panel).textContent, '第二句。');
audio.emit('ended');
assert.equal(audio.paused, true);
assert.equal(timers.size, 0);
key(panel, 'ArrowLeft');
assert.equal(current(panel).textContent, '第一句。');
assert.equal(audio.currentTime, 0);
key(panel, ' ');
assert.equal(audio.getAttribute('src'), audioParts[1].url);
button(panel, '朗读').click();
assert.equal(audio.paused, true);
assert.equal(button(panel, '手动逐句回放').disabled, true);
button(panel, '朗读').click(); await settle();
assert.equal(speechRequests, 1);
assert.equal(audio.getAttribute('src'), audioParts[0].url);
audio.emit('error');
assert.ok(panel.textContent.includes('已切换为文字回放'));
assert.equal(timers.size, 0);
assert.equal(audio.paused, true);
closePlayback();
assert.equal(audio.getAttribute('src'), undefined);
assert.equal(audio.loaded, true);
assert.equal(document.focused, action);

reduced = false;
rejectPlay = true;
[action, panel] = await open();
button(panel, '朗读').click(); await settle();
assert.ok(panel.textContent.includes('已切换为文字回放'));
assert.equal(audios.at(-1).paused, true);
assert.ok(timers.size > 0);
closePlayback();
assert.equal(timers.size, 0);
rejectPlay = false;
audioFailure = true;
[action, panel] = await open();
button(panel, '朗读').click(); await settle();
assert.ok(panel.textContent.includes('已切换为文字回放'));
closePlayback();

let finishAudio;
fetch = async path => ({ok: true, text: async () => {
  if (path.endsWith('audio')) return await new Promise(resolve => { finishAudio = resolve; });
  return JSON.stringify(path.endsWith('capabilities') ? {available: true, backend: 'test-speech'} : script);
}});
[action, panel] = await open();
button(panel, '朗读').click(); await settle();
audio = audios.at(-1);
closePlayback();
finishAudio(JSON.stringify({segments: audioParts})); await settle();
assert.equal(audio.playCalls, 0);
assert.equal(timers.size, 0);

[action, panel] = await open();
button(panel, '朗读').click(); await settle();
audio = audios.at(-1);
key(panel, ' ');
finishAudio(JSON.stringify({segments: audioParts})); await settle();
assert.equal(audio.playCalls, 0);
key(panel, ' '); await settle();
assert.equal(audio.playCalls, 1);
assert.equal(audio.getAttribute('src'), audioParts[0].url);
assert.equal(current(panel).textContent, '合成提示');
closePlayback();
assert.equal(timers.size, 0);
console.log('Speech playback unit checks passed');
"""


def test_playback_controls(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for offline frontend unit checks")
    for name in ("playback.js", "api.js", "dom.js", "state.js"):
        shutil.copyfile(STATIC / name, tmp_path / name)
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (tmp_path / "harness.mjs").write_text(HARNESS, encoding="utf-8")
    result = subprocess.run([node, "harness.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
