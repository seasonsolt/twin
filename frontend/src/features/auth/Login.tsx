import { useEffect, useState } from 'react';
import { Button } from '../../components/ui';
import { api } from '../../lib/api';
import { useAuth } from '../../stores/auth';

export function Login() {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'email' | 'code' | 'waitlist'>('email');
  const [deadline, setDeadline] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const update = () =>
      setRemaining(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [deadline]);
  const work = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '登录失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  const request = () =>
    work(async () => {
      const result = await api<{ status: string }>('/api/auth/request', {
        method: 'POST',
        json: { email: email.trim() },
      });
      setEmail(email.trim().toLowerCase());
      setStep(result.status === 'waitlist' ? 'waitlist' : 'code');
      setCode('');
      setDeadline(Date.now() + 60000);
      setRemaining(60);
    });
  const verify = () =>
    work(async () => {
      await api('/api/auth/verify', { method: 'POST', json: { email, code } });
      await useAuth.getState().login();
    });
  return (
    <main className="grid min-h-dvh place-items-center bg-background px-4 py-8">
      <section className="w-full max-w-sm space-y-6 rounded-xl border border-border bg-surface p-6">
        <p className="text-lg font-semibold text-accent">twin</p>
        <h1 className="text-xl font-semibold">
          {step === 'waitlist' ? '已加入等候名单' : '用邮箱登录'}
        </h1>
        {step === 'waitlist' ? (
          <div className="space-y-3">
            <p className="break-all">{email}</p>
            <p className="text-secondary">开放后会第一时间通知你</p>
          </div>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (!busy) void (step === 'email' ? request() : verify());
            }}
          >
            {step === 'email' ? (
              <label className="block space-y-2">
                <span>邮箱</span>
                <input
                  type="email"
                  autoComplete="email"
                  required
                  autoFocus
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  maxLength={254}
                  className="block min-h-12 w-full rounded-md border border-border bg-background px-3 text-base"
                />
              </label>
            ) : (
              <>
                <p className="break-all text-sm text-secondary">
                  验证码已发送至 {email}
                </p>
                <label className="block space-y-2">
                  <span>6 位验证码</span>
                  <input
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    required
                    autoFocus
                    value={code}
                    onChange={(event) =>
                      setCode(
                        event.target.value.replace(/\D/gu, '').slice(0, 6),
                      )
                    }
                    pattern="[0-9]{6}"
                    maxLength={6}
                    className="block min-h-12 w-full rounded-md border border-border bg-background px-3 text-base tracking-widest"
                  />
                </label>
              </>
            )}
            <Button
              type="submit"
              className="min-h-12 w-full"
              loading={busy}
              disabled={busy || (step === 'code' && code.length !== 6)}
            >
              {step === 'email' ? '获取验证码' : '登录'}
            </Button>
            {step === 'code' && (
              <Button
                variant="ghost"
                disabled={busy || remaining > 0}
                onClick={() => void request()}
              >
                {remaining > 0 ? `重新发送（${remaining} 秒）` : '重新发送'}
              </Button>
            )}
          </form>
        )}
        {step !== 'email' && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              setStep('email');
              setCode('');
              setError('');
            }}
          >
            换个邮箱
          </Button>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
      </section>
    </main>
  );
}
