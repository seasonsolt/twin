import { MemoryRouter, Route, Routes } from 'react-router';
import { Settings } from '../features/settings/Settings';
import { Member } from '../pages/Member';
import { usePersonas, type Persona } from '../stores/personas';

/** A twin the signed-in person manages, as the list of twins holds it. */
export const memberTwin = (change: Partial<Persona> = {}): Persona => ({
  id: 'default',
  name: '本人',
  avatar_url: null,
  sources: 1,
  created_at: '',
  is_default: true,
  can_manage: true,
  ...change,
});

/** The twins the page knows of, with the first in view (the member page switches to the one its address names). */
export function showTwins(items: Persona[] = [memberTwin()]) {
  usePersonas.setState({ id: items[0].id, items, pendingId: null });
}

/** A member page as its address opens it: ``/team/twin/:id`` with the search, or ``/team/:person`` for a person. */
export function MemberAt({ path = '/team/twin/default' }: { path?: string }) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="team/twin/:twinId" element={<Member />} />
        <Route path="team/:id" element={<Member />} />
        <Route path="team" element={<p>团队页</p>} />
        <Route path="chat" element={<p>聊天页</p>} />
      </Routes>
      <Settings />
    </MemoryRouter>
  );
}
