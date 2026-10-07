import { useEffect, useRef, useState } from 'react';
import Cropper, { type Area } from 'react-easy-crop';
import 'react-easy-crop/react-easy-crop.css';
import { Button } from '../../components/ui';
import { api } from '../../lib/api';
import { personaUrl } from '../../lib/persona';
import { uploadForm } from '../../lib/mediaUpload';
import type { Capabilities } from '../avatar/types';
import { useRecorder } from './useRecorder';
import { usePendingWork } from '../../lib/pendingWork';

export const ASSETS_CHANGED = 'twin-assets-changed';
interface Profile {
  portrait: { sha: string; file: string } | null;
  voice: { id: string; file: string; duration_s: number } | null;
}
interface Assets extends Profile {
  speech_clone: boolean;
  video: boolean;
}

export function uploadAsset(
  path: string,
  form: FormData,
  progress: (value: number) => void,
  signal: AbortSignal,
): Promise<Profile> {
  return uploadForm<Profile>(path, form, signal, progress, 'PUT');
}

const SERVER_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

const isHeic = (file: File) =>
  /^image\/hei[cf](?:-sequence)?$/i.test(file.type) ||
  /\.hei[cf]$/i.test(file.name);

// Re-encode browser-readable formats as JPEG; undecodable HEIC goes to the server.
export async function toUploadableImage(file: File): Promise<File> {
  if (SERVER_IMAGE_TYPES.has(file.type)) return file;
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
    } catch {
      if (isHeic(file)) return file;
      throw new Error('无法读取照片，请选择有效的图片');
    }
    const scale = Math.min(
      1,
      4096 / Math.max(image.naturalWidth, image.naturalHeight),
    );
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(image.naturalWidth * scale);
    canvas.height = Math.round(image.naturalHeight * scale);
    const context = canvas.getContext('2d');
    if (!context) throw new Error('无法转换照片，请换一张 JPEG 或 PNG 照片');
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', 0.92),
    );
    if (!blob) throw new Error('无法转换照片，请换一张 JPEG 或 PNG 照片');
    return new File([blob], 'portrait.jpg', { type: 'image/jpeg' });
  } finally {
    URL.revokeObjectURL(url);
  }
}

function useObjectUrl(blob: Blob | null) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    if (!blob) {
      setUrl('');
      return;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}

const passage =
  '今天的阳光很温暖，我想放慢脚步，看看身边的风景。无论生活怎样变化，我都会认真倾听，坦诚表达，把每一个平凡的日子过得有趣而充实。';

export function SelfAssets({ active = true }: { active?: boolean }) {
  const [profile, setProfile] = useState<Assets | null>(null);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [size, setSize] = useState(0);
  const [busyKind, setBusyKind] = useState<'portrait' | 'voice'>('portrait');
  const [busyLabel, setBusyLabel] = useState('');
  const retryWork = useRef<(() => void) | null>(null);
  const [photo, setPhoto] = useState<File | null>(null);
  const [previewUnavailable, setPreviewUnavailable] = useState(false);
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [area, setArea] = useState<Area | null>(null);
  const [sample, setSample] = useState<string | null>(null);
  const portraitInput = useRef<HTMLInputElement>(null);
  const voiceInput = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController | null>(null);
  const recorder = useRecorder(active);
  const photoUrl = useObjectUrl(photo);
  const recordingUrl = useObjectUrl(recorder.file);
  const recording =
    recorder.state === 'recording' || recorder.state === 'requesting';
  const disabled = busy || recording || !profile;
  usePendingWork(busy || recording, busy ? busyLabel : '正在录音…');

  useEffect(() => {
    if (!active) return;
    setBusy(false);
    const controller = new AbortController();
    void api<Assets>('/api/me/assets', { signal: controller.signal })
      .then((assets) => {
        if (!controller.signal.aborted) {
          setProfile(assets);
          setError('');
        }
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error ? failure.message : '无法加载形象和声音',
          );
      });
    void api<Capabilities>('/api/media/capabilities', {
      signal: controller.signal,
    })
      .then((capabilities) => {
        if (!controller.signal.aborted) setCaps(capabilities);
      })
      .catch(() => {});
    return () => {
      controller.abort();
      request.current?.abort();
    };
  }, [active, attempt]);

  useEffect(() => {
    if (!active) return;
    const refresh = () => {
      if (!busy && !request.current) setAttempt((value) => value + 1);
    };
    window.addEventListener(ASSETS_CHANGED, refresh);
    return () => window.removeEventListener(ASSETS_CHANGED, refresh);
  }, [active, busy]);

  const changed = async (next: Profile, signal: AbortSignal) => {
    if (signal.aborted) return;
    setProfile((current) => (current ? { ...current, ...next } : null));
    window.dispatchEvent(new Event(ASSETS_CHANGED));
    try {
      const nextCaps = await api<Capabilities>('/api/media/capabilities', {
        signal,
      });
      if (!signal.aborted) {
        setCaps(nextCaps);
        return nextCaps;
      }
    } catch {
      /* The portrait and voice are saved even if speech is offline. */
    }
  };
  const trial = async (signal: AbortSignal) => {
    const result = await api<{ segments: { url: string }[] }>(
      '/api/media/audio',
      {
        method: 'POST',
        signal,
        json: {
          kind: 'chat_reply',
          answer: {
            reply: '你好，这是我的声音。很高兴和你聊天，今天想聊些什么？',
            citations: [],
            confidence: 1,
            abstain: false,
            abstain_reason: '',
            retrieved_ids: [],
          },
        },
      },
    );
    if (!signal.aborted)
      setSample(result.segments[0] ? personaUrl(result.segments[0].url) : null);
  };
  const operation = async (
    kind: 'portrait' | 'voice',
    label: string,
    work: (signal: AbortSignal) => Promise<void>,
    bytes = 0,
  ) => {
    if (request.current && busy) return;
    retryWork.current = () => void operation(kind, label, work, bytes);
    setBusyKind(kind);
    setBusyLabel(label);
    setSize(bytes);
    const controller = new AbortController();
    request.current?.abort();
    request.current = controller;
    setBusy(true);
    setError('');
    setProgress(0);
    try {
      await work(controller.signal);
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(
          failure instanceof Error && /[\u3400-\u9fff]/u.test(failure.message)
            ? failure.message
            : '保存失败，请重试',
        );
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  };
  const save = (kind: 'portrait' | 'voice', file: File) => {
    setBusyKind(kind);
    if (file.size > (kind === 'portrait' ? 15 * 1024 * 1024 : 95_000_000)) {
      setError(
        kind === 'portrait' ? '照片不能超过 15 MB' : '录音或视频不能超过 95 MB',
      );
      return;
    }
    const uploading = kind === 'portrait' ? '正在上传照片…' : '正在上传声音…';
    const processing = kind === 'portrait' ? '正在处理照片…' : '正在处理声音…';
    void operation(
      kind,
      uploading,
      async (signal) => {
        const form = new FormData();
        const uploadable =
          kind === 'portrait' && !previewUnavailable
            ? await toUploadableImage(file)
            : file;
        const uncropped =
          kind === 'portrait' && isHeic(file) && uploadable === file;
        if (uncropped && !signal.aborted) setPreviewUnavailable(true);
        if (signal.aborted) return;
        setSize(uploadable.size);
        form.append('file', uploadable);
        if (kind === 'portrait' && area && !uncropped) {
          for (const [key, value] of Object.entries({
            x: area.x,
            y: area.y,
            w: area.width,
            h: area.height,
          }))
            form.append(key, String(value / 100));
        }
        const next = await uploadAsset(
          `/api/me/${kind}`,
          form,
          (value) => {
            if (signal.aborted) return;
            setProgress(value);
            if (value === 100) setBusyLabel(processing);
          },
          signal,
        );
        if (signal.aborted) return;
        setProgress(100);
        setBusyLabel(processing);
        const nextCaps = await changed(next, signal);
        if (signal.aborted) return;
        if (kind === 'portrait') setPhoto(null);
        else {
          recorder.reset();
          setSample(null);
          if (nextCaps?.available) await trial(signal);
        }
      },
      file.size,
    );
  };
  const reset = (kind: 'portrait' | 'voice') =>
    void operation(kind, '正在恢复默认…', async (signal) => {
      const next = await api<Profile>(`/api/me/${kind}`, {
        method: 'DELETE',
        signal,
      });
      await changed(next, signal);
      if (kind === 'voice' && !signal.aborted) setSample(null);
    });
  const currentPortrait = profile?.portrait
    ? personaUrl(`/api/media/avatar-image?v=${profile.portrait.sha}`)
    : caps?.avatar_image?.url
      ? personaUrl(caps.avatar_image.url)
      : undefined;

  const errorFeedback = error && (
    <div role="alert" className="text-danger">
      {error}
      {profile && retryWork.current && (
        <Button
          variant="ghost"
          disabled={disabled}
          onClick={() => retryWork.current?.()}
        >
          重试
        </Button>
      )}
      {!profile && (
        <Button
          variant="ghost"
          onClick={() => setAttempt((value) => value + 1)}
        >
          重试加载
        </Button>
      )}
    </div>
  );

  return (
    <div className="self-assets space-y-5 [&_button]:min-h-11 [&_input]:text-base [&_label]:min-h-11">
      <section
        aria-label="形象"
        aria-busy={busy && busyKind === 'portrait'}
        className={`space-y-3 rounded-xl bg-surface p-4 shadow-card ${busy && busyKind === 'portrait' ? 'opacity-60' : ''}`}
      >
        <h2 className="text-md font-semibold">形象</h2>
        <div className="flex items-center gap-3">
          {currentPortrait ? (
            <img
              src={currentPortrait}
              alt="当前肖像"
              className="size-18 rounded-full object-cover"
            />
          ) : (
            <div
              className="flex size-18 items-center justify-center rounded-full bg-background text-secondary"
              aria-label="肖像占位"
            >
              未设置
            </div>
          )}
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={() => portraitInput.current?.click()}
          >
            换一张
          </Button>
          {profile?.portrait && (
            <Button
              variant="ghost"
              disabled={disabled}
              onClick={() => reset('portrait')}
            >
              恢复默认
            </Button>
          )}
        </div>
        <input
          ref={portraitInput}
          aria-label="选择照片"
          type="file"
          accept="image/*"
          hidden
          disabled={disabled}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) {
              setBusyKind('portrait');
              retryWork.current = null;
              if (file.size > 15 * 1024 * 1024) {
                setError('照片不能超过 15 MB');
                return;
              }
              setError('');
              setPhoto(file);
              setPreviewUnavailable(false);
              setCrop({ x: 0, y: 0 });
              setZoom(1);
              setArea(null);
            }
          }}
        />
        <p className="text-sm text-secondary">
          正脸、光线均匀、头肩入镜效果最好
        </p>
        {photoUrl && (
          <div className="space-y-3">
            <div
              className={`relative h-80 overflow-hidden rounded-lg ${previewUnavailable ? 'flex items-center justify-center bg-background p-6 text-center text-secondary' : 'bg-black'}`}
              aria-label="裁剪照片"
            >
              {previewUnavailable ? (
                <p>这个格式无法在浏览器里预览，会自动居中裁剪</p>
              ) : (
                <Cropper
                  key={photoUrl}
                  image={photoUrl}
                  crop={crop}
                  zoom={zoom}
                  aspect={3 / 4}
                  onCropChange={setCrop}
                  onZoomChange={setZoom}
                  onCropComplete={setArea}
                  mediaProps={{
                    onError: () => {
                      setArea(null);
                      if (photo && isHeic(photo)) {
                        setPreviewUnavailable(true);
                      } else {
                        setPhoto(null);
                        setError('无法读取照片，请选择有效的图片');
                      }
                    },
                    onLoad: () => setPreviewUnavailable(false),
                  }}
                  disableAutomaticStylesInjection
                />
              )}
            </div>
            {!previewUnavailable && (
              <>
                <label className="flex items-center gap-3">
                  缩放
                  <input
                    aria-label="照片缩放"
                    type="range"
                    min={1}
                    max={3}
                    step={0.01}
                    value={zoom}
                    disabled={busy}
                    onChange={(event) => setZoom(Number(event.target.value))}
                    className="min-h-11 flex-1"
                  />
                </label>
                <p className="text-sm text-secondary">
                  拖动照片或双指缩放，让脸部留在框内。
                </p>
              </>
            )}
            <div className="flex gap-2">
              <Button
                disabled={disabled || (!area && !previewUnavailable)}
                loading={busy && busyKind === 'portrait'}
                onClick={() => photo && save('portrait', photo)}
              >
                {busy && busyKind === 'portrait' ? busyLabel : '使用这张'}
              </Button>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => setPhoto(null)}
              >
                取消
              </Button>
            </div>
          </div>
        )}
        {busyKind === 'portrait' && errorFeedback}
      </section>
      <section
        aria-label="声音"
        aria-busy={(busy && busyKind === 'voice') || recording}
        className={`space-y-3 rounded-xl bg-surface p-4 shadow-card ${(busy && busyKind === 'voice') || recording ? 'opacity-60' : ''}`}
      >
        <h2 className="text-md font-semibold">声音</h2>
        <p>
          {profile?.voice
            ? `我的声音（${profile.voice.duration_s.toFixed(1)} 秒）`
            : '预置音色'}
        </p>
        {profile?.voice && (
          <audio
            key={profile.voice.id}
            controls
            preload="none"
            aria-label="播放声音参考"
            src={personaUrl(`/api/me/voice/reference?v=${profile.voice.id}`)}
            className="w-full max-w-sm"
          />
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={() => void recorder.start()}
          >
            录一段
          </Button>
          <Button
            variant="secondary"
            disabled={disabled}
            loading={busy && busyKind === 'voice'}
            onClick={() => voiceInput.current?.click()}
          >
            上传录音或视频
          </Button>
          {profile?.voice && (
            <Button
              variant="ghost"
              disabled={disabled}
              onClick={() => reset('voice')}
            >
              恢复默认
            </Button>
          )}
        </div>
        <input
          ref={voiceInput}
          aria-label="选择录音或视频"
          type="file"
          accept="audio/*,video/*"
          hidden
          disabled={disabled}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) save('voice', file);
          }}
        />
        <p className="text-sm text-secondary">
          安静环境下说话至少 5 秒，会保留前 20 秒。
        </p>
        {recorder.state !== 'idle' && (
          <div className="recording-card space-y-3 rounded-xl p-4">
            <p className="text-md leading-relaxed">{passage}</p>
            {recorder.state === 'requesting' && (
              <p role="status">正在打开麦克风…</p>
            )}
            {recorder.state === 'recording' && (
              <>
                <p role="timer" className="flex items-center gap-2">
                  <span className="recording-live" aria-hidden />
                  {recorder.seconds} / 30 秒
                </p>
                <div className="recording-bars" aria-hidden>
                  {Array.from({ length: 12 }, (_, index) => (
                    <i
                      key={index}
                      style={{
                        height: `${8 + recorder.level * ((index % 3) + 1) * 12}px`,
                      }}
                    />
                  ))}
                </div>
                <meter
                  aria-label="录音音量"
                  value={recorder.level}
                  min={0}
                  max={1}
                  className="sr-only"
                />
                <Button onClick={recorder.stop}>停止录音</Button>
              </>
            )}
            {recorder.state === 'review' && (
              <>
                <audio
                  controls
                  aria-label="回放录音"
                  src={recordingUrl || undefined}
                  className="w-full"
                />
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() => void recorder.start()}
                  >
                    重录
                  </Button>
                  <Button
                    disabled={busy || !recorder.file}
                    onClick={() =>
                      recorder.file && save('voice', recorder.file)
                    }
                  >
                    使用
                  </Button>
                </div>
              </>
            )}
            <Button variant="ghost" disabled={busy} onClick={recorder.reset}>
              取消录音
            </Button>
          </div>
        )}
        {profile?.voice && caps?.available && (
          <div className="space-y-2">
            <Button
              variant="secondary"
              disabled={disabled}
              onClick={() => void operation('voice', '正在处理声音…', trial)}
            >
              试听
            </Button>
            {sample && (
              <audio
                controls
                aria-label="试听我的声音"
                src={sample}
                className="w-full max-w-sm"
              />
            )}
          </div>
        )}
        {busyKind === 'voice' && errorFeedback}
        {recorder.error && (
          <p role="alert" className="text-danger">
            {recorder.error}
          </p>
        )}
      </section>
      {busy && (
        <div role="status">
          {size > 0 && (
            <>
              <progress
                aria-label="上传进度"
                value={progress}
                max={100}
                className="w-full"
              />
              <p>
                上传中 {progress}% ·{' '}
                {((size * progress) / 100 / 1024 ** 2).toFixed(1)} /{' '}
                {(size / 1024 ** 2).toFixed(1)} MB
              </p>
            </>
          )}
          <p>{busyLabel}</p>
        </div>
      )}
    </div>
  );
}
