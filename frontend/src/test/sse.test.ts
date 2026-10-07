import { expect, it, vi } from 'vitest';
import { readSSE } from '../lib/sse';

it('decodes split UTF-8, CRLF, comments and multiline SSE data without leaking heartbeats', async () => {
  const bytes = new TextEncoder().encode(
    ': connected\r\n\r\nevent: delta\r\ndata: {"text":"你好"}\r\n\r\n' +
      ': heartbeat\n\nevent: final\ndata: {"reply":\ndata: "修正回复"}\n\n',
  );
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        controller.close();
      },
    }),
  );
  const events = [];
  for await (const event of readSSE(response, new AbortController().signal))
    events.push(event);
  expect(events).toEqual([
    { event: 'delta', data: { text: '你好' } },
    { event: 'final', data: { reply: '修正回复' } },
  ]);
});

it('cancels and unlocks a pending reader on abort', async () => {
  const cancel = vi.fn();
  const response = new Response(new ReadableStream({ cancel }));
  const controller = new AbortController();
  const events = readSSE(response, controller.signal);
  const pending = events.next();
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  expect(cancel).toHaveBeenCalledOnce();
  expect(response.body?.locked).toBe(false);
});
