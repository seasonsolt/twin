import { useCallback, useEffect, useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import {
  Button,
  Card,
  FileDrop,
  FileInput,
  Grid,
  Heading,
  Notice,
  Page,
  Skeleton,
  Stack,
  StepNumber,
  Text,
  Toolbar,
} from '../components/ui';
import { api } from '../lib/api';
import { usePolling } from '../lib/usePolling';
import { Team } from '../features/library/Team';
import { UploadList } from '../features/library/UploadList';
import { MEDIA_ACCEPT, useUploads } from '../features/library/useUploads';
import type { LibraryState } from './Library';
import { NewTwinForm } from '../components/layout/NewTwin';
import { usePersonas } from '../stores/personas';

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
  // Uploads and transcription move by the second; waiting proofreads only need to leave 正在处理 eventually.
  const interval = busy
    ? 3000
    : library?.recordings.some((r) => r.proofread === 'waiting')
      ? library.quota?.exhausted
        ? 60000
        : 15000
      : 0;
  usePolling(load, interval);

  const picker = (
    <FileInput
      ref={input}
      label="选择录音文件"
      multiple
      accept={MEDIA_ACCEPT}
      onFiles={(files) => void add(files)}
    />
  );
  const fresh = library !== null && library.recordings.length === 0;
  // Someone without a twin of their own can start with one of themselves, beside the team's recordings.
  const ownTwin = usePersonas((state) =>
    state.items.some((item) => item.mine || (item.can_manage ?? true)),
  );
  useEffect(() => {
    void usePersonas
      .getState()
      .refresh()
      .catch(() => {});
  }, []);
  const drop = (
    <FileDrop
      label="添加录音"
      size={ownTwin ? 'lg' : 'md'}
      title="把会议录音拖到这里"
      inputLabel="选择录音文件"
      accept={MEDIA_ACCEPT}
      disabled={uploading}
      onFiles={(files) => void add(files)}
      hint="音频或视频都可以，一次可以选多个。只有你的账号能看到。"
    />
  );
  return (
    <div className="home-page">
      <Page gap={8}>
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
        {library && !library.asr && (
          <Notice>
            还没有配置能区分说话人的转写服务（asr-funasr），录音会先排队，配置后自动开始转写。
          </Notice>
        )}
        {!library ? (
          <Skeleton className="h-64" />
        ) : fresh ? (
          <>
            {ownTwin ? (
              <>
                <Stack as="header" gap={2}>
                  <Heading level={2} size="display" align="center">
                    从一段会议录音开始
                  </Heading>
                  <Text tone="secondary" align="center">
                    不用先建档。上传后自动区分每个人、认出已知的人，新出现的人自动建档。
                  </Text>
                </Stack>
                {drop}
              </>
            ) : (
              <Grid columns={2}>
                <Card as="section" aria-labelledby="start-self">
                  <Stack gap={4}>
                    <Stack gap={1}>
                      <Heading id="start-self" level={2} size="title">
                        给自己建分身
                      </Heading>
                      <Text size="sm" tone="secondary">
                        它从你说过的话里学你怎么想、怎么说。
                      </Text>
                    </Stack>
                    <NewTwinForm />
                  </Stack>
                </Card>
                <Card as="section" aria-labelledby="start-team">
                  <Stack gap={4}>
                    <Stack gap={1}>
                      <Heading id="start-team" level={2} size="title">
                        从团队会议录音开始
                      </Heading>
                      <Text size="sm" tone="secondary">
                        自动区分每个人、认出已知的人，新出现的人自动建档。
                      </Text>
                    </Stack>
                    {drop}
                  </Stack>
                </Card>
              </Grid>
            )}
            <UploadList
              picks={unfinished}
              uploading={uploading}
              onStop={stop}
            />
            <Grid as="ol" columns={3} aria-label="接下来会发生什么">
              {STEPS.map(([title, body], i) => (
                <Card
                  as="li"
                  key={title}
                  variant="outline"
                  className="flex flex-col gap-2"
                >
                  <StepNumber>{i + 1}</StepNumber>
                  <Text as="span" weight="semibold">
                    {title}
                  </Text>
                  <Text as="span" size="sm" tone="secondary">
                    {body}
                  </Text>
                </Card>
              ))}
            </Grid>
          </>
        ) : (
          <>
            <Toolbar as="header" gap={4} align="end">
              <Stack gap={1}>
                <Heading level={2} size="display">
                  团队
                </Heading>
                <Text tone="secondary">
                  会议里出现过的人。上传新录音后，系统会自动认人，有拿不准的再请你确认。
                </Text>
              </Stack>
              <Button
                disabled={uploading}
                onClick={() => input.current?.click()}
              >
                <Upload aria-hidden className="size-5" />
                上传会议录音
              </Button>
              {picker}
            </Toolbar>
            <UploadList
              picks={unfinished.filter((pick) => pick.error)}
              uploading={false}
              onStop={stop}
            />
            <Team
              version={version}
              recordings={library.recordings}
              onReload={load}
              uploads={unfinished.filter((pick) => !pick.error)}
              onStopUpload={uploading ? stop : undefined}
            />
          </>
        )}
      </Page>
    </div>
  );
}
