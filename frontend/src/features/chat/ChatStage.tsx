import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  motion,
  useSpring,
  useTransform,
  type MotionStyle,
} from 'motion/react';
import { History, LoaderCircle } from 'lucide-react';
import { StageHeader } from '../../components/layout/StageHeader';
import { useMotionPreset, springs } from '../../design/motion';
import type { Capabilities } from '../avatar/types';
import { ChatAvatar } from './ChatAvatar';
import { ReplyVideo } from './ReplyVideo';
import type { Turn } from './types';
import { videoUrl, type ReplyVideoState } from './useReplyVideos';
import { useDesktop } from '../../lib/useMobile';
import { stripMarkdown } from './markdownText';
import { usePersonaId } from '../../lib/usePersonaState';

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
  onHistory,
  history,
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
  onHistory?(): void;
  history?: ReactNode;
}) {
  const { reduced } = useMotionPreset();
  const personaId = usePersonaId();
  const desktop = useDesktop();
  const [collapsed, setCollapsed] = useState(false);
  const [open, setOpen] = useState(false);
  const [time, setTime] = useState(0);
  const [videoShown, setVideoShown] = useState(false);
  const boundedLevel = Number.isFinite(level)
    ? Math.max(0, Math.min(3, level))
    : 0;
  const intensity = useSpring(0, springs.gentle);
  const breathing = useTransform(intensity, (value) => 1 + value * 0.03);
  const expansion = useTransform(intensity, (value) => 1.08 + value * 0.16);
  const opacity = useTransform(intensity, (value) => 0.3 + value * 0.45);
  useEffect(() => {
    if (reduced) intensity.jump(0);
    else intensity.set(speaking ? 0.25 + (boundedLevel / 3) * 0.75 : 0);
  }, [intensity, boundedLevel, speaking, reduced]);
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
    setVideoShown(false);
  }, [url, turn?.id]);
  useEffect(() => {
    if (videoPlaying) setVideoShown(true);
  }, [videoPlaying]);
  const videoStatus =
    capabilities?.video?.available && turn?.reply
      ? videoState?.status === 'generating'
        ? 'generating'
        : url
          ? 'done'
          : undefined
      : undefined;
  const height = useSpring(desktop ? 470 : 360, springs.snappy);
  const size = useSpring(desktop ? 210 : 196, springs.snappy);
  const targetHeight = desktop
    ? 470
    : collapsed
      ? videoStatus
        ? 128
        : 96
      : videoStatus
        ? 392
        : 360;
  const targetSize = desktop ? 210 : collapsed ? 60 : 196;
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
  const videoText = url && videoPlaying ? (turn?.content ?? '') : '';
  const plainReply = useMemo(() => stripMarkdown(videoText), [videoText]);
  const plainVoiceCaption = useMemo(
    () => stripMarkdown(voiceCaption),
    [voiceCaption],
  );
  const videoCaptionText =
    url && videoPlaying && turn
      ? videoCaption(plainReply, time, videoState?.result?.duration_s ?? 0)
      : '';
  const caption = videoCaptionText || plainVoiceCaption;
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
        data-speaking={speaking}
        data-video-status={videoStatus}
        style={{ height: reduced ? targetHeight : height }}
        right={
          !desktop && (
            <div className="flex items-center gap-1">
              {onHistory && (
                <button
                  type="button"
                  className="stage-new"
                  aria-label="对话记录"
                  onClick={onHistory}
                >
                  <History size={20} aria-hidden />
                </button>
              )}
              <button type="button" className="stage-new" onClick={onClear}>
                新对话
              </button>
            </div>
          )
        }
        portrait={
          <div className="stage-portrait-content">
            <motion.div
              className="stage-speaking"
              data-stage-level={speaking ? boundedLevel : 0}
              style={
                {
                  width: reduced ? targetSize : size,
                  height: reduced ? targetSize : size,
                  '--ring-expansion': expansion,
                  '--ring-opacity': opacity,
                } as MotionStyle
              }
            >
              {speaking &&
                !reduced &&
                [0, 1].map((ring) => (
                  <span
                    key={ring}
                    aria-hidden
                    className="stage-speaking-ring"
                  />
                ))}
              <motion.button
                ref={circle}
                type="button"
                className="stage-circle size-full"
                style={{ scale: reduced ? 1 : breathing }}
                aria-label={
                  small
                    ? '展开舞台'
                    : url && videoPlaying
                      ? '打开真人视频全屏'
                      : '播放或暂停当前句'
                }
                aria-expanded={!small}
                onClick={() => {
                  if (small) {
                    setCollapsed(false);
                    if (url && !videoPlaying) onToggle();
                    return;
                  }
                  if (url && videoPlaying) {
                    player.current?.pause();
                    setOpen(true);
                  } else onToggle();
                }}
              >
                {url && (videoPlaying || videoShown) ? (
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
                    personaId={personaId}
                    capabilities={capabilities}
                    className="size-full"
                    glow={false}
                  />
                )}
                {url && videoPlaying && (
                  <span className="stage-video-chip">
                    真人 ·{' '}
                    {Math.floor((videoState?.result?.duration_s ?? 0) / 60)}:
                    {String(
                      Math.round(videoState?.result?.duration_s ?? 0) % 60,
                    ).padStart(2, '0')}
                  </span>
                )}
                {reduced && speaking && (
                  <span
                    role="status"
                    aria-label="正在说话"
                    className="stage-speaking-chip"
                  >
                    正在说
                  </span>
                )}
              </motion.button>
            </motion.div>
            {videoStatus && (
              <span role="status" className="stage-video-status">
                {videoStatus === 'generating' ? (
                  <>
                    <LoaderCircle
                      size={12}
                      aria-hidden
                      className="stage-video-spinner"
                    />
                    真人视频生成中
                  </>
                ) : (
                  '真人视频已就绪 · 点头像播放'
                )}
              </span>
            )}
          </div>
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
        {desktop && history}
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
