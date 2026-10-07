import {
  lazy,
  startTransition,
  Suspense,
  useEffect,
  useRef,
  useState,
} from 'react';
import { Link, Navigate, NavLink, useLocation, useOutlet } from 'react-router';
import { motion } from 'motion/react';
import * as Popover from '@radix-ui/react-popover';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import { BookUser, MessageCircle } from 'lucide-react';
import { useMotionPreset } from '../../design/motion';
import { startStatusPolling, useStatus } from '../../stores/status';
import { Button, Skeleton, Tooltip } from '../ui';
import { LayoutScope, PageTransition } from '../motion';
import { useMobile } from '../../lib/useMobile';
import { api, ApiError } from '../../lib/api';
import { useCanManage, usePersonas } from '../../stores/personas';
import { PersonaSwitcher, PersonaPortrait } from './PersonaSwitcher';
import { NewTwin } from './NewTwin';
import { useAuth } from '../../stores/auth';
import { StageHeader } from './StageHeader';
import type { IdentityData } from '../../features/identity/useIdentity';
const Onboarding = lazy(() =>
  import('../../pages/Onboarding').then((module) => ({
    default: module.Onboarding,
  })),
);

export const navItems = [
  { route: 'chat', title: '聊天', icon: MessageCircle },
  { route: 'profile', title: '档案', icon: BookUser },
];

function useNavItems() {
  return useCanManage() ? navItems : navItems.slice(0, 1);
}

function Navigation() {
  const { reduced, transition } = useMotionPreset('layout');
  const items = useNavItems();
  return (
    <LayoutScope>
      <nav aria-label="主导航" className="space-y-1">
        {items.map(({ route, title, icon: Icon }) => {
          const link = (
            <NavLink
              key={route}
              to={`/${route}`}
              className="rail-link relative flex min-h-16 flex-col items-center justify-center gap-1 rounded-full text-xs text-primary aria-[current=page]:text-canvas"
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId={reduced ? undefined : 'active-nav'}
                      initial={reduced ? { opacity: 0 } : false}
                      animate={{ opacity: 1 }}
                      transition={transition}
                      className="absolute inset-0 rounded-full bg-primary"
                    />
                  )}
                  <Icon aria-hidden className="relative size-5 shrink-0" />
                  <span className="relative whitespace-nowrap">{title}</span>
                </>
              )}
            </NavLink>
          );
          return link;
        })}
      </nav>
    </LayoutScope>
  );
}

function BottomTabs() {
  const items = useNavItems();
  return (
    <nav
      aria-label="底部导航"
      className={`mobile-tabs fixed inset-x-0 bottom-0 z-30 grid gap-2 border-t border-border bg-canvas px-3 pt-2 md:hidden ${items.length === 2 ? 'grid-cols-2' : 'grid-cols-1'}`}
    >
      {items.map(({ route, title, icon: Icon }) => (
        <NavLink
          key={route}
          to={`/${route}`}
          className={({ isActive }) =>
            `flex min-h-11 items-center justify-center gap-2 rounded-full text-sm ${isActive ? 'bg-primary font-semibold text-canvas' : 'text-secondary'}`
          }
        >
          <Icon className="size-5" aria-hidden />
          <span>{title}</span>
        </NavLink>
      ))}
    </nav>
  );
}

function TwinRail() {
  const { id, items, pendingId, refresh, switchTo } = usePersonas();
  const current = items.find((item) => item.id === id);
  const identity = useAuth((state) => state.identity);
  const [accountOpen, setAccountOpen] = useState(false);
  const accountButton = useRef<HTMLButtonElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const load = () => void refresh().catch(() => {});
    load();
    window.addEventListener('twin-assets-changed', load);
    window.addEventListener('twin-identity-changed', load);
    return () => {
      window.removeEventListener('twin-assets-changed', load);
      window.removeEventListener('twin-identity-changed', load);
    };
  }, [refresh]);
  return (
    <aside className="nav-rail sticky top-0 flex h-dvh shrink-0 flex-col overflow-y-auto border-r border-border bg-canvas px-2 py-4 text-primary">
      <div
        className="flex flex-col items-center gap-2"
        aria-label="分身快捷切换"
      >
        <Tooltip label={current?.name || '本人'}>
          <span>
            <PersonaSwitcher
              label="切换分身"
              className="rail-twin rounded-full ring-2 ring-accent ring-offset-2 ring-offset-canvas"
              trigger={<PersonaPortrait persona={current} />}
            />
          </span>
        </Tooltip>
        {items
          .filter((item) => item.id !== id)
          .slice(0, 4)
          .map((persona) => (
            <Tooltip key={persona.id} label={persona.name}>
              <button
                type="button"
                aria-label={`切换到${persona.name}`}
                aria-busy={pendingId === persona.id}
                className="rail-twin rounded-full hover:bg-soft"
                onClick={() => void switchTo(persona.id)}
              >
                <PersonaPortrait persona={persona} />
              </button>
            </Tooltip>
          ))}
        {items.length > 5 && (
          <Link
            to="/twins"
            className="grid min-h-11 place-items-center text-xs text-accent"
          >
            全部
          </Link>
        )}
        <Tooltip label="新建分身">
          <span>
            <NewTwin className="grid size-11 place-items-center rounded-full text-2xl hover:bg-soft">
              ＋
            </NewTwin>
          </span>
        </Tooltip>
      </div>
      <div className="my-3 border-t border-border" />
      <Navigation />
      {identity?.auth_enabled && (
        <div className="rail-account mt-auto pt-4 text-center text-xs">
          <Popover.Root open={accountOpen} onOpenChange={setAccountOpen}>
            <Popover.Trigger asChild>
              <button
                ref={accountButton}
                type="button"
                aria-label="账户"
                className="rail-account-button mx-auto grid size-11 place-items-center rounded-full bg-primary text-lg text-canvas"
              >
                {Array.from(identity.email?.trim() || '?')[0].toUpperCase()}
              </button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                side="right"
                align="end"
                sideOffset={12}
                avoidCollisions
                collisionPadding={12}
                aria-label="账户"
                onCloseAutoFocus={(event) => {
                  event.preventDefault();
                  accountButton.current?.focus();
                }}
                className="account-popover z-50 rounded-xl border border-border bg-surface p-3 shadow-elevation-2"
              >
                <p className="mb-1 text-xs text-secondary">
                  {identity.email || ''}
                </p>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    setError('');
                    void useAuth
                      .getState()
                      .logout()
                      .catch((failure: unknown) =>
                        setError(
                          failure instanceof Error
                            ? failure.message
                            : '退出失败',
                        ),
                      )
                      .finally(() => setBusy(false));
                  }}
                >
                  退出登录
                </Button>
                {error && (
                  <p role="alert" className="break-words">
                    {error}
                  </p>
                )}
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </div>
      )}
    </aside>
  );
}

export function AppShell() {
  const personaId = usePersonaId();
  const mobile = useMobile();
  const { error } = useStatus();
  const location = useLocation();
  const outlet = useOutlet();
  const twinLevel = location.pathname === '/twins';
  const canManage = useCanManage();
  const [onboarding, setOnboarding] = usePersonaState<IdentityData | null>(
    null,
  );
  const [checked, setChecked] = useState(false);
  const [noPersona, setNoPersona] = usePersonaState(false);
  useEffect(startStatusPolling, [personaId]);
  useEffect(() => {
    if (twinLevel) return;
    const controller = new AbortController();
    void Promise.all([
      api<IdentityData>('/api/identity', { signal: controller.signal }),
      api<{ counts: { sources: number } }>('/api/status', {
        signal: controller.signal,
      }),
    ])
      .then(([identity, status]) => {
        if (
          !controller.signal.aborted &&
          !identity.visitor &&
          (identity.onboarding_pending ||
            (identity.name_source === 'config' && status.counts.sources === 0))
        )
          startTransition(() => setOnboarding(identity));
      })
      .catch((failure: unknown) => {
        if (
          !controller.signal.aborted &&
          failure instanceof ApiError &&
          failure.code === 'no_persona'
        ) {
          setNoPersona(true);
          void usePersonas
            .getState()
            .refresh()
            .catch(() => {});
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecked(true);
      });
    return () => controller.abort();
  }, [twinLevel, personaId, setOnboarding, setNoPersona]);
  if (!canManage && !twinLevel && location.pathname !== '/chat')
    return <Navigate to="/chat" replace />;
  if (noPersona && !twinLevel)
    return (
      <main className="entry-page min-h-dvh">
        <StageHeader variant="brand" />
        <section className="mx-auto max-w-sm space-y-6 px-4 py-8">
          <h2 className="text-xl font-semibold">先新建一个分身</h2>
          <Link to="/twins" className="text-sm text-accent underline">
            返回我的分身
          </Link>
          <NewTwin initialOpen />
        </section>
      </main>
    );
  if (!twinLevel && location.pathname !== '/gallery') {
    if (!checked) return <Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />;
    if (onboarding)
      return (
        <>
          <Suspense
            fallback={<Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />}
          >
            <Onboarding
              identity={onboarding}
              onDone={() => setOnboarding(null)}
            />
          </Suspense>
        </>
      );
  }
  return (
    <div className="app-shell flex min-h-dvh">
      <a
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById('main')?.focus();
        }}
        className="sr-only fixed top-2 left-2 z-70 rounded-md bg-surface p-2 focus:not-sr-only"
      >
        跳至主内容
      </a>
      {!mobile && <TwinRail />}
      <div className="flex min-w-0 flex-1 flex-col">
        {error && !twinLevel && (
          <div
            role="alert"
            className="border-b border-danger/20 bg-danger/5 px-5 py-2 text-sm text-danger"
          >
            {error}
          </div>
        )}
        <main
          id="main"
          tabIndex={-1}
          className={`app-main mx-auto w-full flex-1 outline-none ${location.pathname === '/chat' ? 'chat-main' : 'max-w-6xl content-main'}`}
        >
          {location.pathname === '/chat' ? (
            outlet
          ) : (
            <PageTransition route={location.pathname}>
              {location.pathname === '/gallery' ? (
                <>
                  <StageHeader />
                  <div className="page-content">{outlet}</div>
                </>
              ) : (
                outlet
              )}
            </PageTransition>
          )}
        </main>
      </div>
      {mobile && !twinLevel && <BottomTabs />}
    </div>
  );
}
