import type { ChatReply, Turn } from '../features/chat/types';

/** A task as the list across twins gives it. */
export interface ListedTask {
  task_id: string;
  persona_id: string;
  title: string;
  status: 'idle' | 'running' | 'failed';
  updated_at: string;
}

export function conversationServer() {
  // The person's own twin, set by a test that has one; the tasks listed with the conversations.
  const own: { mine: { persona_id: string | null; pending: number } | null } = {
    mine: null,
  };
  const tasks: ListedTask[] = [];
  const rows = new Map<
    string,
    {
      id: string;
      title: string;
      turns: Turn[];
      updated_at: string;
      persona: string;
      /** The tier it answers from, where a test is about the person's own conversations. */
      audience?: 'self' | 'colleague';
      /** Asked by the person's assistant in their name, or how many colleagues' twins it asked in this one. */
      via?: 'direct' | 'delegate';
      delegated?: number;
    }
  >();
  const json = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), { status });
  const respond = (path: string, init?: RequestInit): Response | undefined => {
    const persona =
      new Headers(init?.headers).get('X-Twin-Persona') || 'default';
    if (path.startsWith('/api/personas/conversations')) {
      const query = new URL(path, 'http://localhost').searchParams;
      const offset = Number(query.get('offset') || 0);
      const only = query.get('with');
      const apart = query.get('mine') === 'true';
      const mineId = own.mine?.persona_id ?? null;
      const wanted = (id: string) =>
        (!only || id === only) && (id === mineId) === apart;
      const listed = [...rows.values()]
        // What the assistant asked in the person's name is listed with the assistant's own.
        .filter(
          (row) => wanted(row.persona) || (apart && row.via === 'delegate'),
        )
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
      return json({
        mine: own.mine,
        conversations: listed.slice(offset, offset + 50).map((row) => ({
          id: row.id,
          persona_id: row.persona,
          title: row.title,
          preview: row.turns.at(-1)?.content || '',
          updated_at: row.updated_at,
          via: row.via ?? 'direct',
          handoff: row.turns.at(-1)?.role === 'self' ? '本人已回' : null,
          delegated: row.delegated ?? 0,
        })),
        tasks: offset ? [] : tasks.filter((task) => wanted(task.persona_id)),
        more: listed.length > offset + 50,
      });
    }
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
            owner_replied: row.turns.at(-1)?.role === 'self',
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
  return { rows, respond, append, tasks, own };
}
