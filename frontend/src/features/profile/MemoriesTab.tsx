import { Suspense, lazy } from 'react';
import { Row, Skeleton, Tabs } from '../../components/ui';
import { personaUrl } from '../../lib/persona';
import { usePersonaId } from '../../lib/usePersonaState';
import { Memories } from '../../pages/Memories';
import { usePersonas } from '../../stores/personas';
import type { useIdentity } from '../identity/useIdentity';

const MemoryGraphPanel = lazy(() => import('./graph/MemoryGraphPanel'));

/** The 记忆 tab: where the memories came from (list, uploads) or how they connect (graph). */
export function MemoriesTab({
  identity,
  view,
  onView,
  onSpeakerCount,
}: {
  identity: ReturnType<typeof useIdentity>;
  view: 'list' | 'graph';
  onView: (view: 'list' | 'graph') => void;
  onSpeakerCount?: (count: number) => void;
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
          onValueChange={(next) => onView(next === 'graph' ? 'graph' : 'list')}
          items={[
            { value: 'list', label: '列表' },
            { value: 'graph', label: '图谱' },
          ]}
        />
      </Row>
      {view === 'graph' ? (
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
