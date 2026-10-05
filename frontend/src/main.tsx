import { lazy, StrictMode, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter, Navigate, Route, Routes } from 'react-router';
import { MotionConfig } from 'motion/react';
import { AppShell } from './components/layout/AppShell';
import {
  ConfirmProvider,
  Skeleton,
  ToastViewport,
  TooltipProvider,
} from './components/ui';
import './design/tokens.css';

const Chat = lazy(() =>
  import('./pages/Chat').then((module) => ({ default: module.Chat })),
);
const Sources = lazy(() =>
  import('./pages/Sources').then((module) => ({ default: module.Sources })),
);
const Profile = lazy(() =>
  import('./pages/Profile').then((module) => ({ default: module.Profile })),
);
const Questionnaire = lazy(() =>
  import('./pages/Questionnaire').then((module) => ({
    default: module.Questionnaire,
  })),
);
const Identity = lazy(() =>
  import('./pages/Identity').then((module) => ({ default: module.Identity })),
);
const Gallery = lazy(() =>
  import('./pages/Gallery').then((module) => ({ default: module.Gallery })),
);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={300}>
        <ConfirmProvider>
          <HashRouter>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<Navigate to="/chat" replace />} />
                <Route
                  path="chat"
                  element={
                    <Suspense fallback={<Skeleton className="h-40" />}>
                      <Chat />
                    </Suspense>
                  }
                />
                <Route
                  path="sources"
                  element={
                    <Suspense fallback={<Skeleton className="h-40" />}>
                      <Sources />
                    </Suspense>
                  }
                />
                <Route
                  path="persona"
                  element={
                    <Suspense fallback={<Skeleton className="h-40" />}>
                      <Profile />
                    </Suspense>
                  }
                />
                <Route
                  path="questionnaire"
                  element={
                    <Suspense fallback={<Skeleton className="h-40" />}>
                      <Questionnaire />
                    </Suspense>
                  }
                />
                <Route
                  path="identity"
                  element={
                    <Suspense fallback={<Skeleton className="h-40" />}>
                      <Identity />
                    </Suspense>
                  }
                />
                <Route
                  path="gallery"
                  element={
                    <Suspense fallback={<Skeleton className="h-40" />}>
                      <Gallery />
                    </Suspense>
                  }
                />
                <Route path="*" element={<Navigate to="/chat" replace />} />
              </Route>
            </Routes>
          </HashRouter>
          <ToastViewport />
        </ConfirmProvider>
      </TooltipProvider>
    </MotionConfig>
  </StrictMode>,
);
