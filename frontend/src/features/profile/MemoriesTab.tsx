import { Suspense, lazy } from 'react';
import { Row, Skeleton, Tabs } from '../../components/ui';
import { personaUrl } from '../../lib/persona';
import { usePersonaId } from '../../lib/usePersonaState';
import { Memories } from '../../pages/Memories';
import { usePersonas } from '../../stores/personas';
import { MyAnswers } from '../answers/MyAnswers';
import type { useIdentity } from '../identity/useIdentity';

const MemoryGraphPanel = lazy(() => import('./graph/MemoryGraphPanel'));

export type MemoryView = 'list' | 'graph' | 'answers';

/**
 * The 记忆 tab: where the memories came from (list, uploads), how they connect (graph), and, for the person themself,
 * the answers they made the team's.
 */
export function MemoriesTab({
  identity,
  view,
  onView,
  onSpeakerCount,
  answers = false,
}: {
  identity: ReturnType<typeof useIdentity>;
  view: MemoryView;
  onView: (view: MemoryView) => void;
  onSpeakerCount?: (count: number) => void;
  /** The person's own page: the team answers they set are one of the views. */
  answers?: boolean;
}) {
  const personaId = usePersonaId();
  const current = usePersonas((state) =>
    state.items.find((item) => item.id === state.id),
  );
  return (
    <>
      <Row gap={3} wrap justify="end">
        <Tabs
          variant="filters"
          label="记忆的看法"
          value={view}
          onValueChange={(next) =>
            onView(
              next === 'graph' || (next === 'answers' && answers)
                ? next
                : 'list',
            )
          }
          items={[
            { value: 'list', label: '列表' },
            { value: 'graph', label: '图谱' },
            ...(answers ? [{ value: 'answers', label: '我的团队答案' }] : []),
          ]}
        />
      </Row>
      {view === 'answers' && answers ? (
        <MyAnswers />
      ) : view === 'graph' ? (
        <Suspense fallback={<Skeleton panel />}>
          <MemoryGraphPanel
            key={personaId}
            twin={{
              id: personaId,
              name: identity.data?.name || current?.name || '分身',
              avatarPreset:
                identity.data?.avatar_preset ??
                identity.data?.avatar ??
                current?.avatar_preset,
              portrait: identity.capabilities?.avatar_image
                ? personaUrl(
                    identity.capabilities.avatar_image.url ||
                      '/api/media/avatar-image',
                    personaId,
                  )
                : undefined,
            }}
          />
        </Suspense>
      ) : (
        <Memories profile onSpeakerCount={onSpeakerCount} />
      )}
    </>
  );
}
