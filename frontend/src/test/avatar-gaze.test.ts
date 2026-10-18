import { expect, it } from 'vitest';
import {
  AvatarMotion,
  BlinkScheduler,
  GazeAversion,
} from '../features/avatar/motion';
import type { PresenceState } from '../components/ui';

/** A repeatable stand-in for Math.random. */
function seeded(seed = 7) {
  let value = seed;
  return () => {
    value = (value * 16807) % 2147483647;
    return (value - 1) / 2147483646;
  };
}

const FRAME = 1 / 60;

function run(frames: number, step: (time: number) => void, start = 0): number {
  let time = start;
  for (let i = 0; i < frames; i++) {
    time += FRAME;
    step(time);
  }
  return time;
}

it('blinks every 2 to 6 seconds at no steady rhythm, now and then twice', () => {
  const blink = new BlinkScheduler(seeded(3));
  const starts: number[] = [];
  let doubles = 0;
  let closed = false;
  let lastStart = -Infinity;
  run(60 * 600, (time) => {
    const shut = blink.step(time, false) > 0.5;
    if (shut && !closed) {
      // A second closing within 0.4 s of the first is the double blink, not a new one.
      if (time - lastStart < 0.45) doubles++;
      else {
        starts.push(time);
        lastStart = time;
      }
    }
    closed = shut;
  });
  const gaps = starts.slice(1).map((time, index) => time - starts[index]);
  expect(Math.min(...gaps)).toBeGreaterThanOrEqual(2);
  expect(Math.max(...gaps)).toBeLessThanOrEqual(6.5);
  expect(new Set(gaps.map((gap) => gap.toFixed(1))).size).toBeGreaterThan(10);
  expect(doubles).toBeGreaterThan(0);
  expect(doubles).toBeLessThan(starts.length * 0.35);
});

it('looks away up or to the side for 1 to 2 seconds while thinking, then drifts back, never on a beat', () => {
  const gaze = new GazeAversion(seeded(11));
  const holds: number[] = [];
  const drifts: number[] = [];
  const rests: number[] = [];
  let phase = gaze.state;
  let since = 0;
  let maxDown = 0;
  let maxAway = 0;
  run(60 * 120, (time) => {
    const shift = gaze.step(time, true);
    maxDown = Math.min(maxDown, shift.y);
    maxAway = Math.max(maxAway, Math.hypot(shift.x, shift.y));
    if (gaze.state !== phase) {
      if (phase === 'away') holds.push(time - since);
      if (phase === 'back') drifts.push(time - since);
      if (phase === 'rest' && since > 0) rests.push(time - since);
      phase = gaze.state;
      since = time;
    }
  });
  expect(holds.length).toBeGreaterThan(10);
  for (const hold of holds) {
    expect(hold).toBeGreaterThanOrEqual(1);
    expect(hold).toBeLessThanOrEqual(2 + FRAME);
  }
  // The way back is a slow drift, slower than the glance away.
  for (const drift of drifts) expect(drift).toBeGreaterThanOrEqual(0.9);
  // Up or to the side, never down at the floor.
  expect(maxDown).toBeGreaterThanOrEqual(0);
  expect(maxAway).toBeGreaterThan(0.1);
  // No fixed period: the cycles all differ in length.
  const cycles = holds.map(
    (hold, index) => hold + (drifts[index] ?? 0) + (rests[index] ?? 0),
  );
  expect(new Set(cycles.map((cycle) => cycle.toFixed(2))).size).toBe(
    cycles.length,
  );
});

it('starts looking away soon after thinking begins and comes back promptly when it ends', () => {
  const gaze = new GazeAversion(seeded(5));
  expect(gaze.step(0, false)).toEqual({ x: 0, y: 0, pitch: 0, yaw: 0 });
  let time = run(60, (now) => gaze.step(now, true));
  expect(gaze.state).toBe('away');
  time = run(6, (now) => gaze.step(now, true), time);
  const away = gaze.step(time, true);
  expect(Math.hypot(away.x, away.y)).toBeGreaterThan(0.1);
  // The answer starts: back to the viewer within 0.4 s, and no new glance while idle.
  time = run(25, (now) => gaze.step(now, false), time);
  expect(gaze.step(time, false)).toEqual({ x: 0, y: 0, pitch: 0, yaw: 0 });
  run(
    60 * 10,
    (now) => {
      expect(gaze.step(now, false).x).toBe(0);
    },
    time,
  );
});

function settle(motion: AvatarMotion, state: PresenceState, reduced = false) {
  let pose = motion.step(FRAME, 0, state, reduced);
  for (let i = 0; i < 180; i++) pose = motion.step(FRAME, 0, state, reduced);
  return pose;
}

it('keeps the eyes on the viewer and leans in a little while listening', () => {
  const motion = new AvatarMotion(seeded(2));
  expect(settle(motion, 'idle').lean).toBeCloseTo(0);
  let widest = 0;
  let pose = settle(motion, 'listening');
  for (let i = 0; i < 600; i++) {
    pose = motion.step(FRAME, 0, 'listening', false);
    widest = Math.max(widest, Math.abs(pose.gaze.x), Math.abs(pose.gaze.y));
  }
  expect(pose.lean).toBeCloseTo(0.05, 2);
  // Only tiny saccades, a third of the idle wander, and the head tips back so the face stays level.
  expect(widest).toBeLessThanOrEqual(0.035 * 0.3 * 0.5 + 1e-9);
  expect(pose.pitch).toBeLessThan(0);
  expect(settle(motion, 'idle').lean).toBeLessThan(0.01);
});

it('turns the eyes and head away while thinking, and keeps only the blink under reduced motion', () => {
  const motion = new AvatarMotion(seeded(9));
  let furthest = 0;
  let turned = 0;
  for (let i = 0; i < 60 * 8; i++) {
    const pose = motion.step(FRAME, 0, 'thinking', false);
    furthest = Math.max(furthest, Math.hypot(pose.gaze.x, pose.gaze.y));
    turned = Math.max(turned, Math.abs(pose.yaw) + Math.abs(pose.pitch));
  }
  expect(furthest).toBeGreaterThan(0.1);
  expect(turned).toBeGreaterThan(0.03);
  const reduced = new AvatarMotion(seeded(9));
  let blinked = false;
  for (const state of ['idle', 'listening', 'thinking', 'speaking'] as const)
    for (let i = 0; i < 60 * 8; i++) {
      const pose = reduced.step(FRAME, 0, state, true);
      expect(pose).toMatchObject({
        lean: 0,
        pitch: 0,
        yaw: 0,
        breath: 0,
        gaze: { x: 0, y: 0 },
      });
      blinked ||= pose.blink > 0;
    }
  expect(blinked).toBe(true);
});
