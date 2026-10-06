import { useCallback, useEffect, useRef, useState } from 'react';
import { Badge, Button, Dialog, toast } from '../../components/ui';
import { api, ApiError } from '../../lib/api';
import { personaUrl } from '../../lib/persona';
import { ASSETS_CHANGED } from '../assets/SelfAssets';

interface Speaker {
  id: string;
  seconds: number;
  similarity: number | null;
  suggested: boolean;
  samples: string[];
}
interface Candidate {
  id: string;
  url: string;
}
interface Claim {
  speaker: string | null;
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
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
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
            <legend className="text-lg font-semibold">说话人</legend>
            {!claim.confirmed && (
              <p className="text-sm text-secondary">请确认哪位是你</p>
            )}
            {claim.automatic && claim.speakers.length > 1 && (
              <p className="text-sm text-secondary">已自动识别，可修改</p>
            )}
            {claim.speakers.map((speaker) => (
              <div
                key={speaker.id}
                className="rounded-lg border border-border p-3"
              >
                <label className="flex min-h-11 items-center gap-3 text-base">
                  <input
                    type="radio"
                    name={`speaker-${sourceId}`}
                    value={speaker.id}
                    checked={claim.confirmed && claim.speaker === speaker.id}
                    className="size-5"
                    onChange={() =>
                      void mutate(
                        'speaker',
                        { speaker: speaker.id },
                        '已确认，正在重新整理记忆',
                        'PUT',
                      )
                    }
                  />
                  <span>
                    {speaker.id} ·{' '}
                    {speaker.seconds < 60
                      ? `${speaker.seconds.toFixed(0)} 秒`
                      : `${(speaker.seconds / 60).toFixed(1)} 分钟`}
                  </span>
                  {speaker.suggested && <Badge tone="success">像你</Badge>}
                </label>
                <SpeakerSample speaker={speaker} />
              </div>
            ))}
            <label className="flex min-h-11 items-center gap-3 text-base">
              <input
                type="radio"
                name={`speaker-${sourceId}`}
                value="none"
                className="size-5"
                checked={claim.confirmed && claim.speaker === null}
                onChange={() =>
                  void mutate(
                    'speaker',
                    { speaker: null },
                    '已保存为旁观资料',
                    'PUT',
                  )
                }
              />
              都不是我（旁观资料）
            </label>
          </fieldset>
          {claim.confirmed && (
            <>
              <section aria-label="声音候选" className="space-y-3">
                <h3 className="text-lg font-semibold">声音候选</h3>
                {!claim.voices.length && (
                  <p className="text-sm text-secondary">
                    {claim.pending
                      ? '正在从你的片段里挑选…'
                      : '暂无足够长的清晰片段'}
                  </p>
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
                <h3 className="text-lg font-semibold">形象候选</h3>
                {!claim.portraits.length && (
                  <p className="text-sm text-secondary">
                    {claim.pending ? '正在提取形象候选…' : '暂无形象候选'}
                  </p>
                )}
                <div className="grid grid-cols-2 gap-3">
                  {claim.portraits.map((candidate, i) => (
                    <div key={candidate.id} className="min-w-0 space-y-2">
                      <img
                        src={personaUrl(candidate.url)}
                        alt={`形象候选 ${i + 1}`}
                        className="aspect-[3/4] w-full rounded-lg object-cover"
                      />
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
            <p role="status" className="text-sm text-danger">
              {claim.candidate_error}{' '}
              <Button
                variant="ghost"
                className="min-h-11"
                disabled={busy}
                onClick={() =>
                  void mutate(
                    'speaker',
                    { speaker: claim.speaker },
                    '正在重新提取候选',
                    'PUT',
                  )
                }
              >
                重试候选
              </Button>
            </p>
          )}
        </>
      )}
    </div>
  );
}

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
        const rows = await api<typeof sources>('/api/persona/sources', {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setSources(
          rows.filter((row) => row.voice_candidates || row.portrait_candidates),
        );
        if (
          rows.some(
            (row) =>
              row.candidates_pending ||
              ['queued', 'extracting', 'transcribing'].includes(
                row.status ?? '',
              ),
          )
        )
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
