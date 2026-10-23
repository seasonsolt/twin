import { lazy, Suspense, type ReactNode } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router';
import { MotionConfig } from 'motion/react';
import { AppShell } from './components/layout/AppShell';
import { useCanManage } from './stores/access';
import { featureOn, useAuth, type Feature } from './stores/auth';
import { AuthGate } from './features/auth/AuthGate';
import {
  ConfirmProvider,
  Skeleton,
  ToastViewport,
  TooltipProvider,
} from './components/ui';

const Chat = lazy(() =>
  import('./pages/Chat').then((module) => ({ default: module.Chat })),
);
const Member = lazy(() =>
  import('./pages/Member').then((module) => ({ default: module.Member })),
);
const ProfileRedirect = lazy(() =>
  import('./pages/ProfileRedirect').then((module) => ({
    default: module.ProfileRedirect,
  })),
);
const Commitments = lazy(() =>
  import('./pages/Commitments').then((module) => ({
    default: module.Commitments,
  })),
);
const Inbox = lazy(() =>
  import('./pages/Inbox').then((module) => ({ default: module.Inbox })),
);
const Library = lazy(() =>
  import('./pages/Library').then((module) => ({ default: module.Library })),
);
const Recording = lazy(() =>
  import('./pages/Recording').then((module) => ({ default: module.Recording })),
);
const Home = lazy(() =>
  import('./pages/Home').then((module) => ({ default: module.Home })),
);
const Gallery = lazy(() =>
  import('./pages/Gallery').then((module) => ({ default: module.Gallery })),
);

// Those who run the twins start from their team (no twin is set up first); a guest who may only talk to a twin
// starts in its chat.
function Start() {
  return <Navigate to={useCanManage() ? '/team' : '/chat'} replace />;
}

// A page an administrator switched off is not there: its address leads to chat, which always is.
function FeaturePage({
  feature,
  children,
}: {
  feature: Feature;
  children: ReactNode;
}) {
  const on = useAuth((state) => featureOn(state.identity, feature));
  return on ? children : <Navigate to="/chat" replace />;
}

// Work is a kind of message in the conversation now: the old address opens the conversation on it (or plain, where
// work is switched off).
export function WorkRedirect() {
  const on = useAuth((state) => featureOn(state.identity, 'work'));
  return <Navigate to={on ? '/chat?mode=task' : '/chat'} replace />;
}

export function App() {
  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={300}>
        <ConfirmProvider>
          <HashRouter>
            <AuthGate>
              <Suspense fallback={<Skeleton className="h-40" />}>
                <Routes>
                  <Route element={<AppShell />}>
                    <Route index element={<Start />} />
                    {/* The way in (finding their voice, then the twin made for them): AppShell frames it. */}
                    <Route path="welcome" element={null} />
                    <Route path="team" element={<Home />} />
                    <Route path="team/twin/:twinId" element={<Member />} />
                    <Route path="team/:id" element={<Member />} />
                    <Route
                      path="twins"
                      element={<Navigate to="/team" replace />}
                    />
                    <Route path="library" element={<Library />} />
                    <Route path="inbox" element={<Inbox />} />
                    {/* Finding one's voice is the way in's first step now: AppShell takes it there. */}
                    <Route path="voice" element={null} />
                    <Route
                      path="library/:recordingId"
                      element={<Recording />}
                    />
                    <Route path="chat" element={<Chat />} />
                    <Route path="work" element={<WorkRedirect />} />
                    {/* The old profile addresses lead to the member page of the twin in view. */}
                    <Route path="profile" element={<ProfileRedirect />} />
                    <Route
                      path="commitments"
                      element={
                        <FeaturePage feature="ledger">
                          <Commitments />
                        </FeaturePage>
                      }
                    />
                    {/* The ledger is the commitments of whoever is chosen there. */}
                    <Route
                      path="ledger"
                      element={<Navigate to="/commitments" replace />}
                    />
                    <Route
                      path="memories"
                      element={<ProfileRedirect section="memories" />}
                    />
                    <Route path="about" element={<ProfileRedirect />} />
                    <Route
                      path="sources"
                      element={<ProfileRedirect section="memories" />}
                    />
                    <Route path="persona" element={<ProfileRedirect />} />
                    <Route path="identity" element={<ProfileRedirect />} />
                    {/* The fixed questions became 补一补, on the member page. */}
                    <Route path="questionnaire" element={<ProfileRedirect />} />
                    <Route path="gallery" element={<Gallery />} />
                    <Route path="*" element={<Navigate to="/chat" replace />} />
                  </Route>
                </Routes>
              </Suspense>
            </AuthGate>
          </HashRouter>
          <ToastViewport />
        </ConfirmProvider>
      </TooltipProvider>
    </MotionConfig>
  );
}
