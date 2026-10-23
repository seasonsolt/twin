import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { CircleHelp } from 'lucide-react';
import {
  ActionMenu,
  AvatarFrame,
  Badge,
  Button,
  Card,
  ClipButton,
  EmptyState,
  Heading,
  IconButton,
  Row,
  Stack,
  Text,
  TextLink,
  Tooltip,
  type ClipControls,
} from '../../components/ui';
import type { Person } from '../../pages/Recording';
import { useHeard } from '../../stores/listening';
import { recordingPath } from '../library/review';
import { PersonClip } from '../library/PersonClip';
import { NameField, clipSrc, heardIn, voiceFacts } from './VoiceRows';
import { answerFor, type Answer, type VoiceItem } from './voice';

const KEYS = '空格 播放 · ← → 换一段 · 1 2 选人 · S 跳过 · N 输入名字 · U 撤销';

/** Text being typed into, where keys are letters and not shortcuts. */
const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));

/**
 * New voices one at a time: hear it, hear who it may be, answer. Everything is on the keyboard: space plays,
 * ← → hear another recording of the voice, 1 2 pick one of the names offered, S leaves it for later, N types a name,
 * U takes back the last answer. What was answered is gone from here at once and told to the server a few seconds
 * later (``useDeferred``).
 */
export function InboxFocus({
  items,
  people,
  last,
  onAnswer,
  onUndo,
  onList,
}: {
  /** The voices still to settle, in the order the list has them. */
  items: VoiceItem[];
  /** Everyone in the team, to offer and to hear. */
  people: Person[];
  /** The latest answer still to be taken back. */
  last?: { id: string; label: string };
  onAnswer: (item: VoiceItem, answer: Answer) => void;
  onUndo: (id: string) => void;
  onList: () => void;
}) {
  const [skipped, setSkipped] = useState<string[]>([]);
  const queue = useMemo(
    () => [
      ...items.filter((item) => !skipped.includes(item.id)),
      ...skipped.flatMap((id) => items.filter((item) => item.id === id)),
    ],
    [items, skipped],
  );
  const item = queue[0];
  const next = queue[1];
  const [heard, setHeard] = useState(0);
  const clip = useRef<ClipControls>(null);
  const field = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const hear = useHeard();
  const known = useMemo(() => people.filter((p) => !p.auto), [people]);
  const { facts, title } = voiceFacts(item ?? EMPTY);
  const members = item ? heardIn(item) : [];
  const current = members.length ? members[heard % members.length] : undefined;
  const options = facts?.options ?? [];
  useEffect(() => setHeard(0), [item?.id]);

  // The latest values for the key handler, which is bound once.
  const live = useRef({ item, options, known, members, last });
  useEffect(() => {
    live.current = { item, options, known, members, last };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const { item, options, known, members, last } = live.current;
      if (typing(event.target)) {
        if (event.key === 'Escape' && event.target instanceof HTMLElement)
          event.target.blur();
        return;
      }
      const target = event.target instanceof HTMLElement ? event.target : null;
      // A button or link has these keys itself.
      const native = !!target?.closest('button, a, summary, [role="radio"]');
      const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
      const handled = () => event.preventDefault();
      if (key === 'u' && last) {
        handled();
        onUndo(last.id);
      } else if (!item) {
        return;
      } else if (key === ' ' && !native) {
        handled();
        clip.current?.toggle();
      } else if (
        (key === 'ArrowRight' || key === 'ArrowLeft') &&
        !target?.closest('[role="radio"]')
      ) {
        if (members.length > 1) {
          handled();
          setHeard((n) => n + (key === 'ArrowRight' ? 1 : -1 + members.length));
        }
      } else if (/^[1-9]$/u.test(key)) {
        const option = options[Number(key) - 1];
        if (option) {
          handled();
          onAnswer(item, answerFor('', known, option));
        }
      } else if (key === 's') {
        handled();
        setSkipped((list) => [...list.filter((id) => id !== item.id), item.id]);
      } else if (key === 'n' || key === '/') {
        handled();
        field.current?.focus();
      } else if (key === 'Enter' && !native) {
        const sure = options.find((option) => option.sure);
        if (sure) {
          handled();
          onAnswer(item, answerFor('', known, sure));
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onAnswer, onUndo]);

  const undoLine = last && (
    <Text size="sm" tone="secondary" truncate>
      <Text as="span" role="status" size="sm" tone="inherit">
        {last.label}
      </Text>
      {' · '}
      <TextLink size="sm" onClick={() => onUndo(last.id)}>
        撤销
      </TextLink>
    </Text>
  );
  if (!item)
    return (
      <EmptyState title="新的声音都处理完了">
        {undoLine}
        <TextLink onClick={onList}>回到列表</TextLink>
      </EmptyState>
    );
  const compared = options.map((option) => ({
    option,
    person: option.added ? undefined : people.find((p) => p.id === option.id),
  }));
  const nextTitle = next ? nextName(next) : '';
  return (
    <Stack gap={5} aria-label="逐个听">
      <Heading level={2} size="title">
        这是谁？
      </Heading>
      <Card as="section" aria-label="这个声音">
        <Row gap={4} wrap>
          {current && (
            <ClipButton
              key={`${item.id}/${current.recording_id}/${current.speaker_id}`}
              controls={clip}
              size="lg"
              label="播放这个声音"
              src={hear(clipSrc(current))}
            />
          )}
          <Stack gap={1} grow>
            <Text weight="semibold">{title}</Text>
            {facts?.quote && (
              <Text size="sm" tone="secondary">
                「{facts.quote}」
              </Text>
            )}
            <Row gap={3} wrap>
              {members.length > 1 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`换一段录音听（现在是第 ${(heard % members.length) + 1} 段，共 ${members.length} 段）`}
                  onClick={() => setHeard((n) => n + 1)}
                >
                  换一段 {(heard % members.length) + 1}/{members.length}
                </Button>
              )}
              {current?.filename && (
                <Text size="sm" tone="tertiary">
                  {current.filename}
                </Text>
              )}
            </Row>
          </Stack>
        </Row>
      </Card>
      {compared.length > 0 && (
        <Stack as="section" gap={3} aria-label="对比听">
          {compared.map(({ option, person }, index) => (
            <Card key={option.id} as="div" variant="soft" padding="md">
              <Row gap={3} wrap justify="between">
                <Row gap={3}>
                  <AvatarFrame>{Array.from(option.name)[0]}</AvatarFrame>
                  <Stack gap={0}>
                    <Text weight="semibold">{option.name}</Text>
                    <Row gap={2}>
                      {person && (
                        <Text size="sm" tone="secondary">
                          {person.speakers} 段录音
                        </Text>
                      )}
                      {facts?.split && !option.added && index === 0 && (
                        <Badge
                          tone="warning"
                          title="这几段录音里已经有这个人，可能是同一个人被分成了两位"
                        >
                          可能被拆开
                        </Badge>
                      )}
                    </Row>
                  </Stack>
                  <PersonClip person={person} icon />
                </Row>
                <Button
                  variant={option.sure ? 'primary' : 'secondary'}
                  onClick={() => onAnswer(item, answerFor('', known, option))}
                >
                  {option.added ? `新建${option.name}` : `是${option.name}`}
                </Button>
              </Row>
            </Card>
          ))}
        </Stack>
      )}
      <Row gap={3} wrap>
        <Stack gap={0} grow>
          <NameField
            key={item.id}
            label="都不是，输入名字"
            placeholder="都不是？输入名字"
            known={known}
            inputRef={field}
            onName={(name) => onAnswer(item, answerFor(name, known))}
          />
        </Stack>
        <Button
          variant="ghost"
          onClick={() =>
            setSkipped((list) => [
              ...list.filter((id) => id !== item.id),
              item.id,
            ])
          }
        >
          跳过
        </Button>
        <ActionMenu
          label="更多：打开录音、不在团队里、几个人混在一起"
          items={[
            ...(current
              ? [
                  {
                    label: '打开录音',
                    onSelect: () =>
                      void navigate(
                        recordingPath(current.recording_id, current.speaker_id),
                        {
                          state: {
                            inboxTask: item.id,
                            voiceRecordings: item.recordings,
                          },
                        },
                      ),
                  },
                ]
              : []),
            {
              label: '不在团队里',
              onSelect: () => onAnswer(item, { to: 'nobody' }),
            },
            ...(item.kind === 'voice'
              ? [
                  {
                    label: '几个人混在一起',
                    onSelect: () => onAnswer(item, { to: 'mixed' }),
                  },
                ]
              : []),
          ]}
        />
      </Row>
      <Row gap={3} justify="between">
        {undoLine ?? (
          <Text size="sm" tone="secondary" truncate>
            {nextTitle ? `下一个：${nextTitle}` : ''}
          </Text>
        )}
        <Tooltip label={KEYS}>
          <IconButton label="快捷键" shape="circle" size="md" variant="ghost">
            <CircleHelp aria-hidden className="size-4" />
          </IconButton>
        </Tooltip>
      </Row>
    </Stack>
  );
}

const EMPTY = {
  kind: 'voice',
  id: '',
  seconds: 0,
  recordings: 0,
  enough: false,
  stranger: false,
  voice: { id: '', members: [], seconds: 0, candidates: [], near: false },
} as const satisfies VoiceItem;

/** What the next voice is called, for the line under the current one. */
function nextName(item: VoiceItem) {
  if (item.kind === 'person') return item.person.name;
  return item.voice.called
    ? `会上被叫作${item.voice.called}`
    : (item.voice.candidates[0] && `像${item.voice.candidates[0].name}`) ||
        '没听过的声音';
}
