import { useState } from 'react';
import { api } from '../../lib/api';
import {
  Badge,
  Button,
  EmptyState,
  Heading,
  Notice,
  Row,
  Skeleton,
  Stack,
  Text,
  TextLink,
  toast,
  useConfirm,
} from '../../components/ui';
import { LensPublish } from './LensPublish';
import { LensUses } from './LensUses';
import type { Lens, LensList } from './types';
import { useLenses } from './useLenses';

const message = (failure: unknown, fallback: string) =>
  failure instanceof Error ? failure.message : fallback;

/** One published lens: what it is, its three actions, what was corrected out, and what it was used for. */
function LensBlock({
  lens,
  person,
  stopAfter,
  onAdjust,
  onChanged,
}: {
  lens: Lens;
  person: string;
  stopAfter: number;
  onAdjust: () => void;
  onChanged: () => Promise<void>;
}) {
  const confirm = useConfirm();
  const [facet, setFacet] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const act = async (action: 'pause' | 'resume' | 'withdraw', done: string) => {
    try {
      await api(
        `/api/persona/lenses/${encodeURIComponent(lens.id)}/${action}`,
        { method: 'POST', json: {} },
      );
      toast(done, 'success');
      setVersion((now) => now + 1);
      await onChanged();
    } catch (failure) {
      toast(message(failure, '操作失败'), 'danger');
    }
  };
  const paused = lens.status === 'paused';
  const who =
    lens.audience.scope === 'team'
      ? '全团队'
      : `${lens.audience.twins.length} 人`;
  return (
    <Stack gap={4}>
      <Row gap={3} wrap>
        <Heading level={2} size="section">
          {person} · {lens.name}
        </Heading>
        <Badge tone={paused ? 'warning' : 'success'}>
          {paused ? '已暂停' : '已发布'}
        </Badge>
        <Text as="span" size="sm" tone="secondary">
          {who} · {lens.facets.length} 个方面 · 本周 {lens.uses_week} 次
        </Text>
        <Row gap={2} as="div">
          <Button size="sm" variant="secondary" onClick={onAdjust}>
            调整范围
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              void (paused ? act('resume', '已恢复') : act('pause', '已暂停'))
            }
          >
            {paused ? '恢复' : '暂停'}
          </Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() =>
              void confirm({
                title: '撤回这个视角？',
                body: '同事马上不能再用，撤回后不能恢复；已经问过的对话不变。',
                confirmLabel: '撤回',
                tone: 'danger',
              }).then((ok) => {
                if (ok) void act('withdraw', '已撤回');
              })
            }
          >
            撤回
          </Button>
        </Row>
      </Row>
      {lens.stopped.map((stopped) => (
        <Notice
          key={stopped.facet_id}
          tone="warning"
          actions={
            <TextLink onClick={() => setFacet(stopped.facet_id)}>
              去看看 →
            </TextLink>
          }
        >
          “{stopped.name}”被纠正 {stopAfter} 次，已停用
        </Notice>
      ))}
      {lens.failing.length > 0 && (
        <Text size="sm" tone="secondary">
          {lens.facets
            .filter((f) => lens.failing.includes(f.facet_id))
            .map((f) => `“${f.name}”`)
            .join('、')}
          暂时不满足条件，没有在用。
        </Text>
      )}
      <LensUses
        lensId={lens.id}
        facet={facet}
        version={version}
        onFacet={setFacet}
        onChanged={onChanged}
      />
    </Stack>
  );
}

/**
 * 视角, for the person alone: a lens lends their judgement to colleagues, facet by facet. With none published it
 * offers to publish one; otherwise each lens is managed here, with what it was used for. `person` is their name.
 */
export function LensTab({
  person,
  twinId,
}: {
  person: string;
  twinId: string;
}) {
  const { data, error, reload } = useLenses();
  const [publishing, setPublishing] = useState(false);
  const [adjusting, setAdjusting] = useState<Lens | null>(null);
  if (error)
    return (
      <Stack gap={2} role="alert">
        <Text tone="danger">{error}</Text>
        <Row>
          <Button variant="secondary" onClick={() => void reload()}>
            重试加载
          </Button>
        </Row>
      </Stack>
    );
  if (!data) return <Skeleton className="h-40" />;
  const dialog = (list: LensList) => (
    <>
      {publishing && (
        <LensPublish
          open
          person={person}
          twinId={twinId}
          data={list}
          onClose={() => setPublishing(false)}
          onDone={reload}
        />
      )}
      {adjusting && (
        <LensPublish
          open
          person={person}
          twinId={twinId}
          data={list}
          lens={adjusting}
          onClose={() => setAdjusting(null)}
          onDone={reload}
        />
      )}
    </>
  );
  if (data.lenses.length === 0)
    return (
      <>
        <EmptyState title="还没有视角">
          <Button onClick={() => setPublishing(true)}>发布为视角</Button>
        </EmptyState>
        {dialog(data)}
      </>
    );
  return (
    <Stack gap={6}>
      {data.lenses.map((lens) => (
        <LensBlock
          key={lens.id}
          lens={lens}
          person={person}
          stopAfter={data.stop_after}
          onAdjust={() => setAdjusting(lens)}
          onChanged={reload}
        />
      ))}
      <Row>
        <Button variant="ghost" onClick={() => setPublishing(true)}>
          发布新视角
        </Button>
      </Row>
      {dialog(data)}
    </Stack>
  );
}
