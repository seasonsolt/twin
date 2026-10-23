import { useCallback, useEffect, useState, type ReactNode } from 'react';
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
import { memberPath, twinMemberPath } from '../../lib/members';
import { useAuth } from '../../stores/auth';
import { usePersonas, type Persona } from '../../stores/personas';
import { useNewTwinCard } from '../../components/layout/NewTwin';
import type { Recording } from '../../pages/Library';
import type { Gender, Person, TwinMatch } from '../../pages/Recording';
import type { Pick } from './useUploads';
import { PersonClip } from './PersonClip';
import { PersonVoice } from './PersonVoice';
import { WorkClaim } from './WorkClaim';
import { BuildMeter } from '../memories/BuildProgress';
import { minutes } from './review';
import { useTeamData } from './useTeamData';
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

/** Where a person's twin stands, as the team table's filter and status column name it. */
type TwinState = 'ready' | 'updating' | 'none' | 'own' | 'elsewhere';
const twinState = (person: Person): TwinState =>
  person.self_claimed
    ? 'own'
    : person.twin_elsewhere && !person.talk
      ? 'elsewhere'
      : person.persona_id || person.talk
        ? person.updating
          ? 'updating'
          : 'ready'
        : 'none';
const TWIN_STATES: Record<TwinState, { label: string; tone: Tone }> = {
  ready: { label: '可以聊', tone: 'success' },
  updating: { label: '整理中', tone: 'warning' },
  none: { label: '没有分身', tone: 'neutral' },
  own: { label: '本人已认领', tone: 'success' },
  elsewhere: { label: '同事建了分身', tone: 'neutral' },
};
// The filters over the table; the two kinds managed elsewhere show under 全部 only.
const TWIN_FILTERS: TwinState[] = ['ready', 'updating', 'none'];

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
  onAddress,
  onRemove,
  onVoice,
}: {
  person: Person;
  twin?: Persona;
  busy: boolean;
  /** Talk to their twin: switch to it and open the chat. */
  onOpen: (personaId: string) => void;
  /** Their page: the recordings they are in, and their twin if they have one. */
  onMember: () => void;
  onEdit: () => void;
  onAddress: () => void;
  onRemove: () => void;
  /** Their voice samples, and what voice alone gave them, to spot-check. */
  onVoice: () => void;
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
    <Row key="heard" gap={2}>
      <Text size="sm" tone="secondary">
        {person.speakers} 段 · {minutes(person.seconds)}
      </Text>
      <PersonClip person={person} icon />
    </Row>,
    <Stack key="twin" gap={1}>
      <Row gap={2}>
        <StatusDot tone={TWIN_STATES[state].tone} />
        <Text size="sm">{TWIN_STATES[state].label}</Text>
      </Row>
      {state === 'updating' && (
        // The twin can talk once its memory is updated: where the update is, under the word.
        <div aria-live="polite">
          <BuildMeter processing={person.build} />
        </div>
      )}
      {checks > 0 ? (
        <TextLink size="sm" onClick={onVoice}>
          {checks} 段可抽查
        </TextLink>
      ) : (
        lacking && (
          <Text size="sm" tone="secondary">
            {lacking}
          </Text>
        )
      )}
    </Stack>,
    <Recent key="recent" person={person} />,
    <Row key="act" gap={1} justify="end">
      {state === 'ready' ? (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onOpen((person.persona_id ?? person.talk)!)}
        >
          聊天
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
            { label: '编辑名字和性别', disabled: busy, onSelect: onEdit },
            { label: '声线和抽查', disabled: busy, onSelect: onVoice },
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
    </Row>,
  ];
}

/** A twin no recording belongs to (made by hand, or someone else's public one), as a row of the same table: it is
 * there to talk to and to open. */
function twinRow({
  twin,
  me,
  match,
  onOpen,
  onMember,
  onSame,
}: {
  twin: Persona;
  /** The signed-in person's address, so only other people's twins name their owner. */
  me?: string | null;
  /** Someone in the meetings with this twin's name, whom its keeper may say it is. */
  match?: TwinMatch;
  onOpen: (personaId: string) => void;
  onMember: () => void;
  onSame: (match: TwinMatch, same: boolean) => void;
}): ReactNode[] {
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
      <StatusDot tone={TWIN_STATES.ready.tone} />
      <Text size="sm">{TWIN_STATES.ready.label}</Text>
    </Row>,
    <Text key="recent" size="sm" tone="secondary">
      —
    </Text>,
    <Row key="act" gap={1} justify="end">
      <Button size="sm" variant="secondary" onClick={() => onOpen(twin.id)}>
        聊天
      </Button>
      {match && (
        <ActionMenu
          label={`${twin.name}是不是会议里的人`}
          items={[
            { label: '是会议里的人', onSelect: () => onSame(match, true) },
            { label: '不是同一个人', onSelect: () => onSame(match, false) },
          ]}
        />
      )}
    </Row>,
  ];
}

/**
 * The team's people, each with their twin. What waits to be settled is the inbox (``/inbox``): the old address of
 * its tab leads there.
 */
export function Team(props: {
  version: number;
  recordings: Recording[];
  onReload?: () => Promise<void>;
  uploads?: Pick[];
}) {
  const [params] = useSearchParams();
  const location = useLocation();
  if (params.get('tab') === 'todo') {
    const cat = params.get('cat');
    return (
      <Navigate
        to={`/inbox${cat ? `?cat=${encodeURIComponent(cat)}` : ''}`}
        replace
        state={location.state}
      />
    );
  }
  return <Roster {...props} />;
}

function Roster({
  version,
  recordings,
  onReload,
  uploads = [],
}: {
  version: number;
  recordings: Recording[];
  onReload?: () => Promise<void>;
  uploads?: Pick[];
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
  } = useTeamData({ version, onReload });
  const [hearing, setHearing] = useState<Person | null>(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<TwinState | null>(null);
  const [editing, setEditing] = useState<Person | null>(null);
  const [addressing, setAddressing] = useState<Person | null>(null);
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
  const switchTo = usePersonas((state) => state.switchTo);
  const twins = usePersonas((state) => state.items);
  const identity = useAuth((state) => state.identity);
  const newTwin = useNewTwinCard((state) => state.set);
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
  // Talking to someone's twin: switch to it, then its chat.
  const chat = async (personaId: string) => {
    await switchTo(personaId);
    void navigate('/chat');
  };

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
      state: 'ready' as const,
      twin,
    })),
  ];
  const matchingPeople = entries?.filter(
    (entry) =>
      (!filter || entry.state === filter) &&
      entry.name
        .toLocaleLowerCase()
        .includes(search.trim().toLocaleLowerCase()),
  );
  const arriving = recordings.filter(
    (r) => r.status === 'queued' || r.status === 'transcribing',
  );
  const organising = people?.filter((p) => p.updating) ?? [];
  const twinOf = (person: Person) =>
    twins.find((t) => t.id === person.persona_id);
  const toAddress = named?.filter((p) => unaddressed(p, twinOf(p))) ?? [];
  const proofreading = recordings.filter(
    (r) => r.status === 'ready' && r.proofread === 'waiting',
  );
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
  const pending =
    arriving.length + organising.length + proofreading.length + uploads.length;

  const peopleTab = (
    <Stack gap={5}>
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
                    pressed={filter === state}
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
                  onOpen: (personaId) => void chat(personaId),
                  onMember: () => void navigate(memberPath(entry.person.id)),
                  onEdit: () => setEditing(entry.person),
                  onAddress: () => setAddressing(entry.person),
                  onRemove: () => void remove(entry.person),
                  onVoice: () => setHearing(entry.person),
                })
              : twinRow({
                  twin: entry.twin,
                  me: identity?.email,
                  match: matches.find((m) => m.persona_id === entry.twin.id),
                  onOpen: (personaId) => void chat(personaId),
                  onMember: () => void navigate(twinMemberPath(entry.twin.id)),
                  onSame: (match, same) => void sameTwin(match, same),
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
            meta={`${new Date(entry.expires_at).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}到期`}
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
  return (
    <>
      {(error || peopleError) && (
        <Text role="alert" tone="danger">
          {error || peopleError}
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
                        label: `按邮箱或工号建分身（${toAddress.length}）`,
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
            label: (
              <Row gap={2} as="div">
                成员
                <Text as="span" size="sm" tone="inherit">
                  {entries?.length ?? 0}
                </Text>
              </Row>
            ),
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
        onClose={() => setAddressing(null)}
        onSave={(claim) =>
          addressing &&
          void saveClaim(addressing, claim).then(() => setAddressing(null))
        }
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
    </>
  );
}
