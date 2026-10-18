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
  Dialog,
  Field,
  Grid,
  Input,
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
import { usePersonas, type Persona } from '../../stores/personas';
import type { Recording } from '../../pages/Library';
import type { Gender, Person, Speaker } from '../../pages/Recording';
import type { Pick } from './useUploads';

interface Waiting extends Speaker {
  recording_id: string;
  filename: string;
}

const minutes = (seconds: number) =>
  `${Math.max(0, Math.round(seconds / 60))} 分钟`;
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

function Unnamed({
  person,
  busy,
  onName,
  taskState,
}: {
  person: Person;
  busy: boolean;
  onName: (name: string) => void;
  taskState: { teamTask: string };
}) {
  const [name, setName] = useState('');
  return (
    <Task kind="新出现的声音">
      <Text weight="medium">
        {person.name} · 在 {person.speakers} 段录音里出现
      </Text>
      <Row
        as="form"
        gap={2}
        wrap
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) onName(name.trim());
        }}
      >
        <Input
          aria-label={`给${person.name}起名`}
          placeholder="这是谁"
          maxLength={40}
          value={name}
          className="min-w-0 flex-1"
          onChange={(event) => setName(event.target.value)}
        />
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          disabled={busy || !name.trim()}
        >
          起名
        </Button>
      </Row>
      {person.recording_id && (
        <RouteButton
          to={recordingPath(person.recording_id)}
          state={taskState}
          variant="secondary"
          size="sm"
        >
          听原声
        </RouteButton>
      )}
    </Task>
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
  const [name, setName] = useState('');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Person | null>(null);
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
        api<{ items: Waiting[] }>('/api/library/review'),
      ]);
      setPeople(folks.items);
      setWaiting(queue.items);
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
  const createTwin = (person: Person) =>
    act(async () => {
      await api(
        `/api/library/people/${encodeURIComponent(person.id)}/persona`,
        { method: 'POST' },
      );
      await refreshPersonas();
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
  const open = async (personaId: string, page: '/chat' | '/profile') => {
    await switchTo(personaId);
    void navigate(page);
  };

  const unnamed = people?.filter((p) => p.auto) ?? [];
  const named = people?.filter((p) => !p.auto);
  const arriving = recordings.filter(
    (r) => r.status === 'queued' || r.status === 'transcribing',
  );
  const failed = recordings.filter((r) => r.status === 'failed');
  const organising = people?.filter((p) => p.updating) ?? [];
  const proofreading = recordings.filter(
    (r) => r.status === 'ready' && r.proofread === 'waiting',
  );
  // Speakers nobody's voice resembles (often short) are not in the review queue; their recording still asks.
  const unsorted = recordings.filter(
    (r) =>
      r.status === 'ready' &&
      r.unsettled > 0 &&
      !waiting.some((w) => w.recording_id === r.id),
  );
  const taskIds = [
    ...unnamed.map((p) => `person-${p.id}`),
    ...waiting.map((w) => `speaker-${w.recording_id}-${w.id}`),
    ...unsorted.map((r) => `unsorted-${r.id}`),
    ...failed.map((r) => `failed-${r.id}`),
  ];
  const tasks = taskIds.length;
  const pending =
    arriving.length + organising.length + proofreading.length + uploads.length;
  const taskOrder = taskIds.join('|');
  useEffect(() => {
    if (!focusPending || !people || busy) return;
    if (taskOrder.split('|').includes(focusPending)) return;
    taskList.current
      ?.querySelector<HTMLElement>('input, a, button:not(:disabled)')
      ?.focus();
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
          <Grid ref={taskList} as="ul" columns={3} gap={3}>
            {unnamed.map((person) => (
              <Unnamed
                key={person.id}
                person={person}
                taskState={{ teamTask: `person-${person.id}` }}
                busy={busy}
                onName={(value) => void rename(person, value)}
              />
            ))}
            {waiting.map((w) => (
              <Task key={`${w.recording_id}-${w.id}`} kind="拿不准是谁">
                <Text weight="medium">
                  <span className="break-all">{w.filename}</span> · {w.id}{' '}
                  {w.candidates.length > 1
                    ? `像${w.candidates[0].name}，也像${w.candidates[1].name}`
                    : `像${w.candidates[0].name}`}
                </Text>
                <RouteButton
                  to={recordingPath(w.recording_id)}
                  state={{ teamTask: `speaker-${w.recording_id}-${w.id}` }}
                  size="sm"
                >
                  试听并确认
                </RouteButton>
              </Task>
            ))}
            {unsorted.map((r) => (
              <Task
                key={`unsorted-${r.id}`}
                kind={r.unsettled === r.speakers ? '还没认人' : '还有人没认'}
              >
                <Text weight="medium">
                  <span className="break-all">{r.filename}</span> ·{' '}
                  {r.unsettled} 位说话人待确认
                </Text>
                <RouteButton
                  to={recordingPath(r.id)}
                  state={{ teamTask: `unsorted-${r.id}` }}
                  size="sm"
                >
                  试听并确认
                </RouteButton>
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
                    </Text>
                  </Stack>
                </IdentityLink>
                <div>
                  {person.persona_id ? (
                    person.updating ? (
                      <Badge tone="warning">记忆更新中</Badge>
                    ) : (
                      <Badge tone="success">可以聊</Badge>
                    )
                  ) : (
                    <Badge tone="neutral">还没有分身</Badge>
                  )}
                </div>
                <div className="mt-auto flex flex-wrap gap-2">
                  {person.persona_id ? (
                    <>
                      <Button
                        className="flex-1"
                        disabled={person.updating}
                        onClick={() => void open(person.persona_id!, '/chat')}
                      >
                        {person.updating ? '整理完成后可以聊' : '和分身聊聊'}
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        variant="secondary"
                        className="flex-1"
                        disabled={busy || !person.speakers}
                        onClick={() => void createTwin(person)}
                      >
                        生成分身
                      </Button>
                    </>
                  )}
                  <ActionMenu
                    label={`更多：${person.name}`}
                    items={[
                      {
                        label: '编辑名字和性别',
                        disabled: busy,
                        onSelect: () => setEditing(person),
                      },
                      ...(!person.persona_id
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
