import { useEffect, useRef, useState } from 'react';

// Main recording players and comparison clips share the listener's attention. A stopped pending play request
// must lose ownership before its promise/event can arrive; it cannot silence or restart the next clip.
let active: { element: HTMLAudioElement; stop: () => void } | null = null;

export function useClipAudio(src: string | undefined, nativeControls = false) {
  const audio = useRef<HTMLAudioElement>(null);
  const controller = useRef<{ toggle: () => void } | null>(null);
  const [state, setState] = useState({
    playing: false,
    loading: false,
    error: '',
  });
  useEffect(() => {
    const element = audio.current;
    if (!element) return;
    // StrictMode replays setup/cleanup on the same node. Cleanup cancels loading, so restore the resource here.
    if (src) element.setAttribute('src', src);
    let disposed = false;
    let request = 0;
    let failed = false;
    const owns = () => active?.element === element;
    const quiet = () => {
      ++request;
      if (owns()) active = null;
      if (!disposed)
        setState((before) => ({ ...before, playing: false, loading: false }));
    };
    const stop = () => {
      quiet();
      element.pause();
    };
    const pause = () => {
      // pause() queues an event; a new click may already have resumed this same element before it arrives.
      if (element.paused) quiet();
    };
    const ended = () => {
      if (element.ended) quiet();
    };
    const claim = () => {
      if (!owns()) {
        active?.stop();
        active = { element, stop };
      }
    };
    const failure = () => {
      if (!owns()) return;
      failed = true;
      quiet();
      element.pause();
      if (!disposed)
        setState({ playing: false, loading: false, error: '无法试听，请重试' });
    };
    const error = () => {
      // load() clears MediaError. A queued error from that earlier resource is no longer this request's failure.
      if (element.error) failure();
    };
    const play = () => {
      if (element.paused) return;
      if (nativeControls) claim();
      if (!owns()) {
        element.pause();
        return;
      }
      setState({ playing: false, loading: true, error: '' });
    };
    const playing = () => {
      if (!owns()) {
        element.pause();
        return;
      }
      setState({ playing: true, loading: false, error: '' });
    };
    const toggle = () => {
      if (owns()) {
        stop();
        return;
      }
      claim();
      if (failed) {
        // A failed media resource stays failed until load() starts a fresh request at this same address.
        element.load();
        failed = false;
      }
      const version = ++request;
      setState({ playing: false, loading: true, error: '' });
      try {
        void Promise.resolve(element.play()).catch(() => {
          if (!disposed && request === version && owns()) failure();
        });
      } catch {
        if (!disposed && request === version && owns()) failure();
      }
    };
    setState({ playing: false, loading: false, error: '' });
    controller.current = { toggle };
    element.addEventListener('play', play);
    element.addEventListener('playing', playing);
    element.addEventListener('pause', pause);
    element.addEventListener('ended', ended);
    element.addEventListener('error', error);
    return () => {
      disposed = true;
      controller.current = null;
      element.removeEventListener('play', play);
      element.removeEventListener('playing', playing);
      element.removeEventListener('pause', pause);
      element.removeEventListener('ended', ended);
      element.removeEventListener('error', error);
      stop();
      // Drop a pending network request too; detached audio must not keep loading the previous task's sound.
      element.removeAttribute('src');
      element.load();
    };
  }, [src, nativeControls]);
  return { audio, ...state, toggle: () => controller.current?.toggle() };
}
