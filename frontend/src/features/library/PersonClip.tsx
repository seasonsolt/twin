import { ClipButton } from '../../components/ui';
import { withBase } from '../../lib/base';
import type { Person } from '../../pages/Recording';

/** The voice a person is recognised by (one of their voice samples, or a meeting they were confirmed in), as a
 * small reference beside what is being looked at. */
export function PersonClip({
  person,
  icon = false,
}: {
  person?: Person;
  /** Only the round play button, for a card; otherwise a text button naming the person. */
  icon?: boolean;
}) {
  if (!person?.recording_id || !person.speaker_id) return null;
  return (
    <ClipButton
      size="md"
      label={`听${person.name}确认过的声音`}
      caption={icon ? undefined : `听${person.name}`}
      src={withBase(
        `/api/library/recordings/${encodeURIComponent(person.recording_id)}/speakers/${encodeURIComponent(person.speaker_id)}/samples/0`,
      )}
    />
  );
}
