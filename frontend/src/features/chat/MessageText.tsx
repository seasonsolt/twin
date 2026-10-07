import { memo, useMemo } from 'react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

const plugins = [remarkGfm];
const components: Components = {
  h1: ({ children }) => <h4>{children}</h4>,
  h2: ({ children }) => <h4>{children}</h4>,
  h5: ({ children }) => <h4>{children}</h4>,
  h6: ({ children }) => <h4>{children}</h4>,
  a: ({ href, children }) =>
    href ? (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
  img: ({ alt }) => <span>{alt}</span>,
  table: ({ children }) => (
    <div
      className="message-table"
      tabIndex={0}
      role="region"
      aria-label="对比表格"
    >
      <table>{children}</table>
    </div>
  ),
};

function safeUrl(url: string) {
  return /^(?:https?:\/\/|mailto:)/iu.test(url) ? url : '';
}

function fenceLine(line: string) {
  return line.replace(/^\s*(?:>\s*)*/u, '').match(/^(`{3,}|~{3,})(.*)$/u);
}

// Blank lines inside fences and loose/nested lists do not complete a block.
export function markdownBlocks(text: string): string[] {
  const lines = text.replace(/\r\n?/gu, '\n').split('\n');
  const blocks: string[] = [];
  let start = 0;
  let fence = '';
  let list = false;
  for (let i = 0; i < lines.length; i++) {
    const match = fenceLine(lines[i]);
    if (match) {
      if (!fence) fence = match[1];
      else if (
        match[1][0] === fence[0] &&
        match[1].length >= fence.length &&
        !match[2].trim()
      )
        fence = '';
    }
    if (/^\s*(?:[-+*]|\d+[.)])\s/u.test(lines[i])) list = true;
    if (lines[i].trim() || fence) continue;
    if (i + 1 < lines.length && !lines[i + 1].trim()) continue;
    const next = lines[i + 1] ?? '';
    if (list && /^(?:\s+|(?:[-+*]|\d+[.)])\s)/u.test(next)) continue;
    const block = lines.slice(start, i + 1).join('\n');
    if (block.trim()) blocks.push(block);
    start = i + 1;
    list = false;
  }
  const tail = lines.slice(start).join('\n');
  if (tail.trim()) blocks.push(tail);
  return blocks;
}

function tableSeparator(line: string) {
  return (
    line.includes('|') &&
    line
      .trim()
      .replace(/^\||\|$/gu, '')
      .split('|')
      .every((cell) => /^\s*:?-{3,}:?\s*$/u.test(cell))
  );
}

function incomplete(text: string, streaming: boolean) {
  let fence = '';
  for (const line of text.split('\n')) {
    const match = fenceLine(line);
    if (!match) continue;
    if (!fence) fence = match[1];
    else if (
      match[1][0] === fence[0] &&
      match[1].length >= fence.length &&
      !match[2].trim()
    )
      fence = '';
  }
  if (fence) return true;
  if (
    streaming &&
    !text.endsWith('\n') &&
    tableSeparator(text.split('\n').at(-1) ?? '')
  )
    return true;
  // CommonMark already leaves most unfinished syntax literal. Avoid its partial
  // emphasis fallback (e.g. **word*) and partial link/image labels while typing.
  const inline = text
    .replace(/(`+)[\s\S]*?\1/gu, '')
    .replace(/\\./gu, '')
    .replace(/^\s*(?:[-+*]|\d+[.)])\s/gmu, '');
  const stack: { marker: string; width: number }[] = [];
  for (const match of inline.matchAll(/\*+|_+/gu)) {
    const before = inline[match.index - 1] ?? ' ';
    const after = inline[match.index + match[0].length] ?? ' ';
    const marker = match[0][0];
    if (
      marker === '_' &&
      /[\p{L}\p{N}]/u.test(before) &&
      /[\p{L}\p{N}]/u.test(after)
    )
      continue;
    let width = match[0].length;
    if (/\S/u.test(before)) {
      while (width && stack.at(-1)?.marker === marker) {
        const opening = stack.at(-1)!;
        const consumed = Math.min(width, opening.width);
        width -= consumed;
        opening.width -= consumed;
        if (!opening.width) stack.pop();
      }
    }
    if (width && /\S/u.test(after)) stack.push({ marker, width });
  }
  return (
    stack.length > 0 ||
    (inline.match(/`/gu)?.length ?? 0) % 2 !== 0 ||
    (inline.match(/\[/gu)?.length ?? 0) > (inline.match(/\]/gu)?.length ?? 0) ||
    /\]\([^)]*$/u.test(inline)
  );
}

const RenderedMarkdown = memo(function RenderedMarkdown({
  text,
}: {
  text: string;
}) {
  return (
    <Markdown
      remarkPlugins={plugins}
      components={components}
      urlTransform={safeUrl}
      skipHtml
    >
      {text}
    </Markdown>
  );
});

const MarkdownBlock = memo(function MarkdownBlock({
  text,
  streaming,
}: {
  text: string;
  streaming: boolean;
}) {
  const lines = text.split('\n');
  if (streaming && !text.endsWith('\n') && !lines.some(fenceLine)) {
    const separator = lines.findIndex(
      (line, index) => index > 0 && tableSeparator(line),
    );
    if (separator >= 0 && separator < lines.length - 1) {
      const completeRows = `${lines.slice(0, -1).join('\n')}\n`;
      return (
        <div className="message-block">
          <RenderedMarkdown text={completeRows} />
          <div className="message-pending">{lines.at(-1)}</div>
        </div>
      );
    }
  }
  return (
    <div className="message-block">
      {incomplete(text, streaming) ? (
        <div className="message-pending">{text}</div>
      ) : (
        <RenderedMarkdown text={text} />
      )}
    </div>
  );
});

export function MessageText({
  text,
  plain = false,
  streaming = false,
}: {
  text: string;
  plain?: boolean;
  streaming?: boolean;
}) {
  const blocks = useMemo(() => markdownBlocks(text), [text]);
  return (
    <div className={`message-text${plain ? ' message-plain' : ''}`}>
      {plain
        ? text
        : blocks.map((block, index) => (
            <MarkdownBlock
              key={index}
              text={block}
              streaming={streaming && index === blocks.length - 1}
            />
          ))}
    </div>
  );
}
