import { useCallback, useEffect, useId, useRef, useState } from 'react';
import {
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router';
import {
  AudioPlayer,
  AvatarFrame,
  Chip,
  DecisionBar,
  ListRow,
  Meter,
  Notice,
  RouteButton,
  Section,
  Toolbar,
  VoiceChoice,
  Badge,
  Button,
  Card,
  Checkbox,
  Disclosure,
  Field,
  Heading,
  Input,
  Page,
  Row,
  Select,
  Skeleton,
  Stack,
  Text,
  TextLink,
} from '../components/ui';
import { api, ApiError } from '../lib/api';
import { sortByName } from '../lib/names';
import { withBase } from '../lib/base';
import { heard, useListening } from '../stores/listening';
import type { Recording as RecordingRow } from './Library';
import type { Processing } from '../features/memories/BuildProgress';

export interface Candidate {
  person_id: string;
  name: string;
  score: number;
  // Close enough to be the answer by default.
  sure?: boolean;
  // Already speaking in this recording, and this alike: one person diarization split in two.
  split?: boolean;
  // The meeting calls the speaker by this person's name.
  called?: boolean;
}
export interface Speaker {
  id: string;
  seconds: number;
  decision: 'none' | 'confirmed' | 'unknown' | 'mixed';
  person_id: string | null;
  rejected: string[];
  sample: boolean;
  // Taken by voice alone, without the owner.
  auto: boolean;
  // The person it was given to said it is not them; it waits for whoever decides about the recording.
  disputed?: boolean;
  candidates: Candidate[];
  near: boolean;
  samples: number;
  // What the meeting calls the speaker, and what was said that names them.
  called?: string | null;
  quote?: string;
}
export type Gender = '' | 'male' | 'female';
export interface Person {
  id: string;
  name: string;
  persona_id: string | null;
  speakers: number;
  seconds: number;
  // How much longer they would have to be heard to have what a twin learns from.
  lacking?: number;
  samples: number;
  updating: boolean;
  // Where the update is while ``updating``; null when the twin has not started on it in this server yet. Once a
  // build stopped without completing, ``last_error`` says why, and ``retry_at`` when it is tried again by itself.
  build?: (Processing & { retry_at?: string | null }) | null;
  // They found themselves here by voice: their twin is their own, not the library's to open.
  self_claimed?: boolean;
  // Whether the viewer may name them, make their twin or delete them (they uploaded a recording they are in).
  can_manage?: boolean;
  // A colleague keeps a twin of them, which the viewer cannot open.
  twin_elsewhere?: boolean;
  // People who may be the same person (shown to administrators).
  similar?: string[];
  // Made from a voice that matched nobody, not named yet.
  auto: boolean;
  gender: Gender;
  recording_id: string | null;
  speaker_id: string | null;
  // Speakers given to them by voice alone, to spot-check (``Team.checks``).
  checks?: number;
}
interface Detail extends Omit<RecordingRow, 'speakers' | 'segments'> {
  transcript_id: string | null;
  revision: number;
  // The viewer was identified in it and only reads it; ``mine`` are the speakers given to them.
  can_edit?: boolean;
  mine?: string[];
  // Whether it has a denoised copy to listen to (``media.denoise``); its clips play that unless the original is asked.
  denoised?: boolean;
  speakers: Speaker[];
  segments: { start: number; end: number; text: string; speaker: string }[];
}
type Action = 'confirm' | 'unknown' | 'mixed' | 'reject' | 'clear';
interface Decision {
  action: Action;
  person_id?: string;
  new_person?: string;
  sample?: boolean;
}

const clock = (seconds: number) => {
  const s = Math.floor(seconds);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};
const span = (seconds: number) =>
  seconds < 60
    ? `${Math.round(seconds)} 秒`
    : `${Math.round(seconds / 60)} 分钟`;

/** media.claim.SAMPLE_SECONDS: how long one moment to hear a speaker at lasts. */
const SAMPLE_SECONDS = 10;

/** Mirrors media.claim.sample_windows so chip times and text describe the existing sample URLs. */
export function sampleWindows(segments: Detail['segments'], speakerId: string) {
  const others = segments.filter((s) => s.speaker !== speakerId);
  let runs: [number, number][] = [];
  for (const segment of segments
    .filter((s) => s.speaker === speakerId)
    .sort((a, b) => a.start - b.start)) {
    const last = runs.at(-1);
    if (
      last &&
      segment.start - last[1] < 0.6 &&
      !others.some((s) => s.start < segment.start && s.end > last[1])
    )
      last[1] = Math.max(last[1], segment.end);
    else runs.push([segment.start, segment.end]);
  }
  for (const other of others) {
    if (other.end > other.start)
      runs = runs
        .flatMap(
          ([start, end]) =>
            [
              [start, Math.min(end, other.start)],
              [Math.max(start, other.end), end],
            ] as [number, number][],
        )
        .filter(([start, end]) => end > start);
  }
  // The start of each of the three longest runs, so the moments differ; whole further windows of them if fewer.
  const longest = runs.sort((a, b) => b[1] - b[0] - (a[1] - a[0])).slice(0, 3);
  const windows: [number, number][] = longest.map(([start, end]) => [
    start,
    Math.min(start + SAMPLE_SECONDS, end),
  ]);
  for (const [start, end] of longest)
    for (let i = 1; i < Math.floor((end - start) / SAMPLE_SECONDS); i += 1)
      windows.push([
        start + i * SAMPLE_SECONDS,
        start + (i + 1) * SAMPLE_SECONDS,
      ]);
  return windows.slice(0, 3);
}

function SpeakerCard({
  recordingId,
  speaker,
  people,
  segments,
  busy,
  remaining,
  now,
  elsewhere = 0,
  denoised,
  onDecide,
}: {
  recordingId: string;
  speaker: Speaker;
  people: Person[];
  segments: Detail['segments'];
  busy: boolean;
  remaining: number;
  /** Whom the speaker is given to already, when a team task opens one settled automatically. */
  now?: string;
  /** Other recordings the same voice waits in, when a team task opens it: deciding here settles this one alone. */
  elsewhere?: number;
  /** The recording has a denoised copy, so the original can be chosen instead. */
  denoised: boolean;
  onDecide: (decision: Decision) => void;
}) {
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  // Voice matches remain suggestions until the owner chooses one.
  const [person, setPerson] = useState('');
  const [name, setName] = useState('');
  const [sample, setSample] = useState(false);
  const [clip, setClip] = useState(0);
  const { original, setOriginal } = useListening();
  const choices = sortByName(
    people.filter((p) => !speaker.rejected.includes(p.id)),
    (p) => p.name,
  );
  const candidates = speaker.candidates.filter(
    (c) => !speaker.rejected.includes(c.person_id),
  );
  // A name the meeting calls the speaker that nobody in the team has yet.
  const newName =
    speaker.called && !candidates.some((c) => c.called) ? speaker.called : '';
  const selectedName =
    person === 'new' ? name.trim() : choices.find((p) => p.id === person)?.name;
  const windows = sampleWindows(segments, speaker.id);
  const window = windows[clip];
  const transcript = window
    ? segments
        .filter(
          (s) =>
            s.speaker === speaker.id &&
            s.start < window[1] &&
            s.end > window[0],
        )
        .map((s) => s.text)
        .join(' ')
    : '';
  return (
    <Card padding="none" aria-labelledby={`${id}-heading`}>
      <Card as="div" variant="plain" padding="roomy" className="space-y-5">
        <Toolbar>
          <Row gap={3} wrap>
            <Heading level={3} id={`${id}-heading`} ref={heading} tabIndex={-1}>
              {speaker.id} 是谁？
            </Heading>
            <Text size="sm" tone="secondary">
              这段录音里说了 {span(speaker.seconds)}
            </Text>
          </Row>
          <Text size="sm" tone="tertiary">
            还剩 {remaining} 位
          </Text>
        </Toolbar>
        {now && (
          <Text size="sm" tone="secondary">
            现在算作{now}，听一下是谁。
          </Text>
        )}
        {elsewhere > 0 && (
          <Text size="sm" tone="secondary">
            这个声音还出现在另外 {elsewhere}{' '}
            段录音里。这里只确认这一段，其余的回到待处理一起确认。
          </Text>
        )}
        {speaker.disputed && (
          <Text size="sm" tone="warning">
            原来标成的人说这不是 TA，请重新听一下是谁。
          </Text>
        )}
        <Card variant="soft" padding="md" className="space-y-3">
          {speaker.samples > 0 ? (
            <>
              <AudioPlayer
                aria-label={`${speaker.id} 试听`}
                src={heard(
                  withBase(
                    `/api/library/recordings/${encodeURIComponent(recordingId)}/speakers/${encodeURIComponent(speaker.id)}/samples/${clip}`,
                  ),
                  original && denoised,
                )}
              />
              <Row gap={2} wrap>
                <Text as="span" size="sm" tone="tertiary">
                  这段录音里的 {speaker.samples} 个片段
                </Text>
                {Array.from({ length: speaker.samples }, (_, i) => (
                  <Chip key={i} pressed={clip === i} onClick={() => setClip(i)}>
                    片段 {i + 1}
                    {windows[i] ? ` · ${clock(windows[i][0])}` : ''}
                  </Chip>
                ))}
                {denoised && (
                  <Chip
                    pressed={original}
                    onClick={() => setOriginal(!original)}
                    title="默认播放降噪后的声音；打开后播放原始录音"
                  >
                    原声
                  </Chip>
                )}
              </Row>
              {transcript && (
                <Text size="sm" tone="secondary">
                  {transcript}
                </Text>
              )}
            </>
          ) : (
            <Text size="sm" tone="secondary">
              这位说话人没有可试听的片段，可参考完整转写稿。
            </Text>
          )}
        </Card>
        <Stack gap={3}>
          <Text weight="medium">
            {candidates.some((c) => c.called) || newName
              ? '会上叫到了名字，听一下再选'
              : candidates.length > 1
                ? '声音像这两位，选一个'
                : candidates.length
                  ? '声音像这位，选一个人'
                  : '没认出这是谁，选一个人或写新名字'}
          </Text>
          {candidates.length > 1 &&
            Number.isFinite(candidates[0].score) &&
            Number.isFinite(candidates[1].score) &&
            Math.abs(candidates[0].score - candidates[1].score) <= 0.25 && (
              <Text size="sm" tone="warning">
                两位很接近，多听一个片段再选。
              </Text>
            )}
          {speaker.called && speaker.quote && (
            <Text size="sm" tone="secondary">
              会上被叫作{speaker.called}：「{speaker.quote}」
            </Text>
          )}
          {(candidates.length > 0 || newName) && (
            <Row gap={3} wrap>
              {newName && (
                <VoiceChoice
                  selected={person === 'new' && name.trim() === newName}
                  disabled={busy}
                  onClick={() => {
                    setPerson('new');
                    setName(newName);
                  }}
                >
                  <AvatarFrame size="md">{Array.from(newName)[0]}</AvatarFrame>
                  <Stack gap={0}>
                    <Text as="span" weight="medium" tone="inherit">
                      {newName}
                    </Text>
                    <Text as="span" size="sm" tone="inherit">
                      会上这样叫，新加到团队
                    </Text>
                  </Stack>
                </VoiceChoice>
              )}
              {candidates.map((c) => (
                <VoiceChoice
                  key={c.person_id}
                  selected={person === c.person_id}
                  disabled={busy}
                  onClick={() => setPerson(c.person_id)}
                >
                  <AvatarFrame size="md">{Array.from(c.name)[0]}</AvatarFrame>
                  <Stack gap={0}>
                    <Text as="span" weight="medium" tone="inherit">
                      {c.name}
                    </Text>
                    <Text as="span" size="sm" tone="inherit">
                      {c.split
                        ? `这段里已有${c.name}，可能被拆成了两位`
                        : c.called
                          ? `会上被叫作${c.name}`
                          : `声音像 ${Math.round(c.score * 100)}%`}
                    </Text>
                  </Stack>
                </VoiceChoice>
              ))}
            </Row>
          )}
        </Stack>
        <Row gap={3} wrap align="end">
          <Field id={`${id}-who`} label="都不是：">
            <Select
              id={`${id}-who`}
              aria-label="这是谁"
              value={person}
              disabled={busy}
              onChange={(event) => setPerson(event.target.value)}
            >
              <option value="">请选择</option>
              {choices.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
              <option value="new">新的人…</option>
            </Select>
          </Field>
          {person === 'new' && (
            <Input
              aria-label="新人物的名字"
              placeholder="名字"
              maxLength={40}
              value={name}
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
            />
          )}
        </Row>
      </Card>
      <DecisionBar
        secondary={
          <>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => onDecide({ action: 'unknown' })}
            >
              不在名单里
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => onDecide({ action: 'mixed' })}
            >
              几个人混在一起
            </Button>
          </>
        }
      >
        <Button
          disabled={busy || !selectedName}
          onClick={() =>
            onDecide(
              person === 'new'
                ? { action: 'confirm', new_person: name.trim(), sample }
                : { action: 'confirm', person_id: person, sample },
            )
          }
        >
          {selectedName ? `确认是${selectedName}` : '先选一个人'}
        </Button>
        <Checkbox
          label="声音清楚，用作这个人的声纹样本"
          checked={sample}
          disabled={busy}
          onChange={(event) => setSample(event.target.checked)}
        />
      </DecisionBar>
    </Card>
  );
}

export function Recording() {
  const { recordingId = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  // The speaker to settle first: one just reopened, or the one a link points at (in the address, so a recording
  // opened in a new tab opens on the same voice).
  const [params] = useSearchParams();
  const linked: string | null =
    params.get('speaker') ?? location.state?.speaker ?? null;
  const [reopened, setReopened] = useState<string | null>(linked);
  // They said the only speaker given to them is not them: the recording is no longer theirs to see.
  const [left, setLeft] = useState(false);
  const base = `/api/library/recordings/${encodeURIComponent(recordingId)}`;
  const load = useCallback(async () => {
    try {
      const [value, folks] = await Promise.all([
        api<Detail>(base),
        api<{ items: Person[] }>('/api/library/people'),
      ]);
      // Someone who only reads it is not shown whom the voices resemble.
      setDetail({
        ...value,
        speakers: value.speakers.map((s) => ({
          ...s,
          candidates: s.candidates ?? [],
          rejected: s.rejected ?? [],
          near: s.near ?? false,
        })),
      });
      setPeople(folks.items);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法加载录音');
    }
  }, [base]);
  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (speaker: Speaker, decision: Decision) => {
    if (!detail) return;
    setBusy(true);
    setError('');
    try {
      await api(`${base}/speakers/${encodeURIComponent(speaker.id)}`, {
        method: 'PUT',
        json: {
          transcript_id: detail.transcript_id,
          revision: detail.revision,
          ...decision,
        },
      });
      setReopened(decision.action === 'clear' ? speaker.id : null);
      if (
        location.state?.teamTask &&
        ['confirm', 'unknown', 'mixed'].includes(decision.action)
      ) {
        void navigate('/team', {
          state: { resolvedTeamTask: location.state.teamTask },
        });
        return;
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败');
      if (!(failure instanceof ApiError && failure.status === 409)) {
        setBusy(false);
        return;
      }
    }
    // A saved decision moves the revision on; a refused one means someone else did.
    await load();
    setBusy(false);
  };

  const notMe = async (speaker: Speaker) => {
    setBusy(true);
    setError('');
    try {
      await api(`${base}/speakers/${encodeURIComponent(speaker.id)}/not-me`, {
        method: 'POST',
      });
      try {
        await api(base);
        await load();
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 404)
          setLeft(true);
        else throw failure;
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败');
    }
    setBusy(false);
  };

  const names = new Map(people.map((p) => [p.id, p.name]));
  const who = (speakerId: string) => {
    const speaker = detail?.speakers.find((s) => s.id === speakerId);
    return speaker?.decision === 'confirmed' && speaker.person_id
      ? (names.get(speaker.person_id) ?? speakerId)
      : speakerId;
  };
  const transcript = detail && (
    <Disclosure summary={`完整转写稿（${detail.segments.length} 段）`}>
      <Stack as="ol" gap={1}>
        {detail.segments.map((s, i) => (
          <Text as="li" key={i} size="sm">
            <Text as="span" size="inherit" tone="secondary">
              [{clock(s.start)}] {who(s.speaker)}：
            </Text>
            {s.text}
          </Text>
        ))}
      </Stack>
    </Disclosure>
  );
  const undecided = detail?.speakers.filter((s) => s.decision === 'none') ?? [];
  const settled = (detail?.speakers.length ?? 0) - undecided.length;
  // A link may point at a speaker already given to someone automatically (an unnamed voice): it is heard and
  // settled here like any other, not left in the list below while another speaker's card asks instead.
  const pointed = detail?.speakers.find(
    (s) =>
      s.id === reopened &&
      (s.decision === 'none' ||
        (s.id === linked && s.decision === 'confirmed')),
  );
  const current = pointed ?? undecided[0];
  const remaining = undecided.filter((s) => s.id !== current?.id);
  const decided =
    detail?.speakers.filter(
      (s) => s.decision !== 'none' && s.id !== current?.id,
    ) ?? [];
  return (
    <Page
      stackHeaderOnMobile
      breadcrumb={
        <TextLink to="/library" size="sm">
          录音库
        </TextLink>
      }
      title={detail?.filename ?? '录音'}
      titleSize="display"
      description={
        detail
          ? [
              Number.isNaN(Date.parse(detail.created_at))
                ? ''
                : new Date(detail.created_at).toLocaleDateString('zh-CN', {
                    month: 'long',
                    day: 'numeric',
                  }),
              detail.duration_s == null ? '' : span(detail.duration_s),
              `${detail.speakers.length} 位说话人`,
            ]
              .filter(Boolean)
              .join(' · ')
          : undefined
      }
      actions={
        detail && (
          <Stack gap={2}>
            <Text size="sm" tone="secondary">
              已确认 {settled} / {detail.speakers.length} 位
            </Text>
            <Meter
              label="说话人确认进度"
              size="sm"
              hideLabel
              value={settled}
              max={detail.speakers.length}
            />
          </Stack>
        )
      }
    >
      <Text size="xs" tone="tertiary">
        只有确认过的发言才会进入这个人的分身。
      </Text>
      {error && (
        <Text role="alert" tone="danger">
          {error}
        </Text>
      )}
      {left ? (
        <Notice
          tone="success"
          title="已经告诉上传的同事"
          actions={<RouteButton to="/library">回录音库</RouteButton>}
        >
          这段发言不再算你的，你的分身也不会用它。上传的同事会重新确认是谁。
        </Notice>
      ) : !detail ? (
        <Skeleton className="h-32" />
      ) : detail.status !== 'ready' ? (
        <Text role="status" tone="secondary">
          这段录音还没转写完。
        </Text>
      ) : detail.can_edit === false ? (
        <>
          <Text size="sm" tone="secondary">
            这段录音由上传的同事整理，你参加了这场会，可以查看。标成你的发言如果不是你，点「不是我」。
          </Text>
          <Section title="说话人">
            <Card>
              <Stack as="ul" gap={0}>
                {detail.speakers.map((s) => {
                  const mine = detail.mine?.includes(s.id) ?? false;
                  return (
                    <ListRow
                      key={s.id}
                      variant="divided"
                      leading={
                        <AvatarFrame size="sm">
                          {Array.from(names.get(s.person_id ?? '') ?? s.id)[0]}
                        </AvatarFrame>
                      }
                      title={
                        s.decision === 'confirmed'
                          ? (names.get(s.person_id ?? '') ?? s.id)
                          : s.decision === 'mixed'
                            ? '几个人混在一起'
                            : s.decision === 'unknown'
                              ? '不在名单里'
                              : '还没确认'
                      }
                      meta={`${s.id} · 说了 ${span(s.seconds)}`}
                      trailing={
                        mine ? (
                          <>
                            <Badge tone="success">你</Badge>
                            <Button
                              variant="secondary"
                              size="sm"
                              aria-label={`${s.id} 不是我`}
                              disabled={busy}
                              onClick={() => void notMe(s)}
                            >
                              不是我
                            </Button>
                          </>
                        ) : undefined
                      }
                    />
                  );
                })}
              </Stack>
            </Card>
          </Section>
          {transcript}
        </>
      ) : (
        <>
          {current ? (
            <SpeakerCard
              key={`${current.id}-${detail.revision}`}
              recordingId={detail.id}
              speaker={current}
              people={people}
              segments={detail.segments}
              busy={busy}
              remaining={remaining.length + 1}
              now={
                current.decision === 'confirmed'
                  ? names.get(current.person_id ?? '')
                  : undefined
              }
              elsewhere={
                current.id === linked
                  ? Math.max(0, (location.state?.voiceRecordings ?? 1) - 1)
                  : 0
              }
              denoised={detail.denoised === true}
              onDecide={(decision) => void decide(current, decision)}
            />
          ) : (
            <Notice
              tone="success"
              title="这段录音的说话人都确认好了"
              actions={<RouteButton to="/team">回团队处理下一项</RouteButton>}
            >
              相关的人会在后台重新整理记忆。
            </Notice>
          )}
          {remaining.length > 0 && (
            <Section title="接下来">
              <Stack as="ul" gap={2}>
                {remaining.map((s) => (
                  <ListRow
                    key={s.id}
                    variant="dashed"
                    title={
                      <Text size="sm" tone="secondary">
                        {s.id} · 说了 {span(s.seconds)} ·{' '}
                        {s.candidates.length ? '有候选人' : '没认出来'}
                      </Text>
                    }
                  />
                ))}
              </Stack>
            </Section>
          )}
          {decided.length > 0 && (
            <Section title={`已确认 ${decided.length} 位`}>
              <Card>
                <Stack as="ul" gap={0}>
                  {decided.map((s) => (
                    <ListRow
                      key={s.id}
                      variant="divided"
                      leading={
                        <AvatarFrame size="sm">
                          {Array.from(names.get(s.person_id ?? '') ?? s.id)[0]}
                        </AvatarFrame>
                      }
                      title={
                        s.decision === 'confirmed'
                          ? (names.get(s.person_id ?? '') ?? s.id)
                          : s.decision === 'mixed'
                            ? '几个人混在一起'
                            : '不在名单里'
                      }
                      meta={`${s.id} · 说了 ${span(s.seconds)}`}
                      trailing={
                        <>
                          <Badge>
                            {s.decision !== 'confirmed'
                              ? '不进任何分身'
                              : s.auto
                                ? '按声音自动认出'
                                : '你确认的'}
                          </Badge>
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`改 ${s.id}`}
                            disabled={busy}
                            onClick={() => void decide(s, { action: 'clear' })}
                          >
                            改
                          </Button>
                        </>
                      }
                    />
                  ))}
                </Stack>
              </Card>
            </Section>
          )}
          {transcript}
        </>
      )}
    </Page>
  );
}
