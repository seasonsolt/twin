import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../lib/api';
import { basePath, withBase } from '../lib/base';
import { uploadForm } from '../lib/mediaUpload';
import { personaUrl } from '../lib/persona';

describe('serving under a path prefix', () => {
  afterEach(() => window.history.replaceState(null, '', '/'));

  it('derives the prefix from the page directory', () => {
    expect(basePath('https://daw.example.com/')).toBe('');
    expect(basePath('https://daw.example.com/twin/')).toBe('/twin');
    expect(basePath('https://daw.example.com/twin/#/chat')).toBe('/twin');
    expect(basePath('https://daw.example.com/a/b/index.html')).toBe('/a/b');
  });

  it('prefixes only same-origin absolute paths', () => {
    expect(withBase('/api/status', '/twin')).toBe('/twin/api/status');
    expect(withBase('/api/status', '')).toBe('/api/status');
    expect(withBase('//evil.example/api', '/twin')).toBe('//evil.example/api');
    expect(withBase('blob:abc', '/twin')).toBe('blob:abc');
  });

  it('sends requests and media URLs through the prefix', async () => {
    window.history.replaceState(null, '', '/twin/#/chat');
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', fetcher);
    await api('/api/status');
    expect(fetcher.mock.calls[0][0]).toBe('/twin/api/status');
    expect(personaUrl('/api/media/avatar-image?v=1', 'p1')).toBe(
      '/twin/api/media/avatar-image?v=1&persona=p1',
    );
    window.history.replaceState(null, '', '/');
    expect(personaUrl('/api/media/avatar-image', 'p1')).toBe(
      '/api/media/avatar-image?persona=p1',
    );
  });

  it('sends progress uploads through the prefix', async () => {
    window.history.replaceState(null, '', '/twin/#/memories');
    const opened: string[] = [];
    class FakeXHR {
      upload = {};
      status = 200;
      responseText = '{"ok":true}';
      onload: (() => void) | null = null;
      open(_method: string, url: string) {
        opened.push(url);
      }
      setRequestHeader() {}
      send() {
        this.onload?.();
      }
      abort() {}
    }
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    await uploadForm(
      '/api/persona/import',
      new FormData(),
      new AbortController().signal,
      () => {},
    );
    expect(opened).toEqual(['/twin/api/persona/import']);
    vi.unstubAllGlobals();
  });
});
