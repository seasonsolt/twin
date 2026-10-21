import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router';
import {
  ActionMenu,
  IdentityLink,
  Meter,
  RouteButton,
  AvatarFrame,
  Badge,
  Button,
  Card,
  Chip,
  ClipButton,
  toast,
  Dialog,
  Disclosure,
  Field,
  Grid,
  Input,
  Notice,
  Radio,
  Row,
  Section,
  SideTabs,
  Stack,
  StatusDot,
  Tabs,
  TaskRow,
  Text,
  TextLink,
  type TextTone,
  useConfirm,
} from '../../components/ui';
import { Avatar } from '../avatar/Avatar';
import { api } from '../../lib/api';
import { byName } from '../../lib/names';
import { basePath, withBase } from '../../lib/base';
import { usePolling } from '../../lib/usePolling';
import { usePersonas, type Persona } from '../../stores/personas';
import type { Recording } from '../../pages/Library';
import type { Gender, Person, Speaker } from '../../pages/Recording';
import type { Pick } from './useUploads';
import { MixedSpeaker, type SuspectSpeaker } from './MixedSpeaker';

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

/** A fragment, with the person its voice sounds like, if anyone. */
interface Fragment extends VoiceMember {
  like?: { person_id: string; name: string } | null;
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
  fragments: Fragment[];
  unsorted: Unsorted[];
  // Confirmed speakers some of whose speech sounds like someone else (``media.review``).
  suspects?: SuspectSpeaker[];
  // How long people speak in these recordings, and how much of it is settled.
  heard?: { settled: number; total: number };
}

/** What settling a voice tells the server: who it is, or that nobody known speaks there. */
type VoiceDecision =
  | { action: 'confirm'; person_id: string; sample?: false }
  | { action: 'confirm'; new_person: string }
  | { action: 'unknown' }
  | { action: 'mixed' };

/** The kinds of thing waiting for the owner, in the order they are listed. */
type Category =
  | 'voice'
  | 'mixed'
  | 'unsorted'
  | 'failed'
  | 'similar'
  | 'disputed'
  | 'disowned'
  | 'fragments';

/** Which kind a task belongs to, from its id (the id a recording page hands back once it is settled). */
const categoryOf = (task: string): Category | undefined =>
  (
    [
      ['person-', 'voice'],
      ['voice-', 'voice'],
      ['mixed-', 'mixed'],
      ['unsorted-', 'unsorted'],
      ['failed-', 'failed'],
      ['similar-', 'similar'],
      ['speaker-', 'disputed'],
      ['disowned-', 'disowned'],
      ['fragments', 'fragments'],
    ] as const
  ).find(([prefix]) => task.startsWith(prefix))?.[1];

const CATEGORIES: {
  id: Category;
  label: string;
  tone: 'warning' | 'danger' | 'info';
  help: string;
}[] = [
  {
    id: 'voice',
    label: '新出现的声音',
    tone: 'warning',
    help: '说得最多的在前；处理完一项会自动跳到下一项',
  },
  {
    id: 'mixed',
    label: '混进了别人的话',
    tone: 'warning',
    help: '已确认的声音大部分不像这个人，可能认错了人；疑似片段已自动排除，听几段后决定是谁',
  },
  {
    id: 'unsorted',
    label: '还没认人',
    tone: 'warning',
    help: '这些录音的说话人没有声纹可比，要在录音里逐个确认',
  },
  {
    id: 'failed',
    label: '转写失败',
    tone: 'danger',
    help: '转写没有成功，可以重试，或删掉这段录音',
  },
  {
    id: 'similar',
    label: '可能是同一个人',
    tone: 'info',
    help: '合并录音库时同名，没法确定是不是一个人',
  },
  {
    id: 'disputed',
    label: '有人说不是自己',
    tone: 'warning',
    help: '原来标成的人说这不是 TA，试听后改成对的人',
  },
  {
    id: 'disowned',
    label: '分身被退回',
    tone: 'danger',
    help: '对方登录后说这个分身不是 TA，换一个邮箱或工号',
  },
  {
    id: 'fragments',
    label: '零碎的声音',
    tone: 'info',
    help: '多是插话或附和，放一边不影响分身',
  },
];

// New voices shown at first, and each time more are asked for.
const VOICES_PER_PAGE = 5;

const minutes = (seconds: number) =>
  `${Math.max(0, Math.round(seconds / 60))} 分钟`;
const span = (seconds: number) =>
  seconds < 60 ? `${Math.round(seconds)} 秒` : minutes(seconds);
// The speaker to hear is in the address, so a recording opened in a new tab opens on the voice heard here too.
const recordingPath = (id: string, speaker?: string | null) =>
  `/library/${encodeURIComponent(id)}${speaker ? `?speaker=${encodeURIComponent(speaker)}` : ''}`;

/** The name field, confirm button and "⋯" menu every voice row ends with, so the rows line up. Enter confirms. */
function Ask({
  label,
  value,
  onChange,
  known,
  menu,
  confirmable,
  primary,
  busy,
  onSubmit,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  known: Person[];
  menu: { label: string; onSelect: () => void }[];
  /** Whether there is an answer to confirm. */
  confirmable: boolean;
  /** A sure guess is already in the field: confirming it is the row's main action. */
  primary: boolean;
  busy: boolean;
  onSubmit: () => void;
}) {
  return (
    <Row
      as="form"
      gap={2}
      grow
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Input
        aria-label={label}
        placeholder="这是谁"
        maxLength={40}
        value={value}
        suggestions={known.map((p) => p.name).sort(byName)}
        className="min-w-0 flex-1"
        onChange={(event) => onChange(event.target.value)}
      />
      <Button
        type="submit"
        variant={primary ? 'primary' : 'secondary'}
        disabled={busy || !confirmable}
      >
        确认
      </Button>
      <ActionMenu
        label={`更多选项：${label.replace(/，?是谁$/u, '')}`}
        items={menu.map((item) => ({ ...item, disabled: busy }))}
      />
    </Row>
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
    <TaskRow
      leading={
        person.recording_id && person.speaker_id ? (
          <ClipButton
            size="md"
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
          {person.speakers} 段录音 · 共说了 {minutes(person.seconds)}
          {person.recording_id && (
            <>
              {' · '}
              <TextLink
                size="sm"
                to={recordingPath(person.recording_id, person.speaker_id)}
                state={{ teamTask: `person-${person.id}` }}
              >
                打开录音
              </TextLink>
            </>
          )}
        </>
      }
      actionsWidth="field"
      actions={
        <Ask
          label={`${person.name}是谁`}
          value={name}
          onChange={setName}
          known={known}
          busy={busy}
          confirmable={!!typed}
          primary={false}
          menu={[{ label: '不认识', onSelect: () => onResolve(null) }]}
          onSubmit={() => {
            if (!typed) return;
            if (match) onResolve(match);
            else onName(typed);
          }}
        />
      }
    />
  );
}

/** The voice a person is recognised by (one of their voice samples, or a meeting they were confirmed in), as a
 * small reference beside what is being looked at. */
function PersonClip({
  person,
  icon = false,
}: {
  person?: Person;
  /** Only the round play button, for a card; otherwise a text button naming the person. */
  icon?: boolean;
}) {
  if (!person?.recording_id || !person.speaker_id) return null;
  return (
    <ClipButton
      size="md"
      label={`听${person.name}确认过的声音`}
      caption={icon ? undefined : `听${person.name}`}
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
  const [likely, other] = voice.candidates;
  // Only a voice very close to one person is answered by Enter; a nearer guess is a choice to make on purpose.
  const sure = Boolean(likely?.sure) && !voice.near;
  // A sure guess is already in the field, so Enter confirms it; any other guess is one click away under the text.
  const [name, setName] = useState(sure ? likely.name : '');
  const typed = name.trim();
  const match = known.find((p) => p.name === typed);
  // Heard one recording at a time: a voice grouped from several meetings is checked across them, not by its
  // loudest member alone.
  const [heard, setHeard] = useState(0);
  const current = voice.members[heard % voice.members.length];
  const offered = (voice.near && other ? [likely, other] : [likely]).filter(
    Boolean,
  );
  // Who it may be, to hear next to it before saying so.
  const compared = offered.map((c) => known.find((p) => p.id === c.person_id));
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
  const hint = [
    likely?.split &&
      `这段录音里已经有${likely.name}，可能是同一个人被分成了两位`,
    voice.enough &&
      likely &&
      `${likely.name}已经有 ${minutes(voice.had ?? 0)}发言，够建分身了，可以先处理别的`,
    voice.called && voice.quote && `「${voice.quote}」`,
  ]
    .filter(Boolean)
    .join(' · ');
  const guesses = [
    ...(newName && !typed ? [{ id: 'new', name: newName }] : []),
    ...(!sure ? offered.map((c) => ({ id: c.person_id, name: c.name })) : []),
  ];
  const hearable = voice.members.length > 1 || compared.some(Boolean);
  return (
    <TaskRow
      leading={
        <ClipButton
          size="md"
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
            to={recordingPath(current.recording_id, current.speaker_id)}
            state={{ teamTask: `voice-${voice.id}` }}
          >
            打开录音
          </TextLink>
        </>
      }
      hint={hint || undefined}
      actionsWidth="field"
      actions={
        <Ask
          label={`${title}，是谁`}
          value={name}
          onChange={setName}
          known={known}
          busy={busy}
          confirmable={!!typed || sure}
          primary={sure}
          menu={[
            {
              label: voice.stranger ? '仍不认识' : '不认识',
              onSelect: () => onDecide({ action: 'unknown' }),
            },
            {
              label: '几个人混在一起',
              onSelect: () => onDecide({ action: 'mixed' }),
            },
          ]}
          onSubmit={() => {
            // The prefilled guess is answered by its id: a name can be shared by two people.
            if (sure && (!typed || typed === likely.name))
              onDecide({ action: 'confirm', person_id: likely.person_id });
            else if (match)
              onDecide({ action: 'confirm', person_id: match.id });
            else if (typed) onDecide({ action: 'confirm', new_person: typed });
          }}
        />
      }
    >
      {(guesses.length > 0 || hearable) && (
        <Row gap={2} wrap>
          {guesses.map((guess) => (
            <Chip
              key={guess.id}
              disabled={busy}
              onClick={() =>
                onDecide(
                  guess.id === 'new'
                    ? { action: 'confirm', new_person: guess.name }
                    : { action: 'confirm', person_id: guess.id },
                )
              }
            >
              是{guess.name}
            </Chip>
          ))}
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
        </Row>
      )}
    </TaskRow>
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

/** Adding a person by hand: asked in a small dialog, so the people list keeps its place. */
function AddPerson({
  open,
  onClose,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (open) {
      setName('');
      setError('');
    }
  }, [open]);
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => !value && onClose()}
      title="添加人物"
    >
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (!name.trim()) return;
          setBusy(true);
          onAdd(name.trim())
            .then(onClose, (failure) =>
              setError(failure instanceof Error ? failure.message : '没能添加'),
            )
            .finally(() => setBusy(false));
        }}
      >
        <Field id="new-person-name" label="名字" error={error || undefined}>
          <Input
            id="new-person-name"
            maxLength={40}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Row gap={2} justify="end">
          <Button type="button" variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" loading={busy} disabled={!name.trim()}>
            添加
          </Button>
        </Row>
      </form>
    </Dialog>
  );
}

/** One person found in the meetings: who they are and what their twin is, with the one thing to do next. */
function PersonCard({
  person,
  twin,
  busy,
  onOpen,
  onEdit,
  onAddress,
  onRemove,
}: {
  person: Person;
  twin?: Persona;
  busy: boolean;
  onOpen: (personaId: string, page: '/chat' | '/profile') => void;
  onEdit: () => void;
  onAddress: () => void;
  onRemove: () => void;
}) {
  const lacking =
    person.seconds > 0 && (person.lacking ?? 0) >= 60
      ? `素材还差约 ${minutes(person.lacking ?? 0)}`
      : '';
  return (
    <Card as="li" variant="outline" className="flex flex-col gap-4">
      <Row gap={2}>
        <Stack gap={0} grow>
          <IdentityLink
            to={person.persona_id ? '/profile' : undefined}
            label={
              person.persona_id ? `${person.name}的档案` : `编辑${person.name}`
            }
            onClick={() =>
              person.persona_id
                ? onOpen(person.persona_id, '/profile')
                : onEdit()
            }
          >
            <AvatarFrame>
              <PersonFace person={person} twin={twin} />
            </AvatarFrame>
            <Stack gap={0} grow>
              <Text size="lg" weight="semibold" truncate>
                {person.name}
              </Text>
              <Text size="sm" tone="secondary" truncate>
                {person.speakers} 段录音 · {minutes(person.seconds)}
              </Text>
            </Stack>
          </IdentityLink>
        </Stack>
        <PersonClip person={person} icon />
      </Row>
      <Stack gap={1} align="start">
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
        <ClaimLine twin={twin} />
        {lacking && (
          <Text size="sm" tone="secondary">
            {lacking}
          </Text>
        )}
      </Stack>
      <div className="mt-auto flex gap-2">
        {person.self_claimed ? (
          // Their twin is theirs, not the library's to open: nothing to do here.
          <Button variant="secondary" className="flex-1" disabled>
            分身归 TA 自己
          </Button>
        ) : person.twin_elsewhere ? (
          <Button variant="secondary" className="flex-1" disabled>
            由建它的同事管理
          </Button>
        ) : person.persona_id ? (
          <Button
            className="flex-1"
            disabled={person.updating}
            onClick={() => onOpen(person.persona_id!, '/chat')}
          >
            {person.updating ? '整理完成后可以聊' : '和分身聊聊'}
          </Button>
        ) : person.can_manage === false ? null : (
          <Button
            variant="secondary"
            className="flex-1"
            disabled={busy || !person.speakers}
            onClick={onAddress}
          >
            生成分身
          </Button>
        )}
        {person.can_manage !== false && (
          <ActionMenu
            label={`更多：${person.name}`}
            items={[
              { label: '编辑名字和性别', disabled: busy, onSelect: onEdit },
              ...(person.persona_id && twin?.claimed === false
                ? [
                    {
                      label: '企业邮箱或工号',
                      disabled: busy,
                      onSelect: onAddress,
                    },
                  ]
                : []),
              ...(!person.persona_id &&
              !person.self_claimed &&
              !person.twin_elsewhere
                ? [{ label: '删除', disabled: busy, onSelect: onRemove }]
                : []),
            ]}
          />
        )}
      </div>
    </Card>
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
  const [fragments, setFragments] = useState<Fragment[]>([]);
  const [unsorted, setUnsorted] = useState<Unsorted[]>([]);
  const [suspects, setSuspects] = useState<SuspectSpeaker[]>([]);
  const [reviewing, setReviewing] = useState<SuspectSpeaker | null>(null);
  const [heard, setHeard] = useState<Review['heard']>();
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Person | null>(null);
  const [addressing, setAddressing] = useState<Person | null>(null);
  const [batching, setBatching] = useState(false);
  const [adding, setAdding] = useState(false);
  const [voicesShown, setVoicesShown] = useState(VOICES_PER_PAGE);
  const taskList = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const [focusPending, setFocusPending] = useState<string | null>(
    location.state?.resolvedTeamTask ?? null,
  );
  // Back from settling a speaker in its recording: the tab and the kind of task it was part of.
  const returnedFrom: string | undefined = location.state?.resolvedTeamTask;
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
      setSuspects(queue.suspects ?? []);
      setHeard(queue.heard);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法加载人物');
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load, version]);
  const updating = !!people?.some((p) => p.updating);
  // A twin's memory takes minutes to rebuild: every few seconds would only load the server, many pages at once.
  usePolling(load, updating ? 15000 : 0);

  // Where on screen the row being settled was: the next task, sliding into its place, is taken up there.
  const settledAt = useRef<number | null>(null);
  const act = async (work: () => Promise<unknown>, task?: string) => {
    setBusy(true);
    setError('');
    const row =
      task && document.activeElement instanceof HTMLElement
        ? document.activeElement.closest('li')
        : null;
    settledAt.current =
      row && taskList.current?.contains(row)
        ? row.getBoundingClientRect().top
        : null;
    try {
      await work();
      if (task) setFocusPending(task);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败');
    }
    await load();
    setBusy(false);
  };
  const add = async (value: string) => {
    await api('/api/library/people', { method: 'POST', json: { name: value } });
    await load();
  };
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
  // Whoever was heard longest first: the people with the most recorded speech make the fullest twins. Equal
  // ones keep the server's order by name.
  const named = people
    ?.filter(
      (p) =>
        !p.auto && (p.can_manage !== false || p.persona_id || p.self_claimed),
    )
    .sort((a, b) => b.seconds - a.seconds);
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
  // Fragments by the person they sound like, most first: given to them in one click, without becoming voice samples.
  const fragmentsLike = [
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
  // Whoever speaks longest first, a new person or a voice alike: settling them teaches a twin the most.
  const voiced = [
    ...unnamed.map((person) => ({
      id: `person-${person.id}`,
      seconds: person.seconds,
      enough: false,
      stranger: false,
      person,
    })),
    ...voices.map((voice) => ({
      id: `voice-${voice.id}`,
      seconds: voice.seconds,
      enough: Boolean(voice.enough),
      stranger: Boolean(voice.stranger),
      voice,
    })),
  ].sort(
    // Whoever a twin still lacks first, then the longest; voices like one already marked 不认识 wait last.
    (a, b) =>
      Number(a.stranger) - Number(b.stranger) ||
      Number(a.enough) - Number(b.enough) ||
      b.seconds - a.seconds,
  );
  // The longest are asked first; the rest wait behind "see more", and those that can wait (a twin is already
  // possible, or they sound like a stranger) are folded away.
  const mainVoices = voiced.filter((v) => !v.enough && !v.stranger);
  const enoughVoices = voiced.filter((v) => v.enough && !v.stranger);
  const strangerVoices = voiced.filter((v) => v.stranger);
  const shownVoices = mainVoices.slice(0, voicesShown);
  const laterVoices = mainVoices.slice(voicesShown);
  const taskIds = [
    ...voiced.map((v) => v.id),
    ...suspects.map((m) => `mixed-${m.recording_id}-${m.speaker_id}`),
    ...(fragments.length ? ['fragments'] : []),
    ...similar.map(([a, b]) => `similar-${a.id}-${b.id}`),
    ...waiting.map((w) => `speaker-${w.recording_id}-${w.id}`),
    ...unsorted.map((u) => `unsorted-${u.recording_id}`),
    ...failed.map((r) => `failed-${r.id}`),
    ...disowned.map((p) => `disowned-${p.id}`),
  ];
  const tasks = taskIds.length;
  const counts: Record<Category, number> = {
    voice: voiced.length,
    mixed: suspects.length,
    unsorted: unsorted.length,
    failed: failed.length,
    similar: similar.length,
    disputed: waiting.length,
    disowned: disowned.length,
    fragments: fragments.length ? 1 : 0,
  };
  const openCategories = CATEGORIES.filter((c) => counts[c.id] > 0);
  const tab: 'people' | 'todo' =
    params.get('tab') === 'todo' || returnedFrom ? 'todo' : 'people';
  const asked =
    params.get('cat') ?? (returnedFrom ? categoryOf(returnedFrom) : undefined);
  // The kind in the address, or the first that still has something, when it was settled in full.
  const category =
    openCategories.find((c) => c.id === asked) ?? openCategories[0];
  // Tab and kind live in the address, so a reload or the back button returns to them; other parameters stay.
  const go = useCallback(
    (change: Record<string, string | null>, state?: unknown) =>
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [key, value] of Object.entries(change))
            if (value === null) next.delete(key);
            else next.set(key, value);
          return next;
        },
        { replace: true, state },
      ),
    [setParams],
  );
  const wanted = returnedFrom ? categoryOf(returnedFrom) : undefined;
  useEffect(() => {
    if (!returnedFrom) return;
    if (
      params.get('tab') !== 'todo' ||
      (wanted && params.get('cat') !== wanted)
    )
      go({ tab: 'todo', ...(wanted ? { cat: wanted } : {}) }, location.state);
  }, [returnedFrom, wanted, params, go, location.state]);
  const pending =
    arriving.length + organising.length + proofreading.length + uploads.length;
  const taskOrder = taskIds.join('|');
  useEffect(() => {
    if (!focusPending || !people || busy) return;
    if (taskOrder.split('|').includes(focusPending)) return;
    // The next voice's name field before any button, so naming several is type, Enter, type, Enter: the one now
    // where the settled row was, so the page stays where the owner is working instead of jumping to the top.
    const top = settledAt.current;
    const at = (selector: string) => {
      const found = Array.from(
        taskList.current?.querySelectorAll<HTMLElement>(selector) ?? [],
      );
      return (
        (top === null
          ? undefined
          : found.find(
              (el) =>
                (el.closest('li') ?? el).getBoundingClientRect().top >= top - 1,
            )) ?? found[0]
      );
    };
    const next = at('input:not(:disabled)') ?? at('a, button:not(:disabled)');
    next?.focus({ preventScroll: true });
    settledAt.current = null;
    setFocusPending(null);
    if (location.state?.resolvedTeamTask)
      void navigate(`${location.pathname}${location.search}`, {
        replace: true,
        state: null,
      });
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
  // There is no call for all at once: the same retry for each, one after the other.
  const retryAll = () =>
    act(async () => {
      for (const recording of failed)
        await api(
          `/api/library/recordings/${encodeURIComponent(recording.id)}/retry`,
          { method: 'POST' },
        );
      await onReload?.();
    }, `failed-${failed[0]?.id}`);
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

  const voiceRow = (entry: (typeof voiced)[number]) =>
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
          void decideVoice(entry.voice.members, decision, entry.id)
        }
      />
    );
  const folded = (summary: string, rows: typeof voiced) =>
    rows.length > 0 && (
      <Disclosure
        summary={summary}
        variant="plain"
        defaultOpen={mainVoices.length === 0}
      >
        <Stack as="ul" gap={0}>
          {rows.map(voiceRow)}
        </Stack>
      </Disclosure>
    );
  const sum = (rows: typeof voiced) =>
    rows.reduce((total, row) => total + row.seconds, 0);
  const attention = (tone: 'warning' | 'danger' | 'info') => (
    <StatusDot tone={tone} />
  );

  // What the chosen kind of task shows, and the actions that settle all of its kind at once.
  let batch: ReactNode = null;
  let body: ReactNode = null;
  if (category?.id === 'voice') {
    body = (
      <>
        <Stack as="ul" gap={0} aria-label="新出现的声音">
          {shownVoices.map(voiceRow)}
        </Stack>
        {laterVoices.length > 0 && (
          <Row gap={3} justify="between" wrap>
            <Text size="sm" tone="secondary">
              还有 {laterVoices.length} 个说得更少（共 {span(sum(laterVoices))}
              ）
            </Text>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setVoicesShown((n) => n + VOICES_PER_PAGE)}
            >
              再看 {Math.min(VOICES_PER_PAGE, laterVoices.length)} 个
            </Button>
          </Row>
        )}
        {folded(`${enoughVoices.length} 个像已经够建分身的人`, enoughVoices)}
        {folded(`${strangerVoices.length} 个像你标过不认识的`, strangerVoices)}
        <Row gap={2} wrap>
          <Text size="sm" tone="secondary">
            认不出的人，可以请本人来认：登录后录一句话，系统会找出哪些是 TA 说的
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
      </>
    );
  } else if (category?.id === 'mixed') {
    body = (
      <Stack as="ul" gap={0}>
        {suspects.map((m) => (
          <TaskRow
            key={`mixed-${m.recording_id}-${m.speaker_id}`}
            leading={attention('warning')}
            title={`${m.name} · ${m.filename} · ${m.speaker_id}`}
            meta={`${m.open} 段（${span(m.open_seconds)}）听起来不像${m.name}，占这个声音的 ${Math.round(m.share * 100)}%`}
            hint={
              m.likely_name
                ? `多数像${m.likely_name}`
                : '多数不像团队里的任何人'
            }
            actions={
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={() => setReviewing(m)}
              >
                逐段试听
              </Button>
            }
          />
        ))}
      </Stack>
    );
  } else if (category?.id === 'unsorted') {
    body = (
      <Stack as="ul" gap={0}>
        {unsorted.map((u) => (
          <TaskRow
            key={`unsorted-${u.recording_id}`}
            leading={attention('warning')}
            title={u.filename}
            meta={
              u.speakers === u.total
                ? `${u.speakers} 位说话人待确认`
                : `还有 ${u.speakers} 位没认`
            }
            actions={
              <RouteButton
                to={recordingPath(u.recording_id)}
                state={{ teamTask: `unsorted-${u.recording_id}` }}
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
  } else if (category?.id === 'failed') {
    batch = failed.length > 1 && (
      <Button
        variant="secondary"
        size="sm"
        disabled={busy}
        onClick={() => void retryAll()}
      >
        全部重试
      </Button>
    );
    body = (
      <Stack as="ul" gap={0}>
        {failed.map((r) => (
          <TaskRow
            key={r.id}
            leading={attention('danger')}
            title={r.filename}
            meta={r.error || undefined}
            actions={
              <>
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
              </>
            }
          />
        ))}
      </Stack>
    );
  } else if (category?.id === 'similar') {
    body = (
      <Stack as="ul" gap={0}>
        {similar.map(([a, b]) => (
          <TaskRow
            key={`similar-${a.id}-${b.id}`}
            leading={attention('info')}
            title={`${a.name} 和 ${b.name}`}
            meta={`${a.speakers} 段录音 · ${b.speakers} 段录音`}
            actions={
              <>
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
              </>
            }
          />
        ))}
      </Stack>
    );
  } else if (category?.id === 'disputed') {
    body = (
      <Stack as="ul" gap={0}>
        {waiting.map((w) => (
          <TaskRow
            key={`${w.recording_id}-${w.id}`}
            leading={attention('warning')}
            title={`${w.filename} · ${w.id}`}
            meta="原来标成的人说这不是 TA"
            actions={
              <RouteButton
                to={recordingPath(w.recording_id, w.id)}
                state={{ teamTask: `speaker-${w.recording_id}-${w.id}` }}
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
  } else if (category?.id === 'disowned') {
    body = (
      <Stack as="ul" gap={0}>
        {disowned.map((p) => (
          <TaskRow
            key={`disowned-${p.id}`}
            leading={attention('danger')}
            title={p.name}
            meta={`${twinOf(p)?.claim_rejected} 说这不是 TA`}
            actions={
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={() => setAddressing(p)}
              >
                换个邮箱或工号
              </Button>
            }
          />
        ))}
      </Stack>
    );
  } else if (category?.id === 'fragments') {
    batch = (
      <>
        {fragmentsLike.slice(0, 3).map(({ person, members }) => (
          <Button
            key={person.person_id}
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() =>
              void decideVoice(
                members,
                {
                  action: 'confirm',
                  person_id: person.person_id,
                  sample: false,
                },
                'fragments',
              )
            }
          >
            {members.length} 段像{person.name}：都是{person.name}
          </Button>
        ))}
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          onClick={() =>
            void decideVoice(fragments, { action: 'unknown' }, 'fragments')
          }
        >
          都放一边
        </Button>
      </>
    );
    body = (
      <Stack as="ul" gap={0}>
        <TaskRow
          leading={attention('info')}
          title={`${fragmentRecordings} 段录音里有 ${fragments.length} 段很短的声音`}
          meta={`共 ${span(fragments.reduce((total, m) => total + m.seconds, 0))}${fragmentsLike.length === 0 ? '，不像任何人' : ''}`}
        />
      </Stack>
    );
  }

  const processing = pending > 0 && (
    <Section label="正在处理" gap={2}>
      <Text size="sm" weight="medium">
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
  );

  const peopleTab = (
    <Stack gap={5}>
      {tasks > 0 && (
        <Notice
          tone="warning"
          actions={
            <Button variant="secondary" onClick={() => go({ tab: 'todo' })}>
              去处理
            </Button>
          }
        >
          {tasks} 项待处理。认出更多说话人，分身的素材才会更足。
        </Notice>
      )}
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
            <PersonCard
              key={person.id}
              person={person}
              twin={twinOf(person)}
              busy={busy}
              onOpen={(personaId, page) => void open(personaId, page)}
              onEdit={() => setEditing(person)}
              onAddress={() => setAddressing(person)}
              onRemove={() => void remove(person)}
            />
          ))}
      </Grid>
      <Row gap={3} justify="between" wrap>
        <Text size="sm" tone="secondary">
          {[
            organising.length > 0 &&
              `${organising.map((p) => p.name).join('、')} · 整理记忆中，完成后可以聊`,
            pending > organising.length &&
              `${pending - organising.length} 项录音正在处理`,
          ]
            .filter(Boolean)
            .join(' · ')}
        </Text>
        <TextLink to="/library">全部录音（{recordings.length}）</TextLink>
      </Row>
    </Stack>
  );
  const todoTab =
    tasks === 0 || !category ? (
      <Stack gap={4}>
        <Text tone="secondary">现在没有需要你处理的事。</Text>
        {processing}
      </Stack>
    ) : (
      <SideTabs
        label="待处理类别"
        value={category.id}
        onValueChange={(value) => go({ cat: value })}
        aside={processing}
        groups={[
          {
            label: '待处理类别',
            items: openCategories.map((c) => ({
              value: c.id,
              label: (
                <Row gap={2} as="div">
                  <StatusDot tone={c.tone} />
                  {c.label}
                </Row>
              ),
              trailing: (
                <Text as="span" size="sm" tone="secondary">
                  {counts[c.id]}
                </Text>
              ),
            })),
          },
        ]}
      >
        <Section
          framed
          level={3}
          title={category.label}
          badge={
            <Text as="span" size="sm" tone="secondary">
              {counts[category.id]}
            </Text>
          }
          description={category.help}
          actions={
            batch ? (
              <Row gap={2} wrap>
                {batch}
              </Row>
            ) : undefined
          }
        >
          <Stack ref={taskList} gap={4}>
            {body}
          </Stack>
        </Section>
      </SideTabs>
    );

  return (
    <>
      {error && (
        <Text role="alert" tone="danger">
          {error}
        </Text>
      )}
      <Tabs
        label="团队"
        value={tab}
        onValueChange={(value) =>
          go({ tab: value === 'todo' ? 'todo' : null, cat: null })
        }
        actions={
          tab === 'people' ? (
            <Row gap={2} wrap>
              <Input
                aria-label="找人"
                placeholder="找人"
                className="w-36"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              {toAddress.length > 0 && (
                <Button variant="secondary" onClick={() => setBatching(true)}>
                  按邮箱或工号建分身（{toAddress.length}）
                </Button>
              )}
              <Button variant="secondary" onClick={() => setAdding(true)}>
                添加人物
              </Button>
            </Row>
          ) : (
            heard &&
            heard.total > 0 && (
              <div className="w-64">
                <Meter
                  size="sm"
                  value={heard.settled}
                  max={heard.total}
                  label="已知是谁说的发言"
                />
              </div>
            )
          )
        }
        items={[
          {
            value: 'people',
            label: (
              <Row gap={2} as="div">
                人物
                <Text as="span" size="sm" tone="inherit">
                  {named?.length ?? 0}
                </Text>
              </Row>
            ),
            content: peopleTab,
          },
          {
            value: 'todo',
            label: (
              <Row gap={2} as="div">
                待处理
                {tasks > 0 && <Badge tone="warning">{tasks}</Badge>}
              </Row>
            ),
            content: todoTab,
          },
        ]}
      />
      <AddPerson open={adding} onClose={() => setAdding(false)} onAdd={add} />
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
      <MixedSpeaker
        suspect={reviewing}
        onClose={() => setReviewing(null)}
        onChanged={load}
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
