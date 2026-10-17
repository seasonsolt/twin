import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  Heading,
  Radio,
  Text,
  toast,
} from '../../components/ui';
import { api, ApiError } from '../../lib/api';
import { personaUrl } from '../../lib/persona';
import { ASSETS_CHANGED } from '../assets/SelfAssets';

interface Speaker {
  id: string;
  seconds: number;
  similarity: number | null;
  suggested: boolean;
  also_suggested: boolean;
  samples: string[];
}
interface Candidate {
  id: string;
  url: string;
}
interface Claim {
  claimed: string[];
  diarized: boolean;
  confirmed: boolean;
  automatic: boolean;
  pending: boolean;
  speakers: Speaker[];
  voices: Candidate[];
  portraits: Candidate[];
  candidate_error: string | null;
}

function SpeakerSample({ speaker }: { speaker: Speaker }) {
  const audio = useRef<HTMLAudioElement>(null);
  const next = useRef(0);
  const [error, setError] = useState('');
  return (
    <div className="min-w-0 space-y-2">
      <Button
        className="min-h-11"
        size="sm"
        variant="ghost"
        disabled={!speaker.samples.length}
        onClick={() => {
          const player = audio.current;
          if (!player) return;
          setError('');
          player.src = personaUrl(speaker.samples[next.current]);
          next.current = (next.current + 1) % speaker.samples.length;
          void player.play().catch(() => setError('试听失败，请重试'));
        }}
      >
        试听 {speaker.id}
      </Button>
      <audio
        ref={audio}
        controls
        preload="none"
        aria-label={`${speaker.id} 试听`}
        className="h-11 w-full"
        src={speaker.samples[0] ? personaUrl(speaker.samples[0]) : undefined}
        onError={() => setError('试听失败，请重试')}
      />
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
    </div>
  );
}

export function MediaClaim({
  sourceId,
  onChanged,
}: {
  sourceId: string;
  onChanged?: () => void;
}) {
  const [claim, setClaim] = useState<Claim | null>(null);
  const [selection, setSelection] = useState<string[] | null>(null);
  const dirty = useRef(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const mutation = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const base = `/api/persona/sources/${encodeURIComponent(sourceId)}`;
  const refresh = useCallback(
    async function reload() {
      request.current?.abort();
      if (timer.current) clearTimeout(timer.current);
      const controller = new AbortController();
      request.current = controller;
      try {
        const value = await api<Claim>(`${base}/speakers`, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setClaim(value);
        if (!dirty.current)
          setSelection(value.confirmed ? value.claimed : null);
        setError('');
        if (value.pending)
          timer.current = setTimeout(() => void reload(), 2000);
      } catch (failure) {
        if (!controller.signal.aborted) {
          setError(
            failure instanceof Error ? failure.message : '无法读取说话人',
          );
          if (failure instanceof ApiError && failure.status === 409)
            timer.current = setTimeout(() => void reload(), 2000);
        }
      }
    },
    [base],
  );
  useEffect(() => {
    void refresh();
    return () => {
      request.current?.abort();
      mutation.current?.abort();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [refresh]);

  const mutate = async (
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
      await api(`${base}/${path}`, { method, json, signal: controller.signal });
      if (controller.signal.aborted) return;
      toast(message, 'success');
      if (path.startsWith('adopt-'))
        window.dispatchEvent(new Event(ASSETS_CHANGED));
      if (path === 'speaker') dirty.current = false;
      await refresh();
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
  return (
    <div className="mb-5 space-y-5">
      {error && (
        <p role="alert" className="text-danger">
          {error}{' '}
          <Button variant="ghost" onClick={() => void refresh()}>
            重试
          </Button>
        </p>
      )}
      {claim && (
        <>
          <fieldset disabled={busy} className="min-w-0 space-y-3">
            <Text as="legend" size="lg" weight="semibold">
              说话人
            </Text>
            {!claim.confirmed && (
              <Text size="sm" tone="secondary">
                请确认哪位是你
              </Text>
            )}
            {claim.automatic && claim.speakers.length > 1 && (
              <Text size="sm" tone="secondary">
                已自动识别，可修改
              </Text>
            )}
            {!claim.diarized && (
              <Text size="sm" tone="secondary">
                当前转写服务不区分说话人
              </Text>
            )}
            {!claim.diarized ? (
              <Radio
                label="整段都是我"
                name={`speaker-${sourceId}`}
                checked={selection !== null && selection.length > 0}
                onChange={() => {
                  dirty.current = true;
                  setSelection(claim.speakers.map((speaker) => speaker.id));
                }}
              />
            ) : (
              claim.speakers.map((speaker) => (
                <Card key={speaker.id} as="div" variant="outline" padding="sm">
                  <Checkbox
                    value={speaker.id}
                    checked={selection?.includes(speaker.id) ?? false}
                    label={
                      <>
                        {speaker.id} ·{' '}
                        {speaker.seconds < 60
                          ? `${speaker.seconds.toFixed(0)} 秒`
                          : `${(speaker.seconds / 60).toFixed(1)} 分钟`}
                      </>
                    }
                    onChange={(event) => {
                      dirty.current = true;
                      setSelection(
                        event.target.checked
                          ? [...(selection ?? []), speaker.id]
                          : (selection ?? []).filter((id) => id !== speaker.id),
                      );
                    }}
                  >
                    {speaker.suggested && <Badge tone="success">像你</Badge>}
                    {speaker.also_suggested && <Badge>可能也是你</Badge>}
                  </Checkbox>
                  <SpeakerSample speaker={speaker} />
                </Card>
              ))
            )}
            <Radio
              label="都不是我（旁观资料）"
              name={`speaker-${sourceId}`}
              value="none"
              checked={selection !== null && selection.length === 0}
              onChange={() => {
                dirty.current = true;
                setSelection([]);
              }}
            />
            <Button
              className="min-h-11"
              disabled={selection === null}
              onClick={() =>
                void mutate(
                  'speaker',
                  { speakers: selection },
                  selection?.length
                    ? '已确认，正在重新整理记忆'
                    : '已保存为旁观资料',
                  'PUT',
                )
              }
            >
              确认选择
            </Button>
          </fieldset>
          {claim.confirmed && (
            <>
              <section aria-label="声音候选" className="space-y-3">
                <Heading level={3}>声音候选</Heading>
                {!claim.voices.length && (
                  <Text size="sm" tone="secondary">
                    {claim.pending
                      ? '正在从你的片段里挑选…'
                      : '暂无足够长的清晰片段'}
                  </Text>
                )}
                {claim.voices.map((candidate, i) => (
                  <div key={candidate.id} className="space-y-2">
                    <audio
                      controls
                      preload="none"
                      aria-label={`声音候选 ${i + 1}`}
                      src={personaUrl(candidate.url)}
                      className="h-11 w-full"
                    />
                    <Button
                      className="min-h-11"
                      disabled={busy}
                      onClick={() =>
                        void mutate(
                          'adopt-voice',
                          { candidate: candidate.id },
                          '已更新你的声音',
                        )
                      }
                    >
                      用这段做声音
                    </Button>
                  </div>
                ))}
              </section>
              <section aria-label="形象候选" className="space-y-3">
                <Heading level={3}>形象候选</Heading>
                {!claim.portraits.length && (
                  <Text size="sm" tone="secondary">
                    {claim.pending ? '正在提取形象候选…' : '暂无形象候选'}
                  </Text>
                )}
                <div className="grid grid-cols-2 gap-3">
                  {claim.portraits.map((candidate, i) => (
                    <div key={candidate.id} className="min-w-0 space-y-2">
                      <Card
                        as="div"
                        variant="soft"
                        padding="none"
                        className="overflow-hidden"
                      >
                        <img
                          src={personaUrl(candidate.url)}
                          alt={`形象候选 ${i + 1}`}
                          className="aspect-3/4 w-full object-cover"
                        />
                      </Card>
                      <Button
                        className="min-h-11 w-full"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          void mutate(
                            'adopt-portrait',
                            { candidate: candidate.id },
                            '已更新你的形象',
                          )
                        }
                      >
                        用这张做形象
                      </Button>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}
          {claim.candidate_error && (
            <Text role="status" size="sm" tone="danger">
              {claim.candidate_error}{' '}
              <Button
                variant="ghost"
                className="min-h-11"
                disabled={busy}
                onClick={() =>
                  void mutate(
                    'speaker',
                    { speakers: claim.claimed },
                    '正在重新提取候选',
                    'PUT',
                  )
                }
              >
                重试候选
              </Button>
            </Text>
          )}
        </>
      )}
    </div>
  );
}

// Enough recordings to pick a voice or portrait from; the memory page lists every one.
const SHORTCUT_LIMIT = 20;

export function RecordingShortcut() {
  const [sources, setSources] = useState<
    {
      source_id: string;
      title: string;
      voice_candidates: number;
      portrait_candidates: number;
      candidates_pending?: boolean;
      status?: string;
    }[]
  >([]);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const reload = async () => {
      try {
        const page = await api<{
          items: typeof sources;
          summary: { busy: number };
        }>(`/api/persona/sources?candidates=true&limit=${SHORTCUT_LIMIT}`, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setSources(page.items);
        if (page.summary.busy > 0)
          timer = setTimeout(() => void reload(), 2000);
      } catch {
        // The optional shortcut must not block manual asset setup.
      }
    };
    void reload();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, []);
  if (!sources.length) return null;
  return (
    <div className="space-y-2">
      <p className="font-medium">从你的视频里挑一个</p>
      {sources.map((source) => (
        <Button
          key={source.source_id}
          variant="ghost"
          className="min-h-11"
          onClick={() => setSelected(source.source_id)}
        >
          {source.title}
        </Button>
      ))}
      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title="从你的视频里挑一个"
        body="试听或看看候选，喜欢就直接使用。"
      >
        {selected && <MediaClaim key={selected} sourceId={selected} />}
      </Dialog>
    </div>
  );
}
