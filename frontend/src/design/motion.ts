import { useReducedMotion, type Transition } from 'motion/react';

export const springs = {
  snappy: { type: 'spring', stiffness: 520, damping: 38 },
  gentle: { type: 'spring', stiffness: 260, damping: 30 },
  bouncy: { type: 'spring', stiffness: 380, damping: 18 },
  layout: { type: 'spring', stiffness: 420, damping: 40 },
} satisfies Record<string, Transition>;

export const exitDurations = { quick: 0.12, page: 0.16, dialog: 0.18 };
export const crossfade: Transition = {
  type: 'tween',
  duration: 0.15,
  ease: 'easeOut',
};

export function useMotionPreset(name: keyof typeof springs = 'snappy') {
  const reduced = useReducedMotion() === true;
  return {
    reduced,
    transition: reduced ? crossfade : springs[name],
    exit: { ...crossfade, duration: exitDurations.quick },
  };
}
