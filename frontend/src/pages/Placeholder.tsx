import { EmptyState } from '../components/ui';
import { navItems } from '../components/layout/AppShell';

export function Placeholder({ route }: { route: string }) {
  const title = navItems.find((item) => item.route === route)?.title;
  return (
    <div>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <EmptyState
        title="此页面正在迁移"
        body="旧界面仍可使用；此处先提供导航和页面动效。"
      >
        <a
          className="rounded-md border border-border bg-surface px-4 py-2 text-accent hover:bg-surface-raised"
          href={`/#/${route}`}
        >
          打开旧界面
        </a>
      </EmptyState>
    </div>
  );
}
