import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { useReducedMotion } from 'motion/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ConfirmProvider, toast } from '../components/ui';
import { Questionnaire } from '../pages/Questionnaire';
import type { QuestionnaireData } from '../features/questionnaire/types';
import { SAVE_DELAY_MS } from '../features/questionnaire/useQuestionnaire';

vi.mock('../components/ui', async (original) => ({
  ...(await original<typeof import('../components/ui')>()),
  toast: vi.fn(),
}));
vi.mock('motion/react', async (original) => {
  const actual = await original<typeof import('motion/react')>();
  const { createElement } = await import('react');
  const cache = new Map();
  return {
    ...actual,
    useReducedMotion: vi.fn(),
    AnimatePresence: ({ children }: { children: import('react').ReactNode }) =>
      children,
    motion: new Proxy(
      {},
      {
        get: (_, tag: string) => {
          if (!cache.has(tag))
            cache.set(tag, (props: Record<string, unknown>) =>
              createElement(
                tag,
                Object.fromEntries(
                  Object.entries(props).filter(
                    ([key]) =>
                      key === 'style' || !actual.isValidMotionProp(key),
                  ),
                ),
              ),
            );
          return cache.get(tag);
        },
      },
    ),
  };
});
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
let initial: QuestionnaireData;
let fetcher: ReturnType<typeof vi.fn>;
let saveResponse: ((response: Response) => void) | undefined;
let deferSave: boolean;
let failSave: boolean;
let failSubmit: boolean;
const requests = (method: string) =>
  fetcher.mock.calls.filter(([, options]) => options?.method === method);
const input = () => screen.getByRole('textbox', { name: '1. 介绍你自己' });
const setup = (route = '/questionnaire') =>
  render(
    <ConfirmProvider>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="questionnaire" element={<Questionnaire />} />
          <Route path="sources" element={<h1>资料目标页</h1>} />
        </Routes>
      </MemoryRouter>
    </ConfirmProvider>,
  );
const change = (value: string) =>
  fireEvent.change(input(), { target: { value } });

beforeEach(() => {
  vi.mocked(useReducedMotion).mockReturnValue(true);
  vi.mocked(toast).mockClear();
  sessionStorage.clear();
  deferSave = failSave = failSubmit = false;
  saveResponse = undefined;
  initial = {
    round: 'initial',
    status: 'draft',
    answers: { q01: '已存的个人回答', q02: '原来的爱好' },
    updated_at: '2025-01-01T12:00:00',
    submitted_at: null,
    questions: [
      {
        id: 'q01',
        number: 1,
        section: '身份',
        text: '介绍你自己',
        kind: '开放',
        facets: ['1.1 角色'],
        optional: false,
      },
      {
        id: 'q02',
        number: 2,
        section: '身份',
        text: '生活偏好',
        kind: '开放',
        facets: ['9.1 爱好', '9.2 作息'],
        optional: true,
      },
      {
        id: 'q13',
        number: 13,
        section: '决策',
        text: '你会怎么决定',
        kind: '情境',
        facets: ['3.1 决策'],
        optional: false,
      },
    ],
  };
  initial.answers.q13 = '已保存的回答';
  fetcher = vi.fn((path: string, options: RequestInit) => {
    if (path.startsWith('/api/persona/questionnaire?'))
      return Promise.resolve(json(initial));
    if (path === '/api/persona/questionnaire/draft') {
      if (deferSave)
        return new Promise<Response>((resolve) => {
          saveResponse = resolve;
        });
      return Promise.resolve(
        failSave
          ? json({ detail: '草稿保存暂不可用' }, 503)
          : json({ updated_at: '2025-01-02T12:01:00' }),
      );
    }
    if (path === '/api/persona/questionnaire/submit') {
      if (failSubmit)
        return Promise.resolve(json({ detail: '还没有回答任何建档题目' }, 400));
      const body = JSON.parse(String(options.body));
      initial.answers = body.answers;
      initial.status = 'submitted';
      initial.submitted_at = '2025-03-01T11:12:00';
      return Promise.resolve(
        json({
          round: body.round,
          job_id: null,
          notice: '已导入 2 条回答；构建没有自动开始',
        }),
      );
    }
    if (path === '/api/jobs') return Promise.resolve(json([]));
    if (path === '/api/status') return Promise.resolve(json({}));
    throw new Error(`Unexpected endpoint: ${path}`);
  });
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => {
  vi.useRealTimers();
});

it('restores the draft, progress, API prompts/kinds/facets and group navigation', async () => {
  vi.mocked(useReducedMotion).mockReturnValue(false);
  const user = userEvent.setup();
  setup();
  expect(await screen.findByDisplayValue('已存的个人回答')).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute(
    'aria-valuenow',
    '100',
  );
  expect(screen.getByText('已答 3 / 3 题')).toBeInTheDocument();
  expect(screen.getByText('相关内容：1.1 角色')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '继续' }));
  expect(screen.getByRole('textbox', { name: '13. 你会怎么决定' })).toHaveValue(
    '已保存的回答',
  );
  expect(screen.getByRole('button', { name: '到最后了' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: '上一步' }));
  expect(input()).toHaveValue('已存的个人回答');
  screen.getByRole('button', { name: '第 2 步：决策' }).focus();
  await user.keyboard('{Enter}');
  expect(screen.getByRole('button', { name: '第 2 步：决策' })).toHaveAttribute(
    'aria-current',
    'step',
  );
});

it('starts at the group with the first unanswered question', async () => {
  delete initial.answers.q13;
  setup();
  expect(
    await screen.findByRole('textbox', { name: '13. 你会怎么决定' }),
  ).toHaveValue('');
  expect(screen.getByRole('button', { name: '第 2 步：决策' })).toHaveAttribute(
    'aria-current',
    'step',
  );
  expect(screen.getByText('已答 2 / 3 题')).toBeInTheDocument();
});

it('debounces autosave for 800ms, sends X-Twin, and keeps Enter/IME as answer text', async () => {
  setup();
  await screen.findByDisplayValue('已存的个人回答');
  vi.useFakeTimers();
  change('第一次');
  await act(async () => {
    await vi.advanceTimersByTimeAsync(500);
  });
  change('最后一次个人回答');
  fireEvent.compositionStart(input());
  fireEvent.keyDown(input(), { key: 'Enter', isComposing: true });
  fireEvent.compositionEnd(input());
  fireEvent.keyDown(input(), { key: 'Enter' });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS - 1);
  });
  expect(requests('PUT')).toHaveLength(0);
  expect(requests('POST')).toHaveLength(0);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(requests('PUT')).toHaveLength(1);
  const options = requests('PUT')[0][1];
  expect(new Headers(options.headers).get('X-Twin')).toBe('1');
  expect(JSON.parse(options.body).answers.q01).toBe('最后一次个人回答');
  expect(screen.getByText('已保存')).toBeInTheDocument();
});

it('clears optional answers on skip, declines every mapped facet and does not count a skip as answered', async () => {
  setup();
  await screen.findByDisplayValue('原来的爱好');
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole('button', { name: '跳过' }));
  expect(screen.getByRole('textbox', { name: '2. 生活偏好' })).toHaveValue('');
  expect(
    screen.getByText('留空即跳过，不采集：9.1 爱好、9.2 作息'),
  ).toBeInTheDocument();
  expect(screen.getByText('已答 2 / 3 题')).toBeInTheDocument();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
  });
  expect(JSON.parse(requests('PUT')[0][1].body).answers.q02).toBe('');
});

it('serializes in-flight saves, persists a newer edit and only warns before unload while a save is in flight', async () => {
  const view = setup();
  await screen.findByDisplayValue('已存的个人回答');
  vi.useFakeTimers();
  deferSave = true;
  change('正在保存的答案');
  let event = new Event('beforeunload', { cancelable: true });
  // A pending debounce flushes without a warning.
  await act(async () => {
    window.dispatchEvent(event);
  });
  expect(event.defaultPrevented).toBe(false);
  expect(requests('PUT')).toHaveLength(1);
  change('保存期间的新答案');
  event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
  });
  expect(requests('PUT')).toHaveLength(1);
  deferSave = false;
  await act(async () => {
    saveResponse!(json({ updated_at: 'now' }));
  });
  expect(requests('PUT')).toHaveLength(2);
  expect(JSON.parse(requests('PUT')[1][1].body).answers.q01).toBe(
    '保存期间的新答案',
  );
  expect(screen.getByText('已保存')).toBeInTheDocument();
  event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(false);
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it('flushes a pending draft on unmount instead of discarding personal edits', async () => {
  const view = setup();
  await screen.findByDisplayValue('已存的个人回答');
  change('离开时未到 debounce 的答案');
  await act(async () => {
    view.unmount();
  });
  expect(requests('PUT')).toHaveLength(1);
  expect(JSON.parse(requests('PUT')[0][1].body).answers.q01).toBe(
    '离开时未到 debounce 的答案',
  );
});

it('retries failed saves and does not POST until the confirmed draft save succeeds', async () => {
  const user = userEvent.setup();
  setup();
  await screen.findByDisplayValue('已存的个人回答');
  failSave = true;
  change('不能丢失的答案');
  await user.click(screen.getByRole('button', { name: '保存回答' }));
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: '确认提交',
    }),
  );
  expect(await screen.findByText('草稿保存暂不可用')).toBeInTheDocument();
  expect(requests('POST')).toHaveLength(0);
  expect(input()).toHaveValue('不能丢失的答案');
  failSave = false;
  await user.click(screen.getByRole('button', { name: '重试保存' }));
  expect(await screen.findByText('已保存')).toBeInTheDocument();
});

it('requires confirmation, explains replacement/import/rebuild, saves the latest draft and shows success/build link', async () => {
  initial.status = 'submitted';
  initial.submitted_at = '2025-01-01T10:00:00';
  const user = userEvent.setup();
  setup();
  await screen.findByDisplayValue('已存的个人回答');
  change('本次提交答案');
  await user.click(screen.getByRole('button', { name: '保存回答' }));
  const dialog = screen.getByRole('dialog');
  expect(
    within(dialog).getByText(/答案会成为分身的记忆.*会替换上次/),
  ).toBeInTheDocument();
  expect(requests('POST')).toHaveLength(0);
  await user.click(within(dialog).getByRole('button', { name: '取消' }));
  expect(requests('POST')).toHaveLength(0);
  await user.click(screen.getByRole('button', { name: '保存回答' }));
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: '确认提交',
    }),
  );
  expect(
    await screen.findByText('已导入 2 条回答；构建没有自动开始'),
  ).toBeInTheDocument();
  expect(JSON.parse(requests('POST')[0][1].body)).toMatchObject({
    round: 'initial',
    answers: { q01: '本次提交答案' },
  });
  expect(
    screen.getByRole('link', { name: '去资料与构建查看进度或构建' }),
  ).toHaveAttribute('href', '#/sources');
  expect(
    await screen.findByText(/已于 2025-03-01 11:12 提交/),
  ).toBeInTheDocument();
  expect(toast).toHaveBeenCalledWith(
    '已导入 2 条回答；构建没有自动开始',
    'success',
  );
});

it('attaches the automatic build job and retains the old completion/diff links', async () => {
  const original = fetcher.getMockImplementation() as (
    path: string,
    options: RequestInit,
  ) => Promise<Response>;
  fetcher.mockImplementation((path: string, options: RequestInit) => {
    if (path === '/api/persona/questionnaire/submit')
      return Promise.resolve(
        json({
          round: 'initial',
          job_id: 'q-build',
          notice: '已导入，正在构建人格档案',
        }),
      );
    if (path === '/api/jobs/q-build')
      return Promise.resolve(
        json({
          job_id: 'q-build',
          kind: 'persona_build',
          status: 'done',
          result: {
            sources: 1,
            chunks_extracted: 2,
            candidates: 3,
            items: 4,
            items_added: 2,
            items_changed: 1,
            items_removed: 0,
            facets_changed: 1,
            facet_diffs: { '1.1': { added: 2, changed: 1, removed: 0 } },
          },
        }),
      );
    return original(path, options);
  });
  const user = userEvent.setup();
  setup();
  await screen.findByDisplayValue('已存的个人回答');
  await user.click(screen.getByRole('button', { name: '保存回答' }));
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: '确认提交',
    }),
  );
  expect(
    await screen.findByText(/新增 2 条、修改 1 条、删除 0 条/),
  ).toBeInTheDocument();
  expect(
    screen.getAllByRole('link', { name: '看看我了解到的你' })[0],
  ).toHaveAttribute('href', '#/profile');
  expect(screen.getByRole('link', { name: '去和分身聊天' })).toHaveAttribute(
    'href',
    '#/chat',
  );
  expect(sessionStorage.getItem('twin.next.job.personaBuild')).toBe('q-build');
});

it('preserves answers and displays the backend detail on submit failure', async () => {
  failSubmit = true;
  const user = userEvent.setup();
  setup();
  await screen.findByDisplayValue('已存的个人回答');
  await user.click(screen.getByRole('button', { name: '保存回答' }));
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: '确认提交',
    }),
  );
  expect(await screen.findByText('还没有回答任何建档题目')).toBeInTheDocument();
  expect(input()).toHaveValue('已存的个人回答');
});

it('reports load errors and allows retry', async () => {
  const original = fetcher.getMockImplementation() as (
    path: string,
    options: RequestInit,
  ) => Promise<Response>;
  let failed = false;
  fetcher.mockImplementation((path: string, options: RequestInit) => {
    if (path.startsWith('/api/persona/questionnaire?') && !failed) {
      failed = true;
      return Promise.resolve(json({ detail: '问卷暂时无法读取' }, 503));
    }
    return original(path, options);
  });
  const user = userEvent.setup();
  setup();
  expect(await screen.findByText('问卷暂时无法读取')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '重试加载' }));
  expect(await screen.findByDisplayValue('已存的个人回答')).toBeInTheDocument();
});
