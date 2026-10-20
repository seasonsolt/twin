/** People's names in the order of their pinyin, so a surname is found where the owner expects it (安, 李, 王, 张). */
const collator = new Intl.Collator('zh-CN');

export const byName = (a: string, b: string) => collator.compare(a, b);

/** A copy of ``items`` ordered by name, for choosing someone from a list. */
export function sortByName<T>(
  items: readonly T[],
  name: (item: T) => string,
): T[] {
  return [...items].sort((a, b) => byName(name(a), name(b)));
}
