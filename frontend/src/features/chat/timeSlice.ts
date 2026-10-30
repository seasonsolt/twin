/** 时间切片 (docs/PRODUCT_PERSONA_AGENT.md P2.1): the person talks with themself as of a year gone by. */

/** The day a year chosen to look back to stands for: its last. */
export const yearEnd = (year: number) => `${year}-12-31`;

/** The years a conversation can look back to, newest first: from the first one anything is known of to last year
 * (this year is the person as they are), and the one it looks back to now, whatever that is. */
export function lookBackYears(
  since: number | null,
  current: number | null,
  thisYear: number,
): number[] {
  const years = new Set<number>();
  if (since !== null) for (let y = thisYear - 1; y >= since; y--) years.add(y);
  if (current !== null) years.add(current);
  return [...years].sort((a, b) => b - a);
}
