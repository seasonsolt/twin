import { useEffect, useRef } from 'react';
import type { Capabilities } from '../avatar/types';
import { loadEssential, peekEssential } from '../../lib/personaPrefetch';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import type { useConversation } from './useConversation';
import { useReplyAudio } from './useReplyAudio';
import { useReplyVideos, videoUrl } from './useReplyVideos';
import type { Turn } from './types';

/**
 * Speaking the twin's answers: what the voice and the video can do, which answer is playing, and the choice between
 * the voice and the real-person video of one. The thread's play buttons, the page's menu and the portrait panel
 * all work through this one place.
 */
export function usePlayback({
  active,
  chat,
  name,
  openStage,
}: {
  active: boolean;
  chat: ReturnType<typeof useConversation>;
  name: string;
  /** Called when the portrait should show: a reply is about to be spoken. */
  openStage(): void;
}) {
  const personaId = usePersonaId();
  const [capabilities, setCapabilities] = useState<Capabilities | null>(
    () =>
      peekEssential<Capabilities>('/api/media/capabilities', personaId) ?? null,
  );
  const [assetVersion, setAssetVersion] = useState(0);
  const [videoId, setVideoId] = useState('');
  const [videoPlaying, setVideoPlaying] = useState(false);
  useEffect(() => {
    const changed = () => {
      setCapabilities(null);
      setVideoId('');
      setVideoPlaying(false);
      setAssetVersion((value) => value + 1);
    };
    window.addEventListener('twin-assets-changed', changed);
    return () => window.removeEventListener('twin-assets-changed', changed);
  }, [setCapabilities, setVideoId, setVideoPlaying, setAssetVersion]);
  const audio = useReplyAudio(active);
  useEffect(() => {
    if (audio.speaking) openStage();
  }, [audio.speaking, openStage]);
  const autoSpoken = useRef<string | null>(null);
  useEffect(() => {
    const turn = chat.turns.find((entry) => entry.id === chat.newest);
    if (
      !active ||
      !capabilities?.available ||
      !turn?.reply ||
      !turn.reply.reply.trim() ||
      autoSpoken.current === turn.id
    )
      return;
    autoSpoken.current = turn.id;
    audio.toggle(turn.id, turn.reply, name);
  }, [active, capabilities, chat.turns, chat.newest, audio, name]);
  const video = useReplyVideos(
    active && !!capabilities?.video?.available,
    chat.turns,
    name,
    capabilities?.video?.asset_key ?? '',
  );
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    void loadEssential<Capabilities>(
      '/api/media/capabilities',
      personaId,
      controller.signal,
    )
      .then((data) => {
        if (!controller.signal.aborted) setCapabilities(data);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [active, assetVersion, personaId, setCapabilities]);
  const currentTurn = chat.turns.find(
    (turn) => turn.id === (videoId || audio.id || chat.newest),
  );
  const toggleReply = (turn?: Turn, preferVideo = false) => {
    if (!turn?.reply) return;
    openStage();
    if (videoId === turn.id && videoPlaying) {
      setVideoPlaying(false);
      return;
    }
    const state = video.videos[turn.id];
    const ready = state?.status === 'done' && videoUrl(state.result);
    if (audio.id === turn.id && audio.playing && !(preferVideo && ready)) {
      audio.toggle(turn.id, turn.reply, name);
      return;
    }
    if (ready) {
      audio.stop();
      setVideoId(turn.id);
      setVideoPlaying(true);
    } else {
      setVideoId('');
      setVideoPlaying(false);
      audio.toggle(turn.id, turn.reply, name);
    }
  };
  const stopPlayback = () => {
    audio.stop();
    setVideoId('');
    setVideoPlaying(false);
  };
  /** Whether this answer is the one being spoken, by voice or by video. */
  const speaking = (id: string) =>
    (audio.id === id && audio.playing) || (videoId === id && videoPlaying);
  return {
    audio,
    video,
    capabilities,
    videoId,
    setVideoId,
    videoPlaying,
    setVideoPlaying,
    currentTurn,
    toggleReply,
    stopPlayback,
    speaking,
  };
}

export type Playback = ReturnType<typeof usePlayback>;
