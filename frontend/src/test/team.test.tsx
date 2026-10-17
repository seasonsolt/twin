import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Team } from '../features/library/Team';
import { Recording, type Person, type Speaker } from '../pages/Recording';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const speaker = (change: Partial<Speaker>): Speaker => ({
  id: 'S1',
  seconds: 300,
  decision: 'none',
  person_id: null,
  rejected: [],
  sample: false,
  candidates: [],
  near: false,
  samples: 2,
  ...change,
});
const person = (change: Partial<Person>): Person => ({
  id: 'per_1',
  name: '张总',
  persona_id: null,
  speakers: 1,
  seconds: 600,
  samples: 1,
  updating: false,
  ...change,
});
let revision: number;
let people: Person[];
let puts: Record<string, unknown>[];
beforeEach(() => {
  revision = 3;
  people = [person({}), person({ id: 'per_2', name: '李总' })];
  puts = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url === '/api/library/recordings/rec_1')
        return json({
          id: 'rec_1',
          filename: '周会.m4a',
          status: 'ready',
          transcript_id: 't1',
          revision,
          speakers: [
            speaker({
              candidates: [{ person_id: 'per_1', name: '张总', score: 0.82 }],
            }),
            speaker({ id: 'S2', decision: 'confirmed', person_id: 'per_2' }),
          ],
          segments: [
            { start: 0, end: 4, text: '先看预算。', speaker: 'S1' },
            { start: 4, end: 9, text: '我反对压缩研发。', speaker: 'S2' },
          ],
        });
      if (url.startsWith('/api/library/recordings/rec_1/speakers/')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        puts.push({ url, ...body });
        if (body.revision !== revision)
          return json({ detail: '这段录音刚被修改过，请刷新后再确认' }, 409);
        revision += 1;
        return json({ revision, person_id: body.person_id ?? null });
      }
      throw new Error(url);
    }),
  );
});
afterEach(() => vi.restoreAllMocks());

const showRecording = () =>
  render(
    <MemoryRouter initialEntries={['/library/rec_1']}>
      <Routes>
        <Route path="/library/:recordingId" element={<Recording />} />
      </Routes>
    </MemoryRouter>,
  );

it('lets the owner hear a speaker and confirm who it is, without picking for them', async () => {
  showRecording();
  const card = (await screen.findByRole('heading', { name: 'S1' })).closest(
    'li',
  )!;
  const scope = within(card);
  expect(scope.getAllByLabelText(/S1 试听/u)).toHaveLength(2);
  expect(scope.getByText('张总 82%')).toBeInTheDocument();
  // A voice match is only a hint: nothing is chosen until the owner chooses.
  expect(scope.getByLabelText('这是谁')).toHaveValue('');
  expect(scope.getByRole('button', { name: '确认' })).toBeDisabled();
  await userEvent.selectOptions(scope.getByLabelText('这是谁'), 'per_1');
  await userEvent.click(scope.getByLabelText(/用作声纹样本/u));
  await userEvent.click(scope.getByRole('button', { name: '确认' }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0]).toMatchObject({
    url: '/api/library/recordings/rec_1/speakers/S1',
    transcript_id: 't1',
    revision: 3,
    action: 'confirm',
    person_id: 'per_1',
    sample: true,
  });
  // The transcript names confirmed speakers.
  expect(screen.getByText(/李总：/u)).toBeInTheDocument();
});

it('refuses a decision on an outdated page and reloads it', async () => {
  showRecording();
  const card = (await screen.findByRole('heading', { name: 'S1' })).closest(
    'li',
  )!;
  revision = 4; // Changed elsewhere meanwhile.
  await userEvent.click(
    within(card).getByRole('button', { name: '几个人混在一起' }),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent('请刷新后再确认');
  await userEvent.click(
    within(
      (await screen.findByRole('heading', { name: 'S1' })).closest('li')!,
    ).getByRole('button', { name: '不是张总' }),
  );
  await waitFor(() => expect(puts).toHaveLength(2));
  expect(puts[1]).toMatchObject({
    revision: 4,
    action: 'reject',
    person_id: 'per_1',
  });
});

it('creates a twin for a confirmed person and shows when its memory is updating', async () => {
  const created: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library/people') return json({ items: people });
      if (url === '/api/library/review')
        return json({
          items: [
            {
              ...speaker({
                candidates: [{ person_id: 'per_1', name: '张总', score: 0.7 }],
              }),
              recording_id: 'rec_9',
              filename: '月会.m4a',
            },
          ],
        });
      if (
        url === '/api/library/people/per_1/persona' &&
        init?.method === 'POST'
      ) {
        created.push(url);
        people = [person({ persona_id: 'p-1', updating: true }), people[1]];
        return json({ persona_id: 'p-1', new: true });
      }
      if (url === '/api/personas') return json({ items: [], default: null });
      throw new Error(url);
    }),
  );
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Team version={0} />
      </ConfirmProvider>
    </MemoryRouter>,
  );
  expect(await screen.findByText('像张总 70%')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '去听一听' })).toHaveAttribute(
    'href',
    '/library/rec_9',
  );
  const row = screen.getByText('张总', { selector: 'p' }).closest('li')!;
  await userEvent.click(within(row).getByRole('button', { name: '生成分身' }));
  expect(await screen.findByText('记忆更新中')).toBeInTheDocument();
  expect(created).toHaveLength(1);
});
