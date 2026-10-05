import { describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../lib/api';

describe('local API client', () => {
  it.each(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'])(
    'uses the correct CSRF header for %s',
    async (method) => {
      const fetcher = vi.fn().mockResolvedValue(new Response('{}'));
      vi.stubGlobal('fetch', fetcher);
      await api('/api/example', { method, headers: { 'X-Twin': 'bad' } });
      expect(fetcher.mock.calls[0][1].headers.get('X-Twin')).toBe(
        method === 'GET' ? null : '1',
      );
      expect(fetcher.mock.calls[0][1].credentials).toBe('same-origin');
    },
  );

  it('encodes JSON and lets the browser provide the multipart boundary', async () => {
    const fetcher = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response('{}')));
    vi.stubGlobal('fetch', fetcher);
    await api('/api/example', { method: 'POST', json: { name: '本人' } });
    expect(fetcher.mock.calls[0][1].headers.get('Content-Type')).toBe(
      'application/json',
    );
    expect(fetcher.mock.calls[0][1].body).toBe('{"name":"本人"}');
    const form = new FormData();
    form.append('files', new Blob(['test']), 'test.txt');
    await api('/api/example', { method: 'POST', form });
    expect(fetcher.mock.calls[1][1].headers.has('Content-Type')).toBe(false);
    expect(fetcher.mock.calls[1][1].body).toBe(form);
  });

  it('maps Chinese detail to a typed error and preserves its status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: '请求被安全策略拒绝' }), {
          status: 403,
        }),
      ),
    );
    await expect(api('/api/example')).rejects.toMatchObject({
      name: 'ApiError',
      status: 403,
      message: '请求被安全策略拒绝',
      detail: '请求被安全策略拒绝',
    });
  });

  it('maps unstructured errors and network failures to Chinese', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('Not Found', { status: 404 })),
    );
    await expect(api('/api/missing')).rejects.toThrow('找不到请求的资源');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    );
    await expect(api('/api/status')).rejects.toThrow('无法连接本地服务');
  });

  it('rejects remote requests', async () => {
    await expect(api('https://example.com/api/status')).rejects.toBeInstanceOf(
      ApiError,
    );
    await expect(api('//example.com/api/status')).rejects.toThrow(
      '仅允许访问本地 API',
    );
  });
});
