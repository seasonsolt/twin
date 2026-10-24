import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  Heading,
  ListRow,
  Radio,
  Row,
  Skeleton,
  Stack,
  Text,
  toast,
} from '../../components/ui';
import { api } from '../../lib/api';

interface Spoken {
  segments: number;
  chars: number;
  files: number;
  samples: string[];
}
export interface SpeakerName extends Spoken {
  name: string;
  likely: string | null;
}
export interface LabelledFile {
  source_id: string;
  title: string;
  first_date: string | null;
  speakers: (Spoken & { label: string })[];
}
export interface TranscriptRoster {
  pending: number;
  names: SpeakerName[];
  names_total: number;
  files: LabelledFile[];
  files_total: number;
  aliases: string[];
  fixed: string[];
  not_me: number;
}

const amount = (spoken: Spoken) =>
  `${spoken.segments} 段 · 约 ${spoken.chars} 字`;

function Samples({ samples }: { samples: string[] }) {
  return (
    <Stack as="ul" gap={1}>
      {samples.map((sample) => (
        <Text as="li" key={sample} size="sm" tone="secondary">
          “{sample}”
        </Text>
      ))}
    </Stack>
  );
}

/** One transcript with only labels such as 发言人1: which label is the person here, or none. */
function LabelChoice({
  file,
  busy,
  onAnswer,
}: {
  file: LabelledFile;
  busy: boolean;
  onAnswer: (labels: string[]) => void;
}) {
  const [choice, setChoice] = useState<string | null>(null);
  const group = `labels-${file.source_id}`;
  return (
    <Card as="article" variant="outline" padding="md">
      <Stack as="fieldset" gap={3}>
        <Text as="legend" weight="semibold">
          {file.title}
          {file.first_date && (
            <Text as="span" size="sm" tone="secondary">
              {' '}
              · {file.first_date}
            </Text>
          )}
        </Text>
        {file.speakers.map((speaker) => (
          <Stack key={speaker.label} gap={1}>
            <Radio
              name={group}
              value={speaker.label}
              checked={choice === speaker.label}
              disabled={busy}
              label={`${speaker.label} 是我`}
              onChange={() => setChoice(speaker.label)}
            >
              <Text as="span" size="sm" tone="secondary">
                {amount(speaker)}
              </Text>
            </Radio>
            <Samples samples={speaker.samples} />
          </Stack>
        ))}
        <Radio
          name={group}
          value=""
          checked={choice === ''}
          disabled={busy}
          label="都不是我"
          onChange={() => setChoice('')}
        />
        <Row>
          <Button
            size="sm"
            disabled={busy || choice === null}
            onClick={() => onAnswer(choice ? [choice] : [])}
          >
            确认这份
          </Button>
        </Row>
      </Stack>
    </Card>
  );
}

/**
 * Which speaker of the waiting text transcripts is the person: names once for every file, then the files that only
 * label their speakers (发言人1), one by one or all at once as other people's words.
 */
export function TranscriptClaim({ onChanged }: { onChanged?: () => void }) {
  const [roster, setRoster] = useState<TranscriptRoster | null>(null);
  const [mine, setMine] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const mutation = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const value = await api<TranscriptRoster>(
        '/api/persona/transcripts/speakers',
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setRoster(value);
      setError('');
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(failure instanceof Error ? failure.message : '无法读取说话人');
    }
  }, []);
  useEffect(() => {
    void load();
    return () => {
      request.current?.abort();
      mutation.current?.abort();
    };
  }, [load]);

  const send = async (
    path: string,
    json: unknown,
    message: string,
    method = 'POST',
  ) => {
    if (mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true);
    setError('');
    try {
      const value = await api<TranscriptRoster>(path, {
        method,
        json,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setRoster(value);
      setMine([]);
      toast(message, 'success');
      onChanged?.();
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(
          failure instanceof Error ? failure.message : '保存失败，请重试',
        );
    } finally {
      mutation.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  if (!roster)
    return error ? (
      <Text role="alert" tone="danger">
        {error}{' '}
        <Button variant="ghost" onClick={() => void load()}>
          重试
        </Button>
      </Text>
    ) : (
      <Skeleton className="h-40" />
    );
  const others = roster.names
    .map((row) => row.name)
    .filter((name) => !mine.includes(name));
  return (
    <Stack gap={6} aria-busy={busy}>
      {error && (
        <Text role="alert" tone="danger">
          {error}
        </Text>
      )}
      {roster.pending === 0 && (
        <EmptyState
          title="都确认好了"
          body="以后上传的文字记录会按你确认过的名字自动识别。"
        />
      )}
      {roster.names.length > 0 && (
        <Stack as="section" gap={3} aria-label="说话人名单">
          <Heading
            level={3}
            title="勾选你自己，可以多选；没勾的名字会记为别人，以后不再询问"
          >
            哪些名字是你
          </Heading>
          <Stack as="ul" gap={2}>
            {roster.names.map((row) => (
              <ListRow
                key={row.name}
                variant="outline"
                title={
                  <Checkbox
                    value={row.name}
                    checked={mine.includes(row.name)}
                    disabled={busy}
                    label={row.name}
                    onChange={(event) =>
                      setMine(
                        event.target.checked
                          ? [...mine, row.name]
                          : mine.filter((name) => name !== row.name),
                      )
                    }
                  >
                    {row.likely && (
                      <Badge tone="success" title={row.likely}>
                        可能是你
                      </Badge>
                    )}
                  </Checkbox>
                }
                meta={`${amount(row)} · 出现在 ${row.files} 份文件里`}
              >
                <Samples samples={row.samples} />
              </ListRow>
            ))}
          </Stack>
          {roster.names_total > roster.names.length && (
            <Text size="sm" tone="secondary">
              还有 {roster.names_total - roster.names.length}{' '}
              个说得更少的名字，确认后会接着列出。
            </Text>
          )}
          <Row wrap>
            <Button
              loading={busy}
              onClick={() =>
                void send(
                  '/api/persona/transcripts/names',
                  { mine, others },
                  mine.length
                    ? '已确认，正在重新整理记忆'
                    : '已记下，这些名字都不是你',
                )
              }
            >
              {mine.length
                ? `确认：${mine.length} 个是我，其余 ${others.length} 个不是`
                : `这 ${others.length} 个名字都不是我`}
            </Button>
          </Row>
        </Stack>
      )}
      {roster.files.length > 0 && (
        <Stack as="section" gap={3} aria-label="没有名字的文字记录">
          <Heading level={3}>只有“发言人”标签的记录</Heading>
          <Text size="sm" tone="secondary">
            同一个标签在不同文件里可能是不同的人，所以要逐份选择；也可以全部只当作别人说的话保留。
          </Text>
          <Row wrap>
            <Button
              variant="secondary"
              loading={busy}
              onClick={() =>
                void send(
                  '/api/persona/transcripts/not-mine',
                  { source_ids: roster.files.map((file) => file.source_id) },
                  '已保留为他人上下文',
                )
              }
            >
              这 {roster.files.length} 份都不是我
            </Button>
          </Row>
          {roster.files_total > roster.files.length && (
            <Text size="sm" tone="secondary">
              共 {roster.files_total} 份，先列出 {roster.files.length} 份。
            </Text>
          )}
          {roster.files.map((file) => (
            <LabelChoice
              key={file.source_id}
              file={file}
              busy={busy}
              onAnswer={(labels) =>
                void send(
                  `/api/persona/transcripts/${encodeURIComponent(file.source_id)}/speakers`,
                  { speakers: labels },
                  labels.length
                    ? '已确认，正在重新整理记忆'
                    : '已保留为他人上下文',
                  'PUT',
                )
              }
            />
          ))}
        </Stack>
      )}
    </Stack>
  );
}
