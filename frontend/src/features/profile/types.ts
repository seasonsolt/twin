import type { SourceKind } from '../sources/types';
export type ReviewStatus = 'unreviewed' | 'confirmed' | 'edited' | 'rejected';
export const reviewLabels: Record<ReviewStatus, string> = {
  unreviewed: '待确认',
  confirmed: '已确认',
  edited: '已修改',
  rejected: '已否定',
};
export interface ProfileItem {
  item_id: string;
  dimension_id: string;
  dimension_name: string;
  facet_id: string;
  facet_name: string;
  statement: string;
  extracted_statement: string;
  applies_when: string;
  conflict: string;
  occasions: number;
  review: ReviewStatus;
  evidence: {
    expression_id: string;
    source_id: string;
    source_kind: SourceKind;
    quote: string;
    date: string | null;
    own_words: boolean;
  }[];
}
export interface Coverage {
  taxonomy: string;
  as_of: string;
  level_labels: Record<string, string>;
  kind_labels: Record<string, string>;
  dimensions: {
    dimension_id: string;
    name: string;
    facets: number;
    consented: number;
    covered: number | null;
    sufficient: number | null;
    verified: number | null;
    conflicts: number;
  }[];
  facets: {
    facet_id: string;
    name: string;
    dimension_id: string;
    consented: boolean;
    level: number;
    sufficiency: number;
    confirmed: number;
    asked: number;
    abstained: number;
    conflicts: number;
    by_kind: Record<string, number>;
  }[];
  suggestions: {
    facet_id: string;
    name: string;
    reason: string;
    sources: string[];
  }[];
}
