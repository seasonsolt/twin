import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { jobRatio, jobStage, useJob, type Job } from '../features/jobs/useJob';

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
let fetcher: ReturnType<typeof vi.fn>;
const running: Job = {
  job_id: 'j/1',
  kind: 'persona_build',
  status: 'running',
};
beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.clear();
  fetcher = vi.fn(async (url: string) =>
    json(
      url === '/api/jobs'
        ? []
        : url === '/api/persona/build'
          ? { job_id: running.job_id }
          : running,
    ),
  );
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => vi.useRealTimers());
const mount = (onDone = vi.fn()) =>
  renderHook(() =>
    useJob({ kind: 'persona_build', storageKey: 'test-job', onDone }),
  );
async function flush() {
  await act(async () => {});
}
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
it('polls every second, reports stages and calls completion exactly once', async () => {
  const done = vi.fn();
  const { result } = mount(done);
  await flush();
  await act(async () => {
    await result.current.start('/api/persona/build');
  });
  expect(result.current.busy).toBe(true);
  expect(sessionStorage.getItem('test-job')).toBe('j/1');
  expect(fetcher.mock.calls.at(-1)?.[0]).toBe('/api/jobs/j%2F1');
  fetcher.mockImplementation(async () =>
    json({ ...running, stage: { current: 2, total: 3, label: '合并' } }),
  );
  await advance(1000);
  expect(jobRatio(result.current.job!)).toBe(1 / 3);
  fetcher.mockImplementation(async () =>
    json({ ...running, status: 'done', result: { items: 2 } }),
  );
  await advance(1000);
  expect(result.current.busy).toBe(false);
  expect(done).toHaveBeenCalledWith(
    expect.objectContaining({ result: { items: 2 } }),
    { restored: false },
  );
  await advance(5000);
  expect(done).toHaveBeenCalledTimes(1);
});
it('does not submit twice before React commits the busy state', async () => {
  const { result } = mount();
  await flush();
  await act(async () => {
    await Promise.all([
      result.current.start('/api/persona/build'),
      result.current.start('/api/persona/build'),
    ]);
  });
  expect(
    fetcher.mock.calls.filter(([url]) => url === '/api/persona/build'),
  ).toHaveLength(1);
});
it('parses legacy stage lines but respects explicit null stages and tally fallback', () => {
  expect(
    jobStage({ ...running, progress: ['[1/2] 抽取', 'call', '[2/2] 向量'] }),
  ).toEqual({ current: 2, total: 2, label: '向量' });
  expect(
    jobStage({ ...running, stage: null, progress: ['[2/2] 向量'] }),
  ).toBeNull();
  expect(
    jobRatio({ ...running, tally: { done: 3, failed: 1, total: 8 } }),
  ).toBe(0.5);
  expect(jobRatio(running)).toBeNull();
  expect(jobRatio({ ...running, status: 'done' })).toBe(1);
});
it('resumes a running job from GET /api/jobs before the saved id', async () => {
  sessionStorage.setItem('test-job', 'obsolete');
  fetcher.mockImplementation(async (url: string) =>
    json(
      url === '/api/jobs' ? [{ ...running, kind: 'chat' }, running] : running,
    ),
  );
  const { result } = mount();
  await flush();
  expect(result.current.job?.job_id).toBe('j/1');
  expect(fetcher.mock.calls.some(([url]) => url === '/api/jobs/obsolete')).toBe(
    false,
  );
  expect(fetcher.mock.calls.some(([url]) => url === '/api/persona/build')).toBe(
    false,
  );
});
it('restores completed results quietly and hides expired saved ids', async () => {
  sessionStorage.setItem('test-job', 'old');
  fetcher.mockImplementation(async (url: string) =>
    json(
      url === '/api/jobs' ? [] : { ...running, job_id: 'old', status: 'done' },
    ),
  );
  const done = vi.fn();
  const first = mount(done);
  await flush();
  expect(done).toHaveBeenCalledWith(expect.anything(), { restored: true });
  first.unmount();
  fetcher.mockImplementation(async (url: string) =>
    url === '/api/jobs' ? json([]) : json({ detail: '找不到任务' }, 404),
  );
  const second = mount();
  await flush();
  expect(second.result.current.job).toBeNull();
  expect(second.result.current.error).toBe('');
  expect(sessionStorage.getItem('test-job')).toBeNull();
});
it('retries transient polling failures at 2s, stops after 15 and reconnects', async () => {
  const { result } = mount();
  await flush();
  await act(async () => {
    await result.current.start('/api/persona/build');
  });
  fetcher.mockRejectedValue(new TypeError('offline'));
  await advance(1000);
  expect(result.current.retries).toBe(1);
  await advance(28_000);
  expect(result.current.disconnected).toBe(true);
  expect(result.current.busy).toBe(false);
  const count = fetcher.mock.calls.length;
  await advance(5000);
  expect(fetcher).toHaveBeenCalledTimes(count);
  fetcher.mockResolvedValue(json({ ...running, status: 'done' }));
  await act(async () => result.current.reconnect());
  expect(result.current.error).toBe('');
  expect(result.current.job?.status).toBe('done');
});
it('retries failed submissions and failed jobs, follows 409 job ids without treating other kinds as build results', async () => {
  const done = vi.fn();
  const { result } = mount(done);
  await flush();
  fetcher.mockResolvedValueOnce(json({ detail: '模型未配置' }, 503));
  await act(async () => {
    await result.current.start('/api/persona/build');
  });
  expect(result.current.error).toBe('模型未配置');
  fetcher.mockImplementation(async (url: string) =>
    json(
      url === '/api/persona/build'
        ? { job_id: 'j/1' }
        : { ...running, status: 'failed', error: '构建失败' },
    ),
  );
  await act(async () => {
    await result.current.start('/api/persona/build');
  });
  expect(result.current.job?.status).toBe('failed');
  expect(result.current.busy).toBe(false);
  fetcher.mockImplementation(async (url: string) =>
    url === '/api/persona/build'
      ? json({ detail: '其他任务正在运行', job_id: 'other' }, 409)
      : json({ ...running, job_id: 'other', kind: 'index', status: 'running' }),
  );
  await act(async () => {
    await result.current.start('/api/persona/build');
  });
  expect(result.current.notice).toContain('同一时间只能运行一个');
  fetcher.mockResolvedValue(
    json({ ...running, job_id: 'other', kind: 'index', status: 'done' }),
  );
  await advance(1000);
  expect(result.current.notice).toContain('现在可以重新提交');
  expect(done).not.toHaveBeenCalled();
});
it('cleans up timers and aborts discovery, submission, and polling on unmount or inactive routes', async () => {
  const first = mount();
  await flush();
  await act(async () => {
    await first.result.current.start('/api/persona/build');
  });
  first.unmount();
  const count = fetcher.mock.calls.length;
  await advance(5000);
  expect(fetcher).toHaveBeenCalledTimes(count);
  let signal: AbortSignal | null | undefined;
  fetcher.mockImplementation((_url: string, init: RequestInit) => {
    signal = init.signal;
    return new Promise<Response>(() => {});
  });
  const discovery = mount();
  discovery.unmount();
  expect(signal?.aborted).toBe(true);
  fetcher.mockResolvedValue(json([]));
  const poll = renderHook(
    ({ active }) => useJob({ kind: 'persona_build', active }),
    { initialProps: { active: true } },
  );
  await flush();
  fetcher.mockImplementation((_url: string, init: RequestInit) => {
    signal = init.signal;
    return new Promise<Response>(() => {});
  });
  act(() => poll.result.current.attach('poll'));
  poll.rerender({ active: false });
  expect(signal?.aborted).toBe(true);
  poll.unmount();
  fetcher.mockResolvedValue(json([]));
  const submit = mount();
  await flush();
  fetcher.mockImplementation((_url: string, init: RequestInit) => {
    signal = init.signal;
    return new Promise<Response>(() => {});
  });
  act(() => {
    void submit.result.current.start('/api/persona/build');
  });
  submit.unmount();
  expect(signal?.aborted).toBe(true);
});
