import { useCallback } from 'react';
import { useNavigate } from 'react-router';
import { isTranscript } from '../../features/library/ImportTranscript';
import { useUploadStore } from '../../stores/uploads';

/**
 * What the side bar's button and a drop anywhere do with the files they are given: recordings join the app's uploads,
 * a transcript goes to the library, whose page looks at it before it is brought in.
 */
export function useTakeFiles() {
  const navigate = useNavigate();
  return useCallback(
    (files: File[]) => {
      const texts = files.filter(isTranscript);
      if (texts.length) {
        useUploadStore.getState().holdTranscripts(texts);
        void navigate('/library');
      }
      void useUploadStore
        .getState()
        .add(files.filter((file) => !isTranscript(file)));
    },
    [navigate],
  );
}
