import { useEffect } from 'react';
import { motion, useSpring } from 'motion/react';
import { springs, useMotionPreset } from '../../design/motion';

export function SpeakingGlow({
  level,
  speaking,
  round = false,
}: {
  level: number;
  speaking: boolean;
  round?: boolean;
}) {
  const { reduced } = useMotionPreset();
  const bounded = Number.isFinite(level) ? Math.max(0, Math.min(3, level)) : 0;
  const intensity = speaking && !reduced ? 0.25 + (bounded / 3) * 0.65 : 0;
  const glow = useSpring(0, springs.gentle);
  useEffect(() => {
    if (reduced) glow.jump(0);
    else glow.set(intensity);
  }, [glow, intensity, reduced]);
  if (reduced)
    return speaking ? (
      <span
        role="status"
        aria-label="正在说话"
        className="absolute top-0 right-0 size-2 rounded-full bg-accent"
      />
    ) : null;
  return (
    <motion.span
      aria-hidden
      data-portrait-glow=""
      data-glow-level={speaking ? bounded : 0}
      style={{ opacity: glow }}
      className={`pointer-events-none absolute inset-0 border-2 border-accent shadow-[0_0_20px_4px_var(--color-accent)] ${round ? 'rounded-full' : 'rounded-[22px]'}`}
    />
  );
}
