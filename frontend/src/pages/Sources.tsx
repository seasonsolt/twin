import { useRef, useState } from 'react';
import { useLocation } from 'react-router';
import { MessageList } from '../components/effects/MessageList';
import { LayoutScope } from '../components/motion';
import {
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Skeleton,
  toast,
  useConfirm,
} from '../components/ui';
import { JobProgress } from '../features/jobs/JobProgress';
import { useJob } from '../features/jobs/useJob';
import {
  BuildSummary,
  DropZone,
  KindSelector,
  SourceRow,
} from '../features/sources/SourceCards';
import { useSources } from '../features/sources/useSources';
import {
  staleNotice,
  type BuildResult,
  type SourceKind,
} from '../features/sources/types';
import { useStatus } from '../stores/status';

export function Sources() {
  const active = useLocation().pathname === '/sources';
  const data = useSources(active);
  const confirm = useConfirm();
  const [kind, setKind] = useState<SourceKind>('questionnaire');
  const [date, setDate] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [summary, setSummary] = useState<BuildResult | null>(null);
  const currentFiles = useRef(files);
  currentFiles.current = files;
  const job = useJob<BuildResult>({
    kind: 'persona_build',
    storageKey: 'twin.next.job.personaBuild',
    active,
    onDone: (done, { restored }) => {
      setSummary(done.result ?? {});
      void data.reload();
      void useStatus.getState().refresh();
      if (!restored) toast('人格档案已更新。', 'success');
    },
  });
  const build = () => {
    setSummary(null);
    void job.start('/api/persona/build');
  };
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">记忆资料</h1>
        <p className="mt-2 text-sm text-secondary">
          导入问卷、聊天记录、访谈和文档。问卷和访谈记为“本人自述”，聊天和文档记为“实际行为”，完成度会分开统计。导入后点“构建人格档案”。
        </p>
      </header>
      <Card>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!files.length) {
              toast('请先选择文件', 'warning');
              return;
            }
            const selected = files;
            void data.upload(selected, kind, date).then((ok) => {
              if (ok && currentFiles.current === selected) setFiles([]);
            });
          }}
        >
          <h2 className="text-lg font-semibold">导入资料</h2>
          <KindSelector
            value={kind}
            onChange={setKind}
            disabled={data.uploading}
          />
          <Field
            id="source-date"
            label="资料日期（可选）"
            help="问卷、访谈、文档默认从文件名识别日期"
          >
            <Input
              id="source-date"
              type="date"
              value={date}
              disabled={data.uploading}
              onChange={(event) => setDate(event.target.value)}
              aria-describedby="source-date-description"
              className="max-w-64"
            />
          </Field>
          <DropZone
            kind={kind}
            files={files}
            onChange={setFiles}
            disabled={data.uploading}
          />
          <Button type="submit" loading={data.uploading}>
            导入
          </Button>
          {data.importError && (
            <p role="alert" className="text-sm text-danger">
              导入失败：{data.importError}
            </p>
          )}
          {data.result && (
            <ul
              aria-label="导入结果"
              className="space-y-1 text-sm"
              aria-live="polite"
            >
              {data.result.imported.map((source) => (
                <li key={source.source_id} className="text-success">
                  {source.new ? '已导入' : '已更新'}：{source.title}（本人{' '}
                  {source.n_target} 条）
                </li>
              ))}
              {data.result.skipped.map((skip, i) => (
                <li key={i} className="text-warning">
                  未导入：{skip.file}：{skip.reason}
                </li>
              ))}
            </ul>
          )}
        </form>
      </Card>
      <Card>
        <h2 className="mb-4 text-lg font-semibold">已导入的资料</h2>
        {data.loading && <Skeleton className="h-24" />}
        {data.error && (
          <div role="alert" className="mb-3 text-danger">
            {data.error}{' '}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void data.reload()}
            >
              重试加载
            </Button>
          </div>
        )}
        {!data.loading && !data.error && !data.sources.length && (
          <EmptyState
            title="还没有导入资料"
            body="从上面选择资料类型和文件导入。"
          />
        )}
        <LayoutScope>
          <MessageList
            layout
            label="已导入资料"
            items={data.sources.map((source) => ({
              id: source.source_id,
              text: source.title,
              content: (
                <SourceRow
                  source={source}
                  onDelete={() => {
                    void (async () => {
                      if (
                        await confirm({
                          title: '删除资料？',
                          body: `删除“${source.title}”及从它提炼的档案内容？下次构建时生效。`,
                          confirmLabel: '确认删除',
                          tone: 'danger',
                        })
                      )
                        await data.remove(source);
                    })();
                  }}
                />
              ),
            }))}
          />
        </LayoutScope>
      </Card>
      <Card>
        <h2 className="text-lg font-semibold">构建</h2>
        <p className="my-3 text-sm text-secondary">
          只处理新增或变化的资料；已经完成的模型调用不会重复。
        </p>
        {data.stale && (
          <p
            role="status"
            className="mb-4 rounded-md border border-warning/20 bg-warning/5 p-3 text-sm text-secondary"
          >
            {staleNotice}
          </p>
        )}
        <Button loading={job.busy} onClick={build}>
          {job.busy ? '构建中…' : '构建人格档案'}
        </Button>
        <JobProgress state={job} onRetry={build} />
        {summary && <BuildSummary result={summary} />}
      </Card>
    </div>
  );
}
