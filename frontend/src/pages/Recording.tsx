import { useCallback, useEffect, useId, useState } from 'react';
import { useParams } from 'react-router';
import {
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
  type Tone,
} from '../components/ui';
import { StageHeader } from '../components/layout/StageHeader';
import { api, ApiError } from '../lib/api';
import { withBase } from '../lib/base';
import type { Recording as RecordingRow } from './Library';

export interface Candidate {
  person_id: string;
  name: string;
  score: number;
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
  candidates: Candidate[];
  near: boolean;
  samples: number;
}
export type Gender = '' | 'male' | 'female';
export interface Person {
  id: string;
  name: string;
  persona_id: string | null;
  speakers: number;
  seconds: number;
  samples: number;
  updating: boolean;
  // Made from a voice that matched nobody, not named yet.
  auto: boolean;
  gender: Gender;
  recording_id: string | null;
}
interface Detail extends Omit<RecordingRow, 'speakers' | 'segments'> {
  transcript_id: string | null;
  revision: number;
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

const decisionLabel: Record<Speaker['decision'], [string, Tone]> = {
  none: ['待确认', 'warning'],
  confirmed: ['已确认', 'success'],
  unknown: ['不在名单里', 'neutral'],
  mixed: ['几个人混在一起', 'neutral'],
};
const clock = (seconds: number) => {
  const s = Math.floor(seconds);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};
const span = (seconds: number) =>
  seconds < 60
    ? `${Math.round(seconds)} 秒`
    : `${Math.round(seconds / 60)} 分钟`;

function SpeakerCard({
  recordingId,
  speaker,
  people,
  lines,
  busy,
  onDecide,
}: {
  recordingId: string;
  speaker: Speaker;
  people: Person[];
  lines: string[];
  busy: boolean;
  onDecide: (decision: Decision) => void;
}) {
  const id = useId();
  // Never pre-selected: a match is only a hint until the owner picks the person.
  const [person, setPerson] = useState('');
  const [name, setName] = useState('');
  const [sample, setSample] = useState(false);
  const owner = people.find((p) => p.id === speaker.person_id);
  const [label, tone] = decisionLabel[speaker.decision];
  const choices = people.filter((p) => !speaker.rejected.includes(p.id));
  const confirm = () =>
    onDecide(
      person === 'new'
        ? { action: 'confirm', new_person: name.trim(), sample }
        : { action: 'confirm', person_id: person, sample },
    );
  return (
    <Card as="li" padding="md" className="space-y-3">
      <Row gap={3} wrap>
        <Heading level={3} size="item">
          {speaker.id}
        </Heading>
        <Text as="span" size="sm" tone="secondary">
          说了 {span(speaker.seconds)}
        </Text>
        <Badge tone={tone}>
          {speaker.decision === 'confirmed' && owner
            ? `${label}：${owner.name}`
            : label}
        </Badge>
        {speaker.auto && <Badge tone="info">按声音自动认出</Badge>}
        {speaker.sample && <Badge tone="info">声纹样本</Badge>}
        {speaker.auto && owner && (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => onDecide({ action: 'reject', person_id: owner.id })}
          >
            不是{owner.name}
          </Button>
        )}
      </Row>
      <div className="grid gap-2 sm:grid-cols-3">
        {Array.from({ length: speaker.samples }, (_, i) => (
          <audio
            key={i}
            controls
            preload="none"
            aria-label={`${speaker.id} 试听 ${i + 1}`}
            className="h-11 w-full"
            src={withBase(
              `/api/library/recordings/${encodeURIComponent(recordingId)}/speakers/${encodeURIComponent(speaker.id)}/samples/${i}`,
            )}
          />
        ))}
      </div>
      {lines.length > 0 && (
        <Stack as="ul" gap={1}>
          {lines.map((line, i) => (
            <Text as="li" key={i} size="sm" tone="secondary">
              {line}
            </Text>
          ))}
        </Stack>
      )}
      {speaker.candidates.length > 0 && (
        <Row gap={2} wrap>
          <Text as="span" size="sm">
            声音像：
          </Text>
          {speaker.candidates.map((c) => (
            <span key={c.person_id} className="inline-flex items-center gap-1">
              <Badge tone={speaker.near ? 'warning' : 'info'}>
                {c.name} {Math.round(c.score * 100)}%
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() =>
                  onDecide({ action: 'reject', person_id: c.person_id })
                }
              >
                不是{c.name}
              </Button>
            </span>
          ))}
          {speaker.near && (
            <Text as="span" size="sm" tone="secondary">
              两位很接近，请仔细听
            </Text>
          )}
        </Row>
      )}
      <Row gap={3} align="end" wrap>
        <Field id={`${id}-who`} label="这是谁">
          <Select
            id={`${id}-who`}
            value={person}
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
            onChange={(event) => setName(event.target.value)}
          />
        )}
        <Checkbox
          label="这段声音清楚，用作声纹样本"
          checked={sample}
          onChange={(event) => setSample(event.target.checked)}
        />
        <Button
          disabled={busy || !person || (person === 'new' && !name.trim())}
          onClick={confirm}
        >
          确认
        </Button>
      </Row>
      <Row gap={2} wrap>
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          onClick={() => onDecide({ action: 'unknown' })}
        >
          不在名单里
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          onClick={() => onDecide({ action: 'mixed' })}
        >
          几个人混在一起
        </Button>
        {(speaker.decision !== 'none' || speaker.rejected.length > 0) && (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => onDecide({ action: 'clear' })}
          >
            撤销
          </Button>
        )}
      </Row>
    </Card>
  );
}

export function Recording() {
  const { recordingId = '' } = useParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const base = `/api/library/recordings/${encodeURIComponent(recordingId)}`;
  const load = useCallback(async () => {
    try {
      const [value, folks] = await Promise.all([
        api<Detail>(base),
        api<{ items: Person[] }>('/api/library/people'),
      ]);
      setDetail(value);
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

  const names = new Map(people.map((p) => [p.id, p.name]));
  const who = (speakerId: string) => {
    const speaker = detail?.speakers.find((s) => s.id === speakerId);
    return speaker?.decision === 'confirmed' && speaker.person_id
      ? (names.get(speaker.person_id) ?? speakerId)
      : speakerId;
  };
  return (
    <div className="library-page">
      <StageHeader
        variant="brand"
        intro={
          <p className="stage-caption">
            听一听每位说话人，确认是谁。只有确认过的发言才会进入这个人的分身。
          </p>
        }
      />
      <Page
        title={detail?.filename ?? '录音'}
        aside={
          <TextLink to="/library" size="sm">
            返回录音库
          </TextLink>
        }
      >
        {error && (
          <Text role="alert" tone="danger">
            {error}
          </Text>
        )}
        {!detail ? (
          <Skeleton className="h-32" />
        ) : detail.status !== 'ready' ? (
          <Text role="status" tone="secondary">
            这段录音还没转写完。
          </Text>
        ) : (
          <>
            <Stack as="ul" gap={3} aria-label="说话人">
              {detail.speakers.map((speaker) => (
                <SpeakerCard
                  // A new revision starts every card from nothing chosen.
                  key={`${speaker.id}-${detail.revision}`}
                  recordingId={detail.id}
                  speaker={speaker}
                  people={people}
                  busy={busy}
                  lines={detail.segments
                    .filter((s) => s.speaker === speaker.id && s.text)
                    .slice(0, 3)
                    .map((s) => `[${clock(s.start)}] ${s.text}`)}
                  onDecide={(decision) => void decide(speaker, decision)}
                />
              ))}
            </Stack>
            <Disclosure summary={`转写稿（${detail.segments.length} 段）`}>
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
          </>
        )}
      </Page>
    </div>
  );
}
