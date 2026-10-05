import { readdir, readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { ESLint } from 'eslint';
import { expect, it } from 'vitest';

it('pages use effects wrappers, never vendored sources', async () => {
  const pages = resolve('src/pages');
  for (const name of await readdir(pages)) {
    if (!/\.tsx?$/.test(name)) continue;
    expect(await readFile(join(pages, name), 'utf8')).not.toMatch(
      /(?:from\s*|import\s*\()\s*['"][^'"]*\/reactbits(?:\/|['"])/,
    );
  }
});

it('ESLint rejects relative and aliased vendor imports outside effects', async () => {
  const eslint = new ESLint();
  for (const path of [
    '../components/reactbits/BlurText',
    '@/components/reactbits/BlurText',
  ]) {
    const [result] = await eslint.lintText(
      `import BlurText from '${path}'; export default BlurText;`,
      { filePath: 'src/pages/ForbiddenFixture.tsx' },
    );
    expect(result.messages).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          ruleId: 'no-restricted-imports',
          severity: 2,
        }),
      ]),
    );
  }
  const [allowed] = await eslint.lintText(
    "import BlurText from '../reactbits/BlurText'; export default BlurText;",
    { filePath: 'src/components/effects/AllowedFixture.tsx' },
  );
  expect(allowed.errorCount).toBe(0);
});
