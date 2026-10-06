import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, toast } from '../components/ui';
import { ASSETS_CHANGED } from '../features/assets/SelfAssets';
import { MediaClaim, RecordingShortcut } from '../features/sources/MediaClaim';
import { setPersonaId } from '../lib/persona';
import { Memories } from '../pages/Memories';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown) => new Response(JSON.stringify(value));
const base = '/api/persona/sources/recording';
let chosen: string | null | undefined;
let fetcher: ReturnType<typeof vi.fn>;
const claim = () => ({
  speaker: chosen ?? null,
  confirmed: chosen !== undefined,
  automatic: false,
  pending: false,
  speakers: [
    {
      id: 'S1',
      seconds: 24,
      similarity: 0.7,
      suggested: true,
      samples: [
        base + '/samples/S1/0',
        base + '/samples/S1/1',
        base + '/samples/S1/2',
      ],
    },
    {
      id: 'S2',
      seconds: 12,
      similarity: 0.6,
      suggested: false,
      samples: [base + '/samples/S2/0'],
    },
  ],
  voices: chosen ? [{ id: 'v1', url: base + '/candidates/voice/v1' }] : [],
  portraits: chosen
    ? [{ id: 'p1', url: base + '/candidates/portrait/p1' }]
    : [],
  candidate_error: null,
});
beforeEach(() => {
  chosen = undefined;
  setPersonaId('p-test');
  vi.mocked(toast).mockClear();
  fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url === '/api/persona/sources')
      return json([
        {
          source_id: 'recording',
          title: '我的录音',
          first_date: null,
          detected_kind_label: '音频',
          kind: 'audio',
          status: chosen === undefined ? 'needs_speaker' : 'remembered',
          remembered: 1,
          media_sha: 'sha',
          voice_candidates: chosen ? 1 : 0,
          portrait_candidates: chosen ? 1 : 0,
        },
      ]);
    if (url === '/api/persona/processing') return json({ state: 'idle' });
    if (url === '/api/status')
      return json({ counts: { sources: 1, items: 0 }, egress: [] });
    if (url === base + '/text') return new Response('本人：[00:00] 你好');
    if (url === base + '/speakers') return json(claim());
    if (url === base + '/speaker') {
      chosen = JSON.parse(init.body as string).speaker;
      return json(claim());
    }
    if (url.startsWith(base + '/adopt-'))
      return json({ voice: { id: 'self-v1' }, portrait: { sha: 'p1' } });
    throw new Error(url);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => setPersonaId('default'));

it('opens the first pending recording from the banner, confirms a speaker, and adopts both candidates', async () => {
  const changed = vi.fn();
  window.addEventListener(ASSETS_CHANGED, changed);
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/memories']}>
        <Memories />
      </MemoryRouter>
    </ConfirmProvider>,
  );
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: '有 1 段录音需要确认哪位是你' }),
  );
  const detail = await screen.findByRole('dialog', { name: '我的录音' });
  expect(screen.getByText('待确认')).toBeVisible();
  expect(await within(detail).findByText('请确认哪位是你')).toBeVisible();
  expect(within(detail).getByText('像你')).toBeVisible();
  await user.click(within(detail).getByRole('radio', { name: /S1/ }));
  await within(detail).findByRole('button', { name: '用这段做声音' });
  expect(within(detail).getByRole('radio', { name: /S1/ })).toBeChecked();
  expect(
    screen.queryByRole('button', { name: '有 1 段录音需要确认哪位是你' }),
  ).not.toBeInTheDocument();
  const audio = within(detail).getByLabelText('声音候选 1');
  expect(audio).toHaveAttribute(
    'src',
    base + '/candidates/voice/v1?persona=p-test',
  );
  expect(audio).not.toHaveAttribute('autoplay');
  expect(within(detail).getByAltText('形象候选 1')).toHaveAttribute(
    'src',
    base + '/candidates/portrait/p1?persona=p-test',
  );
  await user.click(
    within(detail).getByRole('button', { name: '用这段做声音' }),
  );
  await waitFor(() =>
    expect(toast).toHaveBeenCalledWith('已更新你的声音', 'success'),
  );
  await waitFor(() =>
    expect(
      within(detail).getByRole('button', { name: '用这张做形象' }),
    ).not.toBeDisabled(),
  );
  await user.click(
    within(detail).getByRole('button', { name: '用这张做形象' }),
  );
  await waitFor(() =>
    expect(toast).toHaveBeenCalledWith('已更新你的形象', 'success'),
  );
  expect(changed).toHaveBeenCalledTimes(2);
  const mutations = fetcher.mock.calls.filter(
    ([, init]) => init.method === 'PUT' || init.method === 'POST',
  );
  expect(mutations.map(([url]) => url)).toEqual([
    base + '/speaker',
    base + '/adopt-voice',
    base + '/adopt-portrait',
  ]);
  for (const [, init] of mutations)
    expect(new Headers(init.headers).get('X-Twin-Persona')).toBe('p-test');
  window.removeEventListener(ASSETS_CHANGED, changed);
});

it('cycles short samples only on play clicks and can save observer material', async () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  render(<MediaClaim sourceId="recording" />);
  const user = userEvent.setup();
  await screen.findByText('请确认哪位是你');
  expect(play).not.toHaveBeenCalled();
  const sample = screen.getByLabelText('S1 试听');
  for (let i = 0; i < 3; i++) {
    await user.click(screen.getByRole('button', { name: '试听 S1' }));
    expect(sample).toHaveAttribute(
      'src',
      base + `/samples/S1/${i}?persona=p-test`,
    );
  }
  expect(play).toHaveBeenCalledTimes(3);
  await user.click(screen.getByRole('radio', { name: '都不是我（旁观资料）' }));
  await waitFor(() => expect(chosen).toBeNull());
  await waitFor(() =>
    expect(
      screen.getByRole('radio', { name: '都不是我（旁观资料）' }),
    ).toBeChecked(),
  );
  expect(
    screen.queryByRole('button', { name: '用这段做声音' }),
  ).not.toBeInTheDocument();
  play.mockRestore();
});

it('shows the onboarding recording shortcut only when candidates exist', async () => {
  chosen = 'S1';
  render(<RecordingShortcut />);
  await screen.findByText('从你的视频里挑一个');
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '我的录音' }));
  const dialog = await screen.findByRole('dialog', {
    name: '从你的视频里挑一个',
  });
  const adopt = await within(dialog).findByRole('button', {
    name: '用这段做声音',
  });
  // The candidate can mount before the dialog's opacity animation starts.
  await waitFor(() => expect(adopt).toBeVisible());
});

it('hides the onboarding recording shortcut when no candidates exist', async () => {
  await act(async () => {
    render(<RecordingShortcut />);
  });
  expect(fetcher).toHaveBeenCalledWith(
    '/api/persona/sources',
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
  expect(screen.queryByText('从你的视频里挑一个')).not.toBeInTheDocument();
});
