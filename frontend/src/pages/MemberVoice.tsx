import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { CircleHelp, Mic, Square } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  ClipButton,
  Heading,
  IconButton,
  ListRow,
  Notice,
  PlainButton,
  Row,
  Skeleton,
  Stack,
  Text,
  TextLink,
  Tooltip,
  toast,
} from '../components/ui';
import { useRecorder } from '../features/assets/useRecorder';
import { api, ApiError } from '../lib/api';
import { withBase } from '../lib/base';
import { usePersonas } from '../stores/personas';
import { useWelcome } from '../stores/welcome';

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
}

// Said on hover: what happens to the recording.
const PRIVACY = '录音只用来在同事传的会议里找像你的声音，比对完就删掉。';

const day = (date: string | null) => {
  const found = date?.match(/^\d{4}-(\d{2})-(\d{2})/u);
  return found ? `${Number(found[1])} 月 ${Number(found[2])} 日` : null;
};

/**
 * 员工 1b: someone signed in through the company login, with no twin made for them, finds their voice in the
 * meetings colleagues uploaded. They read a sentence aloud, hear one sentence of each voice like theirs and say
 * "是我" or "不是"; the twin made from what they confirm is theirs. ``onSkip`` leads on to an empty twin; without
 * it (heard again by someone who has a twin) the page only adds voices to the twin, and when there is nothing to
 * hear leaves for where they came from.
 */
export function MemberVoice({ onSkip }: { onSkip?: () => void }) {
  const [state, setState] = useState<VoiceState | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const recorder = useRecorder();
  const navigate = useNavigate();
  // Nothing to hear: on the way in the empty twin is next; heard again, they go back to where they were and are told.
  const leave = useCallback(() => {
    if (onSkip) {
      onSkip();
      return;
    }
    toast('会议里还没有可听的声音');
    useWelcome.getState().finishVoice();
  }, [onSkip]);

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
        else leave();
      })
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 404) leave();
        else setError(failure instanceof Error ? failure.message : '加载失败');
      });
    return () => controller.abort();
  }, [leave]);

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
      // The voice step is over: on the way in, the twin now waiting for them is the next step, shown without a
      // navigation; heard again, it leads to the twin.
      useWelcome.getState().finishVoice();
      if (!onSkip) navigate('/profile');
    } finally {
      setBusy('');
    }
  };

  const mine = state?.items.filter((item) => item.state === 'mine') ?? [];
  const recording =
    recorder.state === 'recording' || recorder.state === 'requesting';
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
          <Row gap={2}>
            <Text weight="semibold">先读一句话，十秒左右</Text>
            <Tooltip label={PRIVACY}>
              <IconButton label={`说明：${PRIVACY}`} shape="circle">
                <CircleHelp className="size-4" aria-hidden />
              </IconButton>
            </Tooltip>
          </Row>
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
            <PlainButton onClick={onSkip}>先建空分身</PlainButton>
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
          {onSkip && <Button onClick={onSkip}>先建空分身</Button>}
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
                  ? '拿不准'
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
                      aria-label={`撤回：${item.quote}`}
                      disabled={!!busy}
                      onClick={() => void takeBack(item)}
                    >
                      撤回
                    </PlainButton>
                  </>
                ) : (
                  <>
                    <Button
                      aria-label={`是我：${item.quote}`}
                      variant={item.unsure ? 'secondary' : 'primary'}
                      loading={busy === item.id}
                      disabled={!!busy}
                      onClick={() => void answer(item, 'me')}
                    >
                      是我
                    </Button>
                    <Button
                      aria-label={`不是：${item.quote}`}
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
      {error && (
        <Text size="sm" tone="danger" role="alert">
          {error}
        </Text>
      )}
      <Row justify="between" wrap gap={3}>
        {mine.length > 0 ? (
          <Badge tone="success">已确认 {mine.length} 段</Badge>
        ) : onSkip ? (
          <Text size="sm" tone="secondary">
            都不是你？
            <TextLink size="sm" onClick={onSkip}>
              先建空分身
            </TextLink>
          </Text>
        ) : (
          <span />
        )}
        {state.persona_id && (
          <Button
            size="lg"
            disabled={!!busy}
            loading={busy === 'open'}
            onClick={() => state.persona_id && void openTwin(state.persona_id)}
          >
            看看分身
          </Button>
        )}
      </Row>
    </>
  );
  return (
    <Stack gap={5}>
      <Heading level={1} size="display">
        会议里可能有你
      </Heading>
      {content}
    </Stack>
  );
}
