import { useCallback, useEffect, useState } from 'react';
import { api } from '../../lib/api';
import {
  Badge,
  Button,
  Heading,
  ListRow,
  Row,
  Skeleton,
  Stack,
  Text,
  TextLink,
  toast,
} from '../../components/ui';
import { dayLabel, type LensUse } from './types';

// Enough to see what the lens is used for; the rest is a tap away.
const SHOWN = 5;

/**
 * 最近被用在哪: what the lens was asked and said, newest first, never who asked. 纠正 says what it said there was
 * wrong; a facet corrected enough times stops being used. `facet` narrows the list to the uses that touched it.
 */
export function LensUses({
  lensId,
  facet,
  version,
  onFacet,
  onChanged,
}: {
  lensId: string;
  facet: string | null;
  /** Changes when the lens was changed elsewhere, so the list is read again. */
  version: number;
  onFacet: (facet: string | null) => void;
  onChanged: () => Promise<void> | void;
}) {
  const [uses, setUses] = useState<LensUse[] | null>(null);
  const [error, setError] = useState('');
  const [all, setAll] = useState(false);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const query = facet ? `?facet=${encodeURIComponent(facet)}` : '';
        const found = await api<{ uses: LensUse[] }>(
          `/api/persona/lenses/${encodeURIComponent(lensId)}/uses${query}`,
          { signal },
        );
        setUses(found.uses);
        setError('');
      } catch (failure) {
        if (signal?.aborted) return;
        setError(failure instanceof Error ? failure.message : '加载失败');
      }
    },
    [lensId, facet],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, version]);
  const correct = async (use: LensUse) => {
    try {
      await api(
        `/api/persona/lenses/${encodeURIComponent(lensId)}/uses/${encodeURIComponent(use.id)}/correct`,
        { method: 'POST', json: {} },
      );
      await load();
      await onChanged();
    } catch (failure) {
      toast(failure instanceof Error ? failure.message : '操作失败', 'danger');
    }
  };
  const shown = uses ? (all ? uses : uses.slice(0, SHOWN)) : [];
  return (
    <Stack gap={2}>
      <Row gap={2} wrap>
        <Heading level={3} size="section">
          最近被用在哪
        </Heading>
        <Badge title="只记问题和赋能说的话">不显示提问人</Badge>
        {facet && <TextLink onClick={() => onFacet(null)}>看全部</TextLink>}
      </Row>
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
      {!uses && !error && <Skeleton className="h-16" />}
      {uses && uses.length === 0 && (
        <Text size="sm" tone="secondary">
          还没有人用过。
        </Text>
      )}
      <Stack as="ul" gap={0}>
        {shown.map((use) => (
          <ListRow
            key={use.id}
            variant="divided"
            title={<Text truncate>{use.question}</Text>}
            meta={
              use.said ? (
                <Text size="sm" tone="secondary" truncate>
                  → {use.said.split('\n').join('；')}
                </Text>
              ) : (
                <Text size="sm" tone="secondary">
                  未回答
                </Text>
              )
            }
            trailing={
              <>
                <Text as="span" size="xs" tone="secondary">
                  {dayLabel(use.at)}
                </Text>
                {use.corrected ? (
                  <Badge>已纠正</Badge>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-label={`纠正：${use.question}`}
                    onClick={() => void correct(use)}
                  >
                    纠正
                  </Button>
                )}
              </>
            }
          />
        ))}
      </Stack>
      {uses && uses.length > SHOWN && !all && (
        <Row>
          <Button size="sm" variant="ghost" onClick={() => setAll(true)}>
            看全部 {uses.length} 条
          </Button>
        </Row>
      )}
    </Stack>
  );
}
