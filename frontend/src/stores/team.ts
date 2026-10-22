import { create } from 'zustand';
import { api } from '../lib/api';
import type { LibraryState, Recording } from '../pages/Library';
import type { Person } from '../pages/Recording';
import type { ReviewLists } from '../features/library/teamCounts';

/** What, in the recordings, people and the review queue follow: a transcript arriving, speakers settled, one
 * removed. Not progress, which moves on every poll while recordings wait. */
export const recordingsKey = (recordings: Recording[]) =>
  JSON.stringify(
    recordings.map((r) => [
      r.id,
      r.status,
      r.speakers,
      r.unsettled,
      r.people,
      r.previous ?? null,
    ]),
  );

interface Team {
  library: LibraryState | null;
  error: string;
  /** Bumped when the recordings change in a way people and the review queue follow. */
  version: number;
  people: Person[] | null;
  review: ReviewLists | null;
  /** The team page is open and loads people and the review queue itself (handing them over with `absorb`). */
  pages: number;
  /**
   * Load the library; on a change people and the review queue follow, them too unless the team page will. Polls
   * close together share one request; `fresh` asks again even so, after something was changed.
   */
  refresh: (fresh?: boolean) => Promise<void>;
  absorb: (change: { people?: Person[]; review?: ReviewLists }) => void;
  /** Mark the team page open; the function returned marks it closed. */
  attach: () => () => void;
}

let inflight: Promise<void> | null = null;
let lastLoad = 0;
let seen = '';
// Two callers polling at once (the side bar and the team page) share one request.
const MIN_GAP_MS = 1500;

/** The library as the whole app sees it: what the side bar counts, and what the team page lists. The review queue
 * is the heaviest view the server computes, so it is asked for only when the recordings change. */
export const useTeam = create<Team>((set, get) => {
  const follow = async () => {
    const [people, review] = await Promise.all([
      api<{ items: Person[] }>('/api/library/people').then((r) => r.items),
      api<ReviewLists>('/api/library/review'),
    ]);
    set({ people, review });
  };
  const load = async () => {
    try {
      const library = await api<LibraryState>('/api/library');
      const key = recordingsKey(library.recordings);
      const changed = key !== seen;
      seen = key;
      set((state) => ({
        library,
        error: '',
        version: changed ? state.version + 1 : state.version,
      }));
      if (changed && !get().pages) await follow().catch(() => {});
    } catch (failure) {
      set({
        error: failure instanceof Error ? failure.message : '无法加载录音',
      });
    }
  };
  return {
    library: null,
    error: '',
    version: 0,
    people: null,
    review: null,
    pages: 0,
    refresh: (fresh = false) => {
      if (inflight && !fresh) return inflight;
      if (!fresh && Date.now() - lastLoad < MIN_GAP_MS && get().library)
        return Promise.resolve();
      // A load already under way may have left before the change: this one starts after it.
      const after = inflight ?? Promise.resolve();
      const next = after.then(load).finally(() => {
        if (inflight === next) inflight = null;
        lastLoad = Date.now();
      });
      inflight = next;
      return next;
    },
    absorb: (change) => set(change),
    attach: () => {
      set((state) => ({ pages: state.pages + 1 }));
      return () => {
        set((state) => ({ pages: state.pages - 1 }));
        // Left before the page listed anyone (it had no recordings yet): the side bar still needs its counts.
        if (!get().pages && !get().people) void follow().catch(() => {});
      };
    },
  };
});

/** Back to nothing loaded, as on a fresh load (tests start each case from here). */
export function resetTeam() {
  inflight = null;
  lastLoad = 0;
  seen = '';
  useTeam.setState({
    library: null,
    error: '',
    version: 0,
    people: null,
    review: null,
    pages: 0,
  });
}
