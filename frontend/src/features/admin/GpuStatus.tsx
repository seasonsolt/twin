import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  Heading,
  HistoryBar,
  Row,
  Stack,
  Text,
  Toolbar,
} from '../../components/ui';
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
      <Row gap={2} wrap>
        <Text as="span" weight="medium">
          {service.name}
        </Text>
        <Text as="span" size="xs" tone="secondary">
          {service.address}
        </Text>
        {!latest ? (
          <Badge>尚未检查</Badge>
        ) : latest.ok ? (
          <Badge tone="success">正常</Badge>
        ) : (
          <Badge tone="danger">异常</Badge>
        )}
      </Row>
      {latest && !latest.ok && (
        <Text role="alert" size="sm" tone="danger">
          {latest.reason ?? '无法访问服务'}
          {service.since !== null &&
            service.since < latest.at &&
            `（自 ${clock(service.since)} 起）`}
        </Text>
      )}
      {latest && details(latest).length > 0 && (
        <Text size="sm" tone="secondary">
          {details(latest).join(' · ')}
        </Text>
      )}
      {service.availability !== null && (
        <Text size="sm">
          最近 {span(covered)}可用率{' '}
          <Text
            as="span"
            size="inherit"
            tone={
              service.availability >= 0.99
                ? 'success'
                : service.availability >= 0.9
                  ? 'warning'
                  : 'danger'
            }
          >
            {percent(service.availability)}
          </Text>
          （{service.checks} 次检查，{service.failures} 次失败）
          {!service.last_failure && ' · 期间没有失败'}
        </Text>
      )}
      {service.last_failure && (
        <Text size="sm" tone="secondary">
          最近一次失败 {clock(service.last_failure.at)}：
          {service.last_failure.reason ?? '无法访问服务'}
        </Text>
      )}
      <HistoryBar
        label={`${service.name}每小时检查结果`}
        slots={service.buckets.map((bucket) => ({
          key: bucket.start,
          title: `${clock(bucket.start)} 起：${bucket.checks} 次检查，${bucket.failures} 次失败`,
          tone:
            bucket.checks === 0
              ? 'none'
              : bucket.failures === 0
                ? 'success'
                : bucket.failures === bucket.checks
                  ? 'danger'
                  : 'warning',
        }))}
      />
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
      <Toolbar gap={2} as="header">
        <div>
          <Heading level={2} size="item">
            GPU 服务
          </Heading>
          <Text size="xs" tone="secondary">
            仅管理员可见 · 服务器每 {Math.round((state?.interval ?? 60) / 60)}{' '}
            分钟检查一次
            {latest ? ` · 上次检查 ${clock(latest)}` : ''}
          </Text>
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
      </Toolbar>
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
      {state && (
        <Stack as="ul" gap={3}>
          {state.services.map((service) => (
            <Service key={service.key} service={service} now={state.now} />
          ))}
        </Stack>
      )}
    </Card>
  );
}
