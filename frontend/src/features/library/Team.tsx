import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate } from 'react-router';
import {
  ActionMenu,
  IdentityLink,
  Meter,
  RouteButton,
  AvatarFrame,
  Badge,
  Button,
  Card,
  ClipButton,
  toast,
  Dialog,
  Field,
  Grid,
  Input,
  ListRow,
  Radio,
  Row,
  Section,
  Stack,
  Text,
  TextLink,
  type TextTone,
  useConfirm,
} from '../../components/ui';
import { Avatar } from '../avatar/Avatar';
import { api } from '../../lib/api';
import { basePath, withBase } from '../../lib/base';
import { usePersonas, type Persona } from '../../stores/personas';
import type { Recording } from '../../pages/Library';
import type { Gender, Person, Speaker } from '../../pages/Recording';
import type { Pick } from './useUploads';

interface Waiting extends Speaker {
  recording_id: string;
  filename: string;
}

/** One undecided speaker of a voice heard across recordings. */
interface VoiceMember {
  recording_id: string;
  filename: string;
  transcript_id: string;
  speaker_id: string;
  seconds: number;
}

/** Undecided speakers of several recordings who sound like one person, longest first (``Team.voices``). */
interface Voice {
  id: string;
  members: VoiceMember[];
  seconds: number;
  candidates: Speaker['candidates'];
  near: boolean;
  // Sounds like a voice the owner already said is nobody they know.
  stranger?: boolean;
  // What the meeting calls the speakers, and what was said that names them.
  called?: string | null;
  quote?: string;
  // The leading candidate, surely the one, already heard this long; enough for a twin, so the voice waits behind.
  had?: number;
  enough?: boolean;
}

/** A recording whose undecided speakers have no voiceprint to group by: settled in the recording itself. */
interface Unsorted {
  recording_id: string;
  filename: string;
  speakers: number;
  total: number;
}

interface Review {
  items: Waiting[];
  voices: Voice[];
  fragments: VoiceMember[];
  unsorted: Unsorted[];
  // How long people speak in these recordings, and how much of it is settled.
  heard?: { settled: number; total: number };
}

/** What settling a voice tells the server: who it is, or that nobody known speaks there. */
type VoiceDecision =
  | { action: 'confirm'; person_id: string }
  | { action: 'confirm'; new_person: string }
  | { action: 'unknown' };

const minutes = (seconds: number) =>
  `${Math.max(0, Math.round(seconds / 60))} 分钟`;
const span = (seconds: number) =>
  seconds < 60 ? `${Math.round(seconds)} 秒` : minutes(seconds);
const recordingPath = (id: string) => `/library/${encodeURIComponent(id)}`;

/** One thing for the owner to settle: what kind of task it is, what it is about, and how to settle it. */
function Task({
  kind,
  tone = 'warning',
  children,
}: {
  kind: string;
  tone?: TextTone;
  children: ReactNode;
}) {
  return (
    <Card
      as="li"
      variant="outline"
      padding="md"
      className="flex flex-col gap-2"
    >
      <Text as="span" size="sm" weight="medium" tone={tone}>
        {kind}
      </Text>
      {children}
    </Card>
  );
}

/** A voice nobody has named yet, settled in its row: hear it, then say who it is (someone known, or a new
 * name) or that nobody known speaks there. Enter confirms. */
function Unnamed({
  person,
  known,
  busy,
  onName,
  onResolve,
}: {
  person: Person;
  known: Person[];
  busy: boolean;
  onName: (name: string) => void;
  onResolve: (into: Person | null) => void;
}) {
  const [name, setName] = useState('');
  const typed = name.trim();
  const match = known.find((p) => p.name === typed);
  return (
    <ListRow
      variant="divided"
      leading={
        person.recording_id && person.speaker_id ? (
          <ClipButton
            label={`听${person.name}的声音`}
            src={withBase(
              `/api/library/recordings/${encodeURIComponent(person.recording_id)}/speakers/${encodeURIComponent(person.speaker_id)}/samples/0`,
            )}
          />
        ) : undefined
      }
      title={person.name}
      meta={
        <>
          说了 {minutes(person.seconds)} · {person.speakers} 段录音
          {person.recording_id && (
            <>
              {' · '}
              <TextLink
                size="sm"
                to={recordingPath(person.recording_id)}
                state={{ teamTask: `person-${person.id}` }}
              >
                打开录音
              </TextLink>
            </>
          )}
        </>
      }
      trailing={
        <Row
          as="form"
          gap={2}
          onSubmit={(event) => {
            event.preventDefault();
            if (!typed) return;
            if (match) onResolve(match);
            else onName(typed);
          }}
        >
          <Input
            aria-label={`${person.name}是谁`}
            placeholder="这是谁"
            maxLength={40}
            value={name}
            suggestions={known.map((p) => p.name)}
            className="min-w-0 flex-1 sm:w-56 sm:flex-none"
            onChange={(event) => setName(event.target.value)}
          />
          <Button type="submit" size="sm" disabled={busy || !typed}>
            {match ? `是${match.name}` : '确认'}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => onResolve(null)}
          >
            不认识
          </Button>
        </Row>
      }
    />
  );
}

/** The voice a person is recognised by (one of their voice samples, or a meeting they were confirmed in), as a
 * small reference beside what is being looked at. */
function PersonClip({ person }: { person?: Person }) {
  if (!person?.recording_id || !person.speaker_id) return null;
  return (
    <ClipButton
      label={`听${person.name}确认过的声音`}
      caption={`听${person.name}`}
      src={withBase(
        `/api/library/recordings/${encodeURIComponent(person.recording_id)}/speakers/${encodeURIComponent(person.speaker_id)}/samples/0`,
      )}
    />
  );
}

/** A voice heard in several recordings, settled once for all of them: hear it, then say who it is (the person it
 * sounds like, someone else known, or a new name) or that nobody known speaks there. Enter confirms. */
function VoiceRow({
  voice,
  known,
  busy,
  onDecide,
}: {
  voice: Voice;
  known: Person[];
  busy: boolean;
  onDecide: (decision: VoiceDecision) => void;
}) {
  const [name, setName] = useState('');
  const typed = name.trim();
  const match = known.find((p) => p.name === typed);
  // Heard one recording at a time: a voice grouped from several meetings is checked across them, not by its
  // loudest member alone.
  const [heard, setHeard] = useState(0);
  const current = voice.members[heard % voice.members.length];
  const [likely, other] = voice.candidates;
  const offered = (voice.near && other ? [likely, other] : [likely]).filter(
    Boolean,
  );
  // Who it may be, to hear next to it before saying so.
  const compared = offered.map((c) => known.find((p) => p.id === c.person_id));
  // Only a voice very close to one person is answered by Enter; a nearer guess is a choice to make on purpose.
  const sure = Boolean(likely?.sure) && !voice.near;
  const recordings = new Set(voice.members.map((m) => m.recording_id)).size;
  // A name the meeting calls them that nobody in the team has yet: added as a new person in one click.
  const newName =
    voice.called && !voice.candidates.some((c) => c.called) ? voice.called : '';
  const title = likely?.called
    ? sure
      ? `会上叫作${likely.name}，声音也像`
      : `会上被叫作${likely.name}`
    : newName
      ? `会上被叫作${newName}`
      : !likely
        ? voice.stranger
          ? '你标过不认识的声音'
          : '没听过的声音'
        : sure
          ? `像${likely.name}`
          : `可能是${offered.map((c) => c.name).join('或')}`;
  return (
    <ListRow
      variant="divided"
      leading={
        <ClipButton
          key={`${current.recording_id}/${current.speaker_id}`}
          label={`听这个声音（${current.filename}）`}
          src={withBase(
            `/api/library/recordings/${encodeURIComponent(current.recording_id)}/speakers/${encodeURIComponent(current.speaker_id)}/samples/0`,
          )}
        />
      }
      title={title}
      meta={
        <>
          {recordings} 段录音 · 共说了 {span(voice.seconds)}
          {' · '}
          <TextLink
            size="sm"
            to={recordingPath(current.recording_id)}
            state={{
              teamTask: `voice-${voice.id}`,
              speaker: current.speaker_id,
            }}
          >
            打开录音
          </TextLink>
          {voice.members.length > 1 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={`换一段录音听（现在是第 ${(heard % voice.members.length) + 1} 段，共 ${voice.members.length} 段）`}
              onClick={() => setHeard((n) => n + 1)}
            >
              换一段 {(heard % voice.members.length) + 1}/{voice.members.length}
            </Button>
          )}
          {compared.map((person) => (
            <PersonClip key={person?.id} person={person} />
          ))}
          {likely?.split && (
            <>
              <br />
              这段录音里已经有{likely.name}，可能是同一个人被分成了两位
            </>
          )}
          {voice.called && voice.quote && (
            <>
              <br />「{voice.quote}」
            </>
          )}
          {voice.enough && likely && (
            <>
              <br />
              {`${likely.name}已经有 ${minutes(voice.had ?? 0)}发言，够建分身了，可以先处理别的`}
            </>
          )}
        </>
      }
      trailing={
        <Row
          as="form"
          gap={2}
          onSubmit={(event) => {
            event.preventDefault();
            if (match) onDecide({ action: 'confirm', person_id: match.id });
            else if (typed) onDecide({ action: 'confirm', new_person: typed });
            else if (sure)
              onDecide({ action: 'confirm', person_id: likely.person_id });
          }}
        >
          <Input
            aria-label={`${title}，是谁`}
            placeholder={sure ? '写别人' : '这是谁'}
            maxLength={40}
            value={name}
            suggestions={known.map((p) => p.name)}
            className="min-w-0 flex-1 sm:w-56 sm:flex-none"
            onChange={(event) => setName(event.target.value)}
          />
          <Button type="submit" size="sm" disabled={busy || (!typed && !sure)}>
            {match
              ? `是${match.name}`
              : !typed && sure
                ? `是${likely.name}`
                : '确认'}
          </Button>
          {newName && !typed && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() =>
                onDecide({ action: 'confirm', new_person: newName })
              }
            >
              是{newName}
            </Button>
          )}
          {!sure &&
            offered.map((c) => (
              <Button
                key={c.person_id}
                type="button"
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={() =>
                  onDecide({ action: 'confirm', person_id: c.person_id })
                }
              >
                是{c.name}
              </Button>
            ))}
          <Button
            type="button"
            variant={voice.stranger ? 'secondary' : 'ghost'}
            size="sm"
            disabled={busy}
            onClick={() => onDecide({ action: 'unknown' })}
          >
            {voice.stranger ? '仍不认识' : '不认识'}
          </Button>
        </Row>
      }
    />
  );
}

const GENDERS: [Gender, string][] = [
  ['male', '男'],
  ['female', '女'],
  ['', '不填'],
];

function EditPerson({
  person,
  busy,
  onClose,
  onSave,
}: {
  person: Person | null;
  busy: boolean;
  onClose: () => void;
  onSave: (change: { name: string; gender: Gender }) => void;
}) {
  const [name, setName] = useState('');
  const [gender, setGender] = useState<Gender>('');
  useEffect(() => {
    if (!person) return;
    setName(person.name);
    setGender(person.gender);
  }, [person]);
  return (
    <Dialog
      open={!!person}
      onOpenChange={(open) => !open && onClose()}
      title={`编辑「${person?.name ?? ''}」`}
    >
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) onSave({ name: name.trim(), gender });
        }}
      >
        <Field id="person-name" label="名字">
          <Input
            id="person-name"
            maxLength={40}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Stack as="fieldset" gap={1}>
          <Text as="legend" weight="medium">
            性别
          </Text>
          <Row gap={6} wrap>
            {GENDERS.map(([value, label]) => (
              <Radio
                key={label}
                name="person-gender"
                label={label}
                checked={gender === value}
                onChange={() => setGender(value)}
              />
            ))}
          </Row>
          <Text size="sm" tone="secondary">
            分身的插画形象会换成对应性别的一款。
          </Text>
        </Stack>
        <Row gap={2} justify="end">
          <Button type="button" variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={busy || !name.trim()}>
            保存
          </Button>
        </Row>
      </form>
    </Dialog>
  );
}

/**
 * The work e-mail or employee number of the person a twin is made for: when they sign in with the company account
 * it names, the twin becomes theirs. Asked when the twin is made, and changeable until they have taken it.
 */
function WorkClaim({
  person,
  twin,
  busy,
  onClose,
  onSave,
}: {
  person: Person | null;
  twin?: Persona;
  busy: boolean;
  onClose: () => void;
  onSave: (claim: string) => void;
}) {
  const [claim, setClaim] = useState('');
  useEffect(() => {
    if (person) setClaim(twin?.claim ?? '');
  }, [person, twin]);
  const making = !twin;
  return (
    <Dialog
      open={!!person}
      onOpenChange={(open) => !open && onClose()}
      title={
        making
          ? `为${person?.name ?? ''}建分身`
          : `${person?.name ?? ''}的企业邮箱或工号`
      }
      body="填 TA 企业账号的邮箱或工号。TA 一登录，分身就归到 TA 名下；TA 看过并点“没问题”之前，分身不对同事回答。"
    >
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(claim.trim());
        }}
      >
        <Field
          id="work-claim"
          label={
            making ? '企业邮箱或工号（不知道可以先空着）' : '企业邮箱或工号'
          }
          help={
            twin?.claim_rejected
              ? `${twin.claim_rejected} 的主人说这不是 TA，换一个吧`
              : '填错了也不要紧：对方登录后点“这不是我”，分身会退回给你。'
          }
        >
          <Input
            id="work-claim"
            autoComplete="off"
            maxLength={254}
            placeholder="name@company.com 或 77845"
            value={claim}
            onChange={(event) => setClaim(event.target.value)}
          />
        </Field>
        <Row gap={2} justify="end">
          <Button type="button" variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            type="submit"
            disabled={busy || (!making && !claim.trim() && !twin?.claim)}
          >
            {making ? '建好' : '保存'}
          </Button>
        </Row>
      </form>
    </Dialog>
  );
}

/** Who a twin can still be made for, or whose twin waits for an e-mail or employee number: neither taken nor
 * pointed at anyone yet. */
const unaddressed = (person: Person, twin?: Persona) =>
  !person.auto &&
  person.speakers > 0 &&
  (person.persona_id ? !!twin && twin.claimed === false && !twin.claim : true);

/**
 * Twins for several colleagues at once: everyone heard in the meetings who has no twin yet, or whose twin nobody
 * can take yet, each with a field for their work e-mail or employee number. Rows left empty stay as they are.
 */
function BatchClaim({
  open,
  people,
  twins,
  onClose,
  onDone,
}: {
  open: boolean;
  people: Person[];
  twins: Persona[];
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [claims, setClaims] = useState<Record<string, string>>({});
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setClaims({});
      setFailures({});
    }
  }, [open]);
  const filled = people.filter((person) => claims[person.id]?.trim());
  const save = async () => {
    setBusy(true);
    const failed: Record<string, string> = {};
    for (const person of filled) {
      const claim = claims[person.id].trim();
      try {
        if (person.persona_id)
          await api(
            `/api/personas/${encodeURIComponent(person.persona_id)}/claim`,
            { method: 'PUT', json: { claim } },
          );
        else
          await api(
            `/api/library/people/${encodeURIComponent(person.id)}/persona`,
            { method: 'POST', json: { claim } },
          );
      } catch (failure) {
        failed[person.id] =
          failure instanceof Error ? failure.message : '没能保存';
      }
    }
    await onDone();
    setBusy(false);
    setFailures(failed);
    // What went through leaves the list; what did not stays, with why.
    setClaims((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([id]) => id in failed),
      ),
    );
    if (!Object.keys(failed).length) onClose();
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => !value && onClose()}
      title="为同事建分身"
      body="填同事企业账号的邮箱或工号。系统先用会议为 TA 建好分身，TA 用企业账号一登录就归到自己名下；TA 看过并点“没问题”之前，分身不对同事回答。"
    >
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (filled.length) void save();
        }}
      >
        <Stack as="ul" gap={3}>
          {people.map((person) => {
            const twin = twins.find((t) => t.id === person.persona_id);
            const id = `batch-claim-${person.id}`;
            return (
              <li key={person.id}>
                <Field
                  id={id}
                  label={`${person.name} · ${person.speakers} 段录音`}
                  help={
                    twin?.claim_rejected
                      ? `${twin.claim_rejected} 说不是 TA，换一个`
                      : undefined
                  }
                  error={failures[person.id]}
                >
                  <Input
                    id={id}
                    autoComplete="off"
                    maxLength={254}
                    placeholder="邮箱或工号，不知道就空着"
                    value={claims[person.id] ?? ''}
                    disabled={busy}
                    onChange={(event) =>
                      setClaims((current) => ({
                        ...current,
                        [person.id]: event.target.value,
                      }))
                    }
                  />
                </Field>
              </li>
            );
          })}
        </Stack>
        <Text size="sm" tone="secondary">
          不知道的先空着，以后在这里补。填错了也不要紧：对方登录后点“这不是我”，分身会退回给你。
        </Text>
        <Row gap={2} justify="end">
          <Button type="button" variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" loading={busy} disabled={!filled.length}>
            {filled.length
              ? `为 ${filled.length} 位同事建分身`
              : '为同事建分身'}
          </Button>
        </Row>
      </form>
    </Dialog>
  );
}

/** Whose a twin made from the meetings is: waiting for its person to sign in, or theirs. */
function ClaimLine({ twin }: { twin?: Persona }) {
  const [label, tone]: [string, TextTone] | [null, null] = twin?.claimed
    ? ['本人已认领', 'success']
    : twin?.claim_rejected
      ? [`${twin.claim_rejected} 说不是 TA，换一个`, 'danger']
      : twin?.claim
        ? [`等 ${twin.claim} 登录认领`, 'secondary']
        : [null, null];
  return (
    label && (
      <Text size="sm" tone={tone} breakAll>
        {label}
      </Text>
    )
  );
}

/** What the owner has to settle, quiet background progress, and everyone found in
 * the recordings, each with their twin. */
export function Team({
  version,
  recordings,
  onReload,
  uploads = [],
  onStopUpload,
}: {
  version: number;
  recordings: Recording[];
  onReload?: () => Promise<void>;
  uploads?: Pick[];
  onStopUpload?: () => void;
}) {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [waiting, setWaiting] = useState<Waiting[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [fragments, setFragments] = useState<VoiceMember[]>([]);
  const [unsorted, setUnsorted] = useState<Unsorted[]>([]);
  const [heard, setHeard] = useState<Review['heard']>();
  const [name, setName] = useState('');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Person | null>(null);
  const [addressing, setAddressing] = useState<Person | null>(null);
  const [batching, setBatching] = useState(false);
  const taskList = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const [focusPending, setFocusPending] = useState<string | null>(
    location.state?.resolvedTeamTask ?? null,
  );
  const confirm = useConfirm();
  const navigate = useNavigate();
  const refreshPersonas = usePersonas((state) => state.refresh);
  const switchTo = usePersonas((state) => state.switchTo);
  const twins = usePersonas((state) => state.items);

  const load = useCallback(async () => {
    try {
      const [folks, queue] = await Promise.all([
        api<{ items: Person[] }>('/api/library/people'),
        api<Review>('/api/library/review'),
      ]);
      setPeople(folks.items);
      setWaiting(queue.items);
      setVoices(queue.voices);
      setFragments(queue.fragments);
      setUnsorted(queue.unsorted);
      setHeard(queue.heard);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法加载人物');
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load, version]);
  const updating = !!people?.some((p) => p.updating);
  useEffect(() => {
    if (!updating) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [updating, load]);

  const act = async (work: () => Promise<unknown>, task?: string) => {
    setBusy(true);
    setError('');
    try {
      await work();
      if (task) setFocusPending(task);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败');
    }
    await load();
    setBusy(false);
  };
  const add = () =>
    act(async () => {
      await api('/api/library/people', {
        method: 'POST',
        json: { name: name.trim() },
      });
      setName('');
    });
  const saveClaim = (person: Person, claim: string) =>
    act(async () => {
      if (person.persona_id)
        await api(
          `/api/personas/${encodeURIComponent(person.persona_id)}/claim`,
          {
            method: 'PUT',
            json: { claim: claim || null },
          },
        );
      else
        await api(
          `/api/library/people/${encodeURIComponent(person.id)}/persona`,
          { method: 'POST', json: { claim: claim || null } },
        );
      await refreshPersonas();
      setAddressing(null);
    });
  const remove = async (person: Person) => {
    if (
      await confirm({
        title: `删除「${person.name}」？`,
        body: '这个人在各段录音里的归属和声纹样本会一起删除',
        confirmLabel: '删除人物',
        tone: 'danger',
      })
    )
      await act(() =>
        api(`/api/library/people/${encodeURIComponent(person.id)}`, {
          method: 'DELETE',
        }),
      );
  };
  const rename = (person: Person, value: string) =>
    act(
      () =>
        api(`/api/library/people/${encodeURIComponent(person.id)}`, {
          method: 'PATCH',
          json: { name: value },
        }),
      `person-${person.id}`,
    );
  const resolve = (person: Person, into: Person | null) =>
    act(
      () =>
        api(`/api/library/people/${encodeURIComponent(person.id)}/resolve`, {
          method: 'POST',
          json: { into: into?.id ?? null },
        }),
      `person-${person.id}`,
    );
  const edit = (person: Person, change: { name: string; gender: Gender }) =>
    act(async () => {
      await api(`/api/library/people/${encodeURIComponent(person.id)}`, {
        method: 'PATCH',
        json: {
          ...(change.name !== person.name ? { name: change.name } : {}),
          gender: change.gender,
        },
      });
      setEditing(null);
      // The twin's name and illustration follow.
      if (person.persona_id) await refreshPersonas();
    });
  // An administrator takes two people for one, keeping the one with a twin (or who spoke more).
  const merge = (one: Person, other: Person) => {
    const [kept, folded] =
      other.persona_id || (!one.persona_id && other.speakers > one.speakers)
        ? [other, one]
        : [one, other];
    return act(
      () =>
        api(`/api/library/people/${encodeURIComponent(folded.id)}/merge`, {
          method: 'POST',
          json: { into: kept.id },
        }),
      `similar-${one.id}-${other.id}`,
    );
  };
  const apart = (one: Person, other: Person) =>
    act(
      () =>
        api(`/api/library/people/${encodeURIComponent(one.id)}/apart`, {
          method: 'POST',
          json: { other: other.id },
        }),
      `similar-${one.id}-${other.id}`,
    );
  // Every recording the voice was heard in is settled at once.
  const decideVoice = (
    members: VoiceMember[],
    decision: VoiceDecision,
    task: string,
  ) =>
    act(async () => {
      const { recognised } = await api<{ recognised?: number }>(
        '/api/library/voices',
        {
          method: 'POST',
          json: {
            members: members.map(
              ({ recording_id, transcript_id, speaker_id }) => ({
                recording_id,
                transcript_id,
                speaker_id,
              }),
            ),
            ...decision,
          },
        },
      );
      // What the new voice samples settled elsewhere: an answer that saves the next questions.
      if (recognised)
        toast(`又按声音认出了 ${recognised} 位说话人，不用再问`, 'success');
    }, task);
  const open = async (personaId: string, page: '/chat' | '/profile') => {
    await switchTo(personaId);
    void navigate(page);
  };

  // Only who the viewer may settle: voices in recordings they uploaded (or all, for an administrator).
  const unnamed = people?.filter((p) => p.auto && p.can_manage !== false) ?? [];
  // The team's roster holds everyone; this page shows the people the viewer looks after or can talk to.
  const named = people?.filter(
    (p) =>
      !p.auto && (p.can_manage !== false || p.persona_id || p.self_claimed),
  );
  const byId = new Map((people ?? []).map((p) => [p.id, p]));
  const similar = (people ?? []).flatMap((p) =>
    (p.similar ?? [])
      .filter((id) => p.id < id && byId.has(id))
      .map((id) => [p, byId.get(id)!] as const),
  );
  const arriving = recordings.filter(
    (r) => r.status === 'queued' || r.status === 'transcribing',
  );
  const failed = recordings.filter((r) => r.status === 'failed');
  const organising = people?.filter((p) => p.updating) ?? [];
  const twinOf = (person: Person) =>
    twins.find((t) => t.id === person.persona_id);
  // A colleague said a twin made for them is not theirs: it is back with the owner, to point at the right person.
  const disowned = named?.filter((p) => twinOf(p)?.claim_rejected) ?? [];
  const toAddress = named?.filter((p) => unaddressed(p, twinOf(p))) ?? [];
  const proofreading = recordings.filter(
    (r) => r.status === 'ready' && r.proofread === 'waiting',
  );
  const fragmentRecordings = new Set(fragments.map((m) => m.recording_id)).size;
  // Whoever speaks longest first, a new person or a voice alike: settling them teaches a twin the most.
  const voiced = [
    ...unnamed.map((person) => ({
      id: `person-${person.id}`,
      seconds: person.seconds,
      enough: false,
      person,
    })),
    ...voices.map((voice) => ({
      id: `voice-${voice.id}`,
      seconds: voice.seconds,
      enough: Boolean(voice.enough),
      voice,
    })),
  ].sort(
    // Whoever a twin still lacks first, then the longest.
    (a, b) => Number(a.enough) - Number(b.enough) || b.seconds - a.seconds,
  );
  const taskIds = [
    ...voiced.map((v) => v.id),
    ...(fragments.length ? ['fragments'] : []),
    ...similar.map(([a, b]) => `similar-${a.id}-${b.id}`),
    ...waiting.map((w) => `speaker-${w.recording_id}-${w.id}`),
    ...unsorted.map((u) => `unsorted-${u.recording_id}`),
    ...failed.map((r) => `failed-${r.id}`),
    ...disowned.map((p) => `disowned-${p.id}`),
  ];
  const tasks = taskIds.length;
  const pending =
    arriving.length + organising.length + proofreading.length + uploads.length;
  const taskOrder = taskIds.join('|');
  useEffect(() => {
    if (!focusPending || !people || busy) return;
    if (taskOrder.split('|').includes(focusPending)) return;
    // The next voice's name field before any button, so naming several is type, Enter, type, Enter.
    const next =
      taskList.current?.querySelector<HTMLElement>('input:not(:disabled)') ??
      taskList.current?.querySelector<HTMLElement>('a, button:not(:disabled)');
    next?.focus();
    setFocusPending(null);
    if (location.state?.resolvedTeamTask)
      void navigate(location.pathname, { replace: true, state: null });
  }, [focusPending, people, busy, taskOrder, location, navigate]);

  const retry = (recording: Recording) =>
    act(async () => {
      await api(
        `/api/library/recordings/${encodeURIComponent(recording.id)}/retry`,
        {
          method: 'POST',
        },
      );
      await onReload?.();
    }, `failed-${recording.id}`);
  const removeRecording = async (recording: Recording) => {
    if (
      !(await confirm({
        title: `删除「${recording.filename}」？`,
        body: '转写结果和试听文件会一起删除，不能恢复',
        confirmLabel: '删除录音',
        tone: 'danger',
      }))
    )
      return;
    await act(async () => {
      await api(`/api/library/recordings/${encodeURIComponent(recording.id)}`, {
        method: 'DELETE',
      });
      await onReload?.();
    }, `failed-${recording.id}`);
  };
  return (
    <>
      {error && (
        <Text role="alert" tone="danger">
          {error}
        </Text>
      )}
      {tasks > 0 && (
        <Section
          title="需要你处理"
          badge={<Badge tone="warning">{tasks}</Badge>}
          actions={
            <Text size="xs" tone="tertiary">
              处理完一项会自动跳到下一项
            </Text>
          }
          framed
        >
          <Stack ref={taskList} gap={3}>
            {heard && heard.total > 0 && (
              <Meter
                size="sm"
                value={heard.settled}
                max={heard.total}
                label="会议里的发言，已经知道是谁说的"
              />
            )}
            {voiced.length > 0 && (
              <Stack as="ul" gap={0} aria-label="新出现的声音">
                {voiced.map((entry) =>
                  'person' in entry ? (
                    <Unnamed
                      key={entry.id}
                      person={entry.person}
                      known={named ?? []}
                      busy={busy}
                      onName={(value) => void rename(entry.person, value)}
                      onResolve={(into) => void resolve(entry.person, into)}
                    />
                  ) : (
                    <VoiceRow
                      key={entry.id}
                      voice={entry.voice}
                      known={(people ?? []).filter((p) => !p.auto)}
                      busy={busy}
                      onDecide={(decision) =>
                        void decideVoice(
                          entry.voice.members,
                          decision,
                          entry.id,
                        )
                      }
                    />
                  ),
                )}
              </Stack>
            )}
            {voiced.length > 0 && (
              <Row gap={2} wrap>
                <Text size="sm" tone="secondary">
                  认不出的人，可以请本人来认：登录后录一句话，系统会找出哪些是
                  TA 说的
                </Text>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    const invite = `我们在用会议录音整理每个人的发言，为你建分身。打开这个链接，登录后录一句话，就能认出哪些是你说的：${window.location.origin}${basePath()}/#/voice`;
                    void navigator.clipboard.writeText(invite).then(
                      () => toast('邀请已复制，可以发给同事', 'success'),
                      () => toast(invite, 'info', 15000),
                    );
                  }}
                >
                  复制邀请
                </Button>
              </Row>
            )}
            {tasks > unnamed.length + voices.length && (
              <Grid as="ul" columns={3} gap={3}>
                {fragments.length > 0 && (
                  <Task key="fragments" kind="零碎的声音">
                    <Text weight="medium">
                      {fragmentRecordings} 段录音里有 {fragments.length}{' '}
                      段很短的声音，共{' '}
                      {span(fragments.reduce((sum, m) => sum + m.seconds, 0))}
                      ，不像任何人
                    </Text>
                    <Text size="sm" tone="secondary">
                      多是插话或附和，放一边不影响分身
                    </Text>
                    <Row gap={2}>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          void decideVoice(
                            fragments,
                            { action: 'unknown' },
                            'fragments',
                          )
                        }
                      >
                        都放一边
                      </Button>
                    </Row>
                  </Task>
                )}
                {similar.map(([a, b]) => (
                  <Task key={`similar-${a.id}-${b.id}`} kind="可能是同一个人">
                    <Text weight="medium">
                      {a.name} 和 {b.name}
                    </Text>
                    <Text size="sm" tone="secondary">
                      合并录音库时同名，没法确定是不是一个人
                    </Text>
                    <Row gap={2}>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        onClick={() => void merge(a, b)}
                      >
                        合并
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => void apart(a, b)}
                      >
                        不是同一个人
                      </Button>
                    </Row>
                  </Task>
                ))}
                {waiting.map((w) => (
                  <Task key={`${w.recording_id}-${w.id}`} kind="有人说不是自己">
                    <Text weight="medium">
                      <span className="break-all">{w.filename}</span> · {w.id}{' '}
                      原来标成的人说这不是 TA
                    </Text>
                    <RouteButton
                      to={recordingPath(w.recording_id)}
                      state={{
                        teamTask: `speaker-${w.recording_id}-${w.id}`,
                        speaker: w.id,
                      }}
                      size="sm"
                    >
                      试听并确认
                    </RouteButton>
                  </Task>
                ))}
                {unsorted.map((u) => (
                  <Task
                    key={`unsorted-${u.recording_id}`}
                    kind={u.speakers === u.total ? '还没认人' : '还有人没认'}
                  >
                    <Text weight="medium">
                      <span className="break-all">{u.filename}</span> ·{' '}
                      {u.speakers} 位说话人待确认
                    </Text>
                    <RouteButton
                      to={recordingPath(u.recording_id)}
                      state={{ teamTask: `unsorted-${u.recording_id}` }}
                      size="sm"
                    >
                      试听并确认
                    </RouteButton>
                  </Task>
                ))}
                {disowned.map((p) => (
                  <Task
                    key={`disowned-${p.id}`}
                    kind="分身被退回"
                    tone="danger"
                  >
                    <Text weight="medium" breakAll>
                      {p.name}：{twinOf(p)?.claim_rejected} 说这不是 TA
                    </Text>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => setAddressing(p)}
                    >
                      换个邮箱或工号
                    </Button>
                  </Task>
                ))}
                {failed.map((r) => (
                  <Task key={r.id} kind="转写失败" tone="danger">
                    <Text weight="medium" breakAll>
                      {r.filename}
                    </Text>
                    <Row gap={2}>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={busy}
                        onClick={() => void retry(r)}
                      >
                        重试
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => void removeRecording(r)}
                      >
                        删除
                      </Button>
                    </Row>
                  </Task>
                ))}
              </Grid>
            )}
          </Stack>
        </Section>
      )}
      <Section
        title="人物"
        badge={
          <Text size="sm" tone="secondary">
            {named?.length ?? 0} 人
          </Text>
        }
        actions={
          <Row gap={2} wrap>
            {toAddress.length > 0 && (
              <Button variant="secondary" onClick={() => setBatching(true)}>
                按邮箱或工号建分身（{toAddress.length}）
              </Button>
            )}
            <Input
              aria-label="找人"
              placeholder="找人"
              className="w-36"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <Row
              as="form"
              gap={2}
              onSubmit={(event) => {
                event.preventDefault();
                if (name.trim()) void add();
              }}
            >
              <Input
                aria-label="人物名字"
                placeholder="手动添加人物"
                maxLength={40}
                className="w-48"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              <Button
                type="submit"
                variant="secondary"
                disabled={busy || !name.trim()}
              >
                添加
              </Button>
            </Row>
          </Row>
        }
      >
        {named && named.length === 0 && (
          <Text size="sm" tone="secondary">
            录音转写后，认出来的人会出现在这里；也可以打开录音，确认说话人是谁。
          </Text>
        )}
        <Grid as="ul" columns={3}>
          {named
            ?.filter((person) =>
              person.name
                .toLocaleLowerCase()
                .includes(search.trim().toLocaleLowerCase()),
            )
            .map((person) => (
              <Card
                as="li"
                key={person.id}
                variant="outline"
                className="flex flex-col gap-4"
              >
                <IdentityLink
                  to={person.persona_id ? '/profile' : undefined}
                  label={
                    person.persona_id
                      ? `${person.name}的档案`
                      : `编辑${person.name}`
                  }
                  onClick={() =>
                    person.persona_id
                      ? void open(person.persona_id, '/profile')
                      : setEditing(person)
                  }
                >
                  <AvatarFrame>
                    <PersonFace
                      person={person}
                      twin={twins.find((t) => t.id === person.persona_id)}
                    />
                  </AvatarFrame>
                  <Stack gap={0} grow>
                    <Text size="lg" weight="semibold" truncate>
                      {person.name}
                    </Text>
                    <Text size="sm" tone="secondary">
                      {person.speakers} 段录音 · {minutes(person.seconds)}
                      {person.seconds > 0 && (person.lacking ?? 0) >= 60
                        ? ` · 素材还差约 ${minutes(person.lacking ?? 0)}`
                        : ''}
                    </Text>
                  </Stack>
                </IdentityLink>
                <Row gap={2} justify="between">
                  {person.self_claimed ? (
                    <Badge tone="success">本人已认领</Badge>
                  ) : person.twin_elsewhere ? (
                    <Badge tone="neutral">同事建了分身</Badge>
                  ) : person.persona_id ? (
                    person.updating ? (
                      <Badge tone="warning">记忆更新中</Badge>
                    ) : (
                      <Badge tone="success">可以聊</Badge>
                    )
                  ) : (
                    <Badge tone="neutral">还没有分身</Badge>
                  )}
                  <PersonClip person={person} />
                </Row>
                <ClaimLine
                  twin={twins.find((t) => t.id === person.persona_id)}
                />
                <div className="mt-auto flex flex-wrap gap-2">
                  {person.self_claimed ? (
                    <Text size="sm" tone="secondary">
                      TA 听出了自己的声音，分身归 TA 自己
                    </Text>
                  ) : person.twin_elsewhere ? (
                    <Text size="sm" tone="secondary">
                      分身由建它的同事管理
                    </Text>
                  ) : person.persona_id ? (
                    <>
                      <Button
                        className="flex-1"
                        disabled={person.updating}
                        onClick={() => void open(person.persona_id!, '/chat')}
                      >
                        {person.updating ? '整理完成后可以聊' : '和分身聊聊'}
                      </Button>
                    </>
                  ) : person.can_manage === false ? null : (
                    <>
                      <Button
                        variant="secondary"
                        className="flex-1"
                        disabled={busy || !person.speakers}
                        onClick={() => setAddressing(person)}
                      >
                        生成分身
                      </Button>
                    </>
                  )}
                  {person.can_manage !== false && (
                    <ActionMenu
                      label={`更多：${person.name}`}
                      items={[
                        {
                          label: '编辑名字和性别',
                          disabled: busy,
                          onSelect: () => setEditing(person),
                        },
                        ...(person.persona_id &&
                        twins.find((t) => t.id === person.persona_id)
                          ?.claimed === false
                          ? [
                              {
                                label: '企业邮箱或工号',
                                disabled: busy,
                                onSelect: () => setAddressing(person),
                              },
                            ]
                          : []),
                        ...(!person.persona_id &&
                        !person.self_claimed &&
                        !person.twin_elsewhere
                          ? [
                              {
                                label: '删除',
                                disabled: busy,
                                onSelect: () => void remove(person),
                              },
                            ]
                          : []),
                      ]}
                    />
                  )}
                </div>
              </Card>
            ))}
        </Grid>
      </Section>
      {pending > 0 && (
        <Section label="正在处理" gap={2}>
          <Text size="sm" tone="secondary">
            正在处理 {pending} 项
          </Text>
          <Stack as="ul" gap={1}>
            {uploads.map((pick) => (
              <Text
                as="li"
                key={`${pick.file.name}-${pick.file.lastModified}-${pick.file.size}`}
                size="sm"
                tone="secondary"
                breakAll
              >
                {pick.file.name} ·{' '}
                {pick.progress?.paused
                  ? '等待网络恢复'
                  : `上传中 ${Math.round(pick.progress ? (pick.progress.offset / pick.progress.size) * 100 : 0)}%`}
              </Text>
            ))}
            {arriving.map((r) => (
              <Stack as="li" key={r.id} gap={1}>
                <Text size="sm" tone="secondary" breakAll>
                  {r.filename} · {r.status === 'queued' ? '排队转写' : '转写中'}
                </Text>
                {r.status === 'transcribing' && (
                  <Meter
                    label={`${r.filename}转写进度`}
                    size="sm"
                    hideLabel
                    value={r.duration_s ? r.transcribed_s : null}
                    max={r.duration_s ?? 100}
                  />
                )}
              </Stack>
            ))}
            {proofreading.map((r) => (
              <Text
                as="li"
                key={`proofread-${r.id}`}
                size="sm"
                tone="secondary"
                breakAll
              >
                {r.filename} · 等待校对
              </Text>
            ))}
            {organising.map((p) => (
              <Text as="li" key={p.id} size="sm" tone="secondary" breakAll>
                {p.name} · 整理记忆中
              </Text>
            ))}
          </Stack>
          {uploads.length > 0 && onStopUpload && (
            <TextLink size="sm" onClick={onStopUpload}>
              停止上传（已传的部分下次接着传）
            </TextLink>
          )}
        </Section>
      )}
      <BatchClaim
        open={batching}
        people={toAddress}
        twins={twins}
        onClose={() => setBatching(false)}
        onDone={async () => {
          await refreshPersonas();
          await load();
        }}
      />
      <WorkClaim
        person={addressing}
        twin={twins.find((t) => t.id === addressing?.persona_id)}
        busy={busy}
        onClose={() => setAddressing(null)}
        onSave={(claim) => addressing && void saveClaim(addressing, claim)}
      />
      <EditPerson
        person={editing}
        busy={busy}
        onClose={() => setEditing(null)}
        onSave={(change) => editing && void edit(editing, change)}
      />
    </>
  );
}

/** The twin's portrait or illustration; the first character of the name before there is a twin. */
function PersonFace({ person, twin }: { person: Person; twin?: Persona }) {
  if (!twin) return <>{Array.from(person.name)[0]}</>;
  return twin.avatar_url ? (
    <img src={twin.avatar_url} alt="" className="size-full object-cover" />
  ) : (
    <Avatar preset={twin.avatar_preset} blinking={false} />
  );
}
