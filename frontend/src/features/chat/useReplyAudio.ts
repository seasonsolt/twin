import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import type { AudioPart } from '../avatar/types';
import type { ChatReply } from './types';

const initial = {
  id: '',
  playing: false,
  loading: false,
  speaking: false,
  level: 0,
  progress: 0,
  errors: {} as Record<string, string>,
};
const idle = {
  toggle(_id: string, _answer: ChatReply, _name: string) {
    void _id;
    void _answer;
    void _name;
  },
  stop() {},
};

export function useReplyAudio(active: boolean) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const actions = useRef(idle);
  const [view, setView] = useState(initial);
  useEffect(() => {
    const audio = audioRef.current;
    if (!active || !audio) return;
    let alive = true;
    let state = { ...initial };
    let request: AbortController | null = null;
    let frame: number | null = null;
    let version = 0;
    let parts: AudioPart[] = [];
    let position = 0;
    const cache = new Map<string, AudioPart[]>();
    const publish = (patch: Partial<typeof initial> = {}) => {
      state = { ...state, ...patch };
      if (alive) setView(state);
    };
    const quiet = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      publish({ speaking: false, level: 0 });
    };
    const pause = () => {
      version += 1;
      request?.abort();
      request = null;
      if (audio.hasAttribute('src') || !audio.paused) audio.pause();
      quiet();
      publish({ playing: false, loading: false });
    };
    const stop = () => {
      pause();
      if (audio.hasAttribute('src')) {
        audio.removeAttribute('src');
        audio.load();
      }
      parts = [];
      position = 0;
      publish({ id: '', progress: 0 });
    };
    const fail = (detail = '语音播放失败，请重试') => {
      const id = state.id;
      stop();
      publish({ errors: { ...state.errors, [id]: detail } });
    };
    const progress = () => {
      const total = parts.reduce((sum, part) => sum + part.duration_s, 0);
      const elapsed = parts
        .slice(0, position)
        .reduce((sum, part) => sum + part.duration_s, 0);
      return total > 0 ? Math.min(1, (elapsed + audio.currentTime) / total) : 0;
    };
    const sample = () => {
      frame = null;
      if (!alive || !state.playing || audio.paused || audio.ended)
        return quiet();
      const track = parts[position]?.lipsync;
      publish({
        speaking: true,
        level: track?.levels[Math.floor(audio.currentTime * track.fps)] ?? 0,
        progress: progress(),
      });
      frame = requestAnimationFrame(sample);
    };
    const onPlaying = () => {
      quiet();
      sample();
    };
    const play = () => {
      const part = parts[position];
      if (!part) return fail('没有可播放的语音，请重试');
      if (audio.getAttribute('src') !== part.url) {
        audio.src = part.url;
        audio.currentTime = 0;
      }
      const current = ++version;
      try {
        Promise.resolve(audio.play()).catch(() => {
          if (alive && current === version) fail();
        });
      } catch {
        if (alive && current === version) fail();
      }
    };
    const onEnded = () => {
      quiet();
      if (!state.playing) return;
      position += 1;
      if (position === parts.length) {
        pause();
        audio.removeAttribute('src');
        audio.load();
        position = 0;
        publish({ progress: 1 });
      } else play();
    };
    const onError = () => {
      if (state.playing) fail();
    };
    const onTime = () => {
      if (state.playing) publish({ progress: progress() });
    };
    const toggle = async (id: string, answer: ChatReply, name: string) => {
      if (answer.abstain || answer.mode === 'abstain') return;
      if (state.id === id && state.playing) return pause();
      if (state.id !== id) stop();
      publish({ id, playing: true, errors: { ...state.errors, [id]: '' } });
      if (!parts.length) {
        parts = cache.get(id) ?? [];
        if (!parts.length) {
          const controller = new AbortController();
          request = controller;
          audio.load();
          publish({ loading: true });
          try {
            const result = await api<{ segments: AudioPart[] }>(
              '/api/media/audio',
              {
                method: 'POST',
                json: { kind: 'chat_reply', answer, persona_name: name },
                signal: controller.signal,
              },
            );
            if (!alive || controller.signal.aborted) return;
            parts = result.segments;
            cache.set(id, parts);
            publish({ loading: false });
          } catch (error) {
            if (alive && !controller.signal.aborted)
              fail(
                error instanceof Error ? error.message : '语音暂不可用，请重试',
              );
            return;
          }
        }
      }
      play();
    };
    audio.addEventListener('playing', onPlaying);
    audio.addEventListener('pause', quiet);
    audio.addEventListener('waiting', quiet);
    audio.addEventListener('timeupdate', onTime);
    audio.addEventListener('ended', onEnded);
    audio.addEventListener('error', onError);
    actions.current = {
      toggle: (id, answer, name) => void toggle(id, answer, name),
      stop,
    };
    publish();
    return () => {
      alive = false;
      stop();
      audio.removeEventListener('playing', onPlaying);
      audio.removeEventListener('pause', quiet);
      audio.removeEventListener('waiting', quiet);
      audio.removeEventListener('timeupdate', onTime);
      audio.removeEventListener('ended', onEnded);
      audio.removeEventListener('error', onError);
      actions.current = idle;
    };
  }, [active]);
  return {
    ...view,
    audioRef,
    toggle: (id: string, answer: ChatReply, name: string) =>
      actions.current.toggle(id, answer, name),
    stop: () => actions.current.stop(),
  };
}
