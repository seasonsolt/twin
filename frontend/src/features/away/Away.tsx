import { api } from '../../lib/api';
import {
  Badge,
  Button,
  Disclosure,
  Heading,
  ListRow,
  Row,
  Skeleton,
  Stack,
  Text,
  toast,
} from '../../components/ui';
import { Guessed } from './Guessed';
import { useAway, type Handoff } from './useAway';
import { Waiting, when } from './Waiting';

/** A handoff put aside or settled, folded away; one put aside can be put back. */
function Done({
  item,
  onDone,
}: {
  item: Handoff;
  onDone: () => Promise<void>;
}) {
  const back = item.status === 'dismissed' || item.status === 'expired';
  return (
    <ListRow
      variant="divided"
      title={<Text truncate>“{item.question}”</Text>}
      meta={[
        item.asker_name,
        item.status_label,
        when(item.replied_at ?? item.created_at),
      ]
        .filter(Boolean)
        .join(' · ')}
      trailing={
        back && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              void api(
                `/api/persona/handoffs/${encodeURIComponent(item.id)}/restore`,
                { method: 'POST', json: {} },
              )
                .then(() => onDone())
                .catch((failure: unknown) =>
                  toast(
                    failure instanceof Error ? failure.message : '操作失败',
                    'danger',
                  ),
                )
            }
          >
            放回
          </Button>
        )
      }
    />
  );
}

/**
 * 你不在时: what happened to the twin's answers while the person was away, for the person alone. What waits for their
 * decision comes first, one line a question and the first one opened; then the answers the twin guessed, to confirm or
 * put right; what it answered from the profile is folded; what was put aside or settled waits below.
 * `away` is the list when the page already asks for it (to count it in the tab).
 */
export function Away({ away }: { away?: ReturnType<typeof useAway> }) {
  const own = useAway(!away);
  const { data, error, reload } = away ?? own;
  if (error)
    return (
      <Stack gap={2} role="alert">
        <Text tone="danger">{error}</Text>
        <Row>
          <Button variant="secondary" onClick={() => void reload()}>
            重试加载
          </Button>
        </Row>
      </Stack>
    );
  if (!data) return <Skeleton className="h-40" />;
  const aside = [...data.shelved, ...data.settled];
  return (
    <Stack gap={5}>
      <Stack gap={3}>
        <Row gap={3} wrap>
          <Heading level={2} size="section">
            等你决定 {data.waiting.length}
          </Heading>
          <Text size="xs" tone="secondary" className="ml-auto">
            近 {data.days} 天 · 答了 {data.answered} 问
          </Text>
          <Badge title="这一页只有你看得到">仅你可见</Badge>
        </Row>
        {data.waiting.length === 0 ? (
          <Text size="sm" tone="secondary">
            没有等你决定的事。
          </Text>
        ) : (
          <Stack as="ul" gap={0}>
            {data.waiting.map((item, index) => (
              <Waiting
                key={item.id}
                item={item}
                startOpen={index === 0}
                onDone={reload}
              />
            ))}
          </Stack>
        )}
      </Stack>
      {data.guessed.length > 0 && (
        <Stack gap={3}>
          <Heading level={2} size="section">
            分身推测 {data.guessed.length}
          </Heading>
          <Stack as="ul" gap={0}>
            {data.guessed.map((item) => (
              <Guessed
                key={`${item.conversation_id}-${item.turn}`}
                item={item}
                onDone={reload}
              />
            ))}
          </Stack>
        </Stack>
      )}
      {data.sourced_count > 0 && (
        <Disclosure summary={`有出处 ${data.sourced_count}`} variant="plain">
          <Stack as="ul" gap={0}>
            {data.sourced.map((item) => (
              <ListRow
                key={`${item.conversation_id}-${item.turn}`}
                variant="divided"
                title={
                  <Text truncate>
                    {item.asker_name}问：{item.question}
                  </Text>
                }
                meta={item.answer}
              />
            ))}
          </Stack>
        </Disclosure>
      )}
      {aside.length > 0 && (
        <Disclosure summary={`已处理 ${aside.length}`} variant="plain">
          <Stack as="ul" gap={0}>
            {aside.map((item) => (
              <Done key={item.id} item={item} onDone={reload} />
            ))}
          </Stack>
        </Disclosure>
      )}
    </Stack>
  );
}
