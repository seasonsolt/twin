import { useState } from 'react';
import { Button, Field, Input, Textarea } from '../../components/ui';
import { api } from '../../lib/api';
import { useStatus } from '../../stores/status';
import type { IdentityData } from './useIdentity';

export function IdentityForm({
  identity,
  onSaved,
}: {
  identity: Pick<IdentityData, 'name' | 'about'>;
  onSaved?: (saved: IdentityData) => void;
}) {
  const [name, setName] = useState(identity.name);
  const [about, setAbout] = useState(identity.about || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        setError('');
        void api<IdentityData>('/api/identity', {
          method: 'PUT',
          json: { name: name.trim(), about: about.trim() },
        })
          .then((saved) => {
            onSaved?.(saved);
            void useStatus.getState().refresh();
          })
          .catch((failure: unknown) => {
            setError(
              failure instanceof Error ? failure.message : '保存失败，请重试',
            );
          })
          .finally(() => setBusy(false));
      }}
    >
      <Field id="identity-name" label="名字">
        <Input
          id="identity-name"
          required
          maxLength={20}
          value={name}
          disabled={busy}
          onChange={(event) => setName(event.target.value)}
        />
      </Field>
      <Field
        id="identity-about"
        label="介绍一下自己"
        help="最多 200 字，会保存为一条记忆。"
      >
        <Textarea
          id="identity-about"
          maxLength={200}
          value={about}
          disabled={busy}
          onChange={(event) => setAbout(event.target.value)}
          placeholder="例如：我叫小林，在杭州做设计。喜欢徒步和做饭，最近在学摄影。做事时我很看重真诚，也希望多留些时间陪家人。"
        />
      </Field>
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
      <Button type="submit" loading={busy} disabled={!name.trim()}>
        保存
      </Button>
    </form>
  );
}
