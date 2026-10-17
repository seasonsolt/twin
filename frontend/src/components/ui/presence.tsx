import { useEffect } from 'react';
import {
  animate,
  motion,
  useMotionValue,
  useTransform,
  type AnimationPlaybackControls,
  type MotionStyle,
  type MotionValue,
} from 'motion/react';
import { springs, useMotionPreset } from '../../design/motion';
import { cn } from '../../lib/utils';

/** What the twin is doing, so the user can tell at a glance: idle, listening, thinking or speaking. */
export type PresenceState = 'idle' | 'listening' | 'thinking' | 'speaking';

export const presenceLabels: Record<Exclude<PresenceState, 'idle'>, string> = {
  listening: '正在听',
  thinking: '正在思考',
  speaking: '正在说话',
};

export interface Presence {
  state: PresenceState;
  /** The voice level, 0 to 3. */
  level: number;
  /** 0 to 1: how strongly the twin shows itself now. Follows the voice when speaking, drifts when thinking. */
  intensity: MotionValue<number>;
  reduced: boolean;
}

// While thinking, the ring drifts between these, each move easing over the whole wait before the next: slow, and
// never on a beat a viewer could count.
const DRIFT = { low: 0.12, high: 0.38, minMs: 1200, maxMs: 2600 };

/** The twin's presence as one animated value, shared by the ring and anything that breathes with it. */
export function usePresence(state: PresenceState, level = 0): Presence {
  const { reduced } = useMotionPreset();
  const bounded = Number.isFinite(level) ? Math.max(0, Math.min(3, level)) : 0;
  const intensity = useMotionValue(0);
  useEffect(() => {
    if (reduced) {
      intensity.jump(0);
      return;
    }
    let controls: AnimationPlaybackControls;
    if (state !== 'thinking') {
      // A spring carries the current velocity, so a new voice level never jolts the ring.
      controls = animate(
        intensity,
        state === 'speaking'
          ? 0.25 + (bounded / 3) * 0.75
          : state === 'listening'
            ? 0.35 + (bounded / 3) * 0.3
            : 0,
        springs.gentle,
      );
      return () => controls.stop();
    }
    let timer: ReturnType<typeof setTimeout>;
    const drift = () => {
      const ms = DRIFT.minMs + Math.random() * (DRIFT.maxMs - DRIFT.minMs);
      controls = animate(
        intensity,
        DRIFT.low + Math.random() * (DRIFT.high - DRIFT.low),
        { duration: ms / 1000, ease: 'easeInOut' },
      );
      timer = setTimeout(drift, ms);
    };
    drift();
    return () => {
      clearTimeout(timer);
      controls.stop();
    };
  }, [intensity, state, bounded, reduced]);
  return { state, level: bounded, intensity, reduced };
}

/**
 * The ring around the twin's portrait that shows its state. glow: an accent frame, for a portrait on the page.
 * ripple: rings in the ground colour spreading outwards while it speaks, for the portrait on the coloured chat stage.
 * With reduced motion nothing moves: glow becomes a small dot that names the state; ripple leaves the stage to say it.
 */
export function PresenceRing({
  presence,
  variant = 'glow',
  shape = 'circle',
}: {
  presence: Presence;
  variant?: 'glow' | 'ripple';
  /** circle: a round portrait. card: a portrait photo with rounded corners. */
  shape?: 'circle' | 'card';
}) {
  const { state, level, intensity, reduced } = presence;
  const expansion = useTransform(intensity, (value) => 1.08 + value * 0.16);
  const ringOpacity = useTransform(intensity, (value) => 0.3 + value * 0.45);
  // A glow on a light page reads stronger than rings on the stage: above the speaking floor it rises more gently.
  const glowOpacity = useTransform(intensity, (value) =>
    value <= 0.25 ? value : 0.25 + (value - 0.25) * (0.65 / 0.75),
  );
  const radius = shape === 'circle' ? 'rounded-full' : 'rounded-[22px]';
  if (reduced) {
    if (variant === 'ripple' || state === 'idle') return null;
    return (
      <span
        role="status"
        aria-label={presenceLabels[state]}
        className="absolute top-0 right-0 size-2 rounded-full bg-accent"
      />
    );
  }
  if (variant === 'glow')
    return (
      <motion.span
        aria-hidden
        data-portrait-glow=""
        data-presence={state}
        data-glow-level={state === 'speaking' ? level : 0}
        style={{ opacity: glowOpacity }}
        className={cn(
          'pointer-events-none absolute inset-0 border-2 border-accent shadow-[0_0_20px_4px_var(--color-accent)]',
          radius,
        )}
      />
    );
  if (state === 'idle') return null;
  return (
    <motion.span
      aria-hidden
      data-presence={state}
      className="pointer-events-none absolute inset-0"
      style={
        {
          '--ring-expansion': expansion,
          '--ring-opacity': ringOpacity,
        } as MotionStyle
      }
    >
      {(state === 'speaking' ? [0, 1] : [0]).map((ring) => (
        <span
          key={ring}
          className={cn('presence-ripple', radius)}
          // Listening and thinking hold one still ring whose strength drifts; only speech spreads outwards.
          data-still={state === 'speaking' ? undefined : ''}
        />
      ))}
    </motion.span>
  );
}

/** "思考中…" while the twin works on an answer: one soft sheen passing over the words now and then, or still words
 * with reduced motion. */
export function TypingIndicator({ text = '思考中…' }: { text?: string }) {
  return (
    <span role="status" className="typing-indicator text-sm text-secondary">
      {text}
    </span>
  );
}

/** Words for the reveal: Chinese words through Intl.Segmenter, else single CJK characters and Latin runs. */
export function segmentText(text: string): string[] {
  const Segmenter = (
    Intl as typeof Intl & {
      Segmenter?: new (
        locale?: string,
        options?: { granularity: 'word' },
      ) => { segment: (text: string) => Iterable<{ segment: string }> };
    }
  ).Segmenter;
  if (Segmenter)
    return Array.from(
      new Segmenter(undefined, { granularity: 'word' }).segment(text),
      (unit) => unit.segment,
    );
  return (
    text.match(
      /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]|\s+|[^\s\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]+/gu,
    ) ?? []
  );
}

const UNIT_S = 0.16;
const TOTAL_S = 1.2;
// Longer than this, the text is read rather than watched: show it whole at once.
const MAX_UNITS = 160;

/** Delay between words, so the whole text has appeared within TOTAL_S. */
export function streamUnitDelay(count: number) {
  return Math.min(0.025, (TOTAL_S - UNIT_S) / Math.max(1, count - 1));
}

/**
 * Text that settles into view word by word: opacity and a slight blur only, no movement, each word within 200 ms.
 * Screen readers get the whole text once. Long text and reduced motion show it whole at once.
 */
export function StreamText({ text }: { text: string }) {
  const { reduced } = useMotionPreset();
  const units = reduced ? [] : segmentText(text);
  if (reduced || units.length > MAX_UNITS) return <span>{text}</span>;
  return (
    <span>
      <span className="sr-only">{text}</span>
      <span aria-hidden="true" data-stream-text="">
        {units.map((unit, index) => (
          <motion.span
            key={index}
            data-stream-unit=""
            className="inline-block whitespace-pre-wrap"
            initial={{ filter: 'blur(3px)', opacity: 0 }}
            animate={{ filter: 'blur(0px)', opacity: 1 }}
            transition={{
              duration: UNIT_S,
              delay: index * streamUnitDelay(units.length),
            }}
          >
            {unit}
          </motion.span>
        ))}
      </span>
    </span>
  );
}
