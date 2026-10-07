import type { ReactNode } from 'react';

export function MessageText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split(/\r\n?|\n/);
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index].trim();
    if (!line) continue;
    const kind = /^\d+\.\s*/u.test(line)
      ? 'number'
      : /^-\s+/u.test(line)
        ? 'bullet'
        : /^第[一二三四五六七八九十百零两\d]+步/u.test(line)
          ? 'step'
          : null;
    if (!kind) {
      blocks.push(<p key={index}>{line}</p>);
      continue;
    }
    const pattern =
      kind === 'number'
        ? /^(\d+)\.\s*(.*)$/u
        : kind === 'bullet'
          ? /^-\s+(.*)$/u
          : /^(第[一二三四五六七八九十百零两\d]+步.*)$/u;
    const start = index;
    const items: ReactNode[] = [];
    while (index < lines.length) {
      const match = lines[index].trim().match(pattern);
      if (!match) break;
      items.push(
        <li
          key={index}
          value={kind === 'number' ? Number(match[1]) : undefined}
        >
          {kind === 'number' ? match[2] : match[1]}
        </li>,
      );
      index++;
    }
    index--;
    blocks.push(
      kind === 'bullet' ? (
        <ul key={start} className="list-disc pl-6">
          {items}
        </ul>
      ) : (
        <ol
          key={start}
          className={kind === 'step' ? 'list-none' : 'list-decimal pl-6'}
          start={
            kind === 'number' ? Number(line.match(/^\d+/u)?.[0]) : undefined
          }
        >
          {items}
        </ol>
      ),
    );
  }
  return <div className="message-text space-y-3">{blocks}</div>;
}
