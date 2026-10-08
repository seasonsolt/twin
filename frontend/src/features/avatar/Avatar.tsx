import { useEffect, useState } from 'react';
import { useMotionPreset } from '../../design/motion';
import { SpeakingGlow } from './SpeakingGlow';
import type { AvatarSpec } from './types';
import { PresetSvg } from './presets';

export function Avatar({
  spec,
  preset,
  mouthLevel = 0,
  blinking = true,
}: {
  spec?: AvatarSpec;
  preset?: string | null;
  mouthLevel?: number;
  blinking?: boolean;
}) {
  const { reduced } = useMotionPreset();
  const [blink, setBlink] = useState(false);
  useEffect(() => {
    setBlink(false);
    if (reduced || !blinking) return;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(
        () => {
          setBlink(true);
          timer = setTimeout(() => {
            setBlink(false);
            schedule();
          }, 140);
        },
        3000 + Math.random() * 3000,
      );
    };
    schedule();
    return () => clearTimeout(timer);
  }, [reduced, blinking]);
  const mouth = Number.isInteger(mouthLevel)
    ? Math.max(0, Math.min(reduced ? 1 : 3, mouthLevel))
    : 0;
  return (
    <div className="relative mx-auto aspect-square w-full shrink-0 overflow-hidden rounded-full">
      <PresetSvg
        preset={preset ?? spec?.avatar_id}
        mouth={mouth}
        blink={blink && !reduced && blinking}
      />
    </div>
  );
}

export function PortraitAvatar({
  url,
  mouthLevel,
  speaking,
  onError,
}: {
  url: string;
  mouthLevel: number;
  speaking: boolean;
  onError(): void;
}) {
  return (
    <div className="relative mx-auto w-full max-w-48 shrink-0">
      <SpeakingGlow level={mouthLevel} speaking={speaking} />
      <img
        src={url}
        alt="肖像形象"
        onError={onError}
        className="aspect-[11/12] w-full rounded-[22px] object-cover object-[50%_30%]"
      />
    </div>
  );
}
