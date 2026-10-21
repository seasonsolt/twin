import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  ClipButton,
  Dialog,
  Disclosure,
  ListRow,
  Notice,
  Row,
  Stack,
  Text,
} from '../../components/ui';
import { api } from '../../lib/api';
import { withBase } from '../../lib/base';

/** What the owner decided about a stretch: not the person, someone else's, or theirs indeed. */
export type UnitFix = 'exclude' | 'move' | 'keep';

/** One stretch of a confirmed speaker, heard again (``media.review``). */
export interface ReviewUnit {
  index: number;
  segments: number[];
  start: number;
  end: number;
  seconds: number;
  text: string;
  // 'other': another known person sounds clearly closer; 'stranger': nobody known comes near.
  verdict: '' | 'other' | 'stranger';
  own: number | null;
  other: number | null;
  like: string | null;
  like_name: string | null;
  fix: UnitFix | null;
  to_person: string | null;
  to_name: string | null;
  // Left out by the review itself, not by the owner: it still waits for their word.
  auto?: boolean;
}

/** A confirmed speaker some of whose speech does not sound like the person (``Reviews.suspects``). */
export interface SuspectSpeaker {
  recording_id: string;
  filename: string;
  transcript_id: string;
  revision: number;
  speaker_id: string;
  person_id: string;
  name: string;
  status: 'waiting' | 'failed' | 'no_samples' | 'ready';
  error?: string;
  seconds: number;
  suspect_seconds: number;
  open_seconds: number;
  suspects: number;
  open: number;
  share: number;
  likely: string | null;
  likely_name: string | null;
  units: ReviewUnit[];
}

const SAMPLES = 3;

const clock = (seconds: number) => {
  const whole = Math.max(0, Math.floor(seconds));
  const pad = (n: number) => String(n).padStart(2, '0');
  const hours = Math.floor(whole / 3600);
  return `${hours ? `${hours}:${pad(Math.floor((whole % 3600) / 60))}` : Math.floor(whole / 60)}:${pad(whole % 60)}`;
};
const span = (seconds: number) =>
  seconds < 60
    ? `${Math.round(seconds)} 秒`
    : `${Math.round(seconds / 60)} 分钟`;

/**
 * A confirmed speaker heard again stretch by stretch, beside the team page: one decision for all the suspect
 * stretches on top, a few of the longest to hear, and every stretch folded below to decide one by one. Closing it
 * leaves the team page where it was.
 */
export function MixedSpeaker({
  suspect,
  onClose,
  onChanged,
}: {
  suspect: SuspectSpeaker | null;
  onClose: () => void;
  onChanged: () => Promise<void> | void;
}) {
  const [detail, setDetail] = useState<SuspectSpeaker | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const base = suspect
    ? `/api/library/recordings/${encodeURIComponent(suspect.recording_id)}/speakers/${encodeURIComponent(suspect.speaker_id)}/units`
    : '';
  const load = useCallback(async () => {
    if (!base) return;
    try {
      setDetail(await api<SuspectSpeaker>(base));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法加载片段');
    }
  }, [base]);
  useEffect(() => {
    setDetail(null);
    setError('');
    void load();
  }, [load]);

  const decide = async (
    units: ReviewUnit[],
    action: UnitFix | 'clear',
    personId?: string | null,
  ) => {
    if (!detail || !units.length) return;
    setBusy(true);
    setError('');
    try {
      await api(base, {
        method: 'PUT',
        json: {
          transcript_id: detail.transcript_id,
          revision: detail.revision,
          units: units.map((u) => u.index),
          action,
          ...(personId ? { person_id: personId } : {}),
        },
      });
      await load();
      await onChanged();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败');
      await load();
    }
    setBusy(false);
  };

  const name = detail?.name ?? suspect?.name ?? '';
  const units = detail?.units ?? [];
  const suspects = units.filter((u) => u.verdict);
  const open = suspects.filter((u) => !u.fix || u.auto);
  const likely = detail?.likely;
  const likelyName = detail?.likely_name;
  const toLikely = open.filter(
    (u) => u.verdict === 'other' && u.like === likely,
  );
  const rest = units.filter((u) => !u.verdict);
  // A few of the longest suspect stretches are enough to tell whose voice it is; the rest stay folded.
  const samples = [...suspects]
    .sort((a, b) => b.seconds - a.seconds || a.start - b.start)
    .slice(0, SAMPLES);
  const others = suspects.filter((u) => !samples.includes(u));

  const row = (unit: ReviewUnit) => {
    const heard =
      unit.verdict === 'other'
        ? `更像${unit.like_name}`
        : unit.verdict === 'stranger'
          ? '不像团队里的任何人'
          : `像${name}`;
    const decided =
      unit.fix === 'exclude' && unit.auto
        ? `${heard}，已自动排除`
        : unit.fix === 'exclude'
          ? `已排除：不算${name}的话`
          : unit.fix === 'move'
            ? `已改给${unit.to_name ?? '别人'}`
            : unit.fix === 'keep'
              ? `已确认是${name}`
              : null;
    return (
      <ListRow
        key={unit.index}
        variant="divided"
        leading={
          <ClipButton
            size="md"
            label={`听 ${clock(unit.start)} 这段`}
            src={withBase(`${base}/${unit.index}/clip`)}
          />
        }
        title={`${clock(unit.start)} · ${Math.round(unit.seconds)} 秒 · ${decided ?? heard}`}
        meta={unit.text || '（没有识别出文字）'}
      >
        <Row gap={2} wrap>
          {unit.fix && !unit.auto ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => void decide([unit], 'clear')}
            >
              撤销
            </Button>
          ) : (
            <>
              {unit.like && unit.verdict === 'other' && (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={() => void decide([unit], 'move', unit.like)}
                >
                  是{unit.like_name}
                </Button>
              )}
              <Button
                variant={unit.verdict ? 'secondary' : 'ghost'}
                size="sm"
                disabled={busy}
                onClick={() => void decide([unit], 'exclude')}
              >
                {unit.auto ? `确实不是${name}` : `不是${name}`}
              </Button>
              {unit.verdict && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => void decide([unit], 'keep')}
                >
                  是{name}
                </Button>
              )}
            </>
          )}
        </Row>
      </ListRow>
    );
  };

  return (
    <Dialog
      open={!!suspect}
      onOpenChange={(next) => !next && onClose()}
      variant="side"
      title={suspect ? `${suspect.filename} · ${suspect.speaker_id}` : ''}
      body={
        detail
          ? `确认给了${name}，但 ${Math.round(detail.share * 100)}% 听起来不像 TA（${suspects.length} 段，${span(detail.suspect_seconds)}），可能整个认错了人。这些片段已自动排除，不进${name}的分身。听下面几段，决定是谁。`
          : undefined
      }
    >
      <Stack gap={4}>
        {error && <Notice tone="danger">{error}</Notice>}
        {!detail && !error && (
          <Text size="sm" tone="secondary">
            正在加载…
          </Text>
        )}
        {detail && open.length > 0 && (
          <Row gap={2} wrap>
            {likely && toLikely.length > 0 && (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => void decide(toLikely, 'move', likely)}
              >
                都改给{likelyName}
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() => void decide(open, 'exclude')}
            >
              都不是{name}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => void decide(open, 'keep')}
            >
              其实都是{name}
            </Button>
          </Row>
        )}
        {samples.length > 0 && (
          <Stack as="ul" gap={0} aria-label="代表片段">
            {samples.map(row)}
          </Stack>
        )}
        {others.length > 0 && (
          <Disclosure
            summary={`其余 ${others.length} 段疑似片段`}
            variant="plain"
          >
            <Stack as="ul" gap={0}>
              {others.map(row)}
            </Stack>
          </Disclosure>
        )}
        {rest.length > 0 && (
          <Disclosure
            summary={`其余 ${rest.length} 段听起来是${name}`}
            variant="plain"
          >
            <Stack as="ul" gap={0}>
              {rest.map(row)}
            </Stack>
          </Disclosure>
        )}
      </Stack>
    </Dialog>
  );
}
