import { useState } from 'react';
import { api } from '../../lib/api';

/**
 * The box a person answers in, and 请分身起草, which puts the twin's draft into it for them to change (nothing is sent).
 * A draft that took the place of words they had written is not final: `kept` holds those words until they edit the
 * draft or take them back (`restore`). `setError` is told why a draft could not be made, and cleared when one is asked.
 * `also` drafts one reply for several askers of the same matter, whose question `onQuestion` is told, summed up.
 */
export function useReplyDraft(
  url: string,
  setError: (message: string) => void,
  {
    also,
    onQuestion,
  }: { also?: string[]; onQuestion?: (question: string) => void } = {},
) {
  const [text, setText] = useState('');
  const [kept, setKept] = useState<string | null>(null);
  const [made, setMade] = useState('');
  const [drafting, setDrafting] = useState(false);
  const draft = async () => {
    setDrafting(true);
    setError('');
    try {
      const drafted = await api<{ text: string; question?: string }>(url, {
        method: 'POST',
        json: also?.length ? { also } : {},
      });
      if (drafted.question) onQuestion?.(drafted.question);
      // Drafting again over an untouched draft leaves the words it first replaced as they were.
      if (text !== made) setKept(text.trim() ? text : null);
      setMade(drafted.text);
      setText(drafted.text);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '起草失败');
    } finally {
      setDrafting(false);
    }
  };
  return {
    text,
    /** Words typed or pasted by the person. */
    edit: (value: string) => {
      setText(value);
      setKept(null);
    },
    /** The box is emptied (what was in it has been sent). */
    clear: () => {
      setText('');
      setKept(null);
    },
    drafting,
    draft,
    /** There are words of their own the draft replaced, which can be taken back. */
    replaced: kept !== null,
    restore: () => {
      if (kept !== null) setText(kept);
      setKept(null);
    },
  };
}
