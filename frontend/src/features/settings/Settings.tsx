import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import {
  Activity,
  Brain,
  HardDrive,
  KeyRound,
  LayoutGrid,
  Palette,
  Plug,
  RefreshCw,
  Share2,
  Tag,
  UserRound,
  Users,
} from 'lucide-react';
import {
  Button,
  KeyValue,
  Row,
  Section,
  SettingsDialog,
  Stack,
  Text,
  ThemePicker,
  type SettingsSection,
} from '../../components/ui';
import { accountLabel, personaEdition, useAuth } from '../../stores/auth';
import { usePersonas } from '../../stores/personas';
import {
  failing,
  upgradable,
  useSystem,
  type Components,
  type SystemState,
} from '../../stores/system';
import { useTeam } from '../../stores/team';
import { useThemes } from '../../stores/theme';
import type { LibraryState } from '../../pages/Library';
import { AliasList } from '../identity/AliasList';
import { Channels } from '../profile/Channels';
import { ExternalServices } from '../profile/ExternalServices';
import { LibraryCapacity, libraryStatus } from '../admin/LibraryCapacity';
import {
  SERVICES,
  SystemPane,
  type ServiceKey,
  type SystemSection,
} from '../admin/SystemPanes';
import { LibraryRules, MemoryPane } from '../admin/Upgrades';

/** The search parameter that holds the open section: the dialog sits over any page and closing it returns there. */
export const SETTINGS_PARAM = 'settings';
/** Where the administrators' settings used to open (?system=…): such a link opens the same place here. */
const OLD_PARAM = 'system';
const MOVED: Record<string, SectionKey> = {
  monitor: 'status',
  tokens: 'models',
  params: 'library',
  upgrades: 'memory',
};

type SectionKey =
  | 'look'
  | 'account'
  | 'channels'
  | 'aliases'
  | 'egress'
  | 'library'
  | 'memory'
  | SystemSection;

type Section = Omit<SettingsSection, 'status'> & { key: SectionKey };

const TEAM_SECTIONS = new Set<SectionKey>([
  'channels',
  'team',
  'features',
  'library',
]);

/** Opens the settings at a section, over the current page. */
export function useOpenSettings() {
  const [, setParams] = useSearchParams();
  return useCallback(
    (section?: SectionKey) =>
      setParams((params) => {
        params.set(SETTINGS_PARAM, section ?? '');
        return params;
      }),
    [setParams],
  );
}

/** The automatic memory rebuild is switched off: a reminder to switch it on again. */
export const rebuildHeld = (state: SystemState | null) =>
  state?.params?.find((p) => p.key === 'library.auto_build')?.value === false;

function sectionStatus(
  key: SectionKey,
  state: SystemState | null,
  components: Components | null,
  library: LibraryState | null,
): SettingsSection['status'] {
  if (key === 'memory') {
    const count = upgradable(components);
    return count ? { label: `${count} 项可升级` } : undefined;
  }
  if (key === 'library')
    return (
      libraryStatus(library) ??
      (rebuildHeld(state) ? { label: '整理已暂停' } : undefined)
    );
  if (!state) return undefined;
  if (key === 'status') {
    const count = failing(state).length;
    return count ? { label: `${count} 项异常`, tone: 'danger' } : undefined;
  }
  if (key === 'features') {
    const off = Object.values(state.features ?? {}).filter(
      (feature) => !feature.enabled,
    ).length;
    return off ? { label: `关闭 ${off} 项` } : undefined;
  }
  if (key === 'models' && state.quota.exhausted)
    return { label: '已用完', tone: 'danger' };
  return undefined;
}

function Look() {
  const { theme, setTheme, options } = useThemes();
  return (
    <Section level={4} title="配色" description="只在这台设备上生效。">
      <ThemePicker value={theme} options={options} onChange={setTheme} named />
    </Section>
  );
}

function Account() {
  const identity = useAuth((state) => state.identity);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!identity) return null;
  return (
    <Stack gap={4}>
      <KeyValue
        items={[
          ['账号', accountLabel(identity) || '本机'],
          ['身份', identity.admin ? '管理员' : '成员'],
        ]}
      />
      {identity.auth_enabled && (
        <Row gap={2}>
          <Button
            variant="danger"
            loading={busy}
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
        </Row>
      )}
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
    </Stack>
  );
}

/** Every setting in one dialog over the current page, grouped by what it is about: the person's own, the twin in
 * view (for whoever looks after it), the team's and the system's (for an administrator). Which section is open lives
 * in the URL (?settings=…), so closing it leaves the page as it was. */
export function Settings() {
  const [params, setParams] = useSearchParams();
  const identity = useAuth((state) => state.identity);
  const twin = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  const admin = !!identity?.admin;
  const ownsTwin = !!twin && twin.can_manage !== false;
  const persona = personaEdition(identity);
  const listed: Section[] = [
    { key: 'look', label: '外观', group: '我', icon: Palette },
    { key: 'account', label: '账号', icon: UserRound },
    ...(ownsTwin
      ? ([
          {
            key: 'channels',
            label: '接入',
            group: `分身 · ${twin?.name ?? ''}`,
            icon: Plug,
          },
          { key: 'aliases', label: '别名', icon: Tag },
          { key: 'egress', label: '数据去向', icon: Share2 },
        ] satisfies Section[])
      : []),
    ...(admin
      ? ([
          { key: 'team', label: '团队', group: '团队', icon: Users },
          { key: 'features', label: '功能', icon: LayoutGrid },
          { key: 'models', label: '模型与额度', icon: KeyRound },
          { key: 'status', label: '状态', group: '系统', icon: Activity },
          ...SERVICES.map(({ key, label }) => ({
            key,
            label,
            under: 'status',
          })),
          { key: 'library', label: '录音库', icon: HardDrive },
          { key: 'memory', label: '记忆', icon: Brain },
        ] satisfies Section[])
      : []),
  ];
  // The persona edition has no WeCom, team name, team-wide switches or recording library: the twin's group keeps its
  // heading on its next section, and the models, left without the team's, head a group of their own.
  const sections: Section[] = [];
  let heading: string | undefined;
  for (const section of listed) {
    if (persona && TEAM_SECTIONS.has(section.key)) {
      heading ??= section.group;
      continue;
    }
    const group =
      persona && section.key === 'models' ? '模型' : (section.group ?? heading);
    sections.push(group ? { ...section, group } : section);
    heading = undefined;
  }
  const requested = params.get(SETTINGS_PARAM);
  const open = requested !== null;
  // Without a section the dialog opens where its owner most often goes.
  const fallback: SectionKey = admin
    ? 'status'
    : ownsTwin
      ? persona
        ? 'aliases'
        : 'channels'
      : 'look';
  const active =
    sections.find((section) => section.key === requested)?.key ?? fallback;
  const old = params.get(OLD_PARAM);
  useEffect(() => {
    if (old === null) return;
    setParams(
      (current) => {
        current.delete(OLD_PARAM);
        current.set(SETTINGS_PARAM, MOVED[old] ?? old);
        return current;
      },
      { replace: true },
    );
  }, [old, setParams]);
  const { data, error, load, components, loadComponents } = useSystem();
  const library = useTeam((state) => state.library);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    if (open && admin) void load();
  }, [open, admin, load]);
  // Each time the dialog opens or the memory is chosen, so the menu can say what is waiting to be upgraded.
  const upgrades = open && active === 'memory';
  useEffect(() => {
    if (open && admin) void loadComponents();
  }, [open, admin, upgrades, loadComponents]);
  const select = (key: string) =>
    setParams(
      (current) => {
        current.set(SETTINGS_PARAM, key);
        return current;
      },
      { replace: true },
    );
  // Opening adds a history entry; closing replaces it, so Back after closing does not reopen the dialog.
  const close = () =>
    setParams(
      (current) => {
        current.delete(SETTINGS_PARAM);
        return current;
      },
      { replace: true },
    );
  const monitored = ['status', 'gpu', 'embed', 'asr', 'tts'].includes(active);
  const system = !['look', 'account', 'channels', 'aliases', 'egress'].includes(
    active,
  );
  return (
    <SettingsDialog
      open={open}
      onOpenChange={(next) => !next && close()}
      title="设置"
      sections={sections.map((section) => ({
        ...section,
        status: sectionStatus(section.key, data, components, library),
      }))}
      active={active}
      onSelect={select}
      actions={
        monitored && (
          <Button
            variant="secondary"
            size="sm"
            loading={checking}
            onClick={() => {
              setChecking(true);
              void load(true).finally(() => setChecking(false));
            }}
          >
            {!checking && <RefreshCw aria-hidden className="size-4" />}
            立即检查
          </Button>
        )
      }
    >
      {active === 'look' ? (
        <Look />
      ) : active === 'account' ? (
        <Account />
      ) : active === 'channels' ? (
        <Channels />
      ) : active === 'aliases' ? (
        <AliasList />
      ) : active === 'egress' ? (
        <ExternalServices />
      ) : active === 'library' ? (
        <Stack gap={6}>
          <LibraryCapacity />
          {data && <LibraryRules state={data} />}
        </Stack>
      ) : (
        <>
          {system && error && (
            <Text role="alert" size="sm" tone="danger">
              {error}
            </Text>
          )}
          {data &&
            (active === 'memory' ? (
              <MemoryPane state={data} />
            ) : (
              <SystemPane
                section={active}
                state={data}
                onSelect={(key: ServiceKey) => select(key)}
              />
            ))}
        </>
      )}
    </SettingsDialog>
  );
}
