import { useEffect, useRef } from 'react';
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
import { SidebarAccount } from '../components/layout/Sidebar';
import { basePath } from '../lib/base';
import { useMobile } from '../lib/useMobile';
import { usePolling } from '../lib/usePolling';
import { LegacyTodo, Team } from '../features/library/Team';
import { UploadList } from '../features/library/UploadList';
import { useLibraryFeed } from '../features/library/useLibraryFeed';
import { useUploads } from '../features/library/useUploads';
import { useAuth } from '../stores/auth';
import { useTeam } from '../stores/team';

const STEPS = ['转写分人', '认人', '建分身'];

/** The site's address, to send to colleagues so they can sign in and recognise themselves in the meetings. */
function copyInvite() {
  const link = `${window.location.origin}${basePath()}/`;
  void navigator.clipboard.writeText(link).then(
    () => toast('邀请链接已复制，可以发给同事', 'success'),
    () => toast(link, 'info', 15000),
  );
}

/** The account's start page: the people found in its meeting recordings, and uploading. With no recording yet, it
 * is the way to the first one, with whoever is on the team already (twins made by hand) below. The old address of
 * the inbox leads there at once, without waiting for the library. */
export function Home() {
  return (
    <LegacyTodo>
      <TeamPage />
    </LegacyTodo>
  );
}

function TeamPage() {
  const { library, error, version, load, poll } = useLibraryFeed();
  const input = useRef<HTMLInputElement>(null);
  const mobile = useMobile();
  const { add, uploading, notice, unfinished, stop } = useUploads(
    () => void load(),
  );
  const busy = uploading || !!library?.pending;
  // Colleagues recognise themselves in the meetings by signing in with the company account.
  const inviting = useAuth(
    (state) =>
      !!state.identity?.auth_enabled && state.identity.provider === 'sso',
  );
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
  // With no recording the page lists no one, and the side bar, leaving people to the page, would count no one either.
  useEffect(() => {
    if (fresh && !useTeam.getState().people)
      void useTeam
        .getState()
        .refreshPeople()
        .catch(() => {});
  }, [fresh]);
  const drop = (
    <FileDrop
      label="添加录音"
      size="lg"
      title="把会议录音拖到这里"
      inputLabel="选择录音文件"
      onFiles={(files) => void add(files)}
      hint="音频、视频，可多选"
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
        {library && !library.asr && <Notice>转写服务未配置，录音先排队</Notice>}
        {!library ? (
          <Skeleton className="h-64" />
        ) : fresh ? (
          <>
            <Stack as="header" gap={2}>
              <Heading level={1} size="display" align="center">
                从一段会议录音开始
              </Heading>
            </Stack>
            {drop}
            <UploadList
              picks={unfinished}
              uploading={uploading}
              onStop={stop}
            />
            <Grid as="ol" columns={3} aria-label="接下来会发生什么">
              {STEPS.map((title, i) => (
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
                </Card>
              ))}
            </Grid>
            {inviting && (
              <Card as="section" aria-label="邀请同事" variant="outline">
                <Row justify="between" wrap gap={4}>
                  <Text weight="semibold">请同事登录认自己</Text>
                  <Button variant="secondary" onClick={copyInvite}>
                    复制邀请链接
                  </Button>
                </Row>
              </Card>
            )}
            {/* Twins made by hand, and the deleted ones to bring back, are there before any recording is. */}
            <Team
              quietWhenEmpty
              version={version}
              recordings={library.recordings}
              onReload={load}
            />
          </>
        ) : (
          <>
            <Toolbar as="header" gap={4} align="end">
              <Heading level={1} size="display">
                团队
              </Heading>
              {/* The side bar has the button; a phone has no side bar. */}
              {mobile && (
                <Button onClick={() => input.current?.click()}>
                  <Upload aria-hidden className="size-5" />
                  上传会议录音
                </Button>
              )}
              {mobile && picker}
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
            />
          </>
        )}
        {/* The side bar, and the account in it, is not there on a phone: sign-out and the palette are here. */}
        {mobile && library && <SidebarAccount />}
      </Page>
    </div>
  );
}
