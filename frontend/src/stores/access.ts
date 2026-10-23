import { useAuth } from './auth';
import { usePersonas, type Persona } from './personas';

/** Whether someone runs twins: an administrator, or anyone with a twin they can manage. Everybody else who signed in
 * is a guest, who may only talk to the twins others made public. With no twin at all yet, whoever signed in is
 * offered to make one, so they are not a guest. */
export const runsTwins = (admin: boolean | undefined, items: Persona[]) =>
  !!admin ||
  items.length === 0 ||
  items.some((item) => item.can_manage ?? true);

/** The team's side: the places for running twins (team, recordings, what waits). Not about the twin in view. */
export const useCanManage = () => {
  const admin = useAuth((state) => state.identity?.admin);
  const items = usePersonas((state) => state.items);
  return runsTwins(admin, items);
};

/** Only the person behind the twin in view can change what it remembers; for a public twin of someone else, even
 * a manager of other twins is a visitor. */
export const useManagesCurrent = () =>
  usePersonas(
    (state) =>
      state.items.find((item) => item.id === state.id)?.can_manage ?? true,
  );
