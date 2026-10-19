import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import {
  MemberVoice,
  type VoiceItem,
  type VoiceState,
} from '../pages/MemberVoice';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

class Recorder {
  static isTypeSupported = vi.fn((type: string) => type === 'audio/mp4');
  state = 'inactive';
  mimeType = 'audio/mp4';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  start = vi.fn(() => {
    this.state = 'recording';
  });
  stop = vi.fn(() => {
    this.state = 'inactive';
    this.ondataavailable?.({
      data: new Blob(['a sentence'], { type: this.mimeType }),
    });
    this.onstop?.();
  });
}

const offer = (change: Partial<VoiceItem>): VoiceItem => ({
  id: 'vo_1',
  state: 'offered',
  quote: '续费方案我周四前给到大家。',
  title: '周一经营会',
  date: '2026-10-12',
  more: 3,
  unsure: false,
  sample_url: '/api/library/voice/items/vo_1/sample',
  ...change,
});
const empty: VoiceState = {
  available: true,
  enrolled: false,
  items: [],
  persona_id: null,
};
let voice: VoiceState | null;
let sent: [string, string, unknown][];
beforeEach(() => {
  voice = empty;
  sent = [];
  vi.stubGlobal('MediaRecorder', Recorder);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }),
    },
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      if (path === '/api/library/voice' && method === 'GET')
        return voice ? json(voice) : json({ detail: '用企业账号' }, 404);
      sent.push([
        method,
        path,
        init?.body instanceof FormData
          ? init.body.get('file')
          : init?.body
            ? JSON.parse(String(init.body))
            : null,
      ]);
      if (path === '/api/library/voice' && method === 'PUT')
        return json({
          ...empty,
          enrolled: true,
          items: [
            offer({}),
            offer({
              id: 'vo_2',
              quote: '我同意，先上灰度。',
              title: '季度复盘',
              date: null,
              unsure: true,
            }),
          ],
        });
      if (path === '/api/library/voice/offers/vo_1')
        return json({
          ...empty,
          enrolled: true,
          items: [offer({ id: 'vc_1', state: 'mine' })],
          persona_id: 'p-zhang',
        });
      if (path === '/api/library/voice/offers/vo_2')
        return json({ ...empty, enrolled: true, items: [offer({})] });
      throw new Error(path);
    }),
  );
});

const show = (onSkip?: () => void) =>
  render(
    <MemoryRouter>
      <MemberVoice onSkip={onSkip} />
    </MemoryRouter>,
  );

it('reads a sentence aloud, hears one sentence of each voice and says which is theirs', async () => {
  const user = userEvent.setup();
  show(() => {});
  await screen.findByRole('heading', { name: '会议里可能有你' });
  expect(screen.getByText(/管理员还没为你建分身/u)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '开始录音' }));
  await user.click(await screen.findByRole('button', { name: /说完了/u }));
  const list = await screen.findByRole('list', { name: '可能是你的声音' });
  expect(sent[0]?.slice(0, 2)).toEqual(['PUT', '/api/library/voice']);
  expect(sent[0]?.[2]).toBeInstanceOf(File);
  const [sure, unsure] = within(list).getAllByRole('listitem');
  expect(sure).toHaveTextContent('“续费方案我周四前给到大家。”');
  expect(sure).toHaveTextContent('周一经营会 · 10 月 12 日 · 另有 3 段');
  expect(unsure).toHaveTextContent('季度复盘 · 声音较像，拿不准');
  expect(
    within(sure!).getByRole('button', {
      name: '播放：周一经营会里的这句话',
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: '确认之后就能看分身' }),
  ).toBeDisabled();

  await user.click(within(unsure!).getByRole('button', { name: '不是' }));
  await waitFor(() =>
    expect(within(list).getAllByRole('listitem')).toHaveLength(1),
  );
  await user.click(within(list).getByRole('button', { name: '是我' }));
  await screen.findByText('✓ 是我');
  expect(sent.slice(1)).toEqual([
    ['POST', '/api/library/voice/offers/vo_2', { verdict: 'not' }],
    ['POST', '/api/library/voice/offers/vo_1', { verdict: 'me' }],
  ]);
  expect(
    screen.getByRole('button', { name: '已确认 1 段，看看我的分身' }),
  ).toBeEnabled();
  expect(screen.getByRole('button', { name: '撤回' })).toBeInTheDocument();
  expect(screen.queryByText('一段都不是我')).toBeNull();
});

it('goes on to an empty twin without a work address or when nothing is theirs', async () => {
  const user = userEvent.setup();
  const skipped = vi.fn();
  voice = null;
  show(skipped);
  await waitFor(() => expect(skipped).toHaveBeenCalledTimes(1));

  voice = { ...empty, enrolled: true };
  const later = vi.fn();
  show(later);
  await screen.findByText('已有的会议里还没听到你');
  await user.click(screen.getByRole('button', { name: '先建一个空分身' }));
  expect(later).toHaveBeenCalledTimes(1);
});
