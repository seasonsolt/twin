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

/** Whether a twin is its viewer's own: the one they took on signing in (made for them, or found by their voice). On
 * a machine without sign-in there is one person, and the first twin is theirs. Only they answer for it when it can
 * not (``features/followups``); an administrator looking after it is not it. */
export const isSelf = (twin: Persona | undefined, signInOff: boolean) =>
  !!twin && (!!twin.mine || (signInOff && twin.is_default));

export const useIsSelf = (twin: Persona | undefined) =>
  isSelf(
    twin,
    useAuth((state) => state.identity?.auth_enabled === false),
  );

/** Whether the viewer is the person behind the twin, who sees all of what it remembers and answers for: the one it
 * was made for, once they have taken it and said it is all right (as the server counts it, ``Personas.audience``).
 * With no sign-in there is one person. Everyone else, those who look after the twin included, sees the part
 * colleagues may use. */
export const seesWhole = (twin: Persona | undefined, signInOff: boolean) =>
  signInOff || (!!twin?.mine && !!twin.approved);

export const useSeesWhole = (twin: Persona | undefined) =>
  seesWhole(
    twin,
    useAuth((state) => state.identity?.auth_enabled === false),
  );

/** The signed-in person's own twin, if they have one. */
export const useSelfTwin = () => {
  const signInOff = useAuth((state) => state.identity?.auth_enabled === false);
  return usePersonas((state) =>
    state.items.find((item) => isSelf(item, signInOff)),
  );
};
