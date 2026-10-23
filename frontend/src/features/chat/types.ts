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
}

/** Whether the person has yet to answer what this turn left to them. */
export const waiting = (turn: Turn) =>
  turn.handoff?.status === 'delivered' || turn.handoff?.status === 'writing';

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

/** The turns of the conversation as it is shown and sent: the asker's and the twin's. */
export const spoken = (turn: Turn): turn is Turn & { role: Speaker } =>
  turn.role !== 'self';

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
  for (const turn of local) {
    const line = turn.handoff && lines.get(turn.handoff.id);
    out.push(line ? { ...turn, handoff: line } : turn);
    const reply = turn.handoff && said.get(turn.handoff.id);
    if (reply && !shown.has(reply.handoff_id)) out.push(reply);
  }
  return out;
}
