import {
  Component,
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { Avatar } from '../playback/Avatar';
import type { Capabilities } from '../playback/types';

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
  label,
  onModelNameChange,
}: {
  capabilities: Capabilities;
  mouth?: number;
  speaking?: boolean;
  label?: string;
  onModelNameChange?(name: string | null): void;
}) {
  const url = capabilities.avatar_model?.url;
  const [failedUrl, setFailedUrl] = useState<string | undefined>();
  const onFallback = useCallback(() => {
    setFailedUrl(url);
    onModelNameChange?.(null);
  }, [url, onModelNameChange]);
  useEffect(() => {
    if (!url) onFallback();
  }, [url, onFallback]);
  useEffect(() => {
    onModelNameChange?.(null);
  }, [url, onModelNameChange]);
  const fallback = capabilities.avatar ? (
    <Avatar spec={capabilities.avatar} mouthLevel={mouth} />
  ) : null;
  const badge = label || capabilities.label || capabilities.avatar?.label;
  if (!url || failedUrl === url || !badge) return fallback;
  return (
    <ModelBoundary key={url} fallback={fallback} onFallback={onFallback}>
      <Suspense fallback={fallback}>
        <Avatar3D
          url={url}
          mouth={mouth}
          speaking={speaking}
          label={badge}
          onFallback={onFallback}
          onModelNameChange={onModelNameChange}
        />
      </Suspense>
    </ModelBoundary>
  );
}
