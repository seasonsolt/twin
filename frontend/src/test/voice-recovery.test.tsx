import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { Button, ConfirmProvider, ToastViewport } from '../components/ui';
import {
  MixedSpeaker,
  type SuspectSpeaker,
} from '../features/library/MixedSpeaker';
import { PersonVoice } from '../features/library/PersonVoice';
import { Recording, type Person } from '../pages/Recording';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
afterEach(() => vi.restoreAllMocks());
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const pending = () => {
  let resolve!: (response: Response) => void;
  return {
    response: new Promise<Response>((done) => (resolve = done)),
    resolve: (value: unknown, status = 200) => resolve(json(value, status)),
  };
};
const person = (id: string): Person => ({
  id,
  name: id,
  persona_id: null,
  speakers: 1,
  seconds: 60,
  samples: 0,
  updating: false,
  auto: false,
  gender: '',
  recording_id: id,
  speaker_id: 'S1',
});
const voice = (id: string, revision = 1) => ({
  samples: [],
  checks: [
    {
      recording_id: id,
      filename: `${id}.m4a`,
      transcript_id: `t-${id}`,
      revision,
      speaker_id: 'S1',
      seconds: 60,
      tier: 'high',
      score: 0.9,
      lead: 0.3,
    },
  ],
});
const suspect = (id: string, revision = 1): SuspectSpeaker => ({
  recording_id: id,
  filename: `${id}.m4a`,
  transcript_id: `t-${id}`,
  revision,
  speaker_id: 'S1',
  person_id: 'owner',
  name: '张总',
  status: 'ready',
  seconds: 60,
  suspect_seconds: 20,
  open_seconds: 20,
  suspects: 1,
  open: 1,
  share: 1 / 3,
  likely: null,
  likely_name: null,
  units: [
    {
      index: 0,
      segments: [0],
      start: 0,
      end: 20,
      seconds: 20,
      text: `${id} 的原话`,
      verdict: 'stranger',
      own: 0.1,
      other: null,
      like: null,
      like_name: null,
      fix: null,
      to_person: null,
      to_name: null,
    },
  ],
});
const noop = () => {};
const layer = (
  kind: 'person' | 'mixed',
  id: string | null,
  onChanged = noop,
) => (
  <ConfirmProvider>
    {kind === 'person' ? (
      <PersonVoice
        person={id ? person(id) : null}
        onClose={noop}
        onChanged={onChanged}
      />
    ) : (
      <MixedSpeaker
        suspect={id ? suspect(id) : null}
        onClose={noop}
        onChanged={onChanged}
      />
    )}
  </ConfirmProvider>
);

it.each(['person', 'mixed'] as const)(
  'keeps the current %s task when a closed task answers late',
  async (kind) => {
    const old = pending();
    const payload = kind === 'person' ? voice : suspect;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url.includes('/old/') ? old.response : json(payload('current')),
      ),
    );
    const shown = render(layer(kind, 'old'));
    await screen.findByText('正在加载…');
    shown.rerender(layer(kind, null));
    shown.rerender(layer(kind, 'current'));
    await screen.findByText(
      kind === 'person' ? 'current.m4a' : 'current 的原话',
    );
    await act(async () => old.resolve(payload('old')));
    expect(
      screen.queryByText(kind === 'person' ? 'old.m4a' : 'old 的原话'),
    ).toBeNull();
    expect(
      screen.getByText(kind === 'person' ? 'current.m4a' : 'current 的原话'),
    ).toBeVisible();
  },
);

it.each(['person', 'mixed'] as const)(
  'does not reload a closed %s task after its submission finishes',
  async (kind) => {
    const submission = pending();
    const changed = vi.fn();
    const payload = kind === 'person' ? voice : suspect;
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method !== 'GET') return submission.response;
      return json(payload(url.includes('/old/') ? 'old' : 'current'));
    });
    vi.stubGlobal('fetch', fetch);
    const shown = render(layer(kind, 'old', changed));
    await userEvent.click(
      await screen.findByRole('button', {
        name: kind === 'person' ? '是old' : '其实都是张总',
      }),
    );
    shown.rerender(layer(kind, 'current', changed));
    await screen.findByText(
      kind === 'person' ? 'current.m4a' : 'current 的原话',
    );
    const readsBefore = fetch.mock.calls.filter(
      ([url, init]) => url.includes('/old/') && init?.method === 'GET',
    ).length;
    await act(async () => submission.resolve({}));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    expect(
      fetch.mock.calls.filter(
        ([url, init]) => url.includes('/old/') && init?.method === 'GET',
      ),
    ).toHaveLength(readsBefore);
    expect(
      screen.getByText(kind === 'person' ? 'current.m4a' : 'current 的原话'),
    ).toBeVisible();
  },
);

it.each([false, true])(
  'recovers a concurrent decision while resetting the selection only for a new transcript (%s)',
  async (retranscribed) => {
    let revision = 1;
    const saved: Record<string, unknown>[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/library/people')
          return json({ items: [person('张总')] });
        if (init?.method === 'PUT') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>;
          saved.push(body);
          if (saved.length === 1) {
            revision = 2;
            return json({ detail: '这段录音刚被修改过，请刷新后再确认' }, 409);
          }
          return json({ revision: ++revision });
        }
        return json({
          id: 'recording',
          filename: '周会.m4a',
          status: 'ready',
          transcript_id: retranscribed && revision > 1 ? 't2' : 't1',
          revision,
          speakers: [
            {
              id: 'S1',
              seconds: 60,
              decision: 'none',
              person_id: null,
              rejected: [],
              candidates: [],
              near: false,
              samples: 1,
              sample: false,
              auto: false,
            },
          ],
          segments: [],
        });
      }),
    );
    render(
      <MemoryRouter initialEntries={['/library/recording']}>
        <Routes>
          <Route path="/library/:recordingId" element={<Recording />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByRole('heading', { name: 'S1 是谁？' });
    await userEvent.selectOptions(screen.getByLabelText('这是谁'), '张总');
    await userEvent.click(screen.getByRole('button', { name: '确认是张总' }));
    await screen.findByRole('alert');
    await waitFor(() =>
      expect(screen.getByLabelText('这是谁')).toHaveValue(
        retranscribed ? '' : '张总',
      ),
    );
    if (retranscribed)
      await userEvent.selectOptions(screen.getByLabelText('这是谁'), '张总');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '确认是张总' })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole('button', { name: '确认是张总' }));
    await waitFor(() => expect(saved).toHaveLength(2));
    expect(saved[1]).toMatchObject({
      transcript_id: retranscribed ? 't2' : 't1',
      revision: 2,
      person_id: '张总',
    });
  },
);

it.each(['person', 'mixed'] as const)(
  'reloads a failed %s detail without leaving the current task',
  async (kind) => {
    const payload = kind === 'person' ? voice : suspect;
    let failed = true;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        failed
          ? json({ detail: '服务暂时不可用' }, 503)
          : json(payload('current')),
      ),
    );
    render(layer(kind, 'current'));
    await screen.findByText('服务暂时不可用');
    failed = false;
    await userEvent.click(screen.getByRole('button', { name: '刷新' }));
    expect(
      await screen.findByText(
        kind === 'person' ? 'current.m4a' : 'current 的原话',
      ),
    ).toBeVisible();
    expect(screen.queryByText('服务暂时不可用')).toBeNull();
  },
);

it.each(['person', 'mixed'] as const)(
  'keeps the %s task open after a 409 and retries its current revision',
  async (kind) => {
    const payload = kind === 'person' ? voice : suspect;
    let revision = 1;
    const saved: Record<string, unknown>[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === 'PUT') {
          saved.push(JSON.parse(String(init.body)) as Record<string, unknown>);
          if (saved.length === 1) {
            revision = 2;
            return json({ detail: '这段录音刚被修改过，请重新确认' }, 409);
          }
          return json({});
        }
        return json(payload('current', revision));
      }),
    );
    render(layer(kind, 'current'));
    const name = kind === 'person' ? '是current' : '其实都是张总';
    await userEvent.click(await screen.findByRole('button', { name }));
    await screen.findByText('这段录音刚被修改过，请重新确认');
    await waitFor(() =>
      expect(screen.getByRole('button', { name })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole('button', { name }));
    await waitFor(() => expect(saved).toHaveLength(2));
    expect(saved[0]).toMatchObject({ revision: 1 });
    expect(saved[1]).toMatchObject({ revision: 2 });
  },
);

it.each(['person', 'mixed'] as const)(
  'reports a failed %s submission after its task was closed without changing the next task',
  async (kind) => {
    const submission = pending();
    const payload = kind === 'person' ? voice : suspect;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === 'PUT') return submission.response;
        return json(payload(url.includes('/old/') ? 'old' : 'current'));
      }),
    );
    const shown = render(
      <>
        {layer(kind, 'old')}
        <ToastViewport />
      </>,
    );
    await userEvent.click(
      await screen.findByRole('button', {
        name: kind === 'person' ? '是old' : '其实都是张总',
      }),
    );
    shown.rerender(
      <>
        {layer(kind, 'current')}
        <ToastViewport />
      </>,
    );
    await screen.findByText(
      kind === 'person' ? 'current.m4a' : 'current 的原话',
    );
    await act(async () => submission.resolve({ detail: '修改没有成功' }, 503));
    expect(
      (await screen.findAllByText('刚才的修改未能确认：修改没有成功')).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText(kind === 'person' ? 'current.m4a' : 'current 的原话'),
    ).toBeVisible();
    expect(
      screen.getByRole('button', {
        name: kind === 'person' ? '是current' : '其实都是张总',
      }),
    ).toBeEnabled();
  },
);

it.each(['person', 'mixed'] as const)(
  'releases the %s task controls and distinguishes saved work from a failed list refresh',
  async (kind) => {
    const payload = kind === 'person' ? voice : suspect;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) =>
        json(init?.method === 'PUT' ? {} : payload('current')),
      ),
    );
    const changed = async () => {
      throw new Error('refresh failed');
    };
    render(layer(kind, 'current', changed));
    const name = kind === 'person' ? '是current' : '其实都是张总';
    await userEvent.click(await screen.findByRole('button', { name }));
    await screen.findByText('修改已保存，列表刷新失败');
    expect(screen.getByRole('button', { name })).toBeEnabled();
  },
);

function SwitchRecording() {
  const navigate = useNavigate();
  return (
    <>
      <Button onClick={() => void navigate('/library/current')}>
        切换录音
      </Button>
      <Recording />
    </>
  );
}

it('never shows a previous recording under the current address when its request finishes late', async () => {
  const old = pending();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/people') return json({ items: [] });
      if (url.endsWith('/old')) return old.response;
      return json({
        id: 'current',
        filename: '当前录音.m4a',
        status: 'ready',
        transcript_id: 't-current',
        revision: 1,
        speakers: [],
        segments: [],
      });
    }),
  );
  render(
    <MemoryRouter initialEntries={['/library/old']}>
      <Routes>
        <Route path="/library/:recordingId" element={<SwitchRecording />} />
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole('button', { name: '切换录音' }));
  await screen.findByRole('heading', { name: '当前录音.m4a' });
  await act(async () =>
    old.resolve({
      id: 'old',
      filename: '旧录音.m4a',
      status: 'ready',
      transcript_id: 't-old',
      revision: 1,
      speakers: [],
      segments: [],
    }),
  );
  expect(screen.queryByRole('heading', { name: '旧录音.m4a' })).toBeNull();
  expect(screen.getByRole('heading', { name: '当前录音.m4a' })).toBeVisible();
});
