import { lazy, Suspense } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router';
import { MotionConfig } from 'motion/react';
import { AppShell } from './components/layout/AppShell';
import { useCanManage } from './stores/personas';
import { AuthGate } from './features/auth/AuthGate';
import {
  ConfirmProvider,
  Skeleton,
  ToastViewport,
  TooltipProvider,
} from './components/ui';

const Twins = lazy(() =>
  import('./pages/Twins').then((module) => ({ default: module.Twins })),
);
const Chat = lazy(() =>
  import('./pages/Chat').then((module) => ({ default: module.Chat })),
);
const Profile = lazy(() =>
  import('./pages/Profile').then((module) => ({ default: module.Profile })),
);
const Questionnaire = lazy(() =>
  import('./pages/Questionnaire').then((module) => ({
    default: module.Questionnaire,
  })),
);
const Ledger = lazy(() =>
  import('./pages/Ledger').then((module) => ({ default: module.Ledger })),
);
const Work = lazy(() =>
  import('./pages/Work').then((module) => ({ default: module.Work })),
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

export function App() {
  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={300}>
        <ConfirmProvider>
          <AuthGate>
            <HashRouter>
              <Suspense fallback={<Skeleton className="h-40" />}>
                <Routes>
                  <Route element={<AppShell />}>
                    <Route index element={<Start />} />
                    <Route path="team" element={<Home />} />
                    <Route path="twins" element={<Twins />} />
                    <Route path="library" element={<Library />} />
                    <Route
                      path="library/:recordingId"
                      element={<Recording />}
                    />
                    <Route path="chat" element={<Chat />} />
                    <Route path="work" element={<Work />} />
                    <Route path="profile" element={<Profile />} />
                    <Route path="ledger" element={<Ledger />} />
                    <Route
                      path="memories"
                      element={
                        <Navigate to="/profile?section=memories" replace />
                      }
                    />
                    <Route
                      path="about"
                      element={<Navigate to="/profile" replace />}
                    />
                    <Route
                      path="sources"
                      element={
                        <Navigate to="/profile?section=memories" replace />
                      }
                    />
                    <Route
                      path="persona"
                      element={<Navigate to="/profile" replace />}
                    />
                    <Route
                      path="identity"
                      element={<Navigate to="/profile" replace />}
                    />
                    <Route path="questionnaire" element={<Questionnaire />} />
                    <Route path="gallery" element={<Gallery />} />
                    <Route path="*" element={<Navigate to="/chat" replace />} />
                  </Route>
                </Routes>
              </Suspense>
            </HashRouter>
          </AuthGate>
          <ToastViewport />
        </ConfirmProvider>
      </TooltipProvider>
    </MotionConfig>
  );
}
