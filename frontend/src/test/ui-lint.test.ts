import { ESLint } from 'eslint';
import { describe, expect, it } from 'vitest';

// The style guardrails in eslint/twin-ui.js, run through the project's own eslint.config.js, so the exempt folders
// and the ban on inline disables are checked too.
const eslint = new ESLint({ cwd: process.cwd() });
async function problems(code: string, file = 'src/pages/Sample.tsx') {
  const [result] = await eslint.lintText(code, { filePath: file });
  return result.messages
    .filter(
      (message) => message.ruleId?.startsWith('twin-ui/') || !message.ruleId,
    )
    .map((message) => message.message);
}

describe('twin-ui lint rules', () => {
  it('rejects hand-made form controls and names the component to use', async () => {
    const found = await problems(
      'export const A = () => <><button>x</button><input /><select /><textarea /></>;',
    );
    expect(found).toHaveLength(4);
    expect(found[0]).toContain('Button');
    expect(found[2]).toContain('Select');
  });

  it('rejects inline styles, arbitrary values, hex colours, type sizes and radii', async () => {
    const found = await problems(`
      export const A = () => (
        <div style={{ color: 'red' }}>
          <p className="mt-[3px]">a</p>
          <p className="text-sm text-secondary">b</p>
          <p className="md:rounded-xl">c</p>
          <p className={\`flex \${'rounded-full'}\`}>d</p>
          <p className="bg-[#fff]">e</p>
        </div>
      );`);
    expect(found).toHaveLength(6);
    expect(found[0]).toContain('style');
    expect(found[1]).toContain('任意值');
    expect(found[2]).toContain('Text');
    expect(found[3]).toContain('Card');
  });

  it('checks class lists in cn() calls and in constants', async () => {
    const found = await problems(`
      import { cn } from '../lib/utils';
      const task = 'flex flex-col gap-2 rounded-xl border p-4';
      export const A = ({ on }: { on: boolean }) => <p className={cn('flex', on && 'text-lg')}>{task}</p>;`);
    expect(found).toHaveLength(2);
  });

  it('leaves layout classes, colours from the tokens and ordinary text alone', async () => {
    expect(
      await problems(`
        const label = '圆角 rounded 和 text-sm 只是文字';
        export const A = () => (
          <div className="flex min-w-0 flex-wrap items-center gap-3 text-secondary sm:grid-cols-2">{label} 共 3 条</div>
        );`),
    ).toEqual([]);
  });

  it('does not apply inside components/ui or the exempt visual folders', async () => {
    const code =
      'export const A = () => <button className="rounded-full text-sm" />;';
    expect(await problems(code, 'src/components/ui/Sample.tsx')).toEqual([]);
    expect(
      await problems(code, 'src/features/profile/graph/Sample.tsx'),
    ).toEqual([]);
    expect(await problems(code, 'src/pages/Sample.tsx')).toHaveLength(2);
  });

  it('ignores eslint-disable comments in page code', async () => {
    const found = await problems(
      '// eslint-disable-next-line twin-ui/no-raw-controls\nexport const A = () => <button />;',
    );
    expect(found.some((message) => message.includes('Button'))).toBe(true);
  });
});
