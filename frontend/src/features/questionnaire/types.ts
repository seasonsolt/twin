export type Round = 'initial' | 'retest';
export interface Question {
  id: string;
  number: number;
  section: string;
  text: string;
  kind: string;
  facets: string[];
  test: boolean;
  optional: boolean;
}
export interface QuestionnaireData {
  round: Round;
  status: 'empty' | 'draft' | 'submitted';
  answers: Record<string, string>;
  updated_at: string | null;
  submitted_at: string | null;
  retest_from: string | null;
  questions: Question[];
}
export interface Submission {
  round: Round;
  job_id: string | null;
  notice: string;
}
