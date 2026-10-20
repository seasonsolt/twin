import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  Recording,
  sampleWindows,
  type Speaker,
  type Person,
} from '../pages/Recording';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const people: Person[] = ['林舟', '许清禾'].map((name, i) => ({
  id: `p${i}`,
  name,
  persona_id: null,
  speakers: 1,
  seconds: 600,
  samples: 1,
  updating: false,
  auto: false,
  gender: '',
  recording_id: 'r',
  speaker_id: 'S1',
}));
const segments = [
  { start: 26, end: 29, speaker: 'S1', text: '先看进展。' },
  { start: 40, end: 44, speaker: 'S1', text: '再看计划。' },
  { start: 50, end: 52, speaker: 'S2', text: '周三准备好。' },
];
let speakers: Speaker[];
let revision: number;
let fail: boolean;
let requests: Record<string, unknown>[];
beforeEach(() => {
  revision = 1;
  fail = false;
  requests = [];
  speakers = ['S1', 'S2'].map((id) => ({
    id,
    seconds: 300,
    decision: 'none',
    person_id: null,
    rejected: [],
    sample: false,
    auto: false,
    candidates:
      id === 'S1'
        ? [
            { person_id: 'p0', name: '林舟', score: 0.71 },
            { person_id: 'p1', name: '许清禾', score: 0.52 },
          ]
        : [],
    near: true,
    samples: id === 'S1' ? 2 : 1,
  }));
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url === '/api/library/recordings/r')
        return json({
          id: 'r',
          filename: '周会.m4a',
          created_at: '2026-10-15T08:00:00Z',
          duration_s: 600,
          status: 'ready',
          transcript_id: 't',
          revision,
          speakers,
          segments,
        });
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        requests.push(body);
        if (fail) return json({ detail: '保存失败，请再试一次' }, 500);
        const id = url.split('/').at(-1);
        speakers = speakers.map((s) =>
          s.id !== id
            ? s
            : {
                ...s,
                decision:
                  body.action === 'clear'
                    ? 'none'
                    : body.action === 'confirm'
                      ? 'confirmed'
                      : body.action,
                person_id: body.person_id ?? null,
                sample: body.sample ?? false,
                auto: false,
              },
        );
        revision += 1;
        return json({ revision });
      }
      throw new Error(url);
    }),
  );
});
afterEach(() => vi.restoreAllMocks());
function show() {
  return render(
    <MemoryRouter initialEntries={['/library/r']}>
      <Routes>
        <Route path="/library/:recordingId" element={<Recording />} />
      </Routes>
    </MemoryRouter>,
  );
}

it('shows one current speaker and one player; clips change audio and matching transcript without selecting a person', async () => {
  show();
  const current = await screen.findByRole('region', { name: 'S1 是谁？' });
  expect(screen.queryByRole('heading', { name: 'S2 是谁？' })).toBeNull();
  expect(screen.getByRole('region', { name: '接下来' })).toHaveTextContent(
    'S2 · 说了 5 分钟 · 没认出来',
  );
  expect(document.querySelectorAll('audio')).toHaveLength(1);
  const audio = screen.getByLabelText('S1 试听');
  expect(audio).toHaveAttribute('src', expect.stringContaining('/samples/0'));
  expect(within(current).getByText('再看计划。')).toBeInTheDocument();
  const second = within(current).getByRole('button', {
    name: '片段 2 · 00:26',
  });
  await userEvent.click(second);
  expect(audio).toHaveAttribute('src', expect.stringContaining('/samples/1'));
  expect(second).toHaveAttribute('aria-pressed', 'true');
  expect(within(current).getByText('先看进展。')).toBeInTheDocument();
  expect(within(current).queryByText('再看计划。')).toBeNull();
  expect(screen.getByRole('button', { name: '先选一个人' })).toBeDisabled();
  expect(
    screen.getByText('两位很接近，多听一个片段再选。'),
  ).toBeInTheDocument();
  await userEvent.click(
    within(current).getByRole('button', { name: /林舟.*声音像 71%/u }),
  );
  expect(screen.getByRole('button', { name: '确认是林舟' })).toBeEnabled();
});

it('confirms, focuses the next speaker, reopens a previous one, then shows the all-done state', async () => {
  show();
  await userEvent.click(
    await screen.findByRole('button', { name: /林舟.*声音像 71%/u }),
  );
  await userEvent.click(
    screen.getByLabelText('声音清楚，用作这个人的声纹样本'),
  );
  await userEvent.click(screen.getByRole('button', { name: '确认是林舟' }));
  const next = await screen.findByRole('heading', { name: 'S2 是谁？' });
  await waitFor(() => expect(next).toHaveFocus());
  expect(requests[0]).toMatchObject({
    transcript_id: 't',
    revision: 1,
    action: 'confirm',
    person_id: 'p0',
    sample: true,
  });
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1');
  await userEvent.click(screen.getByRole('button', { name: '改 S1' }));
  const reopened = await screen.findByRole('heading', { name: 'S1 是谁？' });
  await waitFor(() => expect(reopened).toHaveFocus());
  expect(requests[1]).toMatchObject({ revision: 2, action: 'clear' });
  await userEvent.click(screen.getByRole('button', { name: '不在名单里' }));
  await screen.findByRole('heading', { name: 'S2 是谁？' });
  await userEvent.click(screen.getByRole('button', { name: '几个人混在一起' }));
  expect(
    await screen.findByText('这段录音的说话人都确认好了'),
  ).toBeInTheDocument();
  expect(document.querySelectorAll('audio')).toHaveLength(0);
  expect(
    screen.getByRole('link', { name: '回团队处理下一项' }),
  ).toHaveAttribute('href', '/team');
  expect(screen.getAllByText('不进任何分身')).toHaveLength(2);
  expect(screen.getByText('完整转写稿（3 段）')).toBeInTheDocument();
});

it('creates a named person with sample opt-in and keeps the current selection when saving fails', async () => {
  show();
  await screen.findByRole('heading', { name: 'S1 是谁？' });
  await userEvent.selectOptions(screen.getByLabelText('这是谁'), 'new');
  expect(screen.getByRole('button', { name: '先选一个人' })).toBeDisabled();
  await userEvent.type(screen.getByLabelText('新人物的名字'), '小陈');
  fail = true;
  await userEvent.click(screen.getByRole('button', { name: '确认是小陈' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('保存失败');
  expect(screen.getByLabelText('新人物的名字')).toHaveValue('小陈');
  fail = false;
  await userEvent.click(screen.getByRole('button', { name: '确认是小陈' }));
  await screen.findByRole('heading', { name: 'S2 是谁？' });
  expect(requests[1]).toMatchObject({
    action: 'confirm',
    new_person: '小陈',
    sample: false,
  });
});

it('derives the existing ten-second windows after merging speech and removing overlap', () => {
  expect(
    sampleWindows(
      [
        { start: 0, end: 4, speaker: 'S1', text: '' },
        { start: 4.2, end: 15, speaker: 'S1', text: '' },
        { start: 6, end: 8, speaker: 'S2', text: '' },
      ],
      'S1',
    ),
  ).toEqual([
    [8, 15],
    [0, 6],
  ]);
  expect(
    sampleWindows([{ start: 0, end: 30, speaker: 'S1', text: '' }], 'S1'),
  ).toEqual([
    [0, 10],
    [10, 20],
    [20, 30],
  ]); // Three moments of one run a few seconds over ten would be nearly the same sound: the longest runs give one each.
  expect(
    sampleWindows([{ start: 0, end: 14.1, speaker: 'S1', text: '' }], 'S1'),
  ).toEqual([[0, 10]]);
  expect(
    sampleWindows(
      [
        { start: 0, end: 14.1, speaker: 'S1', text: '' },
        { start: 20, end: 33.6, speaker: 'S1', text: '' },
        { start: 40, end: 51.5, speaker: 'S1', text: '' },
        { start: 60, end: 69.6, speaker: 'S1', text: '' },
      ],
      'S1',
    ),
  ).toEqual([
    [0, 10],
    [20, 30],
    [40, 50],
  ]);
});

it('lets someone in a colleague’s meeting read it and say a speaker given to them is not them', async () => {
  const user = userEvent.setup();
  let gone = false;
  const posted: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url === '/api/library/recordings/r') {
        if (gone) return json({ detail: '找不到这段录音' }, 404);
        return json({
          id: 'r',
          filename: '周会.m4a',
          created_at: '2026-10-15T08:00:00Z',
          duration_s: 600,
          status: 'ready',
          transcript_id: 't',
          revision: 2,
          can_edit: false,
          mine: ['S2'],
          // Whom the voices resemble is not sent to someone who only reads it.
          speakers: speakers.map(({ id, seconds, samples }, i) => ({
            id,
            seconds,
            samples,
            decision: 'confirmed',
            person_id: `p${i}`,
            sample: false,
            auto: false,
          })),
          segments,
        });
      }
      if (init?.method === 'POST') {
        posted.push(url);
        gone = true;
        return json({ disputed: true });
      }
      throw new Error(url);
    }),
  );
  show();
  await screen.findByText(/你参加了这场会/u);
  expect(screen.queryByRole('region', { name: /是谁？/u })).toBeNull();
  const list = screen.getByRole('region', { name: '说话人' });
  expect(within(list).getByText('林舟')).toBeInTheDocument();
  expect(within(list).getAllByRole('button')).toHaveLength(1);
  await user.click(within(list).getByRole('button', { name: 'S2 不是我' }));
  await screen.findByText('已经告诉上传的同事');
  expect(posted).toEqual(['/api/library/recordings/r/speakers/S2/not-me']);
});
