import { useCallback, useEffect, useRef } from 'react';
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
  Row,
  Skeleton,
  Stack,
  StepNumber,
  Text,
  Toolbar,
  toast,
} from '../components/ui';
import { basePath } from '../lib/base';
import { usePolling } from '../lib/usePolling';
import { Team } from '../features/library/Team';
import { UploadList } from '../features/library/UploadList';
import { useUploads } from '../features/library/useUploads';
import { useTeam } from '../stores/team';

const STEPS: [string, string][] = [
  ['转写，分出每个人', '每段录音只转写一次。'],
  ['认人', '认得出的直接归位，拿不准的放进待处理请你听一下。'],
  ['每人一个分身', '之后的录音自动补进他的记忆。'],
];

/** The site's address, to send to colleagues so they can sign in and recognise themselves in the meetings. */
function copyInvite() {
  const link = `${window.location.origin}${basePath()}/`;
  void navigator.clipboard.writeText(link).then(
    () => toast('邀请链接已复制，可以发给同事', 'success'),
    () => toast(link, 'info', 15000),
  );
}

/** The account's start page: the people found in its meeting recordings, what needs settling, and uploading. With
 * no recording yet, it is the way to the first one. */
export function Home() {
  // The library the side bar also counts from. `version` moves when a recording changes in a way people and the
  // review queue follow (a transcript arriving, speakers settled, one removed), not on every poll: while recordings
  // wait, the page polls every few seconds, and the review queue is the heaviest view the server computes.
  const library = useTeam((state) => state.library);
  const error = useTeam((state) => state.error);
  const version = useTeam((state) => state.version);
  const input = useRef<HTMLInputElement>(null);
  const load = useCallback(() => useTeam.getState().refresh(true), []);
  const poll = useCallback(() => useTeam.getState().refresh(), []);
  // This page loads people and the review queue itself: the side bar takes them from here rather than asking twice.
  useEffect(() => {
    const detach = useTeam.getState().attach();
    void load();
    return detach;
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
  usePolling(poll, interval);

  const picker = (
    <FileInput
      ref={input}
      label="选择录音文件"
      multiple
      onFiles={(files) => void add(files)}
    />
  );
  const fresh = library !== null && library.recordings.length === 0;
  const drop = (
    <FileDrop
      label="添加录音"
      size="lg"
      title="把会议录音拖到这里"
      inputLabel="选择录音文件"
      onFiles={(files) => void add(files)}
      hint="音频、视频都行，一次可以选多个。团队里参会的人也能看到。"
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
            <Stack as="header" gap={2}>
              <Heading level={2} size="display" align="center">
                从一段会议录音开始
              </Heading>
              <Text tone="secondary" align="center">
                不用先建档。传上来以后，系统分出每个人、认出已知的人，新出现的人自动建档。
              </Text>
            </Stack>
            {drop}
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
            <Card as="section" aria-label="邀请同事" variant="outline">
              <Row justify="between" wrap gap={4}>
                <Stack gap={0}>
                  <Text weight="semibold">请同事来认自己</Text>
                  <Text size="sm" tone="secondary">
                    他们登录后听几句就能确认哪段是自己，分身更准，你也少确认几次。
                  </Text>
                </Stack>
                <Button variant="secondary" onClick={copyInvite}>
                  复制邀请链接
                </Button>
              </Row>
            </Card>
          </>
        ) : (
          <>
            <Toolbar as="header" gap={4} align="end">
              <Heading level={2} size="display">
                团队
              </Heading>
              <Button onClick={() => input.current?.click()}>
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
