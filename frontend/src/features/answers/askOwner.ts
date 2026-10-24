import { api } from '../../lib/api';

/** Where the question went: the conversation in the person's twin, in which their reply will come. */
export interface Asked {
  persona_id: string;
  conversation_id: string;
}

/**
 * 问某某本人: hand the asker's question to the person who confirmed a team answer, in the asker's name. It opens a
 * conversation of the asker's with that person's twin, where their reply will come; asked again while the person has
 * not answered, it is the same conversation.
 */
export async function askOwner(id: string, question: string): Promise<Asked> {
  return api<Asked>(
    `/api/personas/team-answers/${encodeURIComponent(id)}/ask`,
    {
      method: 'POST',
      json: { question },
    },
  );
}

/** The conversation the question went to, as an address. */
export const askedPath = (asked: Asked) =>
  `/chat?with=${encodeURIComponent(asked.persona_id)}&open=${encodeURIComponent(asked.conversation_id)}`;
