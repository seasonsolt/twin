export interface Citation {
  id: string;
  kind: 'item' | 'expression' | 'ledger';
  text: string;
  facet?: string;
  /** A ledger citation's entry kind: 决定、承诺、异议 or 进展. */
  ledger_kind?: string;
  date?: string | null;
  channel?: string;
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
}

export interface Turn {
  id: string;
  role: 'user' | 'twin';
  content: string;
  timestamp: string;
  reply?: ChatReply;
}
