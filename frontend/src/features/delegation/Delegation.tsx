import { useCallback, useEffect, useState } from 'react';
import { CircleHelp } from 'lucide-react';
import { useNavigate } from 'react-router';
import { api } from '../../lib/api';
import {
  ActionMenu,
  AvatarFrame,
  Badge,
  Button,
  Card,
  IconButton,
  Row,
  Skeleton,
  Stack,
  Text,
  TextLink,
  Tooltip,
  toast,
} from '../../components/ui';
import { TeamAnswerCard } from '../answers/TeamAnswerCard';
import type { DelegationNote, DelegationTarget, DelegationView } from './types';

const message = (failure: unknown, fallback: string) =>
  failure instanceof Error ? failure.message : fallback;

/** The word beside a twin's name for where its answer stands. */
function standing(target: DelegationTarget): {
  label: string;
  tone: 'success' | 'warning' | 'info' | 'neutral';
} {
  switch (target.state) {
    case 'needs_owner':
      return { label: `要${target.name}本人定`, tone: 'warning' };
    case 'skipped':
      return { label: `要${target.name}本人定`, tone: 'neutral' };
    case 'handed':
      return { label: '等本人回复', tone: 'info' };
    case 'replied':
      return { label: '本人已回', tone: 'success' };
    default:
      return {
        label: target.mode === 'abstain' ? '没答上' : '答了',
        tone: 'success',
      };
  }
}

/** One twin's answer to the question the person's assistant put to it, with what can be done about it. */
function Answer({
  target,
  busy,
  onForward,
  onSkip,
  onAlso,
}: {
  target: DelegationTarget;
  busy: boolean;
  onForward(): void;
  onSkip(): void;
  onAlso(persona: string): void;
}) {
  const { label, tone } = standing(target);
  const navigate = useNavigate();
  const whole = `/chat?with=${encodeURIComponent(target.persona_id)}&open=${encodeURIComponent(target.conversation_id)}`;
  return (
    <Card
      as="article"
      variant="outline"
      padding="md"
      aria-label={`${target.name}的分身的回答`}
    >
      <Stack gap={2}>
        <Row gap={2} wrap>
          <AvatarFrame size="sm">{target.name.slice(0, 1)}</AvatarFrame>
          <Text weight="bold">{target.name}的分身</Text>
          <Badge tone={tone}>{label}</Badge>
          <ActionMenu
            label={`更多：${target.name}的分身的回答`}
            items={[
              {
                label: '看完整问答',
                onSelect: () => void navigate(whole),
              },
            ]}
          />
        </Row>
        {target.team_answer && <TeamAnswerCard card={target.team_answer} />}
        <Text>{target.answer}</Text>
        <TextLink to={whole} size="sm">
          依据 ›
        </TextLink>
        {target.state === 'replied' && target.owner_reply && (
          <Card
            variant="soft"
            padding="sm"
            as="div"
            aria-label={`${target.name}本人`}
          >
            <Stack gap={1}>
              <Badge tone="info">{target.name}本人</Badge>
              <Text size="sm">{target.owner_reply}</Text>
            </Stack>
          </Card>
        )}
        {target.state === 'handed' && target.handoff && (
          <Text role="status" size="xs" tone="secondary">
            已转给{target.name}本人 · {target.handoff.status_label}
          </Text>
        )}
        {target.state === 'needs_owner' && (
          <Row gap={2} wrap>
            <Text size="sm" tone="secondary">
              转给{target.name}本人吗？
            </Text>
            <Button size="sm" disabled={busy} onClick={onForward}>
              转给本人
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={onSkip}>
              先不用
            </Button>
          </Row>
        )}
        {target.also.map((other) => (
          <Row key={other.persona_id} gap={2} wrap>
            <Text size="sm" tone="secondary">
              答案提到了{other.name}
            </Text>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => onAlso(other.persona_id)}
            >
              也问问{other.name}的分身
            </Button>
          </Row>
        ))}
      </Stack>
    </Card>
  );
}

/**
 * What the person's assistant asked colleagues' twins in their name, read from the team as it stands now: a card for
 * each twin with its answer and where it stands, then the assistant's own note on all of them, kept apart and marked as
 * not theirs. A twin that could not settle something does not bother its person until the asker presses 转给本人; an
 * answer that names someone else offers to ask them too. Only one hop: nothing here asks beyond the person.
 */
export function Delegation({ note }: { note: DelegationNote }) {
  const [view, setView] = useState<DelegationView | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      setView(
        await api<DelegationView>(
          `/api/persona/delegations/${encodeURIComponent(note.id)}`,
        ),
      );
      setError('');
    } catch (failure) {
      setError(message(failure, '没能读到回答'));
    }
  }, [note.id]);
  useEffect(() => {
    void load();
  }, [load]);
  const act = async (path: string, json: object, done?: string) => {
    setBusy(true);
    try {
      setView(
        await api<DelegationView>(
          `/api/persona/delegations/${encodeURIComponent(note.id)}/${path}`,
          { method: 'POST', json },
        ),
      );
      if (done) toast(done, 'success');
    } catch (failure) {
      toast(message(failure, '没成功'), 'danger');
    } finally {
      setBusy(false);
    }
  };
  if (error)
    return (
      <Text role="alert" size="sm" tone="danger">
        {error}
      </Text>
    );
  if (!view) return <Skeleton className="h-24" />;
  return (
    <Stack gap={3}>
      {view.targets.map((target) => (
        <Answer
          key={target.conversation_id}
          target={target}
          busy={busy}
          onForward={() =>
            void act(
              'forward',
              { conversation_id: target.conversation_id },
              `已转给${target.name}本人`,
            )
          }
          onSkip={() =>
            void act('skip', { conversation_id: target.conversation_id })
          }
          onAlso={(persona) => void act('ask', { persona_id: persona })}
        />
      ))}
      {note.summary && (
        <Card variant="soft" padding="md" as="div" aria-label="我的归纳">
          <Stack gap={1}>
            <Text size="xs" tone="secondary">
              我的归纳 · 非原话
            </Text>
            <Text>{note.summary}</Text>
          </Stack>
        </Card>
      )}
      <Row gap={1}>
        <Text size="xs" tone="secondary">
          只走一跳
        </Text>
        <Tooltip label="同事的分身不会再去问别人，要不要再问由你定">
          <IconButton
            label="说明：同事的分身不会再去问别人，要不要再问由你定"
            shape="circle"
          >
            <CircleHelp className="size-4" aria-hidden />
          </IconButton>
        </Tooltip>
      </Row>
    </Stack>
  );
}
