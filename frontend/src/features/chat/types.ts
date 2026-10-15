export interface Citation {
  id: string;
  kind: 'item' | 'expression' | 'file';
  text: string;
  facet?: string;
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
  elapsed_ms?: number;
  completed_at?: string;
}

export interface Turn {
  id: string;
  role: 'user' | 'twin';
  content: string;
  timestamp: string;
  reply?: ChatReply;
}
