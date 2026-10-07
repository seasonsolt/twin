import { useEffect, useRef, useState } from 'react';
import { motion, useSpring } from 'motion/react';
import { PersonaSwitcher } from '../../components/layout/PersonaSwitcher';
import { StageHeader } from '../../components/layout/StageHeader';
import { useMotionPreset, springs } from '../../design/motion';
import type { Capabilities } from '../avatar/types';
import { ChatAvatar } from './ChatAvatar';
import { ReplyVideo } from './ReplyVideo';
import type { Turn } from './types';
import { videoUrl, type ReplyVideoState } from './useReplyVideos';
import { useDesktop, useMobile } from '../../lib/useMobile';

export function videoCaption(text: string, time: number, duration: number) {
  const sentences = text.match(/[^。！？!?\r\n]+[。！？!?]*|[^\r\n]+$/gu) ?? [
    text,
  ];
  const total = sentences.reduce((sum, sentence) => sum + sentence.length, 0);
  let end = 0;
  return (
    sentences.find((sentence) => {
      end += sentence.length;
      return time / (duration || 1) < end / (total || 1);
    }) ??
    sentences.at(-1) ??
    ''
  );
}

export function ChatStage({
  name,
  capabilities,
  turn,
  videoState,
  videoPlaying,
  voiceCaption,
  level,
  speaking,
  onToggle,
  onVideoPlaying,
  onVideoError,
  onClear,
}: {
  name: string;
  capabilities: Capabilities | null;
  turn?: Turn;
  videoState?: ReplyVideoState;
  videoPlaying: boolean;
  voiceCaption: string;
  level: number;
  speaking: boolean;
  onToggle(): void;
  onVideoPlaying(playing: boolean): void;
  onVideoError(): void;
  onClear(): void;
}) {
  const { reduced } = useMotionPreset();
  const desktop = useDesktop();
  const mobile = useMobile();
  const [collapsed, setCollapsed] = useState(false);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [time, setTime] = useState(0);
  const circle = useRef<HTMLButtonElement>(null);
  const player = useRef<HTMLVideoElement>(null);
  const playbackError = useRef(onVideoError);
  useEffect(() => {
    playbackError.current = onVideoError;
  }, [onVideoError]);
  const url =
    videoState?.status === 'done' ? videoUrl(videoState.result) : null;
  useEffect(() => {
    setOpen(false);
    setTime(0);
  }, [url, turn?.id]);
  const height = useSpring(desktop ? 470 : 360, springs.snappy);
  const size = useSpring(desktop ? 240 : 196, springs.snappy);
  const targetHeight = desktop ? 470 : collapsed ? 96 : 360;
  const targetSize = desktop ? 240 : collapsed ? 60 : 196;
  useEffect(() => {
    if (reduced) {
      height.jump(targetHeight);
      size.jump(targetSize);
    } else {
      height.set(targetHeight);
      size.set(targetSize);
    }
  }, [height, size, targetHeight, targetSize, reduced]);
  useEffect(() => {
    let lastScroll = window.scrollY;
    const scroll = () => {
      const distance =
        document.documentElement.scrollHeight -
        window.innerHeight -
        window.scrollY;
      if (window.scrollY < lastScroll && distance > 80) setCollapsed(true);
      else if (
        distance <= 24 &&
        !document.activeElement?.closest('.chat-composer')
      )
        setCollapsed(false);
      lastScroll = window.scrollY;
    };
    const focus = (event: FocusEvent) => {
      if ((event.target as Element).closest('.chat-composer'))
        setCollapsed(true);
    };
    window.addEventListener('scroll', scroll, { passive: true });
    document.addEventListener('focusin', focus);
    return () => {
      window.removeEventListener('scroll', scroll);
      document.removeEventListener('focusin', focus);
    };
  }, [height]);
  useEffect(() => {
    const video = player.current;
    if (!video) return;
    if (!videoPlaying || open) video.pause();
    else {
      if (video.ended) video.currentTime = 0;
      try {
        void Promise.resolve(video.play()).catch(() => playbackError.current());
      } catch {
        playbackError.current();
      }
    }
  }, [url, turn?.id, videoPlaying, open]);
  const small = collapsed && !desktop;
  const videoCaptionText =
    url && videoPlaying && turn
      ? videoCaption(turn.content, time, videoState?.result?.duration_s ?? 0)
      : '';
  const caption = videoCaptionText || voiceCaption;
  return (
    <motion.div
      className="stage-space"
      style={{ height: reduced ? targetHeight : height }}
    >
      <StageHeader
        variant="chat"
        name={name}
        data-collapsed={small}
        data-desktop={desktop}
        data-reduced-motion={reduced}
        style={{ height: reduced ? targetHeight : height }}
        switchable={mobile}
        left={mobile ? <PersonaSwitcher stage /> : undefined}
        right={
          !desktop && (
            <button type="button" className="stage-new" onClick={onClear}>
              新对话
            </button>
          )
        }
        footer={
          desktop && (
            <button type="button" className="stage-new" onClick={onClear}>
              新对话
            </button>
          )
        }
        portrait={
          <motion.button
            ref={circle}
            type="button"
            className="stage-circle"
            style={{
              width: reduced ? targetSize : size,
              height: reduced ? targetSize : size,
            }}
            aria-label={
              small
                ? '展开舞台'
                : url && videoPlaying
                  ? '打开真人视频全屏'
                  : url || !mobile
                    ? '播放或暂停当前句'
                    : `${name}的肖像，快速切换分身`
            }
            aria-expanded={!small}
            onClick={() => {
              if (small) {
                setCollapsed(false);
                return;
              }
              if (url && videoPlaying) {
                player.current?.pause();
                setOpen(true);
              } else if (url || !mobile) onToggle();
              else setSwitching(true);
            }}
          >
            {url ? (
              <video
                key={`${turn?.id}:${url}`}
                ref={player}
                src={url}
                playsInline
                preload="metadata"
                aria-label="舞台真人视频"
                onLoadedMetadata={() => setTime(0)}
                onTimeUpdate={(event) =>
                  setTime(event.currentTarget.currentTime)
                }
                onEnded={() => onVideoPlaying(false)}
                onError={onVideoError}
                className="size-full rounded-full object-cover"
              />
            ) : (
              <ChatAvatar
                name={name}
                capabilities={capabilities}
                className="size-full"
                level={level}
                speaking={speaking}
              />
            )}
            {url && videoPlaying && (
              <span className="stage-video-chip">
                真人 · {Math.floor((videoState?.result?.duration_s ?? 0) / 60)}:
                {String(
                  Math.round(videoState?.result?.duration_s ?? 0) % 60,
                ).padStart(2, '0')}
              </span>
            )}
          </motion.button>
        }
        intro={
          <p
            className="stage-caption"
            aria-live="polite"
            aria-atomic="true"
            data-testid="stage-caption"
          >
            {caption}
          </p>
        }
      >
        {mobile && (
          <PersonaSwitcher
            open={switching}
            onOpenChange={setSwitching}
            returnFocus={circle}
            className="sr-only"
            label="舞台快速切换"
          />
        )}
        {turn?.reply && url && (
          <ReplyVideo
            id={turn.id}
            answer={turn.reply}
            state={videoState}
            portrait={capabilities?.avatar_image?.url}
            name={name}
            open={open}
            trigger={circle}
            onOpenChange={(value) => {
              if (!value && player.current) player.current.currentTime = time;
              setOpen(value);
            }}
            startTime={time}
            onTimeUpdate={setTime}
            onEnded={() => onVideoPlaying(false)}
            onPlaying={() => onVideoPlaying(true)}
            onPause={() => onVideoPlaying(false)}
            onError={() => {
              setOpen(false);
              onVideoError();
            }}
          />
        )}
      </StageHeader>
    </motion.div>
  );
}
