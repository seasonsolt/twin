import { describe, expect, it } from 'vitest';
import { byName, sortByName } from '../lib/names';

describe('names', () => {
  it('orders people by the pinyin of their surname', () => {
    expect(
      ['张总', '王小明', '李四', '安然', '欧阳峰', '赵六'].sort(byName),
    ).toEqual(['安然', '李四', '欧阳峰', '王小明', '张总', '赵六']);
  });

  it('sorts a copy, leaving the list as it was', () => {
    const people = [{ name: '许清禾' }, { name: '林舟' }];
    expect(sortByName(people, (p) => p.name).map((p) => p.name)).toEqual([
      '林舟',
      '许清禾',
    ]);
    expect(people[0].name).toBe('许清禾');
  });
});
