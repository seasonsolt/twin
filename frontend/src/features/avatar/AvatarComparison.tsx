import { useEffect, useState } from 'react';
import { Button, Row, Select, type PresenceState } from '../../components/ui';
import { api } from '../../lib/api';
import { useMotionPreset } from '../../design/motion';
import { Avatar } from './Avatar';
import type { Capabilities } from './types';
import { AvatarPreview } from './AvatarPreview';

const DEMO_TRACK = [0, 1, 2, 3, 2, 1, 0, 0, 2, 3, 2, 1, 0, 1, 2, 1, 0];

// What each state looks like on a VRM: listening leans in and holds the eyes, thinking looks away now and then.
const STATES: { value: PresenceState; label: string }[] = [
  { value: 'speaking', label: '说话：口型演示' },
  { value: 'listening', label: '倾听：注视并微微前倾' },
  { value: 'thinking', label: '思考：不时移开视线' },
  { value: 'idle', label: '待机' },
];

export function AvatarComparison() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [error, setError] = useState(false);
  const [replay, setReplay] = useState(0);
  const [mouth, setMouth] = useState(0);
  const [state, setState] = useState<PresenceState>('speaking');
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
    if (reduced || state !== 'speaking') return;
    const timer = setInterval(() => {
      position = (position + 1) % DEMO_TRACK.length;
      setMouth(DEMO_TRACK[position]);
    }, 160);
    return () => clearInterval(timer);
  }, [replay, reduced, state]);
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
            speaking={!reduced && state === 'speaking'}
            state={state}
          />
        </div>
      </div>
      {!capabilities.avatar_model && (
        <p className="text-xs text-secondary">
          未配置 VRM 模型，3D 预览回退为 2D。
        </p>
      )}
      <Row gap={3} wrap>
        <Select
          aria-label="3D 形象状态"
          value={state}
          onChange={(event) => setState(event.target.value as PresenceState)}
        >
          {STATES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        <Button
          variant="secondary"
          disabled={state !== 'speaking'}
          onClick={() => setReplay((value) => value + 1)}
        >
          重播口型演示
        </Button>
      </Row>
    </div>
  );
}
