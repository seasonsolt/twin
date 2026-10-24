import { useState } from 'react';
import { api } from '../../lib/api';

/**
 * The box a person answers in, and 请分身起草, which puts the twin's draft into it for them to change (nothing is sent).
 * A draft that took the place of words they had written is not final: `kept` holds those words until they edit the
 * draft or take them back (`restore`). `setError` is told why a draft could not be made, and cleared when one is asked.
 */
export function useReplyDraft(
  url: string,
  setError: (message: string) => void,
) {
  const [text, setText] = useState('');
  const [kept, setKept] = useState<string | null>(null);
  const [drafting, setDrafting] = useState(false);
  const draft = async () => {
    setDrafting(true);
    setError('');
    try {
      const drafted = await api<{ text: string }>(url, {
        method: 'POST',
        json: {},
      });
      setKept(text.trim() ? text : null);
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
