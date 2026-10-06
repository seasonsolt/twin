import { lazy, Suspense } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router';
import { MotionConfig } from 'motion/react';
import { usePersonas } from './stores/personas';
import { AppShell } from './components/layout/AppShell';
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
const Memories = lazy(() =>
  import('./pages/Memories').then((module) => ({ default: module.Memories })),
);
const About = lazy(() =>
  import('./pages/About').then((module) => ({ default: module.About })),
);
const Questionnaire = lazy(() =>
  import('./pages/Questionnaire').then((module) => ({
    default: module.Questionnaire,
  })),
);
const Gallery = lazy(() =>
  import('./pages/Gallery').then((module) => ({ default: module.Gallery })),
);

export function App() {
  const personaId = usePersonas((state) => state.id);
  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={300}>
        <ConfirmProvider>
          <AuthGate>
            <HashRouter>
              <Suspense fallback={<Skeleton className="h-40" />}>
                <Routes key={personaId}>
                  <Route element={<AppShell />}>
                    <Route index element={<Navigate to="/chat" replace />} />
                    <Route path="chat" element={<Chat />} />
                    <Route path="memories" element={<Memories />} />
                    <Route path="about" element={<About />} />
                    <Route
                      path="sources"
                      element={<Navigate to="/memories" replace />}
                    />
                    <Route
                      path="persona"
                      element={<Navigate to="/about" replace />}
                    />
                    <Route
                      path="identity"
                      element={<Navigate to="/about" replace />}
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
