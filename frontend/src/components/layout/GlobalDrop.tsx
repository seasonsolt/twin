import { useEffect, useState } from 'react';
import { DropOverlay, toast } from '../ui';
import { useUploadStore } from '../../stores/uploads';
import { useTakeFiles } from './useTakeFiles';

const carriesFiles = (event: DragEvent) =>
  !!event.dataTransfer?.types.includes('Files');

/**
 * Recordings can be dropped anywhere on the page: they join the app's uploads, the same ones the library's button
 * starts. A drop area of a page that takes the files itself (it calls ``preventDefault``) keeps them, and the
 * overlay steps aside there.
 */
export function GlobalDrop() {
  const [over, setOver] = useState(false);
  const take = useTakeFiles();
  // What the uploads have to say (a file skipped, one a colleague sent first) is said here once, wherever the files
  // came from, and not left standing for the next page to show.
  useEffect(
    () =>
      useUploadStore.subscribe((state, before) => {
        if (!state.notice || state.notice === before.notice) return;
        toast(state.notice, 'info');
        useUploadStore.setState({ notice: '' });
      }),
    [],
  );
  useEffect(() => {
    const hover = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      if (event.defaultPrevented) setOver(false);
      else {
        // Without this the browser opens the file instead of dropping it.
        event.preventDefault();
        // A page with a drop area of its own shows where the files go: nothing is drawn over it.
        setOver(!document.querySelector('[data-drop-area]'));
      }
    };
    const leave = (event: DragEvent) => {
      // Leaving the window itself, not moving from one element to another.
      if (event.relatedTarget === null) setOver(false);
    };
    const drop = (event: DragEvent) => {
      setOver(false);
      if (!carriesFiles(event) || event.defaultPrevented) return;
      event.preventDefault();
      take(Array.from(event.dataTransfer?.files ?? []));
    };
    const end = () => setOver(false);
    window.addEventListener('dragenter', hover);
    window.addEventListener('dragover', hover);
    window.addEventListener('dragleave', leave);
    window.addEventListener('drop', drop);
    window.addEventListener('dragend', end);
    return () => {
      window.removeEventListener('dragenter', hover);
      window.removeEventListener('dragover', hover);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('drop', drop);
      window.removeEventListener('dragend', end);
    };
  }, [take]);
  return over ? <DropOverlay title="松开即可上传会议录音" /> : null;
}
