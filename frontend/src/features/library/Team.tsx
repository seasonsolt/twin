import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Badge, Button, Input, Meter, useConfirm } from '../../components/ui';
import { api } from '../../lib/api';
import { usePersonas } from '../../stores/personas';
import type { Recording } from '../../pages/Library';
import type { Person, Speaker } from '../../pages/Recording';

interface Waiting extends Speaker {
  recording_id: string;
  filename: string;
}

const minutes = (seconds: number) =>
  `${Math.max(1, Math.round(seconds / 60))} 分钟`;
const recordingPath = (id: string) => `/library/${encodeURIComponent(id)}`;
const task =
  'flex flex-col gap-2 rounded-xl border border-border bg-surface p-4';
const taskLabel = 'text-sm font-medium';

function Unnamed({
  person,
  busy,
  onName,
}: {
  person: Person;
  busy: boolean;
  onName: (name: string) => void;
}) {
  const [name, setName] = useState('');
  return (
    <li className={task}>
      <span className={`${taskLabel} text-warning`}>新出现的声音</span>
      <p className="font-medium">
        {person.name} · 在 {person.speakers} 段录音里出现
      </p>
      <form
        className="flex flex-wrap gap-2"
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
      </form>
      {person.recording_id && (
        <Link
          to={recordingPath(person.recording_id)}
          className="inline-flex min-h-11 items-center text-sm text-accent underline"
        >
          去听一听
        </Link>
      )}
    </li>
  );
}

/** What the owner has to settle (new voices, uncertain speakers, recordings on their way) and everyone found in
 * the recordings, each with their twin. */
export function Team({
  version,
  recordings,
}: {
  version: number;
  recordings: Recording[];
}) {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [waiting, setWaiting] = useState<Waiting[]>([]);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const confirm = useConfirm();
  const navigate = useNavigate();
  const refreshPersonas = usePersonas((state) => state.refresh);
  const switchTo = usePersonas((state) => state.switchTo);

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

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError('');
    try {
      await work();
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
    act(() =>
      api(`/api/library/people/${encodeURIComponent(person.id)}`, {
        method: 'PATCH',
        json: { name: value },
      }),
    );
  const chat = async (personaId: string) => {
    await switchTo(personaId);
    void navigate('/chat');
  };

  const unnamed = people?.filter((p) => p.auto) ?? [];
  const named = people?.filter((p) => !p.auto);
  const arriving = recordings.filter((r) => r.status !== 'ready');
  const tasks = unnamed.length + waiting.length + arriving.length;
  return (
    <>
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
      {tasks > 0 && (
        <section
          aria-label="需要你处理"
          className="space-y-4 rounded-2xl border border-border bg-surface p-5"
        >
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-semibold">需要你处理</h3>
            <Badge tone="warning">{tasks}</Badge>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {unnamed.map((person) => (
              <Unnamed
                key={person.id}
                person={person}
                busy={busy}
                onName={(value) => void rename(person, value)}
              />
            ))}
            {waiting.map((w) => (
              <li key={`${w.recording_id}-${w.id}`} className={task}>
                <span className={`${taskLabel} text-warning`}>拿不准是谁</span>
                <p className="font-medium">
                  <span className="break-all">{w.filename}</span> · {w.id}{' '}
                  {w.candidates.length > 1
                    ? `像${w.candidates[0].name}，也像${w.candidates[1].name}`
                    : `像${w.candidates[0].name}`}
                </p>
                <Link
                  to={recordingPath(w.recording_id)}
                  className="inline-flex min-h-11 items-center text-sm text-accent underline"
                >
                  去听一听
                </Link>
              </li>
            ))}
            {arriving.map((r) => (
              <li key={r.id} className={task}>
                <span
                  className={`${taskLabel} ${r.status === 'failed' ? 'text-danger' : 'text-secondary'}`}
                >
                  {r.status === 'failed'
                    ? '转写失败'
                    : r.status === 'queued'
                      ? '排队转写'
                      : '转写中'}
                </span>
                <p className="font-medium break-all">{r.filename}</p>
                {r.status === 'transcribing' && r.duration_s ? (
                  <Meter
                    label="已转写"
                    value={(r.transcribed_s / r.duration_s) * 100}
                  />
                ) : r.status === 'failed' ? (
                  <Link
                    to="/library"
                    className="inline-flex min-h-11 items-center text-sm text-accent underline"
                  >
                    去录音库处理
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-label="人物" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold">人物</h3>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim()) void add();
            }}
          >
            <Input
              aria-label="人物名字"
              placeholder="手动添加人物"
              maxLength={40}
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
          </form>
        </div>
        {named && named.length === 0 && (
          <p className="text-sm text-secondary">
            录音转写后，认出来的人会出现在这里；也可以打开录音，确认说话人是谁。
          </p>
        )}
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {named?.map((person) => (
            <li
              key={person.id}
              className="flex flex-col gap-4 rounded-2xl border border-border bg-surface p-5"
            >
              <div className="flex items-center gap-3">
                <span
                  aria-hidden
                  className="grid size-12 shrink-0 place-items-center rounded-full bg-soft text-lg font-semibold text-accent"
                >
                  {Array.from(person.name)[0]}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-lg font-semibold">
                    {person.name}
                  </p>
                  <p className="text-sm text-secondary">
                    {person.speakers
                      ? `${person.speakers} 段录音 · ${minutes(person.seconds)}`
                      : '还没有确认过的发言'}
                  </p>
                </div>
              </div>
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
                  <Button
                    className="flex-1"
                    disabled={person.updating}
                    onClick={() => void chat(person.persona_id!)}
                  >
                    {person.updating ? '整理完成后可以聊' : '和分身聊聊'}
                  </Button>
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
                    <Button
                      variant="ghost"
                      disabled={busy}
                      aria-label={`删除${person.name}`}
                      onClick={() => void remove(person)}
                    >
                      删除
                    </Button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
