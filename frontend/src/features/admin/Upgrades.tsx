import { useEffect, useState, type FormEvent } from 'react';
import {
  Button,
  Field,
  Input,
  KeyValue,
  Row,
  Section,
  Stack,
  Switch,
  Table,
  Text,
  useConfirm,
} from '../../components/ui';
import type { KernelStatus, KernelVersion } from '../../stores/status';
import {
  clock,
  useSystem,
  type Components,
  type ParamState,
  type SystemState,
} from '../../stores/system';

const failureText = (failure: unknown, fallback: string) =>
  failure instanceof Error ? failure.message : fallback;

const shown = (param: ParamState, value: boolean | number) =>
  typeof value === 'boolean' ? (value ? '开' : '关') : `${value}${param.unit}`;

/** One twin.toml value changed here, effective at once for every twin; it can always go back to twin.toml's. */
export function ParamField({ param }: { param: ParamState }) {
  const put = useSystem((s) => s.put);
  const [value, setValue] = useState(String(param.value));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => setValue(String(param.value)), [param.value]);
  const save = (json: object) => {
    setBusy(true);
    setError('');
    put(`/api/admin/system/params/${param.key}`, json)
      .catch((failure: unknown) => setError(failureText(failure, '保存失败')))
      .finally(() => setBusy(false));
  };
  const note =
    param.custom && param.changed_at
      ? `${param.changed_by ?? '本机'} 于 ${clock(Date.parse(param.changed_at) / 1000)} 修改，代替 twin.toml 的设置（${shown(param, param.default)}）。`
      : '';
  const restore = param.custom && (
    <Button variant="ghost" size="sm" disabled={busy} onClick={() => save({})}>
      恢复 twin.toml 的设置
    </Button>
  );
  if (typeof param.value === 'boolean')
    return (
      <Stack gap={2}>
        <Switch
          label={param.label}
          checked={param.value}
          disabled={busy}
          onCheckedChange={(enabled) => save({ value: enabled })}
        />
        <Text size="xs" tone="tertiary">
          {param.help}
          {note && ` ${note}`}
        </Text>
        {restore && (
          <Row gap={2} wrap>
            {restore}
          </Row>
        )}
        {error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
      </Stack>
    );
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const number = Number(value.trim());
    if (!value.trim() || !Number.isFinite(number)) {
      setError('请填数字');
      return;
    }
    save({ value: number });
  };
  const id = `system-param-${param.key.replace('.', '-')}`;
  const dirty = value.trim() !== String(param.value);
  return (
    <form onSubmit={submit} aria-label={`修改${param.label}`}>
      <Stack gap={2}>
        <Field
          id={id}
          label={param.unit ? `${param.label}（${param.unit}）` : param.label}
          help={param.help}
          error={error || undefined}
        >
          <Input
            id={id}
            inputMode="decimal"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </Field>
        {/* The button shows once the value is edited, so a page of fields is not a column of idle buttons. */}
        {(dirty || busy || restore) && (
          <Row gap={2} wrap>
            {(dirty || busy) && (
              <Button type="submit" size="sm" loading={busy}>
                保存
              </Button>
            )}
            {restore}
          </Row>
        )}
        {note && (
          <Text size="xs" tone="tertiary">
            {note}
          </Text>
        )}
      </Stack>
    </form>
  );
}

/** The parameters that are not about one part: the recording library's limits. */
export function Params({ state }: { state: SystemState }) {
  const params = state.params?.filter((p) => p.key.startsWith('library.'));
  return (
    <Section
      level={4}
      title="录音库"
      description="改完立即生效，所有分身一起；其他参数在 twin.toml 里改，重启后生效。"
    >
      {params ? (
        <Stack gap={6}>
          {params.map((param) => (
            <ParamField key={param.key} param={param} />
          ))}
        </Stack>
      ) : (
        <Text size="sm" tone="secondary">
          服务器版本不支持在这里修改参数。
        </Text>
      )}
    </Section>
  );
}

export const kernelLabel = (version: KernelVersion) =>
  `${version.prompt} · 分类 ${version.taxonomy}`;

const busyKernel = (twin: KernelStatus) =>
  twin.state === 'queued' || twin.state === 'running';

function kernelState(twin: KernelStatus) {
  if (twin.state === 'running') return '正在升级';
  if (twin.state === 'queued') return '排队中';
  if (twin.scope === 'none') return '已是最新';
  const redo =
    twin.pending_chunks > 0
      ? `需重新整理 ${twin.pending_chunks} 段`
      : '只需重新合并';
  if (twin.state === 'error') return `上次整理失败 · ${redo}`;
  return `${twin.state === 'awaiting_confirmation' ? '待确认' : '待升级'} · ${redo}`;
}

function kernelBuilt(twin: KernelStatus) {
  if (twin.built) return kernelLabel(twin.built);
  return twin.scope === 'none' ? '还没有记忆' : '旧版';
}

/** The parts a release may raise the version of: what each twin was built on, and upgrading one twin or all. */
export function Upgrades({ state }: { state: SystemState }) {
  const components = useSystem((s) => s.components);
  const loadError = useSystem((s) => s.componentsError);
  const load = useSystem((s) => s.loadComponents);
  const upgrade = useSystem((s) => s.upgrade);
  const confirm = useConfirm();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const working =
    !!components &&
    (components.kernel.twins.some(busyKernel) ||
      components.ledger.twins.some((twin) => twin.running));
  // While an upgrade runs, follow it here; nothing is polled otherwise, since the view opens every twin's memories.
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => void load(), 5_000);
    return () => clearInterval(timer);
  }, [working, load]);
  if (!components)
    return (
      <Text
        role={loadError ? 'alert' : 'status'}
        size="sm"
        tone={loadError ? 'danger' : 'secondary'}
      >
        {loadError || '正在读取各分身的版本…'}
      </Text>
    );
  const run = (key: string, part: 'kernel' | 'ledger', ids?: string[]) => {
    setBusy(key);
    setError('');
    upgrade(part, ids)
      .catch((failure: unknown) => setError(failureText(failure, '升级失败')))
      .finally(() => setBusy(null));
  };
  return (
    <Stack gap={6}>
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
      <KernelSection
        components={components}
        params={state.params?.filter((p) => p.key.startsWith('kernel.'))}
        busy={busy}
        onUpgrade={async (ids) => {
          if (!ids) {
            const stale = components.kernel.twins.filter(
              (twin) => twin.scope !== 'none' && !busyKernel(twin),
            );
            const chunks = stale.reduce(
              (sum, twin) => sum + twin.pending_chunks,
              0,
            );
            const go = await confirm({
              title: '升级全部分身的记忆内核',
              body: `按 ${kernelLabel(components.kernel.version)} 重新整理 ${stale.length} 个分身的记忆${chunks > 0 ? `，共需重新整理 ${chunks} 段，会调用模型` : ''}。分身一个接一个整理，整理完成前各自沿用旧档案。`,
              confirmLabel: '全部升级',
            });
            if (!go) return;
          }
          run(ids ? `kernel:${ids[0]}` : 'kernel', 'kernel', ids);
        }}
      />
      <LedgerSection
        components={components}
        busy={busy}
        onUpgrade={(ids) =>
          run(ids ? `ledger:${ids[0]}` : 'ledger', 'ledger', ids)
        }
      />
      <Section
        level={4}
        title="录音库规则"
        description="新版本发布后，启动时自动按新规则重判旧规则做出的自动决定，结果不变的只改版本；人做的决定不受影响。转写服务换版本后，录音库会标出可以重新转写的录音，由成员决定。"
      >
        <KeyValue
          items={[
            ['说话人自动归属', components.library.attribution],
            ['片段复核', components.library.cleanup],
          ]}
        />
      </Section>
    </Stack>
  );
}

function KernelSection({
  components,
  params,
  busy,
  onUpgrade,
}: {
  components: Components;
  params: ParamState[] | undefined;
  busy: string | null;
  onUpgrade: (ids?: string[]) => void;
}) {
  const { version, twins } = components.kernel;
  const stale = twins.filter(
    (twin) => twin.scope !== 'none' && !busyKernel(twin),
  );
  return (
    <Section
      level={4}
      title="记忆内核"
      description={`抽取和合并记忆的提示词 ${version.prompt}，记忆分类 ${version.taxonomy}。升级后按新版本重新整理记忆，整理完成前沿用旧档案。`}
    >
      <Stack gap={4}>
        {stale.length > 0 ? (
          <Row gap={2} wrap>
            <Button
              size="sm"
              loading={busy === 'kernel'}
              disabled={busy !== null}
              onClick={() => onUpgrade()}
            >
              全部升级（{stale.length} 个分身）
            </Button>
          </Row>
        ) : (
          <Text size="sm" tone="secondary">
            {twins.some(busyKernel)
              ? '正在升级，完成后这里会更新。'
              : '所有分身都已是最新。'}
          </Text>
        )}
        <Table
          caption="各分身的记忆内核"
          headers={['分身', '记忆按哪个版本整理', '状态', '']}
          rows={twins.map((twin) => [
            twin.name,
            kernelBuilt(twin),
            kernelState(twin),
            twin.scope !== 'none' && !busyKernel(twin) ? (
              <Button
                key="upgrade"
                variant="ghost"
                size="sm"
                aria-label={`升级 ${twin.name} 的记忆内核`}
                loading={busy === `kernel:${twin.id}`}
                disabled={busy !== null}
                onClick={() => onUpgrade([twin.id])}
              >
                升级
              </Button>
            ) : null,
          ])}
        />
        {params?.map((param) => (
          <ParamField key={param.key} param={param} />
        ))}
      </Stack>
    </Section>
  );
}

function LedgerSection({
  components,
  busy,
  onUpgrade,
}: {
  components: Components;
  busy: string | null;
  onUpgrade: (ids?: string[]) => void;
}) {
  const { version, enabled, twins } = components.ledger;
  const stale = twins.filter((twin) => twin.pending > 0 && !twin.running);
  return (
    <Section
      level={4}
      title="承诺账本抽取"
      description={`从会议里读出承诺和进展的规则 ${version}。升级后用新规则读还没按它读过的会议，会调用模型；人改过的条目不会被覆盖。`}
    >
      {!enabled ? (
        <Text size="sm" tone="secondary">
          承诺账本已关闭，开启后才能升级。
        </Text>
      ) : (
        <Stack gap={4}>
          {stale.length > 0 ? (
            <Row gap={2} wrap>
              <Button
                size="sm"
                variant="secondary"
                loading={busy === 'ledger'}
                disabled={busy !== null}
                onClick={() => onUpgrade()}
              >
                全部整理（{stale.length} 个分身）
              </Button>
            </Row>
          ) : (
            <Text size="sm" tone="secondary">
              {twins.some((twin) => twin.running)
                ? '正在整理，完成后这里会更新。'
                : '所有会议都已按当前规则整理过。'}
            </Text>
          )}
          <Table
            caption="各分身的承诺账本"
            headers={['分身', '会议', '状态', '']}
            rows={twins.map((twin) => [
              twin.name,
              `${twin.meetings} 场`,
              twin.running
                ? '正在整理'
                : twin.pending > 0
                  ? `${twin.pending} 场待整理`
                  : twin.meetings > 0
                    ? '已是最新'
                    : '还没有会议',
              twin.pending > 0 && !twin.running ? (
                <Button
                  key="upgrade"
                  variant="ghost"
                  size="sm"
                  aria-label={`整理 ${twin.name} 的承诺账本`}
                  loading={busy === `ledger:${twin.id}`}
                  disabled={busy !== null}
                  onClick={() => onUpgrade([twin.id])}
                >
                  整理
                </Button>
              ) : null,
            ])}
          />
        </Stack>
      )}
    </Section>
  );
}
