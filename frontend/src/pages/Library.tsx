import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  EmptyState,
  FileDropSurface,
  FileInput,
  ActionMenu,
  Card,
  Checkbox,
  Dialog,
  Meter,
  Row,
  Page,
  Tabs,
  RouteButton,
  ListRow,
  Notice,
  Skeleton,
  Stack,
  Text,
  TextLink,
  Toolbar,
  useConfirm,
  type Tone,
} from '../components/ui';
import { api } from '../lib/api';
import { usePolling } from '../lib/usePolling';
import { UploadList } from '../features/library/UploadList';
import { MEDIA_ACCEPT, useUploads } from '../features/library/useUploads';

export interface Recording {
  id: string;
  filename: string;
  size: number;
  kind: 'audio' | 'video';
  status: 'queued' | 'transcribing' | 'ready' | 'failed';
  error: string;
  duration_s: number | null;
  transcribed_s: number;
  speakers: number;
  segments: number;
  created_at: string;
  // Who the speakers were recognised as, and how many still wait for the owner.
  people: string[];
  unsettled: number;
  // Whether the model proofread the transcript: done, gave nothing, still to come, or not due (no one identified).
  proofread?: Proofread;
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
}
const statusLabel: Record<Recording['status'], [string, Tone]> = {
  queued: ['排队', 'neutral'],
  transcribing: ['转写中', 'info'],
  ready: ['已转写', 'success'],
  failed: ['失败', 'danger'],
};
/** A transcribed recording is described by how far its speakers are identified. */
function identityLabel(recording: Recording): [string, Tone] {
  if (recording.can_edit === false) return ['你参加的', 'neutral'];
  if (recording.status !== 'ready') return statusLabel[recording.status];
  if (!recording.unsettled) return ['已认人', 'success'];
  return [`${recording.unsettled} 位待确认`, 'warning'];
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
const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;
const minutes = (seconds: number | null) =>
  seconds === null ? '' : `${Math.max(1, Math.round(seconds / 60))} 分钟`;

export function Library() {
  const [library, setLibrary] = useState<LibraryState | null>(null);
  const [error, setError] = useState('');
  const confirm = useConfirm();
  const input = useRef<HTMLInputElement>(null);
  const [filter, setFilter] = useState('all');
  const [recollection, setRecollection] = useState<Recollection | null>(null);
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const [state, again] = await Promise.all([
        api<LibraryState>('/api/library'),
        // Only an offer: the library works the same without it.
        api<Recollection>('/api/library/recollect').catch(() => null),
      ]);
      setLibrary(state);
      setRecollection(Array.isArray(again?.recordings) ? again : null);
      setError('');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法加载录音库');
    }
  }, []);
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
  usePolling(load, interval);

  const retry = async (recording: Recording) => {
    try {
      await api(`/api/library/recordings/${recording.id}/retry`, {
        method: 'POST',
      });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '重试失败');
    }
    await load();
  };
  const recollect = async (ids: string[]) => {
    try {
      await api('/api/library/recollect', {
        method: 'POST',
        json: { recordings: ids },
      });
      setPicking(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作失败');
    }
    await load();
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
    try {
      await api(
        `/api/library/recordings/${encodeURIComponent(recording.id)}/rollback`,
        { method: 'POST' },
      );
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '回退失败');
    }
    await load();
  };
  const remove = async (recording: Recording) => {
    if (
      !(await confirm({
        title: `删除「${recording.filename}」？`,
        body: '转写结果和试听文件会一起删除，不能恢复',
        confirmLabel: '删除录音',
        tone: 'danger',
      }))
    )
      return;
    try {
      await api(`/api/library/recordings/${recording.id}`, {
        method: 'DELETE',
      });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '删除失败');
    }
    await load();
  };

  const capacity = library?.capacity;
  const room = capacity
    ? capacity.free_bytes - capacity.arriving_bytes - capacity.headroom_bytes
    : 0;
  const recordings = library?.recordings ?? [];
  const matches: Record<string, (recording: Recording) => boolean> = {
    all: () => true,
    waiting: (r) =>
      r.status === 'ready' && r.unsettled > 0 && r.can_edit !== false,
    processing: (r) =>
      r.status === 'queued' ||
      r.status === 'transcribing' ||
      r.proofread === 'waiting',
    failed: (r) => r.status === 'failed',
  };
  const filtered = recordings.filter(matches[filter]);
  return (
    <FileDropSurface disabled={uploading} onFiles={(files) => void add(files)}>
      <Page
        stackHeaderOnMobile
        title="录音库"
        titleSize="display"
        description="团队共用：你上传的由你整理，你参加的会议你也能查看。转写校验完成后删除原件，保留转写稿和试听用的音频。"
        actions={
          <>
            {library && capacity && (
              <Text size="xs" tone="tertiary">
                排队 {library.pending} / {library.max_pending} · 还能放约{' '}
                {gb(Math.max(0, room))}
              </Text>
            )}
            <Button disabled={uploading} onClick={() => input.current?.click()}>
              上传录音
            </Button>
          </>
        }
      >
        <FileInput
          ref={input}
          label="选择录音文件"
          accept={MEDIA_ACCEPT}
          multiple
          disabled={uploading}
          onFiles={(files) => void add(files)}
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
          <Text size="xs" tone="tertiary">
            把录音拖到页面任意位置即可上传
          </Text>
        </Toolbar>
        {(offered.length > 0 || recollecting.length > 0) && (
          <Row gap={2} wrap>
            <Text size="sm" tone="secondary" role="status">
              {recollecting.length > 0
                ? `${recollecting.length} 份录音正在排队用新版转写重新采集`
                : `${offered.length} 份录音可以用新版转写重新采集，说话人分得更准`}
            </Text>
            {offered.length > 0 && (
              <TextLink
                size="sm"
                onClick={() => {
                  setPicked(new Set(offered.map((r) => r.id)));
                  setPicking(true);
                }}
              >
                {recollecting.length > 0
                  ? `选择其余 ${offered.length} 份`
                  : '选择录音'}
              </TextLink>
            )}
          </Row>
        )}
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
                这一类里没有录音。
              </Text>
            ) : (
              <Stack as="ul" gap={0} aria-label="录音列表">
                {filtered.map((recording) => {
                  const [label, tone] = identityLabel(recording);
                  return (
                    <ListRow
                      variant="divided"
                      stackOnMobile
                      key={recording.id}
                      title={
                        recording.status === 'ready' ? (
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
                        Number.isNaN(Date.parse(recording.created_at))
                          ? ''
                          : new Date(recording.created_at).toLocaleDateString(
                              'zh-CN',
                              { month: 'long', day: 'numeric' },
                            ),
                        minutes(recording.duration_s),
                        recording.status === 'ready'
                          ? `${recording.speakers} 位说话人`
                          : '',
                        recording.people.join('、'),
                        proofreadLabel[recording.proofread ?? ''],
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                      trailing={
                        <>
                          <Badge tone={tone}>{label}</Badge>
                          {recording.status === 'failed' &&
                            recording.can_edit !== false && (
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => void retry(recording)}
                              >
                                重试
                              </Button>
                            )}
                          {recording.status === 'ready' &&
                            recording.unsettled > 0 &&
                            recording.can_edit !== false && (
                              <RouteButton
                                size="sm"
                                to={`/library/${encodeURIComponent(recording.id)}`}
                              >
                                确认说话人
                              </RouteButton>
                            )}
                          {recording.can_edit !== false && (
                            <ActionMenu
                              label={`更多：${recording.filename}`}
                              items={[
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
                      {recording.error && (
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
