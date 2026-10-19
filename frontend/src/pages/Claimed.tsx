import { useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Heading,
  KeyValue,
  PlainButton,
  Row,
  Stack,
  Text,
  useConfirm,
} from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { api } from '../lib/api';
import { usePersonas, type Persona } from '../stores/personas';
import { useStatus } from '../stores/status';

/**
 * A twin someone else made for the signed-in person, waiting for them: they took it by signing in with the work
 * e-mail it was made for. It answers nobody else until they have looked at it and said it is all right; "这不是我"
 * gives it back to whoever made it.
 */
export function Claimed({ persona }: { persona: Persona }) {
  const counts = useStatus((state) => state.data?.counts);
  const [shared, setShared] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const confirm = useConfirm();
  const navigate = useNavigate();
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError('');
    try {
      await work();
      await usePersonas.getState().refresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  const approve = () =>
    act(async () => {
      await api(`/api/personas/${encodeURIComponent(persona.id)}/approve`, {
        method: 'POST',
        json: { public: shared },
      });
      navigate('/profile');
    });
  const disown = async () => {
    if (
      await confirm({
        title: '这不是你的分身？',
        body: '它会退回给建它的人，并提示对方邮箱填错了。',
        confirmLabel: '这不是我',
        tone: 'danger',
      })
    )
      await act(() =>
        api(`/api/personas/${encodeURIComponent(persona.id)}/disown`, {
          method: 'POST',
        }),
      );
  };
  return (
    <main className="entry-page min-h-dvh">
      <StageHeader variant="brand" />
      <section className="mx-auto max-w-xl px-4 py-8">
        <Stack gap={6}>
          <Stack gap={2} align="start">
            <Badge tone="success">已归到你名下</Badge>
            <Heading level={2} size="title">
              {persona.name}，你的分身已经建好了
            </Heading>
            <Text tone="secondary">
              同事用你的企业邮箱为你建了分身，你用企业账号一登录就认领了。它已经从会议里认识了你。
            </Text>
          </Stack>
          <Card variant="outline">
            <KeyValue
              layout="rows"
              items={[
                [
                  '认出你声音的会议',
                  `${counts?.sources ?? persona.sources} 段`,
                ],
                ['从会议里看出的你', `${counts?.items ?? 0} 条`],
              ]}
            />
          </Card>
          <Card variant="outline">
            <Stack gap={4}>
              <Checkbox
                label="同事能问我的分身"
                checked={shared}
                disabled={busy}
                onChange={(event) => setShared(event.target.checked)}
              />
              <Text size="sm" tone="secondary">
                按你的说法回答，拿不准就说回头问你，不替你拍板。你点“没问题”之前，它不对同事回答；以后可以在档案里改。
              </Text>
              {error && (
                <Text size="sm" tone="danger" role="alert">
                  {error}
                </Text>
              )}
              <Row justify="between" wrap gap={3}>
                <PlainButton disabled={busy} onClick={() => void disown()}>
                  这不是我
                </PlainButton>
                <Button loading={busy} onClick={() => void approve()}>
                  没问题，开始用
                </Button>
              </Row>
            </Stack>
          </Card>
        </Stack>
      </section>
    </main>
  );
}
