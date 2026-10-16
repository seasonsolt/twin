import type { Citation } from '../chat/types';

export type WorkStatus = 'idle' | 'running' | 'failed';

export interface WorkTurn {
  role: 'user' | 'assistant';
  content: string;
  at: string;
  steps: string[];
  files: string[];
  /** A reply answered on chat's path: what it rests on, shown as chat shows it. */
  cited?: Citation[];
}

export interface WorkFile {
  path: string;
  size: number;
}

export interface WorkSummary {
  task_id: string;
  title: string;
  status: WorkStatus;
  updated_at: string;
  turns: number;
}

export interface WorkTask {
  task_id: string;
  title: string;
  status: WorkStatus;
  error: string | null;
  job_id: string | null;
  created_at: string;
  updated_at: string;
  turns: WorkTurn[];
  files: WorkFile[];
  /** Progress lines of the turn in flight; empty otherwise. */
  progress: string[];
  /** A stop was asked for and the turn has not reached its next step yet. */
  stopping: boolean;
}

export interface WorkStarted {
  task: WorkSummary;
  job_id: string;
  /** The message went to the turn in flight instead of starting one. */
  steered: boolean;
}
