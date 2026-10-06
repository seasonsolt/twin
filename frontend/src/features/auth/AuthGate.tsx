import { useEffect, useState, type ReactNode } from 'react';
import { Button, Skeleton } from '../../components/ui';
import { ApiError } from '../../lib/api';
import { useAuth } from '../../stores/auth';
import { usePersonas } from '../../stores/personas';
import { Login } from './Login';

export function AuthGate({ children }: { children: ReactNode }) {
  const identity = useAuth((state) => state.identity);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState('');
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
  return identity ? children : <Login />;
}
