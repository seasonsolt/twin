import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  Button,
  ConfirmProvider,
  Switch,
  Tabs,
  Textarea,
  ToastViewport,
  toast,
  useConfirm,
} from '../components/ui';

function ConfirmDemo({ result }: { result: (confirmed: boolean) => void }) {
  const confirm = useConfirm();
  return (
    <Button
      onClick={async () =>
        result(
          await confirm({
            title: '确认示例',
            body: '仅测试，不会删除数据',
            confirmLabel: '确定',
            tone: 'danger',
          }),
        )
      }
    >
      打开确认
    </Button>
  );
}

describe('confirmation', () => {
  it.each([
    ['确定', true],
    ['取消', false],
    ['关闭', false],
  ] as const)('resolves %s as %s', async (label, value) => {
    const result = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmProvider>
        <ConfirmDemo result={result} />
      </ConfirmProvider>,
    );
    const trigger = screen.getByRole('button', { name: '打开确认' });
    await user.click(trigger);
    expect(
      screen.getByRole('dialog', { name: '确认示例' }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: label }));
    await waitFor(() => expect(result).toHaveBeenCalledWith(value));
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('cancels with Escape', async () => {
    const result = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmProvider>
        <ConfirmDemo result={result} />
      </ConfirmProvider>,
    );
    await user.click(screen.getByText('打开确认'));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(result).toHaveBeenCalledWith(false));
  });

  it('settles an outstanding promise when the provider unmounts', async () => {
    const result = vi.fn();
    const user = userEvent.setup();
    const view = render(
      <ConfirmProvider>
        <ConfirmDemo result={result} />
      </ConfirmProvider>,
    );
    await user.click(screen.getByText('打开确认'));
    view.unmount();
    await waitFor(() => expect(result).toHaveBeenCalledWith(false));
  });
});

it('does not send while composing, with Shift, or on IME keyCode 229', () => {
  const send = vi.fn();
  render(<Textarea aria-label="消息" onSend={send} />);
  const textarea = screen.getByRole('textbox');
  fireEvent.compositionStart(textarea);
  fireEvent.keyDown(textarea, { key: 'Enter', isComposing: true });
  fireEvent.keyDown(textarea, { key: 'Enter' });
  fireEvent.compositionEnd(textarea);
  fireEvent.keyDown(textarea, { key: 'Enter', keyCode: 229 });
  fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
  expect(send).not.toHaveBeenCalled();
  fireEvent.keyDown(textarea, { key: 'Enter' });
  expect(send).toHaveBeenCalledOnce();
});

it('switches tabs with pointer and keyboard and skips disabled tabs', async () => {
  const user = userEvent.setup();
  render(
    <Tabs
      items={[
        { value: 'a', label: '概览', content: '概览内容' },
        { value: 'b', label: '详情', content: '详情内容' },
        { value: 'c', label: '不可用', disabled: true, content: '隐藏内容' },
      ]}
    />,
  );
  expect(screen.getByRole('tabpanel')).toHaveTextContent('概览内容');
  await user.click(screen.getByRole('tab', { name: '详情' }));
  expect(screen.getByRole('tabpanel')).toHaveTextContent('详情内容');
  await user.keyboard('{ArrowRight}');
  expect(screen.getByRole('tab', { name: '概览' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
});

it('handles loading and disabled buttons', async () => {
  const click = vi.fn();
  const user = userEvent.setup();
  render(
    <>
      <Button loading onClick={click}>
        处理中
      </Button>
      <Button disabled onClick={click}>
        不可用
      </Button>
    </>,
  );
  await user.click(screen.getByText('处理中'));
  await user.click(screen.getByText('不可用'));
  expect(click).not.toHaveBeenCalled();
  expect(screen.getByText('处理中')).toHaveAttribute('aria-busy', 'true');
});

it('toggles a switch via its label', async () => {
  function Demo() {
    const [checked, setChecked] = useState(false);
    return (
      <Switch label="设置" checked={checked} onCheckedChange={setChecked} />
    );
  }
  render(<Demo />);
  await userEvent.setup().click(screen.getByText('设置'));
  expect(screen.getByRole('switch')).toBeChecked();
});

it('announces and closes a toast', async () => {
  render(<ToastViewport />);
  act(() => {
    toast('操作已完成', 'success', 0);
  });
  expect(screen.getByRole('status')).toHaveTextContent('操作已完成');
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '关闭通知' }));
  await waitFor(() =>
    expect(
      screen.queryByRole('button', { name: '关闭通知' }),
    ).not.toBeInTheDocument(),
  );
});
