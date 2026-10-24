import { useState } from 'react';
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
  TextLink,
  toast,
} from '../../components/ui';
import { Guessed } from './Guessed';
import { Merged } from './Merged';
import { Often } from './Often';
import { useAway, type Handoff } from './useAway';
import { Waiting, when } from './Waiting';

/**
 * A handoff put aside or settled, folded away; one put aside can be put back. A promise the person answered in words
 * and has not yet taken still can be taken (接下) or turned down (不接) here.
 */
function Done({
  item,
  onDone,
}: {
  item: Handoff;
  onDone: () => Promise<void>;
}) {
  const back = item.status === 'dismissed' || item.status === 'expired';
  const owed = item.status === 'replied' && item.commit?.pending === true;
  const post = (action: string, done: string) =>
    void api(`/api/persona/handoffs/${encodeURIComponent(item.id)}/${action}`, {
      method: 'POST',
      json: {},
    })
      .then(() => {
        toast(done, 'success');
        return onDone();
      })
      .catch((failure: unknown) =>
        toast(
          failure instanceof Error ? failure.message : '操作失败',
          'danger',
        ),
      );
  return (
    <ListRow
      variant="divided"
      title={<Text truncate>“{item.question}”</Text>}
      meta={[
        item.asker_name,
        item.status_label,
        owed && '待接下',
        when(item.replied_at ?? item.created_at),
      ]
        .filter(Boolean)
        .join(' · ')}
      trailing={
        <>
          {back && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => post('restore', '已放回')}
            >
              放回
            </Button>
          )}
          {owed && (
            <>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => post('accept', '已接下，记进承诺')}
              >
                接下
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => post('decline', '已回绝')}
              >
                不接
              </Button>
            </>
          )}
        </>
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
  const [apart, setApart] = useState<Set<string>>(new Set());
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
  const waiting = new Map(data.waiting.map((item) => [item.id, item]));
  // Questions that ask the same thing share a card, unless the person took them apart. A group is known by its
  // earliest question, which stays when others join it, so a reply being written is not lost to the page asking again.
  const merged = new Map<string, { ids: string[]; anchor: string }>();
  for (const ids of data.groups ?? []) {
    if (!ids.every((id) => waiting.has(id))) continue;
    const anchor = ids.reduce((first, id) => {
      const a = waiting.get(first)!;
      const b = waiting.get(id)!;
      return b.created_at < a.created_at ? id : first;
    }, ids[0]);
    if (!apart.has(anchor)) {
      const group = { ids, anchor };
      ids.forEach((id) => merged.set(id, group));
    }
  }
  const shown = new Set<string>();
  return (
    <Stack gap={5}>
      <Stack gap={3}>
        <Row gap={3} wrap>
          <Heading level={2} size="section">
            等你决定
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
            {data.waiting.map((item, index) => {
              const group = merged.get(item.id);
              if (!group)
                return (
                  <Waiting
                    key={item.id}
                    item={item}
                    startOpen={index === 0}
                    onDone={reload}
                  />
                );
              if (shown.has(group.anchor)) return null;
              shown.add(group.anchor);
              return (
                <Merged
                  key={group.anchor}
                  items={group.ids.flatMap((id) => waiting.get(id) ?? [])}
                  onSplit={() =>
                    setApart((previous) => new Set(previous).add(group.anchor))
                  }
                  onDone={reload}
                />
              );
            })}
          </Stack>
        )}
      </Stack>
      {(data.often?.length ?? 0) > 0 && (
        <Stack gap={3}>
          <Heading level={2} size="section">
            常被问到
          </Heading>
          <Stack as="ul" gap={0}>
            {data.often.map((item) => (
              <Often key={item.handoff_id} item={item} onDone={reload} />
            ))}
          </Stack>
        </Stack>
      )}
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
        <Disclosure
          summary={`已处理 ${aside.length}`}
          variant="plain"
          defaultOpen={aside.some(
            (item) => item.status === 'replied' && item.commit?.pending,
          )}
        >
          <Stack as="ul" gap={0}>
            {aside.map((item) => (
              <Done key={item.id} item={item} onDone={reload} />
            ))}
          </Stack>
        </Disclosure>
      )}
      {data.answers && data.answers.total > 0 && (
        <Row gap={2} wrap>
          <Text weight="bold">我的团队答案 {data.answers.total}</Text>
          {data.answers.stale > 0 && (
            <Badge tone="warning">{data.answers.stale} 可能过期</Badge>
          )}
          <TextLink to="?section=memories&view=answers">查看 ›</TextLink>
        </Row>
      )}
    </Stack>
  );
}
