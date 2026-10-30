import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import {
  BookUser,
  FileText,
  Inbox,
  ListChecks,
  LogOut,
  MessageCircle,
  MessageCircleQuestion,
  Mic,
  ScrollText,
  Settings2,
  Users,
} from 'lucide-react';
import { failing, useSystem } from '../../stores/system';
import { rebuildHeld, useOpenSettings } from '../../features/settings/Settings';
import { useKeepsWill, useOpenWill } from '../../features/will/Will';
import {
  AccountMenu,
  NavPill,
  SearchButton,
  StatusCard,
  TeamMark,
  ThemePicker,
} from '../ui';
import { useCanManage, useSelfTwin } from '../../stores/access';
import { usePersonas } from '../../stores/personas';
import { useTeam, useTeamName } from '../../stores/team';
import { api } from '../../lib/api';
import { twinMemberPath } from '../../lib/members';
import { usePolling } from '../../lib/usePolling';
import { AWAY_CHANGED } from '../../features/away/useAway';
import { useUploads } from '../../features/library/useUploads';
import { memberCount, waitingCount } from '../../features/library/teamCounts';
import { FindPerson } from './FindPerson';
import {
  accountLabel,
  featureOn,
  useAuth,
  usePersonaEdition,
  type Feature,
} from '../../stores/auth';
import { useThemes } from '../../stores/theme';

/** The phone's bottom tabs; the wide side bar has its own entries (below). */
const navItems: {
  route: string;
  title: string;
  icon: typeof MessageCircle;
  visitor: boolean;
  feature?: Feature;
}[] = [
  { route: 'chat', title: '聊天', icon: MessageCircle, visitor: true },
  { route: 'profile', title: '档案', icon: BookUser, visitor: false },
  {
    route: 'commitments',
    title: '承诺',
    icon: ListChecks,
    visitor: false,
    feature: 'ledger',
  },
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
      (!item.feature || featureOn(identity, item.feature)),
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

/** The side bar: whose space it is, finding someone, the places to work in and how much waits there,
 * and what runs in the background. A guest, who may only talk to the twins, has the conversation alone. */
export function Sidebar() {
  const refreshPersonas = usePersonas((state) => state.refresh);
  const twins = usePersonas((state) => state.items);
  // The team's places, its counts and finding someone in it; the persona edition has none of them.
  const persona = usePersonaEdition();
  const canManage = useCanManage() && !persona;
  const identity = useAuth((state) => state.identity);
  const teamName = useTeamName();
  const location = useLocation();
  const [finding, setFinding] = useState(false);
  const onTwin = location.pathname.startsWith('/team/');
  const onSources =
    new URLSearchParams(location.search).get('section') === 'memories';
  const library = useTeam((state) => state.library);
  const people = useTeam((state) => state.people);
  const review = useTeam((state) => state.review);
  const refresh = useCallback(() => useTeam.getState().refresh(), []);
  const { unfinished } = useUploads(
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
  // A file stopped by the person is waiting to be added again, not under way and not a failure.
  const sending = unfinished.filter((pick) => !pick.error && !pick.stopped);
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
  // Where the card leads: the library holds what is being sent and transcribed, the team page who is being organised.
  const place =
    organising.length &&
    !sending.length &&
    !transcribing.length &&
    !queued.length &&
    !unsent.length
      ? '/team'
      : '/library';
  const background = [
    sending.length && `${sending.length} 项上传中`,
    transcribing.length && `${transcribing.length} 项转写中`,
    queued.length && `${queued.length} 项排队`,
    organising.length && `${organising.length} 人整理中`,
    unsent.length && `${unsent.length} 项上传失败`,
  ].filter(Boolean);
  const items: {
    to: string;
    title: string;
    icon: typeof MessageCircle;
    count?: number;
    accent?: boolean;
    active?: boolean;
  }[] = canManage
    ? [
        {
          to: '/team',
          title: '团队',
          icon: Users,
          count: members,
          active:
            location.pathname === '/team' ||
            location.pathname.startsWith('/team/'),
        },
        { to: '/chat', title: '对话', icon: MessageCircle },
        { to: '/library', title: '录音库', icon: Mic },
        {
          to: '/inbox',
          title: '待处理',
          icon: Inbox,
          count: waiting || undefined,
          accent: true,
        },
        ...(featureOn(identity, 'ledger')
          ? [{ to: '/commitments', title: '承诺', icon: ListChecks }]
          : []),
      ]
    : persona
      ? [
          { to: '/chat', title: '对话', icon: MessageCircle },
          // Both are tabs of the twin's own page: what it knows of the person, and what it was given.
          {
            to: '/profile',
            title: '记忆',
            icon: BookUser,
            active: onTwin && !onSources,
          },
          {
            to: '/memories',
            title: '资料',
            icon: FileText,
            active: onTwin && onSources,
          },
        ]
      : [{ to: '/chat', title: '对话', icon: MessageCircle }];
  return (
    <aside className="nav-sidebar sticky top-0 flex h-dvh shrink-0 flex-col gap-3 overflow-y-auto px-3 py-4">
      <TeamMark name={persona ? '我的分身' : teamName} />
      {canManage && (
        <>
          <SearchButton
            label="问一句、找人"
            shortcut="⌘K"
            onClick={() => setFinding(true)}
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
          // Already there, it has nowhere to lead.
          to={
            location.pathname === place ||
            location.pathname.startsWith(`${place}/`)
              ? undefined
              : place
          }
          title="后台"
          action="查看"
          detail={background.join(' · ')}
          progress={progress && { ...progress, label: '当前一项的进度' }}
        />
      )}
      <SidebarAccount />
    </aside>
  );
}

/** How many handoffs wait for the person's decision in their own twin's 你不在时 (none for someone without such a
 * twin). */
function useWaiting(twinId: string | undefined) {
  const [count, setCount] = useState(0);
  // Only the latest question's answer counts: one asked of a twin before the person had another is not theirs now.
  const asked = useRef(0);
  const load = useCallback(async () => {
    const ask = ++asked.current;
    if (!twinId) {
      setCount(0);
      return;
    }
    try {
      const { pending } = await api<{ pending: number }>(
        '/api/persona/handoffs/count',
        { headers: { 'X-Twin-Persona': twinId } },
      );
      if (ask === asked.current) setCount(pending);
    } catch {
      // A count that cannot be had is no count: the account stays as it is.
    }
  }, [twinId]);
  useEffect(() => {
    void load();
    const changed = () => void load();
    window.addEventListener(AWAY_CHANGED, changed);
    return () => window.removeEventListener(AWAY_CHANGED, changed);
  }, [load]);
  usePolling(load, twinId ? 60000 : 0);
  return twinId ? count : 0;
}

/** The account menu at the foot of the side bar: who is signed in, the palette, the settings (for an administrator,
 * a red dot when a switched-on service is failing or the memory rebuild is switched off), and signing out. */
export function SidebarAccount() {
  const identity = useAuth((state) => state.identity);
  const navigate = useNavigate();
  const self = useSelfTwin();
  // The persona edition has no handoffs to wait for.
  const persona = usePersonaEdition();
  const waiting = useWaiting(
    self?.can_manage === false || persona ? undefined : self?.id,
  );
  const openSettings = useOpenSettings();
  // 数字遗嘱: only the person keeps one, in the persona edition.
  const keepsWill = useKeepsWill();
  const openWill = useOpenWill();
  const down = useSystem((state) => failing(state.data).length);
  const held = useSystem((state) => rebuildHeld(state.data));
  const { theme, setTheme, options } = useThemes();
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
          <ThemePicker value={theme} options={options} onChange={setTheme} />
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
          [
            ...(keepsWill
              ? [
                  {
                    key: 'will',
                    label: '数字遗嘱',
                    icon: ScrollText,
                    onSelect: () => openWill(),
                  },
                ]
              : []),
            {
              key: 'settings',
              label: '设置',
              icon: Settings2,
              alert: !identity.admin
                ? undefined
                : down
                  ? `${down} 项服务异常`
                  : held
                    ? '记忆自动整理已暂停'
                    : undefined,
              onSelect: () => openSettings(),
            },
          ],
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
