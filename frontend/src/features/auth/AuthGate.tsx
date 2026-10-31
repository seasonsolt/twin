import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router';
import { Button, Skeleton } from '../../components/ui';
import { ApiError } from '../../lib/api';
import { useAuth } from '../../stores/auth';
import { usePersonas } from '../../stores/personas';
import { useTheme } from '../../stores/theme';
import { Login } from './Login';
import { local, loginPath, takeReturn } from './returnTo';

const HeirChat = lazy(() =>
  import('../heir/HeirChat').then((module) => ({ default: module.HeirChat })),
);
const HeirsOnly = lazy(() =>
  import('../heir/HeirsOnly').then((module) => ({
    default: module.HeirsOnly,
  })),
);

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
  // The persona edition shows its own palettes: once the server has said which edition this is, take them up.
  const persona = identity ? identity.edition === 'persona' : null;
  useEffect(() => {
    if (persona !== null) useTheme.getState().adoptEdition(persona);
  }, [persona]);
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
    const sealed = () =>
      void useAuth
        .getState()
        .login()
        .catch(() => {});
    window.addEventListener('twin-login-required', clear);
    window.addEventListener('twin-persona-stale', stale);
    window.addEventListener('twin-heirs-only', sealed);
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
      window.removeEventListener('twin-heirs-only', sealed);
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
  // An heir who opened the twin (P2.7) has their own conversation and nothing else, whatever the address.
  if (identity.heir)
    return (
      <Suspense fallback={<Skeleton className="mx-auto mt-12 h-64 max-w-sm" />}>
        <HeirChat key={identity.heir.id} heir={identity.heir} />
      </Suspense>
    );
  // Once the person's own twin is sealed, this computer is the heirs' way in and nothing else (P2.7).
  if (identity.sealed)
    return (
      <Suspense fallback={<Skeleton className="mx-auto mt-12 h-64 max-w-sm" />}>
        <HeirsOnly />
      </Suspense>
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
