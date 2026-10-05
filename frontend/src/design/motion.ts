import { useReducedMotion, type Transition } from 'motion/react';
import { useEffect, useState } from 'react';

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
  const initialReduced = useReducedMotion() === true;
  const [override, setOverride] = useState<boolean | null>(null);
  useEffect(() => {
    // Motion caches the initial preference; playback must also stop on live changes.
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const change = (event: MediaQueryListEvent) => setOverride(event.matches);
    preference.addEventListener('change', change);
    return () => preference.removeEventListener('change', change);
  }, []);
  const reduced = override ?? initialReduced;
  return {
    reduced,
    transition: reduced ? crossfade : springs[name],
    exit: { ...crossfade, duration: exitDurations.quick },
  };
}
