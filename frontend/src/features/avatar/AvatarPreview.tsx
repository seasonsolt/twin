import {
  Component,
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { Avatar, PortraitAvatar } from './Avatar';
import type { Capabilities } from './types';
import { personaUrl } from '../../lib/persona';

const Avatar3D = lazy(() => import('./Avatar3D'));

class ModelBoundary extends Component<
  { children: ReactNode; fallback: ReactNode; onFallback(): void },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onFallback();
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function AvatarPreview({
  capabilities,
  mouth = 0,
  speaking = false,
  onModelNameChange,
}: {
  capabilities: Capabilities;
  mouth?: number;
  speaking?: boolean;
  onModelNameChange?(name: string | null): void;
}) {
  const url = capabilities.avatar_model?.url
    ? personaUrl(capabilities.avatar_model.url)
    : undefined;
  const [failedUrl, setFailedUrl] = useState<string | undefined>();
  const imageUrl = capabilities.avatar_image?.url
    ? personaUrl(capabilities.avatar_image.url)
    : undefined;
  const [failedImageUrl, setFailedImageUrl] = useState<string | undefined>();
  const onFallback = useCallback(() => {
    setFailedUrl(url);
    onModelNameChange?.(null);
  }, [url, onModelNameChange]);
  useEffect(() => {
    if (!url) onFallback();
  }, [url, onFallback]);
  useEffect(() => {
    onModelNameChange?.(null);
  }, [url, imageUrl, onModelNameChange]);
  const fallback =
    imageUrl && failedImageUrl !== imageUrl ? (
      <PortraitAvatar
        url={imageUrl}
        mouthLevel={mouth}
        speaking={speaking}
        onError={() => setFailedImageUrl(imageUrl)}
      />
    ) : capabilities.avatar ? (
      <Avatar spec={capabilities.avatar} mouthLevel={mouth} />
    ) : null;
  if (
    (imageUrl?.includes('?v=') && failedImageUrl !== imageUrl) ||
    !url ||
    failedUrl === url
  )
    return fallback;
  return (
    <ModelBoundary key={url} fallback={fallback} onFallback={onFallback}>
      <Suspense fallback={fallback}>
        <Avatar3D
          url={url}
          mouth={mouth}
          speaking={speaking}
          onFallback={onFallback}
          onModelNameChange={onModelNameChange}
        />
      </Suspense>
    </ModelBoundary>
  );
}
