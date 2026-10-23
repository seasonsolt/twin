import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { AuthGate } from '../features/auth/AuthGate';
import { useAuth } from '../stores/auth';

// Separate file: a fresh module, so nothing from another test has started leaving the page.
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
let assign: ReturnType<typeof vi.fn>;
beforeEach(() => {
  assign = vi.fn();
  vi.spyOn(window, 'location', 'get').mockReturnValue({
    ...window.location,
    assign,
  } as Location);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useAuth.setState({ identity: null });
});

it('shows its own sign-in page with the company sign-in instead of leaving for it', async () => {
  const fetcher = vi.fn(async (path: string) =>
    path === '/api/auth/methods'
      ? json({
          sso: {
            start_url: '/auth/start?next=/twin/',
            login_url: '/login?next=/twin/',
          },
          password: true,
          email: false,
        })
      : json(
          {
            detail: '请先登录',
            code: 'login_required',
            login_url: '/login?next=/twin/',
          },
          401,
        ),
  );
  vi.stubGlobal('fetch', fetcher);
  render(
    <MemoryRouter initialEntries={['/chat']}>
      <AuthGate>
        <h1>应用</h1>
      </AuthGate>
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole('heading', { name: '登录 twin' }),
  ).toBeVisible();
  expect(
    screen.getByRole('button', { name: '用享佳统一身份登录' }).closest('form'),
  ).toHaveAttribute('action', '/auth/start?next=/twin/');
  expect(assign).not.toHaveBeenCalled();
  expect(screen.queryByRole('heading', { name: '应用' })).toBeNull();
});

it('asks to retry instead of guessing the ways in when the server cannot say', async () => {
  let up = false;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) =>
      path === '/api/auth/methods'
        ? up
          ? json({
              sso: { start_url: null, login_url: '/login?next=/twin/' },
              password: false,
              email: false,
            })
          : new Response('<html>502 Bad Gateway</html>', { status: 502 })
        : json({ detail: '请先登录', code: 'login_required' }, 401),
    ),
  );
  render(
    <MemoryRouter initialEntries={['/chat']}>
      <AuthGate>
        <h1>应用</h1>
      </AuthGate>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '暂时连不上 twin，可能正在重启，请稍后重试',
  );
  expect(screen.queryByRole('heading', { name: '用邮箱登录' })).toBeNull();
  expect(screen.queryByRole('textbox')).toBeNull();
  up = true;
  await userEvent.click(screen.getByRole('button', { name: '重试' }));
  expect(
    await screen.findByRole('link', { name: '用享佳统一身份登录' }),
  ).toHaveAttribute('href', '/login?next=/twin/');
});

it('stays off the sign-in page while the company sign-in cannot answer', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      json(
        {
          detail: '登录服务暂时不可用，请稍后重试',
          code: 'sign_in_unavailable',
        },
        503,
      ),
    ),
  );
  render(
    <MemoryRouter initialEntries={['/chat']}>
      <AuthGate>
        <h1>应用</h1>
      </AuthGate>
    </MemoryRouter>,
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '登录服务暂时不可用，请稍后重试',
  );
  expect(screen.queryByRole('region', { name: '登录方式' })).toBeNull();
  expect(screen.getByRole('button', { name: '重试' })).toBeVisible();
});
