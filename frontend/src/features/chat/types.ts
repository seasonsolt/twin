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
}

export type Speaker = 'user' | 'twin';

export interface Turn {
  id: string;
  /** ``self`` is the person's own reply, written into a conversation to answer a handoff; nothing shows it yet. */
  role: Speaker | 'self';
  content: string;
  timestamp: string;
  reply?: ChatReply;
  /** The handoff a ``self`` turn answers. */
  handoff_id?: string;
}

/** The turns of the conversation as it is shown and sent: the asker's and the twin's. */
export const spoken = (turn: Turn): turn is Turn & { role: Speaker } =>
  turn.role !== 'self';
