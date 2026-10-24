import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { usePersonaId, usePersonaState } from '../lib/usePersonaState';
import { api, ApiError } from '../lib/api';
import { byName } from '../lib/names';
import { usePolling } from '../lib/usePolling';
import { cn } from '../lib/utils';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  EmptyState,
  Field,
  Heading,
  Input,
  KeyValue,
  Select,
  Skeleton,
  Tabs,
  Text,
  Textarea,
  Tooltip,
  ActionMenu,
  toast,
  useConfirm,
  type Tone,
} from '../components/ui';
import { useIsSelf } from '../stores/access';
import { usePersonas } from '../stores/personas';
import { AWAY_CHANGED } from '../features/away/useAway';
import { JobProgress } from '../features/jobs/JobProgress';
import { MemoryUpdating } from '../features/memories/BuildProgress';
import { useJob } from '../features/jobs/useJob';
import type {
  LedgerBrief,
  LedgerBuildResult,
  LedgerChanges,
  LedgerData,
  LedgerEntry,
  LedgerKind,
  LedgerStatus,
} from '../features/ledger/types';

const SELF = '本人';
const statusTones: Record<LedgerStatus, Tone> = {
  open: 'info',
  claimed_done: 'warning',
  evidenced: 'success',
  confirmed_done: 'success',
  not_done: 'danger',
  reopened: 'danger',
  unknown: 'neutral',
  pending_accept: 'warning',
};
const reviewLabels = {
  confirmed: '已确认',
  edited: '已修改',
  rejected: '已驳回',
};

/** "本人" in a ledger is whoever it belongs to: by name when the person looking at it is somebody else. */
function called(value: string, who: string) {
  return value === SELF && who ? who : value;
}

function day(iso: string | null) {
  if (!iso) return '';
  const [, month, date] = iso.split('-').map(Number);
  return `${month}月${date}日`;
}

function today() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <label className="flex flex-col gap-1">
      <Text as="span" size="sm" tone="secondary">
        {label}
      </Text>
      <Select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([option, text]) => (
          <option key={option} value={option}>
            {text}
          </option>
        ))}
      </Select>
    </label>
  );
}

function Facts({ entry, who }: { entry: LedgerEntry; who: string }) {
  const facts: [string, ReactNode][] = [];
  if (entry.owner)
    facts.push([
      '负责人',
      entry.counterpart
        ? `${called(entry.owner, who)} → ${called(entry.counterpart, who)}`
        : called(entry.owner, who),
    ]);
  if (entry.due || entry.due_text)
    facts.push([
      '截止',
      [day(entry.due), entry.due_text && `（${entry.due_text}）`]
        .filter(Boolean)
        .join(''),
    ]);
  if (entry.condition) facts.push(['前提', entry.condition]);
  if (!facts.length) return null;
  return <KeyValue items={facts} layout="inline" />;
}

function Quote({
  entry,
  who,
  meeting,
}: {
  entry: LedgerEntry;
  who: string;
  /** Say which meeting it is from: not where the entries are already under their meeting's heading. */
  meeting: boolean;
}) {
  return (
    <Text
      as="blockquote"
      size="sm"
      tone="secondary"
      className="border-l-2 border-border pl-3"
    >
      <span className="text-tertiary">
        {meeting && `${day(entry.meeting_date)} ${entry.meeting_title} · `}
        {called(entry.speaker, who)}：
      </span>
      「{entry.quote}」
      {!entry.quote_exact && (
        <span className="ml-1">
          <Tooltip label="没有找到逐字原话，显示整句">
            <Badge tone="warning" tabIndex={0}>
              非原话
            </Badge>
          </Tooltip>
        </span>
      )}
    </Text>
  );
}

function EntryCard({
  entry,
  who,
  meeting = true,
  onReview,
  onEdit,
  onTake,
}: {
  entry: LedgerEntry;
  /** The name the ledger's "本人" goes by for the one looking at it, when that is somebody else. */
  who: string;
  /** Say which meeting the quote is from (off under the meeting's own heading). */
  meeting?: boolean;
  onReview?: (
    entry: LedgerEntry,
    action: 'confirm' | 'reject' | 'reset',
  ) => void;
  onEdit?: (entry: LedgerEntry) => void;
  /** Take on or turn down a promise someone asked for in a conversation. */
  onTake?: (entry: LedgerEntry, action: 'accept' | 'decline') => void;
}) {
  const rejected = entry.review === 'rejected';
  // Waiting for the person to answer the one who asked, or answered no: it is changed only by answering, not here.
  const answering = entry.status === 'pending_accept';
  const asked = !!onTake && answering && !rejected;
  const copy = () => {
    void navigator.clipboard.writeText(entry.confirmation_message ?? '').then(
      () => toast('确认消息已复制，可以发给对方', 'success'),
      () => toast(entry.confirmation_message ?? '', 'info', 15000),
    );
  };
  // One main action, the others behind "⋯": confirm what is unchecked, undo a rejection, else correct.
  const main =
    onReview && entry.review === 'unreviewed' ? (
      <Button size="sm" onClick={() => onReview(entry, 'confirm')}>
        确认
      </Button>
    ) : onReview && rejected ? (
      <Button
        size="sm"
        variant="secondary"
        onClick={() => onReview(entry, 'reset')}
      >
        撤销{reviewLabels.rejected}
      </Button>
    ) : onEdit ? (
      <Button size="sm" variant="secondary" onClick={() => onEdit(entry)}>
        修改
      </Button>
    ) : null;
  const more: { label: string; onSelect: () => void }[] = [];
  if (onEdit && !rejected && entry.review === 'unreviewed')
    more.push({ label: '修改', onSelect: () => onEdit(entry) });
  if (onReview && entry.review === 'unreviewed')
    more.push({ label: '驳回', onSelect: () => onReview(entry, 'reject') });
  if (onReview && entry.review !== 'unreviewed' && !rejected)
    more.push({
      label: `撤销${reviewLabels[entry.review]}`,
      onSelect: () => onReview(entry, 'reset'),
    });
  if ((onReview || onEdit) && entry.confirmation_message && !rejected)
    more.push({ label: '复制确认消息', onSelect: copy });
  return (
    <Card className={cn('space-y-3', rejected && 'opacity-60')}>
      <article
        aria-label={`${entry.kind_label}：${entry.what}`}
        className="space-y-3"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{entry.kind_label}</Badge>
          {entry.kind !== 'objection' && (
            <Badge tone={statusTones[entry.current_status]}>
              {entry.current_status_label}
            </Badge>
          )}
          {entry.review !== 'unreviewed' && (
            <Badge tone={rejected ? 'danger' : 'success'}>
              {reviewLabels[entry.review]}
            </Badge>
          )}
          {entry.review === 'unreviewed' && entry.confidence < 0.6 && (
            <Tooltip label="把握不大，请核对">
              <Badge tone="warning" tabIndex={0}>
                待核对
              </Badge>
            </Tooltip>
          )}
        </div>
        <p className={cn('font-medium', rejected && 'line-through')}>
          {entry.what}
        </p>
        <Facts entry={entry} who={who} />
        <Quote entry={entry} who={who} meeting={meeting} />
        {asked && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => onTake(entry, 'accept')}>
              接下
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onTake(entry, 'decline')}
            >
              不接
            </Button>
          </div>
        )}
        {!answering && (main || more.length > 0) && (
          <div className="flex flex-wrap items-center gap-2">
            {main}
            {more.length > 0 && <ActionMenu label="更多" items={more} />}
          </div>
        )}
      </article>
    </Card>
  );
}

function EditDialog({
  entry,
  statusLabels,
  who,
  everyone,
  onClose,
  onSave,
}: {
  entry: LedgerEntry | null;
  statusLabels: Record<LedgerStatus, string>;
  who: string;
  everyone: boolean;
  onClose: () => void;
  onSave: (entry: LedgerEntry, changes: LedgerChanges) => Promise<void>;
}) {
  const [draft, setDraft] = useState({
    owner: '',
    counterpart: '',
    what: '',
    due: '',
    condition: '',
    status: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!entry) return;
    setDraft({
      owner: entry.owner,
      counterpart: entry.counterpart,
      what: entry.what,
      due: entry.due ?? '',
      condition: entry.condition,
      status: entry.status ?? '',
    });
    setError('');
  }, [entry]);
  const set = (key: keyof typeof draft) => (value: string) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const save = async () => {
    if (!entry) return;
    if (!draft.owner.trim() || !draft.what.trim()) {
      setError('负责人和内容不能为空');
      return;
    }
    const changes: LedgerChanges = {};
    if (draft.owner.trim() !== entry.owner) changes.owner = draft.owner.trim();
    if (draft.counterpart.trim() !== entry.counterpart)
      changes.counterpart = draft.counterpart.trim();
    if (draft.what.trim() !== entry.what) changes.what = draft.what.trim();
    if (draft.due !== (entry.due ?? '')) changes.due = draft.due || null;
    if (draft.condition.trim() !== entry.condition)
      changes.condition = draft.condition.trim();
    if (draft.status !== (entry.status ?? ''))
      changes.status = (draft.status || null) as LedgerStatus | null;
    if (!Object.keys(changes).length) {
      onClose();
      return;
    }
    setSaving(true);
    setError('');
    try {
      await onSave(entry, changes);
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };
  const statusOptions: [string, string][] = [
    ['', '按会议记录推断'],
    // 待你接受 is the state of a promise asked for in a conversation until it is taken or turned down, not a choice.
    ...(Object.entries(statusLabels).filter(
      ([status]) => status !== 'pending_accept',
    ) as [string, string][]),
  ];
  return (
    <Dialog
      open={entry !== null}
      onOpenChange={(open) => !open && onClose()}
      title="修改这一条"
      body="改过的条目重新整理会议时不会被覆盖。"
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <Field id="ledger-what" label="内容">
          <Textarea
            id="ledger-what"
            value={draft.what}
            onChange={(event) => set('what')(event.target.value)}
          />
        </Field>
        <Field
          id="ledger-owner"
          label="负责人"
          help={everyone ? undefined : `写「${SELF}」表示${who || '你'}自己`}
        >
          <Input
            id="ledger-owner"
            value={draft.owner}
            onChange={(event) => set('owner')(event.target.value)}
          />
        </Field>
        <Field id="ledger-counterpart" label="对谁负责">
          <Input
            id="ledger-counterpart"
            value={draft.counterpart}
            onChange={(event) => set('counterpart')(event.target.value)}
          />
        </Field>
        <Field id="ledger-due" label="截止日期">
          <Input
            id="ledger-due"
            type="date"
            value={draft.due}
            onChange={(event) => set('due')(event.target.value)}
          />
        </Field>
        <Field id="ledger-condition" label="前提">
          <Input
            id="ledger-condition"
            value={draft.condition}
            onChange={(event) => set('condition')(event.target.value)}
          />
        </Field>
        {entry?.kind !== 'objection' && (
          <FilterSelect
            label="状态"
            value={draft.status}
            onChange={set('status')}
            options={statusOptions}
          />
        )}
        {error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" loading={saving}>
            保存
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function Entries({
  data,
  everyone,
  who,
  onReview,
  onEdit,
  onTake,
}: {
  data: LedgerData;
  /** The list holds several people's ledgers: nobody is "我自己". */
  everyone: boolean;
  /** The name "我自己" goes by for the one looking at somebody else's ledger. */
  who: string;
  onReview: (
    entry: LedgerEntry,
    action: 'confirm' | 'reject' | 'reset',
  ) => void;
  onEdit: (entry: LedgerEntry) => void;
  onTake: (entry: LedgerEntry, action: 'accept' | 'decline') => void;
}) {
  const [kind, setKind] = useState('');
  const [person, setPerson] = useState('');
  const [status, setStatus] = useState('');
  const [showRejected, setShowRejected] = useState(false);
  const rows = data.entries.filter(
    (entry) =>
      (showRejected || entry.review !== 'rejected') &&
      (!kind || entry.kind === kind) &&
      (!person || entry.owner === person) &&
      (!status || entry.current_status === status),
  );
  const meetings = new Map<string, LedgerEntry[]>();
  for (const entry of rows) {
    // A meeting several people were in has an entry in each of their ledgers, under their own source.
    const key = entry.meeting ?? entry.source_id;
    const group = meetings.get(key) ?? [];
    group.push(entry);
    meetings.set(key, group);
  }
  const groups = [...meetings.values()].reverse();
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <FilterSelect
          label="类型"
          value={kind}
          onChange={setKind}
          options={[
            ['', '全部'],
            ...(Object.entries(data.kind_labels) as [LedgerKind, string][]),
          ]}
        />
        <FilterSelect
          label="负责人"
          value={person}
          onChange={setPerson}
          options={[
            ['', '所有人'],
            ...(everyone ? [] : [[SELF, who || '我自己'] as [string, string]]),
            ...[...data.people]
              .sort(byName)
              .map((name): [string, string] => [name, name]),
          ]}
        />
        <FilterSelect
          label="状态"
          value={status}
          onChange={setStatus}
          options={[
            ['', '全部'],
            ...(Object.entries(data.status_labels) as [string, string][]),
          ]}
        />
        <Checkbox
          label={
            <Text as="span" size="sm">
              显示已驳回
            </Text>
          }
          checked={showRejected}
          onChange={(event) => setShowRejected(event.target.checked)}
        />
      </div>
      {!rows.length && <p className="text-secondary">没有符合条件的条目。</p>}
      {groups.map((group) => (
        <section
          key={group[0].meeting ?? group[0].source_id}
          aria-label={`${day(group[0].meeting_date)}${group[0].meeting_title}`}
          className="space-y-3"
        >
          <Heading level={3}>
            {day(group[0].meeting_date)} {group[0].meeting_title}
          </Heading>
          {group.map((entry) => (
            <EntryCard
              key={entry.entry_id}
              entry={entry}
              who={who}
              meeting={false}
              onReview={onReview}
              onEdit={onEdit}
              onTake={onTake}
            />
          ))}
        </section>
      ))}
    </div>
  );
}

function Brief({
  people,
  version,
  who,
}: {
  people: string[];
  version: number;
  who: string;
}) {
  const [person, setPerson] = useState(people[0] ?? '');
  const [asOf, setAsOf] = useState(today());
  const [brief, setBrief] = useState<LedgerBrief | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!people.includes(person)) setPerson(people[0] ?? '');
  }, [people, person]);
  useEffect(() => {
    if (!person) return;
    const controller = new AbortController();
    setError('');
    void api<LedgerBrief>(
      `/api/persona/ledger/brief?${new URLSearchParams({ person, as_of: asOf || today() })}`,
      { signal: controller.signal },
    )
      .then((next) => setBrief(next))
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        setError(failure instanceof Error ? failure.message : '加载失败');
      });
    return () => controller.abort();
  }, [person, asOf, version]);
  if (!people.length)
    return (
      <EmptyState
        title="还没有可以准备的人"
        body="整理出别人的承诺或异议后，可以在这里按人查看见面前要聊的事。"
      />
    );
  const sections: [string, LedgerEntry[], string][] = brief
    ? [
        [`${brief.person}答应的事`, brief.theirs, '没有未完成的承诺'],
        [`${who || '我'}答应${brief.person}的事`, brief.mine, '没有'],
        ['最近进展', brief.progress, '没有进展记录'],
        [`${brief.person}提过的顾虑`, brief.objections, '没有'],
      ]
    : [];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <FilterSelect
          label="见谁"
          value={person}
          onChange={setPerson}
          options={[...people]
            .sort(byName)
            .map((name): [string, string] => [name, name])}
        />
        <label className="flex flex-col gap-1">
          <Text as="span" size="sm" tone="secondary">
            日期
          </Text>
          <Input
            type="date"
            value={asOf}
            onChange={(event) => setAsOf(event.target.value)}
            className="w-auto"
          />
        </label>
      </div>
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
      {!brief && !error && <Skeleton className="h-40" />}
      {brief && (
        <>
          <Card className="space-y-2">
            <Heading level={3}>可以问的问题</Heading>
            {brief.questions.length ? (
              <ol className="list-decimal space-y-1 pl-5">
                {brief.questions.map((question) => (
                  <li key={`${question.entry_id}-${question.text}`}>
                    {question.text}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-secondary">账本里没有需要跟进的事。</p>
            )}
          </Card>
          {sections.map(([title, entries, empty]) => (
            <section key={title} aria-label={title} className="space-y-3">
              <Heading level={3}>{title}</Heading>
              {entries.length ? (
                entries.map((entry) => (
                  <EntryCard key={entry.entry_id} entry={entry} who={who} />
                ))
              ) : (
                <p className="text-secondary">{empty}</p>
              )}
            </section>
          ))}
        </>
      )}
    </div>
  );
}

/** The commitments of the twin in view, from the meetings it was in: filters by kind, person and state, the
 * entries with their quotes, and what to bring up before meeting someone. Opened under a member, or on its own
 * (``/commitments``) for whoever is chosen there. */
export function Ledger({
  everyone = false,
  onOpen,
}: {
  everyone?: boolean;
  /** In the list of everyone's: open one person's own commitments (to read the meetings not yet read there). */
  onOpen?: (twinId: string) => void;
}) {
  const personaId = usePersonaId();
  const persona = usePersonas((state) =>
    state.items.find((item) => item.id === personaId),
  );
  // Somebody else's ledger is told by their name, not as "我": it is the viewer's own when the twin is theirs.
  const self = useIsSelf(persona);
  const who = !everyone && persona && !self ? persona.name : '';
  const confirm = useConfirm();
  const [data, setData] = usePersonaState<LedgerData | null>(null);
  const [error, setError] = usePersonaState('');
  // The twin's memory is being rebuilt: its ledger is not read until then, which is no failure.
  const [rebuilding, setRebuilding] = usePersonaState(false);
  const [editing, setEditing] = useState<LedgerEntry | null>(null);
  const [version, setVersion] = useState(0);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const next = await api<LedgerData>(
          everyone
            ? '/api/personas/commitments?include_rejected=true'
            : '/api/persona/ledger?include_rejected=true',
          { signal },
        );
        setData(next);
        setError('');
        setRebuilding(false);
        setVersion((current) => current + 1);
      } catch (failure) {
        if (signal?.aborted) return;
        if (failure instanceof ApiError && failure.code === 'memory_updating') {
          setRebuilding(true);
          setError('');
          return;
        }
        setError(failure instanceof Error ? failure.message : '加载失败');
      }
    },
    [setData, setError, setRebuilding, everyone],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, personaId]);
  const job = useJob<LedgerBuildResult>({
    kind: 'ledger_build',
    storageKey: 'twin.next.job.ledgerBuild',
    active: !everyone,
    onDone: (done, { restored }) => {
      void load();
      if (!restored && done.result)
        toast(
          `读了 ${done.result.sources} 场会议，记下 ${done.result.entries} 条`,
          'success',
        );
    },
  });
  // An entry is changed in the ledger it is kept in, whoever's page it is shown on.
  const whose = (entry: LedgerEntry): Record<string, string> =>
    entry.persona_id ? { 'X-Twin-Persona': entry.persona_id } : {};
  const review = async (
    entry: LedgerEntry,
    action: 'confirm' | 'reject' | 'reset' | 'edit',
    changes?: LedgerChanges,
  ) => {
    // In the team's list the owner of a promise is named; in the ledger it came from, the person is 本人.
    const sent =
      changes?.owner && changes.owner === entry.persona_name
        ? { ...changes, owner: SELF }
        : changes;
    await api<LedgerEntry>(
      `/api/persona/ledger/${encodeURIComponent(entry.entry_id)}/review`,
      {
        method: 'POST',
        json: { action, ...(sent ? { changes: sent } : {}) },
        headers: whose(entry),
      },
    );
    await load();
  };
  const onReview = (
    entry: LedgerEntry,
    action: 'confirm' | 'reject' | 'reset',
  ) => {
    void review(entry, action).catch((failure: unknown) =>
      toast(failure instanceof Error ? failure.message : '操作失败', 'danger'),
    );
  };
  const onTake = (entry: LedgerEntry, action: 'accept' | 'decline') => {
    void api(
      `/api/persona/ledger/${encodeURIComponent(entry.entry_id)}/${action}`,
      { method: 'POST', json: {}, headers: whose(entry) },
    )
      .then(async () => {
        await load();
        window.dispatchEvent(new Event(AWAY_CHANGED));
      })
      .catch((failure: unknown) =>
        toast(
          failure instanceof Error ? failure.message : '操作失败',
          'danger',
        ),
      );
  };
  const rebuild = async () => {
    const ok = await confirm({
      title: '重新整理全部会议',
      body: '会重新读每一场会议，替换还没确认或修改的条目；确认、修改、驳回过的条目保持不变。会调用模型，可能需要几分钟。',
      confirmLabel: '重新整理',
    });
    if (ok) await job.start('/api/persona/ledger/build', { force: true });
  };
  // A rebuild takes minutes: look again now and then until it is over.
  const organising = data?.updating ?? [];
  usePolling(load, rebuilding || organising.length ? 15000 : 0);
  const organisingLine = organising.length
    ? `${organising.map((twin) => twin.name).join('、')}整理中，完成后列出`
    : '';
  const meetings = data?.meetings;
  // In the list of everyone's: whose ledgers have meetings not read yet.
  const unread = (data?.twins ?? []).filter((twin) => (twin.pending ?? 0) > 0);
  const unreviewed =
    data?.entries.filter((entry) => entry.review === 'unreviewed').length ?? 0;
  return (
    <div>
      <div className="space-y-6">
        {error && (
          <div role="alert" className="space-y-2 text-danger">
            <p>{error}</p>
            <Button variant="secondary" onClick={() => void load()}>
              重试加载
            </Button>
          </div>
        )}
        {rebuilding && <MemoryUpdating text="记忆更新中，整理完成后列出" />}
        {!data && !error && !rebuilding && <Skeleton className="h-40" />}
        {meetings && (
          <Card className="flex flex-wrap items-center justify-between gap-3">
            <p role="status">
              {meetings.total
                ? `共 ${meetings.total} 场会议${meetings.pending ? `，${meetings.pending} 场还没整理` : '，都已整理'}${unreviewed ? `；${unreviewed} 条待确认` : ''}${organisingLine ? `；${organisingLine}` : ''}`
                : everyone
                  ? organisingLine || '还没有会议。'
                  : `还没有会议。添加有${who || '你'}和别人发言的录音或会议记录，并选出哪位是${who || '你'}。`}
            </p>
            {!everyone && (
              <div className="flex flex-wrap gap-2">
                {meetings.pending > 0 && (
                  <Button
                    loading={job.busy}
                    onClick={() =>
                      void job.start('/api/persona/ledger/build', {})
                    }
                  >
                    整理 {meetings.pending} 场新会议
                  </Button>
                )}
                {meetings.total > 0 && meetings.pending === 0 && (
                  <Button
                    variant="secondary"
                    disabled={job.busy}
                    onClick={() => void rebuild()}
                  >
                    重新整理全部
                  </Button>
                )}
              </div>
            )}
          </Card>
        )}
        {!everyone && (
          <JobProgress
            state={job}
            onRetry={() => void job.start('/api/persona/ledger/build', {})}
          />
        )}
        {data && data.entries.length > 0 && everyone && (
          <Entries
            data={data}
            everyone
            who=""
            onReview={onReview}
            onEdit={setEditing}
            onTake={onTake}
          />
        )}
        {data && data.entries.length > 0 && !everyone && (
          <Tabs
            items={[
              {
                value: 'entries',
                label: '全部条目',
                content: (
                  <Entries
                    data={data}
                    everyone={false}
                    who={who}
                    onReview={onReview}
                    onEdit={setEditing}
                    onTake={onTake}
                  />
                ),
              },
              {
                value: 'brief',
                label: '见面前',
                content: (
                  <Brief people={data.people} version={version} who={who} />
                ),
              },
            ]}
          />
        )}
        {data &&
          !data.entries.length &&
          meetings &&
          meetings.total > 0 &&
          !job.busy && (
            <EmptyState
              title="账本还是空的"
              body={
                meetings.pending
                  ? everyone
                    ? unread.length && onOpen
                      ? '选一位，去整理会议。'
                      : '先在各人的承诺里整理会议。'
                    : '点上面的按钮，从会议里整理出决定和承诺。'
                  : '已整理的会议里没有找到决定或承诺。'
              }
            >
              {everyone && onOpen && (
                <div className="flex flex-wrap justify-center gap-2">
                  {unread.map((twin) => (
                    <Button
                      key={twin.id}
                      variant="secondary"
                      onClick={() => onOpen(twin.id)}
                    >
                      {twin.name}
                    </Button>
                  ))}
                </div>
              )}
            </EmptyState>
          )}
      </div>
      <EditDialog
        entry={editing}
        statusLabels={
          data?.status_labels ?? ({} as Record<LedgerStatus, string>)
        }
        who={who}
        everyone={everyone}
        onClose={() => setEditing(null)}
        onSave={(entry, changes) => review(entry, 'edit', changes)}
      />
    </div>
  );
}
