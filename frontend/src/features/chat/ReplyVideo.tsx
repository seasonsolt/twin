import { useRef, type RefObject } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { personaUrl } from '../../lib/persona';
import type { ChatReply } from './types';
import { videoUrl, type ReplyVideoState } from './useReplyVideos';

export function ReplyVideo({
  id,
  answer,
  portrait,
  state,
  open,
  onOpenChange,
  trigger,
  onError,
  startTime = 0,
  onTimeUpdate,
  onEnded,
  onPlaying,
  onPause,
}: {
  id: string;
  answer: ChatReply;
  portrait?: string;
  state?: ReplyVideoState;
  open: boolean;
  onOpenChange(open: boolean): void;
  trigger: RefObject<HTMLButtonElement | null>;
  onError(): void;
  startTime?: number;
  onTimeUpdate?(time: number): void;
  onEnded?(): void;
  onPlaying?(): void;
  onPause?(): void;
}) {
  portrait = portrait ? personaUrl(portrait) : undefined;
  const touch = useRef<{ x: number; y: number } | null>(null);
  const url = state?.status === 'done' ? videoUrl(state.result) : null;
  if (answer.abstain || answer.mode === 'abstain') return null;
  const ready = !!url;
  const setOpen = onOpenChange;
  return (
    <Dialog.Root open={open && ready} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/90" />
        <Dialog.Content
          aria-describedby={`video-text-${id}`}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            trigger.current?.focus();
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
                onLoadedMetadata={(event) => {
                  event.currentTarget.currentTime = startTime;
                }}
                onTimeUpdate={(event) =>
                  onTimeUpdate?.(event.currentTarget.currentTime)
                }
                onEnded={onEnded}
                onPlaying={onPlaying}
                onPause={onPause}
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
