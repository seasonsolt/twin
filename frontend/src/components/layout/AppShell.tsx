import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation, useOutlet } from 'react-router';
import { motion } from 'motion/react';
import { BookUser, Folder, MessageCircle, Plus } from 'lucide-react';
import { useMotionPreset } from '../../design/motion';
import { startStatusPolling, useStatus } from '../../stores/status';
import { Button, Dialog, Skeleton, Tooltip } from '../ui';
import { LayoutScope, PageTransition } from '../motion';
import { useMobile } from '../../lib/useMobile';
import { api, ApiError } from '../../lib/api';
import { usePersonas } from '../../stores/personas';
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
  { route: 'memories', title: '记忆', icon: Folder },
  { route: 'about', title: '关于他', icon: BookUser },
];

function Navigation() {
  const { reduced, transition } = useMotionPreset('layout');
  return (
    <LayoutScope>
      <nav aria-label="主导航" className="space-y-1">
        {navItems.map(({ route, title, icon: Icon }) => {
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
  return (
    <nav
      aria-label="底部导航"
      className="mobile-tabs fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 gap-2 border-t border-border bg-canvas px-3 pt-2 md:hidden"
    >
      {navItems.map(({ route, title, icon: Icon }) => (
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
  const { id, items, refresh, switchTo } = usePersonas();
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
    <aside className="nav-rail sticky top-0 flex h-dvh shrink-0 flex-col border-r border-border bg-canvas px-2 py-4 text-primary">
      <Link
        to="/twins"
        aria-label="我的分身"
        className="persona-name my-3 mb-6 text-center text-2xl"
      >
        twin
      </Link>
      <nav className="rail-twins" aria-label="分身导航">
        {items.slice(0, 6).map((persona) => (
          <Tooltip key={persona.id} label={persona.name}>
            <button
              type="button"
              className="rail-twin rounded-full"
              aria-label={`切换到${persona.name}`}
              aria-pressed={id === persona.id}
              onClick={() => switchTo(persona.id)}
            >
              <PersonaPortrait persona={persona} />
            </button>
          </Tooltip>
        ))}
      </nav>
      <Link
        to="/twins"
        className="rail-all min-h-11 rounded-full text-center text-xs"
      >
        全部
      </Link>
      <NewTwin className="rail-new grid min-h-11 place-items-center rounded-full">
        <Plus size={22} aria-hidden />
      </NewTwin>
      <div className="my-3 border-t border-border" />
      <Navigation />
      {identity?.auth_enabled && (
        <div className="rail-account mt-auto pt-4 text-center text-xs">
          <button
            ref={accountButton}
            type="button"
            aria-label="账户"
            aria-haspopup="dialog"
            aria-expanded={accountOpen}
            className="rail-account-button mx-auto grid size-11 place-items-center rounded-full bg-primary text-lg text-canvas"
            onClick={() => setAccountOpen(!accountOpen)}
          >
            {Array.from(identity.email?.trim() || '?')[0].toUpperCase()}
          </button>
          <Dialog
            open={accountOpen}
            onOpenChange={setAccountOpen}
            title="账户"
            body={identity.email || ''}
            popover
            className="account-popover"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              accountButton.current?.focus();
            }}
          >
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                setError('');
                void useAuth
                  .getState()
                  .logout()
                  .catch((failure: unknown) =>
                    setError(
                      failure instanceof Error ? failure.message : '退出失败',
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
          </Dialog>
        </div>
      )}
    </aside>
  );
}

export function AppShell() {
  const mobile = useMobile();
  const { error } = useStatus();
  const location = useLocation();
  const outlet = useOutlet();
  const twinLevel = location.pathname === '/twins';
  const [onboarding, setOnboarding] = useState<IdentityData | null>(null);
  const [checked, setChecked] = useState(false);
  const [noPersona, setNoPersona] = useState(false);
  useEffect(startStatusPolling, []);
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
          (identity.onboarding_pending ||
            (identity.name_source === 'config' && status.counts.sources === 0))
        )
          setOnboarding(identity);
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
  }, [twinLevel]);
  if (noPersona && !twinLevel)
    return (
      <main className="entry-page min-h-dvh">
        <StageHeader variant="brand" />
        <section className="mx-auto max-w-sm space-y-6 px-4 py-8">
          <h2 className="text-xl font-semibold">先新建一个分身</h2>
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
                  <StageHeader left={<PersonaSwitcher stage />} />
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
