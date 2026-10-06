export type Round = 'initial';
export interface Question {
  id: string;
  number: number;
  section: string;
  text: string;
  kind: string;
  facets: string[];
  optional: boolean;
}
export interface QuestionnaireData {
  round: Round;
  status: 'empty' | 'draft' | 'submitted';
  answers: Record<string, string>;
  updated_at: string | null;
  submitted_at: string | null;
  questions: Question[];
}
export interface Submission {
  round: Round;
  job_id: string | null;
  notice: string;
}
