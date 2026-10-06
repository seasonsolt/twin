import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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
let loggedIn: boolean;
let items: Persona[];
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  loggedIn = false;
  items = [persona];
  localStorage.clear();
  sessionStorage.clear();
  useAuth.getState().clear();
  window.location.hash = '#/chat';
  fetcher = vi.fn(async (path: string, init: RequestInit) => {
    if (path === '/api/auth/request') return json({ status: 'code_sent' });
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
    if (path === '/api/whoami') return json(member);
    if (path === '/api/personas') {
      if (init.method === 'POST') {
        items = [persona];
        return json(persona, 201);
      }
      return json(items);
    }
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
    if (path === '/api/persona/sources' || path === '/api/jobs')
      return json([]);
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

it('shows the waitlist without a code form and can change email', async () => {
  fetcher.mockResolvedValue(json({ status: 'waitlist' }));
  const user = userEvent.setup();
  render(<Login />);
  await user.type(
    screen.getByRole('textbox', { name: '邮箱' }),
    'wait@example.com',
  );
  await user.click(screen.getByRole('button', { name: '获取验证码' }));
  expect(
    await screen.findByRole('heading', { name: '已加入等候名单' }),
  ).toBeVisible();
  expect(screen.getByText('wait@example.com')).toBeVisible();
  expect(screen.getByText('开放后会第一时间通知你')).toBeVisible();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '换个邮箱' }));
  expect(screen.getByRole('textbox', { name: '邮箱' })).toBeVisible();
});

it('enables resend only after the 60-second countdown and restarts it', async () => {
  vi.useFakeTimers();
  render(<Login />);
  fireEvent.change(screen.getByRole('textbox', { name: '邮箱' }), {
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

it('routes no_persona to creation, then opens the app for the new twin', async () => {
  loggedIn = true;
  items = [];
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole('dialog', { name: '新建分身' });
  await user.type(
    await screen.findByRole('textbox', { name: '分身名字' }),
    '我的分身',
  );
  await user.click(screen.getByRole('button', { name: '创建并开始' }));
  await screen.findByRole('button', { name: '切换分身' });
  await waitFor(() => expect(usePersonas.getState().id).toBe(persona.id));
  expect(
    fetcher.mock.calls
      .filter(([path]) => path === '/api/personas')
      .every(([, init]) => !new Headers(init.headers).has('X-Twin-Persona')),
  ).toBe(true);
});

it('shows the email in the switcher and logs out', async () => {
  loggedIn = true;
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: '切换分身' }));
  await waitFor(() => expect(screen.getByText(member.email)).toBeVisible());
  await user.click(screen.getByRole('button', { name: '退出登录' }));
  expect(
    await screen.findByRole('heading', { name: '用邮箱登录' }),
  ).toBeVisible();
  expect(loggedIn).toBe(false);
});

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
