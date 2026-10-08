import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { NewTwin } from '../components/layout/NewTwin';
import { Profile } from '../pages/Profile';
import { Chat } from '../pages/Chat';
import { Memories } from '../pages/Memories';
import { Questionnaire } from '../pages/Questionnaire';
import { Onboarding } from '../pages/Onboarding';
import { Login } from '../features/auth/Login';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';
import { setPersonaId } from '../lib/persona';
import type { IdentityData } from '../features/identity/useIdentity';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const persona: Persona = {
  id: 'p-stage',
  name: '小林',
  avatar_url: '/api/media/avatar-image?v=portrait',
  sources: 2,
  created_at: '',
  is_default: true,
};
const identity: IdentityData = {
  name: persona.name,
  about: '喜欢徒步',
  name_source: 'user',
  aliases: [],
  voice: null,
  avatar: null,
  egress: [],
};
const json = (value: unknown) => new Response(JSON.stringify(value));
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  });
  setPersonaId(persona.id);
  usePersonas.setState({ id: persona.id, items: [persona] });
  useStatus.setState({ data: null, error: null });
  fetcher = vi.fn(async (path: string) => {
    if (path === '/api/personas') return json([persona]);
    if (path === '/api/identity') return json(identity);
    if (path === '/api/media/capabilities')
      return json({
        available: false,
        avatar_image: { url: persona.avatar_url },
        video: { available: false },
      });
    if (path === '/api/status')
      return json({
        target_name: persona.name,
        counts: { sources: 2, items: 0 },
        egress: [],
      });
    if (path === '/api/persona/processing') return json({ state: 'idle' });
    if (path === '/api/persona/sources')
      return json([
        {
          source_id: 'audio',
          title: '访谈',
          kind: 'audio',
          status: 'needs_speaker',
          duration_s: 7200,
          remembered: 0,
          detected_kind_label: '录音',
          first_date: null,
        },
        {
          source_id: 'note',
          title: '日记',
          status: 'remembered',
          remembered: 3,
          detected_kind_label: '笔记',
          first_date: null,
        },
      ]);
    if (path === '/api/persona/coverage')
      return json({ facets: [], suggestions: [], kind_labels: {} });
    if (path.startsWith('/api/persona/items')) return json([]);
    if (path.startsWith('/api/questionnaire'))
      return json({ questions: [], answers: {}, round: 'initial' });
    if (path === '/api/me/assets')
      return json({
        portrait: null,
        voice: null,
        speech_clone: false,
        video: false,
      });
    if (path === '/api/persona/state') return json({ stale: false });
    if (path === '/api/auth/request') return json({ status: 'waitlist' });
    throw new Error(`Unexpected API ${path}`);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
  useStatus.setState({ data: null, error: null });
  Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView');
});
function mount(page: React.ReactNode, route: string) {
  return render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={[route]}>{page}</MemoryRouter>
    </ConfirmProvider>,
  );
}

it.each([
  ['chat', Chat],
  ['memories', Memories],
  ['profile', Profile],
  ['questionnaire', Questionnaire],
] as const)(
  'shows the current name and round portrait on %s, with a working switcher',
  async (route, Page) => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({
        matches: query === '(max-width: 767px)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    const view = mount(<Page />, `/${route}`);
    const header = await screen.findByRole('banner', { name: '小林的舞台' });
    await waitFor(() => expect(header.querySelector('img')).not.toBeNull());
    expect(header).toHaveClass('stage-header');
    expect(within(header).getByRole('heading', { name: '小林' })).toHaveClass(
      'persona-name',
    );
    expect(header.querySelector('img')?.src).toContain('persona=p-stage');
    expect(
      header.querySelectorAll(
        '[aria-hidden].stage-sun, [aria-hidden].stage-coral',
      ),
    ).toHaveLength(2);
    if (route === 'chat') {
      expect(
        header.querySelectorAll(
          '.stage-portrait-area > .stage-decorations > span',
        ),
      ).toHaveLength(2);
      expect(
        header.querySelector('.stage-actions .stage-decorations'),
      ).toBeNull();
      expect(header.querySelector('.stage-name .stage-decorations')).toBeNull();
      expect(
        header.querySelector('.stage-caption .stage-decorations'),
      ).toBeNull();
    }
    fireEvent.click(within(header).getByRole('button', { name: '切换分身' }));
    const sheet = await screen.findByRole('dialog', { name: '切换分身' });
    expect(within(sheet).getByText('小林').closest('button')).toHaveClass(
      'bg-primary',
      'text-canvas',
    );
    expect(
      within(sheet).getByRole('link', { name: '＋ 新建分身' }),
    ).toBeEnabled();
    expect(
      within(sheet).getByRole('link', { name: '全部分身' }),
    ).toHaveAttribute('href', '/twins');
    expect(within(sheet).queryByRole('button', { name: '管理' })).toBeNull();
    view.unmount();
  },
);

it.each([true, false])(
  'adds memories from the band (mobile: %s)',
  async (mobile) => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        matches: mobile,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    mount(<Memories />, '/memories');
    await screen.findByText('2 条 · 2 小时录音');
    expect(screen.getByRole('heading', { name: '他记得的事' })).toBeVisible();
    expect(screen.getByText(/段录音需要确认哪位是你/)).toHaveClass(
      'speaker-banner',
    );
    const header = screen.getByRole('banner', { name: '小林的舞台' });
    if (mobile) {
      expect(
        within(header).queryByRole('button', { name: '从舞台添加记忆' }),
      ).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: '添加记忆' }));
    } else {
      fireEvent.click(
        within(header).getByRole('button', { name: '从舞台添加记忆' }),
      );
    }
    if (mobile) {
      const sheet = screen.getByRole('dialog', { name: '添加记忆' });
      expect(within(sheet).getAllByRole('tab')).toHaveLength(3);
    } else {
      expect(
        screen.getByRole('textbox', { name: '要记住的文字' }),
      ).toHaveFocus();
    }
  },
);

it('shows a live future-twin preview and four pills when creating', async () => {
  mount(<NewTwin />, '/chat');
  fireEvent.click(screen.getByRole('button', { name: '新建分身' }));
  const sheet = screen.getByRole('dialog', { name: '新建分身' });
  fireEvent.change(within(sheet).getByRole('textbox', { name: '分身名字' }), {
    target: { value: '阿宁' },
  });
  const header = within(sheet).getByRole('banner', { name: '阿宁的舞台' });
  expect(header.querySelector('img')).toBeNull();
  expect(
    within(header).getByRole('img', { name: '阿宁的头像' }),
  ).toHaveTextContent('阿');
  expect(
    within(header).getByRole('img', { name: '第 1 步，共 4 步' }).children,
  ).toHaveLength(4);
});

it('keeps the onboarding portrait and live name on the band above four steps', async () => {
  mount(<Onboarding identity={identity} onDone={vi.fn()} />, '/chat');
  expect(
    screen.getByRole('banner', { name: '小林的舞台' }).querySelector('img'),
  ).not.toBeNull();
  expect(screen.getAllByRole('button', { name: /第 \d 步/ })).toHaveLength(4);
  fireEvent.change(screen.getByRole('textbox', { name: '名字' }), {
    target: { value: '阿宁' },
  });
  expect(screen.getByRole('banner', { name: '阿宁的舞台' })).toBeVisible();
});

it('renders persona-free login and waitlist heroes even with a previous persona in memory', async () => {
  mount(<Login />, '/login');
  const header = screen.getByRole('banner', { name: 'twin 的舞台' });
  expect(within(header).getByRole('heading', { name: 'twin' })).toHaveClass(
    'persona-name',
  );
  expect(header.querySelector('.stage-brand-mark')?.children).toHaveLength(2);
  expect(header.querySelector('img')).toBeNull();
  expect(screen.queryByText('小林')).not.toBeInTheDocument();
  const email = screen.getByRole('textbox', { name: '邮箱' });
  expect(email).toHaveClass('border-2', 'border-primary', 'text-md');
  fireEvent.change(email, { target: { value: 'wait@example.com' } });
  fireEvent.click(screen.getByRole('button', { name: '获取验证码' }));
  await screen.findByRole('heading', { name: '已加入等候名单' });
  expect(header).toBeVisible();
  expect(screen.getByText('开放后会第一时间通知你').parentElement).toHaveClass(
    'waitlist-message',
  );
});

it('falls back to the chosen illustration when the portrait fails', () => {
  mount(<StageHeader />, '/memories');
  fireEvent.error(screen.getByRole('img', { name: '小林的肖像' }));
  expect(screen.getByRole('img', { name: '插画形象：栗' })).toHaveAttribute(
    'viewBox',
    '0 0 220 220',
  );
});
