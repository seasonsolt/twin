import type { BuildResult } from './types';

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
