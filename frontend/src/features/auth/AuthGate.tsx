import { useEffect, useState, type ReactNode } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router';
import { Button, Skeleton } from '../../components/ui';
import { ApiError } from '../../lib/api';
import { useAuth } from '../../stores/auth';
import { usePersonas } from '../../stores/personas';
import { Login } from './Login';
import { local, loginPath, takeReturn } from './returnTo';

/**
 * Everything behind signing in. Signed out, every address leads to ``#/login``, which keeps the page asked for
 * (``?next=``); signed in, ``#/login`` leads back to it, else to the team (where a guest, who may only talk to twins,
 * is sent on to the chat). Needs a router around it.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const identity = useAuth((state) => state.identity);
  const signedOut = useAuth((state) => state.signedOut);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState('');
  // Back from the company sign-in, which returns to the start page: the page it was started from.
  const [back, setBack] = useState('');
  useEffect(() => {
    if (!back) return;
    setBack('');
    void navigate(back, { replace: true });
  }, [back, navigate]);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const clear = () => {
      useAuth.getState().clear();
      setChecking(false);
    };
    const stale = () =>
      void usePersonas
        .getState()
        .refresh()
        .catch(() => {});
    window.addEventListener('twin-login-required', clear);
    window.addEventListener('twin-persona-stale', stale);
    void useAuth
      .getState()
      .login(controller.signal)
      .then(() => {
        if (active && useAuth.getState().identity) setBack(takeReturn());
      })
      .catch((failure: unknown) => {
        if (
          active &&
          !(failure instanceof ApiError && failure.code === 'login_required')
        )
          setError(
            failure instanceof Error ? failure.message : '无法读取登录状态',
          );
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
      controller.abort();
      window.removeEventListener('twin-login-required', clear);
      window.removeEventListener('twin-persona-stale', stale);
    };
  }, []);
  if (checking) return <Skeleton className="mx-auto mt-12 h-64 max-w-sm" />;
  if (error)
    return (
      <main className="p-6">
        <p role="alert">{error}</p>
        <Button onClick={() => window.location.reload()}>重试</Button>
      </main>
    );
  if (!identity)
    return pathname === '/login' ? (
      <Login />
    ) : (
      <Navigate
        to={signedOut ? '/login' : loginPath(pathname + search)}
        replace
      />
    );
  return pathname === '/login' ? (
    <Navigate
      to={local(new URLSearchParams(search).get('next')) || '/team'}
      replace
    />
  ) : (
    children
  );
}
