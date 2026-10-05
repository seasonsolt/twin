import { api } from "./api.js";

const listeners = new Set();

export const state = {
  status: null,
  statusError: null,
};

export async function refreshStatus() {
  try {
    state.status = await api("/api/status");
    state.statusError = null;
  } catch (err) {
    state.statusError = err;
  }
  for (const listener of listeners) listener(state);
  return state.status;
}

export function onStatus(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function targetName() {
  return state.status?.target_name || "目标人物";
}

export function createScope() {
  const timers = new Set();
  const cleanups = [];
  const scope = {
    alive: true,
    timeout(fn, ms) {
      const id = window.setTimeout(() => {
        timers.delete(id);
        if (scope.alive) fn();
      }, ms);
      timers.add(id);
      return id;
    },
    onDispose(fn) {
      cleanups.push(fn);
    },
    dispose() {
      scope.alive = false;
      for (const id of timers) window.clearTimeout(id);
      timers.clear();
      for (const fn of cleanups.splice(0)) fn();
    },
  };
  return scope;
}
