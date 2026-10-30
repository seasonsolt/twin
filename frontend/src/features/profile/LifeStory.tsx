import { useEffect, useState } from 'react';
import {
  Dialog,
  Disclosure,
  ListRow,
  Notice,
  Skeleton,
  Stack,
  Text,
} from '../../components/ui';
import { api } from '../../lib/api';

interface StoryItem {
  item_id: string;
  facet_id: string;
  facet_name: string;
  statement: string;
  /** written: the year is in its words; dated: the year its words were dated as they happened. */
  basis: 'written' | 'dated' | null;
}
interface StoryYear {
  year: number;
  /** The last year of a run of years with nothing, or the year itself. */
  until: number;
  items: StoryItem[];
}
interface Story {
  years: StoryYear[];
  undated: StoryItem[];
}

/** A memory of the story. One dated only by when its words were written says so: the year may be when it was
 * told, not when it happened. */
function Told({ item }: { item: StoryItem }) {
  return (
    <li>
      <Text size="sm" twoLines>
        {item.statement}
      </Text>
      {item.basis === 'dated' && (
        <Text as="span" size="xs" tone="tertiary">
          记于当年
        </Text>
      )}
    </li>
  );
}

/**
 * 生命叙事 (P1.6): what the person has told of their life, year by year, read only. A year comes only from the words
 * themselves; a run of years with nothing is one blank row, never filled; what has no year waits, folded, at the end.
 */
export function LifeStory({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [story, setStory] = useState<Story | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setStory(null);
    setError('');
    api<Story>('/api/persona/life-story', { signal: controller.signal })
      .then(setStory)
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        setError(failure instanceof Error ? failure.message : String(failure));
      });
    return () => controller.abort();
  }, [open]);

  const empty = story && !story.years.length && !story.undated.length;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="生命线"
      variant="side"
    >
      {error ? (
        <Notice tone="danger" role="alert">
          {error}
        </Notice>
      ) : !story ? (
        <Stack gap={2}>
          <Skeleton />
          <Skeleton />
        </Stack>
      ) : empty ? (
        <Text tone="secondary">回顾人生之后，这里按年份排出来。</Text>
      ) : (
        <Stack gap={3}>
          <Stack as="ol" gap={0} aria-label="按年份">
            {story.years.map((span) =>
              span.items.length ? (
                <ListRow
                  key={span.year}
                  variant="divided"
                  title={String(span.year)}
                >
                  <Stack as="ul" gap={1}>
                    {span.items.map((item) => (
                      <Told key={item.item_id} item={item} />
                    ))}
                  </Stack>
                </ListRow>
              ) : (
                <ListRow
                  key={span.year}
                  variant="dashed"
                  aria-label="没有资料"
                  title={
                    <Text as="span" size="sm" tone="tertiary">
                      {span.until > span.year
                        ? `${span.year}–${span.until}`
                        : span.year}
                    </Text>
                  }
                />
              ),
            )}
          </Stack>
          {story.undated.length > 0 && (
            <Disclosure
              variant="plain"
              summary={
                <Text as="span" size="sm" tone="secondary">
                  年份不明 {story.undated.length}
                </Text>
              }
            >
              <Stack as="ul" gap={1}>
                {story.undated.map((item) => (
                  <Told key={item.item_id} item={item} />
                ))}
              </Stack>
            </Disclosure>
          )}
        </Stack>
      )}
    </Dialog>
  );
}
