import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Badge, Button, Card } from '../../components/ui';
import { api } from '../../lib/api';

export interface GpuCheck {
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

export interface GpuService {
  key: string;
  name: string;
  address: string;
  latest: GpuCheck | null;
  /** Since when the service has been in its latest state, as far as the record reaches. */
  since: number | null;
  checks: number;
  failures: number;
  availability: number | null;
  first_at: number | null;
  last_failure: { at: number; reason: string | null } | null;
  buckets: { start: number; checks: number; failures: number }[];
}

export interface GpuState {
  now: number;
  interval: number;
  window: number;
  services: GpuService[];
}

const REFRESH_MS = 60_000;

const pad = (n: number) => String(n).padStart(2, '0');
/** "10-17 09:12" for a Unix time in seconds, in the viewer's time zone. */
export function clock(seconds: number) {
  const d = new Date(seconds * 1000);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function span(seconds: number) {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} 分钟`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} 小时`;
  return `${Math.round(seconds / 86400)} 天`;
}

const percent = (value: number) =>
  `${value === 1 ? '100' : (Math.floor(value * 1000) / 10).toFixed(1)}%`;

function details(check: GpuCheck) {
  return [
    check.version && `版本 ${check.version}`,
    check.device,
    check.model,
    check.busy === true ? '正在处理任务' : check.busy === false ? '空闲' : null,
    check.latency_ms !== null && `响应 ${check.latency_ms} ms`,
    check.embeddings_ms !== null && `向量 ${check.embeddings_ms} ms`,
  ].filter(Boolean);
}

function Service({ service, now }: { service: GpuService; now: number }) {
  const { latest } = service;
  const covered = service.first_at === null ? 0 : now - service.first_at;
  return (
    <li className="space-y-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{service.name}</span>
        <span className="text-xs text-secondary">{service.address}</span>
        {!latest ? (
          <Badge>尚未检查</Badge>
        ) : latest.ok ? (
          <Badge tone="success">正常</Badge>
        ) : (
          <Badge tone="danger">异常</Badge>
        )}
      </div>
      {latest && !latest.ok && (
        <p role="alert" className="text-sm text-danger">
          {latest.reason ?? '无法访问服务'}
          {service.since !== null &&
            service.since < latest.at &&
            `（自 ${clock(service.since)} 起）`}
        </p>
      )}
      {latest && details(latest).length > 0 && (
        <p className="text-sm text-secondary">{details(latest).join(' · ')}</p>
      )}
      {service.availability !== null && (
        <p className="text-sm">
          最近 {span(covered)}可用率{' '}
          <span
            className={
              service.availability >= 0.99
                ? 'text-success'
                : service.availability >= 0.9
                  ? 'text-warning'
                  : 'text-danger'
            }
          >
            {percent(service.availability)}
          </span>
          （{service.checks} 次检查，{service.failures} 次失败）
          {!service.last_failure && ' · 期间没有失败'}
        </p>
      )}
      {service.last_failure && (
        <p className="text-sm text-secondary">
          最近一次失败 {clock(service.last_failure.at)}：
          {service.last_failure.reason ?? '无法访问服务'}
        </p>
      )}
      <div
        role="img"
        aria-label={`${service.name}每小时检查结果`}
        className="flex h-4 gap-px"
      >
        {service.buckets.map((bucket) => (
          <span
            key={bucket.start}
            title={`${clock(bucket.start)} 起：${bucket.checks} 次检查，${bucket.failures} 次失败`}
            className={`flex-1 rounded-[1px] ${
              bucket.checks === 0
                ? 'bg-border'
                : bucket.failures === 0
                  ? 'bg-success'
                  : bucket.failures === bucket.checks
                    ? 'bg-danger'
                    : 'bg-warning'
            }`}
          />
        ))}
      </div>
    </li>
  );
}

/** For administrators: whether the transcription and embedding services on the GPU machine answer now, and how
 * they did over the last day. The server checks them every minute, so this works from any network. */
export function GpuStatus() {
  const [state, setState] = useState<GpuState | null>(null);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const load = useCallback(async (refresh = false) => {
    if (refresh) setChecking(true);
    try {
      setState(
        await api<GpuState>(`/api/admin/gpu${refresh ? '?refresh=true' : ''}`),
      );
      setError('');
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : '无法获取 GPU 服务状态',
      );
    } finally {
      if (refresh) setChecking(false);
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);
  if (!error && (!state || state.services.length === 0)) return null;
  const latest = state?.services
    .map((service) => service.latest?.at ?? 0)
    .reduce((a, b) => Math.max(a, b), 0);
  return (
    <Card className="space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-semibold">GPU 服务</h2>
          <p className="text-xs text-secondary">
            仅管理员可见 · 服务器每 {Math.round((state?.interval ?? 60) / 60)}{' '}
            分钟检查一次
            {latest ? ` · 上次检查 ${clock(latest)}` : ''}
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={checking}
          onClick={() => void load(true)}
        >
          {!checking && <RefreshCw aria-hidden className="size-4" />}
          立即检查
        </Button>
      </header>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      {state && (
        <ul className="space-y-3">
          {state.services.map((service) => (
            <Service key={service.key} service={service} now={state.now} />
          ))}
        </ul>
      )}
    </Card>
  );
}
