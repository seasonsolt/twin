import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import {
  Button,
  Dialog,
  IconButton,
  ListRow,
  Row,
  Select,
  Skeleton,
  Stack,
  Text,
} from '../../components/ui';
import { api } from '../../lib/api';

interface Brief {
  id: string;
  filename: string;
  day: string | null;
}
/** Written minutes waiting to be put on a recording (``web.minutes.pending_view``). */
export interface PendingMinutes {
  id: string;
  filename: string;
  title: string;
  part: number;
  parts: number;
  day: string | null;
  // How the recording was found (当天唯一, 时刻相近, 内容最像), or why none was (没有日期, 当天没有录音, 分不出是哪场, 已有纪要).
  how: string;
  matched: boolean;
  proposal: Brief | null;
  choices: Brief[];
}

// The file a meeting's minutes came from, shown on hover: the row itself names the meeting.
const fileOf = (item: PendingMinutes) =>
  item.parts > 1 ? `${item.filename} · 第 ${item.part} 场` : item.filename;
const dayOf = (brief: Brief) => (brief.day ? `${brief.day} · ` : '');

/**
 * Put written minutes on the recordings they are of: those matched by their day fold into one line, opened to check
 * or leave one out; the others are each given a recording here. Nothing is put on a recording before 挂上, and what
 * is left keeps waiting, counted at the top of the library.
 */
export function MatchMinutes({
  open,
  skipped,
  onOpenChange,
  onAttached,
}: {
  open: boolean;
  // Minutes just brought in again, and not read twice.
  skipped: number;
  onOpenChange: (open: boolean) => void;
  onAttached: (attached: number) => void;
}) {
  const [items, setItems] = useState<PendingMinutes[] | null>(null);
  const [left, setLeft] = useState<Set<string>>(new Set());
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setItems(null);
    setLeft(new Set());
    setChosen({});
    setChecking(false);
    setError('');
    const controller = new AbortController();
    void api<{ items: PendingMinutes[] }>('/api/library/minutes/pending', {
      signal: controller.signal,
    })
      .then((found) => setItems(found.items))
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(failure instanceof Error ? failure.message : '读取失败');
      });
    return () => controller.abort();
  }, [open]);

  const matched = (items ?? []).filter((item) => item.matched);
  const choosing = (items ?? []).filter((item) => !item.matched);
  const kept = matched.filter((item) => !left.has(item.id));
  const picks = [
    ...kept.map((item) => ({
      id: item.id,
      recording_id: item.proposal?.id ?? '',
    })),
    ...choosing
      .filter((item) => chosen[item.id])
      .map((item) => ({ id: item.id, recording_id: chosen[item.id] })),
  ];

  const attach = async () => {
    setBusy(true);
    setError('');
    try {
      const done = await api<{ attached: number }>(
        '/api/library/minutes/attach',
        { method: 'POST', json: { items: picks } },
      );
      onAttached(done.attached);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '挂上失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={items ? `挂上纪要 · ${items.length} 份` : '挂上纪要'}
    >
      <Stack gap={4}>
        {!items ? (
          error ? (
            <Text role="alert" tone="danger">
              {error}
            </Text>
          ) : (
            <Skeleton className="h-24" />
          )
        ) : (
          <>
            {matched.length > 0 && (
              <Stack gap={1}>
                <Button
                  variant="secondary"
                  aria-expanded={checking}
                  onClick={() => setChecking(!checking)}
                >
                  已配上 {kept.length} 份 · {checking ? '收起' : '检查'}
                </Button>
                {checking && (
                  <Stack as="ul" gap={0} aria-label="已配上的纪要">
                    {matched.map((item) => (
                      <ListRow
                        key={item.id}
                        variant="divided"
                        title={
                          <Text
                            truncate
                            title={fileOf(item)}
                            tone={left.has(item.id) ? 'secondary' : undefined}
                          >
                            {item.title}
                          </Text>
                        }
                        meta={
                          item.proposal
                            ? `→ ${dayOf(item.proposal)}${item.proposal.filename} · ${item.how}`
                            : ''
                        }
                        trailing={
                          left.has(item.id) ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                const next = new Set(left);
                                next.delete(item.id);
                                setLeft(next);
                              }}
                            >
                              恢复
                            </Button>
                          ) : (
                            <IconButton
                              label={`不挂：${item.title}`}
                              onClick={() =>
                                setLeft(new Set(left).add(item.id))
                              }
                            >
                              <X aria-hidden className="size-4" />
                            </IconButton>
                          )
                        }
                      />
                    ))}
                  </Stack>
                )}
              </Stack>
            )}
            {choosing.length > 0 && (
              <Stack as="ul" gap={0} aria-label="要选录音的纪要">
                {choosing.map((item) => (
                  <ListRow
                    key={item.id}
                    variant="divided"
                    stackOnMobile
                    title={
                      <Text truncate title={fileOf(item)}>
                        {item.title}
                      </Text>
                    }
                    meta={item.how}
                    trailing={
                      <Select
                        aria-label={`${item.title}是哪场会`}
                        value={chosen[item.id] ?? ''}
                        onChange={(event) =>
                          setChosen({
                            ...chosen,
                            [item.id]: event.target.value,
                          })
                        }
                      >
                        <option value="">选录音</option>
                        {item.choices.map((choice) => (
                          <option key={choice.id} value={choice.id}>
                            {dayOf(choice)}
                            {choice.filename}
                          </option>
                        ))}
                      </Select>
                    }
                  />
                ))}
              </Stack>
            )}
            {items.length === 0 && (
              <Text tone="secondary">没有待配对的纪要。</Text>
            )}
            {skipped > 0 && (
              <Text size="sm" tone="secondary">
                重复 {skipped} 份已跳过
              </Text>
            )}
            {error && (
              <Text role="alert" tone="danger">
                {error}
              </Text>
            )}
            <Row gap={2} justify="end">
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                稍后再选
              </Button>
              <Button
                loading={busy}
                disabled={picks.length === 0}
                onClick={() => void attach()}
              >
                挂上 {picks.length} 份
              </Button>
            </Row>
          </>
        )}
      </Stack>
    </Dialog>
  );
}
