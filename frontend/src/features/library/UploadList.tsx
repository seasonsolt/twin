import { Button, Card, Meter, Stack, Text } from '../../components/ui';
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
    <Stack as="section" gap={3} aria-label="上传进度">
      {picks.map((pick) => (
        <Card
          as="div"
          variant="soft"
          padding="md"
          key={`${pick.file.name}-${pick.file.lastModified}-${pick.file.size}`}
        >
          {pick.error ? (
            <Text size="sm">
              {pick.file.name}：
              <Text as="span" size="inherit" tone="danger">
                {pick.error}
              </Text>
            </Text>
          ) : (
            <Meter
              label={
                pick.progress?.paused
                  ? `${pick.file.name}（网络中断，恢复后继续）`
                  : pick.progress?.preparing !== undefined
                    ? `${pick.file.name}（正在本机提取音频）`
                    : pick.file.name
              }
              value={
                pick.progress?.preparing !== undefined
                  ? pick.progress.preparing * 100
                  : pick.progress
                    ? (pick.progress.offset / pick.progress.size) * 100
                    : 0
              }
            />
          )}
        </Card>
      ))}
      {uploading && (
        <Button variant="ghost" onClick={onStop}>
          停止上传（已传的部分下次接着传）
        </Button>
      )}
    </Stack>
  );
}
