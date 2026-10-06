import { lazy, Suspense, useEffect, useState } from 'react';
import { NavLink, useLocation, useOutlet } from 'react-router';
import { AnimatePresence, motion } from 'motion/react';
import * as Drawer from '@radix-ui/react-dialog';
import {
  BookUser,
  Folder,
  Menu,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  X,
} from 'lucide-react';
import { useMotionPreset } from '../../design/motion';
import { startStatusPolling, useStatus } from '../../stores/status';
import { Badge, IconButton, Skeleton, Tooltip } from '../ui';
import { LayoutScope, PageTransition, shouldDismissDrag } from '../motion';
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

function MobileDrawer({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const { reduced, transition, exit } = useMotionPreset('layout');
  return (
    <Drawer.Root open={open} onOpenChange={setOpen}>
      <Drawer.Trigger asChild>
        <IconButton label="打开导航" className="md:hidden">
          <Menu className="size-5" />
        </IconButton>
      </Drawer.Trigger>
      <Drawer.Portal forceMount>
        <AnimatePresence>
          {open && (
            <Drawer.Overlay key="backdrop" forceMount asChild>
              <motion.div
                key="backdrop"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={exit}
                className="fixed inset-0 z-40 bg-black/25 backdrop-blur-sm"
              />
            </Drawer.Overlay>
          )}
          {open && (
            <Drawer.Content key="drawer" forceMount asChild>
              <motion.div
                key="drawer"
                initial={{ opacity: 0, y: reduced ? 0 : '100%' }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: reduced ? 0 : '100%', transition: exit }}
                transition={transition}
                drag={reduced ? false : 'y'}
                dragConstraints={{ top: 0, bottom: 0 }}
                dragElastic={{ top: 0.05, bottom: 0.5 }}
                dragSnapToOrigin
                dragMomentum
                onDragEnd={(_, info) => {
                  if (
                    info.offset.y > 0 &&
                    shouldDismissDrag(info.offset.y, info.velocity.y)
                  )
                    setOpen(false);
                }}
                className="fixed right-0 bottom-0 left-0 z-50 rounded-t-xl border border-border bg-surface p-5 pb-[max(20px,env(safe-area-inset-bottom))] shadow-elevation-3"
                style={{ touchAction: 'pan-x' }}
              >
                <div
                  aria-hidden
                  className="mx-auto mb-4 h-1 w-10 rounded-full bg-border"
                />
                <div className="mb-3 flex items-center justify-between">
                  <Drawer.Title className="text-lg font-semibold">
                    导航
                  </Drawer.Title>
                  <Drawer.Close asChild>
                    <IconButton label="关闭导航">
                      <X className="size-5" />
                    </IconButton>
                  </Drawer.Close>
                </div>
                <Drawer.Description className="sr-only">
                  选择要打开的页面
                </Drawer.Description>
                <Navigation onNavigate={() => setOpen(false)} />
              </motion.div>
            </Drawer.Content>
          )}
        </AnimatePresence>
      </Drawer.Portal>
    </Drawer.Root>
  );
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);
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
  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 768px)');
    const change = () => {
      if (desktop.matches) setDrawer(false);
    };
    desktop.addEventListener('change', change);
    return () => desktop.removeEventListener('change', change);
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
    <div className="flex min-h-dvh">
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
        <Navigation collapsed={collapsed} />
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
        <header className="flex min-h-20 flex-wrap items-center gap-3 border-b border-border px-5 py-4 md:px-8">
          <MobileDrawer open={drawer} setOpen={setDrawer} />
          <span className="mr-auto font-semibold md:hidden">twin</span>
          {data ? (
            <>
              <Badge>{data.target_name}</Badge>
              <span className="ml-auto text-xs text-tertiary">
                {data.labels.explicit}
              </span>
            </>
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
          className="mx-auto w-full max-w-6xl flex-1 px-5 py-8 outline-none md:px-8 md:py-10"
        >
          <PageTransition route={location.pathname}>{outlet}</PageTransition>
        </main>
        <footer className="border-t border-border px-5 py-5 text-xs leading-relaxed text-secondary md:px-8">
          {data?.labels.disclaimer ?? <Skeleton className="max-w-lg" />}
        </footer>
      </div>
    </div>
  );
}
