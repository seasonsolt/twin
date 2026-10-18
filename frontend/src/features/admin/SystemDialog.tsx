import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router';
import {
  Activity,
  AudioLines,
  Cpu,
  KeyRound,
  RefreshCw,
  Video,
  Volume2,
  Waypoints,
} from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  HistoryBar,
  Input,
  KeyValue,
  Meter,
  Notice,
  Row,
  Section,
  Select,
  SettingsDialog,
  Stack,
  Switch,
  Table,
  Text,
  type SettingsSection,
} from '../../components/ui';
import {
  failing,
  useSystem,
  type AuditEntry,
  type EditableModel,
  type ServiceCheck,
  type ServiceState,
  type SwitchName,
  type SystemState,
} from '../../stores/system';

/** The search parameter that holds the open section: the dialog sits over any page and closing it returns there. */
export const SYSTEM_PARAM = 'system';

type SectionKey =
  'monitor' | 'gpu' | 'embed' | 'asr' | 'tts' | 'video' | 'tokens';

const SECTIONS: (Omit<SettingsSection, 'status'> & { key: SectionKey })[] = [
  { key: 'monitor', label: '监控', icon: Activity },
  { key: 'gpu', label: 'GPU 服务', group: '服务', icon: Cpu },
  { key: 'embed', label: '向量服务', icon: Waypoints },
  { key: 'asr', label: 'ASR 转写', icon: AudioLines },
  { key: 'tts', label: 'TTS 朗读', icon: Volume2 },
  { key: 'video', label: '视频服务', icon: Video },
  { key: 'tokens', label: '模型与 Token', group: '设置', icon: KeyRound },
];

/** Opens the system dialog at a section, over the current page. */
export function useOpenSystem() {
  const [, setParams] = useSearchParams();
  return useCallback(
    (section: SectionKey = 'monitor') =>
      setParams((params) => {
        params.set(SYSTEM_PARAM, section);
        return params;
      }),
    [setParams],
  );
}

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

function details(check: ServiceCheck) {
  return [
    check.version && `版本 ${check.version}`,
    check.device,
    check.model,
    check.busy === true ? '正在处理任务' : check.busy === false ? '空闲' : null,
    check.latency_ms !== null && `响应 ${check.latency_ms} ms`,
    check.embeddings_ms !== null && `向量 ${check.embeddings_ms} ms`,
  ].filter(Boolean);
}

const tokens = (n: number) =>
  n >= 10_000 ? `${(n / 10_000).toFixed(n % 10_000 ? 1 : 0)} 万` : String(n);

function sectionStatus(
  key: SectionKey,
  state: SystemState | null,
): SettingsSection['status'] {
  if (!state) return undefined;
  if (key === 'monitor') {
    const count = failing(state).length;
    return count ? { label: `${count} 项异常`, tone: 'danger' } : undefined;
  }
  if (key === 'tokens')
    return state.quota.exhausted
      ? { label: '已用完', tone: 'danger' }
      : undefined;
  if (key === 'tts' || key === 'video') {
    const sw = state.switches[key];
    if (!sw.configured) return { label: '未配置' };
    if (!sw.enabled) return { label: '已关闭' };
  }
  const service = state.services.find((s) => s.key === key);
  if (key === 'gpu' && failing(state).length)
    return { label: '异常', tone: 'danger' };
  if (service?.enabled && service.latest && !service.latest.ok)
    return { label: '异常', tone: 'danger' };
  return undefined;
}

function historyTone(bucket: { checks: number; failures: number }) {
  if (bucket.checks === 0) return 'none' as const;
  if (bucket.failures === 0) return 'success' as const;
  return bucket.failures === bucket.checks
    ? ('danger' as const)
    : ('warning' as const);
}

function ServiceHistory({ service }: { service: ServiceState }) {
  return (
    <HistoryBar
      label={`${service.name}每小时检查结果`}
      slots={service.buckets.map((bucket) => ({
        key: bucket.start,
        title: `${clock(bucket.start)} 起：${bucket.checks} 次检查，${bucket.failures} 次失败`,
        tone: historyTone(bucket),
      }))}
    />
  );
}

function StateText({ service }: { service: ServiceState }) {
  const { latest } = service;
  if (!service.enabled)
    return (
      <Text as="span" size="sm" tone="tertiary">
        已关闭，不检查
      </Text>
    );
  if (!latest)
    return (
      <Text as="span" size="sm" tone="tertiary">
        尚未检查
      </Text>
    );
  return latest.ok ? (
    <Text as="span" size="sm" tone="success">
      正常
    </Text>
  ) : (
    <Text as="span" size="sm" tone="danger">
      异常
    </Text>
  );
}

/** The monitor's full record of one service: state now, the last day, and the last failure. */
function ServiceRecord({
  service,
  now,
}: {
  service: ServiceState;
  now: number;
}) {
  const { latest } = service;
  const covered = service.first_at === null ? 0 : now - service.first_at;
  return (
    <Stack gap={2}>
      <Row gap={2} wrap>
        <StateText service={service} />
        <Text as="span" size="sm" tone="secondary">
          {service.address}
        </Text>
      </Row>
      {service.enabled && latest && !latest.ok && (
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
          最近 {span(covered)}可用率 {percent(service.availability)}（
          {service.checks} 次检查，{service.failures} 次失败）
        </Text>
      )}
      {service.last_failure && (
        <Text size="sm" tone="secondary">
          最近一次失败 {clock(service.last_failure.at)}：
          {service.last_failure.reason ?? '无法访问服务'}
        </Text>
      )}
      <ServiceHistory service={service} />
    </Stack>
  );
}

function QuotaMeter({ quota }: { quota: SystemState['quota'] }) {
  if (!quota.limit)
    return (
      <Text size="sm" tone="secondary">
        你最近 {quota.hours} 小时用了 {tokens(quota.used)} token，不设上限。
      </Text>
    );
  return (
    <Stack gap={1}>
      <Meter
        label={`你最近 ${quota.hours} 小时的 token 用量`}
        value={Math.min(quota.used, quota.limit)}
        max={quota.limit}
      />
      <Text size="xs" tone={quota.exhausted ? 'danger' : 'tertiary'}>
        {tokens(quota.used)} / {tokens(quota.limit)}
        {quota.exhausted &&
          quota.resets_at &&
          ` · ${clock(Date.parse(quota.resets_at) / 1000)} 起恢复`}
      </Text>
    </Stack>
  );
}

function Monitor({
  state,
  onSelect,
}: {
  state: SystemState;
  onSelect: (key: SectionKey) => void;
}) {
  const down = failing(state);
  return (
    <Stack gap={6}>
      {down.length > 0 && (
        <Notice tone="danger" role="alert" title={`${down.length} 项服务异常`}>
          {down.map((service) => (
            <p key={service.key}>
              {service.name}：{service.latest?.reason ?? '无法访问服务'}
            </p>
          ))}
        </Notice>
      )}
      <Section
        level={4}
        title="GPU 机器上的服务"
        description={`服务器每 ${Math.round(state.interval / 60)} 分钟检查一次，保留最近 ${span(state.window)}。`}
      >
        {state.services.length === 0 ? (
          <Text size="sm" tone="secondary">
            twin.toml 里没有配置经隧道访问的服务。
          </Text>
        ) : (
          <Stack as="ul" gap={2}>
            {state.services.map((service) => (
              <li key={service.key}>
                <Card
                  interactive
                  variant="outline"
                  padding="md"
                  className="w-full space-y-2"
                  onClick={() => onSelect(service.key as SectionKey)}
                >
                  <Row gap={2} justify="between">
                    <Text as="span" weight="medium">
                      {service.name}
                    </Text>
                    <StateText service={service} />
                  </Row>
                  <ServiceHistory service={service} />
                </Card>
              </li>
            ))}
          </Stack>
        )}
      </Section>
      <Section level={4} title="Token 额度">
        <QuotaMeter quota={state.quota} />
      </Section>
    </Stack>
  );
}

function Gpu({
  state,
  onSelect,
}: {
  state: SystemState;
  onSelect: (key: SectionKey) => void;
}) {
  if (state.services.length === 0)
    return (
      <EmptyState
        title="没有配置 GPU 服务"
        body="在 twin.toml 里配置经隧道访问的转写、向量或朗读服务后重启，这里会显示 GPU 机器的状态。"
      />
    );
  const seen = state.services.map((s) => s.latest).filter(Boolean);
  const devices = [...new Set(seen.map((c) => c?.device).filter(Boolean))];
  const hosts = [...new Set(state.services.map((s) => s.address))];
  const down = failing(state);
  return (
    <Stack gap={6}>
      <KeyValue
        items={[
          ['状态', down.length ? `${down.length} 项服务异常` : '服务正常'],
          ['显卡', devices.length ? devices.join('、') : '服务未报告'],
          ['地址', hosts.join('、')],
        ]}
      />
      <Section level={4} title="承载的服务">
        <Table
          caption="GPU 机器上的服务"
          headers={['服务', '状态', '版本', '响应']}
          rows={state.services.map((service) => [
            <Button
              key="name"
              variant="ghost"
              size="sm"
              onClick={() => onSelect(service.key as SectionKey)}
            >
              {service.name}
            </Button>,
            <StateText key="state" service={service} />,
            service.latest?.version ?? '—',
            service.latest?.latency_ms != null
              ? `${service.latest.latency_ms} ms`
              : '—',
          ])}
        />
      </Section>
    </Stack>
  );
}

function SwitchRow({
  name,
  label,
  state,
}: {
  name: SwitchName;
  label: string;
  state: SystemState;
}) {
  const sw = state.switches[name];
  const put = useSystem((s) => s.put);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!sw.configured)
    return (
      <Notice title={`${sw.missing ?? '还没有配置'}`}>
        写好配置后重启一次，再回到这里开启。方法见 docs/MEDIA.md。
      </Notice>
    );
  return (
    <Stack gap={2}>
      <Switch
        label={label}
        checked={sw.enabled}
        disabled={busy}
        onCheckedChange={(enabled) => {
          setBusy(true);
          setError('');
          put(`/api/admin/system/switches/${name}`, { enabled })
            .catch((failure: unknown) =>
              setError(failure instanceof Error ? failure.message : '切换失败'),
            )
            .finally(() => setBusy(false));
        }}
      />
      <Text size="xs" tone="tertiary">
        立即生效，所有分身一起。
        {sw.changed_at &&
          ` ${sw.changed_by ?? '本机'} 于 ${clock(Date.parse(sw.changed_at) / 1000)} ${sw.enabled ? '开启' : '关闭'}`}
      </Text>
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
    </Stack>
  );
}

function ConfigRows({ rows }: { rows: [string, string][] }) {
  return (
    <Section
      level={4}
      title="twin.toml 配置"
      description="改配置文件后重启生效；密钥在 .env 里，这里不显示。"
    >
      <KeyValue items={rows} />
    </Section>
  );
}

const failureText = (failure: unknown, fallback: string) =>
  failure instanceof Error ? failure.message : fallback;

function changedNote(model: EditableModel) {
  return model.custom && model.changed_at
    ? `${model.changed_by ?? '本机'} 于 ${clock(Date.parse(model.changed_at) / 1000)} 修改，代替 twin.toml 的设置。`
    : '';
}

/** Points a model at another address or model name, used from the next request on. Hidden behind one button: the
 * page is for reading the state, and changing it is the rare task. */
function ModelEdit({ model, note }: { model: EditableModel; note?: string }) {
  const put = useSystem((s) => s.put);
  const [open, setOpen] = useState(false);
  const [baseUrl, setBaseUrl] = useState(model.base_url ?? '');
  const [name, setName] = useState(model.model ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    setBaseUrl(model.base_url ?? '');
    setName(model.model ?? '');
  }, [model.base_url, model.model]);
  if (model.locked)
    return (
      <Text size="xs" tone="tertiary">
        {model.locked}
      </Text>
    );
  const save = (json: object) => {
    setBusy(true);
    setError('');
    put(`/api/admin/system/models/${model.name}`, json)
      .then(() => setOpen(false))
      .catch((failure: unknown) => setError(failureText(failure, '保存失败')))
      .finally(() => setBusy(false));
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save({ base_url: baseUrl.trim() || null, model: name.trim() || null });
  };
  const id = `system-model-${model.name}`;
  return (
    <Stack gap={2}>
      {changedNote(model) && (
        <Text size="xs" tone="tertiary">
          {changedNote(model)}
        </Text>
      )}
      {open ? (
        <form onSubmit={submit} aria-label={`修改 ${model.section}`}>
          <Stack gap={4}>
            <Field
              id={`${id}-url`}
              label="地址"
              help="OpenAI 兼容地址，通常以 /v1 结尾；不要把密钥写进地址"
            >
              <Input
                id={`${id}-url`}
                inputMode="url"
                spellCheck={false}
                autoComplete="off"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
              />
            </Field>
            <Field id={`${id}-name`} label="模型名">
              <Input
                id={`${id}-name`}
                spellCheck={false}
                autoComplete="off"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            {note && (
              <Notice tone="warning" title="换模型之后">
                {note}
              </Notice>
            )}
            <Row gap={2} wrap>
              <Button type="submit" loading={busy}>
                保存并立即生效
              </Button>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setOpen(false);
                  setError('');
                  setBaseUrl(model.base_url ?? '');
                  setName(model.model ?? '');
                }}
              >
                取消
              </Button>
              {model.custom && (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => save({})}
                >
                  恢复 twin.toml 的设置
                </Button>
              )}
            </Row>
          </Stack>
        </form>
      ) : (
        <Row gap={2} wrap>
          <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
            修改地址和模型
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

const EMBED_NOTE =
  '已有的检索向量会按新模型重新生成，完成前检索只按字面匹配；生成在后台进行，不影响聊天。';

function ServicePane({
  name,
  state,
}: {
  name: 'embed' | 'asr' | 'tts';
  state: SystemState;
}) {
  const service = state.services.find((s) => s.key === name);
  const embedModel = state.editable_models?.find((m) => m.name === 'embed');
  return (
    <Stack gap={6}>
      {name === 'tts' && (
        <SwitchRow name="tts" label="启用朗读" state={state} />
      )}
      <Section level={4} title="运行状态">
        {service ? (
          <ServiceRecord service={service} now={state.now} />
        ) : (
          <Text size="sm" tone="secondary">
            {name === 'tts' && !state.switches.tts.configured
              ? '没有配置朗读服务。'
              : '这个服务不经隧道访问，不做定时检查。'}
          </Text>
        )}
      </Section>
      <ConfigRows rows={state.config[name]} />
      {name === 'embed' && embedModel && (
        <ModelEdit model={embedModel} note={EMBED_NOTE} />
      )}
    </Stack>
  );
}

function VideoPane({ state }: { state: SystemState }) {
  return (
    <Stack gap={6}>
      <SwitchRow name="video" label="启用口型视频" state={state} />
      <ConfigRows rows={state.config.video} />
    </Stack>
  );
}

const HOURS = [1, 6, 12, 24, 72, 168];

function QuotaForm({ quota }: { quota: SystemState['quota'] }) {
  const put = useSystem((s) => s.put);
  const [limit, setLimit] = useState(String(quota.limit));
  const [hours, setHours] = useState(String(quota.hours));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    setLimit(String(quota.limit));
    setHours(String(quota.hours));
  }, [quota.limit, quota.hours]);
  const save = (json: object) => {
    setBusy(true);
    setError('');
    put('/api/admin/system/quota', json)
      .catch((failure: unknown) =>
        setError(failure instanceof Error ? failure.message : '保存失败'),
      )
      .finally(() => setBusy(false));
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(limit);
    if (!Number.isInteger(value) || value < 0) {
      setError('上限请填 0 或正整数');
      return;
    }
    save({ batch_tokens: value, batch_hours: Number(hours) });
  };
  const options = HOURS.includes(quota.hours)
    ? HOURS
    : [...HOURS, quota.hours].sort((a, b) => a - b);
  return (
    <form onSubmit={submit}>
      <Stack gap={4}>
        <Row gap={4} wrap align="start">
          <Field
            id="system-quota-limit"
            label="每人 token 上限"
            help="0 表示不限"
          >
            <Input
              id="system-quota-limit"
              inputMode="numeric"
              value={limit}
              onChange={(event) => setLimit(event.target.value)}
            />
          </Field>
          <Field id="system-quota-hours" label="统计时长">
            <Select
              id="system-quota-hours"
              value={hours}
              onChange={(event) => setHours(event.target.value)}
            >
              {options.map((h) => (
                <option key={h} value={h}>
                  {h < 24 ? `${h} 小时` : `${h / 24} 天`}
                </option>
              ))}
            </Select>
          </Field>
        </Row>
        <Row gap={2} wrap>
          <Button type="submit" loading={busy}>
            保存
          </Button>
          {quota.custom && (
            <Button variant="ghost" disabled={busy} onClick={() => save({})}>
              恢复 twin.toml 的设置（{tokens(quota.default_limit)} /{' '}
              {quota.default_hours} 小时）
            </Button>
          )}
        </Row>
        {error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
      </Stack>
    </form>
  );
}

/** Replaces or removes one key. The field starts empty and the value is never shown again, here or anywhere. */
function KeyForm({
  env,
  isSet,
  file,
  onDone,
}: {
  env: string;
  isSet: boolean;
  file: string;
  onDone: () => void;
}) {
  const put = useSystem((s) => s.put);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = (json: object) => {
    setBusy(true);
    setError('');
    put(`/api/admin/system/keys/${env}`, json)
      .then(() => {
        setValue('');
        onDone();
      })
      .catch((failure: unknown) => setError(failureText(failure, '保存失败')))
      .finally(() => setBusy(false));
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (value.trim()) save({ value: value.trim() });
  };
  const id = `system-key-${env}`;
  return (
    <Card variant="outline" padding="md">
      <form onSubmit={submit} aria-label={`设置 ${env}`}>
        <Stack gap={4}>
          <Field
            id={id}
            label={isSet ? `新的 ${env}` : env}
            help={`保存后立即生效，写入服务器的 ${file}；之后这里也只显示“已设置”。`}
            error={error || undefined}
          >
            <Input
              id={id}
              type="password"
              autoComplete="new-password"
              spellCheck={false}
              autoFocus
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          </Field>
          <Row gap={2} wrap>
            <Button type="submit" loading={busy} disabled={!value.trim()}>
              保存
            </Button>
            <Button variant="ghost" disabled={busy} onClick={onDone}>
              取消
            </Button>
            {isSet && (
              <Button variant="danger" disabled={busy} onClick={() => save({})}>
                移除这个密钥
              </Button>
            )}
          </Row>
        </Stack>
      </form>
    </Card>
  );
}

function auditText(entry: AuditEntry) {
  if (entry.action === 'key')
    return `${entry.set ? '设置' : '移除'}了 ${entry.env ?? '密钥'}`;
  if (entry.action === 'model' && entry.model && entry.address)
    return `把 ${entry.section ?? '模型'} 改为 ${entry.address[1]} · ${entry.model[1] ?? '—'}`;
  return '修改了系统设置';
}

function Tokens({ state }: { state: SystemState }) {
  const [editing, setEditing] = useState<string | null>(null);
  const editable = (section: string) =>
    state.editable_models?.find((m) => m.section === section);
  const file = state.env_file ?? '.env';
  const editingKey = state.keys.find((key) => key.env === editing);
  return (
    <Stack gap={6}>
      <Section
        level={4}
        title="Token 额度"
        description="录音库校对和重新整理按这个上限排队，改完立即生效。"
      >
        <QuotaMeter quota={state.quota} />
        <QuotaForm quota={state.quota} />
      </Section>
      <Section
        level={4}
        title="文字模型"
        description="改地址或模型名立即生效，所有分身一起；接口类型和其他参数在 twin.toml 里改。"
      >
        <Stack as="ul" gap={2}>
          {state.models.map((model) => {
            const edit = editable(model.section);
            return (
              <Card as="li" key={model.section} variant="outline" padding="md">
                <Stack gap={3}>
                  <KeyValue
                    items={[
                      ['用途', model.use],
                      ['配置', model.section],
                      ['接口', model.provider],
                      ['模型', model.model],
                      [
                        '地址',
                        <Row key="address" gap={2} wrap>
                          {model.address}
                          {model.external && <Badge tone="warning">外部</Badge>}
                        </Row>,
                      ],
                    ]}
                  />
                  {edit && <ModelEdit model={edit} />}
                </Stack>
              </Card>
            );
          })}
        </Stack>
      </Section>
      <Section
        level={4}
        title="密钥"
        description={`密钥写在服务器的 ${file} 里，这里只显示是否已设置，从不显示内容。`}
      >
        <Table
          caption="密钥"
          headers={['环境变量', '用途', '状态', '']}
          rows={state.keys.map((key) => [
            key.env,
            key.use,
            key.set ? (
              <Badge key="set" tone="success">
                已设置
              </Badge>
            ) : (
              <Badge key="unset" tone="warning">
                未设置
              </Badge>
            ),
            <Button
              key="edit"
              variant="ghost"
              size="sm"
              aria-label={`${key.set ? '更换' : '设置'} ${key.env}`}
              onClick={() => setEditing(key.env)}
            >
              {key.set ? '更换' : '设置'}
            </Button>,
          ])}
        />
        {editingKey && (
          <KeyForm
            key={editingKey.env}
            env={editingKey.env}
            isSet={editingKey.set}
            file={file}
            onDone={() => setEditing(null)}
          />
        )}
      </Section>
      {state.audit && state.audit.length > 0 && (
        <Section level={4} title="最近修改">
          <Stack as="ul" gap={1}>
            {state.audit.slice(0, 5).map((entry, index) => (
              <Text as="li" key={index} size="xs" tone="secondary">
                {clock(Date.parse(entry.at) / 1000)} {entry.by ?? '本机'}{' '}
                {auditText(entry)}
              </Text>
            ))}
          </Stack>
        </Section>
      )}
    </Stack>
  );
}

/** For administrators: every service, the speech and video switches, and the token settings, in one dialog over the
 * current page. Which section is open lives in the URL (?system=…), so closing it leaves the page as it was. */
export function SystemDialog() {
  const [params, setParams] = useSearchParams();
  const requested = params.get(SYSTEM_PARAM);
  const open = requested !== null;
  const active: SectionKey = SECTIONS.some((s) => s.key === requested)
    ? (requested as SectionKey)
    : 'monitor';
  const { data, error, load } = useSystem();
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    if (open) void load();
  }, [open, load]);
  const select = (key: string) =>
    setParams(
      (current) => {
        current.set(SYSTEM_PARAM, key);
        return current;
      },
      { replace: true },
    );
  // Opening adds a history entry; closing replaces it, so Back after closing does not reopen the dialog.
  const close = () =>
    setParams(
      (current) => {
        current.delete(SYSTEM_PARAM);
        return current;
      },
      { replace: true },
    );
  const monitored = ['monitor', 'gpu', 'embed', 'asr', 'tts'].includes(active);
  return (
    <SettingsDialog
      open={open}
      onOpenChange={(next) => !next && close()}
      title="系统"
      note="仅管理员可见"
      sections={SECTIONS.map((section) => ({
        ...section,
        status: sectionStatus(section.key, data),
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
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
      {data &&
        (active === 'monitor' ? (
          <Monitor state={data} onSelect={select} />
        ) : active === 'gpu' ? (
          <Gpu state={data} onSelect={select} />
        ) : active === 'video' ? (
          <VideoPane state={data} />
        ) : active === 'tokens' ? (
          <Tokens state={data} />
        ) : (
          <ServicePane name={active} state={data} />
        ))}
    </SettingsDialog>
  );
}
