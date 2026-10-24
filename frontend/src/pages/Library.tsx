import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActionMenu,
  AvatarStack,
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  EmptyState,
  FileDropSurface,
  FileInput,
  Input,
  ListRow,
  Meter,
  Notice,
  Page,
  RouteButton,
  Row,
  Skeleton,
  Stack,
  Tabs,
  Text,
  TextLink,
  Toolbar,
  toast,
  useConfirm,
  type Tone,
} from '../components/ui';
import { api } from '../lib/api';
import { useMobile } from '../lib/useMobile';
import { useTeam } from '../stores/team';
import { usePolling } from '../lib/usePolling';
import {
  ImportTranscript,
  TRANSCRIPT_ACCEPT,
  isTranscript,
} from '../features/library/ImportTranscript';
import { UploadList } from '../features/library/UploadList';
import { useUploads } from '../features/library/useUploads';

export interface Recording {
  id: string;
  filename: string;
  size: number;
  // A transcript brought in as text has no sound: it cannot be played, and it keeps no voiceprints.
  kind: 'audio' | 'video' | 'transcript';
  status: 'queued' | 'transcribing' | 'ready' | 'failed';
  error: string;
  duration_s: number | null;
  transcribed_s: number;
  speakers: number;
  segments: number;
  created_at: string;
  // When it was recorded (an imported transcript: the day the importer gave), when the file says; else null.
  creation_time?: string | null;
  // Who the speakers were recognised as, and how many still wait for the owner.
  people: string[];
  unsettled: number;
  // Whether the model proofread the transcript: done, gave nothing, still to come, or not due (no one identified).
  proofread?: Proofread;
  // The one being proofread right now (one per library at a time).
  proofreading?: boolean;
  // Whether the viewer decides about it (they uploaded it, or administer); otherwise they were in it and may read it.
  can_edit?: boolean;
  // The transcript before it was last transcribed again, to go back to.
  previous?: string | null;
}
/** Recordings the current transcription service would transcribe anew (``Library.recollectable``). */
interface Recollection {
  service: string | null;
  recordings: {
    id: string;
    filename: string;
    asr: string | null;
    asked: string | null;
  }[];
}
export type Proofread = 'done' | 'failed' | 'waiting' | '';
export interface Quota {
  limit: number;
  hours: number;
  used: number;
  exhausted: boolean;
  resets_at: string | null;
  waiting_proofread: number;
  waiting_twins: number;
}
export interface LibraryState {
  recordings: Recording[];
  pending: number;
  max_pending: number;
  asr: boolean;
  capacity: {
    free_bytes: number;
    arriving_bytes: number;
    arriving: number;
    headroom_bytes: number;
  };
  quota?: Quota;
  /** Twins being rebuilt; ``revision`` moves whenever a rebuild starts or finishes. */
  twins?: { updating: number; revision: number };
}
/**
 * What a row says about itself beyond its title: one thing. Transcribing is the bar, failing is the retry, and a
 * transcribed one says it in the speakers it shows; what is left to name is a recording waiting its turn, or one the
 * viewer only attended.
 */
function stateLabel(recording: Recording): [string, Tone] | null {
  if (recording.can_edit === false) return ['你参加的', 'neutral'];
  return recording.status === 'queued' ? ['排队', 'neutral'] : null;
}
const proofreadLabel: Record<Proofread, string> = {
  done: '已校对',
  failed: '校对未完成，使用识别原文',
  waiting: '待校对',
  '': '',
};
const tokens = (n: number) =>
  n >= 10000 ? `${Math.round(n / 10000).toLocaleString()} 万` : `${n}`;
/** What the spent quota holds back, and when it frees up. */
export function quotaNotice(quota: Quota): string {
  const held = [
    quota.waiting_proofread ? `${quota.waiting_proofread} 段录音的校对` : '',
    quota.waiting_twins ? `${quota.waiting_twins} 个分身的记忆更新` : '',
  ].filter(Boolean);
  const resumes = quota.resets_at
    ? `，约 ${new Date(quota.resets_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} 起自动继续`
    : '';
  return (
    `本批次的大模型额度已用完（${quota.hours} 小时内已用 ${tokens(quota.used)} / ${tokens(quota.limit)} token）` +
    `${held.length ? `，${held.join('和 ')}已暂停` : '，新的校对和分身更新会暂停'}${resumes}。需要更多额度请联系管理员。`
  );
}
const minutes = (seconds: number | null) =>
  seconds === null ? '' : `${Math.max(1, Math.round(seconds / 60))} 分钟`;
/** The day it was made, as a row and its page both say it: when it was recorded (an imported transcript: the day
 * the importer gave), else the day it was added. A bare date is that day wherever the browser is. */
export function madeOn(
  recording: Pick<Recording, 'creation_time' | 'created_at'>,
): string {
  for (const text of [recording.creation_time, recording.created_at]) {
    if (!text) continue;
    const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
    const date = day
      ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]))
      : new Date(text);
    if (!Number.isNaN(date.getTime()))
      return date.toLocaleDateString('zh-CN', {
        month: 'long',
        day: 'numeric',
      });
  }
  return '';
}

export function Library() {
  // The library the side bar counts from too: a change made here shows there at once, and one request serves both.
  const library = useTeam((state) => state.library);
  const loadError = useTeam((state) => state.error);
  const [problem, setProblem] = useState('');
  const error = problem || (library ? '' : loadError);
  const confirm = useConfirm();
  const input = useRef<HTMLInputElement>(null);
  const transcriptInput = useRef<HTMLInputElement>(null);
  // Transcripts chosen or dropped, brought in one at a time.
  const [transcripts, setTranscripts] = useState<File[]>([]);
  const [filter, setFilter] = useState('all');
  const [recollection, setRecollection] = useState<Recollection | null>(null);
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  // What can be collected again is only an offer: the library works the same without it.
  const loadOffer = useCallback(async () => {
    const again = await api<Recollection>('/api/library/recollect').catch(
      () => null,
    );
    setRecollection(Array.isArray(again?.recordings) ? again : null);
  }, []);
  // After a change the page makes: asked again at once, for the side bar's counts as much as for this list.
  const load = useCallback(async () => {
    await Promise.all([useTeam.getState().refresh(true), loadOffer()]);
  }, [loadOffer]);
  // Polling shares the side bar's request when it asked a moment ago.
  const follow = useCallback(async () => {
    await Promise.all([useTeam.getState().refresh(), loadOffer()]);
  }, [loadOffer]);
  useEffect(() => {
    void load();
  }, [load]);
  const { add, uploading, notice, unfinished, stop } = useUploads(
    () => void load(),
  );
  const offered = recollection?.recordings.filter((r) => !r.asked) ?? [];
  const recollecting = recollection?.recordings.filter((r) => r.asked) ?? [];
  const busy = uploading || !!library?.pending || recollecting.length > 0;
  // Proofreading runs on the server; the page follows it, slowly while the quota holds it back.
  const proofreading =
    !!library?.recordings.some((r) => r.proofread === 'waiting') ||
    !!library?.quota?.waiting_twins;
  const interval = busy
    ? 3000
    : proofreading
      ? library?.quota?.exhausted
        ? 60000
        : 3000
      : 0;
  usePolling(follow, interval);

  // Recordings upload; a transcript is read and looked at first, in a dialog of its own.
  const take = (files: File[]) => {
    const texts = files.filter(isTranscript);
    if (texts.length) setTranscripts((current) => [...current, ...texts]);
    void add(files.filter((file) => !isTranscript(file)));
  };
  const retry = async (recording: Recording) => {
    setProblem('');
    try {
      await api(`/api/library/recordings/${recording.id}/retry`, {
        method: 'POST',
      });
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : '重试失败');
    }
    await load();
  };
  const recollect = async (ids: string[]) => {
    setProblem('');
    try {
      await api('/api/library/recollect', {
        method: 'POST',
        json: { recordings: ids },
      });
      setPicking(false);
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : '操作失败');
    }
    await load();
  };
  const collectAgain = async (recording: Recording) => {
    if (
      await confirm({
        title: `重新采集「${recording.filename}」？`,
        body: '重新转写后，已经确认的说话人会尽量沿用，对不上的会请你重新确认；不满意可以在录音的菜单里回到上一版',
        confirmLabel: '重新采集',
      })
    )
      await recollect([recording.id]);
  };
  const rollback = async (recording: Recording) => {
    if (
      !(await confirm({
        title: `「${recording.filename}」回到上一版转写？`,
        body: '回到重新采集之前的转写，那时做的确认都会恢复',
        confirmLabel: '回到上一版',
      }))
    )
      return;
    setProblem('');
    try {
      await api(
        `/api/library/recordings/${encodeURIComponent(recording.id)}/rollback`,
        { method: 'POST' },
      );
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : '回退失败');
    }
    await load();
  };
  const remove = async (recording: Recording) => {
    if (
      !(await confirm({
        title: `删除「${recording.filename}」？`,
        // A transcript has no sound to delete with it.
        body:
          recording.kind === 'transcript'
            ? '导入的转写稿会删除，不能恢复'
            : '转写结果和试听文件会一起删除，不能恢复',
        confirmLabel: '删除录音',
        tone: 'danger',
      }))
    )
      return;
    setProblem('');
    try {
      await api(`/api/library/recordings/${recording.id}`, {
        method: 'DELETE',
      });
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : '删除失败');
    }
    await load();
  };

  const mobile = useMobile();
  const [search, setSearch] = useState('');
  const recordings = library?.recordings ?? [];
  const recollectingIds = new Set(recollecting.map((r) => r.id));
  const matches: Record<string, (recording: Recording) => boolean> = {
    all: () => true,
    waiting: (r) =>
      r.status === 'ready' && r.unsettled > 0 && r.can_edit !== false,
    processing: (r) =>
      r.status === 'queued' ||
      r.status === 'transcribing' ||
      r.proofread === 'waiting' ||
      recollectingIds.has(r.id),
    failed: (r) => r.status === 'failed',
  };
  // By title or by who was in it.
  const wanted = search.trim().toLocaleLowerCase();
  const found = (r: Recording) =>
    !wanted ||
    [r.filename, ...r.people].some((text) =>
      text.toLocaleLowerCase().includes(wanted),
    );
  const filtered = recordings.filter((r) => matches[filter](r) && found(r));
  return (
    <FileDropSurface onFiles={take}>
      <Page
        stackHeaderOnMobile
        title="录音库"
        titleSize="display"
        actions={
          <>
            <ActionMenu
              label="更多"
              items={[
                {
                  label: '导入转写稿',
                  onSelect: () => transcriptInput.current?.click(),
                },
                ...(offered.length > 0
                  ? [
                      {
                        label: `用新版转写重新采集（${offered.length}）`,
                        onSelect: () => {
                          setPicked(new Set(offered.map((r) => r.id)));
                          setPicking(true);
                        },
                      },
                    ]
                  : []),
              ]}
            />
            {mobile && (
              <Button onClick={() => input.current?.click()}>上传录音</Button>
            )}
          </>
        }
      >
        <FileInput ref={input} label="选择录音文件" multiple onFiles={take} />
        <FileInput
          ref={transcriptInput}
          label="选择转写稿"
          accept={TRANSCRIPT_ACCEPT}
          multiple
          onFiles={(files) =>
            setTranscripts((current) => [...current, ...files])
          }
        />
        {error && (
          <Text role="alert" tone="danger">
            {error}
          </Text>
        )}
        {notice && (
          <Text role="status" size="sm" tone="secondary">
            {notice}
          </Text>
        )}
        {library?.quota?.exhausted && (
          <Notice>{quotaNotice(library.quota)}</Notice>
        )}
        {library && !library.asr && (
          <Notice>
            还没有配置能区分说话人的转写服务（asr-funasr），录音会先排队，配置后自动开始转写。
          </Notice>
        )}
        <Toolbar>
          <Tabs
            variant="filters"
            label="录音分类"
            value={filter}
            onValueChange={setFilter}
            items={[
              ['all', '全部'],
              ['waiting', '待确认'],
              ['processing', '处理中'],
              ['failed', '失败'],
            ].map(([value, label]) => ({
              value,
              label: `${label} ${recordings.filter(matches[value]).length}`,
            }))}
          />
          <Input
            type="search"
            aria-label="找录音"
            placeholder="找录音"
            className="w-48"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </Toolbar>
        <UploadList picks={unfinished} uploading={uploading} onStop={stop} />
        {!library ? (
          <Skeleton className="h-32" />
        ) : library.recordings.length === 0 ? (
          <EmptyState
            title="还没有录音"
            body="添加会议录音后，会自动转写并区分每位说话人。"
          />
        ) : (
          <Card>
            {filtered.length === 0 ? (
              <Text align="center" tone="secondary">
                {search.trim() ? '没有找到。' : '这一类里没有录音。'}
              </Text>
            ) : (
              <Stack as="ul" gap={0} aria-label="录音列表">
                {filtered.map((recording) => {
                  const label = stateLabel(recording);
                  const ready = recording.status === 'ready';
                  const failed = recording.status === 'failed';
                  const editable = recording.can_edit !== false;
                  return (
                    <ListRow
                      variant="divided"
                      stackOnMobile
                      key={recording.id}
                      title={
                        ready ? (
                          <TextLink
                            to={`/library/${encodeURIComponent(recording.id)}`}
                            weight="medium"
                            truncate
                            title={recording.filename}
                          >
                            {recording.filename}
                          </TextLink>
                        ) : (
                          <Text truncate title={recording.filename}>
                            {recording.filename}
                          </Text>
                        )
                      }
                      meta={[
                        madeOn(recording),
                        recording.kind === 'transcript' &&
                        recording.duration_s !== null
                          ? `约 ${minutes(recording.duration_s)}`
                          : minutes(recording.duration_s),
                        ready ? `${recording.speakers} 位说话人` : '',
                        recording.proofreading
                          ? '校对中'
                          : proofreadLabel[recording.proofread ?? ''],
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                      trailing={
                        <>
                          {ready && (
                            <AvatarStack
                              names={recording.people}
                              unknown={editable ? recording.unsettled : 0}
                            />
                          )}
                          {recording.kind === 'transcript' && (
                            <Badge>转写稿</Badge>
                          )}
                          {label && <Badge tone={label[1]}>{label[0]}</Badge>}
                          {recollectingIds.has(recording.id) && (
                            <Badge>重新采集中</Badge>
                          )}
                          {ready &&
                            editable &&
                            !recording.unsettled &&
                            !recollectingIds.has(recording.id) && (
                              <Text as="span" size="sm" tone="success">
                                都认出来了
                              </Text>
                            )}
                          {failed && editable && (
                            <Button
                              variant="secondary"
                              size="sm"
                              title={recording.error || undefined}
                              onClick={() => void retry(recording)}
                            >
                              重试
                            </Button>
                          )}
                          {ready && recording.unsettled > 0 && editable && (
                            <RouteButton
                              size="sm"
                              to={`/library/${encodeURIComponent(recording.id)}`}
                            >
                              认 {recording.unsettled} 位说话人
                            </RouteButton>
                          )}
                          {editable && (
                            <ActionMenu
                              label={`更多：${recording.filename}`}
                              items={[
                                ...(offered.some((r) => r.id === recording.id)
                                  ? [
                                      {
                                        label: '重新采集',
                                        onSelect: () =>
                                          void collectAgain(recording),
                                      },
                                    ]
                                  : []),
                                ...(recording.previous
                                  ? [
                                      {
                                        label: '回到上一版转写',
                                        onSelect: () =>
                                          void rollback(recording),
                                      },
                                    ]
                                  : []),
                                {
                                  label: '删除',
                                  disabled: recording.status === 'transcribing',
                                  onSelect: () => void remove(recording),
                                },
                              ]}
                            />
                          )}
                        </>
                      }
                    >
                      {recording.status === 'transcribing' && (
                        <Meter
                          size="sm"
                          hideLabel
                          label={`${recording.filename}转写进度`}
                          value={
                            recording.duration_s
                              ? recording.transcribed_s
                              : null
                          }
                          max={recording.duration_s ?? 100}
                        />
                      )}
                      {recording.error && !(failed && editable) && (
                        <Text size="sm" tone="danger">
                          {recording.error}
                        </Text>
                      )}
                    </ListRow>
                  );
                })}
              </Stack>
            )}
          </Card>
        )}
      </Page>
      <ImportTranscript
        file={transcripts[0] ?? null}
        onClose={() => setTranscripts((current) => current.slice(1))}
        onImported={(result) => {
          setTranscripts((current) => current.slice(1));
          void load();
          toast(
            result.new === false
              ? '这份转写稿已经导入过'
              : result.unsettled
                ? `导入了，还有 ${result.unsettled} 位说话人要认`
                : '导入了，说话人都认出来了',
            'success',
          );
        }}
      />
      <Dialog
        open={picking}
        onOpenChange={setPicking}
        title="用新版转写重新采集"
        body="重新转写后，已经确认的说话人会尽量沿用，对不上的会请你重新确认；不满意可以在录音的菜单里回到上一版。转写时排队进行，不影响使用。"
      >
        <Stack gap={4}>
          <Stack gap={0} aria-label="要重新采集的录音">
            {offered.map((r) => (
              <Checkbox
                key={r.id}
                label={r.filename}
                checked={picked.has(r.id)}
                onChange={(event) => {
                  const next = new Set(picked);
                  if (event.target.checked) next.add(r.id);
                  else next.delete(r.id);
                  setPicked(next);
                }}
              />
            ))}
          </Stack>
          <Row gap={2} justify="end">
            <Button variant="ghost" onClick={() => setPicking(false)}>
              取消
            </Button>
            <Button
              disabled={picked.size === 0}
              onClick={() => void recollect([...picked])}
            >
              重新采集 {picked.size} 份
            </Button>
          </Row>
        </Stack>
      </Dialog>
    </FileDropSurface>
  );
}
