import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { TeamAnswerCard } from '../answers/types';

/** Someone worth asking about a matter, and how well they know it. */
export interface Recommended {
  persona_id: string;
  name: string;
  /** 1 提到过, 2 了解一些, 3 了解较多. */
  level: number;
  label: string;
  /** On how many occasions it came up. */
  occasions: number;
  last_seen: string | null;
  /** The facets it falls in, at most two. */
  facets: string[];
}

/** A meeting the matter came up in: one line of it. */
export interface MeetingHit {
  recording_id: string;
  title: string;
  date: string;
  speaker: string;
  quote: string;
  start: number;
  /** Which line of the transcript it is, counting from 0. */
  line: number;
}

export interface Found {
  /** The question this is the answer to. */
  query: string;
  team_answers: TeamAnswerCard[];
  people: Recommended[];
  meetings: MeetingHit[];
  /** The question asks someone to decide, promise or judge: what they answer is theirs to give. */
  decision: boolean;
  /** Only the meetings could be searched: the embedding model is not at hand. */
  degraded: boolean;
}

/** A pause after the last key before the team is asked, so that typing does not ask it at every letter. */
export const ASK_AFTER_MS = 350;
const MIN_CHARS = 2;

/**
 * What the team makes of a question typed in the search: the answers it already has, whom to ask and the meetings it
 * came up in. Asked once the typing stops; a newer question drops the one still under way. `enabled` is false when
 * the question needs no asking (a name that is just found). The answer to the question before stays in `found` until
 * the next one arrives (`busy` says it is on its way), so that the list does not empty and fill at every pause.
 */
export function useAsk(query: string, enabled: boolean) {
  const [found, setFound] = useState<Found | null>(null);
  const [asking, setAsking] = useState('');
  const [error, setError] = useState('');
  const wanted = query.trim();
  const worth = enabled && wanted.length >= MIN_CHARS;
  useEffect(() => {
    if (!worth) {
      // Nothing is asked: what an earlier question found is not shown beside the next one.
      setFound(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setAsking(wanted);
      setError('');
      api<Omit<Found, 'query'>>(
        `/api/personas/ask?q=${encodeURIComponent(wanted)}`,
        { signal: controller.signal },
      )
        .then((result) => setFound({ ...result, query: wanted }))
        .catch((failure: unknown) => {
          if (controller.signal.aborted) return;
          setError(failure instanceof Error ? failure.message : '没能问成');
        })
        .finally(() => {
          if (!controller.signal.aborted) setAsking('');
        });
    }, ASK_AFTER_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [worth, wanted]);
  return {
    found: worth && !error ? found : null,
    busy: worth && (asking === wanted || found?.query !== wanted) && !error,
    error: worth ? error : '',
  };
}
