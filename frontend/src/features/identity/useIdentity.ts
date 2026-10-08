import { useEffect } from 'react';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import {
  clearPrefetch,
  loadEssential,
  peekEssential,
} from '../../lib/personaPrefetch';
import { api } from '../../lib/api';
import { usePersonas } from '../../stores/personas';
import { presetSpec } from '../avatar/presets';
import type { Capabilities } from '../avatar/types';
import type { Status } from '../../stores/status';

export interface IdentityData {
  name: string;
  about: string;
  name_source: 'config' | 'user';
  onboarding_pending?: boolean;
  visitor?: boolean;
  aliases: string[];
  voice: string | null;
  avatar: string | null;
  avatar_preset?: string;
  avatar_presets?: { id: string; name: string }[];
  egress: Status['egress'];
}

export function useIdentity(active = true) {
  const personaId = usePersonaId();
  const [data, setData] = useState<IdentityData | null>(
    () => peekEssential<IdentityData>('/api/identity', personaId) ?? null,
  );
  const [capabilities, setCapabilities] = useState<Capabilities | null>(
    () =>
      peekEssential<Capabilities>('/api/media/capabilities', personaId) ?? null,
  );
  const [loading, setLoading] = useState(
    () => !peekEssential('/api/identity', personaId),
  );
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
    setLoading(!peekEssential('/api/identity', personaId));
    setError('');
    setAvatarError('');
    void loadEssential<IdentityData>(
      '/api/identity',
      personaId,
      controller.signal,
    )
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
    void loadEssential<Capabilities>(
      '/api/media/capabilities',
      personaId,
      controller.signal,
    )
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
  }, [active, attempt, personaId]);
  return {
    data,
    capabilities,
    loading,
    error,
    avatarError,
    reload: () => setAttempt((value) => value + 1),
    savePreset: async (preset: string) => {
      const saved = await api<IdentityData>('/api/identity/avatar-preset', {
        method: 'PUT',
        headers: { 'X-Twin-Persona': personaId },
        json: { preset },
      });
      clearPrefetch();
      usePersonas.setState((state) => ({
        items: state.items.map((item) =>
          item.id === personaId
            ? {
                ...item,
                avatar_preset: saved.avatar_preset ?? saved.avatar ?? preset,
              }
            : item,
        ),
      }));
      if (usePersonas.getState().id !== personaId) return;
      setData(saved);
      setCapabilities((current) =>
        current
          ? {
              ...current,
              avatar: presetSpec(saved.avatar_preset ?? saved.avatar),
              avatar_preset: saved.avatar_preset,
            }
          : current,
      );
    },
  };
}
