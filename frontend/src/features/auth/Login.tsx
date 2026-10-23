import { useEffect, useId, useState } from 'react';
import { ChevronDown, ShieldCheck } from 'lucide-react';
import {
  Button,
  Card,
  Field,
  Heading,
  Input,
  LinkButton,
  Skeleton,
  Stack,
  Text,
} from '../../components/ui';
import { api } from '../../lib/api';
import { useAuth } from '../../stores/auth';

/** The ways the server signs people in (GET /api/auth/methods). */
export interface LoginMethods {
  /** The company sign-in, run by another app on this site: a form posted to start_url, else a link to login_url. */
  sso: { start_url: string | null; login_url: string } | null;
  /** twin's own accounts and passwords. */
  password: boolean;
  /** A code sent by e-mail. */
  email: boolean;
}

// A server from before the sign-in page asked had only e-mail codes of its own.
const EMAIL_ONLY: LoginMethods = { sso: null, password: false, email: true };

/** Paths on this site only: never send the browser, or a form, to another origin. */
const local = (path: string | null | undefined) =>
  path && path.startsWith('/') && !path.startsWith('//') ? path : '';

/** Once signed in, ``#/login`` leads on to the team (people are found in the recordings, not set up first), so there
 * is nothing to navigate here. */
async function signedIn() {
  await useAuth.getState().login();
}

export function Login() {
  const [methods, setMethods] = useState<LoginMethods | null>(null);
  const [waitlisted, setWaitlisted] = useState('');
  const [ownOpen, setOwnOpen] = useState(false);
  const ownId = useId();
  useEffect(() => {
    let active = true;
    api<LoginMethods>('/api/auth/methods')
      .then((found) => {
        if (active)
          setMethods(
            found && typeof found === 'object' && 'password' in found
              ? found
              : EMAIL_ONLY,
          );
      })
      .catch(() => {
        if (active) setMethods(EMAIL_ONLY);
      });
    return () => {
      active = false;
    };
  }, []);
  const start = local(methods?.sso?.start_url);
  const link = local(methods?.sso?.login_url);
  const sso = Boolean(start || link);
  return (
    <main className="auth-page bg-background">
      <AuthStage />
      <section aria-label="登录方式" className="auth-panel">
        {!methods ? (
          <Skeleton className="h-48" />
        ) : waitlisted ? (
          <Stack gap={4}>
            <Heading level={1} size="title">
              已加入等候名单
            </Heading>
            <Card
              as="div"
              variant="soft"
              padding="md"
              className="waitlist-message space-y-3"
            >
              <Text breakAll>{waitlisted}</Text>
              <Text tone="secondary">开放后会第一时间通知你</Text>
            </Card>
          </Stack>
        ) : (
          <>
            <Card variant="outline" padding="lg" className="auth-card">
              <div className="auth-card-head">
                <span aria-hidden className="auth-tile">
                  <span className="auth-mark">
                    <span />
                    <span />
                  </span>
                </span>
                <Stack gap={1} align="center">
                  {(sso || methods.password) && (
                    <Text size="sm" tone="secondary">
                      欢迎回来
                    </Text>
                  )}
                  <Heading level={1} size="title">
                    {sso || methods.password ? '登录 twin' : '用邮箱登录'}
                  </Heading>
                </Stack>
              </div>
              {sso &&
                (start ? (
                  // The other app checks that the post comes from this site, then hands the browser to the sign-in.
                  <form method="post" action={start}>
                    <Button type="submit" size="lg" className="min-h-12 w-full">
                      <ShieldCheck aria-hidden className="size-5" />
                      用享佳统一身份登录
                    </Button>
                  </form>
                ) : (
                  <LinkButton href={link} size="lg" className="min-h-12 w-full">
                    <ShieldCheck aria-hidden className="size-5" />
                    用享佳统一身份登录
                  </LinkButton>
                ))}
              {sso && methods.email && (
                <div className="auth-divider">
                  <Text size="sm" tone="secondary">
                    或用邮箱验证码
                  </Text>
                </div>
              )}
              {(!sso || methods.email) && (
                <div className="space-y-4">
                  {!sso && methods.password && <PasswordLogin primary />}
                  {methods.email && (
                    <EmailLogin
                      primary={!sso && !methods.password}
                      onWaitlist={setWaitlisted}
                    />
                  )}
                </div>
              )}
              {sso && methods.password && (
                <>
                  <div className="auth-divider">
                    <Button
                      variant="ghost"
                      aria-expanded={ownOpen}
                      aria-controls={ownId}
                      onClick={() => setOwnOpen((open) => !open)}
                    >
                      或用 twin 账号登录
                      <ChevronDown
                        aria-hidden
                        className={`size-4 transition-transform ${ownOpen ? 'rotate-180' : ''}`}
                      />
                    </Button>
                  </div>
                  {ownOpen && (
                    <div id={ownId}>
                      <PasswordLogin primary={false} />
                    </div>
                  )}
                </>
              )}
            </Card>
            <Text size="sm" tone="secondary" align="center">
              登录遇到问题？请联系管理员
            </Text>
          </>
        )}
      </section>
    </main>
  );
}

/** What twin is for: a twin that knows you best, and twins that meet and work together become an organisation. */
function AuthStage() {
  return (
    <header className="auth-stage" aria-label="twin">
      <span aria-hidden className="auth-sun" />
      <span aria-hidden className="auth-ring" />
      <span aria-hidden className="auth-dot" />
      <div className="auth-brand">
        <span aria-hidden className="auth-mark">
          <span />
          <span />
        </span>
        twin
      </div>
      <div className="auth-pitch">
        <p className="auth-slogan">
          最懂你的，
          <br />
          是另一个你。
        </p>
        <p className="auth-lede">
          分身记住你如何思考、如何取舍，替你高效应答；当每个人的分身在会议中相遇、协作，个体便汇聚成组织。
        </p>
        <ol className="auth-path" aria-label="从个人分身到超级组织">
          <li>个人分身</li>
          <li>超级个体</li>
          <li>超级组织</li>
        </ol>
      </div>
      <p className="auth-footnote">享佳集团 · 内部使用</p>
    </header>
  );
}

function useWork() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
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
  return { busy, error, setError, work };
}

function PasswordLogin({ primary }: { primary: boolean }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const { busy, error, work } = useWork();
  const userId = useId();
  const passwordId = useId();
  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!busy)
          void work(async () => {
            await api('/api/auth/password', {
              method: 'POST',
              json: { username: username.trim(), password },
            });
            await signedIn();
          });
      }}
    >
      <Field id={userId} label="账号">
        <Input
          id={userId}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          autoFocus={primary}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          maxLength={64}
          size="lg"
        />
      </Field>
      <Field id={passwordId} label="密码">
        <Input
          id={passwordId}
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          maxLength={256}
          size="lg"
        />
      </Field>
      <Button
        type="submit"
        variant={primary ? 'primary' : 'secondary'}
        className="min-h-12 w-full"
        loading={busy}
        disabled={busy || !username.trim() || !password}
      >
        登录
      </Button>
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
    </form>
  );
}

function EmailLogin({
  primary,
  onWaitlist,
}: {
  primary: boolean;
  onWaitlist: (email: string) => void;
}) {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [deadline, setDeadline] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const { busy, error, setError, work } = useWork();
  const emailId = useId();
  const codeId = useId();
  useEffect(() => {
    const update = () =>
      setRemaining(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [deadline]);
  const request = () =>
    work(async () => {
      const result = await api<{ status: string }>('/api/auth/request', {
        method: 'POST',
        json: { email: email.trim() },
      });
      const address = email.trim().toLowerCase();
      setEmail(address);
      if (result.status === 'waitlist') {
        onWaitlist(address);
        return;
      }
      setStep('code');
      setCode('');
      setDeadline(Date.now() + 60000);
      setRemaining(60);
    });
  const verify = () =>
    work(async () => {
      await api('/api/auth/verify', { method: 'POST', json: { email, code } });
      await signedIn();
    });
  return (
    <Stack gap={4}>
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
              autoFocus={primary}
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
                  setCode(event.target.value.replace(/\D/gu, '').slice(0, 6))
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
          variant={primary || step === 'code' ? 'primary' : 'secondary'}
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
    </Stack>
  );
}
