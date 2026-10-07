export async function* readSSE(response: Response, signal: AbortSignal) {
  if (!response.body) throw new Error('服务没有返回回复流');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let event = '';
  let data: string[] = [];
  const abort = () => void reader.cancel().catch(() => {});
  signal.addEventListener('abort', abort, { once: true });
  try {
    for (;;) {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      const chunk = await reader.read();
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      buffer += decoder.decode(chunk.value, { stream: !chunk.done });
      let end: number;
      while ((end = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, end).replace(/\r$/u, '');
        buffer = buffer.slice(end + 1);
        if (!line) {
          if (data.length)
            yield { event, data: JSON.parse(data.join('\n')) as unknown };
          event = '';
          data = [];
        } else if (line.startsWith('event:')) {
          event = line.slice(6).trimStart();
        } else if (line.startsWith('data:')) {
          data.push(line.slice(5).replace(/^ /u, ''));
        }
      }
      if (chunk.done) return;
    }
  } finally {
    signal.removeEventListener('abort', abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
