import type { TeamAnswerCard } from '../answers/types';
import type { DelegationNote } from '../delegation/types';
import type { LensCardData } from '../lens/types';

export interface Citation {
  id: string;
  kind: 'item' | 'expression' | 'ledger' | 'file';
  text: string;
  facet?: string;
  /** A ledger citation's entry kind: 决定、承诺、异议 or 进展. */
  ledger_kind?: string;
  date?: string | null;
  channel?: string;
  file_name?: string;
  locator?: string;
}

/** Where what a twin's answer left to the person stands (for the asker, under the answer). */
export interface HandoffLine {
  id: string;
  kind: 'decide' | 'commit' | 'evaluate' | 'missing' | 'inferred';
  status:
    | 'delivered'
    | 'writing'
    | 'replied'
    | 'accepted'
    | 'declined'
    | 'dismissed'
    | 'expired'
    | 'withdrawn';
  status_label: string;
  /** What the twin is called: the person it was handed to. */
  owner_name: string;
}

/** Who may use what the person asked their assistant to remember (``记一下``): ``none`` is not keeping it. */
export type NoteTier = 'none' | 'colleague' | 'self';
/** How the person is talking with their own assistant this turn: asking it things, or looking at themself. */
export type Reflection = 'ask' | 'mirror' | 'free' | 'dream' | 'voice';
export const REFLECTIONS = [
  { id: 'ask', label: '问答' },
  { id: 'mirror', label: '照镜子' },
  { id: 'free', label: '随便说' },
  { id: 'dream', label: '记梦' },
  { id: 'voice', label: '内在声音' },
] as const satisfies readonly { id: Reflection; label: string }[];

/** A note the assistant took down, shown under its reply with the tier it has now. */
export interface NoteCard {
  /** The memory source it is kept as; what the tier is changed by. */
  id: string;
  text: string;
  tier: NoteTier;
}

/** A promise the person said they make, which stands in their commitments from the moment it is said. */
export interface PromiseLine {
  entry_id: string;
  what: string;
  to: string;
  due: string | null;
}

/** What a trial question (看同事会得到什么) left out: what the person keeps from colleagues that it would have used. */
export interface Withheld {
  id: string;
  facet: string;
  text: string;
}

export interface ChatReply {
  reply: string;
  citations: string[];
  confidence: number;
  abstain: boolean;
  abstain_reason: string;
  topic_facets?: string[];
  retrieved_ids: string[];
  as_of?: string | null;
  cited?: Citation[];
  mode?: 'grounded' | 'general' | 'inferred' | 'abstain';
  /** False when the model sent no metadata to check the answer's grounding against, as with a short greeting. */
  verified?: boolean;
  elapsed_ms?: number;
  completed_at?: string;
  /** Sent with the final answer when it left something to the person. */
  handoff?: HandoffLine;
  /** The team's answers that match the question, shown as cards apart from what the twin says. */
  team_answers?: TeamAnswerCard[];
  /** The person's own conversation: what was taken down, and the promise that was made. */
  note?: NoteCard;
  /** The person's assistant asked colleagues' twins in their name (帮我问问…): which asking, and its own note on it. */
  delegation?: DelegationNote;
  /** The message spoke of ending one's life or harming oneself: the fixed reply that says where help is. */
  crisis?: boolean;
  /** The way the person was talking with their own assistant when it answered (照镜子, 内在声音…). */
  reflection?: Reflection;
  /** The twin said goodbye to an heir past their day to leave (P2.8), and answers them no more. */
  farewell?: boolean;
  commitment?: PromiseLine;
  /** A lens's answer (a colleague asked the person's lens): statements with their basis, in place of the twin's words. */
  lens?: LensCardData;
  /** A trial question's answer: not part of the conversation, and what it left out. */
  preview?: { withheld: Withheld[] };
}

export type Speaker = 'user' | 'twin';

export interface Turn {
  id: string;
  /** ``self`` is the person's own reply, written into a conversation to answer a handoff; it is shown as theirs and
   * never sent back to the twin as part of the history. */
  role: Speaker | 'self';
  content: string;
  timestamp: string;
  reply?: ChatReply;
  /** The handoff a ``self`` turn answers. */
  handoff_id?: string;
  /** Where what this answer left to the person stands. */
  handoff?: HandoffLine;
  /** A trial question (看同事会得到什么) or its answer: shown where it was asked, never saved or sent on. */
  preview?: boolean;
  /** What the person said of this answer of their twin's (自评记录): like them or not. */
  self_rating?: SelfRating;
}

export type SelfRating = 'like' | 'unlike';

/** Whether the person has yet to answer what this turn left to them. */
export const waiting = (turn: Turn) =>
  turn.handoff?.status === 'delivered' || turn.handoff?.status === 'writing';

/** Whether what this turn left to the person could still change, though they have answered it or it ran out: they may
 * reply to one that expired or was put back, and take a promise on afterwards in the commitments. */
export const settling = (turn: Turn) =>
  turn.handoff?.status === 'expired' ||
  turn.handoff?.status === 'dismissed' ||
  (turn.handoff?.status === 'replied' && turn.handoff.kind === 'commit');

/** Whether the person took on, as a commitment, what the handoff a reply of theirs answers asked them to promise. */
export const promiseTaken = (turns: Turn[], handoffId: string | undefined) =>
  !!handoffId &&
  turns.some(
    (turn) =>
      turn.handoff?.id === handoffId &&
      turn.handoff.kind === 'commit' &&
      turn.handoff.status === 'accepted',
  );

/** What the line under an answer says of the handoff: the asker is told it went to the person and where it stands. */
export function handoffText(line: HandoffLine) {
  const where: Record<HandoffLine['status'], string> = {
    delivered: '等回复',
    writing: '等回复',
    replied: '已回复',
    accepted: '已接受',
    declined: '已拒绝',
    dismissed: '不答',
    expired: '已过期',
    withdrawn: '已撤回',
  };
  return `已转给${line.owner_name}本人 · ${where[line.status]}`;
}

/** The turns of the conversation as it is shown and sent: the asker's and the twin's, not the person's own replies
 * and not a trial question. */
export const spoken = (turn: Turn): turn is Turn & { role: Speaker } =>
  turn.role !== 'self' && !turn.preview;

/**
 * The conversation as the server has it now, folded into the one on screen: the state of each handoff, and the
 * person's reply right after the answer it answers. Nothing else is touched, so a message still being written, or
 * one the page has not saved, stays as it is.
 */
export function withHandoffs(local: Turn[], remote: Turn[]): Turn[] {
  const lines = new Map(
    remote.flatMap((turn) =>
      turn.handoff ? [[turn.handoff.id, turn.handoff] as const] : [],
    ),
  );
  const said = new Map(
    remote.flatMap((turn) =>
      turn.role === 'self' && turn.handoff_id
        ? [[turn.handoff_id, turn] as const]
        : [],
    ),
  );
  const shown = new Set(local.map((turn) => turn.handoff_id));
  const out: Turn[] = [];
  let changed = false;
  for (const turn of local) {
    const line = turn.handoff && lines.get(turn.handoff.id);
    if (line && !sameLine(line, turn.handoff)) {
      out.push({ ...turn, handoff: line });
      changed = true;
    } else out.push(turn);
    const reply = turn.handoff && said.get(turn.handoff.id);
    if (reply && !shown.has(reply.handoff_id)) {
      out.push(reply);
      changed = true;
    }
  }
  // Nothing new: the same turns, so what depends on them (such as the scroll) is left alone.
  return changed ? out : local;
}

const sameLine = (a: HandoffLine, b: HandoffLine | undefined) =>
  !!b && (Object.keys(a) as (keyof HandoffLine)[]).every((k) => a[k] === b[k]);
