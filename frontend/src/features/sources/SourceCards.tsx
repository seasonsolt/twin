import type { BuildResult } from './types';

export function BuildSummary({ result: r }: { result: BuildResult }) {
  return (
    <div role="status" className="mt-4 space-y-3 text-sm">
      <p>
        已整理 {r.sources ?? 0} 份记忆。
        {r.failures?.length ? '有些内容没有处理成功，可以重试。' : ''}{' '}
        <a href="#/profile" className="text-accent underline">
          看看我了解到的你
        </a>
      </p>
      <p>
        新增 {r.items_added ?? 0} 条、修改 {r.items_changed ?? 0} 条、删除{' '}
        {r.items_removed ?? 0} 条
      </p>
    </div>
  );
}
