import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { Upload } from 'lucide-react';
import { Button, Skeleton } from '../components/ui';
import { api } from '../lib/api';
import { Team } from '../features/library/Team';
import { UploadList } from '../features/library/UploadList';
import { MEDIA_ACCEPT, useUploads } from '../features/library/useUploads';
import type { LibraryState } from './Library';

const STEPS: [string, string][] = [
  ['转写，区分说话人', '每段录音只转写一次。'],
  ['自动认人', '认得出的直接归位；新声音建成“未命名”，拿不准的请你听一下。'],
  ['起名，生成分身', '之后的录音会自动补充到他的记忆里。'],
];

/** The account's start page: the people found in its meeting recordings, what needs settling, and uploading. With
 * no recording yet, it is the way to the first one. */
export function Home() {
  const [library, setLibrary] = useState<LibraryState | null>(null);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  // Bumped on every reload, so people and the review queue follow new transcripts.
  const [version, setVersion] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    try {
      setLibrary(await api<LibraryState>('/api/library'));
      setVersion((v) => v + 1);
      setError('');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法加载录音');
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const { add, uploading, notice, unfinished, stop } = useUploads(
    () => void load(),
  );
  const busy = uploading || !!library?.pending;
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [busy, load]);

  const picker = (
    <input
      ref={input}
      type="file"
      multiple
      accept={MEDIA_ACCEPT}
      className="sr-only"
      aria-label="选择录音文件"
      onChange={(event) => {
        const files = Array.from(event.currentTarget.files ?? []);
        event.currentTarget.value = '';
        void add(files);
      }}
    />
  );
  const fresh = library !== null && library.recordings.length === 0;
  return (
    <div className="home-page">
      <div className="page-content space-y-8">
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="text-sm text-secondary">
            {notice}
          </p>
        )}
        {library && !library.asr && (
          <p role="status" className="rounded-xl bg-note p-4 text-sm">
            还没有配置能区分说话人的转写服务（asr-funasr），录音会先排队，配置后自动开始转写。
          </p>
        )}
        {!library ? (
          <Skeleton className="h-64" />
        ) : fresh ? (
          <>
            <header className="space-y-2 text-center">
              <h2 className="text-3xl font-semibold">从一段会议录音开始</h2>
              <p className="text-secondary">
                不用先建档。上传后自动区分每个人、认出已知的人，新出现的人自动建档。
              </p>
            </header>
            <section
              aria-label="添加录音"
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                void add(Array.from(event.dataTransfer.files));
              }}
              className={`flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed bg-surface px-6 py-12 text-center ${dragging ? 'border-accent bg-soft' : 'border-tertiary'}`}
            >
              <Upload aria-hidden className="size-10" />
              <p className="text-lg">把会议录音拖到这里</p>
              <Button
                disabled={uploading}
                onClick={() => input.current?.click()}
              >
                选择文件
              </Button>
              {picker}
              <p className="text-sm text-secondary">
                音频或视频都可以，一次可以选多个。只有你的账号能看到。
              </p>
            </section>
            <UploadList
              picks={unfinished}
              uploading={uploading}
              onStop={stop}
            />
            <ol
              aria-label="接下来会发生什么"
              className="grid gap-4 sm:grid-cols-3"
            >
              {STEPS.map(([title, body], i) => (
                <li
                  key={title}
                  className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-5"
                >
                  <span
                    aria-hidden
                    className="grid size-8 place-items-center rounded-full bg-primary font-semibold text-canvas"
                  >
                    {i + 1}
                  </span>
                  <span className="font-semibold">{title}</span>
                  <span className="text-sm text-secondary">{body}</span>
                </li>
              ))}
            </ol>
            <p className="text-center text-secondary">
              想先给自己建一个分身？
              <Link
                to="/twins?create=1"
                className="inline-flex min-h-11 items-center text-accent underline"
              >
                用文字资料新建
              </Link>
            </p>
          </>
        ) : (
          <>
            <header className="flex flex-wrap items-end justify-between gap-4">
              <div className="space-y-1">
                <h2 className="text-2xl font-semibold">团队</h2>
                <p className="text-secondary">
                  会议里出现过的人。上传新录音后，系统会自动认人，有拿不准的再请你确认。
                </p>
              </div>
              <Button
                disabled={uploading}
                onClick={() => input.current?.click()}
              >
                <Upload aria-hidden className="size-5" />
                上传会议录音
              </Button>
              {picker}
            </header>
            <UploadList
              picks={unfinished}
              uploading={uploading}
              onStop={stop}
            />
            <Team version={version} recordings={library.recordings} />
            <p>
              <Link
                to="/library"
                className="inline-flex min-h-11 items-center text-accent underline"
              >
                全部录音（{library.recordings.length}）
              </Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
