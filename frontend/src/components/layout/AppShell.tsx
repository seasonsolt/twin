import { lazy, Suspense, useEffect, useState } from 'react';
import { Navigate, useLocation, useNavigate, useOutlet } from 'react-router';
import { usePersonaId, usePersonaState } from '../../lib/usePersonaState';
import { startStatusPolling, useStatus } from '../../stores/status';
import { startSystemPolling } from '../../stores/system';
import { Settings } from '../../features/settings/Settings';
import { Will } from '../../features/will/Will';
import {
  Card,
  Heading,
  Stack,
  PlainButton,
  Row,
  Skeleton,
  SkipLink,
  Text,
  TextLink,
} from '../ui';
import { PageTransition } from '../motion';
import { useMobile } from '../../lib/useMobile';
import { api, ApiError } from '../../lib/api';
import { useCanManage, useManagesCurrent } from '../../stores/access';
import { awaitsApproval, usePersonas, useTrial } from '../../stores/personas';
import { useWelcome } from '../../stores/welcome';
import { BottomTabs, Sidebar, visitorRoutes } from './Sidebar';
import { GlobalDrop } from './GlobalDrop';
import { NewTwinForm, NewTwinHost } from './NewTwin';
import { useAuth, usePersonaEdition } from '../../stores/auth';
import { StageHeader } from './StageHeader';
import type { ShellContext } from './shellContext';
const Welcome = lazy(() =>
  import('../../features/auth/Welcome').then((module) => ({
    default: module.Welcome,
  })),
);

// Pages laid out as a conversation (stage, thread, pinned composer), full width and without a page transition.
const conversationRoutes = new Set(['/chat']);
// Pages about the twin in view that only its own people may open (a colleague's public twin is for talking to).
const twinPages = new Set(['/commitments']);
// Pages that say themselves that there is no twin yet, in place of the new-twin card.
const ownEmpty = new Set(['/commitments']);

/** The old address of finding one's voice: the first step of the way in, taken up again. */
function VoiceAgain() {
  const navigate = useNavigate();
  useEffect(() => {
    useWelcome.getState().hearAgain();
    void navigate('/welcome', { replace: true });
  }, [navigate]);
  return null;
}

export function AppShell() {
  const personaId = usePersonaId();
  const mobile = useMobile();
  const { error } = useStatus();
  const location = useLocation();
  const conversation = conversationRoutes.has(location.pathname);
  // Account-level pages: not about the current twin, so no twin check or twin tabs.
  const twinLevel =
    location.pathname === '/team' ||
    location.pathname.startsWith('/team/') ||
    location.pathname === '/library' ||
    location.pathname.startsWith('/library/') ||
    location.pathname === '/inbox';
  const onWelcome = location.pathname === '/welcome';
  const canManage = useCanManage();
  const persona = usePersonaEdition();
  const [checked, setChecked] = useState(false);
  const [noPersona, setNoPersona] = usePersonaState(false);
  const outlet = useOutlet({ noTwin: noPersona } satisfies ShellContext);
  useEffect(startStatusPolling, [personaId]);
  const admin = useAuth((state) => state.identity?.admin);
  // Signed in through the company login: look for them in colleagues' meetings before an empty twin.
  const address = useAuth(
    (state) => state.identity?.address || state.identity?.account,
  );
  const voiceDone = useWelcome((state) => state.voiceDone);
  const claimDone = useWelcome((state) => state.claimDone);
  const again = useWelcome((state) => state.again);
  const after = useWelcome((state) => state.after);
  useEffect(() => (admin ? startSystemPolling() : undefined), [admin]);
  // A twin a colleague made for this person comes first: until they have looked at it, it answers nobody else.
  const waiting = usePersonas((state) => state.items.find(awaitsApproval));
  const trial = useTrial();
  // Trying it out in chat first: the page asking for the go-ahead steps aside there, and only there.
  const trying =
    !!waiting && trial.id === waiting.id && location.pathname === '/chat';
  // Until the go-ahead step is passed (or left for later): after that the person is free to look at any twin.
  useEffect(() => {
    if (waiting && !claimDone && waiting.id !== personaId)
      void usePersonas.getState().switchTo(waiting.id);
  }, [waiting, claimDone, personaId]);
  // The page about one twin's commitments is for a twin the person looks after: standing on a colleague's public twin
  // from the conversation, they go on to one of their own rather than to an error.
  const manages = useManagesCurrent();
  const pageOfOwnTwin = twinPages.has(location.pathname);
  const own = usePersonas(
    (state) =>
      state.items.find(
        (item) => item.can_manage !== false && (item.is_default || item.mine),
      ) ?? state.items.find((item) => item.can_manage !== false),
  );
  useEffect(() => {
    if (canManage && !manages && pageOfOwnTwin && own)
      void usePersonas.getState().switchTo(own.id);
  }, [canManage, manages, pageOfOwnTwin, own]);
  // A company account that has not found itself yet starts at the way in whatever address it came by (the invitation
  // is the site's own), so whether there is a twin at all is asked on the team's pages too. The persona edition has no
  // meetings to look in.
  const finding = !!address && !voiceDone && !persona;
  const asking = !twinLevel || finding;
  useEffect(() => {
    if (!asking) return;
    const controller = new AbortController();
    // Getting to know a new twin happens in its chat (the setup card); here only whether there is a twin at all.
    void api('/api/identity', { signal: controller.signal })
      .catch((failure: unknown) => {
        if (
          !controller.signal.aborted &&
          failure instanceof ApiError &&
          failure.code === 'no_persona'
        ) {
          setNoPersona(true);
          void usePersonas
            .getState()
            .refresh()
            .catch(() => {});
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecked(true);
      });
    return () => controller.abort();
  }, [asking, personaId, setNoPersona]);
  const welcome = (step: 'voice' | 'claim') => (
    <Suspense fallback={<Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />}>
      {step === 'claim' && waiting ? (
        <Welcome step="claim" persona={waiting} />
      ) : (
        <Welcome step="voice" again={again} />
      )}
    </Suspense>
  );
  // Finding their voice again, asked for from the twin step (or by the old ``#/voice``): the first step of the way in.
  if (location.pathname === '/voice') return <VoiceAgain />;
  if (again)
    return onWelcome ? welcome('voice') : <Navigate to="/welcome" replace />;
  // The way in comes before the app: a twin made for this person first, else finding their voice in the meetings.
  if (waiting && !claimDone && !trying && location.pathname !== '/gallery')
    return onWelcome ? welcome('claim') : <Navigate to="/welcome" replace />;
  // A company account with no twin of its own yet, whether the list is empty or holds only twins others made public
  // (those are all it can talk to), finds itself first.
  if ((noPersona || !canManage) && finding)
    return onWelcome ? welcome('voice') : <Navigate to="/welcome" replace />;
  // A guest, who may only talk to twins, has the conversation alone: the team's places are not theirs by address
  // either.
  if (
    !canManage &&
    !onWelcome &&
    !visitorRoutes.has(location.pathname.slice(1))
  )
    return <Navigate to="/chat" replace />;
  // Nothing left to do on the way in: on to the app.
  if (onWelcome)
    return checked ? (
      <Navigate to={after} replace />
    ) : (
      <Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />
    );
  // No twin yet on a page about one (chat, work, profile): say so in the page and open the new-twin card right there,
  // in the workspace, rather than leaving it for a page of its own.
  const missing = noPersona && !twinLevel && !ownEmpty.has(location.pathname);
  // Until whether there is a twin is known, and while a page's code loads, only the page waits: the side bar and the
  // frame stay as they are, so moving between places never blanks the screen.
  const pending =
    !missing &&
    !(twinLevel && !finding) &&
    location.pathname !== '/gallery' &&
    !checked;
  const page = (
    <Suspense fallback={<Skeleton className="mx-auto mt-12 h-64 max-w-3xl" />}>
      {pending ? <Skeleton className="mx-auto mt-12 h-64 max-w-3xl" /> : outlet}
    </Suspense>
  );
  return (
    <div
      className={`app-shell flex min-h-dvh ${conversation ? 'conversation-shell' : ''}`}
    >
      <SkipLink target="main">跳至主内容</SkipLink>
      {!mobile && <Sidebar />}
      <div
        className={`app-column flex min-w-0 flex-1 flex-col ${conversation ? 'chat-app-column' : ''}`}
      >
        {error && !twinLevel && !missing && (
          <div
            role="alert"
            className="border-b border-danger/20 bg-danger/5 px-5 py-2"
          >
            <Text size="sm" tone="danger">
              {error}
            </Text>
          </div>
        )}
        {trying && (
          <div className="border-b border-info/20 bg-info/5 px-5 py-2">
            <Row justify="between" wrap gap={3}>
              <Text size="sm">试聊中：你点“没问题”之前，同事问不到它。</Text>
              <PlainButton onClick={() => trial.set(null)}>
                回去确认
              </PlainButton>
            </Row>
          </div>
        )}
        <main
          id="main"
          tabIndex={-1}
          className={`app-main mx-auto w-full flex-1 outline-none ${conversation ? 'chat-main' : 'max-w-6xl content-main'}`}
        >
          {conversation && !missing ? (
            page
          ) : (
            <PageTransition route={location.pathname}>
              {missing ? (
                // Nothing else here yet: the twin is made right on the page, with the navigation still around it.
                <div className="mx-auto w-full max-w-md px-4 py-12">
                  <Card as="section" aria-labelledby="no-twin-title">
                    <Stack gap={4}>
                      <Heading id="no-twin-title" level={1} size="title">
                        先新建一个分身
                      </Heading>
                      <NewTwinForm />
                      {address && (
                        <TextLink
                          size="sm"
                          onClick={() =>
                            useWelcome.getState().finishVoice(false)
                          }
                        >
                          其实开过会？回去再听一遍
                        </TextLink>
                      )}
                    </Stack>
                  </Card>
                </div>
              ) : location.pathname === '/gallery' ? (
                <>
                  <StageHeader />
                  <div className="page-content">{page}</div>
                </>
              ) : (
                page
              )}
            </PageTransition>
          )}
        </main>
      </div>
      {mobile && !twinLevel && <BottomTabs />}
      <Settings />
      <Will />
      {/* Dropped files go to the team's recording library, which the persona edition does not have. */}
      {canManage && !mobile && !persona && <GlobalDrop />}
      <NewTwinHost />
    </div>
  );
}
