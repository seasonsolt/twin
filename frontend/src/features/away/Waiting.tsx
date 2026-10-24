import { useState } from 'react';
import { ApiError, api } from '../../lib/api';
import {
  ActionMenu,
  AvatarFrame,
  Badge,
  Button,
  Card,
  Disclosure,
  Input,
  ListRow,
  Row,
  Stack,
  Text,
  Textarea,
  toast,
} from '../../components/ui';
import { ReplyTierChoice, type ReplyTier } from './ReplyTier';
import type { Handoff } from './useAway';
import { useReplyDraft } from './useReplyDraft';

/** The time of day of a moment, where the reader is (the server keeps UTC). */
export function clock(iso: string) {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? ''
    : at.toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      });
}

export function when(iso: string) {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? ''
    : `${at.getMonth() + 1}月${at.getDate()}日 ${clock(iso)}`;
}

function dayText(iso: string) {
  const [, month, date] = iso.split('-').map(Number);
  return `${month}月${date}日`;
}

/** What a handoff says under the name: who asked (unless the name is already beside it), when it came and how long it
 * waits. */
function Meta({ item, named = true }: { item: Handoff; named?: boolean }) {
  const left =
    item.days_left === null
      ? ''
      : item.days_left <= 0
        ? '今天到期'
        : `还剩 ${item.days_left} 天`;
  return (
    <>
      {[named && (item.asker_name || '来源不明'), when(item.created_at), left]
        .filter(Boolean)
        .join(' · ')}
    </>
  );
}

/**
 * One colleague's question the twin left to the person, as a row: the question, who asked and what kind of thing it
 * is, and 回复, which opens it. “⋯” sets it aside. Opened, it is a card: what the twin said, the promise asked for
 * (take it, move its date, turn it down) and the box for their own words, which go into the asker's conversation.
 */
export function Waiting({
  item,
  onDone,
  startOpen = false,
}: {
  item: Handoff;
  onDone: () => Promise<void>;
  startOpen?: boolean;
}) {
  const [open, setOpen] = useState(startOpen);
  const [moving, setMoving] = useState(false);
  const [due, setDue] = useState(item.commit?.due ?? '');
  const [tier, setTier] = useState<ReplyTier>('colleague');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const base = `/api/persona/handoffs/${encodeURIComponent(item.id)}`;
  /** The twin's draft of the person's answer goes into the box, for them to change; nothing is sent. */
  const { text, edit, clear, drafting, draft, replaced, restore } =
    useReplyDraft(`${base}/draft`, setError);
  const run = async (
    request: () => Promise<unknown>,
    done: string,
    after?: () => void,
  ) => {
    setBusy(true);
    setError('');
    try {
      await request();
      toast(done, 'success');
      after?.();
      await onDone();
    } catch (failure) {
      const message = failure instanceof Error ? failure.message : '保存失败';
      setError(message);
      // A row folded away has no place for it.
      if (!open) toast(message, 'danger');
      // Answered or being written back meanwhile: the list is out of date, so it is read again.
      if (failure instanceof ApiError && failure.status === 409) await onDone();
    } finally {
      setBusy(false);
    }
  };
  const post = (action: string, json: object = {}) =>
    api(`${base}/${action}`, { method: 'POST', json });
  const dismiss = (
    <ActionMenu
      label={`更多：${item.question}`}
      items={[
        {
          label: '不答',
          disabled: busy,
          onSelect: () => void run(() => post('dismiss'), '已放到一边'),
        },
      ]}
    />
  );
  if (!open)
    return (
      <ListRow
        variant="divided"
        aria-label={item.question}
        leading={<Initial name={item.asker_name} />}
        title={<Text truncate>“{item.question}”</Text>}
        meta={
          <>
            <Meta item={item} /> · {item.kind_label}
          </>
        }
        trailing={
          <>
            <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
              回复
            </Button>
            {dismiss}
          </>
        }
      />
    );
  const commit = item.commit;
  return (
    <Card as="article" variant="outline" aria-label={item.question}>
      <Stack gap={3}>
        <Row gap={3} wrap>
          <Initial name={item.asker_name} />
          <Stack gap={0} grow>
            <Text weight="bold">{item.asker_name || '来源不明'}</Text>
            <Text size="xs" tone="secondary">
              <Meta item={item} named={false} />
            </Text>
          </Stack>
          {dismiss}
        </Row>
        <Text size="lg">“{item.question}”</Text>
        {item.context && (
          <Text size="sm" tone="secondary">
            接着「{item.context}」问
          </Text>
        )}
        {item.answer && (
          <Disclosure
            summary="分身的回答"
            variant="plain"
            defaultOpen={startOpen}
          >
            <Text tone="secondary">{item.answer}</Text>
          </Disclosure>
        )}
        {commit?.pending && (
          <Card variant="note" padding="md">
            <Stack gap={2}>
              <Stack gap={0}>
                <Text size="xs" tone="secondary">
                  待接承诺
                </Text>
                <Text weight="bold">
                  {commit.what}
                  {commit.due ? `（${dayText(commit.due)}前）` : ''}
                </Text>
              </Stack>
              <Row gap={2} wrap>
                {moving && (
                  <Input
                    type="date"
                    aria-label="新的截止日期"
                    value={due}
                    onChange={(event) => setDue(event.target.value)}
                    className="w-auto"
                  />
                )}
                <Button
                  size="sm"
                  loading={busy}
                  onClick={() =>
                    void run(
                      () =>
                        post(
                          'accept',
                          moving && due && due !== commit.due ? { due } : {},
                        ),
                      '已接下，记进承诺',
                    )
                  }
                >
                  接下
                </Button>
                {!moving && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() => setMoving(true)}
                  >
                    改时间
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => void run(() => post('decline'), '已回绝')}
                >
                  不接
                </Button>
              </Row>
            </Stack>
          </Card>
        )}
        <Stack gap={2}>
          <label htmlFor={`reply-${item.id}`} className="sr-only">
            {item.source_known ? `以本人回复${item.asker_name}` : '你的回答'}
          </label>
          <Textarea
            id={`reply-${item.id}`}
            value={text}
            placeholder={
              item.source_known
                ? `发到${item.asker_name}的对话`
                : '用你自己的话回答，会作为你的原话记下来'
            }
            onChange={(event) => edit(event.target.value)}
          />
          {error && (
            <Text role="alert" size="sm" tone="danger">
              {error}
            </Text>
          )}
          <Row gap={2} justify="between" wrap>
            <ReplyTierChoice
              value={tier}
              onChange={setTier}
              disabled={busy}
              keepable={!item.source_known}
            />
            <Row gap={2}>
              {!item.source_known && <Badge>来源不明</Badge>}
              <Button
                size="sm"
                variant="ghost"
                loading={drafting}
                disabled={busy}
                onClick={() => void draft()}
              >
                请分身起草
              </Button>
              {replaced && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={restore}
                >
                  换回我写的
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => setOpen(false)}
              >
                收起
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={busy}
                disabled={!text.trim()}
                onClick={() =>
                  void run(
                    () => post('reply', { text: text.trim(), tier }),
                    !item.source_known
                      ? '已记下'
                      : tier === 'none'
                        ? '已发送'
                        : '已发送，正在整理成记忆',
                    clear,
                  )
                }
              >
                {item.source_known ? '发送' : '记下'}
              </Button>
            </Row>
          </Row>
        </Stack>
      </Stack>
    </Card>
  );
}

/** The asker's first letter in a round frame. */
export function Initial({ name }: { name: string }) {
  return <AvatarFrame size="sm">{(name || '?').slice(0, 1)}</AvatarFrame>;
}
