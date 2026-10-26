import { create } from 'zustand';
import { api } from '../lib/api';
import type { KernelStatus, KernelVersion } from './status';

const pad = (n: number) => String(n).padStart(2, '0');
/** "10-17 09:12" for a Unix time in seconds, in the viewer's time zone. */
export function clock(seconds: number) {
  const d = new Date(seconds * 1000);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export interface ServiceCheck {
  at: number;
  ok: boolean;
  latency_ms: number | null;
  reason: string | null;
  version: string | null;
  device: string | null;
  busy: boolean | null;
  model: string | null;
  embeddings_ms: number | null;
}

/** One service on the GPU machine, as the server's monitor last saw it. */
export interface ServiceState {
  key: 'asr' | 'embed' | 'tts' | string;
  name: string;
  /** False when an administrator switched it off: it is not checked. */
  enabled: boolean;
  address: string;
  latest: ServiceCheck | null;
  /** Since when the service has been in its latest state, as far as the record reaches. */
  since: number | null;
  checks: number;
  failures: number;
  availability: number | null;
  first_at: number | null;
  last_failure: { at: number; reason: string | null } | null;
  buckets: { start: number; checks: number; failures: number }[];
}

export type SwitchName = 'tts' | 'video';

export interface SwitchState {
  configured: boolean;
  enabled: boolean;
  /** What twin.toml lacks before it can be switched on. */
  missing: string | null;
  changed_at: string | null;
  changed_by: string | null;
}

export type ModelName = 'llm' | 'chat_llm' | 'embed';

export interface EditableModel {
  name: ModelName;
  section: string;
  use: string;
  base_url: string | null;
  model: string | null;
  locked: string | null;
  /** Changed here rather than taken from twin.toml. */
  custom: boolean;
  changed_at: string | null;
  changed_by: string | null;
}

export interface AuditEntry {
  at: string;
  by: string | null;
  action: 'model' | 'key' | 'param' | 'kernel' | 'ledger' | string;
  section?: string;
  address?: [string, string];
  model?: [string | null, string | null];
  env?: string;
  set?: boolean;
  param?: string;
  value?: [boolean | number, boolean | number];
  personas?: string[];
  name?: [string | null, string | null];
}

/** A twin.toml value an administrator may change here, effective at once. */
export interface ParamState {
  key: string;
  label: string;
  help: string;
  unit: string;
  value: boolean | number;
  /** twin.toml's value, which an empty change goes back to. */
  default: boolean | number;
  custom: boolean;
  changed_at: string | null;
  changed_by: string | null;
}

/** The parts a release may raise the version of, and where each twin stands. */
export interface Components {
  kernel: {
    version: KernelVersion;
    twins: ({ id: string; name: string } & KernelStatus)[];
  };
  ledger: {
    version: string;
    /** False when an administrator switched 承诺账本 off: nothing is listed. */
    enabled: boolean;
    twins: {
      id: string;
      name: string;
      meetings: number;
      /** Meetings the running reader has not read. */
      pending: number;
      running: boolean;
    }[];
  };
  library: { attribution: string; cleanup: string };
}

/** Twins whose kernel or ledger an administrator may upgrade now. */
export function upgradable(components: Components | null) {
  if (!components) return 0;
  const kernels = components.kernel.twins.filter(
    (twin) =>
      twin.scope !== 'none' && !['queued', 'running'].includes(twin.state),
  ).length;
  const ledgers = components.ledger.twins.filter(
    (twin) => twin.pending > 0 && !twin.running,
  ).length;
  return kernels + ledgers;
}

export interface FeatureState {
  label: string;
  enabled: boolean;
  changed_at: string | null;
  changed_by: string | null;
}

export interface SystemState {
  now: number;
  interval: number;
  window: number;
  services: ServiceState[];
  switches: Record<SwitchName, SwitchState>;
  /** 工作 and 承诺账本, which an administrator may switch off for everyone. */
  features?: Record<'work' | 'ledger', FeatureState>;
  /** The team's name, once set. */
  team_name?: string | null;
  /** Label/value rows of twin.toml per service: hosts and models only. */
  config: Record<'embed' | 'asr' | 'tts' | 'video', [string, string][]>;
  models: {
    use: string;
    section: string;
    provider: string;
    model: string;
    address: string;
    external: boolean;
  }[];
  /** The models an administrator may point elsewhere; ``locked`` says why not when they cannot. */
  editable_models?: EditableModel[];
  /** Key variables and whether each is set; never their values. */
  keys: { env: string; use: string; set: boolean }[];
  /** The env file the keys are written to, by name. */
  env_file?: string;
  /** The latest changes made here, newest first; never a key's value. */
  audit?: AuditEntry[];
  /** Common parameters; absent from an older server. */
  params?: ParamState[];
  quota: {
    /** 0: no limit. */
    limit: number;
    hours: number;
    used: number;
    exhausted: boolean;
    resets_at: string | null;
    /** Changed here rather than taken from twin.toml. */
    custom: boolean;
    default_limit: number;
    default_hours: number;
  };
  /** Model tokens of the last day by use, most first; absent from an older server. */
  usage?: UsageRow[];
}

export interface UsageRow {
  stage: string;
  calls: number;
  failures: number;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  /** Calls whose provider did not report usage: the totals are a floor. */
  unknown_calls: number;
}

/** Switched-on services whose latest check failed: what the red dot on the 系统 entry counts. */
export const failing = (state: SystemState | null) =>
  state?.services.filter((s) => s.enabled && s.latest && !s.latest.ok) ?? [];

export const useSystem = create<{
  data: SystemState | null;
  error: string;
  load: (refresh?: boolean) => Promise<void>;
  put: (url: string, json: unknown) => Promise<void>;
  /** Fetched when the dialog opens, not polled: it opens every twin's memories. */
  components: Components | null;
  componentsError: string;
  loadComponents: () => Promise<void>;
  /** Starts the upgrade of one part for the given twins, or all that need it; errors go to the caller. */
  upgrade: (part: 'kernel' | 'ledger', personaIds?: string[]) => Promise<void>;
}>((set) => ({
  data: null,
  error: '',
  components: null,
  componentsError: '',
  loadComponents: async () => {
    try {
      const components = await api<Components>('/api/admin/system/components');
      if (!components?.kernel || !components.ledger)
        throw new Error('服务器版本不支持在这里升级记忆');
      set({ components, componentsError: '' });
    } catch (failure) {
      set({
        componentsError:
          failure instanceof Error ? failure.message : '无法获取部件版本',
      });
    }
  },
  upgrade: async (part, personaIds) => {
    const components = await api<Components>(
      `/api/admin/system/components/${part}`,
      {
        method: 'POST',
        json: personaIds ? { persona_ids: personaIds } : {},
      },
    );
    set({ components, componentsError: '' });
  },
  load: async (refresh = false) => {
    try {
      const data = await api<SystemState>(
        `/api/admin/system${refresh ? '?refresh=true' : ''}`,
      );
      // An older server answers something else here; show nothing rather than break the page.
      if (!Array.isArray(data?.services) || !data.switches || !data.quota)
        throw new Error('服务器版本不支持系统设置');
      set({ data, error: '' });
    } catch (failure) {
      set({
        error: failure instanceof Error ? failure.message : '无法获取系统状态',
      });
    }
  },
  // Errors go to the caller, which shows them beside the control that failed.
  put: async (url, json) =>
    set({ data: await api<SystemState>(url, { method: 'PUT', json }) }),
}));

const POLL_MS = 60_000;

/** For administrators: keep the system state fresh, so the entry can show when a service fails. */
export function startSystemPolling() {
  const load = () => {
    if (!document.hidden) void useSystem.getState().load();
  };
  load();
  const timer = setInterval(load, POLL_MS);
  document.addEventListener('visibilitychange', load);
  return () => {
    clearInterval(timer);
    document.removeEventListener('visibilitychange', load);
  };
}
