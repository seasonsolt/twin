import { useRef } from 'react';
import { motion } from 'motion/react';
import { Badge, Button, Dialog } from '../../components/ui';
import { useMotionPreset } from '../../design/motion';
import { useStatus } from '../../stores/status';
import type { ChatReply } from '../chat/types';
import { CitationCard } from '../chat/Citations';
import { AvatarPreview } from '../avatar/AvatarPreview';
import { usePlayback } from './usePlayback';
import { RemoteVideoPanel } from './RemoteVideoPanel';

export function PlaybackDialog({
  open,
  onOpenChange,
  answer,
  personaName,
  trigger,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  answer: ChatReply;
  personaName: string;
  trigger: HTMLElement | null;
}) {
  const { reduced, transition } = useMotionPreset('layout');
  const panel = useRef<HTMLDivElement>(null);
  const status = useStatus((state) => state.data);
  const playback = usePlayback(open, answer, personaName, reduced);
  const { script, capabilities, position, playing, speaking, actions } =
    playback;
  const label =
    status?.labels.explicit || capabilities?.label || script?.explicit_label;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`${script?.persona_name || personaName} · 回放`}
      body="空格播放 / 暂停，左右方向键逐句切换；减少动态效果时仅朗读可自动推进。"
      className="w-[min(760px,calc(100%_-_32px))]"
      exitTransition={transition}
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        panel.current?.focus();
      }}
      onCloseAutoFocus={(event) => {
        event.preventDefault();
        if (trigger?.isConnected) trigger.focus();
      }}
    >
      <div
        ref={panel}
        tabIndex={-1}
        className="space-y-4 outline-none"
        aria-label="回放控制"
        onKeyDown={(event) => {
          if (
            !script ||
            event.altKey ||
            event.ctrlKey ||
            event.metaKey ||
            event.target instanceof HTMLVideoElement
          )
            return;
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault();
            actions.step(event.key === 'ArrowLeft' ? -1 : 1);
          } else if (event.key === ' ' && event.target === panel.current) {
            event.preventDefault();
            actions.toggle();
          }
        }}
      >
        {label && (
          <p role="note" className="text-sm text-secondary">
            {label}
          </p>
        )}
        {!script && !playback.error && <p role="status">正在准备回放…</p>}
        {playback.error && (
          <div role="alert" className="text-danger">
            <p>{playback.error}</p>
            {!script && (
              <Button variant="secondary" onClick={actions.retry}>
                重试
              </Button>
            )}
          </div>
        )}
        {script && (
          <>
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={actions.toggle}
                disabled={playback.voiceLoading || (reduced && !speaking)}
              >
                {playing
                  ? '暂停'
                  : reduced && !speaking
                    ? '手动逐句回放'
                    : '播放'}
              </Button>
              <Button
                variant="secondary"
                onClick={() => actions.step(-1)}
                disabled={position === 0}
              >
                上一句
              </Button>
              <Button
                variant="secondary"
                onClick={() => actions.step(1)}
                disabled={position === script.segments.length - 1}
              >
                下一句
              </Button>
              <Button
                variant="secondary"
                onClick={actions.export}
                loading={playback.exporting}
                disabled={playback.exportingVideo}
              >
                导出
              </Button>
              <Button
                variant="secondary"
                onClick={actions.exportVideo}
                loading={playback.exportingVideo}
                disabled={playback.exporting}
              >
                导出视频
              </Button>
            </div>
            {open &&
              capabilities?.video?.available &&
              !script.abstain &&
              label && (
                <RemoteVideoPanel
                  key={JSON.stringify(answer)}
                  answer={answer}
                  personaName={personaName}
                  label={label}
                />
              )}
            {capabilities?.available && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  aria-pressed={speaking}
                  loading={playback.voiceLoading}
                  onClick={actions.voice}
                >
                  朗读
                </Button>
                <span className="text-xs text-secondary">
                  语音由 AI 合成（{capabilities.backend}）
                </span>
              </div>
            )}
            <p role="status" className="text-sm text-secondary">
              {playback.voiceNotice}
            </p>
            <p className="text-xs text-tertiary">
              {position + 1} / {script.segments.length}
              {script.abstain ? ' · 分身弃权，仅展示提示' : ''}
            </p>
            <div className="flex flex-col gap-5 sm:flex-row">
              {open && capabilities?.avatar && (
                <AvatarPreview
                  capabilities={capabilities}
                  mouth={playback.mouth}
                  speaking={speaking && playing}
                  label={label}
                />
              )}
              <div className="min-w-0 flex-1">
                <p
                  aria-live="polite"
                  aria-atomic="true"
                  className="mb-4 whitespace-pre-wrap text-lg"
                >
                  {script.segments[position].text}
                </p>
                <ol aria-label="已展示的句子" className="space-y-2">
                  {script.segments
                    .slice(0, position + 1)
                    .map((segment, index) => (
                      <motion.li
                        key={segment.index}
                        layout={reduced ? false : 'position'}
                        transition={transition}
                        aria-current={index === position ? 'step' : undefined}
                        className={`relative rounded-md px-3 py-2 ${index === position ? 'text-primary' : 'text-tertiary'}`}
                      >
                        {index === position && (
                          <motion.span
                            aria-hidden
                            layoutId={reduced ? undefined : 'playback-current'}
                            transition={transition}
                            className="absolute inset-0 rounded-md border border-accent/15 bg-accent/5"
                          />
                        )}
                        <span className="relative whitespace-pre-wrap">
                          {segment.text}
                        </span>
                      </motion.li>
                    ))}
                </ol>
              </div>
            </div>
            <h3 className="font-semibold">回答依据</h3>
            <p className="text-sm text-secondary">
              引用属于整份回答，并非逐句对应。
            </p>
            {script.citations.length ? (
              <ul aria-label="回答依据" className="space-y-2">
                {script.citations.map((citation) => {
                  const cited = answer.cited?.find(
                    (entry) => entry.id === citation.ref_id,
                  );
                  return cited ? (
                    <CitationCard key={citation.ref_id} citation={cited} />
                  ) : (
                    <li key={citation.ref_id}>
                      <Badge>{citation.ref_id}</Badge>
                      {citation.reason && `：${citation.reason}`}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-secondary">没有有效引用。</p>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}
