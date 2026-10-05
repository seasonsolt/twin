import { MetricNumber } from '../../components/effects/MetricNumber';
import { Badge, Card, Meter } from '../../components/ui';
import type { Tone } from '../../components/ui/controls';
import type { Coverage } from './types';

const levelTones: Record<number, Tone> = {
  0: 'neutral',
  1: 'info',
  2: 'success',
  3: 'info',
};
export function CoverageOverview({ report }: { report: Coverage }) {
  return (
    <div className="space-y-6">
      <section
        aria-label="维度汇总"
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        {report.dimensions.map((dimension) => (
          <Card key={dimension.dimension_id}>
            <h2 className="font-semibold">
              {dimension.dimension_id} {dimension.name}
            </h2>
            <p className="my-3 text-sm text-secondary">
              已授权细项 <MetricNumber value={dimension.consented} /> /{' '}
              <MetricNumber value={dimension.facets} />
              {dimension.conflicts > 0 && ` · 矛盾 ${dimension.conflicts} 处`}
            </p>
            <div className="space-y-3">
              {(
                [
                  ['covered', '覆盖率'],
                  ['sufficient', '充分率'],
                  ['verified', '验证率'],
                ] as const
              ).map(([key, label]) => {
                const ratio = dimension[key];
                return (
                  <div key={key}>
                    <div className="flex justify-between text-sm">
                      <span>{label}</span>
                      {ratio === null ? (
                        <span aria-label={`${label}暂无已授权细项`}>—</span>
                      ) : (
                        <MetricNumber
                          value={Math.round(ratio * 100)}
                          suffix="%"
                        />
                      )}
                    </div>
                    {ratio !== null && (
                      <Meter
                        hideLabel
                        value={ratio * 100}
                        label={`${dimension.name}${label}`}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </Card>
        ))}
      </section>
      <Card>
        <h2 className="mb-3 text-lg font-semibold">下一步采集建议</h2>
        {!report.suggestions.length ? (
          <p>所有已授权细项都已验证。</p>
        ) : (
          <ul className="space-y-2 text-sm text-secondary">
            {report.suggestions.slice(0, 15).map((suggestion) => (
              <li key={suggestion.facet_id}>
                <strong className="text-primary">
                  {suggestion.facet_id} {suggestion.name}
                </strong>
                ：{suggestion.reason}
                {suggestion.sources.length > 0 &&
                  `；建议来源：${suggestion.sources.map((kind) => report.kind_labels[kind] ?? kind).join('、')}`}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <h2 className="mb-3 text-lg font-semibold">细项 × 来源矩阵</h2>
        <ul aria-label="细项完成度" className="grid gap-3 md:grid-cols-2">
          {report.facets.map((facet) => (
            <li
              key={facet.facet_id}
              className="space-y-2 rounded-md border border-border p-3 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="mr-auto font-medium">
                  {facet.facet_id} {facet.name}
                </h3>
                <Badge
                  tone={facet.consented ? levelTones[facet.level] : 'neutral'}
                >
                  {facet.consented
                    ? report.level_labels[facet.level]
                    : '未授权'}
                </Badge>
                {facet.conflicts > 0 && <Badge tone="warning">矛盾</Badge>}
              </div>
              <p className="text-secondary">
                充分度 {facet.sufficiency.toFixed(2)} · 已确认 {facet.confirmed}{' '}
                · 被问 / 答不上 {facet.asked} / {facet.abstained}
              </p>
              <p className="text-secondary">
                {Object.entries(report.kind_labels)
                  .map(
                    ([kind, label]) => `${label} ${facet.by_kind[kind] ?? 0}`,
                  )
                  .join(' · ')}
              </p>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
