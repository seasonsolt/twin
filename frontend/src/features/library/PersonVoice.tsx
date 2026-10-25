import { useCallback, useEffect, useState } from 'react';
import {
  ActionMenu,
  Button,
  ClipButton,
  Dialog,
  ListRow,
  Notice,
  Section,
  Stack,
  Text,
  toast,
  useConfirm,
} from '../../components/ui';
import { api } from '../../lib/api';
import { withBase } from '../../lib/base';
import { useHeard } from '../../stores/listening';
import type { Person } from '../../pages/Recording';

/** A speaker given to the person by voice alone (``Team.checks``), least sure first. */
export interface Check {
  recording_id: string;
  filename: string;
  transcript_id: string;
  revision: number;
  speaker_id: string;
  seconds: number;
  // How sure voice alone was: its lead over the runner-up; none when the review gave it.
  tier: string | null;
  score: number | null;
  lead: number | null;
}

/** One of the person's voice samples (``Team.samples``). */
export interface VoiceSample {
  id: number;
  recording_id: string;
  filename: string;
  transcript_id: string;
  speaker_id: string;
  seconds: number;
  source: 'speaker' | 'voice' | 'new' | null;
  created_at: string;
  // Speakers it gave the person by voice alone that still stand, and those the owner gave otherwise.
  claims: number;
  corrected: number;
}

interface PersonVoiceState {
  samples: VoiceSample[];
  checks: Check[];
}

// The least sure are heard first; the rest wait behind "see more".
const CHECKS_PER_PAGE = 10;

const span = (seconds: number) =>
  seconds < 60
    ? `${Math.round(seconds)} 秒`
    : `${Math.round(seconds / 60)} 分钟`;
/** A speaker's clip, as heard beside their voice sample. */
export const clip = (recordingId: string, speakerId: string) =>
  withBase(
    `/api/library/recordings/${encodeURIComponent(recordingId)}/speakers/${encodeURIComponent(speakerId)}/samples/0`,
  );
/** How sure voice alone was, in words: the lead over whoever came second. */
const sureness = (check: Check) =>
  check.lead === null
    ? '复核时改给了 TA'
    : check.lead < 0.15
      ? '把握不大'
      : check.lead < 0.3
        ? '比较有把握'
        : '很有把握';
const SOURCES: Record<NonNullable<VoiceSample['source']>, string> = {
  speaker: '打标时留下',
  voice: '整组声音确认时留下',
  new: '新声音自动留下',
};

/**
 * Beside the team page, what a person is recognised by and what voice alone gave them: their speakers taken
 * without asking, the least sure first, to say "not them" where it went wrong; and their voice samples, to take
 * away one that draws other people's voices. Closing it leaves the team page where it was.
 */
export function PersonVoice({
  person,
  onClose,
  onChanged,
}: {
  person: Person | null;
  onClose: () => void;
  onChanged: () => Promise<void> | void;
}) {
  const [state, setState] = useState<PersonVoiceState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [shown, setShown] = useState(CHECKS_PER_PAGE);
  const confirm = useConfirm();
  const hear = useHeard();
  const base = person
    ? `/api/library/people/${encodeURIComponent(person.id)}`
    : '';
  const load = useCallback(async () => {
    if (!base) return;
    try {
      setState(await api<PersonVoiceState>(`${base}/voice`));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法加载');
    }
  }, [base]);
  useEffect(() => {
    setState(null);
    setError('');
    setShown(CHECKS_PER_PAGE);
    void load();
  }, [load]);

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError('');
    try {
      await work();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败');
    }
    await load();
    await onChanged();
    setBusy(false);
  };
  const decide = (
    check: Check,
    action: 'confirm' | 'reject' | 'unknown' | 'mixed',
  ) =>
    act(() =>
      api(
        `/api/library/recordings/${encodeURIComponent(check.recording_id)}/speakers/${encodeURIComponent(check.speaker_id)}`,
        {
          method: 'PUT',
          json: {
            transcript_id: check.transcript_id,
            revision: check.revision,
            action,
            ...(action === 'confirm' || action === 'reject'
              ? { person_id: person?.id }
              : {}),
          },
        },
      ),
    );
  const remove = async (sample: VoiceSample) => {
    if (
      !(await confirm({
        title: '移除这段声线？',
        body:
          sample.claims > 0
            ? `靠它认出的 ${sample.claims} 段发言会退回待处理，等你确认`
            : '以后不再用它认人',
        confirmLabel: '移除',
        tone: 'danger',
      }))
    )
      return;
    await act(async () => {
      const { returned } = await api<{ returned: number }>(
        `${base}/samples/${sample.id}`,
        { method: 'DELETE' },
      );
      toast(
        returned ? `已移除，${returned} 段发言退回待处理` : '已移除',
        'success',
      );
    });
  };

  const name = person?.name ?? '';
  const checks = state?.checks ?? [];
  const samples = state?.samples ?? [];
  return (
    <Dialog
      open={!!person}
      onOpenChange={(next) => !next && onClose()}
      variant="side"
      title={`${name}的声音`}
    >
      <Stack gap={6}>
        {error && <Notice tone="danger">{error}</Notice>}
        {!state && !error && (
          <Text size="sm" tone="secondary">
            正在加载…
          </Text>
        )}
        {state && (
          <Section
            level={3}
            title="抽查"
            badge={
              <Text as="span" size="sm" tone="secondary">
                {checks.length}
              </Text>
            }
            description={
              checks.length
                ? `按声音自动认给${name}的发言，最没把握的在前。听一听，不对就改。`
                : `没有按声音自动认给${name}的发言。`
            }
          >
            {checks.length > 0 && (
              <Stack as="ul" gap={0} aria-label="可抽查的发言">
                {checks.slice(0, shown).map((check) => (
                  <ListRow
                    key={`${check.recording_id}/${check.speaker_id}`}
                    variant="divided"
                    leading={
                      <ClipButton
                        size="md"
                        label={`听这段（${check.filename}）`}
                        src={hear(clip(check.recording_id, check.speaker_id))}
                      />
                    }
                    title={
                      <Text truncate title={check.filename}>
                        {check.filename}
                      </Text>
                    }
                    meta={`${span(check.seconds)} · ${sureness(check)}`}
                    trailing={
                      <>
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={busy}
                          onClick={() => void decide(check, 'confirm')}
                        >
                          是{name}
                        </Button>
                        <ActionMenu
                          label={`不是${name}：${check.filename}`}
                          items={[
                            {
                              label: `不是${name}，放回待处理`,
                              disabled: busy,
                              onSelect: () => void decide(check, 'reject'),
                            },
                            {
                              label: '不认识',
                              disabled: busy,
                              onSelect: () => void decide(check, 'unknown'),
                            },
                            {
                              label: '几个人混在一起',
                              disabled: busy,
                              onSelect: () => void decide(check, 'mixed'),
                            },
                          ]}
                        />
                      </>
                    }
                  />
                ))}
              </Stack>
            )}
            {checks.length > shown && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShown((n) => n + CHECKS_PER_PAGE)}
              >
                再看 {Math.min(CHECKS_PER_PAGE, checks.length - shown)} 段（还有{' '}
                {checks.length - shown} 段）
              </Button>
            )}
          </Section>
        )}
        {state && (
          <Section
            level={3}
            title="声线"
            badge={
              <Text as="span" size="sm" tone="secondary">
                {samples.length}
              </Text>
            }
            description={
              samples.length
                ? `用来认出${name}的声音样本。哪段其实是别人，就移除它。`
                : `${name}还没有声音样本，确认 TA 的说话人时会留下。`
            }
          >
            {samples.length > 0 && (
              <Stack as="ul" gap={0} aria-label="声线">
                {samples.map((sample) => (
                  <ListRow
                    key={sample.id}
                    variant="divided"
                    leading={
                      <ClipButton
                        size="md"
                        label={`听这段声线（${sample.filename}）`}
                        src={hear(clip(sample.recording_id, sample.speaker_id))}
                      />
                    }
                    title={
                      <Text truncate title={sample.filename}>
                        {sample.filename}
                      </Text>
                    }
                    meta={[
                      sample.source ? SOURCES[sample.source] : '',
                      `认出 ${sample.claims} 段`,
                      sample.corrected ? `被改过 ${sample.corrected} 次` : '',
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                    trailing={
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => void remove(sample)}
                      >
                        移除
                      </Button>
                    }
                  />
                ))}
              </Stack>
            )}
          </Section>
        )}
      </Stack>
    </Dialog>
  );
}
