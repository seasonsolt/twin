import { useState } from 'react';
import { api } from '../../lib/api';
import {
  ActionMenu,
  Button,
  Dialog,
  Field,
  Input,
  ListRow,
  Row,
  Stack,
  Text,
  Textarea,
  toast,
} from '../../components/ui';
import type { OftenReply } from './useAway';

/**
 * A reply the twin has given again and again: offered once as a team answer. 设为团队答案 opens the title (the question,
 * summed up) and the words, both the person's to change; “⋯ → 不用” means it is not offered again.
 */
export function Often({
  item,
  onDone,
}: {
  item: OftenReply;
  onDone: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [body, setBody] = useState(item.reply);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const fail = (failure: unknown, fallback: string) =>
    failure instanceof Error ? failure.message : fallback;
  const save = async () => {
    setBusy(true);
    setError('');
    try {
      await api('/api/persona/team-answers', {
        method: 'POST',
        json: {
          handoff_id: item.handoff_id,
          title: title.trim(),
          body: body.trim(),
        },
      });
      toast('已设为团队答案', 'success');
      setOpen(false);
      await onDone();
    } catch (failure) {
      setError(fail(failure, '没能设好'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <ListRow
        variant="divided"
        title={<Text truncate>{item.title}</Text>}
        meta={`${item.askers.join('、')} · 近 ${item.days} 天 ${item.uses} 次`}
        trailing={
          <>
            <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
              设为团队答案
            </Button>
            <ActionMenu
              label={`更多：${item.title}`}
              items={[
                {
                  label: '不用',
                  onSelect: () =>
                    void api(
                      `/api/persona/handoffs/${encodeURIComponent(item.handoff_id)}/often/decline`,
                      { method: 'POST', json: {} },
                    )
                      .then(() => onDone())
                      .catch((failure: unknown) =>
                        toast(fail(failure, '操作失败'), 'danger'),
                      ),
                },
              ]}
            />
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen} title="设为团队答案">
        <Stack gap={3}>
          <Field label="标题" id={`often-title-${item.handoff_id}`}>
            <Input
              id={`often-title-${item.handoff_id}`}
              value={title}
              maxLength={80}
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>
          <Field label="内容" id={`often-body-${item.handoff_id}`}>
            <Textarea
              id={`often-body-${item.handoff_id}`}
              value={body}
              rows={4}
              onChange={(event) => setBody(event.target.value)}
            />
          </Field>
          {error && (
            <Text role="alert" size="sm" tone="danger">
              {error}
            </Text>
          )}
          <Row gap={2} justify="end">
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              取消
            </Button>
            <Button
              loading={busy}
              disabled={!title.trim() || !body.trim()}
              onClick={() => void save()}
            >
              设好
            </Button>
          </Row>
        </Stack>
      </Dialog>
    </>
  );
}
