import { create } from 'zustand';

/**
 * Where someone is on the way in (``#/welcome``): the two steps before the app, each of which can be passed. Held
 * for the whole visit, so passing one is not undone by leaving the page; signing out starts them over.
 */
export const useWelcome = create<{
  /** The voice step is over: they listened, or have no meeting to find themselves in. */
  voiceDone: boolean;
  /** The voice step was asked for again by someone with a twin (``#/voice``, 回去再听一遍 on the twin step): it comes
   * before the twin step until passed, and has no empty twin to skip to. */
  again: boolean;
  /** The twin made for them is looked at: approved, handed back, or left for later. */
  claimDone: boolean;
  /** Where the way in leads once nothing is left on it. */
  after: string;
  /** Pass the voice step (or, with ``false``, take it up again). */
  finishVoice: (done?: boolean) => void;
  /** Hear the voices again, having a twin already. */
  hearAgain: () => void;
  /** Pass the twin step, and say where to go on to: the page does not navigate itself, because the step leaves its
   * place the moment this is set. */
  finishClaim: (after?: string) => void;
  reset: () => void;
}>((set) => ({
  voiceDone: false,
  again: false,
  claimDone: false,
  after: '/',
  finishVoice: (done = true) =>
    set({ voiceDone: done, again: false, after: '/' }),
  hearAgain: () => set({ voiceDone: false, again: true, after: '/' }),
  finishClaim: (after = '/') => set({ claimDone: true, after }),
  reset: () =>
    set({ voiceDone: false, again: false, claimDone: false, after: '/' }),
}));
