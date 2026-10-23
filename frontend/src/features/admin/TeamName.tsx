import { useState, type FormEvent } from 'react';
import { Button, Field, Input, Row, Stack, Text } from '../../components/ui';
import { setTeamName } from '../../stores/auth';
import { TEAM_NAME } from '../../stores/team';
import { useSystem } from '../../stores/system';

/** The longest name the server keeps. */
const MAX_CHARS = 20;

/** What the side bar and the sign-in page call the team. */
export function TeamName({ name }: { name: string | null | undefined }) {
  const put = useSystem((state) => state.put);
  const [value, setValue] = useState(name ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = (next: string) => {
    setBusy(true);
    setError('');
    put('/api/admin/system/team', { name: next })
      .then(() => setTeamName(next.trim() || null))
      .catch((failure: unknown) =>
        setError(failure instanceof Error ? failure.message : '保存失败'),
      )
      .finally(() => setBusy(false));
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save(value);
  };
  return (
    <form onSubmit={submit}>
      <Stack gap={4}>
        <Field id="system-team-name" label="团队名">
          <Input
            id="system-team-name"
            maxLength={MAX_CHARS}
            placeholder={TEAM_NAME}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </Field>
        <Row gap={2} wrap>
          <Button
            type="submit"
            loading={busy}
            disabled={value.trim() === (name ?? '')}
          >
            保存
          </Button>
          {name && (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setValue('');
                save('');
              }}
            >
              清除
            </Button>
          )}
        </Row>
        {error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
      </Stack>
    </form>
  );
}
