import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import {
  ConfirmProvider,
  FileDrop,
  ToastViewport,
  TooltipProvider,
} from '../components/ui';
import { uploadMedia } from '../lib/mediaUpload';
import { useAuth } from '../stores/auth';
import { useUploadStore } from '../stores/uploads';
import { usePersonas, type Persona } from '../stores/personas';

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
const recording = new File(['a'], '周会.m4a', { type: 'audio/mp4' });
const picture = new File(['b'], '截图.png', { type: 'image/png' });
const carrying = (...files: File[]) => ({
  dataTransfer: { types: ['Files'], files },
});

let finish: () => void;
let handled: File[][];
beforeEach(() => {
  handled = [];
  vi.mocked(uploadMedia).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = () => resolve({ mine: true } as never);
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
});

const show = (entry = '/team') =>
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route
                path="team"
                element={
                  <FileDrop
                    label="这一页自己的拖放区"
                    title="拖到这里"
                    onFiles={(files) => handled.push(files)}
                  />
                }
              />
              <Route path="chat" element={<p>聊天页</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
      <ToastViewport />
    </TooltipProvider>,
  );

it('takes a recording dropped anywhere on the page into the uploads the side bar shows', async () => {
  show('/chat');
  await screen.findByRole('link', { name: '对话' });
  const nav = screen.getByRole('navigation', { name: '主导航' });
  expect(screen.queryByText('松开即可上传会议录音')).toBeNull();
  fireEvent.dragEnter(nav, carrying(recording));
  expect(screen.getByText('松开即可上传会议录音')).toBeVisible();
  fireEvent.drop(nav, carrying(recording));
  expect(screen.queryByText('松开即可上传会议录音')).toBeNull();
  expect(uploadMedia).toHaveBeenCalledTimes(1);
  expect(vi.mocked(uploadMedia).mock.calls[0]![0]).toBe(recording);
  expect(await screen.findByText('1 项上传中')).toBeVisible();
  await act(async () => finish());
});

it('draws nothing over a page whose own drop area shows where the files go, and still takes a drop beside it', async () => {
  show();
  await screen.findByRole('region', { name: '这一页自己的拖放区' });
  const nav = screen.getByRole('navigation', { name: '主导航' });
  fireEvent.dragEnter(nav, carrying(recording));
  expect(screen.queryByText('松开即可上传会议录音')).toBeNull();
  fireEvent.drop(nav, carrying(recording));
  expect(uploadMedia).toHaveBeenCalledTimes(1);
  await act(async () => finish());
});

it('hands a transcript dropped outside the library to its import dialog instead of skipping it', async () => {
  show('/chat');
  await screen.findByRole('link', { name: '对话' });
  const transcript = new File(['x'], '周会纪要.docx');
  fireEvent.drop(
    screen.getByRole('navigation', { name: '主导航' }),
    carrying(transcript),
  );
  expect(useUploadStore.getState().transcripts).toEqual([transcript]);
  expect(uploadMedia).not.toHaveBeenCalled();
  expect(screen.queryByText(/已跳过/u)).toBeNull();
});

it('says so when what was dropped is not a recording, and uploads nothing', async () => {
  show();
  await screen.findByRole('link', { name: '对话' });
  fireEvent.drop(
    screen.getByRole('navigation', { name: '主导航' }),
    carrying(picture),
  );
  // The notice is shown and announced once each.
  expect(
    await screen.findAllByText('已跳过 1 个不是音视频的文件'),
  ).toHaveLength(2);
  expect(uploadMedia).not.toHaveBeenCalled();
});

it('leaves a drop area on the page to take its own files, without uploading them as well', async () => {
  show();
  const zone = await screen.findByRole('region', {
    name: '这一页自己的拖放区',
  });
  fireEvent.dragEnter(zone, carrying(recording));
  // The area under the pointer says so itself; the page-wide hint steps aside.
  expect(screen.queryByText('松开即可上传会议录音')).toBeNull();
  fireEvent.drop(zone, carrying(recording));
  expect(handled).toEqual([[recording]]);
  expect(uploadMedia).not.toHaveBeenCalled();
});

it('ignores a drag that carries no files', async () => {
  show();
  await screen.findByRole('link', { name: '对话' });
  const nav = screen.getByRole('navigation', { name: '主导航' });
  fireEvent.dragEnter(nav, {
    dataTransfer: { types: ['text/plain'], files: [] },
  });
  expect(screen.queryByText('松开即可上传会议录音')).toBeNull();
});

it('gives a guest no page-wide drop', async () => {
  usePersonas.setState({
    id: 'p-public',
    items: [twin({ id: 'p-public', name: '朋友', can_manage: false })],
  });
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="chat" element={<p>聊天页</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
  await screen.findByText('聊天页');
  fireEvent.dragEnter(document.body, carrying(recording));
  fireEvent.drop(document.body, carrying(recording));
  expect(screen.queryByText('松开即可上传会议录音')).toBeNull();
  expect(uploadMedia).not.toHaveBeenCalled();
});
