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
import { Placeholder } from './pages/Placeholder';
import './design/tokens.css';

const Chat = lazy(() =>
  import('./pages/Chat').then((module) => ({ default: module.Chat })),
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
                {['questionnaire', 'persona', 'sources', 'identity'].map(
                  (route) => (
                    <Route
                      key={route}
                      path={route}
                      element={<Placeholder route={route} />}
                    />
                  ),
                )}
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
