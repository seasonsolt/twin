import { useState } from 'react';
import { CircleHelp, Pencil } from 'lucide-react';
import { api } from '../../lib/api';
import {
  Button,
  Card,
  Checkbox,
  Disclosure,
  IconButton,
  Input,
  ListRow,
  Row,
  Stack,
  Text,
  Textarea,
  Tooltip,
  toast,
} from '../../components/ui';
import { TeamAnswerCard } from '../answers/TeamAnswerCard';
import { ReplyTierChoice, type ReplyTier } from './ReplyTier';
import { useStatus } from '../../stores/status';
import type { Handoff } from './useAway';
import { useReplyDraft } from './useReplyDraft';
import { Initial, clock } from './Waiting';

/** What the twin did with the question, in a word. */
const twinSaid = (item: Handoff) =>
  item.twin_mode === undefined || item.twin_mode === null
    ? ''
    : item.twin_mode === 'abstain'
      ? '未答'
      : '答了一半';

/**
 * Several people asked the same thing: one card with the question summed up, what each of them asked and what the twin
 * did, and one box to answer them all. The reply goes into each asker's own conversation, as the person's; each
 * question stays its own handoff. 同时设为团队答案 also makes the reply the team's, under the title above. 拆开分别回
 * hands them back as separate rows when they were not one matter after all.
 */
export function Merged({
  items,
  onSplit,
  onDone,
}: {
  items: Handoff[];
  onSplit: () => void;
  onDone: () => Promise<void>;
}) {
  const me = useStatus((state) => state.data?.target_name) ?? '我';
  const [title, setTitle] = useState(items[0].question.slice(0, 80));
  const [renaming, setRenaming] = useState(false);
  const [team, setTeam] = useState(false);
  const [tier, setTier] = useState<ReplyTier>('colleague');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const { text, edit, clear, drafting, draft, replaced, restore } =
    useReplyDraft(
      `/api/persona/handoffs/${encodeURIComponent(items[0].id)}/draft`,
      setError,
    );
  const earliest = items.reduce(
    (first, item) => (item.created_at < first ? item.created_at : first),
    items[0].created_at,
  );
  const send = async () => {
    setBusy(true);
    setError('');
    try {
      const sent = await api<{
        done: string[];
        failed: { id: string; detail: string }[];
        team_answer_error?: string | null;
      }>('/api/persona/handoffs/reply-many', {
        method: 'POST',
        json: {
          ids: items.map((item) => item.id),
          text: text.trim(),
          // A team answer is for everyone: it is also a memory they may use.
          tier: team ? 'colleague' : tier,
          ...(team
            ? { team_answer: { title: title.trim(), body: text.trim() } }
            : {}),
        },
      });
      // The replies and the team answer are told apart: one can fail without the other.
      const gaps = [
        sent.failed.length ? `${sent.failed.length} 人没发出去` : '',
        team && sent.team_answer_error
          ? `团队答案没设成：${sent.team_answer_error}`
          : '',
      ].filter(Boolean);
      toast(
        gaps.length
          ? `已回复 ${sent.done.length} 人，${gaps.join('，')}`
          : team
            ? `已回复 ${sent.done.length} 人，并设为团队答案`
            : `已回复 ${sent.done.length} 人`,
        gaps.length ? 'warning' : 'success',
      );
      clear();
      await onDone();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '发送失败');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card as="article" variant="outline" aria-label="同一件事">
      <Stack gap={3}>
        <Row gap={3} wrap>
          <Text weight="bold">{items.length} 人问同一件事</Text>
          <Text size="xs" tone="secondary">
            最早 {clock(earliest)}
          </Text>
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            disabled={busy}
            onClick={onSplit}
          >
            拆开分别回
          </Button>
        </Row>
        <Row gap={2}>
          {renaming ? (
            <Input
              aria-label="归纳的问法"
              value={title}
              maxLength={80}
              autoFocus
              onChange={(event) => setTitle(event.target.value)}
              onBlur={() => setRenaming(false)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') setRenaming(false);
              }}
            />
          ) : (
            <>
              <Text size="lg" weight="bold">
                {title}
              </Text>
              <IconButton label="改问法" onClick={() => setRenaming(true)}>
                <Pencil size={16} aria-hidden />
              </IconButton>
            </>
          )}
        </Row>
        <Stack as="ul" gap={0}>
          {items.map((item) => (
            <ListRow
              key={item.id}
              variant="plain"
              leading={<Initial name={item.asker_name} />}
              title={
                <Text size="sm" truncate>
                  {item.asker_name || '来源不明'}：“{item.question}”
                </Text>
              }
              meta={[clock(item.created_at), twinSaid(item)]
                .filter(Boolean)
                .join(' · ')}
            />
          ))}
        </Stack>
        <label htmlFor={`merged-${items[0].id}`} className="sr-only">
          以本人回复 {items.length} 人
        </label>
        <Textarea
          id={`merged-${items[0].id}`}
          value={text}
          placeholder={`以本人回复 ${items.length} 人，各发到各自的对话`}
          onChange={(event) => edit(event.target.value)}
        />
        <Row gap={3} wrap>
          <ReplyTierChoice
            value={team ? 'colleague' : tier}
            onChange={setTier}
            disabled={busy || team}
          />
          <Checkbox
            label="同时设为团队答案"
            checked={team}
            disabled={busy}
            onChange={(event) => setTeam(event.target.checked)}
          >
            <Tooltip label="全队的分身和助手原样引用，署你的名">
              <IconButton label="团队答案是什么" shape="circle">
                <CircleHelp className="size-4" aria-hidden />
              </IconButton>
            </Tooltip>
          </Checkbox>
        </Row>
        {team && text.trim() && (
          <Disclosure summary="预览" variant="plain">
            <TeamAnswerCard
              card={{
                id: 'preview',
                persona_id: '',
                owner_name: me,
                title: title.trim() || items[0].question,
                body: text.trim(),
                confirmed_at: new Date().toISOString(),
                status: 'valid',
                stale_note: '',
                partial: false,
              }}
            />
          </Disclosure>
        )}
        {error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
        <Row gap={2} justify="end">
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
            <Button size="sm" variant="ghost" disabled={busy} onClick={restore}>
              换回我写的
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            loading={busy}
            disabled={!text.trim() || (team && !title.trim())}
            onClick={() => void send()}
          >
            回复 {items.length} 人
          </Button>
        </Row>
      </Stack>
    </Card>
  );
}
