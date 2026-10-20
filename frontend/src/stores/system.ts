import { create } from 'zustand';
import { api } from '../lib/api';

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
  action: 'model' | 'key' | string;
  section?: string;
  address?: [string, string];
  model?: [string | null, string | null];
  env?: string;
  set?: boolean;
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
}>((set) => ({
  data: null,
  error: '',
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
