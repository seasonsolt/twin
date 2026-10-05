import { useId, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { LayoutScope } from '../../components/motion';
import { MetricNumber } from '../../components/effects/MetricNumber';
import { Badge, Button } from '../../components/ui';
import { useMotionPreset } from '../../design/motion';
import {
  kindOptions,
  type BuildResult,
  type Source,
  type SourceKind,
} from './types';

export function KindSelector({
  value,
  onChange,
  disabled,
}: {
  value: SourceKind;
  onChange: (kind: SourceKind) => void;
  disabled: boolean;
}) {
  const id = useId();
  const { reduced, transition } = useMotionPreset('layout');
  return (
    <LayoutScope>
      <fieldset disabled={disabled} aria-describedby="kind-help">
        <legend className="mb-2 font-medium">资料类型</legend>
        <div className="flex flex-wrap gap-1 rounded-md border border-border bg-canvas p-1">
          {kindOptions.map(([kind, label]) => (
            <label
              key={kind}
              className="relative cursor-pointer rounded-sm px-3 py-2"
            >
              <input
                className="peer sr-only"
                type="radio"
                name={`kind-${id}`}
                value={kind}
                checked={value === kind}
                onChange={() => onChange(kind)}
              />
              {value === kind && (
                <motion.span
                  layoutId={reduced ? undefined : `kind-${id}`}
                  initial={reduced ? { opacity: 0 } : false}
                  animate={{ opacity: 1 }}
                  transition={transition}
                  className="absolute inset-0 rounded-sm bg-surface shadow-elevation-1"
                />
              )}
              <span className="relative rounded-sm peer-focus-visible:outline-2 peer-focus-visible:outline-offset-4 peer-focus-visible:outline-accent">
                {label}
              </span>
            </label>
          ))}
        </div>
        <p id="kind-help" className="mt-2 text-sm text-secondary">
          {kindOptions.find(([kind]) => kind === value)?.[2]}
        </p>
      </fieldset>
    </LayoutScope>
  );
}
export function DropZone({
  kind,
  files,
  onChange,
  disabled,
}: {
  kind: SourceKind;
  files: File[];
  onChange: (files: File[]) => void;
  disabled: boolean;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const depth = useRef(0);
  const [over, setOver] = useState(false);
  const { reduced, transition } = useMotionPreset('gentle');
  const accept = kindOptions.find(([value]) => value === kind)![3];
  return (
    <div className="space-y-2">
      <label htmlFor="source-files" className="sr-only">
        文件（可多选）
      </label>
      <input
        ref={picker}
        id="source-files"
        className="sr-only"
        tabIndex={-1}
        type="file"
        multiple
        accept={accept}
        disabled={disabled}
        onChange={(event) => {
          onChange(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />
      <motion.button
        type="button"
        disabled={disabled}
        aria-label="选择或拖入文件（可多选）"
        aria-describedby="file-help"
        onClick={() => picker.current?.click()}
        onDragEnter={(event) => {
          event.preventDefault();
          if (!disabled) {
            depth.current++;
            setOver(true);
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = disabled ? 'none' : 'copy';
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          depth.current = Math.max(0, depth.current - 1);
          if (!depth.current) setOver(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          depth.current = 0;
          setOver(false);
          if (!disabled) onChange(Array.from(event.dataTransfer.files));
        }}
        style={reduced ? { scale: 1 } : undefined}
        animate={{
          ...(reduced ? {} : { scale: over ? 1.015 : 1 }),
          borderColor: over ? 'var(--accent)' : 'var(--border)',
        }}
        transition={transition}
        className="flex min-h-32 w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed bg-canvas p-5 text-secondary disabled:opacity-50"
      >
        <span className="font-medium text-primary">
          {over ? '松开以选择文件' : '拖入文件，或点击选择'}
        </span>
        <span id="file-help" className="text-sm">
          支持 {accept.replaceAll(',', ' ')}，可多选；Enter / 空格打开文件选择器
        </span>
      </motion.button>
      {files.length > 0 && (
        <ul aria-label="待导入文件" className="text-sm text-secondary">
          {files.map((file, i) => (
            <li key={i}>{file.name}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
export function SourceRow({
  source,
  onDelete,
}: {
  source: Source;
  onDelete: () => void;
}) {
  const s = source;
  const facets = (s.facets ?? []).map((facet) => facet.name).join('、');
  return (
    <article
      aria-label={s.title}
      className="space-y-2 rounded-md border border-border p-4"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="mr-auto break-all font-medium">{s.title}</h3>
        <Badge tone={s.evidence_class === 'self_report' ? 'info' : 'success'}>
          {s.kind_label}
        </Badge>
        <Button
          variant="ghost"
          size="sm"
          className="text-danger"
          onClick={onDelete}
          aria-label={`删除 ${s.title}`}
        >
          删除
        </Button>
      </div>
      <p className="text-sm text-secondary">
        本人 / 全部：
        <MetricNumber value={s.n_target} /> /{' '}
        <MetricNumber value={s.n_expressions} /> ·{' '}
        {[s.first_date, s.last_date].filter(Boolean).join(' 至 ') || '—'}
      </p>
      <p className="text-sm text-secondary">
        原话 <MetricNumber value={s.expressions_total ?? s.n_expressions} />{' '}
        条（本人 <MetricNumber value={s.expressions_target ?? s.n_target} /> /
        他人{' '}
        <MetricNumber
          value={s.expressions_others ?? s.n_expressions - s.n_target}
        />
        ） · 支撑档案 <MetricNumber value={s.items_supported ?? 0} /> 条
        {facets && ` · 涉及：${facets}`}
        {s.build_status === 'not_built'
          ? ' · 尚未构建'
          : s.build_status === 'no_items'
            ? ' · 构建后未产生档案条目'
            : ''}
      </p>
      {s.declined_facets.length > 0 && (
        <p className="text-sm text-secondary">
          未授权细项：{s.declined_facets.join('、')}
        </p>
      )}
    </article>
  );
}
export function BuildSummary({ result: r }: { result: BuildResult }) {
  return (
    <div role="status" className="mt-4 space-y-3 text-sm">
      <p className="text-success">
        资料 {r.sources ?? 0} 份，本次抽取 {r.chunks_extracted ?? 0} 块，候选{' '}
        {r.candidates ?? 0} 条，档案条目 {r.items ?? 0} 条。
        {r.failures?.length
          ? ` 有 ${r.failures.length} 处失败，再次构建会自动补跑。`
          : ''}{' '}
        <a href="#/persona" className="text-accent underline">
          查看档案与完成度
        </a>
      </p>
      <p>
        新增 {r.items_added ?? 0} 条、修改 {r.items_changed ?? 0} 条、删除{' '}
        {r.items_removed ?? 0} 条，涉及 {r.facets_changed ?? 0} 个细项
      </p>
      <ul className="space-y-1 text-secondary">
        {Object.entries(r.facet_diffs ?? {})
          .filter(([, diff]) => diff.added || diff.changed || diff.removed)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([id, diff]) => (
            <li key={id}>
              {id}：新增 {diff.added} 条、修改 {diff.changed} 条、删除{' '}
              {diff.removed} 条
            </li>
          ))}
      </ul>
    </div>
  );
}
