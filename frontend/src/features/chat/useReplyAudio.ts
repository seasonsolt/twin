import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import type { AudioPart } from '../avatar/types';
import type { ChatReply } from './types';
import { GaplessAudio } from './GaplessAudio';

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
interface AudioReply {
  count: number;
  segments: Map<number, AudioPart[]>;
}

export function useReplyAudio(active: boolean) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const actions = useRef(idle);
  const cache = useRef(new Map<string, AudioReply>());
  const buffers = useRef(new Map<string, AudioBuffer>());
  const [view, setView] = useState(initial);
  useEffect(() => {
    const audio = audioRef.current;
    if (!active || !audio) return;
    let alive = true;
    let state = { ...initial };
    let request: AbortController | null = null;
    let frame: number | null = null;
    let version = 0;
    let reply: AudioReply = { count: 0, segments: new Map() };
    let segment = 0;
    let position = 0;
    let waiting = false;
    let player: GaplessAudio | null = null;
    const key = () => `${segment}:${position}`;
    const currentTime = () =>
      player ? player.elapsed(key()) : audio.currentTime;
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
      if (player) void player.pause().catch(() => {});
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
      player?.reset();
      reply = { count: 0, segments: new Map() };
      segment = position = 0;
      waiting = false;
      publish({ id: '', progress: 0 });
    };
    const fail = (detail = '语音播放失败，请重试') => {
      const id = state.id;
      stop();
      publish({ errors: { ...state.errors, [id]: detail } });
    };
    const part = () => reply.segments.get(segment)?.[position];
    const progress = () => {
      const known = [...reply.segments.values()].flat();
      const duration = known.reduce((sum, item) => sum + item.duration_s, 0);
      const total = duration * (reply.count / (reply.segments.size || 1));
      let elapsed = 0;
      for (let index = 0; index <= segment; index++) {
        const items = reply.segments.get(index) ?? [];
        elapsed += (
          index === segment ? items.slice(0, position) : items
        ).reduce((sum, item) => sum + item.duration_s, 0);
      }
      return total > 0
        ? Math.min(1, (elapsed + (waiting ? 0 : currentTime())) / total)
        : 0;
    };
    const sample = () => {
      frame = null;
      if (
        !alive ||
        !state.playing ||
        waiting ||
        (!player && (audio.paused || audio.ended))
      )
        return quiet();
      const track = part()?.lipsync;
      publish({
        speaking: true,
        level: track?.levels[Math.floor(currentTime() * track.fps)] ?? 0,
        progress: progress(),
      });
      frame = requestAnimationFrame(sample);
    };
    const onPlaying = () => {
      quiet();
      sample();
    };
    const play = () => {
      const currentPart = part();
      if (player) {
        for (let index = segment; index < reply.count; index++) {
          const items = reply.segments.get(index);
          if (!items) break;
          for (
            let offset = index === segment ? position : 0;
            offset < items.length;
            offset++
          ) {
            const buffer = buffers.current.get(items[offset].url);
            if (!buffer) break;
            player.schedule(`${index}:${offset}`, buffer, onEnded);
          }
          if (items.some((item) => !buffers.current.has(item.url))) break;
        }
        waiting = !player.has(key());
        publish({ loading: waiting });
        if (waiting) quiet();
        else onPlaying();
        return;
      }
      if (!currentPart) {
        waiting = true;
        publish({ loading: true });
        return;
      }
      waiting = false;
      publish({ loading: false });
      if (audio.getAttribute('src') !== currentPart.url) {
        audio.src = currentPart.url;
        audio.currentTime = 0;
      }
      const current = version;
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
      if (!state.playing && !player) return;
      position += 1;
      if (position === reply.segments.get(segment)?.length) {
        segment += 1;
        position = 0;
      }
      if (segment === reply.count) {
        pause();
        audio.removeAttribute('src');
        audio.load();
        segment = position = 0;
        publish({ progress: 1 });
      } else if (state.playing) play();
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
      reply = cache.current.get(id) ?? { count: 0, segments: new Map() };
      cache.current.set(id, reply);
      const entry = reply;
      const controller = new AbortController();
      request = controller;
      const current = ++version;
      const valid = () =>
        alive && !controller.signal.aborted && current === version;
      publish({ id, playing: true, errors: { ...state.errors, [id]: '' } });
      if (!player && typeof AudioContext !== 'undefined') {
        try {
          player = new GaplessAudio();
        } catch {
          return fail();
        }
      }
      if (player)
        void player.resume().catch(() => {
          if (valid()) fail();
        });
      if (part()) play();
      else {
        audio.load();
        waiting = true;
        publish({ loading: true });
      }
      const fetchSegment = async (index: number) => {
        const result = entry.segments.has(index)
          ? { segment_count: entry.count, segments: entry.segments.get(index)! }
          : await api<{
              segment_count: number;
              segments: AudioPart[];
            }>('/api/media/audio', {
              method: 'POST',
              json: {
                kind: 'chat_reply',
                answer,
                persona_name: name,
                segments: [index],
              },
              signal: controller.signal,
            });
        if (!valid()) return;
        if (!result.segments.length)
          throw new Error('没有可播放的语音，请重试');
        entry.count = result.segment_count;
        entry.segments.set(index, result.segments);
        if (player) {
          for (const item of result.segments) {
            if (!buffers.current.has(item.url)) {
              if (
                !/^\/api\/media\/audio\/[0-9a-f]{64}\.(wav|mp3)$/.test(item.url)
              )
                throw new Error('语音文件不可用，请重试');
              const response = await fetch(item.url, {
                signal: controller.signal,
                credentials: 'same-origin',
                redirect: 'error',
              });
              if (!response.ok) throw new Error('语音文件不可用，请重试');
              const buffer = await player.decode(await response.arrayBuffer());
              if (!valid()) return;
              buffers.current.set(item.url, buffer);
            }
            play();
          }
        } else if (waiting && index === segment) play();
      };
      try {
        await fetchSegment(0);
        if (!valid()) return;
        const remaining = Array.from(
          { length: entry.count },
          (_, index) => index,
        ).filter(
          (index) =>
            !entry.segments.has(index) ||
            (player &&
              entry.segments
                .get(index)!
                .some((item) => !buffers.current.has(item.url))),
        );
        const worker = async () => {
          while (valid() && remaining.length) {
            await fetchSegment(remaining.shift()!);
          }
        };
        await Promise.all([worker(), worker()]);
      } catch (error) {
        if (valid())
          fail(error instanceof Error ? error.message : '语音暂不可用，请重试');
      }
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
      if (player) void player.close().catch(() => {});
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
