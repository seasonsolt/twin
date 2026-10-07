import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';

const parser = unified().use(remarkParse).use(remarkGfm);
interface TextNode {
  type: string;
  value?: string;
  alt?: string | null;
  children?: TextNode[];
}

function plainText(node: TextNode): string {
  if (node.type === 'code') return '（代码略）';
  if (['html', 'definition', 'thematicBreak'].includes(node.type)) return '';
  if (node.type === 'image') return node.alt ?? '';
  if (node.type === 'break') return '\n';
  if (node.value !== undefined) return node.value;
  const separator = [
    'root',
    'list',
    'listItem',
    'blockquote',
    'table',
  ].includes(node.type)
    ? '\n'
    : node.type === 'tableRow'
      ? '，'
      : '';
  return (node.children ?? []).map(plainText).filter(Boolean).join(separator);
}

export function stripMarkdown(text: string): string {
  return plainText(parser.parse(text)).trim();
}
