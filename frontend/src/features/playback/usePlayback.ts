import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { toast } from '../../components/ui';
import type { ChatReply } from '../chat/types';
import type { AudioPart, Capabilities, MediaScript } from './types';

interface PlaybackView {
  script: MediaScript | null;
  capabilities: Capabilities | null;
  position: number;
  playing: boolean;
  speaking: boolean;
  voiceLoading: boolean;
  exporting: boolean;
  exportingVideo: boolean;
  error: string;
  voiceNotice: string;
}
const initial: PlaybackView = {
  script: null,
  capabilities: null,
  position: 0,
  playing: false,
  speaking: false,
  voiceLoading: false,
  exporting: false,
  exportingVideo: false,
  error: '',
  voiceNotice: '',
};
const noActions = {
  toggle() {},
  step(_delta: number) {
    void _delta;
  },
  voice() {},
  export() {},
  exportVideo() {},
  retry() {},
  stop() {},
};
const message = (error: unknown) =>
  error instanceof Error ? error.message : '请求失败，请重试';

export function usePlayback(
  open: boolean,
  answer: ChatReply,
  personaName: string,
  reduced: boolean,
) {
  const [view, setView] = useState(initial);
  const [mouth, setMouth] = useState(0);
  const actions = useRef(noActions);
  const reducedRef = useRef(reduced);
  useEffect(() => {
    reducedRef.current = reduced;
    actions.current.stop();
  }, [reduced]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const body = { kind: 'chat_reply', answer, persona_name: personaName };
    let alive = true;
    let state = { ...initial };
    let timer: ReturnType<typeof setTimeout> | undefined;
    let frame: number | null = null;
    let audio: HTMLAudioElement | null = null;
    let parts: AudioPart[] | null = null;
    let audioRequest: Promise<{ segments: AudioPart[] }> | null = null;
    let currentPart: AudioPart | null = null;
    let partPosition = 0;
    let version = 0;
    const downloads = new Map<string, ReturnType<typeof setTimeout>>();
    const publish = (patch: Partial<PlaybackView> = {}) => {
      state = { ...state, ...patch };
      if (alive) setView(state);
    };
    publish();
    setMouth(0);
    const stopMouth = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      if (alive) setMouth(0);
    };
    const driveMouth = () => {
      stopMouth();
      const tick = () => {
        frame = null;
        if (
          !alive ||
          !audio ||
          !state.playing ||
          !state.speaking ||
          audio.paused ||
          audio.ended
        ) {
          if (alive) setMouth(0);
          return;
        }
        const track = currentPart?.lipsync;
        const level =
          track?.levels[Math.floor(audio.currentTime * track.fps)] ?? 0;
        setMouth(reducedRef.current ? Math.min(1, level) : level);
        frame = requestAnimationFrame(tick);
      };
      tick();
    };
    const stop = (reset = false) => {
      version += 1;
      clearTimeout(timer);
      stopMouth();
      audio?.pause();
      if (reset) {
        partPosition = 0;
        if (audio) audio.currentTime = 0;
      }
      publish({ playing: false });
    };
    const schedule = () => {
      clearTimeout(timer);
      if (
        !alive ||
        !state.script ||
        !state.playing ||
        state.speaking ||
        reducedRef.current
      )
        return;
      timer = setTimeout(
        () => {
          if (!alive || !state.script) return;
          if (state.position >= state.script.segments.length - 1) return stop();
          publish({ position: state.position + 1 });
          schedule();
        },
        Math.max(
          1500,
          Array.from(state.script.segments[state.position].text).length * 240,
        ),
      );
    };
    const audioFailed = (detail = '语音暂不可用') => {
      if (!alive || !state.speaking) return;
      const resume = state.playing;
      stop(true);
      publish({
        speaking: false,
        voiceLoading: false,
        voiceNotice: `${detail}，已切换为文字回放。`,
      });
      if (resume && !reducedRef.current) {
        publish({ playing: true });
        schedule();
      }
    };
    const speakCurrent = () => {
      if (
        !alive ||
        !audio ||
        !state.script ||
        !state.playing ||
        !state.speaking ||
        !parts
      )
        return;
      const selected = parts.filter(
        (part) => part.index === state.script!.segments[state.position].index,
      )[partPosition];
      if (!selected) return audioFailed();
      if (audio.getAttribute('src') !== selected.url) {
        audio.setAttribute('src', selected.url);
        audio.currentTime = 0;
      }
      stopMouth();
      currentPart = selected;
      const active = ++version;
      try {
        Promise.resolve(audio.play()).catch(() => {
          if (alive && active === version) audioFailed();
        });
      } catch {
        if (active === version) audioFailed();
      }
    };
    const ensureAudio = () => {
      if (audio) return;
      audio = new Audio();
      audio.preload = 'auto';
      audio.addEventListener('playing', driveMouth);
      audio.addEventListener('pause', stopMouth);
      audio.addEventListener('waiting', stopMouth);
      audio.addEventListener('error', onAudioError);
      audio.addEventListener('ended', onEnded);
    };
    const onAudioError = () => audioFailed();
    const onEnded = () => {
      stopMouth();
      if (!alive || !state.script || !state.playing || !state.speaking) return;
      const count =
        parts?.filter(
          (part) => part.index === state.script!.segments[state.position].index,
        ).length ?? 0;
      if (partPosition < count - 1) partPosition += 1;
      else {
        if (state.position === state.script.segments.length - 1)
          return stop(true);
        partPosition = 0;
        publish({ position: state.position + 1 });
      }
      speakCurrent();
    };
    const toggle = () => {
      if (
        !state.script ||
        state.voiceLoading ||
        (reducedRef.current && !state.speaking)
      )
        return;
      if (state.playing) return stop();
      if (
        !state.speaking &&
        state.position === state.script.segments.length - 1
      )
        publish({ position: 0 });
      publish({ playing: true });
      if (state.speaking) speakCurrent();
      else schedule();
    };
    const step = (delta: number) => {
      if (!state.script) return;
      stop(true);
      audio?.removeAttribute('src');
      publish({
        position: Math.max(
          0,
          Math.min(state.script.segments.length - 1, state.position + delta),
        ),
      });
    };
    const voice = async () => {
      if (!state.script || state.voiceLoading) return;
      stop(true);
      publish({ speaking: !state.speaking, voiceNotice: '' });
      if (!state.speaking) return;
      ensureAudio();
      audio?.removeAttribute('src');
      publish({ position: 0, playing: true, voiceLoading: !parts });
      try {
        audioRequest ??= api<{ segments: AudioPart[] }>('/api/media/audio', {
          method: 'POST',
          json: body,
          signal: controller.signal,
        });
        const result = await audioRequest;
        if (!alive) return;
        parts = result.segments;
        publish({ voiceLoading: false });
        speakCurrent();
      } catch (error) {
        audioRequest = null;
        audioFailed(message(error));
      }
    };
    const load = async () => {
      publish({ error: '' });
      try {
        const script = await api<MediaScript>('/api/media/script', {
          method: 'POST',
          json: body,
          signal: controller.signal,
        });
        if (!alive) return;
        if (!script.segments.length) throw new Error('回放脚本没有句子');
        publish({ script });
      } catch (error) {
        if (alive) publish({ error: message(error) });
      }
    };
    const loadCapabilities = async () => {
      try {
        const capabilities = await api<Capabilities>(
          '/api/media/capabilities',
          { signal: controller.signal },
        );
        if (alive)
          publish({ capabilities, voiceNotice: capabilities.error ?? '' });
      } catch (error) {
        if (alive)
          publish({ voiceNotice: `${message(error)}，可继续文字回放。` });
      }
    };
    const download = async (video = false) => {
      if (state.exporting || state.exportingVideo) return;
      publish(
        video ? { exportingVideo: true } : { exporting: true, error: '' },
      );
      try {
        let blob: Blob;
        if (video) {
          const response = await fetch('/api/media/clip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Twin': '1' },
            body: JSON.stringify(body),
            credentials: 'same-origin',
            redirect: 'error',
            signal: controller.signal,
          });
          if (!response.ok)
            throw new Error(
              '视频导出失败，请检查 ffmpeg、字体和语音配置后重试',
            );
          blob = await response.blob();
        } else {
          const html = await api<string>('/api/media/export', {
            method: 'POST',
            json: body,
            responseType: 'text',
            signal: controller.signal,
          });
          blob = new Blob([html], { type: 'text/html;charset=utf-8' });
        }
        if (!alive) return;
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = video ? 'twin-media.mp4' : 'twin-media.html';
        document.body.append(link);
        link.click();
        link.remove();
        downloads.set(
          url,
          setTimeout(() => {
            URL.revokeObjectURL(url);
            downloads.delete(url);
          }, 1000),
        );
      } catch (error) {
        if (alive) {
          if (video)
            toast(
              '视频导出失败，请检查 ffmpeg、字体和语音配置后重试',
              'danger',
            );
          else publish({ error: message(error) });
        }
      } finally {
        if (alive)
          publish(video ? { exportingVideo: false } : { exporting: false });
      }
    };
    actions.current = {
      toggle,
      step,
      voice: () => void voice(),
      export: () => void download(),
      exportVideo: () => void download(true),
      retry: () => {
        void load();
        void loadCapabilities();
      },
      stop,
    };
    void load();
    void loadCapabilities();
    return () => {
      alive = false;
      controller.abort();
      stop(true);
      if (audio) {
        audio.removeEventListener('playing', driveMouth);
        audio.removeEventListener('pause', stopMouth);
        audio.removeEventListener('waiting', stopMouth);
        audio.removeEventListener('error', onAudioError);
        audio.removeEventListener('ended', onEnded);
        audio.removeAttribute('src');
        audio.load();
      }
      downloads.forEach((timeout, url) => {
        clearTimeout(timeout);
        URL.revokeObjectURL(url);
      });
      actions.current = noActions;
    };
  }, [open, answer, personaName]);
  return { ...view, mouth: open ? mouth : 0, actions: actions.current };
}
