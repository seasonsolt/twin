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
import type { HTMLMotionProps, PanInfo } from 'motion/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { AppShell } from '../components/layout/AppShell';
import { DragDismiss } from '../components/motion';
import {
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
  useStatus: () => ({ data: null, error: null }),
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

async function openDrawer() {
  render(
    <TooltipProvider>
      <MemoryRouter initialEntries={['/gallery']}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="gallery" element={<p>Gallery</p>} />
            <Route path="memories" element={<p>Memories destination</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </TooltipProvider>,
  );
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '打开导航' }));
  return screen.findByRole('dialog', { name: '导航' });
}

function latestDragProps(axis: 'x' | 'y') {
  return [...divProps.mock.calls]
    .reverse()
    .find(([props]) => props.drag === axis)![0];
}

it.each(['X', 'backdrop', 'navigation', 'Escape'])(
  'closes the drawer via %s',
  async (method) => {
    const dialog = await openDrawer();
    const user = userEvent.setup();
    if (method === 'X') {
      await user.pointer([
        { keys: '[TouchA>]', target: within(dialog).getByRole('button') },
        { keys: '[/TouchA]' },
      ]);
    } else if (method === 'backdrop') {
      const overlay = document.querySelector('.backdrop-blur-sm')!;
      // A click alone must close even without Radix's outside-pointer handler.
      fireEvent.click(overlay);
    } else if (method === 'navigation') {
      await user.pointer([
        {
          keys: '[TouchA>]',
          target: within(dialog).getByRole('link', { name: '记忆' }),
        },
        { keys: '[/TouchA]' },
      ]);
      await waitFor(() =>
        expect(screen.getByText('Memories destination')).toBeVisible(),
      );
    } else {
      await user.keyboard('{Escape}');
    }
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    expect(dragStart).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '打开导航' })).toHaveFocus();
  },
);

it('starts drawer drag only on the grab handle and header, not controls or content', async () => {
  const dialog = await openDrawer();
  const props = latestDragProps('y');
  expect(props.dragListener).toBe(false);
  expect(props.dragControls).toBeDefined();
  expect(props.style?.touchAction).toBeUndefined();
  const header = dialog.querySelector('.touch-none')!;
  const handle = header.querySelector('[aria-hidden]')!;
  fireEvent.pointerDown(handle, { pointerType: 'touch' });
  fireEvent.pointerDown(within(dialog).getByRole('heading'), {
    pointerType: 'touch',
  });
  expect(dragStart).toHaveBeenCalledTimes(2);
  dragStart.mockClear();
  for (const target of [
    dialog,
    within(dialog).getByRole('button'),
    within(dialog).getByRole('button').querySelector('svg')!,
    within(dialog).getByRole('link', { name: '记忆' }),
  ]) {
    fireEvent.pointerDown(target, { pointerType: 'touch' });
  }
  expect(dragStart).not.toHaveBeenCalled();
});

it.each([
  [101, 0, true],
  [50, 650, true],
  [50, 500, false],
  [-101, -650, false],
])(
  'drawer drag offset %s velocity %s dismisses: %s',
  async (offset, velocity, dismisses) => {
    await openDrawer();
    const props = latestDragProps('y');
    act(() => {
      props.onDragEnd!(new MouseEvent('pointerup'), {
        offset: { x: 0, y: offset },
        velocity: { x: 0, y: velocity },
      } as PanInfo);
    });
    if (dismisses) {
      await waitFor(() =>
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
      );
    } else {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    }
  },
);

it('does not start drawer drag with reduced motion', async () => {
  reducedMotion.mockReturnValue(true);
  const dialog = await openDrawer();
  fireEvent.pointerDown(within(dialog).getByRole('heading'), {
    pointerType: 'touch',
  });
  expect(dragStart).not.toHaveBeenCalled();
});

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
    {
      pointerType: 'touch',
    },
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
