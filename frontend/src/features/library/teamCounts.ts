// What the team page counts, kept apart from the page so the side bar shows the same numbers without loading it.
import type { Recording } from '../../pages/Library';
import type { Person } from '../../pages/Recording';
import type { Persona } from '../../stores/personas';

/** The lists of the review queue that come a page at a time (``review_queue.page``): voices by when they are
 * asked, speakers someone said are not them, recordings settled one by one, and suspect confirmed speakers. */
export type Paged =
  'voices' | 'enough' | 'strangers' | 'items' | 'unsorted' | 'suspects';

/** How many each paged list holds in all, and how long its voices speak; a list without one came whole. */
export type ReviewTotals = Partial<
  Record<Paged, { count: number; seconds?: number }>
>;

/** The review queue with the first so many of each paged list (none unless asked for): asking again with more keeps
 * every list of one reading, so nothing is skipped or shown twice when a decision reorders them. */
export const reviewPath = (first: Partial<Record<Paged, number>> = {}) =>
  `/api/library/review?${new URLSearchParams({
    voices: String(first.voices ?? 0),
    enough: String(first.enough ?? 0),
    strangers: String(first.strangers ?? 0),
    items: String(first.items ?? 0),
    unsorted: String(first.unsorted ?? 0),
    suspects: String(first.suspects ?? 0),
  } satisfies Record<Paged, string>).toString()}`;

/** The review queue's lists, as far as counting needs them (``/api/library/review``). */
export interface ReviewLists {
  items: unknown[];
  voices: unknown[];
  fragments: unknown[];
  unsorted: unknown[];
  // Confirmed speakers some of whose speech sounds like someone else: optional, so never counted as waiting.
  suspects?: unknown[];
  totals?: ReviewTotals;
}

/** How many a paged list holds in all: its total, else (it came whole) as many as came. */
export const inAll = (
  review: Pick<ReviewLists, 'totals'>,
  list: Paged,
  loaded: number,
) => review.totals?.[list]?.count ?? loaded;

/** The team's roster as the page shows it: the people the viewer looks after or can talk to, not the voices still
 * waiting for a name. */
export const namedPeople = (people: Person[]) =>
  people.filter(
    (p) =>
      !p.auto &&
      (p.can_manage !== false || p.persona_id || p.talk || p.self_claimed),
  );

/** Twins no recording belongs to (made by hand, or someone else's public twin): rows of the team table like the
 * people found in the meetings. */
export const looseTwins = (people: Person[], twins: Persona[]) => {
  const linked = new Set(people.map((p) => p.persona_id));
  return twins.filter((twin) => !linked.has(twin.id));
};

/** How many rows the team table has: the people and the twins no recording belongs to. */
export const memberCount = (people: Person[], twins: Persona[]) =>
  namedPeople(people).length + looseTwins(people, twins).length;

/** New voices waiting for a name, among those the viewer may settle (recordings they uploaded, or all for an
 * administrator). */
export const unnamedPeople = (people: Person[]) =>
  people.filter((p) => p.auto && p.can_manage !== false);

/** Pairs of people the merge of two libraries could not tell apart, each pair once. */
export const similarPairs = (people: Person[]) => {
  const byId = new Map(people.map((p) => [p.id, p]));
  return people.flatMap((p) =>
    (p.similar ?? [])
      .filter((id) => p.id < id && byId.has(id))
      .map((id) => [p, byId.get(id)!] as const),
  );
};

/** People whose twin a colleague sent back as not theirs. */
export const disownedPeople = (named: Person[], twins: Persona[]) =>
  named.filter((p) => twins.find((t) => t.id === p.persona_id)?.claim_rejected);

/** How many things wait for the owner: every kind on the 待处理 tab except those that harm nobody while they wait. */
export function waitingCount({
  people,
  review,
  recordings,
  twins,
}: {
  people: Person[];
  review: ReviewLists;
  recordings: Recording[];
  twins: Persona[];
}) {
  return (
    unnamedPeople(people).length +
    (review.totals
      ? inAll(review, 'voices', 0) +
        inAll(review, 'enough', 0) +
        inAll(review, 'strangers', 0)
      : review.voices.length) +
    (review.fragments.length ? 1 : 0) +
    similarPairs(people).length +
    inAll(review, 'items', review.items.length) +
    inAll(review, 'unsorted', review.unsorted.length) +
    recordings.filter((r) => r.status === 'failed').length +
    disownedPeople(namedPeople(people), twins).length
  );
}
