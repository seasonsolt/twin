import { Component, lazy, Suspense, useState, type ReactNode } from 'react';
import type { Capabilities } from '../avatar/types';
import { personaUrl } from '../../lib/persona';
import { SpeakingGlow } from '../avatar/SpeakingGlow';

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
}: {
  name: string;
  capabilities: Capabilities | null;
  level?: number;
  speaking?: boolean;
}) {
  const portrait = capabilities?.avatar_image?.url
    ? personaUrl(capabilities.avatar_image.url)
    : undefined;
  const model = capabilities?.avatar_model?.url
    ? personaUrl(capabilities.avatar_model.url)
    : undefined;
  const [failedPortrait, setFailedPortrait] = useState<string>();
  const [failedModel, setFailedModel] = useState<string>();
  const initial = (
    <span
      role="img"
      aria-label={`${name}的头像`}
      className="flex size-full items-center justify-center bg-accent/10 text-sm text-secondary"
    >
      {Array.from(name.trim())[0] || '本'}
    </span>
  );
  return (
    <div className="relative size-9 shrink-0" aria-label="分身头像">
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
      <SpeakingGlow round level={level} speaking={speaking} />
    </div>
  );
}
