import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { CircleCheck } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  Chip,
  ClipButton,
  Dialog,
  FileDrop,
  Heading,
  ListRow,
  Meter,
  Notice,
  Row,
  Stack,
  StepNumber,
  Text,
  TextLink,
  Textarea,
} from '../../components/ui';
import { api, ApiError } from '../../lib/api';
import { personaUrl } from '../../lib/persona';
import {
  isMedia,
  uploadForm,
  uploadMedia,
  type UploadProgress,
} from '../../lib/mediaUpload';
import { usePendingWork } from '../../lib/pendingWork';
import { useMobile } from '../../lib/useMobile';
import { useStatus } from '../../stores/status';
import type { IdentityData } from '../identity/useIdentity';
import type { Memory, SourcePage } from '../../pages/Memories';
import type { Processing } from '../memories/BuildProgress';

interface Speaker {
  id: string;
  seconds: number;
  suggested: boolean;
  quote?: string;
  samples: string[];
}
interface Claim {
  diarized: boolean;
  speakers: Speaker[];
}

// A new twin has only a few sources; the card looks at the latest of them.
const SOURCE_LIMIT = 20;
const POLL_MS = 2000;
const NOTES_LIMIT = 5000;
const ABOUT_LIMIT = 200;
// What a person tries first to see whether the twin sounds like them.
export const FIRST_QUESTIONS = [
  '我最近在忙什么？',
  '开会时我一般怎么拍板？',
  '这周的事你会怎么安排？',
];

const transcribing = (memory: Memory) =>
  ['queued', 'extracting', 'transcribing'].includes(memory.status);
const minutes = (seconds: number) =>
  seconds < 60
    ? `${Math.round(seconds)} 秒`
    : `${Math.round(seconds / 60)} 分钟`;

function Step({
  number,
  state,
  title,
  detail,
  children,
}: {
  number: number;
  state: 'done' | 'current' | 'pending';
  title: string;
  detail?: string;
  children?: ReactNode;
}) {
  return (
    <Row as="li" gap={3} align="start">
      <StepNumber size="sm" state={state}>
        {number}
      </StepNumber>
      <Stack gap={2} grow>
        <Stack gap={1}>
          <Text
            weight="semibold"
            tone={state === 'pending' ? 'tertiary' : 'primary'}
          >
            {title}
          </Text>
          {detail && (
            <Text
              size="sm"
              tone={state === 'pending' ? 'tertiary' : 'secondary'}
            >
              {detail}
            </Text>
          )}
        </Stack>
        {children}
      </Stack>
    </Row>
  );
}

/** The speakers of one recording, each with a clip and a line they said, and 是我 beside them. */
function SpeakerPick({
  source,
  onChosen,
}: {
  source: Memory;
  onChosen: () => void;
}) {
  const [claim, setClaim] = useState<Claim | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const base = `/api/persona/sources/${encodeURIComponent(source.source_id)}`;
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const value = await api<Claim>(`${base}/speakers`, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) setClaim(value);
      } catch (failure) {
        if (controller.signal.aborted) return;
        // Still being transcribed: the speakers come once it is done.
        if (failure instanceof ApiError && failure.status === 409)
          timer = setTimeout(() => void load(), POLL_MS);
        else
          setError(
            failure instanceof Error ? failure.message : '无法读取说话人',
          );
      }
    };
    void load();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [base]);
  const choose = async (speakers: string[]) => {
    setBusy(true);
    setError('');
    try {
      await api(`${base}/speaker`, { method: 'PUT', json: { speakers } });
      onChosen();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  if (!claim)
    return error ? (
      <Text role="alert" size="sm" tone="danger">
        {error}
      </Text>
    ) : (
      <Text role="status" size="sm" tone="secondary">
        正在读取说话人…
      </Text>
    );
  return (
    <Stack gap={2}>
      <Card as="div" variant="outline" padding="sm">
        <Stack as="ul" gap={0} aria-label={`「${source.title}」里的说话人`}>
          {claim.diarized ? (
            claim.speakers.map((speaker, i) => (
              <ListRow
                key={speaker.id}
                variant="divided"
                leading={
                  speaker.samples.length ? (
                    <ClipButton
                      src={personaUrl(speaker.samples[0])}
                      label={`播放说话人 ${i + 1} 的片段`}
                    />
                  ) : undefined
                }
                title={
                  <>
                    说话人 {i + 1}{' '}
                    <Text
                      as="span"
                      size="sm"
                      tone="secondary"
                      className="whitespace-nowrap"
                    >
                      · {minutes(speaker.seconds)}
                    </Text>
                    {speaker.suggested && (
                      <>
                        {' '}
                        <Badge tone="success">像你</Badge>
                      </>
                    )}
                  </>
                }
                meta={
                  speaker.quote ? (
                    <Text size="sm" tone="secondary" truncate>
                      “{speaker.quote}”
                    </Text>
                  ) : undefined
                }
                trailing={
                  <Button
                    variant="secondary"
                    disabled={busy}
                    aria-label={`说话人 ${i + 1} 是我`}
                    onClick={() => void choose([speaker.id])}
                  >
                    是我
                  </Button>
                }
              />
            ))
          ) : (
            <ListRow
              variant="plain"
              title="这段录音没有区分说话人"
              meta="整段都是你说的吗？"
              trailing={
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() =>
                    void choose(claim.speakers.map((speaker) => speaker.id))
                  }
                >
                  整段都是我
                </Button>
              }
            />
          )}
        </Stack>
      </Card>
      <Row>
        <TextLink size="sm" disabled={busy} onClick={() => void choose([])}>
          都不是我
        </TextLink>
      </Row>
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
    </Stack>
  );
}

/** The one-line introduction, written in a small card over the chat; the name was asked when the twin was made. */
function AboutDialog({
  identity,
  open,
  onOpenChange,
  onSaved,
}: {
  identity: IdentityData;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const mobile = useMobile();
  const [about, setAbout] = useState(identity.about);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (open) setAbout(identity.about);
  }, [open, identity.about]);
  const save = async () => {
    setBusy(true);
    setError('');
    try {
      await api('/api/identity', {
        method: 'PUT',
        json: { name: identity.name, about: about.trim() },
      });
      window.dispatchEvent(new Event('twin-identity-changed'));
      onSaved();
      onOpenChange(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="一句话介绍自己"
      body="在聊天页的名字下面显示，也帮它知道你是谁。"
      variant={mobile ? 'sheet' : 'center'}
      inPlace
    >
      <Stack
        as="form"
        gap={3}
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <Textarea
          aria-label="一句话介绍"
          rows={2}
          maxLength={ABOUT_LIMIT}
          value={about}
          placeholder="比如：产品负责人，管排期和发布"
          onChange={(event) => setAbout(event.target.value)}
        />
        <Row gap={2}>
          <Button type="submit" loading={busy}>
            保存
          </Button>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
        </Row>
        {error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
      </Stack>
    </Dialog>
  );
}

/**
 * 让{name}认识你: the setup of a new twin in its chat. Add a meeting recording, pick out which speaker is the person,
 * and the memories are built; once they are, the card turns into one line saying what it now knows, with a few
 * questions to try. Writing a few lines or adding a document stands in for the recording.
 */
export function SetupCard({
  name,
  identity,
  onIdentityChanged,
  onAsk,
  onReadyChange,
}: {
  name: string;
  identity: IdentityData;
  onIdentityChanged: () => void;
  onAsk: (question: string) => void;
  /** Whether the card is the one-line summary of what it remembers (rather than the steps). */
  onReadyChange?: (ready: boolean) => void;
}) {
  const [introducing, setIntroducing] = useState(false);
  const [page, setPage] = useState<SourcePage | null>(null);
  const [processing, setProcessing] = useState<Processing | null>(null);
  const [remembered, setRemembered] = useState<number | null>(null);
  const [upload, setUpload] = useState<UploadProgress | null>(null);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [writing, setWriting] = useState(false);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [poll, setPoll] = useState(0);
  const finished = useRef(false);
  const alive = useRef(true);
  const adding = useRef(false);
  usePendingWork(!!upload, '正在上传…');
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  const reload = useCallback(() => setPoll((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    void Promise.all([
      api<SourcePage>(
        `/api/persona/sources?limit=${SOURCE_LIMIT}&attention=true`,
        { signal: controller.signal },
      ),
      api<Processing>('/api/persona/processing', {
        signal: controller.signal,
      }),
    ])
      .then(([sources, build]) => {
        if (controller.signal.aborted) return;
        setLoadError('');
        setPage(sources);
        setProcessing(build);
        const working =
          sources.summary.busy > 0 ||
          build.state !== 'idle' ||
          sources.items.some(
            (item) => transcribing(item) || item.status === 'processing',
          );
        if (working) timer = setTimeout(reload, POLL_MS);
      })
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        setLoadError(failure instanceof Error ? failure.message : '加载失败');
        timer = setTimeout(reload, POLL_MS * 5);
      });
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [poll, reload]);

  const items = page?.items ?? [];
  const pick =
    page?.attention?.find((item) => item.status === 'needs_speaker') ??
    items.find((item) => item.status === 'needs_speaker');
  const pending = items.find(transcribing);
  const naming = items.find((item) => item.status === 'needs_name');
  const building =
    processing?.state !== 'idle' ||
    items.some((item) => item.status === 'processing');
  const ready =
    !!page &&
    page.summary.remembered > 0 &&
    !building &&
    !pick &&
    !pending &&
    !naming;
  // Done once: the twin is no longer new, and the card shows what it remembers.
  useEffect(() => {
    if (!ready || finished.current) return;
    finished.current = true;
    void api('/api/identity/onboarding-complete', { method: 'POST' }).catch(
      () => {},
    );
    void useStatus.getState().refresh();
    void api<{ total: number }>('/api/persona/items/summary')
      .then((summary) => {
        if (alive.current) setRemembered(summary.total);
      })
      .catch(() => {
        if (alive.current) setRemembered(0);
      });
  }, [ready]);

  const summarised = ready && remembered !== null;
  useEffect(() => onReadyChange?.(summarised), [onReadyChange, summarised]);

  const add = async (files: File[]) => {
    if (!files.length || adding.current) return;
    adding.current = true;
    setError('');
    setUpload({
      name: files.map((file) => file.name).join('、'),
      offset: 0,
      size: files.reduce((sum, file) => sum + file.size, 0),
      paused: false,
    });
    const controller = new AbortController();
    try {
      const documents = files.filter((file) => !isMedia(file));
      for (const file of files.filter(isMedia))
        await uploadMedia(file, controller.signal, (value) => {
          if (alive.current) setUpload(value);
        });
      if (documents.length) {
        const form = new FormData();
        documents.forEach((file) => form.append('files', file, file.name));
        const size = documents.reduce((sum, file) => sum + file.size, 0);
        const label = documents.map((file) => file.name).join('、');
        await uploadForm(
          '/api/persona/import',
          form,
          controller.signal,
          (percent) => {
            if (alive.current)
              setUpload({
                name: label,
                offset: (size * percent) / 100,
                size,
                paused: false,
              });
          },
        );
      }
    } catch (failure) {
      if (alive.current)
        setError(
          failure instanceof Error ? failure.message : '上传失败，请重试',
        );
    } finally {
      adding.current = false;
      if (alive.current) {
        setUpload(null);
        reload();
      }
    }
  };
  const save = async () => {
    const text = note.trim();
    if (!text) return;
    setSaving(true);
    setError('');
    try {
      await api('/api/persona/notes', { method: 'POST', json: { text } });
      if (!alive.current) return;
      setNote('');
      setWriting(false);
      reload();
    } catch (failure) {
      if (alive.current)
        setError(
          failure instanceof Error ? failure.message : '保存失败，请重试',
        );
    } finally {
      if (alive.current) setSaving(false);
    }
  };

  if (summarised) {
    const titles = items
      .filter((item) => item.remembered > 0)
      .slice(0, 2)
      .map((item) => `「${item.title}」`)
      .join('、');
    return (
      <Stack gap={5} align="center">
        <Notice
          tone="success"
          actions={
            <TextLink to="/profile?section=memories" size="sm">
              看看记了什么
            </TextLink>
          }
        >
          <Row gap={2}>
            <CircleCheck aria-hidden className="size-4 shrink-0 text-success" />
            <span>
              {name}已经记住 {remembered} 条关于你的事
              {titles && ` · 来自${titles}`}
            </span>
          </Row>
        </Notice>
        <Text tone="secondary" align="center">
          先试试这几个，看它像不像你：
        </Text>
        <Row gap={2} wrap justify="center">
          {FIRST_QUESTIONS.map((question) => (
            <Chip key={question} onClick={() => onAsk(question)}>
              {question}
            </Chip>
          ))}
        </Row>
      </Stack>
    );
  }

  const hasSource = (page?.summary.total ?? 0) > 0;
  const empty =
    !!page &&
    page.summary.remembered === 0 &&
    !building &&
    !pick &&
    !pending &&
    !naming;
  // Added something, but nothing about the person was found in it (or it failed): ask for another.
  const another = hasSource && empty;
  const first: 'done' | 'current' = hasSource && !another ? 'done' : 'current';
  const second: 'done' | 'current' | 'pending' =
    first === 'current'
      ? 'pending'
      : pick || pending || naming
        ? 'current'
        : 'done';
  const third: 'current' | 'pending' =
    second === 'done' ? 'current' : 'pending';
  const latest = items[0];
  const percent =
    pending?.status === 'transcribing' && pending.duration_s
      ? ((pending.transcribed_s ?? 0) / pending.duration_s) * 100
      : null;
  return (
    <Card
      as="section"
      variant="outline"
      padding="lg"
      aria-labelledby="setup-title"
    >
      <Stack gap={4}>
        <Stack gap={1}>
          <Heading id="setup-title" level={2} size="section">
            让{name}认识你
          </Heading>
          <Text size="sm" tone="secondary">
            加一段你参加过的会议录音，它会从你说的话里学你怎么想、怎么说。
          </Text>
        </Stack>
        <Stack as="ol" gap={4} aria-label="设置步骤">
          <Step
            number={1}
            state={first}
            title="加一段会议录音"
            detail={
              first === 'done' && latest
                ? `${latest.title}${latest.duration_s ? ` · ${minutes(latest.duration_s)}` : ''}${pending ? '' : ' · 已收到'}`
                : another
                  ? latest?.status === 'failed'
                    ? `「${latest.title}」没能处理，换一段试试。`
                    : `没从「${latest?.title ?? '这段资料'}」里找到你说的话，换一段试试。`
                  : undefined
            }
          >
            {first === 'current' && (
              <>
                {upload ? (
                  <Card as="div" variant="soft" padding="md" role="status">
                    <Meter
                      label={
                        upload.paused
                          ? `${upload.name}（网络断开，联网后继续）`
                          : `正在上传 ${upload.name}`
                      }
                      value={
                        upload.size ? (upload.offset / upload.size) * 100 : null
                      }
                    />
                  </Card>
                ) : writing ? (
                  <Stack gap={2}>
                    <Textarea
                      aria-label="写一段关于你的事"
                      rows={4}
                      maxLength={NOTES_LIMIT}
                      value={note}
                      placeholder="比如你在做什么、怎么做决定、平时怎么说话"
                      onChange={(event) => setNote(event.target.value)}
                    />
                    <Row gap={2}>
                      <Button
                        loading={saving}
                        disabled={!note.trim()}
                        onClick={() => void save()}
                      >
                        保存
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={saving}
                        onClick={() => setWriting(false)}
                      >
                        取消
                      </Button>
                    </Row>
                  </Stack>
                ) : (
                  <FileDrop
                    label="添加会议录音"
                    title="把会议录音或视频拖到这里"
                    actionLabel="选择文件"
                    inputLabel="选择会议录音"
                    hint="转写在后台进行，可以先去忙别的。"
                    onFiles={(files) => void add(files)}
                  />
                )}
                {!upload && !writing && (
                  <Row>
                    <TextLink size="sm" onClick={() => setWriting(true)}>
                      没有录音？写一段或上传文档
                    </TextLink>
                  </Row>
                )}
              </>
            )}
          </Step>
          <Step
            number={2}
            state={second}
            title={second === 'current' && pick ? '哪位是你？' : '勾出哪位是你'}
            detail={
              second === 'pending'
                ? '转写完成后在这里选。'
                : pick
                  ? '听一段，点「是我」。'
                  : pending
                    ? `正在转写「${pending.title}」，好了在这里选。`
                    : naming
                      ? `「${naming.title}」需要你认一下哪位是你。`
                      : undefined
            }
          >
            {second === 'current' && pick && (
              <SpeakerPick
                key={pick.source_id}
                source={pick}
                onChosen={reload}
              />
            )}
            {second === 'current' && !pick && pending && (
              <Meter label="转写进度" hideLabel size="sm" value={percent} />
            )}
            {second === 'current' && !pick && !pending && naming && (
              <Row>
                <TextLink to="/profile?section=memories" size="sm">
                  去档案里认一下
                </TextLink>
              </Row>
            )}
          </Step>
          <Step
            number={3}
            state={third}
            title="整理记忆"
            detail={
              third === 'current'
                ? '正在从你说的话里整理，好了会在这里告诉你。'
                : undefined
            }
          >
            {third === 'current' && (
              <Meter
                label="整理进度"
                hideLabel
                size="sm"
                value={
                  processing?.progress?.total
                    ? (processing.progress.done / processing.progress.total) *
                      100
                    : null
                }
              />
            )}
          </Step>
        </Stack>
        {(error || loadError) && (
          <Text role="alert" size="sm" tone="danger">
            {error || loadError}
          </Text>
        )}
        <Row gap={3} wrap>
          <Text as="span" size="sm" tone="secondary">
            还可以：
          </Text>
          <TextLink size="sm" onClick={() => setIntroducing(true)}>
            {identity.about ? '改一下介绍' : '一句话介绍自己'}
          </TextLink>
          <TextLink to="/profile?section=assets" size="sm">
            形象和声音
          </TextLink>
        </Row>
      </Stack>
      <AboutDialog
        identity={identity}
        open={introducing}
        onOpenChange={setIntroducing}
        onSaved={onIdentityChanged}
      />
    </Card>
  );
}
