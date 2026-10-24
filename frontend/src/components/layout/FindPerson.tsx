import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { AskDialog, LevelDots, type AskItem, type AskSection } from '../ui';
import { TeamAnswerCard } from '../../features/answers/TeamAnswerCard';
import { useAsk } from '../../features/ask/useAsk';
import { memberPath, twinMemberPath } from '../../lib/members';
import { usePersonas } from '../../stores/personas';
import { useTeam } from '../../stores/team';
import { looseTwins, namedPeople } from '../../features/library/teamCounts';
import { PersonaPortrait } from './PersonaSwitcher';

/** How many people are listed by name: the first few before anything is typed, the best matches after. */
const NAMES_SHOWN = 8;

/**
 * 问一句、找人 (⌘K): a name finds the person, a question is put to the whole team: the answers it already has, whom
 * to ask and the meetings it came up in. A person picked from the name list opens on their member page, one picked
 * from whom to ask opens a conversation with their twin with the question in the box.
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
  const [query, setQuery] = useState('');
  useEffect(() => {
    if (open) setQuery('');
  }, [open]);
  const named = people ? namedPeople(people) : [];
  const known: (AskItem & { to: string })[] = [
    ...named.map((person) => {
      const twin = twins.find(
        (t) => t.id === (person.persona_id ?? person.talk ?? person.twin_id),
      );
      return {
        id: `person-${person.id}`,
        label: person.name,
        detail: twin ? undefined : '没有分身',
        action: '看档案',
        leading: twin && <PersonaPortrait persona={twin} />,
        to: memberPath(person.id),
      };
    }),
    // Twins made without recordings (yourself, someone added by hand) are people to find too.
    ...looseTwins(people ?? [], twins).map((twin) => ({
      id: `twin-${twin.id}`,
      label: twin.name,
      action: '看档案',
      leading: <PersonaPortrait persona={twin} />,
      to: twinMemberPath(twin.id),
    })),
  ];
  const wanted = query.trim().toLocaleLowerCase();
  const byName = known
    .filter((item) => item.label.toLocaleLowerCase().includes(wanted))
    .slice(0, NAMES_SHOWN);
  // A name that is just a person's is found, not asked.
  const justAName = byName.some(
    (item) => item.label.toLocaleLowerCase() === wanted,
  );
  const { found, busy, error } = useAsk(query, open && !justAName);
  const sections: AskSection[] = [
    ...(byName.length ? [{ id: 'names', title: '找人', items: byName }] : []),
    ...(found?.team_answers.length
      ? [
          {
            id: 'answers',
            title: '团队答案',
            count: found.team_answers.length,
            cards: found.team_answers.map((card) => (
              <TeamAnswerCard key={card.id} card={card} labelled={false} />
            )),
          },
        ]
      : []),
    ...(found?.people.length
      ? [
          {
            id: 'people',
            title: '该问谁',
            count: found.people.length,
            note: found.decision ? '要拍板的，分身会转给本人' : undefined,
            items: found.people.map((row) => {
              const twin = twins.find((t) => t.id === row.persona_id);
              return {
                id: `ask-${row.persona_id}`,
                label: row.name,
                detail: [
                  row.label,
                  row.facets.join('、'),
                  `${row.occasions} 场`,
                ]
                  .filter(Boolean)
                  .join(' · '),
                leading: twin && <PersonaPortrait persona={twin} />,
                sign: <LevelDots level={row.level} />,
                action: '问分身',
              };
            }),
          },
        ]
      : []),
    ...(found?.meetings.length
      ? [
          {
            id: 'meetings',
            title: '会议',
            count: found.meetings.length,
            items: found.meetings.map((hit) => ({
              id: `meeting-${hit.line}-${hit.recording_id}`,
              label: `${hit.title} · ${hit.date.slice(5).replace('-', '/')}`,
              detail: `${hit.speaker ? `${hit.speaker}：` : ''}“${hit.quote}”`,
              action: '看录音',
            })),
          },
        ]
      : []),
  ];
  const select = (item: AskItem) => {
    const person = known.find((k) => k.id === item.id);
    if (person) return void navigate(person.to);
    if (item.id.startsWith('ask-'))
      return void navigate(
        `/chat?with=${encodeURIComponent(item.id.slice(4))}`,
        {
          state: { ask: query.trim() },
        },
      );
    if (item.id.startsWith('meeting-')) {
      const [, line, recording] = /^meeting-(\d+)-(.+)$/.exec(item.id) ?? [];
      if (recording)
        void navigate(`/library/${encodeURIComponent(recording)}?line=${line}`);
    }
  };
  return (
    <AskDialog
      open={open}
      onOpenChange={onOpenChange}
      title="问一句、找人"
      placeholder="问一件事，或输入名字"
      query={query}
      onQueryChange={setQuery}
      sections={sections}
      onSelect={select}
      busy={busy}
      notice={
        error ||
        (found?.degraded
          ? '向量模型暂时不可用，团队答案和该问谁没能查，只按字面找了会议'
          : undefined)
      }
      // Nothing is said about the team when it could not be asked: no answer found is not an answer.
      empty={
        justAName || error
          ? ''
          : found?.degraded
            ? '会议里也没找到'
            : '团队里还没人谈过这件事，可以按名字找人'
      }
      hint="↑↓ 选择　↵ 打开"
    />
  );
}
