import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useReducedMotion } from 'motion/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  segmentReply,
  replyUnitDelay,
} from '../components/effects/ReplyReveal';
import {
  FlowStepper,
  MessageList,
  MetricNumber,
  ReplyReveal,
  SectionReveal,
  SpotlightAction,
  ThinkingLabel,
} from '../components/effects';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

describe('reduced-motion effects', () => {
  it('renders the full reply and a single screen-reader copy immediately', () => {
    const { container } = render(
      <ReplyReveal text="完整的助手回复 without delay" />,
    );
    expect(container.querySelector('.sr-only')).toHaveTextContent(
      '完整的助手回复 without delay',
    );
    expect(container.querySelector('[aria-hidden="true"]')).toHaveTextContent(
      '完整的助手回复 without delay',
    );
    expect(container.querySelector('.blur-text')).toBeNull();
  });

  it('shows the final metric immediately, with a reserved width and accessible value', () => {
    const { container } = render(<MetricNumber value={1280} suffix="%" />);
    expect(container.querySelector('.sr-only')).toHaveTextContent('1,280%');
    expect(
      container.querySelector('[aria-hidden="true"]:not(.invisible)'),
    ).toHaveTextContent('1,280%');
    expect(container.querySelector('.invisible')).toHaveTextContent('1,280%');
  });

  it('renders a static thinking label and no animated spans', () => {
    render(<ThinkingLabel />);
    const status = screen.getByRole('status');
    expect(status.querySelector('.sr-only')).toHaveTextContent('思考中…');
    expect(status.querySelector('[aria-hidden="true"]')).toHaveTextContent(
      '思考中…',
    );
    expect(status.querySelector('[style]')).toBeNull();
  });

  it('renders message/source items without the upstream animations or staggering', () => {
    render(
      <MessageList
        label="资料"
        items={[
          { id: 'a', text: '资料 A' },
          { id: 'b', text: '资料 B' },
        ]}
      />,
    );
    const list = screen.getByRole('list', { name: '资料' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(list.querySelector('[data-index]')).toBeNull();
    expect(list.querySelector('[style]')).toBeNull();
  });

  it('disables spotlight without disabling the action', async () => {
    const onClick = vi.fn();
    const { container } = render(
      <SpotlightAction label="资料卡片" onClick={onClick}>
        查看资料
      </SpotlightAction>,
    );
    fireEvent.mouseMove(screen.getByRole('button'), {
      clientX: 20,
      clientY: 20,
    });
    expect(container.querySelector('[style]')).toBeNull();
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: '资料卡片' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('switches and completes steps without slides', async () => {
    const onComplete = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <FlowStepper
        onComplete={onComplete}
        steps={[
          { id: 'a', title: '准备', content: '第一步内容' },
          { id: 'b', title: '检查', content: '第二步内容' },
        ]}
      />,
    );
    await user.click(screen.getByRole('button', { name: '继续' }));
    expect(screen.getByText('第二步内容')).toBeVisible();
    expect(screen.queryByText('第一步内容')).not.toBeInTheDocument();
    expect(container.querySelector('[style]')).toBeNull();
    expect(
      screen.getByRole('button', { name: '第 2 步：检查' }),
    ).toHaveAttribute('aria-current', 'step');
    await user.click(screen.getByRole('button', { name: '完成' }));
    expect(onComplete).toHaveBeenCalledOnce();
    expect(screen.getByRole('status')).toHaveTextContent('已完成');
  });

  it('shows a section immediately, without GSAP styles or scroll triggers', () => {
    const { container } = render(<SectionReveal>完整区块</SectionReveal>);
    expect(screen.getByText('完整区块')).toBeVisible();
    expect(container.querySelector('.invisible, [style]')).toBeNull();
  });
});

it('keeps full text accessible while the animated reply and loading spans are aria-hidden', () => {
  vi.mocked(useReducedMotion).mockReturnValue(false);
  const { container } = render(
    <>
      <ReplyReveal text="A full assistant reply" />
      <ThinkingLabel />
      <MetricNumber value={86} suffix="%" />
    </>,
  );
  const copies = [...container.querySelectorAll('.sr-only')].map(
    (node) => node.textContent,
  );
  expect(copies).toEqual(['A full assistant reply', '思考中…', '86%']);
  for (const span of container.querySelectorAll('.blur-text span, [style]')) {
    expect(span.closest('[aria-hidden="true"]')).not.toBeNull();
  }
});

it('segments Chinese into multiple reveal units without changing visible or screen-reader text', () => {
  vi.mocked(useReducedMotion).mockReturnValue(false);
  const text = '我会先听大家的意见。 Hello world!';
  const { container } = render(<ReplyReveal text={text} />);
  expect(
    container.querySelectorAll('[data-reveal-unit]').length,
  ).toBeGreaterThan(4);
  expect(container.querySelector('.sr-only')?.textContent).toBe(text);
  expect(container.querySelector('.blur-text')?.textContent).toBe(text);
  expect(segmentReply('中文句子').length).toBeGreaterThan(1);
  expect(replyUnitDelay(1000) * 999 + 0.12).toBeLessThanOrEqual(1.200001);
});

it('falls back to CJK characters and space-delimited Latin runs', () => {
  vi.stubGlobal('Intl', { ...Intl, Segmenter: undefined });
  expect(segmentReply('中文 hello world 日本語')).toEqual([
    '中',
    '文',
    ' ',
    'hello',
    ' ',
    'world',
    ' ',
    '日',
    '本',
    '語',
  ]);
});

it('never intercepts global Tab navigation through the upstream list', () => {
  vi.mocked(useReducedMotion).mockReturnValue(false);
  render(<MessageList label="消息" items={[{ id: 'a', text: '消息 A' }]} />);
  const event = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(false);
});
