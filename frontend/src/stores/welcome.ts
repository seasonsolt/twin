import { create } from 'zustand';

/**
 * Where someone is on the way in (``#/welcome``): the two steps before the app, each of which can be passed. Held
 * for the whole visit, so passing one is not undone by leaving the page; signing out starts them over.
 */
export const useWelcome = create<{
  /** The voice step is over: they listened, or have no meeting to find themselves in. */
  voiceDone: boolean;
  /** The twin made for them is looked at: approved, handed back, or left for later. */
  claimDone: boolean;
  /** Where the way in leads once nothing is left on it. */
  after: string;
  /** Pass the voice step (or, with ``false``, take it up again). */
  finishVoice: (done?: boolean) => void;
  /** Pass the twin step, and say where to go on to: the page does not navigate itself, because the step leaves its
   * place the moment this is set. */
  finishClaim: (after?: string) => void;
  reset: () => void;
}>((set) => ({
  voiceDone: false,
  claimDone: false,
  after: '/',
  finishVoice: (done = true) => set({ voiceDone: done, after: '/' }),
  finishClaim: (after = '/') => set({ claimDone: true, after }),
  reset: () => set({ voiceDone: false, claimDone: false, after: '/' }),
}));
