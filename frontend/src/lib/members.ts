/** The member page of someone found in the recordings (``people.id``), and of a twin that no recording belongs to (a
 * twin made by hand, or someone else's public twin): until every twin has a person, they are two addresses. */
export const memberPath = (personId: string, section?: string) =>
  `/team/${encodeURIComponent(personId)}${section ? `?section=${section}` : ''}`;
export const twinMemberPath = (twinId: string, section?: string) =>
  `/team/twin/${encodeURIComponent(twinId)}${section ? `?section=${section}` : ''}`;
/** The chat with a twin (``?with=``): its conversations listed, the next message written to it. */
export const chatPath = (twinId: string) =>
  `/chat?with=${encodeURIComponent(twinId)}`;
