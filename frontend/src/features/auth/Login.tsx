import { useEffect, useId, useState } from 'react';
import { Button, Card, Field, Heading, Input, Text } from '../../components/ui';
import { StageHeader } from '../../components/layout/StageHeader';
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
  const emailId = useId();
  const codeId = useId();
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
      // Start from the team: people are found in the recordings, not set up first.
      window.location.hash = '#/team';
      await useAuth.getState().login();
    });
  return (
    <main className="auth-page min-h-dvh bg-background">
      <StageHeader
        variant="brand"
        intro={<p className="stage-caption">留住记忆，让对话继续。</p>}
      />
      <Card className="mx-auto my-6 w-11/12 max-w-sm space-y-6">
        <Heading level={2} size="title">
          {step === 'waitlist' ? '已加入等候名单' : '用邮箱登录'}
        </Heading>
        {step === 'waitlist' ? (
          <Card
            as="div"
            variant="soft"
            padding="md"
            className="waitlist-message space-y-3"
          >
            <Text breakAll>{email}</Text>
            <Text tone="secondary">开放后会第一时间通知你</Text>
          </Card>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (!busy) void (step === 'email' ? request() : verify());
            }}
          >
            {step === 'email' ? (
              <Field id={emailId} label="邮箱">
                <Input
                  id={emailId}
                  type="email"
                  autoComplete="email"
                  required
                  autoFocus
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  maxLength={254}
                  size="lg"
                />
              </Field>
            ) : (
              <>
                <Text size="sm" tone="secondary" breakAll>
                  验证码已发送至 {email}
                </Text>
                <Field id={codeId} label="6 位验证码">
                  <Input
                    id={codeId}
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
                    size="lg"
                    className="tracking-widest"
                  />
                </Field>
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
        {step === 'code' && (
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
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
      </Card>
    </main>
  );
}
