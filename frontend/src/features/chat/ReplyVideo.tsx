import { useEffect, useState } from 'react';
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
  const [revealed, setRevealed] = useState(false);
  const url = state?.status === 'done' ? videoUrl(state.result) : null;
  useEffect(() => {
    if (url && !speaking) setRevealed(true);
    if (!url) setRevealed(false);
  }, [url, speaking]);
  if (answer.abstain || answer.mode === 'abstain') return null;
  if (state?.status === 'failed')
    return (
      <p role="alert" className="w-full text-xs text-secondary">
        真人版生成失败 ·{' '}
        <button
          className="min-h-11 px-1 text-accent underline"
          aria-label="重试生成视频"
          onClick={onRetry}
        >
          重试
        </button>
      </p>
    );
  if (!url || !revealed)
    return (
      <p role="status" className="w-full text-xs text-tertiary">
        真人版生成中…
      </p>
    );
  return (
    <section
      className="w-full min-w-0 basis-full space-y-2"
      aria-label="回复视频"
    >
      <div className="max-w-[360px] space-y-2">
        <p className="text-xs text-secondary">真人版</p>
        <video
          controls
          playsInline
          preload="metadata"
          poster={portrait}
          src={url}
          onError={onError}
          aria-label="回复的真人视频"
          aria-describedby={`video-text-${id}`}
          className="w-full max-w-[360px] rounded-lg"
        />
        <p id={`video-text-${id}`} className="sr-only">
          {answer.reply}
        </p>
        <a
          href={url}
          download="twin-video.mp4"
          className="inline-flex min-h-11 items-center text-sm text-accent underline"
        >
          保存
        </a>
        {state?.result?.warnings.map((warning, index) => {
          const sentence = /^s(\d+): cer=/.exec(warning);
          return (
            <p key={index} role="note" className="text-xs text-secondary">
              {sentence
                ? Number(sentence[1]) === 1
                  ? '开头提示回听与原文有出入'
                  : `第 ${Number(sentence[1]) - 1} 句回听与原文有出入`
                : '视频生成有提示，请检查回听结果'}
            </p>
          );
        })}
      </div>
    </section>
  );
}
