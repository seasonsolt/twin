import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Badge, Button, Input, useConfirm } from '../../components/ui';
import { api } from '../../lib/api';
import { usePersonas } from '../../stores/personas';
import type { Person, Speaker } from '../../pages/Recording';

interface Waiting extends Speaker {
  recording_id: string;
  filename: string;
}

const minutes = (seconds: number) =>
  `${Math.max(1, Math.round(seconds / 60))} 分钟`;

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
    <li className="flex flex-wrap items-center gap-3 rounded-xl bg-surface p-3">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{person.name}</p>
        <p className="text-sm text-secondary">
          {person.speakers} 段录音里出现 · 共 {minutes(person.seconds)}
        </p>
      </div>
      {person.recording_id && (
        <Link
          to={`/library/${encodeURIComponent(person.recording_id)}`}
          className="inline-flex min-h-11 items-center text-sm text-accent underline"
        >
          去听一听
        </Link>
      )}
      <form
        className="flex gap-2"
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
          onChange={(event) => setName(event.target.value)}
        />
        <Button type="submit" size="sm" disabled={busy || !name.trim()}>
          起名
        </Button>
      </form>
    </li>
  );
}

/** People tagged in the owner's recordings, their twins, and the speakers waiting for confirmation. */
export function Team({ version }: { version: number }) {
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
        {
          method: 'POST',
        },
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
  const unnamed = people?.filter((p) => p.auto) ?? [];
  const named = people?.filter((p) => !p.auto);
  const chat = async (personaId: string) => {
    await switchTo(personaId);
    void navigate('/chat');
  };

  return (
    <>
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
      {unnamed.length > 0 && (
        <section aria-label="新出现的声音" className="space-y-3">
          <h3 className="text-lg font-semibold">
            新出现的声音（{unnamed.length}）
          </h3>
          <p className="text-sm text-secondary">
            录音里这些声音还对不上任何人，已经自动建档。听一听、起好名字，就能生成分身。
          </p>
          <ul className="space-y-2">
            {unnamed.map((person) => (
              <Unnamed
                key={person.id}
                person={person}
                busy={busy}
                onName={(value) => void rename(person, value)}
              />
            ))}
          </ul>
        </section>
      )}
      {waiting.length > 0 && (
        <section aria-label="待确认的说话人" className="space-y-3">
          <h3 className="text-lg font-semibold">
            声音像已知的人（{waiting.length}）
          </h3>
          <p className="text-sm text-secondary">
            只是声音相似，确认前不会算作任何人的发言。
          </p>
          <ul className="space-y-2">
            {waiting.map((w) => (
              <li
                key={`${w.recording_id}-${w.id}`}
                className="flex flex-wrap items-center gap-3 rounded-xl bg-surface p-3"
              >
                <span className="min-w-0 flex-1 truncate" title={w.filename}>
                  {w.filename} · {w.id}
                </span>
                {w.candidates.map((c) => (
                  <Badge key={c.person_id} tone={w.near ? 'warning' : 'info'}>
                    像{c.name} {Math.round(c.score * 100)}%
                  </Badge>
                ))}
                <Link
                  to={`/library/${encodeURIComponent(w.recording_id)}`}
                  className="inline-flex min-h-11 items-center text-sm text-accent underline"
                >
                  去听一听
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-label="人物" className="space-y-3">
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
            placeholder="添加人物，例如 张总"
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
        {named && named.length === 0 && (
          <p className="text-sm text-secondary">
            打开一段已转写的录音，确认说话人是谁，就会出现在这里。
          </p>
        )}
        <ul className="space-y-2">
          {named?.map((person) => (
            <li
              key={person.id}
              className="flex flex-wrap items-center gap-3 rounded-xl bg-surface p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="font-medium">{person.name}</p>
                <p className="text-sm text-secondary">
                  {person.speakers
                    ? `${person.speakers} 段录音里确认过 · 共 ${minutes(person.seconds)}`
                    : '还没有确认过的发言'}
                  {person.samples ? ` · ${person.samples} 个声纹样本` : ''}
                </p>
              </div>
              {person.persona_id ? (
                person.updating ? (
                  <Badge tone="warning">记忆更新中</Badge>
                ) : (
                  <Button
                    size="sm"
                    onClick={() => void chat(person.persona_id!)}
                  >
                    和分身聊聊
                  </Button>
                )
              ) : (
                <>
                  <Button
                    size="sm"
                    disabled={busy || !person.speakers}
                    onClick={() => void createTwin(person)}
                  >
                    生成分身
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    aria-label={`删除${person.name}`}
                    onClick={() => void remove(person)}
                  >
                    删除
                  </Button>
                </>
              )}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
