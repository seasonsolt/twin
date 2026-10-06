import { useCallback, useState } from 'react';
import { useLocation } from 'react-router';
import { Badge, Button, Card, Skeleton, Table } from '../components/ui';
import { useIdentity } from '../features/identity/useIdentity';
import { AvatarPreview } from '../features/avatar/AvatarPreview';
import { useStatus } from '../stores/status';

export function Identity() {
  const identity = useIdentity(useLocation().pathname === '/identity');
  const labels = useStatus((state) => state.data?.labels);
  const data = identity.data;
  const modelUrl = identity.capabilities?.avatar_model?.url;
  const [model, setModel] = useState<{ url?: string; name: string | null }>({
    name: null,
  });
  const onModelNameChange = useCallback(
    (name: string | null) => {
      setModel({ url: modelUrl, name });
    },
    [modelUrl],
  );
  const modelName = modelUrl && model.url === modelUrl ? model.name : null;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">身份</h1>
        <p className="mt-2 text-sm text-secondary">
          名字、别名、预置音色与形象来自配置，只读展示。
        </p>
      </header>
      {labels?.explicit && <Badge tone="info">{labels.explicit}</Badge>}
      {identity.loading && <Skeleton className="h-40" />}
      {identity.error && (
        <p role="alert" className="text-danger">
          {identity.error}{' '}
          <Button variant="secondary" onClick={identity.reload}>
            重试加载
          </Button>
        </p>
      )}
      {data && (
        <>
          <Card>
            <h2 className="mb-4 text-lg font-semibold">名字与音色/形象</h2>
            <div className="flex flex-wrap items-start gap-6">
              <dl className="grid flex-1 grid-cols-[auto_1fr] gap-x-4 gap-y-2">
                <dt className="text-secondary">名字</dt>
                <dd>{data.name}</dd>
                <dt className="text-secondary">别名</dt>
                <dd>{data.aliases.join('、') || '—'}</dd>
                <dt className="text-secondary">音色</dt>
                <dd>{data.voice || '—'}（预置音色）</dd>
                <dt className="text-secondary">形象</dt>
                <dd>
                  {modelName
                    ? `${modelName}（3D 模型）`
                    : `${data.avatar || '—'}（风格化形象）`}
                </dd>
              </dl>
              {identity.capabilities?.avatar && (
                <div className="w-48">
                  <AvatarPreview
                    capabilities={identity.capabilities}
                    label={labels?.explicit}
                    onModelNameChange={onModelNameChange}
                  />
                </div>
              )}
            </div>
            {identity.avatarError && (
              <p role="alert" className="mt-3 text-danger">
                形象预览：{identity.avatarError}{' '}
                <Button variant="secondary" size="sm" onClick={identity.reload}>
                  重试预览
                </Button>
              </p>
            )}
          </Card>
          <Card>
            <h2 className="text-lg font-semibold">出境</h2>
            <p className="my-3 text-sm text-secondary">
              外部服务按配置使用，以下如实展示各后端的出境分类。
            </p>
            <div
              tabIndex={0}
              role="region"
              aria-label="出境状态"
              className="overflow-x-auto"
            >
              <Table
                caption="出境状态"
                headers={['类型', '提供方', '主机', '本机/外部', '声明/推断']}
                rows={data.egress.map((row) => [
                  row.kind,
                  row.provider,
                  row.host || '未知',
                  <Badge tone={row.external ? 'warning' : 'neutral'}>
                    {row.external ? '外部' : '本机'}
                  </Badge>,
                  row.declared ? '声明' : '推断',
                ])}
              />
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
