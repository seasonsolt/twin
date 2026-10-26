import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
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
type Kind = 'recording' | 'person' | 'mixed';
beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
});
const kinds: Kind[] = ['recording', 'person', 'mixed'];
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const person: Person = {
  id: 'owner',
  name: '张总',
  persona_id: null,
  speakers: 1,
  seconds: 60,
  samples: 0,
  updating: false,
  auto: false,
  gender: '',
  recording_id: 'rec',
  speaker_id: 'S1',
};
const suspect: SuspectSpeaker = {
  recording_id: 'rec',
  filename: '周会.m4a',
  transcript_id: 't1',
  revision: 1,
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
      text: '这是一段原话',
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
};
function server() {
  const state = {
    revision: 1,
    transcript: 't1',
    committed: false,
    commitOnWrite: true,
    loseResponse: false,
    readFailure: false,
    reads: 0,
    writes: 0,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        state.writes += 1;
        if (state.commitOnWrite) {
          state.committed = true;
          state.revision += 1;
        }
        if (state.loseResponse)
          throw new TypeError('connection lost after commit');
        return json({ revision: state.revision });
      }
      if (url === '/api/library/people') return json({ items: [person] });
      state.reads += 1;
      if (state.readFailure)
        return json({ detail: '暂时无法读取最新结果' }, 503);
      if (url.endsWith('/voice'))
        return json({
          samples: [],
          checks: state.committed
            ? []
            : [
                {
                  recording_id: 'rec',
                  filename: '周会.m4a',
                  transcript_id: state.transcript,
                  revision: state.revision,
                  speaker_id: 'S1',
                  seconds: 60,
                  tier: 'high',
                  score: 0.9,
                  lead: 0.3,
                },
              ],
        });
      if (url.endsWith('/units'))
        return json({
          ...suspect,
          transcript_id: state.transcript,
          revision: state.revision,
          units: suspect.units.map((unit) => ({
            ...unit,
            fix: state.committed ? 'keep' : null,
          })),
        });
      return json({
        id: 'rec',
        filename: '周会.m4a',
        status: 'ready',
        transcript_id: state.transcript,
        revision: state.revision,
        speakers: [
          {
            id: 'S1',
            seconds: 60,
            decision: state.committed ? 'confirmed' : 'none',
            person_id: state.committed ? 'owner' : null,
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
  return state;
}
function show(kind: Kind, onChanged: () => Promise<void> | void = () => {}) {
  return render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/library/rec']}>
        {kind === 'person' ? (
          <PersonVoice
            person={person}
            onClose={() => {}}
            onChanged={onChanged}
          />
        ) : kind === 'mixed' ? (
          <MixedSpeaker
            suspect={suspect}
            onClose={() => {}}
            onChanged={onChanged}
          />
        ) : (
          <Routes>
            <Route path="/library/:recordingId" element={<Recording />} />
          </Routes>
        )}
      </MemoryRouter>
    </ConfirmProvider>,
  );
}
const action = (kind: Kind) =>
  kind === 'mixed'
    ? '其实都是张总'
    : kind === 'person'
      ? '是张总'
      : '确认是张总';
async function ready(kind: Kind) {
  if (kind === 'recording') {
    await screen.findByLabelText('这是谁');
    await userEvent.selectOptions(screen.getByLabelText('这是谁'), 'owner');
  } else await screen.findByRole('button', { name: action(kind) });
}
async function assertCurrent(kind: Kind) {
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: action(kind) })).toBeNull(),
  );
  if (kind === 'mixed')
    expect(screen.getByRole('button', { name: '撤销' })).toBeEnabled();
  if (kind === 'recording')
    expect(screen.getByText('已确认 1 / 1 位')).toBeVisible();
}

it.each(kinds)(
  'reads the authoritative %s result after the server commits but its response is lost',
  async (kind) => {
    const state = server();
    state.loseResponse = true;
    show(kind);
    await ready(kind);
    await userEvent.click(screen.getByRole('button', { name: action(kind) }));
    await assertCurrent(kind);
    expect(
      screen.queryByText('无法连接本地服务，请检查服务是否启动'),
    ).toBeNull();
    expect(state.writes).toBe(1);
    expect(state.reads).toBeGreaterThan(1);
  },
);

it.each([false, true])(
  'recovers a lost not-me response when the withdrawn recording is no longer visible (delayed read=%s)',
  async (delayed) => {
    let committed = false;
    let readFailure = false;
    let writes = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === 'POST') {
          writes += 1;
          committed = true;
          readFailure = delayed;
          throw new TypeError('lost response after withdrawal');
        }
        if (url === '/api/library/people') return json({ items: [person] });
        if (readFailure) return json({ detail: '暂时无法读取最新结果' }, 503);
        if (committed) return json({ detail: '录音不存在' }, 404);
        return json({
          id: 'rec',
          filename: '周会.m4a',
          status: 'ready',
          transcript_id: 't1',
          revision: 1,
          can_edit: false,
          mine: ['S1'],
          speakers: [
            {
              id: 'S1',
              decision: 'confirmed',
              person_id: 'owner',
              seconds: 60,
            },
          ],
          segments: [],
        });
      }),
    );
    show('recording');
    await userEvent.click(
      await screen.findByRole('button', { name: 'S1 不是我' }),
    );
    if (delayed) {
      await screen.findByText('修改结果未确认，请刷新后再操作');
      expect(screen.getByRole('button', { name: 'S1 不是我' })).toBeDisabled();
      readFailure = false;
      await userEvent.click(screen.getByRole('button', { name: '刷新' }));
    }
    await screen.findByText('已经告诉上传的同事');
    expect(screen.queryByRole('button', { name: 'S1 不是我' })).toBeNull();
    expect(writes).toBe(1);
  },
);

it.each(kinds)(
  'blocks a stale %s after a successful write cannot be read back, and refreshes without submitting again',
  async (kind) => {
    const state = server();
    show(kind);
    await ready(kind);
    state.readFailure = true;
    await userEvent.click(screen.getByRole('button', { name: action(kind) }));
    expect(await screen.findByText(/修改已保存/u)).toBeVisible();
    expect(screen.getByRole('button', { name: action(kind) })).toBeDisabled();
    const refresh = screen.getByRole('button', { name: '刷新' });
    expect(refresh).toBeEnabled();
    state.readFailure = false;
    await userEvent.click(refresh);
    await assertCurrent(kind);
    expect(screen.queryByText(/修改已保存/u)).toBeNull();
    expect(state.writes).toBe(1);
  },
);

it.each(kinds)(
  'does not claim a %s decision was saved when recovery finds it still open',
  async (kind) => {
    const state = server();
    state.commitOnWrite = false;
    state.loseResponse = true;
    show(kind);
    await ready(kind);
    await userEvent.click(screen.getByRole('button', { name: action(kind) }));
    await waitFor(() => expect(state.reads).toBeGreaterThan(1));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: action(kind) })).toBeEnabled(),
    );
    expect(screen.queryByText(/修改已保存/u)).toBeNull();
    expect(state.writes).toBe(1);
  },
);

it.each(['person', 'mixed'] as const)(
  'follows another window resolving its %s task when focus returns',
  async (kind) => {
    const state = server();
    show(kind);
    await ready(kind);
    state.committed = true;
    state.revision += 1;
    await act(async () => window.dispatchEvent(new Event('focus')));
    await assertCurrent(kind);
    expect(state.writes).toBe(0);
  },
);

it.each(kinds)(
  'keeps a %s write unconfirmed while both response and recovery read are unavailable',
  async (kind) => {
    const state = server();
    state.loseResponse = true;
    show(kind);
    await ready(kind);
    state.readFailure = true;
    await userEvent.click(screen.getByRole('button', { name: action(kind) }));
    expect(await screen.findByText(/修改结果未确认/u)).toBeVisible();
    expect(screen.queryByText(/修改已保存/u)).toBeNull();
    expect(screen.getByRole('button', { name: action(kind) })).toBeDisabled();
    state.readFailure = false;
    await userEvent.click(screen.getByRole('button', { name: '刷新' }));
    await assertCurrent(kind);
    expect(state.writes).toBe(1);
  },
);

it.each(['person', 'mixed'] as const)(
  'retries a failed %s parent refresh when the owner refreshes its task',
  async (kind) => {
    server();
    const changed = vi
      .fn()
      .mockRejectedValueOnce(new Error('list unavailable'))
      .mockResolvedValue(undefined);
    show(kind, changed);
    await ready(kind);
    await userEvent.click(screen.getByRole('button', { name: action(kind) }));
    await screen.findByText('修改已保存，列表刷新失败');
    await userEvent.click(screen.getByRole('button', { name: '刷新' }));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(2));
    expect(screen.queryByText('修改已保存，列表刷新失败')).toBeNull();
  },
);

it.each(['person', 'mixed'] as const)(
  'ignores an older %s list refresh failure after a new answer was saved',
  async (kind) => {
    const state = server();
    state.readFailure = true;
    let fail!: (error: Error) => void;
    const changed = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<void>((_resolve, reject) => {
            fail = reject;
          }),
      )
      .mockResolvedValue(undefined);
    show(kind, changed);
    await screen.findByText('暂时无法读取最新结果');
    state.readFailure = false;
    await userEvent.click(screen.getByRole('button', { name: '刷新' }));
    await ready(kind);
    await userEvent.click(screen.getByRole('button', { name: action(kind) }));
    await assertCurrent(kind);
    await act(async () => fail(new Error('old refresh failed')));
    expect(screen.queryByText('列表刷新失败，请重试')).toBeNull();
    expect(state.writes).toBe(1);
  },
);

it.each([false, true])(
  'refreshes a recording on focus while preserving its selection only for the same transcript (%s)',
  async (retranscribed) => {
    const state = server();
    show('recording');
    await ready('recording');
    const selected = screen.getByLabelText('这是谁');
    state.revision = 2;
    state.transcript = retranscribed ? 't2' : 't1';
    const before = state.reads;
    await act(async () => window.dispatchEvent(new Event('focus')));
    await waitFor(() => expect(state.reads).toBeGreaterThan(before));
    expect(screen.getByLabelText('这是谁')).toHaveValue(
      retranscribed ? '' : 'owner',
    );
    if (!retranscribed) expect(screen.getByLabelText('这是谁')).toBe(selected);
  },
);
