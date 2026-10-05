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
  private schedule(time: number) {
    this.next =
      time + (this.reduced ? 8 + this.random() * 6 : 2.5 + this.random() * 3.5);
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

export class AvatarMotion {
  private mouth = new DampedSpring();
  private pitch = new DampedSpring(10);
  private yaw = new DampedSpring(10);
  private blink = new BlinkScheduler();
  private time = 0;
  private nextSaccade = 0;
  private gaze = { x: 0, y: 0 };
  step(delta: number, level: number, speaking: boolean, reduced: boolean) {
    this.time += delta;
    const t = this.time;
    if (!reduced && t >= this.nextSaccade) {
      this.gaze = {
        x: (Math.random() - 0.5) * 0.035,
        y: (Math.random() - 0.5) * 0.025,
      };
      this.nextSaccade = t + 0.7 + Math.random() * 1.5;
    }
    const aa = Math.max(
      0,
      Math.min(
        reduced ? MOUTH_WEIGHTS[1] : 1,
        this.mouth.step(mouthWeight(level, speaking, reduced), delta),
      ),
    );
    const variety = (Math.sin(t * 8) + 1) / 2;
    return {
      aa,
      oh: reduced ? 0 : aa * variety * 0.12,
      ih: reduced ? 0 : aa * (1 - variety) * 0.1,
      blink: this.blink.step(t, reduced),
      breath: reduced ? 0 : Math.sin(t * Math.PI * 0.8) * 0.008,
      pitch: reduced
        ? 0
        : this.pitch.step(
            Math.sin(t * 0.73) * 0.018 +
              (speaking ? Math.sin(t * 3.4) * 0.025 : 0),
            delta,
          ),
      yaw: reduced ? 0 : this.yaw.step(Math.sin(t * 0.51) * 0.025, delta),
      gaze: reduced ? { x: 0, y: 0 } : this.gaze,
    };
  }
}
