import { useRef, type RefObject } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { Clip, IconButton, LinkButton, Text } from '../../components/ui';
import { personaUrl } from '../../lib/persona';
import type { ChatReply } from './types';
import { videoUrl, type ReplyVideoState } from './useReplyVideos';

export function ReplyVideo({
  id,
  answer,
  portrait,
  name = '分身',
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
  name?: string;
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
  if (!answer.reply.trim()) return null;
  const ready = !!url;
  const setOpen = onOpenChange;
  return (
    <Dialog.Root open={open && ready} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-primary" />
        <Dialog.Content
          aria-describedby={`video-text-${id}`}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            trigger.current?.focus();
          }}
          className="video-overlay fixed inset-0 z-50 flex h-dvh flex-col bg-primary px-4 text-canvas outline-none"
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
            <div>
              <Text size="lg" tone="inherit" className="persona-name">
                {name}
              </Text>
              <Dialog.Title asChild>
                <Text as="h2" size="sm" tone="inherit">
                  真人版
                </Text>
              </Dialog.Title>
            </div>
            <Dialog.Close asChild>
              <IconButton
                label="关闭视频"
                shape="circle"
                size="lg"
                className="bg-canvas text-primary"
              >
                <X size={20} aria-hidden />
              </IconButton>
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
              <Clip shape="card">
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
                  className="max-h-full max-w-full object-contain"
                />
              </Clip>
            )}
          </div>
          <div className="shrink-0 py-2">
            <LinkButton
              href={url ?? undefined}
              download="twin-video.mp4"
              variant="secondary"
              shape="pill"
            >
              保存
            </LinkButton>
            {state?.result?.warnings.map((warning, index) => {
              const sentence = /^s(\d+): cer=/.exec(warning);
              return (
                <Text key={index} role="note" size="xs" tone="inherit">
                  {sentence
                    ? Number(sentence[1]) === 1
                      ? '开头提示回听与原文有出入'
                      : `第 ${Number(sentence[1]) - 1} 句回听与原文有出入`
                    : '视频生成有提示，请检查回听结果'}
                </Text>
              );
            })}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
