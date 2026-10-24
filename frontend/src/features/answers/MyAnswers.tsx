import { useCallback, useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { usePersonaId } from '../../lib/usePersonaState';
import {
  ActionMenu,
  Badge,
  Button,
  Dialog,
  EmptyState,
  Field,
  Input,
  ListRow,
  Notice,
  Row,
  Skeleton,
  Stack,
  Text,
  Textarea,
  toast,
  useConfirm,
} from '../../components/ui';
import { AWAY_CHANGED } from '../away/useAway';
import { dayOf, type MyTeamAnswer } from './types';

const message = (failure: unknown, fallback: string) =>
  failure instanceof Error ? failure.message : fallback;

/** Put an answer right: its title and words are the person's to change, and it stands again from today. */
function Revise({
  answer,
  onClose,
  onSaved,
}: {
  answer: MyTeamAnswer;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [title, setTitle] = useState(answer.title);
  const [body, setBody] = useState(answer.body);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async () => {
    setBusy(true);
    setError('');
    try {
      await api(`/api/persona/team-answers/${encodeURIComponent(answer.id)}`, {
        method: 'PATCH',
        json: { title: title.trim(), body: body.trim() },
      });
      toast('已更新', 'success');
      onClose();
      await onSaved();
    } catch (failure) {
      setError(message(failure, '没能保存'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title="更新团队答案"
    >
      <Stack gap={3}>
        <Field label="标题" id={`answer-title-${answer.id}`}>
          <Input
            id={`answer-title-${answer.id}`}
            value={title}
            maxLength={80}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <Field label="内容" id={`answer-body-${answer.id}`}>
          <Textarea
            id={`answer-body-${answer.id}`}
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
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            取消
          </Button>
          <Button
            loading={busy}
            disabled={!title.trim() || !body.trim()}
            onClick={() => void save()}
          >
            保存
          </Button>
        </Row>
      </Stack>
    </Dialog>
  );
}

/**
 * 我设的团队答案: what the person made the team's, newest first, those that may be out of date at the top with what they
 * said since. 更新 puts one right (it stands again), 仍然有效 says what they said since changes nothing, 撤回 takes it back
 * so no twin quotes it any more.
 */
export function MyAnswers() {
  const personaId = usePersonaId();
  const confirm = useConfirm();
  const [answers, setAnswers] = useState<MyTeamAnswer[] | null>(null);
  const [error, setError] = useState('');
  const [revising, setRevising] = useState<MyTeamAnswer | null>(null);
  const load = useCallback(async () => {
    try {
      const found = await api<{ team_answers: MyTeamAnswer[] }>(
        '/api/persona/team-answers',
      );
      setAnswers(found.team_answers);
      setError('');
    } catch (failure) {
      setError(message(failure, '加载失败'));
    }
    window.dispatchEvent(new Event(AWAY_CHANGED));
  }, []);
  useEffect(() => {
    void load();
  }, [load, personaId]);
  const act = async (answer: MyTeamAnswer, action: string, done: string) => {
    try {
      await api(
        `/api/persona/team-answers/${encodeURIComponent(answer.id)}/${action}`,
        { method: 'POST', json: {} },
      );
      toast(done, 'success');
      await load();
    } catch (failure) {
      toast(message(failure, '操作失败'), 'danger');
    }
  };
  if (error) return <Notice tone="danger">{error}</Notice>;
  if (!answers) return <Skeleton className="h-24" />;
  if (!answers.length)
    return (
      <EmptyState title="还没有团队答案">
        几个人问同一件事时，回复可同时设为团队答案；常被问到的回复也能设。
      </EmptyState>
    );
  return (
    <>
      <Stack as="ul" gap={0}>
        {answers.map((answer) => (
          <ListRow
            key={answer.id}
            variant="divided"
            title={<Text truncate>{answer.title}</Text>}
            meta={
              <>
                {dayOf(answer.confirmed_at)}确认
                {answer.status === 'stale' && (
                  <>
                    {' '}
                    <Badge tone="warning">可能过期</Badge>
                  </>
                )}
              </>
            }
            trailing={
              <>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setRevising(answer)}
                >
                  更新
                </Button>
                <ActionMenu
                  label={`更多：${answer.title}`}
                  items={[
                    ...(answer.status === 'stale'
                      ? [
                          {
                            label: '仍然有效',
                            onSelect: () =>
                              void act(answer, 'keep', '已确认仍然有效'),
                          },
                        ]
                      : []),
                    {
                      label: '撤回',
                      onSelect: () =>
                        void confirm({
                          title: '撤回这条团队答案？',
                          body: '之后同事的分身不再引用它，已经发出去的对话不变。',
                          confirmLabel: '撤回',
                          tone: 'danger',
                        }).then((ok) => {
                          if (ok) void act(answer, 'withdraw', '已撤回');
                        }),
                    },
                  ]}
                />
              </>
            }
          >
            <Text size="sm" tone="secondary" twoLines>
              {answer.body}
            </Text>
            {answer.status === 'stale' && answer.stale_note && (
              <Text size="xs" tone="secondary">
                {answer.stale_note}
              </Text>
            )}
          </ListRow>
        ))}
      </Stack>
      {revising && (
        <Revise
          answer={revising}
          onClose={() => setRevising(null)}
          onSaved={load}
        />
      )}
    </>
  );
}
