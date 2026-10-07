import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { readFileSync } from 'node:fs';
import { beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider } from '../components/ui';
import { PersonaSwitcher } from '../components/layout/PersonaSwitcher';
import { NewTwin } from '../components/layout/NewTwin';
import { Login } from '../features/auth/Login';
import { Chat } from '../pages/Chat';
import { Memories } from '../pages/Memories';
import { usePersonas } from '../stores/personas';
import { useStatus } from '../stores/status';

const css = readFileSync('src/design/tokens.css', 'utf8');
const desktopCss = css.slice(css.indexOf('@media (min-width: 1200px)'));
const persona = {
  id: 'default',
  name: '小林',
  sources: 1,
  avatar_url: '/portrait.png',
  created_at: 'now',
  is_default: true,
};

beforeEach(() => {
  sessionStorage.clear();
  usePersonas.setState({ id: 'default', items: [persona] });
  useStatus.setState({ data: null, error: null });
  vi.stubGlobal('innerWidth', 1280);
  vi.stubGlobal('innerHeight', 900);
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(min-width: 1200px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (path: string) =>
        new Response(
          JSON.stringify(
            path === '/api/personas'
              ? [persona]
              : path === '/api/persona/sources' ||
                  path.startsWith('/api/conversations?')
                ? []
                : path === '/api/status'
                  ? { target_name: '小林', counts: { sources: 1, items: 0 } }
                  : path === '/api/persona/processing'
                    ? { state: 'idle' }
                    : path === '/api/media/capabilities'
                      ? { available: false, video: { available: false } }
                      : { stale: false },
          ),
        ),
    ),
  );
});

function mount(element: React.ReactNode) {
  return render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={['/chat']}>{element}</MemoryRouter>
    </ConfirmProvider>,
  );
}

it('anchors the quick portrait switcher as a popover and restores focus on Escape', async () => {
  mount(<PersonaSwitcher />);
  const trigger = screen.getByRole('button', { name: '切换分身' });
  expect(trigger.querySelector('img')).toHaveAttribute('src', '/portrait.png');
  vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
    left: 8,
    right: 64,
    top: 820,
    bottom: 876,
    width: 56,
    height: 56,
    x: 8,
    y: 820,
    toJSON: () => ({}),
  });
  const user = userEvent.setup();
  await user.click(trigger);
  const dialog = await screen.findByRole('dialog', { name: '切换分身' });
  expect(dialog).toHaveClass('persona-popover');
  expect(dialog).toHaveStyle({
    left: '24px',
    bottom: '24px',
    width: '360px',
    translate: 'none',
  });
  await waitFor(() =>
    expect(
      within(dialog).getByRole('button', { name: /小林.*1 条记忆/ }),
    ).toBeVisible(),
  );
  await user.keyboard('{Escape}');
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
  expect(trigger).toHaveFocus();
});

it('removes centering translation for the wide fullscreen create dialog', async () => {
  mount(<NewTwin />);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: '新建分身' }));
  const dialog = screen.getByRole('dialog', { name: '新建分身' });
  expect(dialog).toHaveClass('create-twin-sheet');
  expect(dialog).toHaveStyle({ translate: 'none' });
  expect(desktopCss).toMatch(
    /\.create-twin-sheet > div:first-child\s*\{[^}]*grid-row: 1/s,
  );
  expect(desktopCss).toMatch(/\.create-twin-sheet > p\s*\{[^}]*grid-row: 2/s);
  await waitFor(() =>
    expect(
      within(dialog).getByRole('textbox', { name: '分身名字' }),
    ).toBeVisible(),
  );
  await user.keyboard('{Escape}');
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
});

it('keeps desktop stage and scrolling conversation separate with the composer inside the conversation zone', async () => {
  const view = mount(<Chat />);
  await waitFor(() =>
    expect(view.container.querySelector('.chat-stage')).toHaveAttribute(
      'data-desktop',
      'true',
    ),
  );
  const thread = view.container.querySelector('.chat-thread')!;
  expect(
    thread.querySelector('.chat-scroll .chat-conversation'),
  ).toBeInTheDocument();
  expect(
    within(thread as HTMLElement).getByRole('form', { name: '消息输入' }),
  ).toBeInTheDocument();
  expect(
    view.container.querySelector('.stage-space')?.parentElement,
  ).toHaveClass('chat-page');
  expect(desktopCss).toContain(
    'grid-template-columns: clamp(360px, 28vw, 400px) minmax(0, 1fr)',
  );
  expect(desktopCss).toMatch(/\.chat-scroll\s*\{[^}]*overflow-y: auto/s);
  expect(desktopCss).toMatch(/\.chat-composer\s*\{[^}]*position: static/s);
  expect(desktopCss).toMatch(/\.chat-column-grid\s*\{\s*display: grid;/);
  expect(desktopCss).toContain('clamp(32px, calc((100% - 760px) / 2), 96px)');
  expect(desktopCss).toContain('minmax(0, 760px) minmax(32px, 1fr)');
  expect(
    within(thread as HTMLElement).getByRole('form', { name: '消息输入' }),
  ).toHaveClass('chat-column-grid');
  expect(desktopCss).toMatch(
    /\.chat-composer \.composer-field\s*\{\s*width: 100%/s,
  );
  const stage = view.container.querySelector('.chat-stage')!;
  expect(
    within(stage as HTMLElement).queryByRole('button', { name: /切换/ }),
  ).toBeNull();
  expect(stage.querySelector('.stage-speaking')).toHaveStyle({
    width: '210px',
    height: '210px',
  });
  expect(stage.querySelector('.stage-circle')).toHaveClass('size-full');
  expect(stage.querySelector('.stage-name button')).toBeNull();
  expect(stage.querySelector('.stage-footer')).toBeNull();
  expect(stage.querySelector('.stage-history')).toContainElement(
    screen.getByRole('button', { name: '新对话' }),
  );
  expect(
    within(stage as HTMLElement).getByRole('searchbox', { name: '搜索对话' }),
  ).toBeVisible();
  expect(
    within(thread as HTMLElement).queryByRole('button', { name: '对话记录' }),
  ).toBeNull();
  expect(screen.queryByRole('dialog', { name: '对话记录' })).toBeNull();
  expect(css).toMatch(/\.chat-stage\s*\{[^}]*overflow: hidden/s);
  expect(desktopCss).toMatch(
    /\.chat-stage\s*\{[^}]*justify-content: flex-start/s,
  );
  expect(desktopCss).toMatch(
    /\.stage-space\s*\{[^}]*position: sticky[^}]*height: 100dvh/s,
  );
  expect(desktopCss).toMatch(
    /\.chat-conversation\s*\{[^}]*min-height: 100%[^}]*max-width: none[^}]*padding: 32px 0 24px/s,
  );
});

it('keeps switching in the rail on tablet too', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const view = mount(<Chat />);
  await waitFor(() =>
    expect(view.container.querySelector('.chat-stage')).toHaveAttribute(
      'data-desktop',
      'false',
    ),
  );
  const stage = view.container.querySelector('.chat-stage')!;
  expect(
    within(stage as HTMLElement).queryByRole('button', { name: /切换/ }),
  ).toBeNull();
  expect(
    within(stage as HTMLElement).getByRole('button', { name: '新对话' }),
  ).toBeVisible();
});

it('uses a desktop memory grid with the sticky add panel and focuses it from the header', async () => {
  const view = mount(<Memories />);
  const panel = screen.getByRole('region', { name: '添加记忆' });
  expect(panel.parentElement).toHaveClass('memories-grid');
  expect(view.container.querySelector('.memory-list')?.parentElement).toBe(
    panel.parentElement,
  );
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '从舞台添加记忆' }));
  expect(screen.getByRole('textbox', { name: '要记住的文字' })).toHaveFocus();
  expect(desktopCss).toMatch(
    /\.memories-grid\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\) 360px/s,
  );
  expect(desktopCss).toMatch(
    /\.memories-grid > \.memory-add-panel\s*\{[^}]*position: sticky/s,
  );
});

it('uses the shared split stage and bounded form card for desktop login', () => {
  const view = mount(<Login />);
  const page = view.container.querySelector('.auth-page')!;
  expect(page.querySelector(':scope > .stage-brand')).toBeInTheDocument();
  expect(
    page.querySelector(':scope > section input[type="email"]'),
  ).toBeInTheDocument();
  expect(desktopCss).toMatch(
    /\.auth-page,[^{]*\{[^}]*grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\)/s,
  );
  expect(desktopCss).toMatch(
    /\.auth-page > section,[^{]*\{[^}]*max-width: 480px/s,
  );
});
