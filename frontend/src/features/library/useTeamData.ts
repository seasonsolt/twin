import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { usePolling } from '../../lib/usePolling';
import { toast } from '../../components/ui';
import type { Recording } from '../../pages/Library';
import type { Person, TwinMatch } from '../../pages/Recording';
import { usePersonas } from '../../stores/personas';
import { useTeam } from '../../stores/team';
import type { SuspectSpeaker } from './MixedSpeaker';
import { reviewPath, type Paged } from './teamCounts';
import type {
  Fragment,
  Review,
  Unsorted,
  VoiceDecision,
  VoiceMember,
  Voice,
  Waiting,
} from './review';

/**
 * What the team page's roster and the inbox of things to settle both stand on: the people and the review queue
 * loaded together, and the actions that change them. Anything done goes through ``act``, which marks the page busy,
 * shows what went wrong and loads both again.
 *
 * ``version`` moves when a recording changes in a way people and the review queue follow (a transcript arriving,
 * speakers settled, one removed); ``onReload`` asks the page's library to load again after a recording changed.
 * ``first`` is how many of each paged list of the queue the page shows (none by default: only how many there are).
 */
export function useTeamData({
  version,
  onReload,
  first,
}: {
  version: number;
  onReload?: () => Promise<void>;
  first?: Partial<Record<Paged, number>>;
}) {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [matches, setMatches] = useState<TwinMatch[]>([]);
  const [waiting, setWaiting] = useState<Waiting[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [fragments, setFragments] = useState<Fragment[]>([]);
  const [unsorted, setUnsorted] = useState<Unsorted[]>([]);
  const [suspects, setSuspects] = useState<SuspectSpeaker[]>([]);
  const [heard, setHeard] = useState<Review['heard']>();
  const [error, setError] = useState('');
  const [peopleError, setPeopleError] = useState('');
  const [reviewError, setReviewError] = useState('');
  const [reviewReady, setReviewReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [totals, setTotals] = useState<Review['totals']>();
  // Each answer is shown only if no newer request of its kind was made meanwhile.
  const peopleVersion = useRef(0);
  const reviewVersion = useRef(0);
  const refreshPersonas = usePersonas((state) => state.refresh);

  // As many of each list as the page shows, from the start; asked for again when it shows more.
  const reviewUrl = reviewPath(first);
  const loadPeople = useCallback(async () => {
    const current = ++peopleVersion.current;
    try {
      const folks = await api<{ items: Person[]; matches?: TwinMatch[] }>(
        '/api/library/people',
      );
      if (current !== peopleVersion.current) return;
      setPeople(folks.items);
      setMatches(folks.matches ?? []);
      // The side bar counts the same people and tasks: it takes them from here rather than asking again.
      useTeam.getState().absorb({ people: folks.items });
      setPeopleError('');
    } catch (failure) {
      if (current === peopleVersion.current)
        setPeopleError(
          failure instanceof Error ? failure.message : '无法加载人物',
        );
    }
  }, []);
  const loadReview = useCallback(async () => {
    const current = ++reviewVersion.current;
    try {
      const queue = await api<Review>(reviewUrl);
      if (current !== reviewVersion.current) return;
      useTeam.getState().absorb({ review: queue });
      setWaiting(queue.items);
      setVoices(queue.voices);
      setFragments(queue.fragments);
      setUnsorted(queue.unsorted);
      setSuspects(queue.suspects ?? []);
      setHeard(queue.heard);
      setTotals(queue.totals);
      setReviewError('');
      setReviewReady(true);
    } catch (failure) {
      if (current === reviewVersion.current)
        setReviewError(
          failure instanceof Error ? failure.message : '无法加载待处理事项',
        );
    }
  }, [reviewUrl]);
  const load = useCallback(
    async () => void (await Promise.all([loadPeople(), loadReview()])),
    [loadPeople, loadReview],
  );
  useEffect(() => {
    void loadPeople();
    return () => {
      peopleVersion.current += 1;
    };
  }, [loadPeople, version]);
  // Also when more of a list is asked for: the server answers from its cached reading, people are not read again.
  useEffect(() => {
    void loadReview();
    return () => {
      reviewVersion.current += 1;
    };
  }, [loadReview, version]);
  const updating = !!people?.some((p) => p.updating);
  // A twin's memory takes minutes to rebuild: every few seconds would only load the server, many pages at once.
  usePolling(load, updating ? 15000 : 0);

  /** Do something, show what went wrong, then load again (``reload: false`` leaves that to the caller, for a run of
   * many that need loading once at the end). Gives what went wrong, empty when it worked, for the caller that must
   * know (a dialog that stays open, a page already left). */
  const act = useCallback(
    async (
      work: () => Promise<unknown>,
      { reload = true }: { reload?: boolean } = {},
    ) => {
      setBusy(true);
      setError('');
      let failed = '';
      try {
        await work();
      } catch (failure) {
        failed = failure instanceof Error ? failure.message : '操作失败';
        setError(failed);
      }
      if (reload) await load();
      setBusy(false);
      return failed;
    },
    [load],
  );

  const saveClaim = (person: Person, claim: string) =>
    act(async () => {
      if (person.persona_id)
        await api(
          `/api/personas/${encodeURIComponent(person.persona_id)}/claim`,
          { method: 'PUT', json: { claim: claim || null } },
        );
      else
        await api(
          `/api/library/people/${encodeURIComponent(person.id)}/persona`,
          { method: 'POST', json: { claim: claim || null } },
        );
      await refreshPersonas();
    });
  const rename = (person: Person, value: string, reload = true) =>
    act(
      () =>
        api(`/api/library/people/${encodeURIComponent(person.id)}`, {
          method: 'PATCH',
          json: { name: value },
        }),
      { reload },
    );
  const resolve = (
    person: Person,
    into: Pick<Person, 'id'> | null,
    reload = true,
  ) =>
    act(
      () =>
        api(`/api/library/people/${encodeURIComponent(person.id)}/resolve`, {
          method: 'POST',
          json: { into: into?.id ?? null },
        }),
      { reload },
    );
  // An administrator takes two people for one, keeping the one with a twin (or who spoke more).
  const merge = (one: Person, other: Person, reload = true) => {
    const [kept, folded] =
      other.persona_id || (!one.persona_id && other.speakers > one.speakers)
        ? [other, one]
        : [one, other];
    return act(
      () =>
        api(`/api/library/people/${encodeURIComponent(folded.id)}/merge`, {
          method: 'POST',
          json: { into: kept.id },
        }),
      { reload },
    );
  };
  const apart = (one: Person, other: Person, reload = true) =>
    act(
      () =>
        api(`/api/library/people/${encodeURIComponent(one.id)}/apart`, {
          method: 'POST',
          json: { other: other.id },
        }),
      { reload },
    );
  // Every recording the voice was heard in is settled at once.
  const decideVoice = (
    members: VoiceMember[],
    decision: VoiceDecision,
    reload = true,
  ) =>
    act(
      async () => {
        const { recognised, unlike } = await api<{
          recognised?: number;
          unlike?: { person_id: string; name: string } | null;
        }>('/api/library/voices', {
          method: 'POST',
          json: {
            members: members.map(
              ({ recording_id, transcript_id, speaker_id }) => ({
                recording_id,
                transcript_id,
                speaker_id,
              }),
            ),
            ...decision,
          },
        });
        // The voice sounds clearly more like someone else: said once, the owner's answer stands.
        if (unlike)
          toast(
            `这组声音听起来更像${unlike.name}，已按你的选择记下；不对可以在人物的「抽查」里改`,
            'warning',
            8000,
          );
        // What the new voice samples settled elsewhere: an answer that saves the next questions.
        else if (recognised)
          toast(`又按声音认出了 ${recognised} 位说话人，不用再问`, 'success');
      },
      { reload },
    );
  // Whoever keeps a twin made by hand says whether it is the person of its name in the meetings.
  const sameTwin = (match: TwinMatch, same: boolean) =>
    act(async () => {
      await api(
        `/api/library/people/${encodeURIComponent(match.person_id)}/same`,
        { method: 'POST', json: { persona_id: match.persona_id, same } },
      );
      await refreshPersonas();
    });
  const retry = (recording: Recording) =>
    act(async () => {
      await api(
        `/api/library/recordings/${encodeURIComponent(recording.id)}/retry`,
        { method: 'POST' },
      );
      await onReload?.();
    });
  // Build a twin again now: its update stopped without completing, or the switched-off automatic rebuild holds it.
  const rebuild = (person: Person) =>
    act(() =>
      api(`/api/library/people/${encodeURIComponent(person.id)}/rebuild`, {
        method: 'POST',
      }),
    );
  // There is no call for all at once: the same retry for each, one after the other.
  const retryAll = (recordings: Recording[]) =>
    act(async () => {
      for (const recording of recordings)
        await api(
          `/api/library/recordings/${encodeURIComponent(recording.id)}/retry`,
          { method: 'POST' },
        );
      await onReload?.();
    });
  const removeRecording = (recording: Recording) =>
    act(async () => {
      await api(`/api/library/recordings/${encodeURIComponent(recording.id)}`, {
        method: 'DELETE',
      });
      await onReload?.();
    });

  return {
    people,
    matches,
    sameTwin,
    peopleError,
    waiting,
    voices,
    fragments,
    unsorted,
    suspects,
    heard,
    totals,
    reviewError,
    reviewReady,
    error,
    busy,
    load,
    act,
    saveClaim,
    rename,
    resolve,
    merge,
    apart,
    decideVoice,
    retry,
    retryAll,
    removeRecording,
    rebuild,
  };
}
