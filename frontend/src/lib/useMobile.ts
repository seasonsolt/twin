import { useEffect, useState } from 'react';

function useMediaQuery(media: string) {
  const [matches, setMatches] = useState(
    () => window.matchMedia(media).matches,
  );
  useEffect(() => {
    const query = window.matchMedia(media);
    const change = () => setMatches(query.matches);
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, [media]);
  return matches;
}

export function useMobile() {
  return useMediaQuery('(max-width: 767px)');
}

export function useDesktop() {
  return useMediaQuery('(min-width: 1200px)');
}
