import { VolumeX } from 'lucide-react';
import {
  Badge,
  Button,
  ClipButton,
  Dialog,
  IconButton,
  ListRow,
  Row,
  Section,
  Stack,
  Text,
} from '../../components/ui';
import { useHeard } from '../../stores/listening';
import { clip } from './PersonVoice';

/** One of the two voice samples of a clash (``ClashSample``). */
export interface ClashSample {
  id: number;
  person_id: string;
  name: string;
  recording_id: string;
  filename: string;
  speaker_id: string;
  seconds: number;
  // More like the other person's sample than like the person's own other samples.
  unlike_own: boolean;
  // Its speaker is gone from the recording's transcript (transcribed again): it cannot be heard, and is as suspect.
  gone: boolean;
}

/** Voice samples of two people that sound nearly alike (``Team.voice_clashes``). */
export interface VoiceClash {
  score: number;
  // Both were heard in one recording: two people, so a sample is wrong.
  together: boolean;
  samples: [ClashSample, ClashSample];
}

/**
 * Beside the team page, for an administrator: two people whose voice samples sound nearly alike, each heard side by
 * side, to take them for one person, take away the sample given to the wrong one, or say both are right. Such samples
 * keep every voice like either of them waiting in the inbox. Closing it leaves the team page where it was.
 */
export function VoiceClashes({
  open,
  clashes,
  busy,
  onClose,
  onMerge,
  onRemove,
  onApart,
}: {
  open: boolean;
  clashes: VoiceClash[];
  busy: boolean;
  onClose: () => void;
  onMerge: (clash: VoiceClash) => void;
  onRemove: (sample: ClashSample) => void;
  onApart: (clash: VoiceClash) => void;
}) {
  const hear = useHeard();
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && onClose()}
      variant="side"
      title="核对声线"
    >
      <Stack gap={6}>
        {clashes.length === 0 && (
          <Text size="sm" tone="secondary">
            都核对完了
          </Text>
        )}
        {clashes.map((clash) => {
          const [a, b] = clash.samples;
          return (
            <Section
              key={`${a.id}-${b.id}`}
              level={3}
              title={`${a.name} 和 ${b.name}`}
              badge={
                clash.together && (
                  <Text as="span" size="sm" tone="secondary">
                    同场出现过
                  </Text>
                )
              }
              actions={
                <Row gap={1}>
                  {!clash.together && (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => onMerge(clash)}
                    >
                      合并
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onApart(clash)}
                  >
                    都没错
                  </Button>
                </Row>
              }
            >
              <Stack
                as="ul"
                gap={0}
                aria-label={`${a.name} 和 ${b.name}的声线`}
              >
                {clash.samples.map((sample) => (
                  <ListRow
                    key={sample.id}
                    variant="divided"
                    leading={
                      sample.gone ? (
                        <IconButton
                          label={`${sample.name}的这段声线听不到`}
                          shape="circle"
                          variant="secondary"
                          disabled
                        >
                          <VolumeX aria-hidden className="size-4" />
                        </IconButton>
                      ) : (
                        <ClipButton
                          size="md"
                          label={`听${sample.name}的声线（${sample.filename}）`}
                          src={hear(
                            clip(sample.recording_id, sample.speaker_id),
                          )}
                        />
                      )
                    }
                    title={
                      <Row gap={2}>
                        <Text truncate title={sample.filename}>
                          {sample.name}
                        </Text>
                        {sample.gone ? (
                          <Badge
                            tone="warning"
                            title="录音重新转写过，这段声线已对不上原来的说话人"
                          >
                            听不到
                          </Badge>
                        ) : (
                          sample.unlike_own && (
                            <Badge tone="warning">更像对方</Badge>
                          )
                        )}
                      </Row>
                    }
                    meta={sample.filename}
                    trailing={
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => onRemove(sample)}
                      >
                        移除这段
                      </Button>
                    }
                  />
                ))}
              </Stack>
            </Section>
          );
        })}
      </Stack>
    </Dialog>
  );
}
