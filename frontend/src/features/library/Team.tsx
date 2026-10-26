import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { AudioLines, IdCard, Pencil, Trash2 } from 'lucide-react';
import {
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
} from 'react-router';
import {
  ActionMenu,
  IdentityLink,
  AvatarFrame,
  Button,
  Chip,
  toast,
  Dialog,
  Field,
  Input,
  ListRow,
  LoadMore,
  Notice,
  Radio,
  Row,
  Stack,
  StatusDot,
  Tabs,
  Table,
  Text,
  TextLink,
  type TextTone,
  type Tone,
  useConfirm,
} from '../../components/ui';
import { PersonFace } from './PersonFace';
import { api } from '../../lib/api';
import { byName } from '../../lib/names';
import { chatPath, memberPath, twinMemberPath } from '../../lib/members';
import { useAuth } from '../../stores/auth';
import { usePersonas, type Persona } from '../../stores/personas';
import { useNewTwinCard } from '../../components/layout/NewTwin';
import type { Recording } from '../../pages/Library';
import type { Gender, Person, TwinMatch } from '../../pages/Recording';
import { PersonVoice } from './PersonVoice';
import {
  VoiceClashes,
  type ClashSample,
  type VoiceClash,
} from './VoiceClashes';
import { WorkClaim } from './WorkClaim';
import { BuildMeter } from '../memories/BuildProgress';
import { minutes } from './review';
import { useTeamData } from './useTeamData';
import { deletable, useDeleteTwin } from '../profile/useDeleteTwin';
import { looseTwins, namedPeople } from './teamCounts';

/** A twin deleted in the last days, which can still be brought back. */
interface Trashed {
  id: string;
  name: string;
  deleted_at: string;
  expires_at: string;
}

// Keep the full roster for search and batch actions; mount the table a page at a time.
const PEOPLE_PER_PAGE = 18;

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
      body="填邮箱或工号，不知道就空着。"
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
                    placeholder="邮箱或工号"
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

/** What is worth a line under a name: that a colleague sent the twin back or the twin waits for its person to sign in,
 * else who they are in their own words (``about``), else that the twin is theirs. */
function ClaimLine({ twin, about }: { twin?: Persona; about?: string | null }) {
  const [label, tone]: [string, TextTone] | [null, null] =
    twin?.claimed === false && twin.claim_rejected
      ? [`${twin.claim_rejected} 说不是 TA，换一个`, 'danger']
      : twin?.claimed === false && twin.claim
        ? [`等 ${twin.claim} 登录认领`, 'secondary']
        : about
          ? [about, 'secondary']
          : twin?.claimed
            ? ['本人已认领', 'success']
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

/** A row of the team table: someone found in the meetings, or a twin no meeting belongs to. */
type TeamEntry = { key: string; name: string; state: TwinState } & (
  { person: Person } | { twin: Persona }
);

/** Why a twin's memory update stopped without completing, or null while it goes on or is done. */
const stalledBuild = (person: Person) =>
  person.updating && !person.held && person.build?.state === 'idle'
    ? (person.build.last_error ?? null)
    : null;

/** When a stopped update is tried again by itself, as a local clock time. */
const retryClock = (at: string) =>
  new Date(at).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });

/** Where a person's twin stands, as the team table's filter and status column name it. ``behind``: new recordings
 * wait while it answers from the memory it has; ``held``: the administrator switched the automatic rebuild off;
 * ``stalled``: its update stopped without completing; ``waiting``: a twin with nothing to learn from yet (made by
 * hand, or for someone who just signed in), which has nothing to answer with until a recording or note is added. */
export type TwinState =
  | 'ready'
  | 'waiting'
  | 'behind'
  | 'updating'
  | 'held'
  | 'stalled'
  | 'none'
  | 'own'
  | 'elsewhere';
export const twinState = (person: Person): TwinState =>
  person.self_claimed
    ? 'own'
    : person.twin_elsewhere && !person.talk
      ? 'elsewhere'
      : person.persona_id || person.talk
        ? stalledBuild(person)
          ? 'stalled'
          : person.answers_behind
            ? 'behind'
            : person.held
              ? 'held'
              : person.updating
                ? 'updating'
                : 'ready'
        : 'none';
export const TWIN_STATES: Record<TwinState, { label: string; tone: Tone }> = {
  ready: { label: '可以聊', tone: 'success' },
  waiting: { label: '等录音', tone: 'neutral' },
  behind: { label: '有新录音', tone: 'neutral' },
  updating: { label: '整理中', tone: 'warning' },
  held: { label: '整理已暂停', tone: 'warning' },
  stalled: { label: '更新没完成', tone: 'danger' },
  none: { label: '没有分身', tone: 'neutral' },
  own: { label: '本人已认领', tone: 'success' },
  elsewhere: { label: '同事建了分身', tone: 'neutral' },
};
// The filters over the table (each only while someone is in it); the two kinds managed elsewhere show under 全部.
const TWIN_FILTERS: TwinState[] = [
  'ready',
  'waiting',
  'behind',
  'updating',
  'held',
  'stalled',
  'none',
];

/** A meeting's day as the table's 最近 column says it: 10月15日. */
const meetingDay = (date: string) => {
  const [, month, day] = date.split('-');
  return `${Number(month)}月${Number(day)}日`;
};

/** The latest meeting someone was heard in, or nothing. */
function Recent({ person }: { person: Person }) {
  return (
    <Text size="sm" tone="secondary" truncate>
      {person.last_meeting
        ? `${meetingDay(person.last_meeting.date)} ${person.last_meeting.title}`
        : '—'}
    </Text>
  );
}

/** One person found in the meetings, as a row of the team table: who they are, how much of them was recorded, where
 * their twin stands, and the one thing to do next with the rest in “⋯”. */
function personRow({
  person,
  twin,
  busy,
  onOpen,
  onMember,
  onEdit,
  admin,
  onAddress,
  onRemove,
  onDeleteTwin,
  onVoice,
  onRebuild,
}: {
  person: Person;
  twin?: Persona;
  busy: boolean;
  /** An administrator can point a twin its person has taken at someone else, or at nobody. */
  admin: boolean;
  /** Talk to their twin: switch to it and open the chat. */
  onOpen: (personaId: string) => void;
  /** Their page: the recordings they are in, and their twin if they have one. */
  onMember: () => void;
  onEdit: () => void;
  onAddress: () => void;
  onRemove: () => void;
  /** Delete their twin, which waits a week in the trash. */
  onDeleteTwin: (twin: Persona) => void;
  /** Their voice samples, and what voice alone gave them, to spot-check. */
  onVoice: () => void;
  /** Build their twin again now: its update stopped, or the switched-off automatic rebuild holds it. */
  onRebuild: () => void;
}): ReactNode[] {
  const state = twinState(person);
  const lacking =
    person.seconds > 0 && (person.lacking ?? 0) >= 60
      ? `素材还差约 ${minutes(person.lacking ?? 0)}`
      : '';
  const checks =
    person.can_manage !== false && (person.checks ?? 0) > 0
      ? (person.checks ?? 0)
      : 0;
  return [
    <IdentityLink
      key="who"
      to={memberPath(person.id)}
      label={`${person.name}的成员页`}
      onClick={onMember}
    >
      <AvatarFrame>
        <PersonFace name={person.name} twin={twin} />
      </AvatarFrame>
      <Stack gap={0} grow>
        <Text weight="semibold" truncate>
          {person.name}
        </Text>
        <ClaimLine twin={twin} about={person.about} />
      </Stack>
    </IdentityLink>,
    <Text key="heard" size="sm" tone="secondary">
      {person.speakers > 0
        ? `${person.speakers} 段 · ${minutes(person.seconds)}`
        : '—'}
    </Text>,
    <Stack key="twin" gap={1}>
      <Row gap={2}>
        <StatusDot tone={TWIN_STATES[state].tone} />
        <Text
          size="sm"
          title={state === 'stalled' ? (stalledBuild(person) ?? '') : undefined}
        >
          {TWIN_STATES[state].label}
        </Text>
      </Row>
      {state === 'stalled' && person.build?.retry_at && (
        <Text size="sm" tone="secondary">
          约 {retryClock(person.build.retry_at)} 自动重试
        </Text>
      )}
      {state === 'updating' && (
        // The twin can talk once its memory is updated: where the update is, under the word.
        <div aria-live="polite">
          <BuildMeter processing={person.build} />
        </div>
      )}
      {lacking && (
        <Text size="sm" tone="secondary">
          {lacking}
        </Text>
      )}
    </Stack>,
    <Recent key="recent" person={person} />,
    <Row key="act" gap={1} justify="end">
      {state === 'ready' || state === 'behind' ? (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onOpen((person.persona_id ?? person.talk)!)}
        >
          聊天
        </Button>
      ) : (state === 'held' || state === 'stalled') && person.persona_id ? (
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={onRebuild}
        >
          {state === 'held' ? '立即整理' : '重试'}
        </Button>
      ) : state === 'none' && person.can_manage !== false ? (
        <Button
          size="sm"
          variant="secondary"
          disabled={busy || !person.speakers}
          onClick={onAddress}
        >
          生成分身
        </Button>
      ) : (
        <Button size="sm" variant="secondary" onClick={onMember}>
          查看
        </Button>
      )}
      {person.can_manage !== false && (
        <ActionMenu
          label={`${person.name}的更多操作`}
          items={[
            // Waiting for the switched-off automatic rebuild, though it answers meanwhile.
            ...(state === 'behind' && person.held
              ? [{ label: '立即整理', disabled: busy, onSelect: onRebuild }]
              : []),
            {
              label: '编辑资料',
              icon: Pencil,
              disabled: busy,
              onSelect: onEdit,
            },
            // Nothing was heard of someone made by hand: no voice to hear or check.
            ...(person.speakers > 0
              ? [
                  {
                    label: '抽查声线',
                    icon: AudioLines,
                    count: checks,
                    disabled: busy,
                    onSelect: onVoice,
                  },
                ]
              : []),
            ...(person.persona_id &&
            (twin?.claimed === false || (admin && twin?.claimed))
              ? [
                  {
                    label: twin.claimed ? '改绑企业账号' : '绑定企业账号',
                    icon: IdCard,
                    // Given one nobody has signed in with yet, it waits for them; none given, it is not bound.
                    status: twin.claimed
                      ? '已认领'
                      : twin.claim
                        ? '待认领'
                        : '未绑定',
                    disabled: busy,
                    onSelect: onAddress,
                  },
                ]
              : []),
            ...(twin && deletable(twin)
              ? [
                  {
                    label: '删除分身',
                    icon: Trash2,
                    danger: true,
                    disabled: busy,
                    onSelect: () => onDeleteTwin(twin),
                  },
                ]
              : []),
            ...(!person.persona_id &&
            !person.self_claimed &&
            !person.twin_elsewhere
              ? [
                  {
                    label: '删除成员',
                    icon: Trash2,
                    danger: true,
                    disabled: busy,
                    onSelect: onRemove,
                  },
                ]
              : []),
          ]}
        />
      )}
    </Row>,
  ];
}

/** Where a twin no recording belongs to stands: with nothing in it yet, it waits for a recording. */
export const looseState = (twin: Persona): TwinState =>
  twin.sources > 0 ? 'ready' : 'waiting';

/** A twin no recording belongs to (made by hand, or someone else's public one), as a row of the same table: it is
 * there to talk to and to open; an empty one only to open, to add what it learns from. */
function twinRow({
  twin,
  me,
  match,
  onOpen,
  onMember,
  onSame,
  onDelete,
}: {
  twin: Persona;
  /** The signed-in person's address, so only other people's twins name their owner. */
  me?: string | null;
  /** Someone in the meetings with this twin's name, whom its keeper may say it is. */
  match?: TwinMatch;
  onOpen: (personaId: string) => void;
  onMember: () => void;
  onSame: (match: TwinMatch, same: boolean) => void;
  /** Delete the twin, which waits a week in the trash. */
  onDelete: () => void;
}): ReactNode[] {
  const state = looseState(twin);
  const menu = [
    ...(match
      ? [
          { label: '是同一人', onSelect: () => onSame(match, true) },
          { label: '不是同一人', onSelect: () => onSame(match, false) },
        ]
      : []),
    ...(deletable(twin)
      ? [
          {
            label: '删除分身',
            icon: Trash2,
            danger: true,
            onSelect: onDelete,
          },
        ]
      : []),
  ];
  return [
    <IdentityLink
      key="who"
      to={twinMemberPath(twin.id)}
      label={`${twin.name}的成员页`}
      onClick={onMember}
    >
      <AvatarFrame>
        <PersonFace name={twin.name} twin={twin} />
      </AvatarFrame>
      <Stack gap={0} grow>
        <Text weight="semibold" truncate>
          {twin.name}
        </Text>
        {match ? (
          <Text size="sm" tone="secondary" truncate>
            会议里有同名的人
          </Text>
        ) : (
          twin.owner &&
          twin.owner !== me && (
            <Text size="sm" tone="secondary" truncate title={twin.owner}>
              {twin.owner}
            </Text>
          )
        )}
      </Stack>
    </IdentityLink>,
    <Text key="heard" size="sm" tone="secondary">
      —
    </Text>,
    <Row key="twin" gap={2}>
      <StatusDot tone={TWIN_STATES[state].tone} />
      <Text size="sm">{TWIN_STATES[state].label}</Text>
    </Row>,
    <Text key="recent" size="sm" tone="secondary">
      —
    </Text>,
    <Row key="act" gap={1} justify="end">
      {state === 'ready' ? (
        <Button size="sm" variant="secondary" onClick={() => onOpen(twin.id)}>
          聊天
        </Button>
      ) : (
        <Button size="sm" variant="secondary" onClick={onMember}>
          查看
        </Button>
      )}
      {menu.length > 0 && (
        <ActionMenu
          label={
            match ? `${twin.name}是不是会议里的人` : `${twin.name}的更多操作`
          }
          items={menu}
        />
      )}
    </Row>,
  ];
}

/** The old address of the inbox, a tab of the team page (``?tab=todo``), leads to ``/inbox``; anything else shows
 * what is inside. It is kept apart from the roster so a page around it can lead there before it has loaded. */
export function LegacyTodo({ children }: { children: ReactNode }) {
  const [params] = useSearchParams();
  const location = useLocation();
  if (params.get('tab') !== 'todo') return children;
  const cat = params.get('cat');
  return (
    <Navigate
      to={`/inbox${cat ? `?cat=${encodeURIComponent(cat)}` : ''}`}
      replace
      state={location.state}
    />
  );
}

/**
 * The team's people, each with their twin. What waits to be settled is the inbox (``/inbox``): the old address of
 * its tab leads there.
 */
export function Team(props: {
  version: number;
  recordings: Recording[];
  onReload?: () => Promise<void>;
  /** Show nothing while no one is there to list and nothing was deleted: a page around it has the empty state. */
  quietWhenEmpty?: boolean;
}) {
  return (
    <LegacyTodo>
      <Roster {...props} />
    </LegacyTodo>
  );
}

function Roster({
  version,
  recordings,
  onReload,
  quietWhenEmpty = false,
}: {
  version: number;
  recordings: Recording[];
  onReload?: () => Promise<void>;
  quietWhenEmpty?: boolean;
}) {
  const {
    people,
    matches,
    sameTwin,
    peopleError,
    error,
    busy,
    act,
    load,
    saveClaim,
    rebuild,
    merge,
  } = useTeamData({ version, onReload });
  const [hearing, setHearing] = useState<Person | null>(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<TwinState | null>(null);
  const [editing, setEditing] = useState<Person | null>(null);
  const [addressing, setAddressing] = useState<Person | null>(null);
  // Why the e-mail or employee number was not saved: the dialog stays open with it, and what was typed.
  const [claimError, setClaimError] = useState('');
  const address = (person: Person | null) => {
    setClaimError('');
    setAddressing(person);
  };
  const [batching, setBatching] = useState(false);
  const [adding, setAdding] = useState(false);
  const [peopleShown, setPeopleShown] = useState(PEOPLE_PER_PAGE);
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  // Someone looked up by name (⌘K) who has no twin to open: the roster, narrowed to them.
  const sought: string | undefined = location.state?.search;
  useEffect(() => {
    if (!sought) return;
    setSearch(sought);
    setFilter(null);
  }, [sought, location.key]);
  const confirm = useConfirm();
  const navigate = useNavigate();
  const refreshPersonas = usePersonas((state) => state.refresh);
  const twins = usePersonas((state) => state.items);
  const identity = useAuth((state) => state.identity);
  const newTwin = useNewTwinCard((state) => state.set);
  // Administrators hear people whose voice samples sound nearly alike (a sample given wrongly, or one person twice).
  const admin = !!identity?.admin;
  const [clashes, setClashes] = useState<VoiceClash[]>([]);
  const [checkingClashes, setCheckingClashes] = useState(false);
  const loadClashes = useCallback(async () => {
    if (!admin) return;
    try {
      const found = await api<VoiceClash[]>('/api/library/voice-clashes');
      if (Array.isArray(found)) setClashes(found);
    } catch {
      // A side matter: the roster does not wait for it.
    }
  }, [admin]);
  useEffect(() => {
    void loadClashes();
  }, [loadClashes, version]);
  const mergeClash = async (clash: VoiceClash) => {
    const [a, b] = clash.samples.map((s) =>
      people?.find((p) => p.id === s.person_id),
    );
    if (!a || !b) return;
    const failed = await merge(a, b);
    if (!failed) toast(`已合并${a.name}和${b.name}`, 'success');
    await loadClashes();
  };
  const removeClashSample = async (sample: ClashSample) => {
    if (
      !(await confirm({
        title: `移除${sample.name}的这段声线？`,
        body: '靠它认出的发言会退回待处理，再按声音重新认一遍',
        confirmLabel: '移除',
        tone: 'danger',
      }))
    )
      return;
    const result: { done?: { returned: number; recognised: number } } = {};
    await act(async () => {
      result.done = await api<{ returned: number; recognised: number }>(
        '/api/library/voice-clashes/remove',
        { method: 'POST', json: { sample_id: sample.id } },
      );
    });
    if (result.done) {
      const { returned, recognised } = result.done;
      toast(
        recognised
          ? `已移除，新认出 ${recognised} 段`
          : returned
            ? `已移除，${returned} 段退回待处理`
            : '已移除',
        'success',
      );
    }
    await loadClashes();
  };
  const apartClash = async (clash: VoiceClash) => {
    await act(
      () =>
        api('/api/library/voice-clashes/apart', {
          method: 'POST',
          json: { samples: clash.samples.map((s) => s.id) },
        }),
      { reload: false },
    );
    await loadClashes();
  };
  // What an action on a row could not do reaches the person where they are, not at the top of a long table.
  useEffect(() => {
    if (error) toast(error, 'danger', 8000);
  }, [error]);
  const [trash, setTrash] = useState<Trashed[]>([]);
  const loadTrash = useCallback(async () => {
    try {
      const entries = await api<Trashed[]>('/api/personas/trash');
      if (Array.isArray(entries)) setTrash(entries);
    } catch {
      // The deleted twins are a side matter: the roster does not wait for them.
    }
  }, []);
  useEffect(() => {
    void loadTrash();
  }, [loadTrash]);
  const deleteTwin = useDeleteTwin();
  // A twin deleted or brought back changes its row and the deleted tab.
  const reloadAll = async () => {
    await Promise.all([load(), loadTrash()]);
  };

  const restore = (entry: Trashed) =>
    act(async () => {
      await api(`/api/personas/${encodeURIComponent(entry.id)}/restore`, {
        method: 'POST',
      });
      await refreshPersonas();
      await loadTrash();
      toast(`已恢复「${entry.name}」`, 'success');
    });
  const add = async (value: string) => {
    await api('/api/library/people', { method: 'POST', json: { name: value } });
    await load();
  };
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
  // Talking to someone's twin: its chat, which switches to it and lists its conversations.
  const chat = (personaId: string) => void navigate(chatPath(personaId));

  // The team's roster holds everyone; this page shows the people the viewer looks after or can talk to.
  // Whoever was heard longest first: the people with the most recorded speech make the fullest twins. Equal
  // ones keep the server's order by name.
  const named =
    people && namedPeople(people).sort((a, b) => b.seconds - a.seconds);
  // Twins no recording belongs to (made by hand, someone else's public one) are rows of the same table, after the
  // people found in the meetings.
  const loose = people
    ? looseTwins(people, twins).sort((a, b) => byName(a.name, b.name))
    : [];
  const entries: TeamEntry[] | null = named && [
    ...named.map((person) => ({
      key: `person-${person.id}`,
      name: person.name,
      state: twinState(person),
      person,
    })),
    ...loose.map((twin) => ({
      key: `twin-${twin.id}`,
      name: twin.name,
      state: looseState(twin),
      twin,
    })),
  ];
  // A filter nobody is in any more (the last one retried is updating now) lets go instead of showing nothing.
  const filterGone =
    !!filter && !!entries && !entries.some((entry) => entry.state === filter);
  useEffect(() => {
    if (filterGone) setFilter(null);
  }, [filterGone]);
  const activeFilter = filterGone ? null : filter;
  const matchingPeople = entries?.filter(
    (entry) =>
      (!activeFilter || entry.state === activeFilter) &&
      entry.name
        .toLocaleLowerCase()
        .includes(search.trim().toLocaleLowerCase()),
  );
  const twinOf = (person: Person) =>
    twins.find((t) => t.id === person.persona_id);
  const toAddress = named?.filter((p) => unaddressed(p, twinOf(p))) ?? [];
  const tab: 'people' | 'trash' =
    params.get('tab') === 'trash' ? 'trash' : 'people';
  // The tab lives in the address, so a reload or the back button returns to it; other parameters stay.
  const go = (change: Record<string, string | null>) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(change))
          if (value === null) next.delete(key);
          else next.set(key, value);
        return next;
      },
      { replace: true },
    );
  const peopleTab = (
    <Stack gap={5}>
      {admin && clashes.length > 0 && (
        <Notice
          tone="info"
          actions={
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setCheckingClashes(true)}
            >
              核对
            </Button>
          }
        >
          {clashes.length} 对成员的声线几乎一样
        </Notice>
      )}
      {people === null && !peopleError && (
        <Text role="status" tone="secondary">
          正在加载人物…
        </Text>
      )}
      {entries && entries.length === 0 && (
        <Text size="sm" tone="secondary">
          录音转写后，认出来的人会出现在这里；也可以打开录音，确认说话人是谁。
        </Text>
      )}
      {entries && entries.length > 0 && (
        <Row gap={2} wrap>
          <Input
            aria-label="找人"
            placeholder="找人"
            className="w-48"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPeopleShown(PEOPLE_PER_PAGE);
            }}
          />
          <Row gap={2} wrap role="group" aria-label="按分身状态筛选">
            {([null, ...TWIN_FILTERS] as const).map((state) => {
              const count = state
                ? entries.filter((e) => e.state === state).length
                : entries.length;
              return (
                (!state || count > 0) && (
                  <Chip
                    key={state ?? 'all'}
                    pressed={activeFilter === state}
                    onClick={() => {
                      setFilter(state);
                      setPeopleShown(PEOPLE_PER_PAGE);
                    }}
                  >
                    {state ? TWIN_STATES[state].label : '全部'} {count}
                  </Chip>
                )
              );
            })}
          </Row>
        </Row>
      )}
      {entries && entries.length > 0 && matchingPeople?.length === 0 && (
        <Text size="sm" tone="secondary">
          没有符合的人
        </Text>
      )}
      {matchingPeople && matchingPeople.length > 0 && (
        <Table
          caption="成员"
          headers={['成员', '录音', '分身', '最近', '操作']}
          scroll={false}
          rows={matchingPeople.slice(0, peopleShown).map((entry) =>
            'person' in entry
              ? personRow({
                  person: entry.person,
                  twin: twinOf(entry.person),
                  busy,
                  admin,
                  onOpen: chat,
                  onMember: () => void navigate(memberPath(entry.person.id)),
                  onEdit: () => setEditing(entry.person),
                  onAddress: () => address(entry.person),
                  onRemove: () => void remove(entry.person),
                  onDeleteTwin: (twin) => void deleteTwin(twin, reloadAll),
                  onVoice: () => setHearing(entry.person),
                  onRebuild: () => void rebuild(entry.person),
                })
              : twinRow({
                  twin: entry.twin,
                  me: identity?.email,
                  match: matches.find((m) => m.persona_id === entry.twin.id),
                  onOpen: chat,
                  onMember: () => void navigate(twinMemberPath(entry.twin.id)),
                  onSame: (match, same) => void sameTwin(match, same),
                  onDelete: () => void deleteTwin(entry.twin, reloadAll),
                }),
          )}
        />
      )}
      {matchingPeople && (
        <LoadMore
          shown={Math.min(peopleShown, matchingPeople.length)}
          total={matchingPeople.length}
          label="继续加载人物"
          disabled={busy}
          active={tab === 'people'}
          onLoadMore={() => setPeopleShown((count) => count + PEOPLE_PER_PAGE)}
        />
      )}
      <Row gap={3} justify="end" wrap>
        <TextLink to="/library">全部录音（{recordings.length}）</TextLink>
      </Row>
    </Stack>
  );
  const trashTab =
    trash.length === 0 ? (
      <Text size="sm" tone="secondary">
        没有已删除的分身。
      </Text>
    ) : (
      <Stack as="ul" gap={0}>
        {trash.map((entry) => (
          <ListRow
            key={entry.id}
            variant="divided"
            title={entry.name}
            meta={`${new Date(entry.expires_at).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}前可恢复`}
            trailing={
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                aria-label={`恢复${entry.name}`}
                onClick={() => void restore(entry)}
              >
                恢复
              </Button>
            }
          />
        ))}
      </Stack>
    );
  if (
    quietWhenEmpty &&
    tab === 'people' &&
    trash.length === 0 &&
    !error &&
    !peopleError &&
    (!entries || entries.length === 0)
  )
    return null;
  return (
    <>
      {peopleError && (
        <Text role="alert" tone="danger">
          {peopleError}
        </Text>
      )}
      <Tabs
        label="团队"
        value={tab}
        onValueChange={(value) => go({ tab: value === 'trash' ? value : null })}
        actions={
          tab === 'people' ? (
            <ActionMenu
              text="添加"
              label="添加"
              items={[
                { label: '添加人物', onSelect: () => setAdding(true) },
                { label: '新建分身', onSelect: () => newTwin(true) },
                ...(toAddress.length > 0
                  ? [
                      {
                        label: `批量建分身（${toAddress.length}）`,
                        onSelect: () => setBatching(true),
                      },
                    ]
                  : []),
              ]}
            />
          ) : undefined
        }
        items={[
          {
            value: 'people',
            label: '成员',
            content: peopleTab,
          },
          // Nothing deleted, nothing to bring back: the tab is there while there is, or while it is open.
          ...(trash.length > 0 || tab === 'trash'
            ? [
                {
                  value: 'trash',
                  label: (
                    <Row gap={2} as="div">
                      已删除
                      {trash.length > 0 && (
                        <Text as="span" size="sm" tone="inherit">
                          {trash.length}
                        </Text>
                      )}
                    </Row>
                  ),
                  content: trashTab,
                },
              ]
            : []),
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
        error={claimError}
        onClose={() => address(null)}
        onSave={async (claim) => {
          if (!addressing) return;
          const twin = twins.find((t) => t.id === addressing.persona_id);
          // Taken already: whoever has it loses it, and what they kept in it to themself goes with them.
          if (
            twin?.claimed &&
            claim !== (twin.claim ?? '') &&
            !(await confirm({
              title: claim ? '改绑这个分身？' : '收回这个分身？',
              body: '原认领人会失去它，TA 的私人笔记和对话会清掉。',
              confirmLabel: claim ? '改绑' : '收回',
              tone: 'danger',
            }))
          )
            return;
          setClaimError('');
          void saveClaim(addressing, claim).then((failed) => {
            if (failed) setClaimError(failed);
            else address(null);
          });
        }}
      />
      <EditPerson
        person={editing}
        busy={busy}
        onClose={() => setEditing(null)}
        onSave={(change) => editing && void edit(editing, change)}
      />
      <PersonVoice
        person={hearing}
        onClose={() => setHearing(null)}
        onChanged={load}
      />
      <VoiceClashes
        open={checkingClashes}
        clashes={clashes}
        busy={busy}
        onClose={() => setCheckingClashes(false)}
        onMerge={(clash) => void mergeClash(clash)}
        onRemove={(sample) => void removeClashSample(sample)}
        onApart={(clash) => void apartClash(clash)}
      />
    </>
  );
}
