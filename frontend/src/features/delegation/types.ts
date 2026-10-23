import type { TeamAnswerCard } from '../answers/types';

/** How one colleague's twin's answer stands, for the person who had it asked. */
export type TargetState =
  'answered' | 'needs_owner' | 'skipped' | 'handed' | 'replied';

/** One twin asked in the person's name, with its answer. */
export interface DelegationTarget {
  persona_id: string;
  name: string;
  /** The person's conversation with that twin, which holds the question and the whole answer. */
  conversation_id: string;
  state: TargetState;
  answer: string;
  mode: 'grounded' | 'general' | 'inferred' | 'abstain' | null;
  /** What the twin left to its person, in a line. */
  ask: string;
  team_answer: TeamAnswerCard | null;
  /** The handoff the person made of it, and where it stands. */
  handoff: { status: string; status_label: string } | null;
  /** What the colleague wrote back. */
  owner_reply: string | null;
  /** Someone else the answer sends the asker to. */
  also: { persona_id: string; name: string }[];
}

/** What the person's assistant asked, and what came back. */
export interface DelegationView {
  id: string;
  question: string;
  targets: DelegationTarget[];
  limit: number;
}

/** The assistant's own note on what came back, kept apart in the reply that said it asked. */
export interface DelegationNote {
  id: string;
  summary: string;
}
