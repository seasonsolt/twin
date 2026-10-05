import { api, errorBox } from "./api.js";
import { h, loading } from "./dom.js";

let activePanel = null;

export function closePlayback() {
  activePanel?.close();
}

export function playbackAction(answer, personaName) {
  return h("button", {
    type: "button", class: "btn", onclick: (event) => openPlayback(answer, personaName, event.currentTarget),
  }, "回放");
}

async function openPlayback(answer, personaName, trigger) {
  closePlayback();
  const body = { kind: "chat_reply", answer, persona_name: personaName };
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  let timer = null;
  let playing = false;
  let position = 0;
  let script = null;
  let audio = null;
  let audioSegments = null;
  let audioRequest = null;
  let speaking = false;
  let partPosition = 0;
  let playbackVersion = 0;
  const label = h("p", { class: "media-label", role: "note" }, "AI 合成 · 模拟推演，不代表本人意见");
  const content = h("div", null, loading("正在准备回放…"));
  const close = h("button", { type: "button", class: "btn", onclick: () => panel.close() }, "关闭");
  const panel = h("dialog", { class: "playback-panel", "aria-label": "模拟推演回放" },
    h("div", { class: "playback-head" }, label, close), content);
  activePanel = panel;
  document.body.append(panel);

  function stop(reset = false) {
    clearTimeout(timer);
    timer = null;
    playing = false;
    playbackVersion += 1;
    audio?.pause();
    if (reset && audio) {
      audio.currentTime = 0;
      partPosition = 0;
    }
    if (script) play.textContent = reduced.matches && !speaking ? "手动逐句回放" : "播放";
  }
  function schedule() {
    clearTimeout(timer);
    if (!playing || speaking || reduced.matches || !panel.open) return;
    timer = setTimeout(() => {
      if (!panel.isConnected || !panel.open) return stop();
      if (position >= script.segments.length - 1) return stop();
      position += 1;
      render();
      schedule();
    }, Math.max(1500, Array.from(script.segments[position].text).length * 240));
  }
  function step(delta) {
    stop(true);
    position = Math.max(0, Math.min(script.segments.length - 1, position + delta));
    if (audio) audio.removeAttribute("src");
    render();
  }
  function toggle() {
    if (!script || (reduced.matches && !speaking)) return;
    if (playing) return stop();
    if (position === script.segments.length - 1 && !speaking) position = 0;
    playing = true;
    play.textContent = "暂停";
    render();
    if (speaking) speakCurrent();
    else schedule();
  }
  const play = h("button", { type: "button", class: "btn primary", onclick: toggle }, "播放");
  const prev = h("button", { type: "button", class: "btn", onclick: () => step(-1) }, "上一句");
  const next = h("button", { type: "button", class: "btn", onclick: () => step(1) }, "下一句");
  const current = h("p", { class: "playback-current", "aria-live": "polite", "aria-atomic": "true" });
  const progress = h("p", { class: "muted small" });
  const transcript = h("ol", { class: "playback-transcript", "aria-label": "已展示的句子" });
  const error = h("div");
  const voiceControls = h("div", { class: "playback-voice" });
  const voiceNotice = h("p", { class: "muted small", role: "status" });
  const voiceToggle = h("button", { type: "button", class: "btn", "aria-pressed": "false", onclick: toggleVoice }, "朗读");

  function audioFailed() {
    if (!speaking || !panel.open) return;
    const resume = playing;
    stop(true);
    speaking = false;
    voiceToggle.setAttribute("aria-pressed", "false");
    voiceNotice.textContent = "语音暂不可用，已切换为文字回放。";
    play.disabled = reduced.matches;
    play.textContent = reduced.matches ? "手动逐句回放" : "播放";
    if (resume && !reduced.matches) {
      playing = true;
      play.textContent = "暂停";
      schedule();
    }
  }
  function speakCurrent() {
    if (!playing || !speaking || !audioSegments || !panel.open) return;
    const parts = audioSegments.filter(segment => segment.index === script.segments[position].index);
    const part = parts[partPosition];
    if (!part) return audioFailed();
    if (audio.getAttribute("src") !== part.url) {
      audio.setAttribute("src", part.url);
      audio.currentTime = 0;
    }
    const version = ++playbackVersion;
    try {
      Promise.resolve(audio.play()).catch(() => {
        if (version === playbackVersion) audioFailed();
      });
    } catch {
      if (version === playbackVersion) audioFailed();
    }
  }
  async function toggleVoice() {
    stop(true);
    speaking = !speaking;
    voiceToggle.setAttribute("aria-pressed", String(speaking));
    play.disabled = reduced.matches && !speaking;
    play.textContent = reduced.matches && !speaking ? "手动逐句回放" : "播放";
    if (!speaking) return;
    position = 0;
    render();
    if (!audio) {
      audio = document.createElement("audio");
      audio.preload = "auto";
      audio.addEventListener("error", audioFailed);
      audio.addEventListener("ended", () => {
        if (!playing || !speaking || !panel.open) return;
        const parts = audioSegments.filter(segment => segment.index === script.segments[position].index);
        if (partPosition < parts.length - 1) partPosition += 1;
        else {
          if (position === script.segments.length - 1) return stop(true);
          position += 1;
          partPosition = 0;
          render();
        }
        speakCurrent();
      });
    }
    audio.removeAttribute("src");
    playing = true;
    play.textContent = "暂停";
    playbackVersion += 1;
    try {
      audioRequest ??= api("/api/media/audio", { method: "POST", json: body });
      const result = await audioRequest;
      if (!panel.open) return;
      audioSegments = result.segments;
      if (speaking && playing) speakCurrent();
    } catch {
      audioFailed();
    }
  }
  const download = h("button", { type: "button", class: "btn", onclick: async () => {
    download.disabled = true;
    error.replaceChildren();
    try {
      const html = await api("/api/media/export", { method: "POST", json: body });
      if (!panel.open) return;
      const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
      const link = h("a", { href: url, download: "twin-media.html" });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      if (panel.open) error.replaceChildren(errorBox(err, { title: "导出失败" }));
    } finally {
      download.disabled = false;
    }
  } }, "导出");

  function render() {
    current.textContent = script.segments[position].text;
    progress.textContent = `${position + 1} / ${script.segments.length}${script.abstain ? " · 分身弃权，仅展示提示" : ""}`;
    prev.disabled = position === 0;
    next.disabled = position === script.segments.length - 1;
    transcript.replaceChildren(...script.segments.slice(0, position + 1).map((segment, index) =>
      h("li", { class: index === position ? "is-current" : null, "aria-current": index === position ? "step" : null }, segment.text)));
  }
  function motionChanged() {
    stop();
    play.disabled = reduced.matches && !speaking;
  }
  reduced.addEventListener("change", motionChanged);
  panel.addEventListener("keydown", (event) => {
    if (!script || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      step(event.key === "ArrowLeft" ? -1 : 1);
    } else if (event.key === " " && event.target === panel) {
      event.preventDefault();
      toggle();
    }
  });
  panel.tabIndex = -1;
  panel.addEventListener("close", () => {
    stop(true);
    audio?.removeAttribute("src");
    audio?.load();
    reduced.removeEventListener("change", motionChanged);
    panel.remove();
    if (activePanel === panel) activePanel = null;
    if (trigger.isConnected) trigger.focus();
  }, { once: true });
  panel.showModal();
  panel.focus();
  try {
    const { segments, citations, abstain, explicit_label: explicitLabel, persona_name: personaName } =
      await api("/api/media/script", { method: "POST", json: body });
    if (!panel.open) return;
    script = { segments, citations, abstain };
    label.textContent = explicitLabel;
    content.replaceChildren(
      h("h2", null, `${personaName} · 模拟推演回放`),
      h("p", { class: "help" }, "空格播放 / 暂停，左右方向键逐句切换；减少动态效果时仅朗读可自动推进。"),
      h("div", { class: "btn-row" }, play, prev, next, download), voiceControls, voiceNotice, progress, current, transcript,
      h("h3", null, "回答依据"),
      h("p", { class: "help" }, "引用属于整份回答，不代表逐句对应；原话与出处可在原回答中展开查看。"),
      script.citations.length ? h("ul", null, script.citations.map((citation) =>
        h("li", null, citation.ref_id, citation.reason ? `：${citation.reason}` : ""))) : h("p", { class: "muted" }, "没有有效引用。"),
      error,
    );
    motionChanged();
    render();
    try {
      const capabilities = await api("/api/media/capabilities");
      if (panel.open && capabilities.available) {
        voiceControls.append(voiceToggle, h("span", { class: "muted small" }, `语音由 AI 合成（${capabilities.backend}）`));
      }
    } catch {
      voiceNotice.textContent = "语音暂不可用，可继续文字回放。";
    }
  } catch (err) {
    if (panel.open) content.replaceChildren(errorBox(err, { title: "无法准备回放" }));
  }
}
