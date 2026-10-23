import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  Grid,
  Heading,
  PlainButton,
  Row,
  Stack,
  Text,
  TextLink,
  useConfirm,
} from '../components/ui';
import { api } from '../lib/api';
import { usePersonas, useTrial, type Persona } from '../stores/personas';
import { useWelcome } from '../stores/welcome';
import type { LedgerData, LedgerEntry } from '../features/ledger/types';
import type { ItemPage, ProfileItem } from '../features/profile/types';

const QUESTIONS = [
  '你最近在忙什么？',
  '这周还欠谁什么？',
  '你做决定时最看重什么？',
];

/** What the twin has gathered so far: the person's commitments from the meetings, and how it sees them. */
function useGathered(persona: Persona) {
  const [commitments, setCommitments] = useState<LedgerEntry[] | null>(null);
  const [items, setItems] = useState<ProfileItem[] | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const options = {
      signal: controller.signal,
      headers: { 'X-Twin-Persona': persona.id },
    };
    // Either can be missing while the twin is still being put together: the page then shows what there is.
    void api<LedgerData>('/api/persona/ledger', options)
      .then((data) =>
        setCommitments(
          (data.entries ?? [])
            .filter(
              (entry) =>
                entry.kind === 'commitment' && entry.owner === persona.name,
            )
            .slice(0, 3),
        ),
      )
      .catch(() => setCommitments([]));
    void api<ItemPage>('/api/persona/items?sort=evidence&limit=3', options)
      .then((page) => setItems(page.items ?? []))
      .catch(() => setItems([]));
    return () => controller.abort();
  }, [persona.id, persona.name]);
  return { commitments, items };
}

/**
 * The second step of the way in (``#/welcome``, which frames it): a twin someone else made for the signed-in person,
 * waiting for them. They took it by signing in with the work e-mail or employee number it was made for, or made it
 * themselves from the voices they recognised in colleagues' meetings (``MemberVoice``). They see what it gathered
 * and can try it out in chat; it answers nobody else until they say it is all right. "这不是我" gives a twin made
 * for them back to whoever made it, and a twin of their voices leads back to those voices.
 */
export function Claimed({ persona }: { persona: Persona }) {
  const { commitments, items } = useGathered(persona);
  const [shared, setShared] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const confirm = useConfirm();
  const navigate = useNavigate();
  const startTrial = useTrial((state) => state.set);
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
      startTrial(null);
      // Passed before the twin stops waiting, so the way in does not send them back to this step.
      useWelcome.getState().finishClaim('/profile');
    });
  const disown = async () => {
    if (
      await confirm({
        title: '这不是你的分身？',
        body: '它会退回给建它的人，并提示对方邮箱或工号填错了。',
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
  const tryOut = (ask: string) => {
    startTrial(persona.id);
    navigate('/chat', { state: { ask } });
  };
  return (
    <Stack gap={6}>
      <Stack gap={2} align="start">
        <Badge tone="success">已归到你名下</Badge>
        <Heading level={2} size="title">
          {persona.name}，你的分身已经建好了
        </Heading>
        <Text tone="secondary">
          {persona.made_by_other
            ? `同事按你的企业邮箱或工号为你建了分身，你用企业账号一登录就认领了。下面是它从 ${persona.sources} 段会议里整理出的你，还在继续整理。`
            : `它从你认出自己声音的 ${persona.sources} 段会议里认识你，还在继续整理。看过觉得没问题，同事就能问它了。`}
        </Text>
      </Stack>
      <Grid columns={2} gap={4}>
        <Card variant="outline">
          <Stack gap={3}>
            <Heading level={3} size="section">
              你在会上答应过的事
            </Heading>
            {commitments === null ? (
              <Text size="sm" tone="secondary">
                正在读取…
              </Text>
            ) : commitments.length ? (
              commitments.map((entry) => (
                <Stack key={entry.entry_id} gap={0}>
                  <Text>{entry.what}</Text>
                  <Text size="sm" tone="secondary">
                    {[entry.meeting_title, entry.meeting_date]
                      .filter(Boolean)
                      .join(' · ')}
                  </Text>
                </Stack>
              ))
            ) : (
              <Text size="sm" tone="secondary">
                还没整理出来，过一会儿在承诺账本里能看到。
              </Text>
            )}
          </Stack>
        </Card>
        <Card variant="outline">
          <Stack gap={3}>
            <Heading level={3} size="section">
              从会议里看出的你
            </Heading>
            {items === null ? (
              <Text size="sm" tone="secondary">
                正在读取…
              </Text>
            ) : items.length ? (
              items.map((item) => (
                <Stack key={item.item_id} gap={0}>
                  <Text>{item.statement}</Text>
                  <Text size="sm" tone="secondary">
                    {item.evidence.length} 处原话支持
                  </Text>
                </Stack>
              ))
            ) : (
              <Text size="sm" tone="secondary">
                还没整理出来，过一会儿在档案里能看到。
              </Text>
            )}
          </Stack>
        </Card>
      </Grid>
      <Card variant="outline">
        <Stack gap={3}>
          <Heading level={3} size="section">
            问它一句，看像不像你
          </Heading>
          <Row gap={2} wrap>
            {QUESTIONS.map((question) => (
              <Chip key={question} onClick={() => tryOut(question)}>
                {question}
              </Chip>
            ))}
          </Row>
          <Text size="sm" tone="secondary">
            试聊时同事还问不到它。哪条不对，点完“没问题”在档案里点开就能改。
          </Text>
        </Stack>
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
            {persona.made_by_other ? (
              <PlainButton disabled={busy} onClick={() => void disown()}>
                这不是我
              </PlainButton>
            ) : (
              <TextLink to="/voice" size="sm">
                回去再听一遍
              </TextLink>
            )}
            <Button loading={busy} onClick={() => void approve()}>
              没问题，开始用
            </Button>
          </Row>
        </Stack>
      </Card>
    </Stack>
  );
}
