import { lazy, Suspense, useEffect, useState, type CSSProperties } from 'react';
import { NavLink, useLocation, useOutlet } from 'react-router';
import { motion } from 'motion/react';
import {
  BookUser,
  Folder,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import { useMotionPreset } from '../../design/motion';
import { startStatusPolling, useStatus } from '../../stores/status';
import { Badge, IconButton, Skeleton, Tooltip } from '../ui';
import { LayoutScope, PageTransition } from '../motion';
import { useMobile } from '../../lib/useMobile';
import { api } from '../../lib/api';
import type { IdentityData } from '../../features/identity/useIdentity';
const Onboarding = lazy(() =>
  import('../../pages/Onboarding').then((module) => ({
    default: module.Onboarding,
  })),
);

export const navItems = [
  { route: 'chat', title: '聊天', icon: MessageCircle },
  { route: 'memories', title: '记忆', icon: Folder },
  { route: 'about', title: '关于你', icon: BookUser },
];

function Navigation({
  collapsed = false,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const { reduced, transition } = useMotionPreset('layout');
  return (
    <LayoutScope>
      <nav aria-label="主导航" className="space-y-1">
        {navItems.map(({ route, title, icon: Icon }) => {
          const link = (
            <NavLink
              key={route}
              to={`/${route}`}
              onClick={onNavigate}
              aria-label={collapsed ? title : undefined}
              className="relative flex min-h-11 items-center gap-3 rounded-md px-3 text-secondary hover:text-primary"
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId={reduced ? undefined : 'active-nav'}
                      initial={reduced ? { opacity: 0 } : false}
                      animate={{ opacity: 1 }}
                      transition={transition}
                      className="absolute inset-0 rounded-md border border-accent/10 bg-accent/10"
                    />
                  )}
                  <Icon aria-hidden className="relative size-5 shrink-0" />
                  {!collapsed && (
                    <span className="relative whitespace-nowrap">{title}</span>
                  )}
                </>
              )}
            </NavLink>
          );
          return collapsed ? (
            <Tooltip key={route} label={title}>
              {link}
            </Tooltip>
          ) : (
            link
          );
        })}
      </nav>
    </LayoutScope>
  );
}

function BottomTabs() {
  return (
    <nav
      aria-label="底部导航"
      className="mobile-tabs fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t border-border bg-surface/95 backdrop-blur-xl md:hidden"
    >
      {navItems.map(({ route, title, icon: Icon }) => (
        <NavLink
          key={route}
          to={`/${route}`}
          className={({ isActive }) =>
            `flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs ${isActive ? 'font-semibold text-accent' : 'text-secondary'}`
          }
        >
          <Icon className="size-5" aria-hidden />
          <span>{title}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false);
  const mobile = useMobile();
  const { data, error } = useStatus();
  const { reduced, transition } = useMotionPreset('layout');
  const location = useLocation();
  const outlet = useOutlet();
  const [onboarding, setOnboarding] = useState<IdentityData | null>(null);
  const [checked, setChecked] = useState(false);
  useEffect(startStatusPolling, []);
  useEffect(() => {
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
          identity.name_source === 'config' &&
          status.counts.sources === 0
        )
          setOnboarding(identity);
      })
      .catch(() => {})
      .finally(() => {
        if (!controller.signal.aborted) setChecked(true);
      });
    return () => controller.abort();
  }, []);
  if (location.pathname !== '/gallery') {
    if (!checked) return <Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />;
    if (onboarding)
      return (
        <Suspense
          fallback={<Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />}
        >
          <Onboarding
            identity={onboarding}
            onDone={() => setOnboarding(null)}
          />
        </Suspense>
      );
  }
  return (
    <div
      className="flex min-h-dvh"
      style={
        { '--sidebar-width': collapsed ? '76px' : '228px' } as CSSProperties
      }
    >
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
      <motion.aside
        style={{
          background: 'var(--sidebar)',
          ...(reduced ? { width: collapsed ? 76 : 228 } : {}),
        }}
        animate={reduced ? { opacity: 1 } : { width: collapsed ? 76 : 228 }}
        transition={transition}
        className="sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border p-4 backdrop-blur-xl md:flex"
      >
        <div className="mb-10 flex h-10 items-center gap-3 overflow-hidden">
          <span className="grid size-10 shrink-0 place-items-center rounded-md bg-accent text-lg font-semibold text-on-accent">
            t
          </span>
          {!collapsed && <span className="text-lg font-semibold">twin</span>}
        </div>
        {!mobile && <Navigation collapsed={collapsed} />}
        <div className="mt-auto pt-8">
          <Tooltip label={collapsed ? '展开侧栏' : '收起侧栏'}>
            <IconButton
              label={collapsed ? '展开侧栏' : '收起侧栏'}
              aria-expanded={!collapsed}
              onClick={() => setCollapsed(!collapsed)}
            >
              {collapsed ? (
                <PanelLeftOpen className="size-5" />
              ) : (
                <PanelLeftClose className="size-5" />
              )}
            </IconButton>
          </Tooltip>
        </div>
      </motion.aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="hidden min-h-16 flex-wrap items-center gap-3 border-b border-border px-8 py-3 md:flex">
          {data ? (
            <Badge>{data.target_name}</Badge>
          ) : (
            <Skeleton className="w-40" />
          )}
        </header>
        {error && (
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
          className="app-main mx-auto w-full max-w-6xl flex-1 px-4 pt-4 outline-none md:px-8 md:py-8"
        >
          {location.pathname === '/chat' ? (
            outlet
          ) : (
            <PageTransition route={location.pathname}>{outlet}</PageTransition>
          )}
        </main>
      </div>
      {mobile && <BottomTabs />}
    </div>
  );
}
