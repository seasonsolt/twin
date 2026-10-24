import { useState, type Ref } from 'react';
import { useNavigate, type NavigateFunction } from 'react-router';
import {
  ActionMenu,
  Badge,
  Button,
  ClipButton,
  Input,
  Row,
  StatusDot,
  TaskRow,
  Text,
} from '../../components/ui';
import { withBase } from '../../lib/base';
import { byName } from '../../lib/names';
import { useHeard } from '../../stores/listening';
import type { Person } from '../../pages/Recording';
import { recordingPath, span } from '../library/review';
import {
  answerFor,
  describeVoice,
  type Answer,
  type Option,
  type VoiceItem,
} from './voice';

/** The element a row of the list is, so the page can put the keyboard in the next one. */
export const rowId = (task: string) => `inbox-${task}`;

/** One recording a voice was heard in, where to hear it and open it. */
export interface Heard {
  recording_id: string;
  speaker_id: string;
  filename: string;
}

export const heardIn = (item: VoiceItem): Heard[] =>
  item.kind === 'voice'
    ? item.voice.members
    : item.person.recording_id && item.person.speaker_id
      ? [
          {
            recording_id: item.person.recording_id,
            speaker_id: item.person.speaker_id,
            filename: '',
          },
        ]
      : [];

export const clipSrc = (heard: Heard) =>
  withBase(
    `/api/library/recordings/${encodeURIComponent(heard.recording_id)}/speakers/${encodeURIComponent(heard.speaker_id)}/samples/0`,
  );

/** What a voice is called in the list and the one line under it. */
export function voiceFacts(item: VoiceItem) {
  const facts = item.kind === 'voice' ? describeVoice(item.voice) : undefined;
  const title =
    facts?.title ?? (item.kind === 'person' ? item.person.name : '');
  const meta = [
    `${item.recordings} 段 · ${span(item.seconds)}`,
    facts?.quote && `「${facts.quote}」`,
  ]
    .filter(Boolean)
    .join(' · ');
  return { facts, title, meta };
}

/** The menu entry that opens the recording being heard, which settles that one alone: it says which of the voice's
 * recordings it is, and the recording says how many more wait. `back` is what the page remembers to come back to. */
export function openRecording(
  item: VoiceItem,
  members: Heard[],
  heard: number,
  navigate: NavigateFunction,
  back: Record<string, unknown> = {},
) {
  const current = members[heard % members.length];
  return {
    label:
      members.length > 1
        ? `打开第 ${(heard % members.length) + 1} 段`
        : '打开录音',
    onSelect: () =>
      void navigate(recordingPath(current.recording_id, current.speaker_id), {
        state: {
          inboxTask: item.id,
          // Only a voice heard in several recordings is settled across them; a person is one speaker's.
          voiceRecordings: item.kind === 'voice' ? item.recordings : undefined,
          ...back,
        },
      }),
  };
}

/** A name to type for a voice that is none of the answers offered; Enter answers. */
export function NameField({
  label,
  known,
  autoFocus,
  placeholder = '输入名字',
  inputRef,
  onName,
}: {
  label: string;
  known: Person[];
  autoFocus?: boolean;
  placeholder?: string;
  inputRef?: Ref<HTMLInputElement>;
  onName: (name: string) => void;
}) {
  const [name, setName] = useState('');
  return (
    <Row
      as="form"
      gap={2}
      grow
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim()) onName(name);
      }}
    >
      <Input
        ref={inputRef}
        aria-label={label}
        placeholder={placeholder}
        maxLength={40}
        value={name}
        autoFocus={autoFocus}
        suggestions={known.map((p) => p.name).sort(byName)}
        className="min-w-0 flex-1"
        onChange={(event) => setName(event.target.value)}
      />
      {name.trim() && <Button type="submit">确认</Button>}
    </Row>
  );
}

/** A new voice in the list: hear it, then answer with one of the names it may be, or type one; the rest is in “⋯”. */
export function VoiceRow({
  item,
  known,
  onAnswer,
}: {
  item: VoiceItem;
  known: Person[];
  onAnswer: (item: VoiceItem, answer: Answer) => void;
}) {
  const navigate = useNavigate();
  const hear = useHeard();
  const { facts, title, meta } = voiceFacts(item);
  const members = heardIn(item);
  const [heard, setHeard] = useState(0);
  const [asking, setAsking] = useState(false);
  const options: Option[] = facts?.options ?? [];
  const current = members.length ? members[heard % members.length] : undefined;
  const typing = options.length === 0 || asking;
  // Rows often share a title: the time they speak tells them apart to a screen reader.
  const named = `${title}（${span(item.seconds)}）`;
  return (
    <TaskRow
      id={rowId(item.id)}
      leading={
        current && (
          <ClipButton
            size="md"
            key={`${current.recording_id}/${current.speaker_id}`}
            label={`听这个声音${current.filename ? `（${current.filename}）` : ''}`}
            src={hear(clipSrc(current))}
          />
        )
      }
      title={
        <Row gap={2}>
          <Text as="span" weight="semibold" truncate>
            {title}
          </Text>
          {facts?.split && (
            <Badge
              tone="warning"
              title="这几段录音里已经有这个人，可能是同一个人被分成了两位"
            >
              可能被拆开
            </Badge>
          )}
        </Row>
      }
      meta={meta}
      actionsWidth={typing ? 'field' : 'auto'}
      actions={
        <>
          <Row gap={2} wrap grow role="group" aria-label="这是谁">
            {options.map((option) => (
              <Button
                key={option.id}
                // Once 其他人 is chosen, the name typed is the row's answer.
                variant={option.sure && !asking ? 'primary' : 'secondary'}
                aria-label={
                  option.added
                    ? `新建成员：${option.name}`
                    : `归给${option.name}`
                }
                onClick={() => onAnswer(item, answerFor('', known, option))}
              >
                {option.added ? `+ ${option.name}` : option.name}
              </Button>
            ))}
            {typing && (
              <NameField
                label={`${named}，是谁`}
                known={known}
                autoFocus={asking}
                onName={(name) => onAnswer(item, answerFor(name, known))}
              />
            )}
          </Row>
          <ActionMenu
            label={`更多：${named}`}
            items={[
              ...(!typing
                ? [{ label: '其他人', onSelect: () => setAsking(true) }]
                : []),
              ...(members.length > 1
                ? [
                    {
                      label: `换一段（${(heard % members.length) + 1}/${members.length}）`,
                      onSelect: () => setHeard((n) => n + 1),
                    },
                  ]
                : []),
              ...(current
                ? [openRecording(item, members, heard, navigate)]
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
        </>
      }
    />
  );
}

/** What stands where a settled row was, until the server is told: what was done, and a way to take it back. */
export function SettledRow({
  id,
  label,
  meta,
  onUndo,
}: {
  id: string;
  label: string;
  meta?: string;
  onUndo: () => void;
}) {
  return (
    <TaskRow
      id={rowId(id)}
      leading={<StatusDot tone="success" />}
      title={
        <Text as="span" role="status" weight="medium">
          {label}
        </Text>
      }
      meta={meta}
      actions={
        <Button variant="ghost" aria-label={`撤销：${label}`} onClick={onUndo}>
          撤销
        </Button>
      }
    />
  );
}
