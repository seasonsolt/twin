import { Component, lazy, Suspense, useState, type ReactNode } from 'react';
import type { Capabilities } from '../avatar/types';
import { personaUrl } from '../../lib/persona';
import { Avatar } from '../avatar/Avatar';
import { usePersonas } from '../../stores/personas';
import {
  Clip,
  Portrait,
  PresenceRing,
  usePresence,
  type PresenceState,
} from '../../components/ui';

const Avatar3D = lazy(() => import('../avatar/Avatar3D'));

class StillBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function ChatAvatar({
  name,
  capabilities,
  level = 0,
  speaking = false,
  glow = true,
  className = 'size-9',
  personaId,
  live,
}: {
  name: string;
  capabilities: Capabilities | null;
  level?: number;
  speaking?: boolean;
  glow?: boolean;
  className?: string;
  personaId?: string;
  /** A 3D model moves with this state (eyes, head, mouth) instead of showing one still frame. For the one large
   * portrait on the chat stage only; avatars in lists stay still. A portrait photo never moves. */
  live?: PresenceState;
}) {
  const selectedPreset = usePersonas(
    (state) =>
      state.items.find((item) => item.id === (personaId ?? state.id))
        ?.avatar_preset,
  );
  const portrait = capabilities?.avatar_image?.url
    ? personaUrl(capabilities.avatar_image.url, personaId)
    : undefined;
  const model = capabilities?.avatar_model?.url
    ? personaUrl(capabilities.avatar_model.url, personaId)
    : undefined;
  const presence = usePresence(speaking ? 'speaking' : 'idle', level);
  const [failedPortrait, setFailedPortrait] = useState<string>();
  const [failedModel, setFailedModel] = useState<string>();
  const initial = (
    <Avatar
      spec={capabilities?.avatar}
      preset={
        capabilities?.avatar_preset ??
        capabilities?.avatar?.avatar_id ??
        selectedPreset
      }
      mouthLevel={level}
    />
  );
  return (
    <div className={`relative shrink-0 ${className}`} aria-label="分身头像">
      <Clip shape="circle">
        <div className="size-full">
          {portrait && failedPortrait !== portrait ? (
            <Portrait
              src={portrait}
              alt={`${name}的肖像`}
              onError={() => setFailedPortrait(portrait)}
            />
          ) : model && failedModel !== model ? (
            <StillBoundary key={model} fallback={initial}>
              <Suspense fallback={initial}>
                {live ? (
                  <Avatar3D
                    url={model}
                    fill
                    mouth={level}
                    state={live}
                    onFallback={() => setFailedModel(model)}
                  />
                ) : (
                  <Avatar3D
                    url={model}
                    still
                    mouth={0}
                    onFallback={() => setFailedModel(model)}
                  />
                )}
              </Suspense>
            </StillBoundary>
          ) : (
            initial
          )}
        </div>
      </Clip>
      {glow && <PresenceRing presence={presence} />}
    </div>
  );
}
