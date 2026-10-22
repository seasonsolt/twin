import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { Navigate, useLocation, useOutlet } from 'react-router';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import {
  BookUser,
  Briefcase,
  Inbox,
  ListChecks,
  LogOut,
  MessageCircle,
  Mic,
  Settings2,
  Upload,
  Users,
} from 'lucide-react';
import { startStatusPolling, useStatus } from '../../stores/status';
import { failing, startSystemPolling, useSystem } from '../../stores/system';
import { SystemDialog, useOpenSystem } from '../../features/admin/SystemDialog';
import {
  AccountMenu,
  Button,
  Card,
  FileInput,
  Heading,
  Stack,
  NavPill,
  PlainButton,
  Row,
  SearchButton,
  Skeleton,
  SkipLink,
  StatusCard,
  TeamMark,
  Text,
  TextLink,
  ThemePicker,
} from '../ui';
import { PageTransition } from '../motion';
import { useMobile } from '../../lib/useMobile';
import { api, ApiError } from '../../lib/api';
import {
  awaitsApproval,
  useCanManage,
  usePersonas,
  useTrial,
} from '../../stores/personas';
import { useTeam } from '../../stores/team';
import { usePolling } from '../../lib/usePolling';
import { useUploads } from '../../features/library/useUploads';
import { namedPeople, waitingCount } from '../../features/library/teamCounts';
import { FindPerson } from './FindPerson';
import { NewTwinForm, NewTwinHost } from './NewTwin';
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

// The backend has no team name yet: the side bar shows this until it does.
const TEAM_NAME = '我的团队';

/** The side bar: whose space it is, finding someone, uploading, the places to work in and how much waits there,
 * and what runs in the background. A guest, who may only talk to the twins, has the conversation alone. */
function Sidebar() {
  const refreshPersonas = usePersonas((state) => state.refresh);
  const twins = usePersonas((state) => state.items);
  const canManage = useCanManage();
  const identity = useAuth((state) => state.identity);
  const location = useLocation();
  const todo =
    location.pathname === '/team' &&
    new URLSearchParams(location.search).get('tab') === 'todo';
  const [finding, setFinding] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const library = useTeam((state) => state.library);
  const people = useTeam((state) => state.people);
  const review = useTeam((state) => state.review);
  const refresh = useCallback(() => useTeam.getState().refresh(), []);
  const { add, unfinished } = useUploads(
    () => void useTeam.getState().refresh(true),
  );
  useEffect(() => {
    const load = () => void refreshPersonas().catch(() => {});
    load();
    window.addEventListener('twin-assets-changed', load);
    window.addEventListener('twin-identity-changed', load);
    return () => {
      window.removeEventListener('twin-assets-changed', load);
      window.removeEventListener('twin-identity-changed', load);
    };
  }, [refreshPersonas]);
  useEffect(() => {
    if (canManage) void refresh();
  }, [canManage, refresh]);
  useEffect(() => {
    if (!canManage) return;
    const open = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setFinding(true);
      }
    };
    window.addEventListener('keydown', open);
    return () => window.removeEventListener('keydown', open);
  }, [canManage]);

  const recordings = library?.recordings ?? [];
  const sending = unfinished.filter((pick) => !pick.error);
  const unsent = unfinished.filter((pick) => pick.error);
  const transcribing = recordings.filter((r) => r.status === 'transcribing');
  const queued = recordings.filter((r) => r.status === 'queued');
  const organising = people?.filter((p) => p.updating) ?? [];
  const jobs =
    sending.length + transcribing.length + queued.length + organising.length;
  usePolling(refresh, !canManage ? 0 : jobs ? 3000 : 30000);
  const members = people ? namedPeople(people).length : undefined;
  const waiting =
    people && review ? waitingCount({ people, review, recordings, twins }) : 0;
  // How far the piece of work under way has got: the file being sent, else the recording being transcribed.
  const moving = sending.find((pick) => pick.progress);
  const progress = moving?.progress
    ? { value: moving.progress.offset, max: moving.progress.size }
    : transcribing[0]
      ? {
          value: transcribing[0].duration_s
            ? transcribing[0].transcribed_s
            : null,
          max: transcribing[0].duration_s ?? 1,
        }
      : undefined;
  const background = [
    sending.length && `${sending.length} 项上传中`,
    transcribing.length && `${transcribing.length} 项转写中`,
    queued.length && `${queued.length} 项排队`,
    organising.length && `${organising.length} 人整理中`,
    unsent.length && `${unsent.length} 项上传失败`,
  ].filter(Boolean);
  const items = canManage
    ? [
        {
          to: '/team',
          title: '团队',
          icon: Users,
          count: members,
          active: location.pathname === '/team' && !todo,
        },
        { to: '/chat', title: '对话', icon: MessageCircle },
        { to: '/library', title: '录音库', icon: Mic },
        {
          to: '/team?tab=todo',
          title: '待处理',
          icon: Inbox,
          count: waiting || undefined,
          accent: true,
          active: todo,
        },
        ...(featureOn(identity, 'ledger')
          ? [{ to: '/ledger', title: '承诺', icon: ListChecks }]
          : []),
      ]
    : [{ to: '/chat', title: '对话', icon: MessageCircle }];
  return (
    <aside className="nav-sidebar sticky top-0 flex h-dvh shrink-0 flex-col gap-3 overflow-y-auto px-3 py-4">
      <TeamMark name={TEAM_NAME} />
      {canManage && (
        <>
          <SearchButton
            label="找人"
            shortcut="⌘K"
            onClick={() => setFinding(true)}
          />
          <Button
            size="lg"
            className="w-full"
            onClick={() => input.current?.click()}
          >
            <Upload aria-hidden className="size-5" />
            上传会议录音
          </Button>
          <FileInput
            ref={input}
            label="选择录音文件"
            multiple
            onFiles={(files) => void add(files)}
          />
          <FindPerson open={finding} onOpenChange={setFinding} />
        </>
      )}
      <nav aria-label="主导航" className="flex flex-col gap-0.5">
        {items.map(({ to, title, icon, count, accent, active }) => (
          <NavPill
            key={to}
            to={to}
            icon={icon}
            label={title}
            layout="sidebar"
            count={count}
            countTone={accent ? 'accent' : 'muted'}
            active={active}
          />
        ))}
      </nav>
      <div className="flex-1" />
      {background.length > 0 && (
        <StatusCard
          to="/library"
          title={`后台 ${jobs + unsent.length} 项`}
          action="查看"
          detail={background.join(' · ')}
          progress={progress && { ...progress, label: '当前一项的进度' }}
        />
      )}
      <SidebarAccount />
    </aside>
  );
}

/** The account menu at the foot of the side bar: who is signed in, the palette, the system settings for an
 * administrator (a red dot when a switched-on service is failing), and signing out. */
function SidebarAccount() {
  const identity = useAuth((state) => state.identity);
  const openSystem = useOpenSystem();
  const down = useSystem((state) => failing(state.data).length);
  const { theme, setTheme } = useTheme();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!identity) return null;
  const canSignOut = identity.auth_enabled;
  return (
    <div className="sidebar-account mt-auto pt-4">
      <AccountMenu
        layout="sidebar"
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
      {!mobile && <Sidebar />}
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
