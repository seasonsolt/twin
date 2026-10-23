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
import { WorkClaim } from '../library/WorkClaim';
import { MemberHeader } from './MemberHeader';

const day = (iso: string) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ''
    : `${date.getMonth() + 1}月${date.getDate()}日`;
};

/** Someone found in the meetings who has no twin: the recordings they spoke in, and the way to make one. */
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
  const canMake = person.can_manage !== false && person.speakers > 0;
  return (
    <Page>
      <MemberHeader
        name={person.name}
        face={<PersonFace name={person.name} />}
        status={{
          label: person.twin_elsewhere ? '同事建了分身' : '没有分身',
          tone: 'neutral',
        }}
        primary={
          canMake
            ? { label: '生成分身', onClick: () => setClaiming(true) }
            : undefined
        }
      />
      {error && (
        <Text role="alert" tone="danger">
          {error}
        </Text>
      )}
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
        onClose={() => setClaiming(false)}
        onSave={(claim) => void make(claim)}
      />
    </Page>
  );
}
