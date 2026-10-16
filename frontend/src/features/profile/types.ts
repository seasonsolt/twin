import type { SourceKind } from '../sources/types';
/** An item is used as soon as it is extracted; the person only steps in to correct one (edited) or remove it
 * (rejected). `confirmed` survives from when items were confirmed one by one. */
export type ReviewStatus = 'unreviewed' | 'confirmed' | 'edited' | 'rejected';
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
export interface ItemSummary {
  total: number;
  /** Items whose evidence disagrees: worth a look, not a queue. */
  conflicts: number;
  dimensions: {
    dimension_id: string;
    name: string;
    total: number;
  }[];
}
export interface ItemQuery {
  dimension?: string[];
  review?: ReviewStatus;
  q?: string;
  source_id?: string;
  conflict?: boolean;
  sort?: 'facet' | 'evidence';
  with_sources?: boolean;
}
export interface ItemSource {
  title: string;
  first_date: string | null;
  kind: string;
}
export interface ItemPage {
  items: ProfileItem[];
  total: number;
  sources?: Record<string, ItemSource>;
}

/** Whether the item stands only on what others said about the person: the twin answers from it tentatively. */
export const secondhand = (item: ProfileItem) =>
  item.review !== 'edited' &&
  item.review !== 'confirmed' &&
  !item.evidence.some((evidence) => evidence.own_words);
