import { useNavigate } from 'react-router';
import { SearchDialog, type SearchItem } from '../ui';
import { memberPath, twinMemberPath } from '../../lib/members';
import { usePersonas } from '../../stores/personas';
import { useTeam } from '../../stores/team';
import { namedPeople } from '../../features/library/teamCounts';
import { PersonaPortrait } from './PersonaSwitcher';

/**
 * Find someone by name from anywhere (⌘K): the team's people and the twins. Each opens on their member page, as
 * clicking them on the team page does.
 */
export function FindPerson({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const people = useTeam((state) => state.people);
  const twins = usePersonas((state) => state.items);
  const named = people ? namedPeople(people) : [];
  const linked = new Set(named.map((p) => p.persona_id).filter(Boolean));
  const items: (SearchItem & { to: string })[] = [
    ...named.map((person) => {
      const twin = twins.find((t) => t.id === person.persona_id);
      return {
        id: `person-${person.id}`,
        label: person.name,
        detail: twin ? '看档案' : '没有分身',
        leading: twin && <PersonaPortrait persona={twin} />,
        to: memberPath(person.id),
      };
    }),
    // Twins made without recordings (yourself, someone added by hand) are people to find too.
    ...twins
      .filter((twin) => !linked.has(twin.id))
      .map((twin) => ({
        id: `twin-${twin.id}`,
        label: twin.name,
        detail: '看档案',
        leading: <PersonaPortrait persona={twin} />,
        to: twinMemberPath(twin.id),
      })),
  ];
  return (
    <SearchDialog
      open={open}
      onOpenChange={onOpenChange}
      title="找人"
      placeholder="输入名字"
      empty="没有叫这个名字的人"
      items={items}
      onSelect={(item) => {
        const found = items.find((i) => i.id === item.id);
        if (found) void navigate(found.to);
      }}
    />
  );
}
