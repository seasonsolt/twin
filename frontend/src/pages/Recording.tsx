import { useCallback, useEffect, useId, useState } from 'react';
import { Link, useParams } from 'react-router';
import { Badge, Button, Input, Skeleton, type Tone } from '../components/ui';
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
  candidates: Candidate[];
  near: boolean;
  samples: number;
}
export interface Person {
  id: string;
  name: string;
  persona_id: string | null;
  speakers: number;
  seconds: number;
  samples: number;
  updating: boolean;
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
const selectClass =
  'min-h-11 rounded-lg border-2 border-primary bg-surface px-3 text-md text-primary';
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
    <li className="space-y-3 rounded-xl bg-surface p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-semibold">{speaker.id}</h3>
        <span className="text-sm text-secondary">
          说了 {span(speaker.seconds)}
        </span>
        <Badge tone={tone}>
          {speaker.decision === 'confirmed' && owner
            ? `${label}：${owner.name}`
            : label}
        </Badge>
        {speaker.sample && <Badge tone="info">声纹样本</Badge>}
      </div>
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
        <ul className="space-y-1 text-sm text-secondary">
          {lines.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}
      {speaker.candidates.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>声音像：</span>
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
            <span className="text-secondary">两位很接近，请仔细听</span>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm" htmlFor={`${id}-who`}>
          <span className="text-secondary">这是谁</span>
          <select
            id={`${id}-who`}
            className={selectClass}
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
          </select>
        </label>
        {person === 'new' && (
          <Input
            aria-label="新人物的名字"
            placeholder="名字"
            maxLength={40}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        )}
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={sample}
            onChange={(event) => setSample(event.target.checked)}
          />
          这段声音清楚，用作声纹样本
        </label>
        <Button
          disabled={busy || !person || (person === 'new' && !name.trim())}
          onClick={confirm}
        >
          确认
        </Button>
      </div>
      <div className="flex flex-wrap gap-2">
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
      </div>
    </li>
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
      <div className="page-content space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="min-w-0 truncate text-2xl font-semibold">
            {detail?.filename ?? '录音'}
          </h2>
          <Link to="/library" className="text-sm text-accent underline">
            返回录音库
          </Link>
        </header>
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
        {!detail ? (
          <Skeleton className="h-32" />
        ) : detail.status !== 'ready' ? (
          <p role="status" className="text-secondary">
            这段录音还没转写完。
          </p>
        ) : (
          <>
            <ul aria-label="说话人" className="space-y-3">
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
            </ul>
            <details className="rounded-xl bg-surface p-4">
              <summary className="min-h-11 cursor-pointer content-center">
                转写稿（{detail.segments.length} 段）
              </summary>
              <ol className="mt-3 space-y-1 text-sm">
                {detail.segments.map((s, i) => (
                  <li key={i}>
                    <span className="text-secondary">
                      [{clock(s.start)}] {who(s.speaker)}：
                    </span>
                    {s.text}
                  </li>
                ))}
              </ol>
            </details>
          </>
        )}
      </div>
    </div>
  );
}
