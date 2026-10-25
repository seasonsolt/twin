import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import {
  ConfirmProvider,
  ToastViewport,
  TooltipProvider,
} from '../components/ui';
import { uploadMedia } from '../lib/mediaUpload';
import { useAuth } from '../stores/auth';
import { usePersonas, type Persona } from '../stores/personas';
import { useUploadStore } from '../stores/uploads';

vi.mock('../lib/mediaUpload', async (original) => ({
  ...(await original<typeof import('../lib/mediaUpload')>()),
  uploadMedia: vi.fn(),
}));

const json = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200 });
const twin = (change: Partial<Persona>): Persona => ({
  id: 'default',
  name: '林舟',
  avatar_url: null,
  sources: 3,
  created_at: '',
  is_default: true,
  can_manage: true,
  ...change,
});
const meeting = (name: string) => new File(['a'], name, { type: 'audio/mp4' });

function Where() {
  const location = useLocation();
  return <p>在{location.pathname}</p>;
}

let finish: (result?: { mine: boolean }) => void;
beforeEach(() => {
  // A send that goes on until it is finished, or stopped.
  vi.mocked(uploadMedia).mockImplementation(
    (_file, signal) =>
      new Promise((resolve, reject) => {
        finish = (result = { mine: true }) => resolve(result as never);
        signal.addEventListener('abort', () =>
          reject(new DOMException('stopped', 'AbortError')),
        );
      }),
  );
  useAuth.setState({
    identity: { email: null, admin: false, auth_enabled: false },
  });
  usePersonas.setState({ id: 'default', items: [twin({})] });
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library')
        return json({
          recordings: [],
          pending: 0,
          max_pending: 20,
          asr: true,
          capacity: {
            free_bytes: 0,
            arriving_bytes: 0,
            arriving: 0,
            headroom_bytes: 0,
          },
        });
      if (url === '/api/library/people') return json({ items: [] });
      if (url.startsWith('/api/library/review'))
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (url === '/api/personas') return json(usePersonas.getState().items);
      return json({});
    }),
  );
});
afterEach(() => {
  useAuth.setState({ identity: null });
  vi.restoreAllMocks();
});

const show = () =>
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="chat" element={<Where />} />
              <Route path="library" element={<Where />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
      <ToastViewport />
    </TooltipProvider>,
  );
// Files dropped on the page, away from any drop area of its own.
const choose = async (...files: File[]) => {
  await screen.findByRole('navigation', { name: '主导航' });
  fireEvent.drop(window, { dataTransfer: { types: ['Files'], files } });
};

it('says from any page that what was dropped is not a recording, and sends nothing', async () => {
  show();
  await choose(new File(['x'], '截图.png'));
  // Shown and announced once each.
  expect(
    await screen.findAllByText('已跳过 1 个不是音视频的文件'),
  ).toHaveLength(2);
  expect(uploadMedia).not.toHaveBeenCalled();
  // Said once: not left standing for the next page to show again.
  expect(useUploadStore.getState().notice).toBe('');
});

it('says again the same thing about a second file dropped after the first', async () => {
  show();
  await choose(new File(['x'], '截图.png'));
  await screen.findAllByText('已跳过 1 个不是音视频的文件');
  await choose(new File(['y'], '截图2.png'));
  await waitFor(() =>
    expect(screen.getAllByText('已跳过 1 个不是音视频的文件').length).toBe(4),
  );
});

it('shows what is being sent in the background card, and says when a colleague had sent the same meeting first', async () => {
  show();
  await choose(meeting('周会.m4a'));
  expect(uploadMedia).toHaveBeenCalledTimes(1);
  expect(await screen.findByText('1 项上传中')).toBeVisible();
  await act(async () => finish({ mine: false }));
  expect(
    (await screen.findAllByText('「周会.m4a」已经有同事上传过，由 TA 整理'))
      .length,
  ).toBeGreaterThan(0);
  await waitFor(() => expect(screen.queryByText('1 项上传中')).toBeNull());
});

it('lets the background card go, and stop polling fast, once uploading is stopped', async () => {
  show();
  await choose(meeting('周会.m4a'), meeting('周报.m4a'));
  expect(await screen.findByText('2 项上传中')).toBeVisible();
  act(() => useUploadStore.getState().stop());
  await waitFor(() => expect(screen.queryByText(/上传中/u)).toBeNull());
  // The files stay listed, as stopped, to be added again.
  expect(useUploadStore.getState().picks.map((p) => p.stopped)).toEqual([
    true,
    true,
  ]);
  expect(screen.queryByText(/上传失败/u)).toBeNull();
  expect(screen.queryByText('后台')).toBeNull();
});

it('takes a dropped transcript to the library to be looked at, instead of skipping it', async () => {
  show();
  const transcript = new File(['x'], '妙记.docx');
  const said = () => screen.queryAllByText(/已跳过/u).length;
  const before = said();
  await choose(transcript);
  expect(await screen.findByText('在/library')).toBeVisible();
  expect(useUploadStore.getState().transcripts).toEqual([transcript]);
  expect(uploadMedia).not.toHaveBeenCalled();
  expect(said()).toBe(before);
});
