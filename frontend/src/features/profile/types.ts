import type { SourceKind } from '../sources/types';
/** An item is used as soon as it is extracted; the person only steps in to correct one (edited) or remove it
 * (rejected). `confirmed` survives from when items were confirmed one by one. */
export type ReviewStatus = 'unreviewed' | 'confirmed' | 'edited' | 'rejected';
/** Who may use a memory: colleagues' conversations, or only the person themself. */
export type Tier = 'colleague' | 'self';
export const TIER_LABELS: Record<Tier, string> = {
  colleague: '同事能用',
  self: '只有本人能用',
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
  /** Its facet's tier unless the person changed it. Absent from an older server: colleagues may use it. */
  tier?: Tier;
  tier_changed?: boolean;
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
  /** 0 还不了解, 1 提到过, 2 了解一些, 3 了解较多: how much the twin knows. */
  level_labels: Record<string, string>;
  /** 回答经过检查: a mark beside level 3, not a level. */
  checked_label?: string;
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
    /** Level 3 and its answers held up when checked. */
    checked?: boolean;
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
