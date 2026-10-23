import { useEffect } from 'react';
import { KeyValue, Meter, Section, Skeleton, Stack } from '../../components/ui';
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

/** What the section's entry in the menu says when there is no more room. */
export function libraryStatus(library: LibraryState | null) {
  // A library that has not said how much room there is says nothing about running out of it.
  if (!library?.capacity) return undefined;
  if (library.max_pending > 0 && library.pending >= library.max_pending)
    return { label: '队列已满', tone: 'danger' as const };
  if (libraryRoom(library) <= 0)
    return { label: '空间不足', tone: 'danger' as const };
  return undefined;
}

/** The recording library's capacity, as the library reports it (``/api/library``). */
export function LibraryCapacity() {
  const library = useTeam((state) => state.library);
  useEffect(() => {
    void useTeam.getState().refresh(true);
  }, []);
  if (!library?.capacity) return <Skeleton className="h-32" />;
  const { capacity } = library;
  return (
    <Stack gap={4}>
      <Section level={4} title="排队转写">
        <Meter
          label={`排队 ${library.pending} / ${library.max_pending}`}
          value={library.pending}
          max={Math.max(library.max_pending, 1)}
        />
      </Section>
      <Section level={4} title="磁盘">
        <KeyValue
          items={[
            ['还能放', `约 ${gb(libraryRoom(library))}`],
            ['留出的空间', gb(capacity.headroom_bytes)],
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
