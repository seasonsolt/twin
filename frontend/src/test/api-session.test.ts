import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../lib/api';
import { uploadMedia } from '../lib/mediaUpload';
import { setPersonaId } from '../lib/persona';
import { useAuth } from '../stores/auth';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const pending = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => (resolve = done));
  return { promise, resolve };
};
const identity = (email: string) => ({
  email,
  admin: false,
  auth_enabled: true,
});
const required = { code: 'login_required', detail: '请先登录' };
const listeners: (() => void)[] = [];
function on(name: string, callback = vi.fn()) {
  window.addEventListener(name, callback);
  listeners.push(() => window.removeEventListener(name, callback));
  return callback;
}
beforeEach(() => {
  localStorage.clear();
  useAuth.getState().clear();
  setPersonaId('current');
});
afterEach(() => {
  listeners.splice(0).forEach((remove) => remove());
  vi.restoreAllMocks();
});

it.each(['next@example.test', 'first@example.test'])(
  'does not sign out a fresh login when an older account request returns 401 (%s)',
  async (next) => {
    const old = pending<Response>();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/status') return old.promise;
        if (url === '/api/whoami') return json(identity(next));
        if (url === '/api/personas') return json([]);
        throw new Error(url);
      }),
    );
    useAuth.setState({ identity: identity('first@example.test') });
    const requiredAgain = on(
      'twin-login-required',
      vi.fn(() => useAuth.getState().clear()),
    );
    const request = api('/api/status').catch((error: Error) => error);
    useAuth.getState().clear();
    await useAuth.getState().login();
    old.resolve(json(required, 401));
    expect(await request).toMatchObject({ status: 401 });
    expect(requiredAgain).not.toHaveBeenCalled();
    expect(useAuth.getState().identity?.email).toBe(next);
  },
);

it('does not let a previous sign-in check clear a newer successful sign-in', async () => {
  const old = pending<Response>();
  let checks = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/whoami')
        return ++checks === 1
          ? old.promise
          : json(identity('current@example.test'));
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  const requiredAgain = on(
    'twin-login-required',
    vi.fn(() => useAuth.getState().clear()),
  );
  const first = useAuth
    .getState()
    .login()
    .catch((error: Error) => error);
  await useAuth.getState().login();
  old.resolve(json(required, 401));
  expect(await first).toMatchObject({ status: 401 });
  expect(requiredAgain).not.toHaveBeenCalled();
  expect(useAuth.getState().identity?.email).toBe('current@example.test');
});

it('still signs out when the current session expires', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json(required, 401)),
  );
  const requiredAgain = on('twin-login-required');
  await expect(api('/api/status')).rejects.toMatchObject({ status: 401 });
  expect(requiredAgain).toHaveBeenCalledTimes(1);
});

it('does not let an older logout response clear a newer successful sign-in', async () => {
  const old = pending<Response>();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/auth/logout') return old.promise;
      if (url === '/api/whoami') return json(identity('current@example.test'));
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  useAuth.setState({ identity: identity('first@example.test') });
  const logout = useAuth.getState().logout();
  // Another expired request already took the old account to the sign-in page.
  useAuth.getState().clear();
  await useAuth.getState().login();
  old.resolve(json({}));
  await logout;
  expect(useAuth.getState().identity?.email).toBe('current@example.test');
  expect(useAuth.getState().signedOut).toBe(false);
});

it('does not publish an error after its response body was cancelled', async () => {
  const body = pending<Record<string, unknown>>();
  const response = json({}, 401);
  const read = vi.spyOn(response, 'json').mockReturnValue(body.promise);
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => response),
  );
  const controller = new AbortController();
  const requiredAgain = on('twin-login-required');
  const request = api('/api/status', { signal: controller.signal }).catch(
    (error: Error) => error,
  );
  await vi.waitFor(() => expect(read).toHaveBeenCalled());
  controller.abort();
  body.resolve(required);
  expect(await request).toMatchObject({ name: 'AbortError' });
  expect(requiredAgain).not.toHaveBeenCalled();
});

it.each(['json', 'text', 'stream'] as const)(
  'does not return a cancelled successful %s response',
  async (responseType) => {
    const reply = pending<Response>();
    vi.stubGlobal(
      'fetch',
      vi.fn(() => reply.promise),
    );
    const controller = new AbortController();
    const request = api('/api/status', {
      responseType,
      signal: controller.signal,
    }).catch((error: Error) => error);
    controller.abort();
    reply.resolve(json({ from: 'closed task' }));
    expect(await request).toMatchObject({ name: 'AbortError' });
  },
);

it.each([false, true])(
  'does not refresh the current persona for an old persona 404 (explicit=%s)',
  async (explicit) => {
    const reply = pending<Response>();
    vi.stubGlobal(
      'fetch',
      vi.fn(() => reply.promise),
    );
    setPersonaId('old');
    const stale = on('twin-persona-stale');
    const request = api(
      '/api/identity',
      explicit ? { headers: { 'X-Twin-Persona': 'old' } } : {},
    ).catch((error: Error) => error);
    setPersonaId('current');
    reply.resolve(json({ detail: '分身不存在' }, 404));
    expect(await request).toMatchObject({ status: 404 });
    expect(stale).not.toHaveBeenCalled();
  },
);

it('still reconciles a missing current persona or an unscoped registry entry', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json({ detail: '分身不存在' }, 404)),
  );
  const stale = on('twin-persona-stale');
  await expect(api('/api/identity')).rejects.toMatchObject({ status: 404 });
  await expect(api('/api/personas/removed')).rejects.toMatchObject({
    status: 404,
  });
  expect(stale).toHaveBeenCalledTimes(2);
});

it('does not publish a late resumable upload 401 over a new login', async () => {
  const reply = pending<Response>();
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/library/uploads') return reply.promise;
      if (url === '/api/whoami') return json(identity('current@example.test'));
      if (url === '/api/personas') return json([]);
      throw new Error(url);
    }),
  );
  const requiredAgain = on(
    'twin-login-required',
    vi.fn(() => useAuth.getState().clear()),
  );
  const request = uploadMedia(
    new File(['wav'], '合成验收.wav'),
    new AbortController().signal,
    vi.fn(),
    {
      base: '/api/library/uploads',
      scope: 'library',
    },
  ).catch((error: Error) => error);
  useAuth.getState().clear();
  await useAuth.getState().login();
  reply.resolve(json(required, 401));
  expect(await request).toMatchObject({ status: 401 });
  expect(requiredAgain).not.toHaveBeenCalled();
  expect(useAuth.getState().identity?.email).toBe('current@example.test');
});
