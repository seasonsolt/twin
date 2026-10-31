import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import { HeirDoor } from '../features/heir/HeirDoor';
import { getPersonaId, personaKey } from '../lib/persona';
import { useAuth } from '../stores/auth';
import { usePersonas } from '../stores/personas';

// The person's own pages are not what is tried here: only whether an heir reaches them.
vi.mock('../pages/Chat', () => ({ Chat: () => <p>本人的对话页</p> }));
vi.mock('motion/react', async (original) => ({
  ...(await original<typeof import('motion/react')>()),
  useReducedMotion: () => true,
}));

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const person = {
  email: null,
  admin: true,
  auth_enabled: false,
  edition: 'persona',
};
// Once an heir has opened it, the person's own twin is sealed.
const sealed = { ...person, sealed: true };
const heir = {
  ...sealed,
  admin: false,
  heir: { id: 'heir_a', name: '小明', person: '张三', persona: 'default' },
};

let whoami: Record<string, unknown>;
let calls: { path: string; method: string; body: unknown }[];
let open: (body: Record<string, unknown>) => Response;
beforeEach(() => {
  whoami = person;
  calls = [];
  open = () => json({ detail: '称呼或口令不对', code: 'heir_wrong' }, 400);
  localStorage.clear();
  useAuth.getState().clear();
  window.location.hash = '#/chat';
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      const body: unknown = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ path, method, body });
      if (path === '/api/whoami') return json(whoami);
      if (path === '/api/heir/open')
        return open(body as Record<string, unknown>);
      if (path === '/api/heir/leave') {
        whoami = sealed;
        return json({ ok: true });
      }
      if (path === '/api/conversations' && method === 'GET')
        return json([{ id: 'c-1', title: '那年的事' }]);
      if (path === '/api/personas')
        return json([
          {
            id: 'default',
            name: '张三',
            avatar_url: null,
            sources: 1,
            created_at: '',
            is_default: true,
            mine: true,
            approved: true,
            can_manage: true,
          },
        ]);
      return json({});
    }),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useAuth.getState().clear();
});

it('says nothing of which was wrong, and lets the heir in only once they confirm the seal', async () => {
  const user = userEvent.setup();
  const changed = vi.fn();
  render(<HeirDoor open onOpenChange={changed} />);
  await user.type(screen.getByLabelText('称呼'), '小明');
  await user.type(screen.getByLabelText('口令'), '不对的口令');
  await user.click(screen.getByRole('button', { name: '进入' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('称呼或口令不对');
  expect(useAuth.getState().identity).toBeNull();

  // The right word, the first time: the seal is said once, and nothing happens before it is confirmed.
  open = (body) =>
    body.confirm
      ? (() => {
          whoami = heir;
          return json({
            status: 'open',
            heir: { id: 'heir_a', name: '小明' },
            sealed_now: true,
          });
        })()
      : json({ status: 'confirm' });
  await user.clear(screen.getByLabelText('口令'));
  await user.type(screen.getByLabelText('口令'), '开启口令123');
  await user.click(screen.getByRole('button', { name: '进入' }));
  const dialog = await screen.findByRole('dialog', { name: '开启后记忆冻结' });
  expect(dialog).toHaveTextContent('不能撤回');
  expect(calls.filter((c) => c.path === '/api/heir/open').at(-1)?.body).toEqual(
    {
      name: '小明',
      password: '开启口令123',
      confirm: false,
    },
  );
  expect(useAuth.getState().identity).toBeNull();
  await user.click(within(dialog).getByRole('button', { name: '确认开启' }));
  await waitFor(() =>
    expect(useAuth.getState().identity?.heir?.name).toBe('小明'),
  );
  expect(calls.filter((c) => c.path === '/api/heir/open').at(-1)?.body).toEqual(
    {
      name: '小明',
      password: '开启口令123',
      confirm: true,
    },
  );
});

it('shows an heir their own conversation alone, says whose memory it is, and leaves to the way in', async () => {
  whoami = heir;
  const user = userEvent.setup();
  render(<App />);
  expect(
    await screen.findByRole('heading', { name: '张三的记忆延续' }),
  ).toBeInTheDocument();
  expect(screen.getByText('不是张三本人')).toBeInTheDocument();
  // None of the person's pages, nor their list of twins or way into the will.
  expect(screen.queryByText('本人的对话页')).not.toBeInTheDocument();
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  expect(calls.some((c) => c.path === '/api/personas')).toBe(false);
  expect(
    await screen.findByRole('combobox', { name: '以前的对话' }),
  ).toBeInTheDocument();
  // Their twin is the one they opened, and what this browser keeps for them is apart from the person's.
  expect(getPersonaId()).toBe('default');
  expect(personaKey('twin.current.conversation')).toBe(
    'twin.heir:heir_a:default:twin.current.conversation',
  );

  await user.click(screen.getByRole('button', { name: '离开' }));
  expect(await screen.findByText('记忆已冻结')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '我是继承人' })).toBeVisible();
  expect(screen.queryByText('本人的对话页')).not.toBeInTheDocument();
  expect(calls.some((c) => c.path === '/api/heir/leave')).toBe(true);
  // What this browser kept for the heir is theirs no longer.
  expect(personaKey('twin.current.conversation')).not.toContain('heir_a');
});

it('offers the way in quietly on the persona edition side bar', async () => {
  const user = userEvent.setup();
  render(<App />);
  await waitFor(() => expect(usePersonas.getState().items).toHaveLength(1));
  await user.click(await screen.findByRole('button', { name: '我是继承人' }));
  expect(
    await screen.findByRole('dialog', { name: '我是继承人' }),
  ).toBeInTheDocument();
});

it('once sealed, shows anyone who is not an heir the way in and nothing of the person', async () => {
  whoami = sealed;
  const user = userEvent.setup();
  render(<App />);
  expect(await screen.findByText('记忆已冻结')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '我是继承人' }));
  expect(
    await screen.findByRole('dialog', { name: '我是继承人' }),
  ).toBeInTheDocument();
  expect(screen.queryByText('本人的对话页')).not.toBeInTheDocument();
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  // Not even the list of twins is asked for.
  expect(calls.map((c) => c.path)).toEqual(['/api/whoami']);
});

it('becomes the way in when the twin is sealed while the page is open', async () => {
  render(<App />);
  expect(await screen.findByText('本人的对话页')).toBeInTheDocument();
  whoami = sealed;
  window.dispatchEvent(new Event('twin-heirs-only'));
  expect(await screen.findByText('记忆已冻结')).toBeInTheDocument();
  expect(screen.queryByText('本人的对话页')).not.toBeInTheDocument();
});

it('once the twin has said goodbye, leaves the heir what was said to read and nothing to ask', async () => {
  whoami = { ...heir, heir: { ...heir.heir, gone: true } };
  render(<App />);
  expect(await screen.findByText('已经道别')).toBeInTheDocument();
  expect(
    await screen.findByRole('combobox', { name: '以前的对话' }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('textbox', { name: '你说' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '新对话' }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/就在下面写/)).not.toBeInTheDocument();
});
