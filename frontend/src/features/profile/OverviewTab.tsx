import { useEffect } from 'react';
import { Notice, TextLink } from '../../components/ui';
import { api } from '../../lib/api';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import type { SourcePage } from '../../pages/Memories';
import { Overview, type AskPerson } from './Overview';

/** The 档案 tab: how well each aspect of the person is known, and what the twin would draw on for it. */
export function OverviewTab({ ask }: { ask?: AskPerson }) {
  const personaId = usePersonaId();
  const [speakerCount, setSpeakerCount] = usePersonaState(0);
  useEffect(() => {
    const controller = new AbortController();
    void api<SourcePage>('/api/persona/sources?limit=0', {
      signal: controller.signal,
      headers: { 'X-Twin-Persona': personaId },
    })
      .then((page) => {
        if (!controller.signal.aborted)
          setSpeakerCount(page.summary.needs_speaker);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [personaId, setSpeakerCount]);
  return (
    <>
      {speakerCount > 0 && (
        <Notice actions={<TextLink to="?section=memories">去确认 →</TextLink>}>
          {speakerCount} 段录音待确认
        </Notice>
      )}
      <Overview ask={ask} />
    </>
  );
}
