import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router';
import type { HTMLMotionProps } from 'motion/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { DragDismiss } from '../components/motion';
import {
  ConfirmProvider,
  IconButton,
  ToastViewport,
  TooltipProvider,
  toast,
} from '../components/ui';

const { dragStart, divProps, reducedMotion } = vi.hoisted(() => ({
  dragStart: vi.fn(),
  divProps: vi.fn<(props: HTMLMotionProps<'div'>) => void>(),
  reducedMotion: vi.fn(() => false),
}));
vi.mock('motion/react', async (original) => {
  const actual = await original<typeof import('motion/react')>();
  const { createElement, forwardRef } = await import('react');
  const observedDiv = forwardRef<HTMLDivElement, HTMLMotionProps<'div'>>(
    (props, ref) => {
      divProps(props);
      return createElement(actual.motion.div, { ...props, ref });
    },
  );
  return {
    ...actual,
    useReducedMotion: reducedMotion,
    useDragControls: vi.fn(() => {
      const controls = actual.useDragControls();
      controls.start = dragStart;
      return controls;
    }),
    motion: new Proxy(actual.motion, {
      get: (target, key) =>
        key === 'div' ? observedDiv : Reflect.get(target, key),
    }),
  };
});
vi.mock('../stores/status', () => ({
  startStatusPolling: vi.fn(),
  useStatus: (selector?: (state: { data: null; error: null }) => unknown) =>
    selector
      ? selector({ data: null, error: null })
      : { data: null, error: null },
}));

beforeEach(() => {
  reducedMotion.mockReturnValue(false);
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ counts: { sources: 1 } }))),
    ),
  );
});
function mount() {
  return render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/chat']}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="chat" element={<p>Chat destination</p>} />
              <Route path="profile" element={<p>Profile destination</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
}
it.each([375, 390, 767])(
  'shows fixed bottom tabs instead of a drawer at %spx, with touch navigation and active state',
  async (width) => {
    vi.stubGlobal('innerWidth', width);
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({
        matches: query === '(max-width: 767px)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    mount();
    const tabs = await screen.findByRole('navigation', { name: '底部导航' });
    expect(tabs).toHaveClass('fixed', 'bottom-0', 'mobile-tabs', 'md:hidden');
    expect(
      within(tabs)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['聊天', '档案']);
    expect(within(tabs).getByRole('link', { name: '聊天' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(within(tabs).getByRole('link', { name: '聊天' })).toHaveClass(
      'min-h-11',
      'bg-primary',
      'text-canvas',
    );
    expect(
      screen.queryByRole('button', { name: '打开导航' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('navigation', { name: '主导航' }),
    ).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.pointer([
      {
        keys: '[TouchA>]',
        target: within(tabs).getByRole('link', { name: '档案' }),
      },
      { keys: '[/TouchA]' },
    ]);
    await screen.findByText('Profile destination');
    expect(within(tabs).getByRole('link', { name: '档案' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await user.click(within(tabs).getByRole('link', { name: '聊天' }));
    await screen.findByText('Chat destination');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  },
);
it.each([768, 1024, 1280, 1440])(
  'shows the slim rail at %spx',
  async (width) => {
    vi.stubGlobal('innerWidth', width);
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    const view = mount();
    const nav = await screen.findByRole('navigation', { name: '主导航' });
    expect(within(nav).getAllByRole('link')).toHaveLength(2);
    expect(view.container.querySelector('.nav-rail')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '切换分身' })).toBeVisible();
    expect(
      screen.queryByRole('button', { name: /收起侧栏|展开侧栏/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('navigation', { name: '底部导航' }),
    ).not.toBeInTheDocument();
  },
);
function latestDragProps(axis: 'x' | 'y') {
  return [...divProps.mock.calls]
    .reverse()
    .find(([props]) => props.drag === axis)![0];
}
it('forwards IconButton ref, click, pointer props, and attributes to the button', async () => {
  const ref = createRef<HTMLButtonElement>();
  const click = vi.fn();
  const pointerDown = vi.fn();
  render(
    <IconButton
      ref={ref}
      label="Close"
      onClick={click}
      onPointerDown={pointerDown}
      data-testid="icon-button"
    >
      <span>icon</span>
    </IconButton>,
  );
  const button = screen.getByRole('button', { name: 'Close' });
  expect(ref.current).toBe(button);
  expect(button).toHaveAttribute('data-testid', 'icon-button');
  await userEvent.setup().click(button);
  expect(click).toHaveBeenCalledOnce();
  expect(pointerDown).toHaveBeenCalledOnce();
});
it('keeps the toast close button tappable without starting a drag', async () => {
  render(<ToastViewport />);
  act(() => {
    toast('Touch notification', 'info', 0);
  });
  expect(latestDragProps('x').dragListener).toBe(false);
  fireEvent.pointerDown(
    screen.getByText('Touch notification', { selector: 'p' }),
    { pointerType: 'touch' },
  );
  expect(dragStart).toHaveBeenCalledOnce();
  dragStart.mockClear();
  const close = screen.getByRole('button', { name: '关闭通知' });
  await userEvent
    .setup()
    .pointer([
      { keys: '[TouchA>]', target: close.querySelector('svg')! },
      { keys: '[/TouchA]' },
    ]);
  expect(dragStart).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(
      screen.queryByRole('button', { name: '关闭通知' }),
    ).not.toBeInTheDocument(),
  );
});
it('skips interactive children in DragDismiss and preserves their clicks', async () => {
  const click = vi.fn();
  render(
    <DragDismiss onDismiss={vi.fn()}>
      <button onClick={click}>
        <span>Close card</span>
      </button>
      <a href="#card">Card link</a>
      <input aria-label="Card input" />
    </DragDismiss>,
  );
  fireEvent.pointerDown(screen.getByText('Close card'), {
    pointerType: 'touch',
  });
  fireEvent.pointerDown(screen.getByRole('link'), { pointerType: 'touch' });
  fireEvent.pointerDown(screen.getByRole('textbox'), { pointerType: 'touch' });
  await userEvent.setup().click(screen.getByRole('button'));
  expect(dragStart).not.toHaveBeenCalled();
  expect(click).toHaveBeenCalledOnce();
});
