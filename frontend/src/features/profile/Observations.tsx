import { useEffect, useState } from 'react';
import {
  Button,
  Dialog,
  Disclosure,
  ListRow,
  Notice,
  Row,
  Segmented,
  Skeleton,
  Stack,
  Text,
} from '../../components/ui';
import { api } from '../../lib/api';

type Mark = 'right' | 'wrong' | 'useless';
const MARKS: readonly { id: Mark; label: string }[] = [
  { id: 'right', label: '对' },
  { id: 'wrong', label: '不对' },
  { id: 'useless', label: '对但没用' },
];

interface Observation {
  id: string;
  kind: string;
  kind_label: string;
  text: string;
  quotes: { quote: string; date: string | null; dream: boolean }[];
  mark: Mark | null;
}
interface Observed {
  made_at: string | null;
  observations: Observation[];
}

const message = (failure: unknown) =>
  failure instanceof Error ? failure.message : String(failure);

/** One observation: what was seen, the words it rests on folded under it, and the person's mark. */
function Seen({
  observation,
  onMark,
}: {
  observation: Observation;
  onMark: (mark: Mark) => void;
}) {
  return (
    <ListRow
      variant="divided"
      title={observation.text}
      meta={observation.kind_label}
    >
      <Stack gap={2}>
        <Disclosure
          variant="plain"
          summary={
            <Text as="span" size="sm" tone="secondary">
              原话 {observation.quotes.length}
            </Text>
          }
        >
          <Stack as="ul" gap={1}>
            {observation.quotes.map((quote) => (
              <Text
                as="li"
                size="sm"
                tone="secondary"
                key={`${quote.date}-${quote.quote}`}
              >
                {quote.dream ? '梦' : (quote.date ?? '没有日期')}
                {quote.dream && quote.date ? ` ${quote.date}` : ''}：
                {quote.quote}
              </Text>
            ))}
          </Stack>
        </Disclosure>
        <Segmented<Mark | ''>
          label="这条说得对吗"
          value={observation.mark ?? ''}
          options={MARKS}
          onChange={(mark) => mark && onMark(mark)}
        />
      </Stack>
    </ListRow>
  );
}

/**
 * 剖析观察 (P1.7): a few observations made from the person's memories and dreams when they ask, each with the words it
 * rests on, marked 对, 不对 or 对但没用 by the person. Read beside the page and closed back to it.
 */
export function Observations({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [observed, setObserved] = useState<Observed | null>(null);
  const [making, setMaking] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setObserved(null);
    setError('');
    api<Observed>('/api/persona/observations', { signal: controller.signal })
      .then(setObserved)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(message(failure));
      });
    return () => controller.abort();
  }, [open]);

  const make = async () => {
    setMaking(true);
    setError('');
    try {
      setObserved(
        await api<Observed>('/api/persona/observations', { method: 'POST' }),
      );
    } catch (failure) {
      setError(message(failure));
    } finally {
      setMaking(false);
    }
  };

  const mark = async (id: string, value: Mark) => {
    setError('');
    try {
      setObserved(
        await api<Observed>(`/api/persona/observations/${id}/mark`, {
          method: 'PUT',
          json: { mark: value },
        }),
      );
    } catch (failure) {
      setError(message(failure));
    }
  };

  const seen = observed?.observations ?? [];
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="剖析观察"
      variant="side"
    >
      <Stack gap={3}>
        {error && (
          <Notice tone="danger" role="alert">
            {error}
          </Notice>
        )}
        {!observed ? (
          !error && (
            <Stack gap={2}>
              <Skeleton />
              <Skeleton />
            </Stack>
          )
        ) : (
          <>
            {seen.length > 0 ? (
              <Stack as="ul" gap={0}>
                {seen.map((observation) => (
                  <Seen
                    key={observation.id}
                    observation={observation}
                    onMark={(value) => void mark(observation.id, value)}
                  />
                ))}
              </Stack>
            ) : (
              <Text tone="secondary">
                {observed.made_at
                  ? '这次没看出能用原话撑住的。'
                  : '从你的记忆和梦里看几条，每条附原话。'}
              </Text>
            )}
            <Row>
              <Button
                size="sm"
                variant={seen.length ? 'ghost' : 'primary'}
                loading={making}
                onClick={() => void make()}
              >
                {observed.made_at ? '重新看' : '开始看'}
              </Button>
            </Row>
          </>
        )}
      </Stack>
    </Dialog>
  );
}
