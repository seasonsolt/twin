import { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { LoaderCircle, Play, RotateCcw, X } from 'lucide-react';
import { personaUrl } from '../../lib/persona';
import type { ChatReply } from './types';
import { videoUrl, type ReplyVideoState } from './useReplyVideos';

export function ReplyVideo({
  id,
  answer,
  portrait,
  state,
  speaking,
  onRetry,
  onError,
}: {
  id: string;
  answer: ChatReply;
  portrait?: string;
  state?: ReplyVideoState;
  speaking: boolean;
  onRetry(): void;
  onError(): void;
}) {
  portrait = portrait ? personaUrl(portrait) : undefined;
  const [revealed, setRevealed] = useState(false);
  const [open, setOpen] = useState(false);
  const touch = useRef<{ x: number; y: number } | null>(null);
  const thumbnail = useRef<HTMLButtonElement>(null);
  const url = state?.status === 'done' ? videoUrl(state.result) : null;
  useEffect(() => {
    if (url && !speaking) setRevealed(true);
    if (!url) {
      setRevealed(false);
      setOpen(false);
    }
  }, [url, speaking]);
  if (answer.abstain || answer.mode === 'abstain') return null;
  const failed = state?.status === 'failed';
  const ready = !!url && revealed;
  const duration = Math.round(state?.result?.duration_s ?? 0);
  return (
    <Dialog.Root open={open && ready} onOpenChange={setOpen}>
      <button
        ref={thumbnail}
        type="button"
        aria-label={
          failed ? '重试生成视频' : ready ? '播放真人视频' : '真人版生成中'
        }
        aria-busy={!ready && !failed}
        disabled={!ready && !failed}
        onClick={() => (failed ? onRetry() : setOpen(true))}
        className="relative h-20 w-16 shrink-0 overflow-hidden rounded-md bg-accent/10 text-white"
      >
        {portrait && (
          <img
            src={portrait}
            alt=""
            className="absolute inset-0 size-full object-cover object-[50%_30%]"
          />
        )}
        <span className="absolute inset-0 bg-black/25" />
        <span className="relative grid place-items-center">
          {failed ? (
            <RotateCcw size={18} aria-hidden />
          ) : ready ? (
            <Play size={20} fill="currentColor" aria-hidden />
          ) : (
            <LoaderCircle
              size={18}
              aria-hidden
              className="animate-spin motion-reduce:animate-none"
            />
          )}
        </span>
        <span className="absolute inset-x-0 bottom-0 bg-black/40 py-0.5 text-center text-xs">
          {failed
            ? '重试'
            : ready
              ? `${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, '0')}`
              : '生成中'}
        </span>
      </button>
      {failed && (
        <span role="alert" className="text-xs text-secondary">
          真人版生成失败 · 重试
        </span>
      )}
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/90" />
        <Dialog.Content
          aria-describedby={`video-text-${id}`}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            thumbnail.current?.focus();
          }}
          className="video-overlay fixed inset-0 z-50 flex h-dvh flex-col bg-black/90 px-4 text-white outline-none"
          onClick={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
          onTouchStart={(event) => {
            touch.current = null;
            if ((event.target as Element).closest('button, a, video')) return;
            const point = event.touches[0];
            touch.current = { x: point.clientX, y: point.clientY };
          }}
          onTouchEnd={(event) => {
            const point = event.changedTouches[0];
            if (
              touch.current &&
              point.clientY - touch.current.y > 80 &&
              Math.abs(point.clientX - touch.current.x) < 80
            )
              setOpen(false);
            touch.current = null;
          }}
        >
          <div
            className="flex shrink-0 items-center justify-between py-2"
            data-testid="video-swipe-area"
          >
            <Dialog.Title className="text-sm">真人版</Dialog.Title>
            <Dialog.Close asChild>
              <button
                aria-label="关闭视频"
                className="grid size-11 place-items-center rounded-full bg-white/10"
              >
                <X size={20} aria-hidden />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description id={`video-text-${id}`} className="sr-only">
            {answer.reply}
          </Dialog.Description>
          <div
            className="flex min-h-0 flex-1 items-center justify-center"
            onClick={(event) => {
              if (event.target === event.currentTarget) setOpen(false);
            }}
          >
            {ready && (
              <video
                controls
                playsInline
                autoPlay
                preload="metadata"
                poster={portrait}
                src={url}
                onError={() => {
                  setOpen(false);
                  onError();
                }}
                aria-label="回复的真人视频"
                aria-describedby={`video-text-${id}`}
                className="max-h-full max-w-full rounded-lg object-contain"
              />
            )}
          </div>
          <div className="shrink-0 py-2">
            <a
              href={url ?? undefined}
              download="twin-video.mp4"
              className="inline-flex min-h-11 items-center px-3 text-sm underline"
            >
              保存
            </a>
            {state?.result?.warnings.map((warning, index) => {
              const sentence = /^s(\d+): cer=/.exec(warning);
              return (
                <p key={index} role="note" className="text-xs text-white/70">
                  {sentence
                    ? Number(sentence[1]) === 1
                      ? '开头提示回听与原文有出入'
                      : `第 ${Number(sentence[1]) - 1} 句回听与原文有出入`
                    : '视频生成有提示，请检查回听结果'}
                </p>
              );
            })}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
