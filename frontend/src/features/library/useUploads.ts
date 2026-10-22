import { useEffect, useRef } from 'react';
import { useUploadStore } from '../../stores/uploads';

export type { Pick } from '../../stores/uploads';

/** The app's library uploads seen from a page: ``changed`` runs after each file is filed or fails, so the page
 * reloads what it shows. The uploads themselves belong to the whole app and go on when the page is left. */
export function useUploads(changed: () => void) {
  const picks = useUploadStore((state) => state.picks);
  const uploading = useUploadStore((state) => state.uploading);
  const notice = useUploadStore((state) => state.notice);
  const add = useUploadStore((state) => state.add);
  const stop = useUploadStore((state) => state.stop);
  const changes = useUploadStore((state) => state.changes);
  const latest = useRef(changed);
  const seen = useRef(changes);
  useEffect(() => {
    latest.current = changed;
  }, [changed]);
  useEffect(() => {
    if (changes === seen.current) return;
    seen.current = changes;
    latest.current();
  }, [changes]);
  return {
    add,
    uploading,
    notice,
    unfinished: picks.filter((p) => !p.done),
    stop,
  };
}
