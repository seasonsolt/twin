import { useEffect, useState } from 'react';
import { useMotionPreset } from '../../design/motion';
import { SpeakingGlow } from './SpeakingGlow';
import type { AvatarSpec } from './types';

export function Avatar({
  spec,
  mouthLevel = 0,
  blinking = true,
}: {
  spec: AvatarSpec;
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
  const color = (key: string) =>
    /^#[0-9a-f]{6}$/i.test(spec.palette[key] ?? '')
      ? spec.palette[key]
      : '#777777';
  const mouth = Number.isInteger(mouthLevel)
    ? Math.max(0, Math.min(reduced ? 1 : 3, mouthLevel))
    : 0;
  return (
    <div className="relative mx-auto w-full max-w-48 shrink-0">
      <svg
        viewBox="0 0 220 240"
        role="img"
        aria-label="风格化插画"
        data-mouth-level={mouth}
      >
        <rect width="220" height="240" rx="22" fill={color('background')} />
        <path
          d="M25 240 Q25 164 110 164 Q195 164 195 240 Z"
          fill={color('outfit')}
        />
        <path
          d="M90 177 L110 204 L130 177"
          fill="none"
          stroke={color('accent')}
          strokeWidth="8"
        />
        <ellipse cx="110" cy="96" rx="68" ry="76" fill={color('hair')} />
        <rect
          x="94"
          y="142"
          width="32"
          height="38"
          rx="12"
          fill={color('skin')}
        />
        <ellipse cx="110" cy="106" rx="57" ry="64" fill={color('skin')} />
        <path
          d="M51 86 Q44 23 110 24 Q179 24 170 84 L139 61 L119 82 L93 57 Z"
          fill={color('hair')}
        />
        {[85, 135].map((cx) => (
          <ellipse
            key={cx}
            data-eye=""
            cx={cx}
            cy="103"
            rx="5"
            ry={blink && !reduced && blinking ? 1 : 7}
            fill={color('hair')}
          />
        ))}
        <path
          d="M105 119 Q110 126 115 119"
          fill="none"
          stroke={color('accent')}
          strokeWidth="3"
        />
        <path
          visibility={mouth === 0 ? 'visible' : 'hidden'}
          d="M96 138 Q110 143 124 138"
          fill="none"
          stroke={color('hair')}
          strokeWidth="3"
        />
        {[1, 2, 3].map((level) => (
          <ellipse
            key={level}
            visibility={mouth === level ? 'visible' : 'hidden'}
            cx="110"
            cy={[140, 141, 143][level - 1]}
            rx={11 + level}
            ry={[3, 7, 12][level - 1]}
            fill={color('hair')}
          />
        ))}
      </svg>
      <p
        role="note"
        className="absolute inset-x-2 bottom-2 rounded-md border border-border bg-canvas px-2 py-1 text-center text-xs text-secondary"
      >
        {spec.label}
      </p>
    </div>
  );
}

export function PortraitAvatar({
  url,
  mouthLevel,
  speaking,
  label,
  onError,
}: {
  url: string;
  mouthLevel: number;
  speaking: boolean;
  label: string;
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
      <p
        role="note"
        className="absolute inset-x-2 bottom-2 rounded-md border border-border bg-canvas px-2 py-1 text-center text-xs text-secondary"
      >
        {label}
      </p>
    </div>
  );
}
