import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router';
import { Skeleton } from '../components/ui';
import { memberPath, twinMemberPath } from '../lib/members';
import { usePersonas } from '../stores/personas';
import { useTeam } from '../stores/team';

/**
 * The old profile addresses (``#/profile``, ``#/memories``, ``#/about`` and the like) lead to the member page of the
 * twin in view, on the tab they named: so the links still in the app and in people's bookmarks need no change.
 * Someone found in the recordings is at their own address; a twin no recording belongs to, at its own.
 */
export function ProfileRedirect({ section }: { section?: string }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const here = useLocation().pathname;
  // The page may still be fading out as the next address opens: only the one at its own address sends anyone away.
  const mountedAt = useRef(here);
  const id = usePersonas((state) => state.id);
  const twins = usePersonas((state) => state.items);
  const people = useTeam((state) => state.people);
  const [listed, setListed] = useState(false);
  const [asked, setAsked] = useState(false);
  useEffect(() => {
    let alive = true;
    void usePersonas
      .getState()
      .refresh()
      .catch(() => {})
      .finally(() => alive && setListed(true));
    return () => {
      alive = false;
    };
  }, []);
  const twin = twins.find((item) => item.id === id) ?? twins[0];
  // Whose twin it is, when the viewer can see the team's people.
  useEffect(() => {
    if (!listed || !twin || people) return;
    let alive = true;
    void useTeam
      .getState()
      .refreshPeople()
      .catch(() => {})
      .finally(() => alive && setAsked(true));
    return () => {
      alive = false;
    };
  }, [listed, twin, people]);
  const ready = listed && (!twin || !!people || asked);
  // Older links named the tab ``?tab=``; the member page's own word for it is ``section``.
  const wanted = section ?? params.get('section') ?? params.get('tab') ?? '';
  const view = params.get('view');
  const query = new URLSearchParams();
  if (wanted) query.set('section', wanted);
  if (view) query.set('view', view);
  const person = people?.find((p) => p.persona_id === twin?.id);
  const base = !twin
    ? '/team'
    : person
      ? memberPath(person.id)
      : twinMemberPath(twin.id);
  const search = twin ? query.toString() : '';
  const target =
    ready && here === mountedAt.current
      ? search
        ? `${base}?${search}`
        : base
      : null;
  useEffect(() => {
    if (target !== null) void navigate(target, { replace: true });
  }, [target, navigate]);
  return <Skeleton className="h-40" />;
}
