import { Component, lazy, Suspense, useState, type ReactNode } from 'react';
import type { Capabilities } from '../avatar/types';
import { personaUrl } from '../../lib/persona';
import { SpeakingGlow } from '../avatar/SpeakingGlow';
import { Avatar } from '../avatar/Avatar';
import { usePersonas } from '../../stores/personas';

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
}: {
  name: string;
  capabilities: Capabilities | null;
  level?: number;
  speaking?: boolean;
  glow?: boolean;
  className?: string;
  personaId?: string;
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
      <div className="size-full overflow-hidden rounded-full">
        {portrait && failedPortrait !== portrait ? (
          <img
            src={portrait}
            alt={`${name}的肖像`}
            onError={() => setFailedPortrait(portrait)}
            className="size-full object-cover object-[50%_30%]"
          />
        ) : model && failedModel !== model ? (
          <StillBoundary key={model} fallback={initial}>
            <Suspense fallback={initial}>
              <Avatar3D
                url={model}
                still
                mouth={0}
                speaking={false}
                onFallback={() => setFailedModel(model)}
              />
            </Suspense>
          </StillBoundary>
        ) : (
          initial
        )}
      </div>
      {glow && <SpeakingGlow round level={level} speaking={speaking} />}
    </div>
  );
}
