import { useState } from 'react';
import {
  Heading,
  ListRow,
  Page,
  Stack,
  Text,
  TextLink,
} from '../../components/ui';
import { api } from '../../lib/api';
import type { Person } from '../../pages/Recording';
import { usePersonas } from '../../stores/personas';
import { useTeam } from '../../stores/team';
import { PersonFace } from '../library/PersonFace';
import { TWIN_STATES, twinState } from '../library/Team';
import { WorkClaim } from '../library/WorkClaim';
import { MemberHeader } from './MemberHeader';

const day = (iso: string) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ''
    : `${date.getMonth() + 1}月${date.getDate()}日`;
};

/** Someone found in the meetings whose twin the viewer cannot open: the recordings they spoke in, and, only while no
 * twin exists for them, the way to make one. A twin of their own voices, or one a colleague keeps, is not the viewer's
 * to make again (the server refuses), so the page says whose it is and offers nothing. */
export function NoTwinMember({ person }: { person: Person }) {
  const library = useTeam((state) => state.library);
  const recordings = (library?.recordings ?? []).filter((recording) =>
    recording.people.includes(person.name),
  );
  const [claiming, setClaiming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const make = async (claim: string) => {
    setBusy(true);
    setError('');
    try {
      await api(
        `/api/library/people/${encodeURIComponent(person.id)}/persona`,
        {
          method: 'POST',
          json: { claim: claim || null },
        },
      );
      await usePersonas.getState().refresh();
      await useTeam.getState().refreshPeople();
      setClaiming(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '没能建好分身');
    } finally {
      setBusy(false);
    }
  };
  // The same word as the team table's.
  const state = twinState(person);
  const canMake =
    state === 'none' && person.can_manage !== false && person.speakers > 0;
  return (
    <Page>
      <MemberHeader
        name={person.name}
        face={<PersonFace name={person.name} />}
        status={TWIN_STATES[state]}
        primary={
          canMake
            ? {
                label: '生成分身',
                onClick: () => {
                  setError('');
                  setClaiming(true);
                },
              }
            : undefined
        }
      />
      <Stack as="section" gap={3} aria-label="参加过的录音">
        <Heading level={2} size="section">
          参加过的录音
        </Heading>
        {recordings.length === 0 ? (
          <Text size="sm" tone="secondary">
            还没有录音。
          </Text>
        ) : (
          <Stack as="ul" gap={0}>
            {recordings.slice(0, 10).map((recording) => (
              <ListRow
                key={recording.id}
                variant="divided"
                title={
                  <TextLink to={`/library/${encodeURIComponent(recording.id)}`}>
                    {recording.filename}
                  </TextLink>
                }
                meta={day(recording.created_at)}
              />
            ))}
          </Stack>
        )}
      </Stack>
      <WorkClaim
        person={claiming ? person : null}
        busy={busy}
        error={error}
        onClose={() => setClaiming(false)}
        onSave={(claim) => void make(claim)}
      />
    </Page>
  );
}
