import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter } from 'react-router';
import { expect, it, vi } from 'vitest';
import {
  ActionMenu,
  Segmented,
  Tabs,
  Text,
  TooltipProvider,
} from '../components/ui';
import { UploadList } from '../features/library/UploadList';

vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const modes = [
  { id: 'ask', label: '问答' },
  { id: 'work', label: '交代任务' },
] as const;

/** Like the conversation page: each mode has its own thread, so the switch is made anew when the mode changes. */
function Modes() {
  const [mode, setMode] = useState<'ask' | 'work'>('ask');
  const switcher = (
    <Segmented
      label="这条消息是"
      value={mode}
      options={modes}
      onChange={setMode}
    />
  );
  return mode === 'ask' ? (
    <section aria-label="问答线程">{switcher}</section>
  ) : (
    <article aria-label="任务线程">{switcher}</article>
  );
}

it('keeps the focus on the chosen mode after the arrow keys when the switch is made anew', async () => {
  const user = userEvent.setup();
  render(<Modes />);
  screen.getByRole('radio', { name: '问答' }).focus();
  await user.keyboard('{ArrowRight}');
  await waitFor(() =>
    expect(screen.getByRole('radio', { name: '交代任务' })).toHaveFocus(),
  );
  expect(screen.getByRole('radio', { name: '交代任务' })).toBeChecked();
  await user.keyboard('{ArrowLeft}');
  await waitFor(() =>
    expect(screen.getByRole('radio', { name: '问答' })).toHaveFocus(),
  );
});

it('keeps what was written in a tab that keeps its content, and makes the others anew', async () => {
  const user = userEvent.setup();
  function Draft({ name }: { name: string }) {
    const [text, setText] = useState('');
    return (
      <input
        aria-label={name}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
    );
  }
  render(
    <Tabs
      label="章节"
      items={[
        {
          value: 'a',
          label: '回复',
          keep: true,
          content: <Draft name="回复草稿" />,
        },
        { value: 'b', label: '别处', content: <Draft name="别处草稿" /> },
      ]}
    />,
  );
  await user.type(screen.getByLabelText('回复草稿'), '先这样');
  await user.click(screen.getByRole('tab', { name: '别处' }));
  await user.type(screen.getByLabelText('别处草稿'), '随手写');
  // The one that keeps is hidden, not gone.
  expect(screen.getByLabelText('回复草稿')).not.toBeVisible();
  await user.click(screen.getByRole('tab', { name: '回复' }));
  expect(screen.getByLabelText('回复草稿')).toHaveValue('先这样');
  await user.click(screen.getByRole('tab', { name: '别处' }));
  expect(screen.getByLabelText('别处草稿')).toHaveValue('');
});

it('gives the focus back to the "⋯" a choice was made from, as the list closes', async () => {
  const user = userEvent.setup();
  const chosen = vi.fn();
  render(
    <ActionMenu label="更多" items={[{ label: '形象', onSelect: chosen }]} />,
  );
  await user.click(screen.getByLabelText('更多'));
  await user.click(screen.getByRole('button', { name: '形象' }));
  expect(chosen).toHaveBeenCalledOnce();
  expect(screen.getByLabelText('更多')).toHaveFocus();
});

it('puts the whole of text cut short in its hover, however it is made up', () => {
  render(
    <TooltipProvider>
      <Text twoLines>很长的一句话</Text>
      <Text twoLines data-testid="parts">
        第{2}条，<strong>要紧</strong>的在后面
      </Text>
    </TooltipProvider>,
  );
  expect(screen.getByText('很长的一句话')).toHaveAttribute(
    'title',
    '很长的一句话',
  );
  expect(screen.getByTestId('parts')).toHaveAttribute(
    'title',
    '第2条，要紧的在后面',
  );
});

it('lists a stopped upload as waiting to be added again, not as failed', () => {
  render(
    <MemoryRouter>
      <UploadList
        picks={[{ file: new File(['a'], '周会.m4a'), stopped: true }]}
        uploading={false}
        onStop={() => {}}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText('已停止，再选一次接着传')).toBeVisible();
  expect(screen.queryByRole('progressbar')).toBeNull();
});
