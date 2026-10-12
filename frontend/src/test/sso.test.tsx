import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AuthGate } from '../features/auth/AuthGate';
import { useAuth } from '../stores/auth';

// Separate file: the redirect happens once per page, so it needs a fresh module.
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

it('hands a signed-out visitor to the single sign-on page instead of its own form', async () => {
  const fetcher = vi.fn(async () =>
    json(
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
    <AuthGate>
      <h1>应用</h1>
    </AuthGate>,
  );
  await act(async () => {
    await vi.waitFor(() =>
      expect(assign).toHaveBeenCalledWith('/login?next=/twin/'),
    );
  });
  expect(assign).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('heading', { name: '用邮箱登录' })).toBeNull();
  expect(screen.queryByRole('heading', { name: '应用' })).toBeNull();
});
