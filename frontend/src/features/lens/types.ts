/** One facet as a lens would open it, and whether the memories colleagues may use of it are well founded. */
export interface FacetVerdict {
  facet_id: string;
  name: string;
  dimension_id: string;
  dimension: string;
  level: number;
  label: string;
  /** 回答经过检查, beside level 3. */
  checked: boolean;
  checked_label: string;
  occasions: number;
  ok: boolean;
  /** Why it cannot be opened yet, a few words each. */
  reasons: string[];
}

/** One of the four aspects a lens opens whole: it can be opened when a facet of it is well founded. */
export interface Aspect {
  id: string;
  name: string;
  facets: FacetVerdict[];
  ok: boolean;
  /** How well the twin knows its best facet. */
  level: number;
  label: string;
  checked: boolean;
  /** Why it cannot be opened yet, in a few words; empty when it can. */
  reason: string;
}

// The reason an aspect shows when no facet of it passes: what to do about it first.
const REASON_ORDER = [
  '内容有矛盾',
  '了解还不够多',
  '只有本人能用',
  '还没有记忆',
];

/** The facets grouped into their aspects, in the order they come. */
export function aspectsOf(facets: FacetVerdict[]): Aspect[] {
  const groups = new Map<string, FacetVerdict[]>();
  for (const facet of facets)
    groups.set(facet.dimension_id, [
      ...(groups.get(facet.dimension_id) ?? []),
      facet,
    ]);
  return [...groups.entries()].map(([id, members]) => {
    const passing = members.filter((f) => f.ok);
    const best = [...(passing.length ? passing : members)].sort(
      (a, b) => b.level - a.level,
    )[0];
    const reasons = new Set(members.flatMap((f) => f.reasons));
    return {
      id,
      name: members[0].dimension,
      facets: members,
      ok: passing.length > 0,
      level: best.level,
      label: best.label,
      checked: passing.some((f) => f.checked),
      reason: passing.length
        ? ''
        : (REASON_ORDER.find((r) => reasons.has(r)) ?? [...reasons][0] ?? ''),
    };
  });
}

export type LensStatus = 'active' | 'paused' | 'withdrawn';

/** Whom a lens is for: everyone, or the people named by their twin. */
export interface LensAudience {
  scope: 'team' | 'people';
  twins: string[];
}

/** A lens as its person sees it. */
export interface Lens {
  id: string;
  name: string;
  status: LensStatus;
  published_at: string;
  audience: LensAudience;
  /** Every facet of the aspects it opens, with the aspect it belongs to. */
  facets: {
    facet_id: string;
    name: string;
    dimension_id: string;
    dimension: string;
  }[];
  /** The opened facets it speaks from now. */
  speaking: string[];
  /** Opened, and no longer well founded (a contradiction, a memory made private). */
  failing: string[];
  /** Corrected out: not used until the person opens them again. */
  stopped: { facet_id: string; name: string; corrected: number }[];
  uses_week: number;
}

export interface LensList {
  lenses: Lens[];
  facets: FacetVerdict[];
  stop_after: number;
}

/** What a lens was asked and said: never who asked. */
export interface LensUse {
  id: string;
  question: string;
  said: string;
  facets: { facet_id: string; name: string }[];
  corrected: boolean;
  /** The day it was, YYYY-MM-DD. */
  at: string;
}

/** The words a statement stands on. */
export interface LensBasis {
  quote: string;
  date: string | null;
  kind: string;
}

export interface LensStatement {
  facet_id: string;
  facet: string;
  text: string;
  basis: LensBasis[];
}

/** A lens's answer as a colleague is shown it. */
export interface LensCardData {
  id: string;
  name: string;
  owner_name: string;
  views: LensStatement[];
  empty: boolean;
  settled_by_person: boolean;
  note: string;
}

/** A lens a colleague can ask in this twin's chat. */
export interface LensChoice {
  id: string;
  name: string;
  owner_name: string;
  facets: { facet_id: string; name: string }[];
}

/** 今天 / 昨天 / 10 月 22 日 from a YYYY-MM-DD day. */
export function dayLabel(day: string, today = new Date()): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return '';
  const at = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const base = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((base.getTime() - at.getTime()) / 86400000);
  if (days === 0) return '今天';
  if (days === 1) return '昨天';
  return `${at.getMonth() + 1} 月 ${at.getDate()} 日`;
}
