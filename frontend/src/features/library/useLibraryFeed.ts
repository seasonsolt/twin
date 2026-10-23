import { useCallback, useEffect } from 'react';
import { useTeam } from '../../stores/team';

/**
 * The library the side bar also counts from, for a page that lists people or the review queue. ``version`` moves
 * when a recording changes in a way people and the review queue follow (a transcript arriving, speakers settled, one
 * removed), not on every poll: while recordings wait, a page polls every few seconds, and the review queue is the
 * heaviest view the server computes. The page loads people and the queue itself (``useTeamData``): the side bar takes
 * them from there rather than asking twice.
 */
export function useLibraryFeed() {
  const library = useTeam((state) => state.library);
  const error = useTeam((state) => state.error);
  const version = useTeam((state) => state.version);
  const load = useCallback(() => useTeam.getState().refresh(true), []);
  const poll = useCallback(() => useTeam.getState().refresh(), []);
  useEffect(() => {
    const detach = useTeam.getState().attach();
    void load();
    return detach;
  }, [load]);
  return { library, error, version, load, poll };
}
