import { useState } from 'react';
import { api } from '../../lib/api';
import {
  ActionMenu,
  Badge,
  Button,
  Disclosure,
  Heading,
  ListRow,
  Row,
  Skeleton,
  Stack,
  Text,
  Textarea,
  toast,
} from '../../components/ui';
import { useFollowups, type Followup } from './useFollowups';

export type { Followup } from './useFollowups';

function when(iso: string) {
  const match = /^\d{4}-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(iso);
  return match ? `${Number(match[1])}月${Number(match[2])}日 ${match[3]}` : '';
}

/** One question waiting for the person: asked again and again, the twin could not answer. 回复 opens the field for
 * their own words; “⋯” sets it aside. */
function Question({
  item,
  onDone,
}: {
  item: Followup;
  onDone: () => Promise<void>;
}) {
  const [replying, setReplying] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const id = `followup-${item.followup_id}`;
  const run = async (request: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError('');
    try {
      await request();
      toast(done, 'success');
      await onDone();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };
  const base = `/api/persona/followups/${encodeURIComponent(item.followup_id)}`;
  const dismiss = () =>
    run(
      () =>
        api(`${base}/status`, {
          method: 'POST',
          json: { status: 'dismissed' },
        }),
      '已放到一边，分身遇到这个问题仍会说要问你本人',
    );
  return (
    <ListRow
      variant="divided"
      aria-label={item.question}
      title={item.question}
      meta={
        <Row gap={2} wrap>
          <Text as="span" size="sm" tone="secondary">
            {item.asked > 1 ? `被问 ${item.asked} 次 · ` : ''}
            {when(item.last_at)}
          </Text>
          {item.unresolved && <Badge tone="warning">还答不上</Badge>}
        </Row>
      }
      trailing={
        !replying && (
          <>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => setReplying(true)}
            >
              回复
            </Button>
            <ActionMenu
              label={`更多：${item.question}`}
              items={[
                {
                  label: '不用回答',
                  disabled: busy,
                  onSelect: () => void dismiss(),
                },
              ]}
            />
          </>
        )
      }
    >
      {replying && (
        <Stack gap={2}>
          {item.previous && (
            <Text size="sm" tone="secondary">
              接着「{item.previous}」问
            </Text>
          )}
          <label htmlFor={id} className="sr-only">
            你的回答
          </label>
          <Textarea
            id={id}
            autoFocus
            value={text}
            placeholder="用你自己的话回答，会作为你的原话记下来"
            onChange={(event) => setText(event.target.value)}
          />
          {error && (
            <Text role="alert" size="sm" tone="danger">
              {error}
            </Text>
          )}
          <Row gap={2} justify="end">
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => setReplying(false)}
            >
              取消
            </Button>
            <Button
              size="sm"
              loading={busy}
              disabled={!text.trim()}
              onClick={() =>
                void run(
                  () =>
                    api(`${base}/answer`, {
                      method: 'POST',
                      json: { text: text.trim() },
                    }),
                  '已记下，正在整理成记忆',
                )
              }
            >
              记下
            </Button>
          </Row>
        </Stack>
      )}
      {!replying && error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
    </ListRow>
  );
}

/**
 * 你不在时: the questions the twin could not answer, for the person themselves. One line a question; 回复 opens the
 * field for their words and “⋯” sets the question aside. What was answered or set aside waits below, folded, and a
 * question set aside can be put back. `away` is the list when the page already asks for it (to count it in the tab).
 */
export function Followups({
  away,
}: {
  away?: ReturnType<typeof useFollowups>;
}) {
  const own = useFollowups(!away);
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
  const all = data.items ?? [];
  const pending = all.filter((item) => item.status === 'pending');
  const answered = all.filter((item) => item.status === 'answered');
  const dismissed = all.filter((item) => item.status === 'dismissed');
  return (
    <Stack gap={4}>
      <Heading level={2} size="section">
        待你回答 {pending.length}
      </Heading>
      {pending.length === 0 ? (
        <Text size="sm" tone="secondary">
          没有待回答的问题。
        </Text>
      ) : (
        <Stack as="ul" gap={0}>
          {pending.map((item) => (
            <Question key={item.followup_id} item={item} onDone={reload} />
          ))}
        </Stack>
      )}
      {answered.length > 0 && (
        <Disclosure summary={`已回答 ${answered.length}`} variant="plain">
          <Stack as="ul" gap={0}>
            {answered.map((item) => (
              <ListRow
                key={item.followup_id}
                variant="divided"
                title={item.question}
                meta={item.handled_at ? when(item.handled_at) : undefined}
              />
            ))}
          </Stack>
        </Disclosure>
      )}
      {dismissed.length > 0 && (
        <Disclosure summary={`不用回答 ${dismissed.length}`} variant="plain">
          <Stack as="ul" gap={0}>
            {dismissed.map((item) => (
              <ListRow
                key={item.followup_id}
                variant="divided"
                title={item.question}
                meta={
                  item.asked_since > 0
                    ? `之后又被问了 ${item.asked_since} 次`
                    : undefined
                }
                trailing={
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      void api(
                        `/api/persona/followups/${encodeURIComponent(item.followup_id)}/status`,
                        { method: 'POST', json: { status: 'pending' } },
                      )
                        .then(() => reload())
                        .catch((failure: unknown) =>
                          toast(
                            failure instanceof Error
                              ? failure.message
                              : '操作失败',
                            'danger',
                          ),
                        )
                    }
                  >
                    放回
                  </Button>
                }
              />
            ))}
          </Stack>
        </Disclosure>
      )}
    </Stack>
  );
}
