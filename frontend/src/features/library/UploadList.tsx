import { Button, Meter } from '../../components/ui';
import type { Pick } from './useUploads';

/** The files still uploading (or that failed), with a way to stop. */
export function UploadList({
  picks,
  uploading,
  onStop,
}: {
  picks: Pick[];
  uploading: boolean;
  onStop: () => void;
}) {
  if (!picks.length) return null;
  return (
    <section aria-label="上传进度" className="space-y-3">
      {picks.map((pick) => (
        <div
          key={`${pick.file.name}-${pick.file.lastModified}-${pick.file.size}`}
          className="rounded-xl bg-surface p-4"
        >
          {pick.error ? (
            <p className="text-sm">
              {pick.file.name}：
              <span className="text-danger">{pick.error}</span>
            </p>
          ) : (
            <Meter
              label={
                pick.progress?.paused
                  ? `${pick.file.name}（网络中断，恢复后继续）`
                  : pick.file.name
              }
              value={
                pick.progress
                  ? (pick.progress.offset / pick.progress.size) * 100
                  : 0
              }
            />
          )}
        </div>
      ))}
      {uploading && (
        <Button variant="ghost" onClick={onStop}>
          停止上传（已传的部分下次接着传）
        </Button>
      )}
    </section>
  );
}
