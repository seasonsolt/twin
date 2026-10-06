import { useEffect, useRef, useState } from 'react';

export function useRecorder(active = true) {
  const [state, setState] = useState<
    'idle' | 'requesting' | 'recording' | 'review'
  >('idle');
  const [file, setFile] = useState<File | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState('');
  const recorder = useRef<MediaRecorder | null>(null);
  const cleanup = useRef(() => {});
  const generation = useRef(0);

  useEffect(() => {
    if (!active) {
      generation.current += 1;
      cleanup.current();
      setState('idle');
      setFile(null);
    }
    return () => {
      generation.current += 1;
      cleanup.current();
    };
  }, [active]);

  const start = async () => {
    if (!active || state === 'recording' || state === 'requesting') return;
    const version = ++generation.current;
    cleanup.current();
    setFile(null);
    setError('');
    setSeconds(0);
    setLevel(0);
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === 'undefined'
    ) {
      setError('这个浏览器无法录音，请上传录音或视频');
      return;
    }
    setState('requesting');
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (version !== generation.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const mime = [
        'audio/webm;codecs=opus',
        'audio/mp4',
        'audio/ogg;codecs=opus',
      ].find((type) => MediaRecorder.isTypeSupported(type));
      const recording = new MediaRecorder(
        stream,
        mime ? { mimeType: mime } : undefined,
      );
      recorder.current = recording;
      const chunks: Blob[] = [];
      const started = Date.now();
      const timer = setInterval(() => {
        const elapsed = Math.floor((Date.now() - started) / 1000);
        setSeconds(Math.min(30, elapsed));
        if (elapsed >= 30 && recording.state === 'recording') recording.stop();
      }, 200);
      let frame: number | undefined;
      let context: AudioContext | undefined;
      const release = () => {
        clearInterval(timer);
        if (frame !== undefined) cancelAnimationFrame(frame);
        stream?.getTracks().forEach((track) => track.stop());
        if (context) void context.close().catch(() => {});
      };
      cleanup.current = () => {
        recording.onstop = null;
        recording.ondataavailable = null;
        recording.onerror = null;
        if (recording.state !== 'inactive') recording.stop();
        release();
      };
      recording.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recording.onstop = () => {
        release();
        if (version !== generation.current) return;
        const type = recording.mimeType || mime || 'audio/webm';
        const extension = type.includes('mp4')
          ? 'm4a'
          : type.includes('ogg')
            ? 'ogg'
            : 'webm';
        setFile(new File(chunks, `recording.${extension}`, { type }));
        setLevel(0);
        setState('review');
      };
      recording.onerror = () => {
        cleanup.current();
        setError('录音中断了，请重新录制');
        setState('idle');
      };
      // A missing audio analyser must not prevent recording on older iPhones.
      try {
        const Audio =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext })
            .webkitAudioContext;
        if (Audio) {
          context = new Audio();
          const analyser = context.createAnalyser();
          analyser.fftSize = 256;
          context.createMediaStreamSource(stream).connect(analyser);
          void context.resume().catch(() => {});
          const samples = new Uint8Array(analyser.fftSize);
          const measure = () => {
            analyser.getByteTimeDomainData(samples);
            setLevel(
              Math.min(
                1,
                Math.sqrt(
                  samples.reduce(
                    (sum, value) => sum + ((value - 128) / 128) ** 2,
                    0,
                  ) / samples.length,
                ) * 4,
              ),
            );
            frame = requestAnimationFrame(measure);
          };
          measure();
        }
      } catch {
        /* Recording still works without a level meter. */
      }
      recording.start(250);
      setState('recording');
    } catch {
      stream?.getTracks().forEach((track) => track.stop());
      cleanup.current();
      if (version === generation.current) {
        setState('idle');
        setError('无法使用麦克风，请允许录音权限，或上传录音');
      }
    }
  };
  return {
    state,
    file,
    seconds,
    level,
    error,
    start,
    stop: () => {
      if (recorder.current?.state === 'recording') recorder.current.stop();
    },
    reset: () => {
      generation.current += 1;
      cleanup.current();
      setFile(null);
      setState('idle');
      setLevel(0);
    },
  };
}
