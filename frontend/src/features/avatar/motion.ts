import type { PresenceState } from '../../components/ui';

export const MOUTH_WEIGHTS = [0, 0.35, 0.65, 1] as const;

export function mouthWeight(
  level: number,
  speaking: boolean,
  reduced: boolean,
) {
  if (!speaking || !Number.isFinite(level)) return 0;
  return MOUTH_WEIGHTS[
    Math.max(0, Math.min(reduced ? 1 : 3, Math.round(level)))
  ];
}

export class DampedSpring {
  value = 0;
  velocity = 0;
  constructor(private readonly frequency = 24) {}
  step(target: number, delta: number) {
    const dt = Math.max(0, Math.min(delta, 0.05));
    const offset = this.value - target;
    const impulse = this.velocity + this.frequency * offset;
    const decay = Math.exp(-this.frequency * dt);
    this.value = target + (offset + impulse * dt) * decay;
    this.velocity = (this.velocity - this.frequency * impulse * dt) * decay;
    return this.value;
  }
}

export class BlinkScheduler {
  private next = 0;
  private start: number | null = null;
  private double = false;
  constructor(
    private readonly random = Math.random,
    private reduced = false,
  ) {
    this.schedule(0);
  }
  // People blink every 2 to 6 seconds, at no steady rhythm. Reduced motion keeps rare single blinks only.
  private schedule(time: number) {
    this.next =
      time + (this.reduced ? 8 + this.random() * 6 : 2 + this.random() * 4);
  }
  step(time: number, reduced: boolean) {
    if (reduced !== this.reduced) {
      this.reduced = reduced;
      this.start = null;
      this.double = false;
      this.schedule(time);
    }
    if (this.start === null && time >= this.next) {
      this.start = time;
      this.double = !reduced && this.random() < 0.15;
    }
    if (this.start === null) return 0;
    const elapsed = time - this.start;
    if (elapsed < 0.16) return Math.sin((elapsed / 0.16) * Math.PI);
    if (this.double && elapsed < 0.4) {
      return elapsed < 0.24 ? 0 : Math.sin(((elapsed - 0.24) / 0.16) * Math.PI);
    }
    this.start = null;
    this.schedule(time);
    return 0;
  }
}

/** Where the eyes go, as a fraction of the model's height from the viewer, and how far the head follows. */
export interface GazeShift {
  x: number;
  y: number;
  pitch: number;
  yaw: number;
}

const AVERSIONS = [
  { x: 0, y: 1 },
  { x: 0.7, y: 0.7 },
  { x: -0.7, y: 0.7 },
  { x: 1, y: 0.15 },
  { x: -1, y: 0.15 },
] as const;

const smoothstep = (value: number) => {
  const t = Math.max(0, Math.min(1, value));
  return t * t * (3 - 2 * t);
};

/**
 * While thinking, look away up or to the side for 1 to 2 seconds, then drift slowly back to the viewer, as people do
 * when they work something out (Andrist et al., IVA 2013 and HRI 2014: cognitive gaze aversion). Every wait and hold
 * is drawn afresh, so the looks never fall on a beat. Once thinking ends the eyes come back promptly.
 */
export class GazeAversion {
  private phase: 'rest' | 'away' | 'back' = 'rest';
  private thinking = false;
  private at = 0;
  private until = Infinity;
  private from = 0;
  private weight = 0;
  private direction: { x: number; y: number } = AVERSIONS[0];
  constructor(private readonly random = Math.random) {}
  /** rest: on the viewer. away: looking off. back: drifting back. */
  get state() {
    return this.phase;
  }
  step(time: number, thinking: boolean): GazeShift {
    if (thinking && !this.thinking && this.phase === 'rest')
      this.until = time + 0.2 + this.random() * 0.5;
    if (!thinking && this.thinking && this.phase !== 'rest')
      this.drift(time, 0.4);
    this.thinking = thinking;
    if (this.phase === 'rest' && thinking && time >= this.until) {
      this.direction =
        AVERSIONS[
          Math.floor(this.random() * AVERSIONS.length) % AVERSIONS.length
        ];
      this.phase = 'away';
      this.at = time;
      this.from = this.weight;
      this.until = time + 1 + this.random();
    } else if (this.phase === 'away' && time >= this.until) {
      this.drift(time, 0.9 + this.random() * 0.9);
    } else if (this.phase === 'back' && time >= this.until) {
      this.phase = 'rest';
      this.until = thinking ? time + 1.2 + this.random() * 2.8 : Infinity;
    }
    if (this.phase === 'away')
      this.weight =
        this.from + (1 - this.from) * smoothstep((time - this.at) / 0.2);
    else if (this.phase === 'back')
      this.weight =
        this.from * (1 - smoothstep((time - this.at) / (this.until - this.at)));
    else this.weight = 0;
    if (this.weight === 0) return { x: 0, y: 0, pitch: 0, yaw: 0 };
    const { x, y } = this.direction;
    return {
      x: x * this.weight * 0.2,
      y: y * this.weight * 0.16,
      pitch: -y * this.weight * 0.05,
      yaw: x * this.weight * 0.08,
    };
  }
  private drift(time: number, seconds: number) {
    this.phase = 'back';
    this.at = time;
    this.from = this.weight;
    this.until = time + seconds;
  }
}

export class AvatarMotion {
  private mouth = new DampedSpring();
  private pitch = new DampedSpring(10);
  private yaw = new DampedSpring(10);
  private lean = new DampedSpring(4);
  private blink: BlinkScheduler;
  private aversion: GazeAversion;
  private time = 0;
  private nextSaccade = 0;
  private gaze = { x: 0, y: 0 };
  constructor(private readonly random = Math.random) {
    this.blink = new BlinkScheduler(random);
    this.aversion = new GazeAversion(random);
  }
  /** One frame of the avatar's pose. Reduced motion keeps the blink and the mouth only. */
  step(delta: number, level: number, state: PresenceState, reduced: boolean) {
    this.time += delta;
    const t = this.time;
    const speaking = state === 'speaking';
    // Listening holds the viewer's eyes: only tiny saccades. Thinking replaces them with looking away.
    const wander = state === 'listening' ? 0.3 : state === 'thinking' ? 0 : 1;
    if (!reduced && t >= this.nextSaccade) {
      this.gaze = {
        x: (this.random() - 0.5) * 0.035 * wander,
        y: (this.random() - 0.5) * 0.025 * wander,
      };
      this.nextSaccade = t + 0.7 + this.random() * 1.5;
    }
    const away = this.aversion.step(t, !reduced && state === 'thinking');
    const aa = Math.max(
      0,
      Math.min(
        reduced ? MOUTH_WEIGHTS[1] : 1,
        this.mouth.step(mouthWeight(level, speaking, reduced), delta),
      ),
    );
    const variety = (Math.sin(t * 8) + 1) / 2;
    // Listening leans the chest a little towards the viewer; the head tips back as much so the face stays level.
    const lean = reduced
      ? 0
      : this.lean.step(state === 'listening' ? 0.05 : 0, delta);
    return {
      aa,
      oh: reduced ? 0 : aa * variety * 0.12,
      ih: reduced ? 0 : aa * (1 - variety) * 0.1,
      blink: this.blink.step(t, reduced),
      breath: reduced ? 0 : Math.sin(t * Math.PI * 0.8) * 0.008,
      lean,
      pitch: reduced
        ? 0
        : this.pitch.step(
            Math.sin(t * 0.73) * 0.018 +
              (speaking ? Math.sin(t * 3.4) * 0.025 : 0) +
              away.pitch -
              lean * 0.6,
            delta,
          ),
      yaw: reduced
        ? 0
        : this.yaw.step(Math.sin(t * 0.51) * 0.025 + away.yaw, delta),
      gaze: reduced
        ? { x: 0, y: 0 }
        : { x: this.gaze.x + away.x, y: this.gaze.y + away.y },
    };
  }
}
