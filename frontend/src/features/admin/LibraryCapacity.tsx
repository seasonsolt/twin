import { useEffect } from 'react';
import {
  Button,
  KeyValue,
  Notice,
  Section,
  Skeleton,
  Stack,
} from '../../components/ui';
import type { LibraryState } from '../../pages/Library';
import { useTeam } from '../../stores/team';

const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;

/** How much room the recordings have: the queue of those waiting to be transcribed, and the disk left for more. */
export const libraryRoom = (library: LibraryState) =>
  Math.max(
    0,
    library.capacity.free_bytes -
      library.capacity.arriving_bytes -
      library.capacity.headroom_bytes,
  );

/** Members whose own waiting recordings have reached the cap: ``max_pending`` limits each member, while
 * ``library.pending`` counts everyone's that the administrator sees. */
export function membersAtLimit(library: LibraryState) {
  if (library.max_pending <= 0) return 0;
  const waiting = new Map<string, number>();
  for (const recording of library.recordings)
    if (
      recording.uploader &&
      (recording.status === 'queued' || recording.status === 'transcribing')
    )
      waiting.set(
        recording.uploader,
        (waiting.get(recording.uploader) ?? 0) + 1,
      );
  return [...waiting.values()].filter((n) => n >= library.max_pending).length;
}

/** What the section's entry in the menu says when there is no more room. */
export function libraryStatus(library: LibraryState | null) {
  // A library that has not said how much room there is says nothing about running out of it.
  if (!library?.capacity) return undefined;
  if (membersAtLimit(library) > 0)
    return { label: '有人排满', tone: 'danger' as const };
  if (libraryRoom(library) <= 0)
    return { label: '空间不足', tone: 'danger' as const };
  return undefined;
}

/** The recording library's capacity, as the library reports it (``/api/library``). */
export function LibraryCapacity() {
  const library = useTeam((state) => state.library);
  const error = useTeam((state) => state.error);
  useEffect(() => {
    void useTeam.getState().refresh(true);
  }, []);
  if (!library?.capacity)
    return error ? (
      <Notice
        tone="danger"
        role="alert"
        actions={
          <Button
            variant="secondary"
            onClick={() => void useTeam.getState().refresh(true)}
          >
            重试
          </Button>
        }
      >
        {error}
      </Notice>
    ) : (
      <Skeleton className="h-32" />
    );
  const { capacity } = library;
  const full = membersAtLimit(library);
  return (
    <Stack gap={4}>
      <Section level={4} title="排队转写">
        <KeyValue
          items={[
            ['全队排队', `${library.pending} 条`],
            ['每人上限', `${library.max_pending} 条`],
            ...(full > 0
              ? ([['已排满', `${full} 位成员`]] as [string, string][])
              : []),
          ]}
        />
      </Section>
      <Section level={4} title="磁盘">
        <KeyValue
          items={[
            ['还能放', `约 ${gb(libraryRoom(library))}`],
            ['安全余量', gb(capacity.headroom_bytes)],
            ...(capacity.arriving > 0
              ? ([
                  [
                    '正在上传',
                    `${capacity.arriving} 项 · ${gb(capacity.arriving_bytes)}`,
                  ],
                ] as [string, string][])
              : []),
          ]}
        />
      </Section>
    </Stack>
  );
}
