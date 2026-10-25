import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { useAuth } from '../stores/auth';
import { usePersonas, type Persona } from '../stores/personas';

// The pages themselves are not what is tried here: who is let in where, and by which address.
vi.mock('../pages/Chat', () => ({ Chat: () => <p>聊天页</p> }));
vi.mock('../pages/Profile', () => ({ Profile: () => <p>档案页</p> }));
vi.mock('../pages/Library', () => ({ Library: () => <p>录音库页</p> }));
vi.mock('../pages/Inbox', () => ({ Inbox: () => <p>待处理页</p> }));
vi.mock('../pages/Commitments', () => ({
  Commitments: () => <p>承诺页</p>,
}));
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const twin = (change: Partial<Persona>): Persona => ({
  id: 'p-1',
  name: '林舟',
  avatar_url: null,
  sources: 2,
  created_at: '',
  is_default: false,
  ...change,
});
const emailOnly = { sso: null, password: false, email: true };

let loggedIn: boolean;
let whoami: Record<string, unknown>;
let items: Persona[];
// Set to hold the answer to whether there is a twin until it is let go.
let identityHeld: Promise<void> | null;
beforeEach(() => {
  loggedIn = false;
  items = [];
  identityHeld = null;
  localStorage.clear();
  useAuth.getState().clear();
  window.location.hash = '#/chat';
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      if (path === '/api/auth/methods') return json(emailOnly);
      if (path === '/api/auth/request') return json({ status: 'code_sent' });
      if (path === '/api/auth/verify') {
        loggedIn = true;
        return json(whoami);
      }
      if (!loggedIn)
        return json({ detail: '请先登录', code: 'login_required' }, 401);
      if (path === '/api/whoami') return json(whoami);
      if (path === '/api/personas') return json(items);
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
      if (
        path === '/api/library/people' ||
        path.startsWith('/api/library/review')
      )
        return json({ items: [], voices: [], fragments: [], unsorted: [] });
      if (path === '/api/identity') {
        if (identityHeld) await identityHeld;
        return json({ name: '林舟', about: '', aliases: [], egress: [] });
      }
      return json({});
    }),
  );
});
afterEach(() => {
  useAuth.setState({ identity: null });
  usePersonas.setState({ id: '', items: [] });
});

async function signIn() {
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    await screen.findByRole('textbox', { name: '邮箱' }),
    'me@example.test',
  );
  await user.click(screen.getByRole('button', { name: '获取验证码' }));
  await user.type(
    await screen.findByRole('textbox', { name: '6 位验证码' }),
    '012345',
  );
  await user.click(screen.getByRole('button', { name: '登录' }));
}
const entries = async () => {
  const nav = await screen.findByRole('navigation', { name: '主导航' });
  return within(nav)
    .getAllByRole('link')
    .map((link) => link.textContent?.replace(/\d+$/u, ''));
};

it('lets an administrator in at the team, with every place to work in', async () => {
  // A fresh visit, not a link to a page: signing in starts at the team.
  window.location.hash = '#/';
  whoami = { email: 'admin@example.test', admin: true, auth_enabled: true };
  items = [twin({ can_manage: false, name: '朋友' })];
  await signIn();
  expect(await entries()).toEqual(['团队', '对话', '录音库', '待处理', '承诺']);
  expect(window.location.hash).toBe('#/team');
  expect(screen.getByRole('button', { name: '问一句、找人' })).toBeVisible();
  expect(screen.getByRole('button', { name: '上传会议录音' })).toBeVisible();
});

it('lets the person behind a twin in at the team, with the same places', async () => {
  // A fresh visit, not a link to a page: signing in starts at the team.
  window.location.hash = '#/';
  whoami = { email: 'me@example.test', admin: false, auth_enabled: true };
  items = [
    twin({
      id: 'p-own',
      name: '我',
      can_manage: true,
      mine: true,
      approved: true,
    }),
    twin({ id: 'p-pub', name: '朋友', can_manage: false }),
  ];
  usePersonas.setState({ id: 'p-pub' });
  await signIn();
  // Another twin being in view does not make them a guest.
  expect(await entries()).toEqual(['团队', '对话', '录音库', '待处理', '承诺']);
  expect(window.location.hash).toBe('#/team');
});

it('gives a guest, who only meets twins made public, the conversation alone', async () => {
  whoami = { email: 'guest@example.test', admin: false, auth_enabled: true };
  items = [twin({ id: 'p-pub', name: '朋友', can_manage: false })];
  await signIn();
  expect(await entries()).toEqual(['对话']);
  await waitFor(() => expect(window.location.hash).toBe('#/chat'));
  expect(await screen.findByText('聊天页')).toBeVisible();
  expect(screen.queryByRole('button', { name: '问一句、找人' })).toBeNull();
  expect(screen.queryByRole('button', { name: '上传会议录音' })).toBeNull();
  // The places of the team are not a guest's, by address either: nor its members' pages, nor the old profile.
  for (const address of [
    '#/library',
    '#/inbox',
    '#/commitments',
    '#/ledger',
    '#/team/twin/p-pub',
    '#/team/u-1',
    '#/profile',
    '#/twins',
  ]) {
    window.location.hash = address;
    await waitFor(() => expect(window.location.hash).toBe('#/chat'));
  }
});

it('opens what waits and the commitments at their own addresses, and leads the old ledger address to the commitments', async () => {
  whoami = { email: 'admin@example.test', admin: true, auth_enabled: true };
  await signIn();
  await entries();
  window.location.hash = '#/inbox';
  expect(await screen.findByText('待处理页')).toBeInTheDocument();
  window.location.hash = '#/ledger';
  expect(await screen.findByText('承诺页')).toBeInTheDocument();
  expect(window.location.hash).toBe('#/commitments');
});

it('leads the commitments and the old ledger address to the conversation once an administrator has switched them off', async () => {
  whoami = {
    email: 'admin@example.test',
    admin: true,
    auth_enabled: true,
    features: { ledger: false },
  };
  await signIn();
  expect(await entries()).toEqual(['团队', '对话', '录音库', '待处理']);
  for (const address of ['#/commitments', '#/ledger']) {
    window.location.hash = address;
    await waitFor(() => expect(window.location.hash).toBe('#/chat'));
    expect(await screen.findByText('聊天页')).toBeVisible();
  }
});

it('keeps the side bar where it is while the next place waits for its twin', async () => {
  whoami = { email: 'admin@example.test', admin: true, auth_enabled: true };
  await signIn();
  await entries();
  const nav = screen.getByRole('navigation', { name: '主导航' });
  let letGo = () => {};
  identityHeld = new Promise((resolve) => (letGo = resolve));
  window.location.hash = '#/commitments';
  await waitFor(() => expect(window.location.hash).toBe('#/commitments'));
  // Only the page waits: the navigation is the very same, not drawn again.
  expect(screen.queryByText('承诺页')).toBeNull();
  expect(screen.getByRole('navigation', { name: '主导航' })).toBe(nav);
  letGo();
  expect(await screen.findByText('承诺页')).toBeInTheDocument();
  expect(screen.getByRole('navigation', { name: '主导航' })).toBe(nav);
});
