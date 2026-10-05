import { useState } from 'react';
import { useLocation } from 'react-router';
import { MessageList } from '../components/effects/MessageList';
import { LayoutScope } from '../components/motion';
import {
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Skeleton,
  Switch,
} from '../components/ui';
import { CoverageOverview } from '../features/profile/CoverageOverview';
import { ItemCard } from '../features/profile/ItemCard';
import { VirtualItemList } from '../features/profile/VirtualItemList';
import { useProfile } from '../features/profile/useProfile';
import type { ProfileItem } from '../features/profile/types';

const filters = [
  ['all', '全部'],
  ['unreviewed', '待核实'],
  ['verified', '已确认'],
  ['rejected', '已否决'],
] as const;
type Filter = (typeof filters)[number][0];
function matches(item: ProfileItem, filter: Filter) {
  return (
    filter === 'all' ||
    (filter === 'verified'
      ? item.review === 'confirmed' || item.review === 'edited'
      : item.review === filter)
  );
}
export function Profile() {
  const active = useLocation().pathname === '/persona';
  const [asOf, setAsOf] = useState('');
  const [includeRejected, setIncludeRejected] = useState(false);
  const [filter, setFilter] = useState<Filter>('all');
  const data = useProfile(active, asOf, includeRejected);
  const available = data.items.filter(
    (item) => includeRejected || item.review !== 'rejected',
  );
  const visible = data.items
    .filter(
      (item) =>
        data.pending.has(item.item_id) ||
        ((includeRejected || item.review !== 'rejected') &&
          matches(item, filter)),
    )
    .sort(
      (a, b) =>
        a.dimension_id.localeCompare(b.dimension_id) ||
        a.facet_id.localeCompare(b.facet_id),
    );
  const rows = visible.map((item, index) => {
    const previous = visible[index - 1];
    return {
      id: item.item_id,
      text: item.statement,
      content: (
        <div className="space-y-3">
          {previous?.dimension_id !== item.dimension_id && (
            <h3 className="pt-3 text-lg font-semibold">
              {item.dimension_id} {item.dimension_name}
            </h3>
          )}
          {previous?.facet_id !== item.facet_id && (
            <h4 className="font-medium text-secondary">
              {item.facet_id} {item.facet_name}
            </h4>
          )}
          <ItemCard
            item={item}
            pending={data.pending.has(item.item_id)}
            onReview={data.review}
            kindLabels={data.coverage?.kind_labels ?? {}}
          />
        </div>
      ),
    };
  });
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">人格档案与完成度</h1>
        <p className="mt-2 text-sm text-secondary">
          9 个维度、39
          个细项。等级：已覆盖＝有证据；充分＝多个场合、多类来源且有实际行为证据；已验证＝测试题实测通过。
        </p>
        {data.coverage && (
          <p className="mt-1 text-sm text-tertiary">
            维度体系 {data.coverage.taxonomy}，截至 {data.coverage.as_of}。
          </p>
        )}
      </header>
      <Card>
        <Field
          id="profile-asof"
          label="完成度参考日期（可选）"
          help="仅影响完成度计算，条目仍为当前档案，不是历史快照。"
        >
          <Input
            id="profile-asof"
            type="date"
            className="max-w-64"
            value={asOf}
            onChange={(event) => setAsOf(event.target.value)}
            aria-describedby="profile-asof-description"
          />
        </Field>
      </Card>
      {data.coverageError && (
        <div role="alert" className="text-danger">
          无法加载完成度：{data.coverageError}{' '}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void data.refreshCoverage()}
          >
            重试完成度
          </Button>
        </div>
      )}
      {!data.coverage && !data.coverageError && <Skeleton className="h-40" />}
      {data.coverage && <CoverageOverview report={data.coverage} />}
      <Card>
        <h2 className="text-lg font-semibold">档案条目</h2>
        <p className="my-3 text-sm text-secondary">
          AI
          提炼的条目默认“未审核”。逐条确认、修改或驳回：驳回的不再被分身使用，修改后分身用你的表述；只依据未审核条目的回答，置信度最高
          60%。
        </p>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div
            role="group"
            aria-label="按核实状态筛选"
            className="flex flex-wrap gap-2"
          >
            {filters.map(([key, label]) => (
              <Button
                key={key}
                variant={filter === key ? 'primary' : 'secondary'}
                size="sm"
                aria-pressed={filter === key}
                disabled={key === 'rejected' && !includeRejected}
                onClick={() => setFilter(key)}
              >
                {label}（{available.filter((item) => matches(item, key)).length}
                ）
              </Button>
            ))}
          </div>
          <Switch
            label="包含已否决条目"
            checked={includeRejected}
            onCheckedChange={(value) => {
              setIncludeRejected(value);
              if (!value && filter === 'rejected') setFilter('all');
            }}
          />
        </div>
        {data.itemsError && (
          <div role="alert" className="text-danger">
            {data.itemsError}{' '}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void data.refreshItems()}
            >
              重试条目
            </Button>
          </div>
        )}
        {data.loading && <Skeleton className="mb-3 h-16" />}
        {!data.loading && !data.itemsError && !visible.length && (
          <EmptyState
            title="没有符合条件的条目"
            body="先到建档问卷答题，或到记忆资料导入资料并构建。"
          >
            <a href="#/sources" className="text-accent underline">
              去导入资料
            </a>
            <a href="/#/questionnaire" className="text-accent underline">
              去答问卷（旧界面）
            </a>
          </EmptyState>
        )}
        {visible.length > 300 ? (
          <VirtualItemList key={`${filter}-${includeRejected}`} rows={rows} />
        ) : (
          <LayoutScope>
            <MessageList
              layout
              label="档案条目"
              className="space-y-4"
              items={rows}
            />
          </LayoutScope>
        )}
      </Card>
    </div>
  );
}
