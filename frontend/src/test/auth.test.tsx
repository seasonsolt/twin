import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { AuthGate } from '../features/auth/AuthGate';
import { Login } from '../features/auth/Login';
import { api } from '../lib/api';
import { getPersonaId, setPersonaId } from '../lib/persona';
import { useAuth } from '../stores/auth';
import { usePersonas, type Persona } from '../stores/personas';
import { isSourcesUrl, sourcesPage } from './personaApi';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const member = { email: 'me@xjjk.com', admin: false, auth_enabled: true };
const persona: Persona = {
  id: 'p-first',
  name: '我的分身',
  owner: member.email,
  sources: 0,
  avatar_url: null,
  created_at: 'now',
  is_default: false,
};
const emailOnly = { sso: null, password: false, email: true };
const companySignIn = {
  sso: {
    start_url: '/auth/start?next=/twin/',
    login_url: '/login?next=/twin/',
  },
  password: true,
  email: false,
};
let methods: Record<string, unknown>;
let loggedIn: boolean;
let whoami: Record<string, unknown>;
let items: Persona[];
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  methods = emailOnly;
  loggedIn = false;
  whoami = member;
  items = [persona];
  localStorage.clear();
  sessionStorage.clear();
  useAuth.getState().clear();
  window.location.hash = '#/chat';
  fetcher = vi.fn(async (path: string, init: RequestInit) => {
    if (path === '/api/auth/methods') return json(methods);
    if (path === '/api/auth/request') return json({ status: 'code_sent' });
    if (path === '/api/auth/password') {
      const body = JSON.parse(String(init.body));
      if (body.password !== 'secret-123')
        return json({ detail: '账号或密码不对' }, 400);
      loggedIn = true;
      return json(member);
    }
    if (path === '/api/auth/verify') {
      loggedIn = true;
      return json(member);
    }
    if (path === '/api/auth/logout') {
      loggedIn = false;
      return json({ logged_out: true });
    }
    if (!loggedIn)
      return json({ detail: '请先登录', code: 'login_required' }, 401);
    if (path === '/api/whoami') return json(whoami);
    if (path === '/api/personas') {
      if (init.method === 'POST') {
        items = [persona];
        return json(persona, 201);
      }
      return json(items);
    }
    // The account's recordings and people, with or without a twin.
    if (path === '/api/library')
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
    if (path === '/api/library/people' || path === '/api/library/review')
      return json({ items: [], voices: [], fragments: [], unsorted: [] });
    if (!items.length)
      return json({ detail: '先新建一个分身', code: 'no_persona' }, 409);
    if (path === '/api/identity')
      return json({
        name: persona.name,
        about: '',
        aliases: [],
        name_source: 'user',
        egress: [],
      });
    if (path === '/api/status')
      return json({
        target_name: persona.name,
        counts: { sources: 0, items: 0 },
        egress: [],
      });
    if (path === '/api/persona/state') return json({ stale: false });
    if (path === '/api/media/capabilities')
      return json({ available: false, video: { available: false } });
    if (isSourcesUrl(path)) return json(sourcesPage(path, []));
    if (path === '/api/jobs') return json([]);
    if (path === '/api/persona/processing') return json({ state: 'idle' });
    throw new Error(path);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  vi.useRealTimers();
  setPersonaId('default');
  usePersonas.setState({ id: 'default', items: [] });
  useAuth.setState({ identity: null });
});
async function requestCode(user: ReturnType<typeof userEvent.setup>) {
  const email = await screen.findByRole('textbox', { name: '邮箱' });
  expect(email).toHaveAttribute('type', 'email');
  expect(email).toHaveAttribute('autocomplete', 'email');
  await user.type(email, member.email);
  await user.click(screen.getByRole('button', { name: '获取验证码' }));
  return screen.findByRole('textbox', { name: '6 位验证码' });
}

it('logs in via email and a paste-friendly code without persisting credentials', async () => {
  const user = userEvent.setup();
  render(
    <AuthGate>
      <h1>应用</h1>
    </AuthGate>,
  );
  const code = await requestCode(user);
  expect(code).toHaveAttribute('inputmode', 'numeric');
  expect(code).toHaveAttribute('autocomplete', 'one-time-code');
  await user.click(code);
  await user.paste('012345');
  await user.click(screen.getByRole('button', { name: '登录' }));
  expect(await screen.findByRole('heading', { name: '应用' })).toBeVisible();
  expect(getPersonaId()).toBe(persona.id);
  const mutation = fetcher.mock.calls.find(
    ([path]) => path === '/api/auth/verify',
  )![1];
  expect(JSON.parse(mutation.body)).toEqual({
    email: member.email,
    code: '012345',
  });
  expect(new Headers(mutation.headers).get('X-Twin')).toBe('1');
  expect(new Headers(mutation.headers).has('X-Twin-Persona')).toBe(false);
  expect(Object.keys(localStorage)).toEqual(['twin:persona']);
});

it('shows the waitlist without a code form or a way to try another email', async () => {
  fetcher.mockImplementation(async () => json({ status: 'waitlist' }));
  const user = userEvent.setup();
  render(<Login />);
  await user.type(
    await screen.findByRole('textbox', { name: '邮箱' }),
    'wait@example.com',
  );
  await user.click(screen.getByRole('button', { name: '获取验证码' }));
  expect(
    await screen.findByRole('heading', { name: '已加入等候名单' }),
  ).toBeVisible();
  expect(screen.getByText('wait@example.com')).toBeVisible();
  expect(screen.getByText('开放后会第一时间通知你')).toBeVisible();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('enables resend only after the 60-second countdown and restarts it', async () => {
  render(<Login />);
  const email = await screen.findByRole('textbox', { name: '邮箱' });
  vi.useFakeTimers();
  fireEvent.change(email, {
    target: { value: member.email },
  });
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '获取验证码' }));
  });
  expect(
    screen.getByRole('button', { name: '重新发送（60 秒）' }),
  ).toBeDisabled();
  await act(async () => {
    vi.advanceTimersByTime(59000);
  });
  expect(
    screen.getByRole('button', { name: '重新发送（1 秒）' }),
  ).toBeDisabled();
  await act(async () => {
    vi.advanceTimersByTime(1000);
  });
  expect(screen.getByRole('button', { name: '重新发送' })).toBeEnabled();
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '重新发送' }));
  });
  expect(
    screen.getByRole('button', { name: '重新发送（60 秒）' }),
  ).toBeDisabled();
  expect(
    fetcher.mock.calls.filter(([path]) => path === '/api/auth/request'),
  ).toHaveLength(2);
});

it('returns to login on a mid-session 401 and clears the previous persona state', async () => {
  loggedIn = true;
  render(
    <AuthGate>
      <h1>应用</h1>
    </AuthGate>,
  );
  await screen.findByRole('heading', { name: '应用' });
  loggedIn = false;
  await act(async () => {
    await expect(api('/api/status')).rejects.toMatchObject({
      code: 'login_required',
    });
  });
  expect(
    await screen.findByRole('heading', { name: '用邮箱登录' }),
  ).toBeVisible();
  expect(usePersonas.getState().items).toEqual([]);
  expect(getPersonaId()).toBe('');
});

it('routes no_persona to creation in the workspace, then opens the app for the new twin', async () => {
  loggedIn = true;
  items = [];
  window.location.hash = '#/work';
  const user = userEvent.setup();
  render(<App />);
  // Nothing else on the page yet: the form is right there, with the workspace navigation around it.
  expect(
    await screen.findByRole('heading', { name: '先新建一个分身' }),
  ).toBeVisible();
  expect(screen.getByRole('form', { name: '新建分身' })).toBeVisible();
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.getByRole('navigation', { name: '主导航' })).toBeVisible();
  await user.type(
    await screen.findByRole('textbox', { name: '分身名字' }),
    '我的分身',
  );
  await user.click(screen.getByRole('button', { name: '创建并开始' }));
  await screen.findByRole('button', { name: /^切换分身/ });
  await waitFor(() => expect(usePersonas.getState().id).toBe(persona.id));
  expect(
    fetcher.mock.calls
      .filter(([path]) => path === '/api/personas')
      .every(([, init]) => !new Headers(init.headers).has('X-Twin-Persona')),
  ).toBe(true);
});

it('shows the full signed-in email in the account popover and logs out', async () => {
  loggedIn = true;
  const user = userEvent.setup();
  render(<App />);
  const account = await screen.findByRole('button', { name: '账户' });
  expect(account).toHaveTextContent('M');
  expect(account).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByText(member.email)).not.toBeInTheDocument();
  await user.click(account);
  expect(screen.getByRole('dialog', { name: '账户' })).toHaveClass(
    'account-popover',
  );
  expect(screen.getByText(member.email)).toBeVisible();
  const menu = screen.getByRole('dialog', { name: '账户' });
  expect(menu).toHaveAttribute('data-side', 'right');
  expect(menu).toHaveAttribute('data-align', 'end');
  expect(within(menu).queryByRole('button', { name: /关闭/ })).toBeNull();
  expect(within(menu).getAllByRole('button')).toHaveLength(1);
  await user.keyboard('{Escape}');
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '账户' })).toBeNull(),
  );
  expect(account).toHaveFocus();
  await user.click(account);
  await user.click(
    screen.getByRole('heading', { name: `${persona.name} / 新对话` }),
  );
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '账户' })).toBeNull(),
  );
  expect(account).toHaveFocus();
  await user.click(account);
  await user.click(screen.getByRole('button', { name: '退出登录' }));
  expect(
    await screen.findByRole('heading', { name: '用邮箱登录' }),
  ).toBeVisible();
  expect(loggedIn).toBe(false);
});

it("shows the single sign-on name and signs out back to twin's own sign-in page", async () => {
  methods = companySignIn;
  loggedIn = true;
  whoami = {
    ...member,
    email: 'sso:u-1',
    name: '张三',
    provider: 'sso',
  };
  const user = userEvent.setup();
  render(<App />);
  const account = await screen.findByRole('button', { name: '账户' });
  expect(account).toHaveTextContent('张');
  await user.click(account);
  const menu = screen.getByRole('dialog', { name: '账户' });
  expect(within(menu).getByText('张三')).toBeVisible();
  expect(within(menu).queryByText('sso:u-1')).toBeNull();
  await user.click(within(menu).getByRole('button', { name: '退出登录' }));
  expect(
    await screen.findByRole('heading', { name: '登录 twin' }),
  ).toBeVisible();
  expect(loggedIn).toBe(false);
});

it("offers the company sign-in as a form posted on this site, beside twin's own account", async () => {
  methods = companySignIn;
  render(<Login />);
  const start = await screen.findByRole('button', {
    name: '用享佳统一身份登录',
  });
  const form = start.closest('form')!;
  expect(form).toHaveAttribute('method', 'post');
  expect(form).toHaveAttribute('action', '/auth/start?next=/twin/');
  expect(start).toHaveAttribute('type', 'submit');
  expect(screen.getByText('或用 twin 账号登录')).toBeVisible();
  expect(screen.getByRole('textbox', { name: '账号' })).toHaveAttribute(
    'autocomplete',
    'username',
  );
  expect(screen.queryByRole('textbox', { name: '邮箱' })).toBeNull();
});

it("links to the other app's sign-in page without a start address and never to another site", async () => {
  methods = {
    sso: { start_url: null, login_url: '/login?next=/twin/' },
    password: false,
    email: false,
  };
  const { unmount } = render(<Login />);
  expect(
    await screen.findByRole('link', { name: '用享佳统一身份登录' }),
  ).toHaveAttribute('href', '/login?next=/twin/');
  unmount();
  methods = {
    sso: {
      start_url: '//evil.example/start',
      login_url: 'https://evil.example/',
    },
    password: true,
    email: false,
  };
  render(<Login />);
  await screen.findByRole('textbox', { name: '账号' });
  expect(
    screen.queryByRole('button', { name: '用享佳统一身份登录' }),
  ).toBeNull();
  expect(screen.queryByRole('link', { name: '用享佳统一身份登录' })).toBeNull();
});

it("signs in with twin's own account and password", async () => {
  methods = { sso: null, password: true, email: false };
  const user = userEvent.setup();
  render(
    <AuthGate>
      <h1>应用</h1>
    </AuthGate>,
  );
  expect(
    await screen.findByRole('heading', { name: '登录 twin' }),
  ).toBeVisible();
  const username = screen.getByRole('textbox', { name: '账号' });
  expect(username).toHaveFocus();
  const password = screen.getByLabelText('密码');
  expect(password).toHaveAttribute('type', 'password');
  expect(password).toHaveAttribute('autocomplete', 'current-password');
  await user.type(username, ' bob ');
  await user.type(password, 'wrong-pass');
  await user.click(screen.getByRole('button', { name: '登录' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('账号或密码不对');
  await user.clear(password);
  await user.type(password, 'secret-123');
  await user.click(screen.getByRole('button', { name: '登录' }));
  expect(await screen.findByRole('heading', { name: '应用' })).toBeVisible();
  const sent = fetcher.mock.calls.filter(
    ([path]) => path === '/api/auth/password',
  );
  expect(JSON.parse(sent[1][1].body)).toEqual({
    username: 'bob',
    password: 'secret-123',
  });
  expect(new Headers(sent[1][1].headers).get('X-Twin')).toBe('1');
  expect(window.location.hash).toBe('#/team');
  expect(JSON.stringify(localStorage)).not.toContain('secret-123');
});

it.each([0, 1, 2])(
  'lands on the team page after login with %s twins',
  async (count) => {
    items = Array.from({ length: count }, (_, index) => ({
      ...persona,
      id: `p-${index}`,
      name: `分身${index}`,
    }));
    window.location.hash = '#/about';
    const user = userEvent.setup();
    render(<App />);
    const code = await requestCode(user);
    await user.type(code, '012345');
    await user.click(screen.getByRole('button', { name: '登录' }));
    // No twin needs setting up first; an account without one is offered one beside the team's recordings.
    await screen.findByRole('heading', {
      name: count ? '从一段会议录音开始' : '从团队会议录音开始',
    });
    if (!count)
      expect(
        screen.getByRole('heading', { name: '给自己建分身' }),
      ).toBeVisible();
    expect(window.location.hash).toBe('#/team');
  },
);

it('clears a stale persona and selects the first owned twin rather than default', async () => {
  loggedIn = true;
  setPersonaId('p-deleted');
  usePersonas.setState({ id: 'p-deleted' });
  render(
    <AuthGate>
      <h1>应用</h1>
    </AuthGate>,
  );
  await screen.findByRole('heading', { name: '应用' });
  expect(getPersonaId()).toBe(persona.id);
  items = [{ ...persona, id: 'p-next' }];
  fetcher.mockImplementationOnce(async () =>
    json({ detail: '分身不存在' }, 404),
  );
  await act(async () => {
    await expect(api('/api/status')).rejects.toMatchObject({ status: 404 });
  });
  await waitFor(() => expect(getPersonaId()).toBe('p-next'));
});

it('opens on a twin made for this person until they say it is all right', async () => {
  loggedIn = true;
  const made: Persona = {
    ...persona,
    owner: 'admin@xjjk.com',
    name: '赵晴',
    sources: 2,
    mine: true,
    made_by_other: true,
    approved: false,
  };
  items = [made];
  const base = fetcher.getMockImplementation() as (
    path: string,
    init: RequestInit,
  ) => Promise<Response>;
  const sent: [string, unknown][] = [];
  fetcher.mockImplementation(async (path: string, init: RequestInit) => {
    if (path.endsWith('/approve') || path.endsWith('/disown')) {
      sent.push([path, init.body ? JSON.parse(String(init.body)) : null]);
      items = path.endsWith('/approve')
        ? [{ ...made, approved: true, public: false }]
        : [];
      return json(path.endsWith('/approve') ? items[0] : { disowned: true });
    }
    if (path.startsWith('/api/') && !path.startsWith('/api/personas'))
      try {
        return await base(path, init);
      } catch {
        return json({});
      }
    return base(path, init);
  });
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole('heading', { name: '赵晴，你的分身已经建好了' });
  expect(screen.queryByRole('navigation')).toBeNull();
  await user.click(screen.getByRole('checkbox', { name: '同事能问我的分身' }));
  await user.click(screen.getByRole('button', { name: '没问题，开始用' }));
  await waitFor(() =>
    expect(sent).toEqual([
      ['/api/personas/p-first/approve', { public: false }],
    ]),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole('heading', { name: '赵晴，你的分身已经建好了' }),
    ).toBeNull(),
  );
});

it('gives a twin made for the wrong address back with 这不是我', async () => {
  loggedIn = true;
  items = [{ ...persona, mine: true, made_by_other: true, approved: false }];
  const base = fetcher.getMockImplementation() as (
    path: string,
    init: RequestInit,
  ) => Promise<Response>;
  let disowned = false;
  fetcher.mockImplementation(async (path: string, init: RequestInit) => {
    if (path === '/api/personas/p-first/disown') {
      disowned = true;
      items = [];
      return json({ disowned: true });
    }
    return base(path, init);
  });
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: '这不是我' }));
  await user.click(
    within(
      await screen.findByRole('dialog', { name: '这不是你的分身？' }),
    ).getByRole('button', {
      name: '这不是我',
    }),
  );
  await waitFor(() => expect(disowned).toBe(true));
  await screen.findByRole('form', { name: '新建分身' });
});

it('shows what the twin gathered and lets its person try it out in chat first', async () => {
  loggedIn = true;
  items = [
    {
      ...persona,
      name: '赵晴',
      owner: 'admin@xjjk.com',
      mine: true,
      made_by_other: true,
      approved: false,
    },
  ];
  const base = fetcher.getMockImplementation() as (
    path: string,
    init: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (path: string, init: RequestInit) => {
    if (path === '/api/persona/ledger')
      return json({
        entries: [
          {
            entry_id: 'l1',
            kind: 'commitment',
            owner: '赵晴',
            what: '周五前重算留存口径',
            meeting_title: '产品周会',
            meeting_date: '2026-10-15',
          },
          {
            entry_id: 'l2',
            kind: 'commitment',
            owner: '王一鸣',
            what: '别人的事',
          },
        ],
      });
    if (path.startsWith('/api/conversations')) return json([]);
    if (path.startsWith('/api/persona/items?'))
      return json({
        items: [
          {
            item_id: 'i1',
            statement: '看数据先问口径',
            evidence: [{}, {}],
          },
        ],
        total: 1,
      });
    try {
      return await base(path, init);
    } catch {
      return json({});
    }
  });
  const user = userEvent.setup();
  render(<App />);
  expect(await screen.findByText('周五前重算留存口径')).toBeInTheDocument();
  expect(screen.queryByText('别人的事')).toBeNull();
  expect(screen.getByText('看数据先问口径')).toBeInTheDocument();
  expect(screen.getByText('2 处原话支持')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '这周还欠谁什么？' }));
  expect(
    await screen.findByText('试聊中：你点“没问题”之前，同事问不到它。'),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: '你说' })).toHaveValue(
      '这周还欠谁什么？',
    ),
  );
  await user.click(screen.getByRole('button', { name: '回去确认' }));
  await screen.findByRole('heading', { name: '赵晴，你的分身已经建好了' });
});

it('looks for someone signed in with a work address in the meetings before an empty twin', async () => {
  loggedIn = true;
  whoami = { ...member, address: 'me@xjjk.com' };
  items = [];
  const base = fetcher.getMockImplementation() as (
    path: string,
    init: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation(async (path: string, init: RequestInit) =>
    path === '/api/library/voice'
      ? json({
          available: true,
          enrolled: false,
          items: [],
          persona_id: null,
        })
      : base(path, init),
  );
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole('heading', { name: '会议里可能有你' });
  await user.click(
    await screen.findByRole('button', { name: '没开过会，先建空分身' }),
  );
  await screen.findByRole('form', { name: '新建分身' });
});

it('a twin of the voices someone recognised leads back to them instead of 这不是我', async () => {
  loggedIn = true;
  items = [{ ...persona, mine: true, from_meetings: true, approved: false }];
  render(<App />);
  await screen.findByRole('heading', { name: '我的分身，你的分身已经建好了' });
  expect(screen.queryByRole('button', { name: '这不是我' })).toBeNull();
  expect(screen.getByRole('link', { name: '回去再听一遍' })).toHaveAttribute(
    'href',
    '#/voice',
  );
});
