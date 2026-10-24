import { useEffect, useState } from 'react';
import {
  Button,
  Dialog,
  Field,
  Input,
  ListRow,
  Row,
  Select,
  Skeleton,
  Stack,
  Text,
} from '../../components/ui';
import { api } from '../../lib/api';
import { sortByName } from '../../lib/names';
import { useTeam } from '../../stores/team';

/** The file extensions of a transcript an export gives (飞书妙记, 通义听悟, 腾讯会议 and the like): text, a Word file, a PDF. */
export const TRANSCRIPT_EXTENSIONS = [
  'txt',
  'md',
  'docx',
  'pdf',
  'srt',
  'vtt',
  'html',
  'htm',
];
export const TRANSCRIPT_ACCEPT = TRANSCRIPT_EXTENSIONS.map(
  (extension) => `.${extension}`,
).join(',');
export const isTranscript = (file: File) =>
  TRANSCRIPT_EXTENSIONS.includes(
    file.name.split('.').at(-1)?.toLowerCase() ?? '',
  );

interface Preview {
  title: string;
  date: string | null;
  speakers: {
    label: string;
    segments: number;
    sample: string;
    person: { id: string; name: string } | null;
  }[];
}
interface Imported {
  id: string;
  new: boolean;
  decided?: number;
  unsettled?: number;
}
/** The choice for a speaker: a member, nobody in the team, or (where no name settled it) not yet, the empty string.
 * A speaker whose name is a member's is that member until the importer changes it. */
const OUTSIDER = 'outsider';

const form = (file: File, payload?: unknown) => {
  const data = new FormData();
  data.append('file', file);
  if (payload !== undefined) data.append('payload', JSON.stringify(payload));
  return data;
};

/**
 * Bring a meeting transcript in as a recording that has no sound. The file is read first and shown: its title and
 * day, and each speaker with how much they say, the member the name is, or a line of what they said and the
 * choice of who they are. Speakers left unchosen wait to be settled like any other.
 */
export function ImportTranscript({
  file,
  onClose,
  onImported,
}: {
  /** The file being brought in; null while no dialog is open. */
  file: File | null;
  onClose: () => void;
  onImported: (result: Imported) => void;
}) {
  const people = useTeam((state) => state.people);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [title, setTitle] = useState('');
  const [date, setDate] = useState('');
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setPreview(null);
    setError('');
    setChoices({});
    if (!file) return;
    const controller = new AbortController();
    void api<Preview>('/api/library/transcripts/preview', {
      method: 'POST',
      form: form(file),
      signal: controller.signal,
    })
      .then((found) => {
        setPreview(found);
        setTitle(found.title);
        setDate(found.date ?? '');
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error ? failure.message : '无法读取这个文件',
          );
      });
    if (!useTeam.getState().people) void useTeam.getState().refreshPeople();
    return () => controller.abort();
  }, [file]);

  const members = sortByName(people ?? [], (person) => person.name);
  const send = async () => {
    if (!file || !preview) return;
    setBusy(true);
    setError('');
    const speakers: Record<string, { person_id?: string; outsider?: boolean }> =
      {};
    for (const [label, choice] of Object.entries(choices)) {
      if (choice === OUTSIDER) speakers[label] = { outsider: true };
      else if (choice) speakers[label] = { person_id: choice };
    }
    try {
      const result = await api<Imported>('/api/library/transcripts', {
        method: 'POST',
        form: form(file, { title, date: date || null, speakers }),
      });
      onImported(result);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '导入失败');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={file !== null}
      onOpenChange={(next) => !next && !busy && onClose()}
      title="导入转写稿"
    >
      <Stack gap={4}>
        <Text size="sm" tone="secondary" truncate>
          {file?.name}
        </Text>
        {!preview ? (
          error ? (
            <Text role="alert" tone="danger">
              {error}
            </Text>
          ) : (
            <Skeleton className="h-32" />
          )
        ) : (
          <>
            <Row gap={3} wrap align="end">
              <Field id="transcript-title" label="标题">
                <Input
                  id="transcript-title"
                  value={title}
                  maxLength={100}
                  disabled={busy}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </Field>
              <Field id="transcript-date" label="日期">
                <Input
                  id="transcript-date"
                  type="date"
                  value={date}
                  disabled={busy}
                  onChange={(event) => setDate(event.target.value)}
                />
              </Field>
            </Row>
            <Stack gap={0} as="ul" aria-label="说话人">
              {preview.speakers.map((speaker) => {
                // The name settled it, until the importer says the speaker is someone else (a client who shares
                // a member's name).
                const named = speaker.person !== null;
                const changing = speaker.label in choices;
                return (
                  <ListRow
                    key={speaker.label}
                    variant="divided"
                    title={
                      <Text as="span" weight="medium">
                        {speaker.label}
                      </Text>
                    }
                    meta={`${speaker.segments} 段${named && !changing ? '' : `：“${speaker.sample}”`}`}
                    trailing={
                      speaker.person && !changing ? (
                        <>
                          <Text as="span" size="sm" tone="success">
                            ✓ {speaker.person.name}
                          </Text>
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`改 ${speaker.label}`}
                            disabled={busy}
                            onClick={() =>
                              setChoices({
                                ...choices,
                                [speaker.label]: speaker.person?.id ?? '',
                              })
                            }
                          >
                            改
                          </Button>
                        </>
                      ) : (
                        <Select
                          aria-label={`${speaker.label} 是谁`}
                          value={choices[speaker.label] ?? ''}
                          disabled={busy}
                          onChange={(event) =>
                            setChoices({
                              ...choices,
                              [speaker.label]: event.target.value,
                            })
                          }
                        >
                          {!named && <option value="">选是谁</option>}
                          {(speaker.person &&
                          !members.some((m) => m.id === speaker.person?.id)
                            ? [...members, speaker.person]
                            : members
                          ).map((person) => (
                            <option key={person.id} value={person.id}>
                              {person.name}
                            </option>
                          ))}
                          <option value={OUTSIDER}>不是团队成员</option>
                        </Select>
                      )
                    }
                  />
                );
              })}
            </Stack>
            <Text size="sm" tone="tertiary">
              没有声音：不能试听，不留声纹
            </Text>
          </>
        )}
        {preview && error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
        <Row gap={2} justify="end">
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            取消
          </Button>
          <Button
            loading={busy}
            disabled={!preview || !title.trim()}
            onClick={() => void send()}
          >
            导入
          </Button>
        </Row>
      </Stack>
    </Dialog>
  );
}
