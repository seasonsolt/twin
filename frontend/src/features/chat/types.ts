export interface Citation {
  id: string;
  kind: 'item' | 'expression';
  text: string;
  facet?: string;
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
  mode?: 'grounded' | 'general' | 'abstain';
}

export interface Turn {
  id: string;
  role: 'user' | 'twin';
  content: string;
  timestamp: string;
  reply?: ChatReply;
}
