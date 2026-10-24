import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { Library, type LibraryState, type Recording } from '../pages/Library';
import { resetTeam, useTeam } from '../stores/team';
import { useUploadStore } from '../stores/uploads';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const transcript: Recording = {
  id: 'rec_t',
  filename: '客户访谈.txt',
  size: 10,
  kind: 'transcript',
  status: 'ready',
  error: '',
  duration_s: 2400,
  transcribed_s: 2400,
  speakers: 3,
  segments: 90,
  created_at: '2026-10-11T00:00:00+00:00',
  people: ['林舟', '许清禾', '周石言'],
  unsettled: 0,
};
const preview = {
  title: '运营周会-10月18日',
  date: '2026-10-18',
  speakers: [
    {
      label: '林舟',
      segments: 23,
      sample: '大家好',
      person: { id: 'per_lin', name: '林舟' },
    },
    {
      label: '许清禾',
      segments: 17,
      sample: '我这边周三前补齐',
      person: { id: 'per_xu', name: '许清禾' },
    },
    {
      label: '说话人 3',
      segments: 6,
      sample: '下周把渠道数据拉一下',
      person: null,
    },
    {
      label: 'Kevin',
      segments: 4,
      sample: '合同这周能签吗',
      person: null,
    },
  ],
};
const members = [
  { id: 'per_lin', name: '林舟' },
  { id: 'per_zhou', name: '周石言' },
  { id: 'per_chen', name: '陈一' },
];
let state: LibraryState;
let sent: FormData | null;
// The server refusing the file (the queue or the disk is full), when it reads it or when it is brought in.
let refusal: { status: number; detail: string; preview?: boolean } | null;
beforeEach(() => {
  resetTeam();
  localStorage.clear();
  sent = null;
  refusal = null;
  useTeam.setState({ people: members as never });
  state = {
    recordings: [],
    pending: 0,
    max_pending: 20,
    asr: true,
    capacity: {
      free_bytes: 50 * 1024 ** 3,
      arriving_bytes: 0,
      arriving: 0,
      headroom_bytes: 20 * 1024 ** 3,
    },
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/library') return json(state);
      if (url === '/api/library/recollect') return json({ recordings: [] });
      if (url === '/api/library/transcripts/preview')
        return refusal?.preview
          ? json({ detail: refusal.detail }, refusal.status)
          : json(preview);
      if (url === '/api/library/transcripts') {
        sent = init?.body as FormData;
        if (refusal && !refusal.preview)
          return json({ detail: refusal.detail }, refusal.status);
        state.recordings = [transcript];
        return json(
          { ...transcript, new: true, decided: 4, unsettled: 0 },
          201,
        );
      }
      if (url.startsWith('/api/library/people'))
        return json({ items: members });
      if (
        url.startsWith('/api/library/people') ||
        url.startsWith('/api/library/review')
      )
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      throw new Error(url);
    }),
  );
});
afterEach(() => vi.restoreAllMocks());

const show = () =>
  render(
    <MemoryRouter>
      <ConfirmProvider>
        <Library />
      </ConfirmProvider>
    </MemoryRouter>,
  );

it('reads a transcript first, then brings it in with the speakers the importer chose', async () => {
  const user = userEvent.setup({ applyAccept: false });
  show();
  expect(await screen.findByText('还没有录音')).toBeInTheDocument();
  await user.upload(
    screen.getByLabelText('选择录音文件'),
    new File(['x'], '运营周会.docx'),
  );
  const dialog = await screen.findByRole('dialog', { name: '导入转写稿' });
  expect(
    await within(dialog).findByDisplayValue('运营周会-10月18日'),
  ).toBeInTheDocument();
  expect(within(dialog).getByLabelText('日期')).toHaveValue('2026-10-18');
  // The two members the names are show who they are; the others ask who they are, with a line they said.
  const speakers = within(dialog).getByRole('list', { name: '说话人' });
  // The dialog fades in: it is read once it has.
  await waitFor(() =>
    expect(within(speakers).getByText('✓ 林舟')).toBeVisible(),
  );
  expect(within(speakers).getByText('✓ 许清禾')).toBeVisible();
  expect(within(speakers).getByText(/“下周把渠道数据拉一下”/)).toBeVisible();
  expect(
    within(dialog).getByText('没有声音：不能试听，不留声纹'),
  ).toBeVisible();
  await user.selectOptions(
    within(dialog).getByRole('combobox', { name: '说话人 3 是谁' }),
    'per_zhou',
  );
  await user.selectOptions(
    within(dialog).getByRole('combobox', { name: 'Kevin 是谁' }),
    '不是团队成员',
  );
  await user.click(within(dialog).getByRole('button', { name: '导入' }));
  await waitFor(() => expect(sent).not.toBeNull());
  expect((sent!.get('file') as File).name).toBe('运营周会.docx');
  expect(JSON.parse(String(sent!.get('payload')))).toEqual({
    title: '运营周会-10月18日',
    date: '2026-10-18',
    speakers: {
      '说话人 3': { person_id: 'per_zhou' },
      Kevin: { outsider: true },
    },
  });
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '导入转写稿' })).toBeNull(),
  );
  // It is listed as a transcript: no sound, a length that is about, and nobody left to settle.
  const row = within(await screen.findByRole('list', { name: '录音列表' }));
  expect(row.getByText('转写稿')).toBeVisible();
  expect(row.getByText(/约 40 分钟/)).toBeVisible();
  expect(row.getByText('都认出来了')).toBeVisible();
});

it('opens the import dialog for a transcript chosen elsewhere in the app, once, when the library opens', async () => {
  useUploadStore.getState().holdTranscripts([new File(['x'], '妙记.docx')]);
  show();
  const dialog = await screen.findByRole('dialog', { name: '导入转写稿' });
  await within(dialog).findByDisplayValue('运营周会-10月18日');
  expect(useUploadStore.getState().transcripts).toEqual([]);
});

it('leaves speakers undecided when nobody is chosen, and says so when the file is no transcript', async () => {
  const user = userEvent.setup({ applyAccept: false });
  show();
  await screen.findByText('还没有录音');
  await user.upload(
    screen.getByLabelText('选择录音文件'),
    new File(['x'], '运营周会.txt'),
  );
  const dialog = await screen.findByRole('dialog', { name: '导入转写稿' });
  await within(dialog).findByDisplayValue('运营周会-10月18日');
  await user.click(within(dialog).getByRole('button', { name: '导入' }));
  await waitFor(() => expect(sent).not.toBeNull());
  expect(JSON.parse(String(sent!.get('payload'))).speakers).toEqual({});
});

it('shows why a file cannot be read and lets it go', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library') return json(state);
      if (url === '/api/library/recollect') return json({ recordings: [] });
      if (url === '/api/library/transcripts/preview')
        return json(
          { detail: '没有找到按说话人分段的发言，请确认这是会议转写稿' },
          400,
        );
      return json({ items: [], voices: [], fragments: [], unsorted: [] });
    }),
  );
  const user = userEvent.setup({ applyAccept: false });
  show();
  await screen.findByText('还没有录音');
  await user.upload(
    screen.getByLabelText('选择录音文件'),
    new File(['x'], '说明.txt'),
  );
  const dialog = await screen.findByRole('dialog', { name: '导入转写稿' });
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    '没有找到按说话人分段的发言',
  );
  expect(within(dialog).getByRole('button', { name: '导入' })).toBeDisabled();
  await user.click(within(dialog).getByRole('button', { name: '取消' }));
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '导入转写稿' })).toBeNull(),
  );
});

it('lets the importer say a speaker the name matched is someone else', async () => {
  const user = userEvent.setup({ applyAccept: false });
  show();
  await screen.findByText('还没有录音');
  await user.upload(
    screen.getByLabelText('选择录音文件'),
    new File(['x'], '客户会.docx'),
  );
  const dialog = await screen.findByRole('dialog', { name: '导入转写稿' });
  await within(dialog).findByDisplayValue('运营周会-10月18日');
  // 林舟 is the member's name, and a client's too: the name is only where the choice starts.
  await user.click(within(dialog).getByRole('button', { name: '改 林舟' }));
  const who = within(dialog).getByRole('combobox', { name: '林舟 是谁' });
  expect(who).toHaveValue('per_lin');
  await user.selectOptions(who, '不是团队成员');
  await user.click(within(dialog).getByRole('button', { name: '导入' }));
  await waitFor(() => expect(sent).not.toBeNull());
  expect(JSON.parse(String(sent!.get('payload'))).speakers).toEqual({
    林舟: { outsider: true },
  });
});

it.each([
  [409, '你已有 20 个文件在排队转写（上限 20 个），等它们转完再导入转写稿'],
  [
    507,
    '磁盘空间不足：添加后可用空间会低于 20 GB 的安全余量，请联系管理员扩容',
  ],
])(
  'keeps the dialog and the choices when the server refuses the import (%i), and tries again',
  async (status, detail) => {
    refusal = { status, detail };
    const user = userEvent.setup({ applyAccept: false });
    show();
    await screen.findByText('还没有录音');
    await user.upload(
      screen.getByLabelText('选择录音文件'),
      new File(['x'], '运营周会.docx'),
    );
    const dialog = await screen.findByRole('dialog', { name: '导入转写稿' });
    await within(dialog).findByDisplayValue('运营周会-10月18日');
    await user.selectOptions(
      within(dialog).getByRole('combobox', { name: '说话人 3 是谁' }),
      'per_zhou',
    );
    await user.click(within(dialog).getByRole('button', { name: '导入' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(detail);
    // Still open, with what was chosen and the way to try again.
    expect(
      within(dialog).getByRole('combobox', { name: '说话人 3 是谁' }),
    ).toHaveValue('per_zhou');
    expect(within(dialog).getByRole('button', { name: '导入' })).toBeEnabled();
    refusal = null;
    sent = null;
    await user.click(within(dialog).getByRole('button', { name: '导入' }));
    await waitFor(() => expect(sent).not.toBeNull());
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '导入转写稿' })).toBeNull(),
    );
  },
);

it('says at once, when the file is read, that the server will not take it', async () => {
  refusal = { status: 409, detail: '你已有 20 个文件在排队', preview: true };
  const user = userEvent.setup({ applyAccept: false });
  show();
  await screen.findByText('还没有录音');
  await user.upload(
    screen.getByLabelText('选择录音文件'),
    new File(['x'], '运营周会.docx'),
  );
  const dialog = await screen.findByRole('dialog', { name: '导入转写稿' });
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    '你已有 20 个文件在排队',
  );
  expect(within(dialog).getByRole('button', { name: '导入' })).toBeDisabled();
});

it('brings in several transcripts one after another, from the page menu too', async () => {
  const user = userEvent.setup({ applyAccept: false });
  show();
  await screen.findByText('还没有录音');
  await user.upload(screen.getByLabelText('选择录音文件'), [
    new File(['x'], '一.docx'),
    new File(['x'], '二.txt'),
  ]);
  let dialog = await screen.findByRole('dialog', { name: '导入转写稿' });
  // In the document, not “visible”: the dialog fades in, and a slow machine is still at its first frame.
  expect(within(dialog).getByText('一.docx')).toBeInTheDocument();
  await user.click(within(dialog).getByRole('button', { name: '取消' }));
  // The second is read when the first is let go.
  await waitFor(() =>
    expect(
      screen.getByRole('dialog', { name: '导入转写稿' }),
    ).toHaveTextContent('二.txt'),
  );
  dialog = screen.getByRole('dialog', { name: '导入转写稿' });
  await within(dialog).findByDisplayValue('运营周会-10月18日');
  await user.click(within(dialog).getByRole('button', { name: '取消' }));
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '导入转写稿' })).toBeNull(),
  );
  // “⋯ → 导入转写稿” opens the file chooser for transcripts.
  const choose = vi.spyOn(screen.getByLabelText('选择转写稿'), 'click');
  await user.click(screen.getByLabelText('更多'));
  await user.click(screen.getByRole('button', { name: '导入转写稿' }));
  expect(choose).toHaveBeenCalledOnce();
  await user.upload(screen.getByLabelText('选择转写稿'), [
    new File(['x'], '三.srt'),
    new File(['x'], '四.vtt'),
  ]);
  dialog = await screen.findByRole('dialog', { name: '导入转写稿' });
  expect(within(dialog).getByText('三.srt')).toBeInTheDocument();
});
