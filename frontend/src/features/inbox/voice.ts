import type { Person } from '../../pages/Recording';
import type { Voice, VoiceDecision } from '../library/review';

/** One new voice waiting for a name: someone the library found and nobody named (``person``), or a voice heard in
 * several recordings (``voice``). */
export type VoiceItem =
  | {
      kind: 'person';
      id: string;
      seconds: number;
      recordings: number;
      enough: false;
      stranger: false;
      person: Person;
    }
  | {
      kind: 'voice';
      id: string;
      seconds: number;
      recordings: number;
      enough: boolean;
      stranger: boolean;
      voice: Voice;
    };

/** An answer offered as one button: someone known, or a name the meeting called the voice that nobody has yet. */
export interface Option {
  id: string;
  name: string;
  /** A name to add to the team rather than someone already in it. */
  added: boolean;
  /** The one answer the voice itself makes sure of. */
  sure: boolean;
}

/** What a voice is called in the list, which answers it offers and what is worth saying about it. */
export interface VoiceFacts {
  title: string;
  /** What the voice is called where the names offered stand right below (one at a time): the same, without saying
   * them twice. */
  lead: string;
  options: Option[];
  /** The leading candidate was heard in a recording that already has them: may be one person split in two. */
  split: boolean;
  /** What was said that names the voice. */
  quote: string;
}

export function describeVoice(voice: Voice): VoiceFacts {
  const [likely, other] = voice.candidates;
  // A voice very close to one person, or far enough ahead of everyone else (the middle tier), is the surest answer;
  // a nearer guess is a choice to make on purpose.
  const middle = voice.tier === 'mid' && !!likely && !voice.near;
  const sure = (Boolean(likely?.sure) && !voice.near) || middle;
  const offered = (voice.near && other ? [likely, other] : [likely]).filter(
    Boolean,
  );
  // A name the meeting calls them that nobody in the team has yet: added as a new person in one click.
  const newName =
    voice.called && !voice.candidates.some((c) => c.called) ? voice.called : '';
  const title = likely?.called
    ? sure
      ? `会上叫作${likely.name}，声音也像`
      : `会上被叫作${likely.name}`
    : newName
      ? `会上被叫作${newName}`
      : !likely
        ? voice.stranger
          ? '你标过不认识的声音'
          : '没听过的声音'
        : sure
          ? likely.sure
            ? `像${likely.name}`
            : `多半是${likely.name}`
          : offered.length === 1
            ? `可能是${likely.name}`
            : `像${offered.map((c) => c.name).join('，也像')}`;
  // Without the names: what the meeting called the voice if nobody in the team is that name, else how sure it is.
  const lead = likely?.called
    ? sure
      ? '会上点过名，声音也像'
      : '会上被点过名'
    : newName || !likely
      ? title
      : sure
        ? likely.sure
          ? '声音很像下面这位'
          : '多半是下面这位'
        : offered.length === 1
          ? '可能是下面这位'
          : '像下面几位之一';
  return {
    title,
    lead,
    options: [
      ...(newName
        ? [{ id: 'new', name: newName, added: true, sure: false }]
        : []),
      ...offered.map((c, i) => ({
        id: c.person_id,
        name: c.name,
        added: false,
        sure: sure && i === 0,
      })),
    ],
    split: Boolean(likely?.split),
    quote: voice.called && voice.quote ? voice.quote : '',
  };
}

/** What the owner says a voice is: someone in the team, a name to add, nobody they know, or several people. */
export type Answer =
  | { to: 'person'; person: { id: string; name: string } }
  | { to: 'new'; name: string }
  | { to: 'nobody' }
  | { to: 'mixed' };

/** The answer a button or a typed name stands for: someone already in the team by that name, else a new person. */
export function answerFor(
  name: string,
  known: Person[],
  option?: Option,
): Answer {
  if (option)
    return option.added
      ? { to: 'new', name: option.name }
      : { to: 'person', person: { id: option.id, name: option.name } };
  const typed = name.trim();
  const match = known.find((p) => p.name === typed);
  return match
    ? { to: 'person', person: { id: match.id, name: match.name } }
    : { to: 'new', name: typed };
}

/** What settling a voice heard in recordings tells the server. */
export function decisionOf(answer: Answer): VoiceDecision {
  switch (answer.to) {
    case 'person':
      return { action: 'confirm', person_id: answer.person.id };
    case 'new':
      return { action: 'confirm', new_person: answer.name };
    case 'nobody':
      return { action: 'unknown' };
    case 'mixed':
      return { action: 'mixed' };
  }
}

/** What the row left in a settled one's place says. */
export function labelOf(answer: Answer): string {
  switch (answer.to) {
    case 'person':
      return `已归给${answer.person.name}`;
    case 'new':
      return `已新建${answer.name}`;
    case 'nobody':
      return '已标为不认识';
    case 'mixed':
      return '已标为几个人混在一起';
  }
}
