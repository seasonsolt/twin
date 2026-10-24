import {
  Button,
  RouteButton,
  Row,
  Stack,
  StatusDot,
  TaskRow,
} from '../../components/ui';
import type { Recording } from '../../pages/Library';
import type { Person } from '../../pages/Recording';
import type { Persona } from '../../stores/personas';
import type { SuspectSpeaker } from '../library/MixedSpeaker';
import {
  recordingPath,
  span,
  type Fragment,
  type Waiting,
} from '../library/review';
import type { Unsorted } from '../library/review';
import { rowId } from './VoiceRows';

/** What a kind of thing in the inbox shows besides new voices: one row each, the one thing to do with it on the
 * row. ``attention`` marks how urgent it is by colour alone. */
const mark = (tone: 'warning' | 'danger' | 'info') => <StatusDot tone={tone} />;

/** Confirmed speakers some of whose speech sounds like someone else, to hear again and give to whoever speaks. */
export function MixedList({
  suspects,
  busy,
  onReview,
}: {
  suspects: SuspectSpeaker[];
  busy: boolean;
  onReview: (suspect: SuspectSpeaker) => void;
}) {
  return (
    <Stack as="ul" gap={0} aria-label="有空再看">
      {suspects.map((m) => (
        <TaskRow
          key={`mixed-${m.recording_id}-${m.speaker_id}`}
          leading={mark('info')}
          title={`${m.name} · ${m.filename}`}
          meta={`${Math.round(m.share * 100)}% 不像 · ${span(m.open_seconds)}`}
          actions={
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() => onReview(m)}
            >
              去听
            </Button>
          }
        />
      ))}
    </Stack>
  );
}

/** Recordings whose speakers have no voiceprint to group by: settled in the recording itself. A transcript brought in
 * as text has no sound to hear: it is read and confirmed. */
export function UnsortedList({
  items,
  recordings,
}: {
  items: Unsorted[];
  recordings: Pick<Recording, 'id' | 'kind'>[];
}) {
  const silent = new Set(
    recordings.filter((r) => r.kind === 'transcript').map((r) => r.id),
  );
  return (
    <Stack as="ul" gap={0} aria-label="还没认人">
      {items.map((u) => (
        <TaskRow
          key={`unsorted-${u.recording_id}`}
          id={rowId(`unsorted-${u.recording_id}`)}
          leading={mark('warning')}
          title={u.filename}
          meta={
            u.speakers === u.total
              ? `${u.speakers} 位说话人待确认`
              : `还有 ${u.speakers} 位没认`
          }
          actions={
            <RouteButton
              to={recordingPath(u.recording_id)}
              state={{ inboxTask: `unsorted-${u.recording_id}` }}
              variant="secondary"
              size="sm"
            >
              {silent.has(u.recording_id) ? '确认' : '试听并确认'}
            </RouteButton>
          }
        />
      ))}
    </Stack>
  );
}

/** Recordings that did not transcribe: try again, or delete. */
export function FailedList({
  recordings,
  busy,
  onRetry,
  onRemove,
}: {
  recordings: Recording[];
  busy: boolean;
  onRetry: (recording: Recording) => void;
  onRemove: (recording: Recording) => void;
}) {
  return (
    <Stack as="ul" gap={0} aria-label="转写失败">
      {recordings.map((r) => (
        <TaskRow
          key={r.id}
          leading={mark('danger')}
          title={r.filename}
          meta={r.error || undefined}
          actions={
            <>
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={() => onRetry(r)}
              >
                重试
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => onRemove(r)}
              >
                删除
              </Button>
            </>
          }
        />
      ))}
    </Stack>
  );
}

/** Pairs of people the merge of two libraries could not tell apart. */
export function SimilarList({
  pairs,
  onMerge,
  onApart,
}: {
  pairs: (readonly [Person, Person])[];
  onMerge: (one: Person, other: Person) => void;
  onApart: (one: Person, other: Person) => void;
}) {
  return (
    <Stack as="ul" gap={0} aria-label="可能是同一个人">
      {pairs.map(([a, b]) => (
        <TaskRow
          key={`similar-${a.id}-${b.id}`}
          id={rowId(`similar-${a.id}-${b.id}`)}
          leading={mark('info')}
          title={`${a.name} 和 ${b.name}`}
          meta={`${a.speakers} 段录音 · ${b.speakers} 段录音`}
          actions={
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onMerge(a, b)}
              >
                合并
              </Button>
              <Button variant="ghost" size="sm" onClick={() => onApart(a, b)}>
                不是同一个人
              </Button>
            </>
          }
        />
      ))}
    </Stack>
  );
}

/** Speakers someone said were not them: hear them again and give them to the right person. */
export function DisputedList({ items }: { items: Waiting[] }) {
  return (
    <Stack as="ul" gap={0} aria-label="有人说不是自己">
      {items.map((w) => (
        <TaskRow
          key={`${w.recording_id}-${w.id}`}
          id={rowId(`speaker-${w.recording_id}-${w.id}`)}
          leading={mark('warning')}
          title={`${w.filename} · ${w.id}`}
          meta={span(w.seconds)}
          actions={
            <RouteButton
              to={recordingPath(w.recording_id, w.id)}
              state={{ inboxTask: `speaker-${w.recording_id}-${w.id}` }}
              variant="secondary"
              size="sm"
            >
              试听并确认
            </RouteButton>
          }
        />
      ))}
    </Stack>
  );
}

/** Twins a colleague sent back as not theirs: point them at the right person again. */
export function DisownedList({
  people,
  twinOf,
  busy,
  onAddress,
}: {
  people: Person[];
  twinOf: (person: Person) => Persona | undefined;
  busy: boolean;
  onAddress: (person: Person) => void;
}) {
  return (
    <Stack as="ul" gap={0} aria-label="分身被退回">
      {people.map((p) => (
        <TaskRow
          key={`disowned-${p.id}`}
          leading={mark('danger')}
          title={p.name}
          meta={`${twinOf(p)?.claim_rejected} 说这不是 TA`}
          actions={
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() => onAddress(p)}
            >
              换个邮箱或工号
            </Button>
          }
        />
      ))}
    </Stack>
  );
}

/** Very short voices, mostly interjections: given in one click to whoever they sound like, or put aside. */
export function FragmentsRow({
  fragments,
  onGive,
  onAside,
}: {
  fragments: Fragment[];
  onGive: (
    person: { person_id: string; name: string },
    members: Fragment[],
  ) => void;
  onAside: () => void;
}) {
  const recordings = new Set(fragments.map((m) => m.recording_id)).size;
  // Fragments by the person they sound like, most first: given to them in one click, without becoming voice samples.
  const like = [
    ...fragments
      .reduce((found, m) => {
        if (m.like) {
          const group = found.get(m.like.person_id) ?? {
            person: m.like,
            members: [] as Fragment[],
          };
          group.members.push(m);
          found.set(m.like.person_id, group);
        }
        return found;
      }, new Map<string, { person: { person_id: string; name: string }; members: Fragment[] }>())
      .values(),
  ].sort((a, b) => b.members.length - a.members.length);
  return (
    <Stack as="ul" gap={0} aria-label="零碎片段">
      <TaskRow
        id={rowId('fragments')}
        leading={mark('info')}
        title={`${recordings} 段录音里有 ${fragments.length} 段很短的声音`}
        meta={`共 ${span(fragments.reduce((total, m) => total + m.seconds, 0))}${like.length === 0 ? '，不像任何人' : ''}`}
        actions={
          <Row gap={2} wrap justify="end">
            {like.slice(0, 3).map(({ person, members }) => (
              <Button
                key={person.person_id}
                variant="secondary"
                size="sm"
                onClick={() => onGive(person, members)}
              >
                归给{person.name}（{members.length}）
              </Button>
            ))}
            <Button variant="secondary" size="sm" onClick={onAside}>
              都放一边
            </Button>
          </Row>
        }
      />
    </Stack>
  );
}
