import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { readFileSync } from 'node:fs';
import { beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import { PersonaSwitcher } from '../components/layout/PersonaSwitcher';
import { NewTwin } from '../components/layout/NewTwin';
import { Login } from '../features/auth/Login';
import { useChatLayout } from '../stores/chatLayout';
import { Chat } from '../pages/Chat';
import { Memories } from '../pages/Memories';
import { usePersonas } from '../stores/personas';
import { useStatus } from '../stores/status';
import { isSourcesUrl, sourcesPage } from './personaApi';

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
  useChatLayout.setState({ sheet: undefined, stage: undefined });
  usePersonas.setState({ id: 'default', items: [persona] });
  useStatus.setState({ data: null, error: null });
  vi.stubGlobal('innerWidth', 1280);
  vi.stubGlobal('innerHeight', 900);
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches:
        query === '(min-width: 1200px)' || query === '(min-width: 1280px)',
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
              : isSourcesUrl(path)
                ? sourcesPage(path, [])
                : path.startsWith('/api/conversations?')
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
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/chat']}>{element}</MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
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
  // Placed by its edges, not by the centring translate: a page rule undoing the translate did not survive
  // minification (transform and translate were folded into one), which pushed the sheet off the top left.
  expect(dialog).toHaveClass('inset-0');
  expect(dialog.className).not.toMatch(/translate/);
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

it('keeps the sheet, optional stage and scrolling conversation separate with the composer inside the thread', async () => {
  const view = mount(<Chat />);
  expect(view.container.querySelector('.chat-stage')).toBeNull();
  const sheet = screen.getByRole('region', { name: '和小林的对话' });
  expect(sheet.closest('.chat-surface-sheet')).not.toBeNull();
  await userEvent.setup().click(screen.getByRole('button', { name: '形象' }));
  const stage = screen.getByRole('banner', { name: '小林的舞台' });
  expect(stage).toHaveAttribute('data-desktop', 'true');
  const thread = view.container.querySelector('.chat-thread')!;
  expect(
    thread.querySelector('.chat-scroll .chat-conversation'),
  ).toBeInTheDocument();
  expect(
    within(thread as HTMLElement).getByRole('form', { name: '消息输入' }),
  ).toHaveClass('chat-column-grid');
  expect(
    view.container.querySelector('.stage-space')?.parentElement,
  ).toHaveClass('chat-surface-stage');
  expect(stage).not.toContainElement(sheet);
  expect(within(stage).queryByRole('button', { name: /切换/ })).toBeNull();
  expect(stage.querySelector('.stage-speaking')).toHaveStyle({
    width: '128px',
    height: '128px',
  });
  expect(stage.querySelector('.stage-circle')).toHaveClass('size-full');
  expect(stage.querySelector('.stage-name button')).toBeNull();
  await userEvent
    .setup()
    .click(within(sheet).getByRole('button', { name: '搜索对话' }));
  expect(
    within(sheet).getByRole('searchbox', { name: '搜索对话' }),
  ).toBeVisible();
  expect(screen.queryByRole('dialog', { name: '对话记录' })).toBeNull();
  const chatCss = readFileSync('src/components/ui/chat.css', 'utf8');
  expect(chatCss).toMatch(
    /\.chat-redesign \.chat-scroll\s*\{[^}]*overflow-y: auto/s,
  );
  expect(chatCss).toMatch(
    /\.chat-redesign \.chat-composer\s*\{[^}]*position: static/s,
  );
  expect(chatCss).toMatch(/minmax\(\s*0,\s*var\(--spacing-chat-column\)\s*\)/);
  expect(chatCss).toContain('height: 100dvh');
});

it('starts with a collapsed sheet on tablet, with an accessible expand control', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const view = mount(<Chat />);
  expect(view.container.querySelector('.chat-stage')).toBeNull();
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '展开对话列表' }));
  const sheet = screen.getByRole('region', { name: '和小林的对话' });
  expect(within(sheet).getByRole('button', { name: '新对话' })).toBeVisible();
  expect(
    within(sheet).getByRole('button', { name: '切换分身（当前：小林）' }),
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
