import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { Capabilities } from '../avatar/types';
import type { Status } from '../../stores/status';

export interface IdentityData {
  name: string;
  about: string;
  name_source: 'config' | 'user';
  aliases: string[];
  voice: string | null;
  avatar: string | null;
  egress: Status['egress'];
}

export function useIdentity(active = true) {
  const [data, setData] = useState<IdentityData | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [avatarError, setAvatarError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const changed = () => setAttempt((value) => value + 1);
    window.addEventListener('twin-assets-changed', changed);
    return () => window.removeEventListener('twin-assets-changed', changed);
  }, []);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setAvatarError('');
    void api<IdentityData>('/api/identity', { signal: controller.signal })
      .then((loaded) => {
        if (!controller.signal.aborted) setData(loaded);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(failure instanceof Error ? failure.message : '身份加载失败');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    void api<Capabilities>('/api/media/capabilities', {
      signal: controller.signal,
    })
      .then((loaded) => {
        if (!controller.signal.aborted) setCapabilities(loaded);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setAvatarError(
            failure instanceof Error ? failure.message : '形象加载失败',
          );
      });
    return () => controller.abort();
  }, [active, attempt]);
  return {
    data,
    capabilities,
    loading,
    error,
    avatarError,
    reload: () => setAttempt((value) => value + 1),
  };
}
