import type { ChatReply, Turn } from '../features/chat/types';

export function conversationServer() {
  const rows = new Map<
    string,
    {
      id: string;
      title: string;
      turns: Turn[];
      updated_at: string;
      persona: string;
    }
  >();
  const json = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), { status });
  const respond = (path: string, init?: RequestInit): Response | undefined => {
    const persona =
      new Headers(init?.headers).get('X-Twin-Persona') || 'default';
    if (path === '/api/conversations' && init?.method === 'POST') {
      const body = JSON.parse((init.body as string) || '{}');
      const id = body.migration_id || crypto.randomUUID();
      if (!rows.has(id))
        rows.set(id, {
          id,
          title:
            body.turns
              ?.find((turn: Turn) => turn.role === 'user')
              ?.content.slice(0, 24) || '新对话',
          turns: body.turns || [],
          updated_at: body.turns?.at(-1)?.timestamp || new Date().toISOString(),
          persona,
        });
      return json({ id }, 201);
    }
    if (
      path.startsWith('/api/conversations?') ||
      path === '/api/conversations'
    ) {
      const offset = Number(
        new URL(path, 'http://localhost').searchParams.get('offset') || 0,
      );
      return json(
        [...rows.values()]
          .filter((row) => row.persona === persona)
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
          .slice(offset, offset + 50)
          .map((row) => ({
            ...row,
            preview: row.turns.at(-1)?.content || '',
            turns: row.turns.length,
          })),
      );
    }
    if (path.startsWith('/api/conversations/')) {
      const id = decodeURIComponent(path.split('/').at(-1)!);
      const row = rows.get(id);
      if (!row || row.persona !== persona)
        return json({ detail: '找不到这段对话' }, 404);
      if (init?.method === 'PATCH') {
        row.title = JSON.parse(init.body as string).title;
        return json({ updated: true });
      }
      if (init?.method === 'DELETE') {
        rows.delete(id);
        return json({ deleted: true });
      }
      return json(row);
    }
  };
  const append = (init: RequestInit, reply: ChatReply) => {
    const body = JSON.parse(init.body as string);
    const row = rows.get(body.conversation_id)!;
    const user = body.messages.at(-1);
    if (!row.turns.some((turn) => turn.role === 'user'))
      row.title = user.content.slice(0, 24);
    row.turns.push(
      { ...user, id: crypto.randomUUID(), timestamp: new Date().toISOString() },
      {
        id: crypto.randomUUID(),
        role: 'twin',
        content: reply.reply,
        reply,
        timestamp: new Date().toISOString(),
      },
    );
    row.updated_at = new Date().toISOString();
  };
  return { rows, respond, append };
}
