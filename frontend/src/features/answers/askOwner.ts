import { api } from '../../lib/api';

/**
 * 还有疑问，问某某: hand the asker's question to the person who confirmed a team answer, in the asker's name. It opens a
 * conversation of the asker's with that person's twin, where their reply will come.
 */
export async function askOwner(id: string, question: string): Promise<void> {
  await api(`/api/personas/team-answers/${encodeURIComponent(id)}/ask`, {
    method: 'POST',
    json: { question },
  });
}
