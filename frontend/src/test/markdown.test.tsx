import { render, screen } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { MessageText, markdownBlocks } from '../features/chat/MessageText';
import { stripMarkdown } from '../features/chat/markdownText';
import { ChatStage } from '../features/chat/ChatStage';

const renderMarkdown = vi.hoisted(() => vi.fn());
vi.mock('react-markdown', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-markdown')>();
  return {
    ...actual,
    default: (props: ComponentProps<typeof actual.default>) => {
      renderMarkdown(props.children);
      return <actual.default {...props} />;
    },
  };
});

const richText = `### 小标题

## 大标题

段落 **重点**和*轻声*，用\`命令\`。

1. 第一步
2. 第二步
   - 子项目

> 引用一段话。

| 方案 | 成本 |
| --- | --- |
| 甲 | 低 |

\`\`\`sh
echo hello

printf world
\`\`\`

---`;

describe('chat Markdown', () => {
  it('renders supported blocks, nested lists and capped headings', () => {
    const { container } = render(<MessageText text={richText} />);
    expect(container.querySelector('h1, h2, h5, h6')).toBeNull();
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent(
      '小标题',
    );
    expect(screen.getByRole('heading', { level: 4 })).toHaveTextContent(
      '大标题',
    );
    expect(container.querySelector('strong')).toHaveTextContent('重点');
    expect(container.querySelector('em')).toHaveTextContent('轻声');
    expect(container.querySelector('ol ul li')).toHaveTextContent('子项目');
    expect(container.querySelector('blockquote')).toHaveTextContent(
      '引用一段话。',
    );
    expect(screen.getByRole('table')).toHaveTextContent('方案成本甲低');
    expect(screen.getByRole('region', { name: '对比表格' })).toHaveAttribute(
      'tabindex',
      '0',
    );
    expect(container.querySelector('pre code')).toHaveTextContent('echo hello');
    expect(container.querySelector('hr')).not.toBeNull();
  });

  it('handles nested emphasis without treating its closing triple marker as unfinished', () => {
    const { container } = render(
      <MessageText text={'*轻声 **重点***'} streaming />,
    );
    expect(container.querySelector('em strong')).toHaveTextContent('重点');
  });

  it('drops raw HTML, neutralises unsafe URLs and shows image alt text only', () => {
    const { container } = render(
      <MessageText
        text={`<img src=x onerror=alert(1)>

<script>alert(1)</script>

[坏链接](javascript:alert%281%29) [数据](data:text/html,boom) [相对](/api)

[网站](https://example.com) [邮件](mailto:test@example.com)

![肖像](https://example.com/a.png)`}
      />,
    );
    expect(container.querySelector('img, script')).toBeNull();
    expect(container.innerHTML).not.toContain('onerror');
    expect(container.querySelectorAll('a')).toHaveLength(2);
    for (const link of screen.getAllByRole('link')) {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer nofollow');
    }
    expect(screen.getByText('坏链接')).not.toHaveAttribute('href');
    expect(screen.getByText('肖像')).toBeInTheDocument();
  });

  it.each([
    '**未完',
    '**未完*',
    '*未完',
    '`未完',
    '[链接](https://exa',
    '```js\nconst x = 1;',
    '| 甲 | 乙 |\n| --- | --- |',
  ])('leaves unfinished syntax literal while streaming: %s', (text) => {
    const { container } = render(<MessageText text={text} streaming />);
    expect(container.querySelector('strong, em, a, pre, table')).toBeNull();
    expect(container.querySelector('.message-pending')?.textContent).toBe(text);
  });

  it('transitions from partial fences and table rows only when complete', () => {
    const view = render(<MessageText text={'```sh\necho'} streaming />);
    view.rerender(<MessageText text={'```sh\necho ok\n```'} streaming />);
    expect(view.container.querySelector('pre')).toHaveTextContent('echo ok');
    view.rerender(
      <MessageText
        text={'| 甲 | 乙 |\n| --- | --- |\n| 一 | 二 |'}
        streaming
      />,
    );
    expect(view.container.querySelector('table')).not.toBeNull();
    expect(view.container.querySelectorAll('td')).toHaveLength(0);
    expect(view.container.querySelector('.message-pending')).toHaveTextContent(
      '| 一 | 二 |',
    );
    view.rerender(
      <MessageText
        text={'| 甲 | 乙 |\n| --- | --- |\n| 一 | 二 |\n'}
        streaming
      />,
    );
    expect(view.container.querySelectorAll('td')).toHaveLength(2);
    const table = view.container.querySelector('table');
    renderMarkdown.mockClear();
    for (const row of ['| 三', '| 三 | 半', '| 三 | 半写']) {
      view.rerender(
        <MessageText
          text={`| 甲 | 乙 |\n| --- | --- |\n| 一 | 二 |\n${row}`}
          streaming
        />,
      );
      expect(view.container.querySelector('table')).toBe(table);
      expect(view.container.querySelectorAll('td')).toHaveLength(2);
      expect(
        view.container.querySelector('.message-pending')?.textContent,
      ).toBe(row);
    }
    expect(renderMarkdown).not.toHaveBeenCalled();
  });

  it('keeps fences and loose/nested lists together and reuses completed DOM', () => {
    expect(markdownBlocks('```\na\n\nb\n```\n\n尾部')).toHaveLength(2);
    expect(markdownBlocks('- 一\n\n  - 子项\n\n- 二\n\n尾部')).toHaveLength(2);
    renderMarkdown.mockClear();
    const view = render(<MessageText text={'**完成**\n\n尾部'} streaming />);
    const completed = view.container.querySelector('strong');
    for (const suffix of ['一', '二', '三']) {
      view.rerender(
        <MessageText text={`**完成**\n\n尾部${suffix}`} streaming />,
      );
      expect(view.container.querySelector('strong')).toBe(completed);
    }
    expect(
      renderMarkdown.mock.calls.filter(([text]) => text === '**完成**\n'),
    ).toHaveLength(1);
  });

  it('displays plain voice and video captions on the stage', () => {
    const props = {
      name: '测试人',
      capabilities: null,
      videoPlaying: false,
      voiceCaption: '**重点**和`命令`。',
      level: 0,
      speaking: false,
      onToggle: vi.fn(),
      onVideoPlaying: vi.fn(),
      onVideoError: vi.fn(),
      onClear: vi.fn(),
    };
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
    const view = render(<ChatStage {...props} />);
    expect(screen.getByTestId('stage-caption')).toHaveTextContent(
      '重点和命令。',
    );
    view.rerender(
      <ChatStage
        {...props}
        videoPlaying
        turn={{
          id: 'video',
          role: 'twin',
          content: '**视频重点**。',
          timestamp: '2026-01-01',
        }}
        videoState={{
          status: 'done',
          result: {
            file: `${'a'.repeat(64)}.mp4`,
            duration_s: 5,
            warnings: [],
          },
        }}
      />,
    );
    expect(screen.getByTestId('stage-caption')).toHaveTextContent('视频重点。');
  });

  it('strips Markdown for plain stage captions, reading cells and skipping code', () => {
    const text = stripMarkdown(richText);
    expect(text).toContain('段落 重点和轻声，用命令。');
    expect(text).toContain('方案，成本\n甲，低');
    expect(text).toContain('（代码略）');
    expect(text).not.toMatch(/echo|printf|\*|###|\|/u);
    expect(
      stripMarkdown('![图片](https://example.com) [来源](https://example.com)'),
    ).toBe('图片 来源');
    expect(stripMarkdown('<script>坏内容</script>')).toBe('');
  });
});
