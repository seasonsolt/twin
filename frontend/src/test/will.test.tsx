import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SidebarAccount } from '../components/layout/Sidebar';
import { ConfirmProvider, TooltipProvider } from '../components/ui';
import { Will } from '../features/will/Will';
import type { Heir } from '../features/will/types';
import { useAuth } from '../stores/auth';
import { usePersonas } from '../stores/personas';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const heir = (change: Partial<Heir>): Heir => ({
  heir_id: 'heir_1',
  name: '小雨',
  relation: '女儿',
  aspects: ['D2'],
  facets: ['9.1'],
  avoid: ['前一段婚姻'],
  voice: false,
  likeness: false,
  retire_on: '2060-01-01',
  farewell: null,
  created_at: '2026-10-30T10:00:00',
  updated_at: '2026-10-30T10:00:00',
  ...change,
});

const coverage = {
  dimensions: [
    { dimension_id: 'D2', name: '价值观与原则' },
    { dimension_id: 'D9', name: '生活与爱好' },
  ],
  facets: [
    { facet_id: '2.1', name: '核心价值排序', dimension_id: 'D2' },
    { facet_id: '2.2', name: '底线与原则', dimension_id: 'D2' },
    { facet_id: '9.1', name: '兴趣爱好', dimension_id: 'D9' },
    { facet_id: '9.2', name: '生活习惯与作息', dimension_id: 'D9' },
  ],
};

let heirs: Heir[];
let sealed: boolean;
let sent: { method: string; url: string; body: Record<string, unknown> }[];

beforeEach(() => {
  heirs = [heir({})];
  sealed = false;
  sent = [];
  useAuth.setState({
    identity: {
      email: null,
      admin: true,
      auth_enabled: false,
      edition: 'persona',
    },
  });
  usePersonas.setState({
    id: 'default',
    items: [
      {
        id: 'default',
        name: '林舟',
        avatar_url: null,
        sources: 3,
        created_at: '',
        is_default: true,
        can_manage: true,
      },
    ],
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (method !== 'GET') {
        sent.push({
          method,
          url,
          body: init.body ? JSON.parse(String(init.body)) : {},
        });
        if (sealed)
          return json(
            { detail: '记忆已冻结，不能再改动', code: 'memory_sealed' },
            423,
          );
      }
      if (url === '/api/persona/will') return json({ heirs });
      if (url === '/api/persona/will/history')
        return json({
          changes: [
            {
              at: '2026-10-30T10:00:00',
              actor: 'self',
              action: 'add',
              heir_id: 'heir_1',
              changes: [],
              heirs,
            },
          ],
        });
      if (url === '/api/persona/coverage') return json(coverage);
      if (url === '/api/persona/chat/stream') return rehearsal();
      if (url === '/api/persona/will/heirs' && method === 'POST') {
        const body = JSON.parse(String(init.body)) as Partial<Heir>;
        const added = heir({ ...body, heir_id: 'heir_2' });
        heirs = [...heirs, added];
        return json({ heir: added });
      }
      if (url.startsWith('/api/persona/will/heirs/') && method === 'PUT') {
        const body = JSON.parse(String(init.body)) as Partial<Heir>;
        heirs = heirs.map((h) =>
          url.endsWith(h.heir_id) ? { ...h, ...body } : h,
        );
        return json({ heir: heirs[0] });
      }
      if (url.startsWith('/api/persona/will/heirs/') && method === 'DELETE') {
        heirs = heirs.filter((h) => !url.endsWith(h.heir_id));
        return json({ ok: true });
      }
      return json({});
    }),
  );
});

/** A rehearsed answer as the server streams it: drawn on what the will gives, with what it left out. */
const rehearsal = () =>
  new Response(
    [
      'event: delta\ndata: {"text":"我们常去河边钓鱼。"}\n\n',
      `event: final\ndata: ${JSON.stringify({
        reply: '我们常去河边钓鱼。',
        citations: [],
        confidence: 0.9,
        abstain: false,
        preview: {
          withheld: [
            { id: 'pi_rule', facet: '底线与原则', text: '他做事不欠人情' },
          ],
        },
      })}\n\n`,
    ].join(''),
    { headers: { 'Content-Type': 'text/event-stream' } },
  );

afterEach(() => {
  useAuth.setState({ identity: null });
});

function renderWill() {
  return render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/chat?will=']}>
          <Will />
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
}

async function openWill() {
  renderWill();
  const dialog = await screen.findByRole('dialog', { name: '数字遗嘱' });
  await within(dialog).findByRole('list', { name: '继承人' });
  return dialog;
}

/** Walks the editor from the current step to the word, with `next` pressed `steps` times. */
async function next(user: ReturnType<typeof userEvent.setup>, steps: number) {
  for (let i = 0; i < steps; i += 1)
    await user.click(screen.getByRole('button', { name: '下一步' }));
}

it('opens from the account menu of the persona edition, beside the settings', async () => {
  const user = userEvent.setup();
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter>
          <SidebarAccount />
          <Will />
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
  await user.click(screen.getByRole('button', { name: '账户' }));
  const menu = screen.getByRole('dialog', { name: '账户' });
  expect(
    within(menu)
      .getAllByRole('button')
      .map((button) => button.textContent),
  ).toEqual(['数字遗嘱', '设置']);
  await user.click(within(menu).getByRole('button', { name: '数字遗嘱' }));
  expect(
    await screen.findByRole('dialog', { name: '数字遗嘱' }),
  ).toBeInTheDocument();
});

it('has no will in the team edition', async () => {
  useAuth.setState({
    identity: { email: null, admin: true, auth_enabled: false },
  });
  const user = userEvent.setup();
  render(
    <TooltipProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/chat?will=']}>
          <SidebarAccount />
          <Will />
        </MemoryRouter>
      </ConfirmProvider>
    </TooltipProvider>,
  );
  await user.click(screen.getByRole('button', { name: '账户' }));
  expect(
    within(screen.getByRole('dialog', { name: '账户' })).queryByRole('button', {
      name: '数字遗嘱',
    }),
  ).toBeNull();
  expect(screen.queryByRole('dialog', { name: '数字遗嘱' })).toBeNull();
});

it('shows each heir as one row, with the history folded', async () => {
  const dialog = await openWill();
  const row = within(
    within(dialog).getByRole('list', { name: '继承人' }),
  ).getByRole('listitem');
  expect(row).toHaveTextContent('小雨');
  expect(row).toHaveTextContent('女儿');
  // A whole aspect and a facet of another: two aspects.
  expect(row).toHaveTextContent('2 个方面');
  expect(row).toHaveTextContent('至 2060-01-01');
  expect(within(dialog).getByText('加了小雨')).not.toBeVisible();
  await userEvent.setup().click(within(dialog).getByText('改动记录 1'));
  expect(within(dialog).getByText('加了小雨')).toBeVisible();
});

it('names a new heir step by step, giving nothing unless ticked and sending the word once', async () => {
  const user = userEvent.setup();
  const dialog = await openWill();
  await user.click(within(dialog).getByRole('button', { name: '加继承人' }));
  const editor = await screen.findByRole('dialog', { name: '加继承人' });
  // A name first.
  await next(user, 1);
  expect(within(editor).getByRole('alert')).toHaveTextContent('写一个称呼');
  await user.type(within(editor).getByLabelText('称呼'), '老周');
  await user.type(within(editor).getByLabelText('关系'), '老友');
  await next(user, 1);
  // Nothing is ticked to begin with.
  const aspects = await within(editor).findByRole('group', {
    name: '能用的方面',
  });
  const boxes = within(aspects).getAllByRole('checkbox');
  expect(boxes).toHaveLength(2);
  boxes.forEach((box) => expect(box).not.toBeChecked());
  // One facet of the second aspect, opened to its facets.
  await user.click(
    within(aspects).getByRole('button', { name: /^生活与爱好里的各项/ }),
  );
  await user.click(within(aspects).getByRole('checkbox', { name: '兴趣爱好' }));
  expect(
    within(aspects).getByRole('checkbox', { name: '生活与爱好' }),
  ).toBePartiallyChecked();
  await next(user, 1);
  await user.type(within(editor).getByLabelText('不谈的话题'), '公司的事');
  await next(user, 3);
  // The word, twice; differently is refused before anything is sent.
  const word = within(editor).getByLabelText('开启口令');
  expect(word).toHaveAttribute('type', 'password');
  await user.type(word, 'sesame-1');
  await user.type(within(editor).getByLabelText('再输一次'), 'sesame-2');
  await user.click(within(editor).getByRole('button', { name: '保存' }));
  expect(within(editor).getByRole('alert')).toHaveTextContent(
    '两次输入的口令不一样',
  );
  expect(sent).toEqual([]);
  await user.clear(within(editor).getByLabelText('再输一次'));
  await user.type(within(editor).getByLabelText('再输一次'), 'sesame-1');
  await user.click(within(editor).getByRole('button', { name: '保存' }));
  await screen.findByRole('dialog', { name: '数字遗嘱' });
  expect(sent).toEqual([
    {
      method: 'POST',
      url: '/api/persona/will/heirs',
      body: {
        name: '老周',
        relation: '老友',
        aspects: [],
        facets: ['9.1'],
        avoid: ['公司的事'],
        voice: false,
        likeness: false,
        retire_on: null,
        farewell: null,
        password: 'sesame-1',
      },
    },
  ]);
  // The word is never shown back.
  expect(
    await within(screen.getByRole('dialog', { name: '数字遗嘱' })).findByText(
      '老周',
    ),
  ).toBeVisible();
  expect(screen.queryByDisplayValue('sesame-1')).toBeNull();
});

it('changes an heir without the word when it is left empty', async () => {
  const user = userEvent.setup();
  const dialog = await openWill();
  await user.click(within(dialog).getByLabelText('小雨的操作'));
  await user.click(within(dialog).getByRole('button', { name: '修改' }));
  const editor = await screen.findByRole('dialog', { name: '小雨' });
  await user.click(within(editor).getByRole('button', { name: '下一步' }));
  const aspects = await within(editor).findByRole('group', {
    name: '能用的方面',
  });
  // The whole aspect given is ticked; taking it back gives none of it.
  const values = within(aspects).getByRole('checkbox', {
    name: '价值观与原则',
  });
  expect(values).toBeChecked();
  await user.click(values);
  await next(user, 4);
  expect(within(editor).getByLabelText('开启口令')).toHaveAttribute(
    'placeholder',
    '留空不改',
  );
  await user.click(within(editor).getByRole('button', { name: '保存' }));
  await screen.findByRole('dialog', { name: '数字遗嘱' });
  expect(sent).toHaveLength(1);
  expect(sent[0].method).toBe('PUT');
  expect(sent[0].url).toBe('/api/persona/will/heirs/heir_1');
  expect(sent[0].body).not.toHaveProperty('password');
  expect(sent[0].body).toMatchObject({
    name: '小雨',
    aspects: [],
    facets: ['9.1'],
    avoid: ['前一段婚姻'],
    retire_on: '2060-01-01',
  });
});

it('sends a new word on a change only when it is set', async () => {
  const user = userEvent.setup();
  const dialog = await openWill();
  await user.click(within(dialog).getByLabelText('小雨的操作'));
  await user.click(within(dialog).getByRole('button', { name: '修改' }));
  const editor = await screen.findByRole('dialog', { name: '小雨' });
  await next(user, 5);
  await user.type(within(editor).getByLabelText('开启口令'), 'new-word');
  await user.click(within(editor).getByRole('button', { name: '保存' }));
  // Typed once only: not saved.
  expect(within(editor).getByRole('alert')).toHaveTextContent(
    '两次输入的口令不一样',
  );
  await user.type(within(editor).getByLabelText('再输一次'), 'new-word');
  await user.click(within(editor).getByRole('button', { name: '保存' }));
  await screen.findByRole('dialog', { name: '数字遗嘱' });
  expect(sent).toHaveLength(1);
  expect(sent[0].body.password).toBe('new-word');
});

it('removes an heir only once it is confirmed', async () => {
  const user = userEvent.setup();
  const dialog = await openWill();
  await user.click(within(dialog).getByLabelText('小雨的操作'));
  await user.click(within(dialog).getByRole('button', { name: '删除' }));
  const ask = await screen.findByRole('dialog', { name: '删除小雨？' });
  await user.click(within(ask).getByRole('button', { name: '取消' }));
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '删除小雨？' })).toBeNull(),
  );
  expect(sent).toEqual([]);
  await user.click(within(dialog).getByLabelText('小雨的操作'));
  await user.click(within(dialog).getByRole('button', { name: '删除' }));
  await user.click(
    within(await screen.findByRole('dialog', { name: '删除小雨？' })).getByRole(
      'button',
      { name: '删除' },
    ),
  );
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '删除小雨？' })).toBeNull(),
  );
  await waitFor(() =>
    expect(within(dialog).queryByRole('list', { name: '继承人' })).toBeNull(),
  );
  expect(sent).toEqual([
    { method: 'DELETE', url: '/api/persona/will/heirs/heir_1', body: {} },
  ]);
  expect(within(dialog).getByText(/还没有继承人/)).toBeVisible();
});

it('keeps the will as it is once the memory is sealed', async () => {
  sealed = true;
  const user = userEvent.setup();
  const dialog = await openWill();
  // Not known until a change is refused.
  await user.click(within(dialog).getByLabelText('小雨的操作'));
  await user.click(within(dialog).getByRole('button', { name: '删除' }));
  await user.click(
    within(await screen.findByRole('dialog', { name: '删除小雨？' })).getByRole(
      'button',
      { name: '删除' },
    ),
  );
  await waitFor(() =>
    expect(screen.queryByRole('dialog', { name: '删除小雨？' })).toBeNull(),
  );
  expect(await within(dialog).findByText('已冻结，遗嘱不能再改')).toBeVisible();
  expect(
    within(dialog).getByRole('button', { name: '加继承人' }),
  ).toBeDisabled();
  await user.click(within(dialog).getByLabelText('小雨的操作'));
  expect(within(dialog).getByRole('button', { name: '修改' })).toBeDisabled();
  expect(within(dialog).getByRole('button', { name: '预演' })).toBeDisabled();
  expect(within(dialog).getByRole('button', { name: '删除' })).toBeDisabled();
  expect(
    within(dialog).getByRole('list', { name: '继承人' }),
  ).toHaveTextContent('小雨');
});

it('knows the will is sealed from a server that says so, before anything is tried', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url === '/api/persona/will'
        ? json({ heirs, sealed: true })
        : json({ changes: [] }),
    ),
  );
  const dialog = await openWill();
  expect(within(dialog).getByText('已冻结，遗嘱不能再改')).toBeVisible();
  expect(
    within(dialog).getByRole('button', { name: '加继承人' }),
  ).toBeDisabled();
});

it("rehearses an heir's conversation as the heir, naming what each answer left out and keeping nothing", async () => {
  const user = userEvent.setup();
  const dialog = await openWill();
  await user.click(within(dialog).getByLabelText('小雨的操作'));
  expect(
    within(dialog)
      .getAllByRole('button')
      .map((button) => button.textContent)
      .filter((label) => ['修改', '预演', '删除'].includes(label ?? '')),
  ).toEqual(['修改', '预演', '删除']);
  await user.click(within(dialog).getByRole('button', { name: '预演' }));
  const panel = await screen.findByRole('dialog', { name: '预演 · 小雨' });
  // It looks as it would to the heir: whose memory this carries on, and that it is not them.
  expect(
    within(panel).getByRole('heading', { name: '林舟的记忆延续' }),
  ).toBeVisible();
  expect(within(panel).getByText('不是林舟本人')).toBeVisible();
  expect(
    within(panel).getByText('小雨，想问林舟什么，就在下面写。'),
  ).toBeVisible();
  const input = within(panel).getByLabelText('以小雨的身份问');
  await user.type(input, '小时候我们常做什么？{Enter}');
  const answer = await within(panel).findByRole('article', {
    name: '分身回复',
  });
  expect(answer).toHaveTextContent('我们常去河边钓鱼。');
  const left = within(answer).getByLabelText('没给小雨的');
  expect(left).toHaveTextContent('未用 · 底线与原则');
  expect(within(left).getByTitle('他做事不欠人情')).toBeVisible();
  // The next question carries the rehearsal so far, as the heir's would; each asks as this heir, keeping nothing.
  await user.type(input, '那工作呢？');
  await user.click(within(panel).getByRole('button', { name: '发送' }));
  await waitFor(() =>
    expect(
      within(panel).getAllByRole('article', { name: '分身回复' }),
    ).toHaveLength(2),
  );
  expect(sent.map(({ method, url }) => `${method} ${url}`)).toEqual([
    'POST /api/persona/chat/stream',
    'POST /api/persona/chat/stream',
  ]);
  expect(sent[0].body).toEqual({
    messages: [{ role: 'user', content: '小时候我们常做什么？' }],
    preview: true,
    heir: 'heir_1',
  });
  expect(sent[1].body).toEqual({
    messages: [
      { role: 'user', content: '小时候我们常做什么？' },
      { role: 'twin', content: '我们常去河边钓鱼。' },
      { role: 'user', content: '那工作呢？' },
    ],
    preview: true,
    heir: 'heir_1',
  });
  // Straight on to changing the will for this heir.
  await user.click(within(panel).getByRole('button', { name: '改遗嘱' }));
  expect(await screen.findByRole('dialog', { name: '小雨' })).toBeVisible();
});

it('goes back to the will when a rehearsal is refused because the memory is sealed', async () => {
  sealed = true;
  const user = userEvent.setup();
  const dialog = await openWill();
  await user.click(within(dialog).getByLabelText('小雨的操作'));
  await user.click(within(dialog).getByRole('button', { name: '预演' }));
  const panel = await screen.findByRole('dialog', { name: '预演 · 小雨' });
  await user.type(
    within(panel).getByLabelText('以小雨的身份问'),
    '在吗{Enter}',
  );
  const will = await screen.findByRole('dialog', { name: '数字遗嘱' });
  expect(await within(will).findByText('已冻结，遗嘱不能再改')).toBeVisible();
});
