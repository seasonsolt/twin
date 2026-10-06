import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, it } from 'vitest';

it('keeps product source text free of the old technical labels', () => {
  function check(directory: string) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== 'test') check(path);
      } else if (/\.(tsx?|css)$/.test(entry.name)) {
        expect(readFileSync(path, 'utf8'), path).not.toMatch(
          /维度|细项|完成度|充分率|验证率|目标人物|推演|会议转写|传记|本人\s*\d+\s*条|支撑档案/,
        );
      }
    }
  }
  check(join(process.cwd(), 'src'));
});
