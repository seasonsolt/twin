import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { Mic, Square } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  ClipButton,
  Heading,
  ListRow,
  Notice,
  Page,
  PlainButton,
  Row,
  Skeleton,
  Stack,
  Text,
  TextLink,
} from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { useRecorder } from '../features/assets/useRecorder';
import { api, ApiError } from '../lib/api';
import { withBase } from '../lib/base';
import { usePersonas } from '../stores/personas';

/** A voice in a colleague's meeting: one sentence of it, offered or already said to be theirs. */
export interface VoiceItem {
  id: string;
  state: 'offered' | 'mine';
  quote: string;
  title: string;
  date: string | null;
  more: number;
  unsure: boolean;
  sample_url: string;
}

export interface VoiceState {
  available: boolean;
  enrolled: boolean;
  items: VoiceItem[];
  persona_id: string | null;
  /** Some voices they confirmed are in a library their twin does not follow. */
  elsewhere: boolean;
}

const day = (date: string | null) => {
  const found = date?.match(/^\d{4}-(\d{2})-(\d{2})/u);
  return found ? `${Number(found[1])} 月 ${Number(found[2])} 日` : null;
};

/**
 * 员工 1b: someone signed in through the company login, with no twin made for them, finds their voice in the
 * meetings colleagues uploaded. They read a sentence aloud, hear one sentence of each voice like theirs and say
 * "是我" or "不是"; the twin made from what they confirm is theirs. ``onSkip`` leads on to an empty twin; without
 * it (opened again later) the page only adds voices to the twin.
 */
export function MemberVoice({ onSkip }: { onSkip?: () => void }) {
  const [state, setState] = useState<VoiceState | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const recorder = useRecorder();
  const navigate = useNavigate();

  const act = useCallback(
    async (key: string, work: () => Promise<VoiceState>) => {
      setBusy(key);
      setError('');
      try {
        setState(await work());
      } catch (failure) {
        setError(
          failure instanceof Error ? failure.message : '操作失败，请重试',
        );
      } finally {
        setBusy('');
      }
    },
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    api<VoiceState>('/api/library/voice', { signal: controller.signal })
      .then((found) => {
        if (found.available || found.enrolled) setState(found);
        else onSkip?.();
      })
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 404) onSkip?.();
        else setError(failure instanceof Error ? failure.message : '加载失败');
      });
    return () => controller.abort();
  }, [onSkip]);

  const { file, reset } = recorder;
  useEffect(() => {
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    reset();
    void act('enroll', () =>
      api<VoiceState>('/api/library/voice', { method: 'PUT', form }),
    );
  }, [file, reset, act]);

  const answer = (item: VoiceItem, verdict: 'me' | 'not') =>
    act(item.id, () =>
      api<VoiceState>(
        `/api/library/voice/offers/${encodeURIComponent(item.id)}`,
        { method: 'POST', json: { verdict } },
      ),
    );
  const takeBack = (item: VoiceItem) =>
    act(item.id, () =>
      api<VoiceState>(
        `/api/library/voice/claims/${encodeURIComponent(item.id)}`,
        { method: 'DELETE' },
      ),
    );
  const again = () =>
    act('again', () =>
      api<VoiceState>('/api/library/voice', { method: 'DELETE' }),
    );
  const openTwin = async (personaId: string) => {
    setBusy('open');
    try {
      await usePersonas.getState().refresh();
      await usePersonas.getState().switchTo(personaId);
      navigate('/profile');
    } finally {
      setBusy('');
    }
  };

  const mine = state?.items.filter((item) => item.state === 'mine') ?? [];
  const recording =
    recorder.state === 'recording' || recorder.state === 'requesting';
  const title = '会议里可能有你';
  const description = `${onSkip ? '管理员还没为你建分身。' : ''}听一句就够：确认是你之后，你的分身就从这些会议里认识你，不用另外上传资料。`;
  const content = !state ? (
    error ? (
      <Notice tone="danger" role="alert">
        {error}
      </Notice>
    ) : (
      <Skeleton className="h-40" />
    )
  ) : !state.enrolled ? (
    <Card variant="outline">
      <Stack gap={4}>
        <Stack gap={1}>
          <Text weight="semibold">先读一句话，让我们听听你的声音</Text>
          <Text size="sm" tone="secondary">
            十秒左右就够，比如介绍一下自己最近在忙什么。录音只用来在同事传的会议里找像你的声音，比对完就删掉。
          </Text>
        </Stack>
        {(recorder.error || error) && (
          <Text size="sm" tone="danger" role="alert">
            {recorder.error || error}
          </Text>
        )}
        <Row wrap gap={3}>
          {recording ? (
            <Button
              variant="secondary"
              onClick={recorder.stop}
              disabled={recorder.state === 'requesting'}
            >
              <Square aria-hidden className="size-4" />
              说完了（{recorder.seconds} 秒）
            </Button>
          ) : (
            <Button
              loading={busy === 'enroll'}
              onClick={() => void recorder.start()}
            >
              <Mic aria-hidden className="size-4" />
              {busy === 'enroll' ? '正在会议里找你' : '开始录音'}
            </Button>
          )}
          {onSkip && !recording && busy !== 'enroll' && (
            <PlainButton onClick={onSkip}>没开过会，先建空分身</PlainButton>
          )}
        </Row>
      </Stack>
    </Card>
  ) : state.items.length === 0 ? (
    <Notice
      title="已有的会议里还没听到你"
      actions={
        <Row wrap gap={2}>
          <Button
            variant="secondary"
            loading={busy === 'again'}
            onClick={() => void again()}
          >
            重新录一句
          </Button>
          {onSkip && <Button onClick={onSkip}>先建一个空分身</Button>}
        </Row>
      }
    >
      同事传上来的会议里有你时，再回来听一遍就行。
    </Notice>
  ) : (
    <>
      <Card variant="outline" padding="none">
        <ul aria-label="可能是你的声音" className="px-4">
          {state.items.map((item) => (
            <ListRow
              key={item.id}
              variant="divided"
              leading={
                <ClipButton
                  label={`播放：${item.title}里的这句话`}
                  src={withBase(item.sample_url)}
                />
              }
              title={
                <Text tone={item.unsure ? 'secondary' : 'primary'}>
                  “{item.quote}”
                </Text>
              }
              meta={[
                item.title,
                day(item.date),
                item.unsure
                  ? '声音较像，拿不准'
                  : item.more > 0
                    ? `另有 ${item.more} 段`
                    : null,
              ]
                .filter(Boolean)
                .join(' · ')}
              trailing={
                item.state === 'mine' ? (
                  <>
                    <Badge tone="success">✓ 是我</Badge>
                    <PlainButton
                      disabled={!!busy}
                      onClick={() => void takeBack(item)}
                    >
                      撤回
                    </PlainButton>
                  </>
                ) : (
                  <>
                    <Button
                      variant={item.unsure ? 'secondary' : 'primary'}
                      loading={busy === item.id}
                      disabled={!!busy}
                      onClick={() => void answer(item, 'me')}
                    >
                      是我
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={!!busy}
                      onClick={() => void answer(item, 'not')}
                    >
                      不是
                    </Button>
                  </>
                )
              }
            />
          ))}
        </ul>
      </Card>
      <Text size="sm" tone="secondary">
        同一个人的几段声音合在一起，确认一次就够。点错了可以撤回。
      </Text>
      {state.elsewhere && mine.length > 0 && (
        <Text size="sm" tone="secondary">
          有的会议在另一位同事的录音库里：已经告诉对方那是你，但暂时不进这个分身。
        </Text>
      )}
      {error && (
        <Text size="sm" tone="danger" role="alert">
          {error}
        </Text>
      )}
      <Row justify="between" wrap gap={3}>
        {onSkip && mine.length === 0 ? (
          <TextLink size="sm" onClick={onSkip}>
            一段都不是我
          </TextLink>
        ) : (
          <span />
        )}
        <Button
          size="lg"
          disabled={!state.persona_id || !!busy}
          loading={busy === 'open'}
          onClick={() => state.persona_id && void openTwin(state.persona_id)}
        >
          {mine.length
            ? `已确认 ${mine.length} 段，看看我的分身`
            : '确认之后就能看分身'}
        </Button>
      </Row>
    </>
  );
  // Opened again from inside the app it is an ordinary page; before any twin, the whole screen.
  if (!onSkip)
    return (
      <Page title={title} description={description}>
        {content}
      </Page>
    );
  return (
    <main className="entry-page min-h-dvh">
      <StageHeader variant="brand" />
      <section className="mx-auto max-w-2xl px-4 py-8">
        <Stack gap={6}>
          <Stack gap={2}>
            <Heading level={2} size="title">
              {title}
            </Heading>
            <Text tone="secondary">{description}</Text>
          </Stack>
          {content}
        </Stack>
      </section>
    </main>
  );
}
