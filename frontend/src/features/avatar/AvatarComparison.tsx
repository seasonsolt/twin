import { useEffect, useState } from 'react';
import { Button } from '../../components/ui';
import { api } from '../../lib/api';
import { useMotionPreset } from '../../design/motion';
import { Avatar } from '../playback/Avatar';
import type { Capabilities } from '../playback/types';
import { AvatarPreview } from './AvatarPreview';

const DEMO_TRACK = [0, 1, 2, 3, 2, 1, 0, 0, 2, 3, 2, 1, 0, 1, 2, 1, 0];

export function AvatarComparison() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [error, setError] = useState(false);
  const [replay, setReplay] = useState(0);
  const [mouth, setMouth] = useState(0);
  const { reduced } = useMotionPreset();
  useEffect(() => {
    const controller = new AbortController();
    void api<Capabilities>('/api/media/capabilities', {
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted) setCapabilities(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    let position = 0;
    setMouth(0);
    if (reduced) return;
    const timer = setInterval(() => {
      position = (position + 1) % DEMO_TRACK.length;
      setMouth(DEMO_TRACK[position]);
    }, 160);
    return () => clearInterval(timer);
  }, [replay, reduced]);
  if (error) return <p role="alert">形象预览暂不可用。</p>;
  if (!capabilities?.avatar) return <p role="status">正在加载形象…</p>;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 items-start gap-4">
        <div>
          <h3 className="mb-2 text-sm text-secondary">2D</h3>
          <Avatar spec={capabilities.avatar} mouthLevel={mouth} />
        </div>
        <div>
          <h3 className="mb-2 text-sm text-secondary">3D</h3>
          <AvatarPreview
            capabilities={capabilities}
            mouth={mouth}
            speaking={!reduced}
          />
        </div>
      </div>
      {!capabilities.avatar_model && (
        <p className="text-xs text-secondary">
          未配置 VRM 模型，3D 预览回退为 2D。
        </p>
      )}
      <Button
        variant="secondary"
        onClick={() => setReplay((value) => value + 1)}
      >
        重播口型演示
      </Button>
    </div>
  );
}
