import { useId, useState, type FormEvent } from 'react';
import { Button, Dialog, Field, Input, Row, Stack } from '../../components/ui';
import { api } from '../../lib/api';
import { useAuth } from '../../stores/auth';

/** What ``POST /api/heir/open`` answers: the first opening waits for ``confirm``; then the heir is in. */
export type Opening =
  | { status: 'confirm' }
  | {
      status: 'open';
      heir: { id: string; name: string };
      sealed_now: boolean;
    };

/**
 * 我是继承人: an heir the will names gives their name and word. The first opening says it seals the memory for good
 * and waits for them to confirm; once they are in, the page becomes their own conversation (``useAuth.login``). The
 * word stays in this dialog only while it is open.
 */
export function HeirDoor({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const id = useId();
  const [name, setName] = useState('');
  const [word, setWord] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const close = (next: boolean) => {
    if (!next) {
      setWord('');
      setConfirming(false);
      setError('');
    }
    onOpenChange(next);
  };
  const enter = async (confirm: boolean) => {
    setBusy(true);
    setError('');
    try {
      const opened = await api<Opening>('/api/heir/open', {
        method: 'POST',
        json: { name, password: word, confirm },
      });
      if (opened.status === 'confirm') {
        setConfirming(true);
        return;
      }
      setWord('');
      await useAuth.getState().login();
    } catch (failure) {
      setConfirming(false);
      setError(failure instanceof Error ? failure.message : '没能进入，请重试');
    } finally {
      setBusy(false);
    }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() && word) void enter(false);
  };
  if (confirming)
    return (
      <Dialog
        open={open}
        onOpenChange={close}
        title="开启后记忆冻结"
        body="确认后立即开启，记忆从此冻结，不能撤回。"
      >
        <Row gap={2} justify="end">
          <Button variant="ghost" onClick={() => close(false)}>
            取消
          </Button>
          <Button
            variant="danger"
            loading={busy}
            onClick={() => void enter(true)}
          >
            确认开启
          </Button>
        </Row>
      </Dialog>
    );
  return (
    <Dialog open={open} onOpenChange={close} title="我是继承人">
      <form onSubmit={submit}>
        <Stack gap={4}>
          <Field id={`${id}-name`} label="称呼">
            <Input
              id={`${id}-name`}
              autoComplete="off"
              maxLength={64}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field id={`${id}-word`} label="口令" error={error || undefined}>
            <Input
              id={`${id}-word`}
              type="password"
              autoComplete="current-password"
              maxLength={128}
              value={word}
              onChange={(event) => setWord(event.target.value)}
            />
          </Field>
          <Row gap={2} justify="end">
            <Button variant="ghost" onClick={() => close(false)}>
              取消
            </Button>
            <Button
              type="submit"
              loading={busy}
              disabled={!name.trim() || !word}
            >
              进入
            </Button>
          </Row>
        </Stack>
      </form>
    </Dialog>
  );
}
