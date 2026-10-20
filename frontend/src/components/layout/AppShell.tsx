import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { Navigate, useLocation, useOutlet } from 'react-router';
import { Plus } from 'lucide-react';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import {
  BookUser,
  Briefcase,
  ListChecks,
  LogOut,
  MessageCircle,
  Mic,
  Settings2,
  Users,
} from 'lucide-react';
import { startStatusPolling, useStatus } from '../../stores/status';
import { failing, startSystemPolling, useSystem } from '../../stores/system';
import { SystemDialog, useOpenSystem } from '../../features/admin/SystemDialog';
import {
  AccountMenu,
  Card,
  Heading,
  Stack,
  NavPill,
  PlainButton,
  Row,
  Skeleton,
  SkipLink,
  Text,
  TextLink,
  ThemePicker,
  Tooltip,
} from '../ui';
import { LayoutScope, PageTransition } from '../motion';
import { useMobile } from '../../lib/useMobile';
import { api, ApiError } from '../../lib/api';
import {
  awaitsApproval,
  useCanManage,
  usePersonas,
  useTrial,
  type Persona,
} from '../../stores/personas';
import { recentPersonas, rememberPersona } from '../../lib/recentPersonas';
import { PersonaSwitcher, PersonaPortrait } from './PersonaSwitcher';
import { NewTwin, NewTwinForm, NewTwinHost, useNewTwinCard } from './NewTwin';
import { accountLabel, featureOn, useAuth } from '../../stores/auth';
import { StageHeader } from './StageHeader';
import { THEMES, useTheme } from '../../stores/theme';
const Claimed = lazy(() =>
  import('../../pages/Claimed').then((module) => ({
    default: module.Claimed,
  })),
);
const MemberVoice = lazy(() =>
  import('../../pages/MemberVoice').then((module) => ({
    default: module.MemberVoice,
  })),
);

export const navItems = [
  { route: 'chat', title: '聊天', icon: MessageCircle, visitor: true },
  { route: 'work', title: '工作', icon: Briefcase, visitor: true },
  { route: 'profile', title: '档案', icon: BookUser, visitor: false },
  { route: 'ledger', title: '承诺账本', icon: ListChecks, visitor: false },
];

// Pages laid out as a conversation (stage, thread, pinned composer), full width and without a page transition.
const conversationRoutes = new Set(['/chat', '/work']);
const visitorRoutes = new Set(
  navItems.filter((item) => item.visitor).map((item) => item.route),
);

function useNavItems() {
  const canManage = useCanManage();
  const identity = useAuth((state) => state.identity);
  // A page an administrator switched off leaves the menu for everyone; chat always stays.
  return navItems.filter(
    (item) =>
      (canManage || item.visitor) &&
      (item.route !== 'work' && item.route !== 'ledger'
        ? true
        : featureOn(identity, item.route)),
  );
}

function Navigation() {
  const items = useNavItems();
  return (
    <LayoutScope>
      <nav aria-label="主导航" className="space-y-1">
        {items.map(({ route, title, icon }) => (
          <NavPill
            key={route}
            to={`/${route}`}
            icon={icon}
            label={title}
            layout="rail"
            indicator="active-nav"
          />
        ))}
      </nav>
    </LayoutScope>
  );
}

function BottomTabs() {
  const items = useNavItems();
  return (
    <nav
      aria-label="底部导航"
      className={`mobile-tabs fixed inset-x-0 bottom-0 z-30 grid gap-2 border-t border-border bg-canvas px-3 pt-2 md:hidden ${['grid-cols-1', 'grid-cols-2', 'grid-cols-3', 'grid-cols-4'][items.length - 1]}`}
    >
      {items.map(({ route, title, icon }) => (
        <NavPill
          key={route}
          to={`/${route}`}
          icon={icon}
          label={title}
          layout="inline"
        />
      ))}
    </nav>
  );
}

// Other twins shown in the rail beside the current one.
const RAIL_SHORTCUTS = 2;

/** `empty`: the account has no twin at all (not merely a list still loading). */
function TwinRail({ empty = false }: { empty?: boolean }) {
  const { id, items, pendingId, refresh, switchTo } = usePersonas();
  const current = items.find((item) => item.id === id);
  // Collapsed to the current twin and the few used last; the rest are one click away in the switcher.
  const [recent, setRecent] = useState(recentPersonas);
  useEffect(() => {
    rememberPersona(id);
    setRecent(recentPersonas());
  }, [id]);
  const others = items.filter((item) => item.id !== id);
  const rank = (persona: Persona) => {
    const at = recent.indexOf(persona.id);
    return at < 0 ? recent.length + others.indexOf(persona) : at;
  };
  const shortcuts = [...others]
    .sort((a, b) => rank(a) - rank(b))
    .slice(0, RAIL_SHORTCUTS);
  const hidden = others.length - shortcuts.length;
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
  const name = current?.name || '本人';
  const [creating, setCreating] = useState(false);
  // Three scopes, top to bottom: the team's space, the twin being worked on with its own pages, the other twins.
  return (
    <aside className="nav-rail sticky top-0 flex h-dvh shrink-0 flex-col items-center overflow-y-auto px-3 py-4">
      <nav aria-label="团队空间" className="flex flex-col gap-1">
        {[
          { to: '/team', title: '团队', icon: Users },
          { to: '/library', title: '录音库', icon: Mic },
        ].map(({ to, title, icon }) => (
          <NavPill key={to} to={to} icon={icon} label={title} layout="rail" />
        ))}
      </nav>
      <div className="rail-divider my-3 w-7" />
      <section
        aria-label={`当前分身：${name}`}
        className="flex flex-col items-center gap-1"
      >
        {!empty ? (
          <Tooltip label={`切换分身（当前：${name}）`}>
            <span>
              <PersonaSwitcher
                label={`切换分身（当前：${name}）`}
                className="rail-current"
                trigger={<PersonaPortrait persona={current} />}
              />
            </span>
          </Tooltip>
        ) : (
          // No twin yet: an empty slot where it will be, which makes one.
          <Tooltip label="新建分身">
            <PlainButton
              shape="circle"
              aria-label="还没有分身，新建一个"
              aria-haspopup="dialog"
              className="rail-current rail-current-empty text-secondary"
              onClick={() => useNewTwinCard.getState().set(true)}
            >
              <Plus aria-hidden className="size-4" />
            </PlainButton>
          </Tooltip>
        )}
        <div className="w-full">
          <Navigation />
        </div>
      </section>
      <div className="flex-1" />
      <div
        className="flex flex-col items-center gap-2"
        aria-label="分身快捷切换"
      >
        {shortcuts.map((persona) => (
          <Tooltip key={persona.id} label={persona.name}>
            <PlainButton
              shape="circle"
              aria-label={`切换到${persona.name}`}
              aria-busy={pendingId === persona.id}
              className="rail-twin hover:bg-soft"
              onClick={() => void switchTo(persona.id)}
            >
              <PersonaPortrait persona={persona} />
            </PlainButton>
          </Tooltip>
        ))}
        {hidden > 0 && (
          <Tooltip label="全部分身">
            <span>
              <PersonaSwitcher
                label={`还有 ${hidden} 个分身`}
                className="grid size-9 place-items-center bg-soft hover:bg-border"
                trigger={
                  <Text as="span" size="sm" weight="semibold" tone="accent">
                    +{hidden}
                  </Text>
                }
              />
            </span>
          </Tooltip>
        )}
        <Tooltip label="新建分身" hidden={creating}>
          <span>
            <NewTwin variant="rail" onOpenChange={setCreating} />
          </span>
        </Tooltip>
      </div>
      <RailAccount />
    </aside>
  );
}

/** The account menu at the foot of the rail: who is signed in, the palette, the system settings for an
 * administrator (a red dot when a switched-on service is failing), and signing out. */
function RailAccount() {
  const identity = useAuth((state) => state.identity);
  const openSystem = useOpenSystem();
  const down = useSystem((state) => failing(state.data).length);
  const { theme, setTheme } = useTheme();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!identity) return null;
  const canSignOut = identity.auth_enabled;
  return (
    <div className="rail-account mt-auto pt-4">
      <AccountMenu
        name={accountLabel(identity) || '本机'}
        detail={identity.admin ? '管理员' : undefined}
        error={error}
        theme={
          <ThemePicker value={theme} options={THEMES} onChange={setTheme} />
        }
        groups={[
          identity.admin
            ? [
                {
                  key: 'system',
                  label: '系统设置',
                  icon: Settings2,
                  alert: down ? `${down} 项服务异常` : undefined,
                  onSelect: () => openSystem(),
                },
              ]
            : [],
          canSignOut
            ? [
                {
                  key: 'logout',
                  label: '退出登录',
                  icon: LogOut,
                  danger: true,
                  disabled: busy,
                  onSelect: () => {
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
                  },
                },
              ]
            : [],
        ]}
      />
    </div>
  );
}

export function AppShell() {
  const personaId = usePersonaId();
  const mobile = useMobile();
  const { error } = useStatus();
  const location = useLocation();
  const conversation = conversationRoutes.has(location.pathname);
  const outlet = useOutlet();
  // Account-level pages: not about the current twin, so no twin check or twin tabs.
  const twinLevel =
    location.pathname === '/twins' ||
    location.pathname === '/team' ||
    location.pathname === '/library' ||
    location.pathname.startsWith('/library/') ||
    location.pathname === '/voice';
  const canManage = useCanManage();
  const [checked, setChecked] = useState(false);
  const [noPersona, setNoPersona] = usePersonaState(false);
  useEffect(startStatusPolling, [personaId]);
  const admin = useAuth((state) => state.identity?.admin);
  // Signed in through the company login: look for them in colleagues' meetings before an empty twin.
  const address = useAuth(
    (state) => state.identity?.address || state.identity?.account,
  );
  const [listened, setListened] = useState(false);
  const skipVoice = useCallback(() => setListened(true), []);
  useEffect(() => (admin ? startSystemPolling() : undefined), [admin]);
  // A twin a colleague made for this person comes first: until they have looked at it, it answers nobody else.
  const waiting = usePersonas((state) => state.items.find(awaitsApproval));
  const trial = useTrial();
  // Trying it out in chat first: the page asking for the go-ahead steps aside there, and only there.
  const trying =
    !!waiting && trial.id === waiting.id && location.pathname === '/chat';
  useEffect(() => {
    if (waiting && waiting.id !== personaId)
      void usePersonas.getState().switchTo(waiting.id);
  }, [waiting, personaId]);
  useEffect(() => {
    if (twinLevel) return;
    const controller = new AbortController();
    // Getting to know a new twin happens in its chat (the setup card); here only whether there is a twin at all.
    void api('/api/identity', { signal: controller.signal })
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
  }, [twinLevel, personaId, setNoPersona]);
  if (waiting && !trying && location.pathname !== '/gallery')
    return (
      <Suspense
        fallback={<Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />}
      >
        <Claimed persona={waiting} />
      </Suspense>
    );
  if (
    !canManage &&
    !twinLevel &&
    !visitorRoutes.has(location.pathname.slice(1))
  )
    return <Navigate to="/chat" replace />;
  if (noPersona && !twinLevel && address && !listened)
    return (
      <Suspense
        fallback={<Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />}
      >
        <MemberVoice onSkip={skipVoice} />
      </Suspense>
    );
  // No twin yet on a page about one (chat, work, profile): say so in the page and open the new-twin card right there,
  // in the workspace, rather than leaving it for a page of its own.
  const missing = noPersona && !twinLevel;
  if (!missing && !twinLevel && location.pathname !== '/gallery' && !checked)
    return <Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />;
  return (
    <div
      className={`app-shell flex min-h-dvh ${conversation ? 'conversation-shell' : ''}`}
    >
      <SkipLink target="main">跳至主内容</SkipLink>
      {!mobile && <TwinRail empty={noPersona} />}
      <div
        className={`app-column flex min-w-0 flex-1 flex-col ${conversation ? 'chat-app-column' : ''}`}
      >
        {error && !twinLevel && !missing && (
          <div
            role="alert"
            className="border-b border-danger/20 bg-danger/5 px-5 py-2"
          >
            <Text size="sm" tone="danger">
              {error}
            </Text>
          </div>
        )}
        {trying && (
          <div className="border-b border-info/20 bg-info/5 px-5 py-2">
            <Row justify="between" wrap gap={3}>
              <Text size="sm">试聊中：你点“没问题”之前，同事问不到它。</Text>
              <PlainButton onClick={() => trial.set(null)}>
                回去确认
              </PlainButton>
            </Row>
          </div>
        )}
        <main
          id="main"
          tabIndex={-1}
          className={`app-main mx-auto w-full flex-1 outline-none ${conversation ? 'chat-main' : 'max-w-6xl content-main'}`}
        >
          {conversation && !missing ? (
            outlet
          ) : (
            <PageTransition route={location.pathname}>
              {missing ? (
                // Nothing else here yet: the twin is made right on the page, with the navigation still around it.
                <div className="mx-auto w-full max-w-md px-4 py-12">
                  <Card as="section" aria-labelledby="no-twin-title">
                    <Stack gap={4}>
                      <Stack gap={2}>
                        <Heading id="no-twin-title" level={1} size="title">
                          先新建一个分身
                        </Heading>
                        <Text tone="secondary">
                          还没有人为你建分身。先建一个，再加一段会议录音，它就会慢慢认识你。
                        </Text>
                      </Stack>
                      <NewTwinForm />
                      {address && (
                        <TextLink size="sm" onClick={() => setListened(false)}>
                          其实开过会？回去再听一遍
                        </TextLink>
                      )}
                    </Stack>
                  </Card>
                </div>
              ) : location.pathname === '/gallery' ? (
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
      {admin && <SystemDialog />}
      <NewTwinHost />
    </div>
  );
}
