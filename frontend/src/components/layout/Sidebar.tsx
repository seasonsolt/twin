import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import {
  BookUser,
  Inbox,
  ListChecks,
  LogOut,
  MessageCircle,
  MessageCircleQuestion,
  Mic,
  Settings2,
  Upload,
  Users,
} from 'lucide-react';
import { failing, useSystem } from '../../stores/system';
import { useOpenSystem } from '../../features/admin/SystemDialog';
import {
  AccountMenu,
  Button,
  FileInput,
  NavPill,
  SearchButton,
  StatusCard,
  TeamMark,
  ThemePicker,
} from '../ui';
import { useCanManage, useSelfTwin } from '../../stores/access';
import { usePersonas } from '../../stores/personas';
import { TEAM_NAME, useTeam } from '../../stores/team';
import { api } from '../../lib/api';
import { twinMemberPath } from '../../lib/members';
import { usePolling } from '../../lib/usePolling';
import {
  FOLLOWUPS_CHANGED,
  type FollowupList,
} from '../../features/followups/useFollowups';
import { useUploads } from '../../features/library/useUploads';
import { memberCount, waitingCount } from '../../features/library/teamCounts';
import { FindPerson } from './FindPerson';
import { accountLabel, featureOn, useAuth } from '../../stores/auth';
import { THEMES, useTheme } from '../../stores/theme';

/** The phone's bottom tabs; the wide side bar has its own entries (below). */
const navItems = [
  { route: 'chat', title: '聊天', icon: MessageCircle, visitor: true },
  { route: 'profile', title: '档案', icon: BookUser, visitor: false },
  { route: 'ledger', title: '承诺账本', icon: ListChecks, visitor: false },
];

/** What a guest, who may only talk to the twins, can open: the conversation, and the old address of work, which
 * leads into it. */
export const visitorRoutes = new Set([
  ...navItems.filter((item) => item.visitor).map((item) => item.route),
  'work',
]);

function useNavItems() {
  const canManage = useCanManage();
  const identity = useAuth((state) => state.identity);
  // A page an administrator switched off leaves the menu for everyone; chat always stays.
  return navItems.filter(
    (item) =>
      (canManage || item.visitor) &&
      (item.route !== 'ledger' ? true : featureOn(identity, item.route)),
  );
}

export function BottomTabs() {
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

/** The side bar: whose space it is, finding someone, uploading, the places to work in and how much waits there,
 * and what runs in the background. A guest, who may only talk to the twins, has the conversation alone. */
export function Sidebar() {
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
  const members = people ? memberCount(people, twins) : undefined;
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
          active:
            (location.pathname === '/team' && !todo) ||
            location.pathname.startsWith('/team/'),
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

/** How many questions wait for the person in their own twin's 你不在时 (none for someone without such a twin). */
function useWaiting(twinId: string | undefined) {
  const [count, setCount] = useState(0);
  const load = useCallback(async () => {
    if (!twinId) {
      setCount(0);
      return;
    }
    try {
      const list = await api<FollowupList>('/api/persona/followups', {
        headers: { 'X-Twin-Persona': twinId },
      });
      setCount(
        (list.items ?? []).filter((item) => item.status === 'pending').length,
      );
    } catch {
      // A count that cannot be had is no count: the account stays as it is.
    }
  }, [twinId]);
  useEffect(() => {
    void load();
    const changed = () => void load();
    window.addEventListener(FOLLOWUPS_CHANGED, changed);
    return () => window.removeEventListener(FOLLOWUPS_CHANGED, changed);
  }, [load]);
  usePolling(load, twinId ? 60000 : 0);
  return twinId ? count : 0;
}

/** The account menu at the foot of the side bar: who is signed in, the palette, the system settings for an
 * administrator (a red dot when a switched-on service is failing), and signing out. */
export function SidebarAccount() {
  const identity = useAuth((state) => state.identity);
  const navigate = useNavigate();
  const self = useSelfTwin();
  const waiting = useWaiting(self?.can_manage === false ? undefined : self?.id);
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
        count={waiting}
        error={error}
        theme={
          <ThemePicker value={theme} options={THEMES} onChange={setTheme} />
        }
        groups={[
          self && waiting > 0
            ? [
                {
                  key: 'away',
                  label: '你不在时',
                  icon: MessageCircleQuestion,
                  count: waiting,
                  onSelect: () =>
                    void navigate(twinMemberPath(self.id, 'away')),
                },
              ]
            : [],
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
