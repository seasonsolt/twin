import { useCallback, useEffect, useRef } from 'react';
import {
  usePersonaId,
  usePersonaState as useState,
} from '../../lib/usePersonaState';
import { api } from '../../lib/api';
import { personaKey } from '../../lib/persona';
import type { QuestionnaireData, Round, Submission } from './types';

export const SAVE_DELAY_MS = 800;
const leavingWrites = new Map<string, Promise<boolean>>();
type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error';
interface DraftSession {
  persona: string;
  round: Round;
  answers: Record<string, string>;
  revision: number;
  savedRevision: number;
  alive: boolean;
  submitting?: boolean;
  signal: AbortSignal;
  timer?: ReturnType<typeof setTimeout>;
  saving?: Promise<boolean>;
}

export function useQuestionnaire(round: Round, active = true) {
  const persona = usePersonaId();
  const [data, setData] = useState<QuestionnaireData | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<Submission | null>(null);
  const [attempt, setAttempt] = useState(0);
  const session = useRef<DraftSession | null>(null);

  const save = useCallback(
    async (draft: DraftSession, keepalive = false): Promise<boolean> => {
      clearTimeout(draft.timer);
      if (draft.saving) {
        if (!(await draft.saving)) return false;
        return save(draft, keepalive);
      }
      if (draft.revision === draft.savedRevision) return true;
      const revision = draft.revision;
      const snapshot = { ...draft.answers };
      if (draft.alive && draft.persona === persona) {
        setSaveState('saving');
        setSaveError('');
      }
      const request = (async () => {
        try {
          await api('/api/persona/questionnaire/draft', {
            method: 'PUT',
            headers: { 'X-Twin-Persona': draft.persona },
            json: { round: draft.round, answers: snapshot },
            keepalive:
              keepalive &&
              new Blob([
                JSON.stringify({ round: draft.round, answers: snapshot }),
              ]).size < 60_000,
          });
          draft.savedRevision = revision;
          if (draft.alive)
            setSaveState(draft.revision === revision ? 'saved' : 'pending');
          return true;
        } catch (failure) {
          if (draft.alive) {
            setSaveState('error');
            setSaveError(
              failure instanceof Error ? failure.message : '保存失败',
            );
          }
          return false;
        }
      })();
      draft.saving = request;
      const ok = await request;
      draft.saving = undefined;
      return ok;
    },
    [persona],
  );

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const key = personaKey(round, persona);
    const draft: DraftSession = {
      persona,
      round,
      answers: {},
      revision: 0,
      savedRevision: 0,
      alive: true,
      signal: controller.signal,
    };
    session.current = draft;
    setData(null);
    setLoading(true);
    setError('');
    setSaveError('');
    setSaveState('idle');
    setSubmitting(false);
    setResult(null);
    void (async () => {
      // A rapid round/route return must not restore an older server snapshot.
      await leavingWrites.get(key);
      if (!draft.alive) return null;
      return api<QuestionnaireData>(
        `/api/persona/questionnaire?round=${round}`,
        {
          signal: controller.signal,
          headers: { 'X-Twin-Persona': draft.persona },
        },
      );
    })()
      .then((loaded) => {
        if (!draft.alive || !loaded) return;
        draft.answers = { ...loaded.answers };
        setData(loaded);
        setAnswers(draft.answers);
        setSaveState(loaded.updated_at ? 'saved' : 'idle');
      })
      .catch((failure: unknown) => {
        if (draft.alive)
          setError(failure instanceof Error ? failure.message : '加载失败');
      })
      .finally(() => {
        if (draft.alive) setLoading(false);
      });
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (draft.saving && draft.revision !== draft.savedRevision) {
        event.preventDefault();
        event.returnValue = '';
      } else void save(draft, true);
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => {
      draft.alive = false;
      controller.abort();
      clearTimeout(draft.timer);
      window.removeEventListener('beforeunload', beforeUnload);
      // Finish writes rather than aborting a personal draft on route changes.
      const preceding = leavingWrites.get(key);
      const finish = (async () => {
        await preceding;
        if (!(await save(draft, true))) return false;
        return save(draft, true);
      })();
      leavingWrites.set(key, finish);
      void finish.finally(() => {
        if (leavingWrites.get(key) === finish) leavingWrites.delete(key);
      });
    };
  }, [active, attempt, round, save, persona]);

  const change = (id: string, value: string) => {
    const draft = session.current;
    if (!draft?.alive || draft.submitting) return;
    draft.answers = { ...draft.answers, [id]: value };
    draft.revision += 1;
    setAnswers(draft.answers);
    setResult(null);
    setSaveState(draft.saving ? 'saving' : 'pending');
    clearTimeout(draft.timer);
    draft.timer = setTimeout(() => void save(draft), SAVE_DELAY_MS);
  };
  const flush = async () => {
    const draft = session.current;
    if (!draft?.alive) return false;
    if (!(await save(draft))) return false;
    return save(draft);
  };
  const submit = async () => {
    const draft = session.current;
    if (!draft?.alive || draft.submitting) return null;
    draft.submitting = true;
    setSubmitting(true);
    setError('');
    try {
      if (!(await flush()) || !draft.alive) return null;
      const submitted = await api<Submission>(
        '/api/persona/questionnaire/submit',
        {
          method: 'POST',
          headers: { 'X-Twin-Persona': draft.persona },
          json: { round: draft.round, answers: draft.answers },
        },
      );
      if (!draft.alive) return null;
      setResult(submitted);
      // Read the server's submission timestamp.
      const loaded = await api<QuestionnaireData>(
        `/api/persona/questionnaire?round=${draft.round}`,
        { signal: draft.signal, headers: { 'X-Twin-Persona': draft.persona } },
      ).catch(() => null);
      if (loaded && draft.alive) setData(loaded);
      return draft.alive ? submitted : null;
    } catch (failure) {
      if (draft.alive)
        setError(failure instanceof Error ? failure.message : '提交失败');
      return null;
    } finally {
      draft.submitting = false;
      if (draft.alive) setSubmitting(false);
    }
  };
  return {
    data,
    answers,
    loading,
    error,
    saveError,
    saveState,
    submitting,
    result,
    change,
    flush,
    submit,
    needsLeaveWarning: () => {
      const draft = session.current;
      return Boolean(draft?.saving && draft.revision !== draft.savedRevision);
    },
    reload: () => setAttempt((value) => value + 1),
  };
}
