export type LedgerKind = 'decision' | 'commitment' | 'objection' | 'progress';
export type LedgerStatus =
  | 'open'
  | 'claimed_done'
  | 'evidenced'
  | 'confirmed_done'
  | 'not_done'
  | 'reopened'
  | 'unknown';
export type LedgerReview = 'unreviewed' | 'confirmed' | 'edited' | 'rejected';

export interface LedgerEntry {
  entry_id: string;
  source_id: string;
  meeting_date: string | null;
  meeting_title: string;
  kind: LedgerKind;
  kind_label: string;
  speaker: string;
  quote: string;
  quote_exact: boolean;
  owner: string;
  counterpart: string;
  what: string;
  due: string | null;
  due_text: string;
  condition: string;
  relates_to: string | null;
  status: LedgerStatus | null;
  status_label: string | null;
  current_status: LedgerStatus;
  current_status_label: string;
  confidence: number;
  review: LedgerReview;
  version: number;
  thread: string;
  confirmation_message: string | null;
}

export interface LedgerData {
  entries: LedgerEntry[];
  people: string[];
  kind_labels: Record<LedgerKind, string>;
  status_labels: Record<LedgerStatus, string>;
  meetings: { total: number; pending: number };
  job_id: string | null;
}

export interface LedgerBrief {
  person: string;
  as_of: string;
  theirs: LedgerEntry[];
  mine: LedgerEntry[];
  progress: LedgerEntry[];
  objections: LedgerEntry[];
  questions: { entry_id: string; text: string }[];
}

export type LedgerChanges = Partial<{
  owner: string;
  counterpart: string | null;
  what: string;
  due: string | null;
  condition: string | null;
  status: LedgerStatus | null;
}>;

export interface LedgerBuildResult {
  sources: number;
  entries: number;
  dropped: number;
}
