// The page may be served under a path prefix (e.g. a reverse proxy at /twin/). Assets are relative to the page, and
// every request to the server goes through `withBase`, so one build works at / and under any prefix.
export function basePath(baseURI = document.baseURI) {
  return new URL('.', baseURI).pathname.replace(/\/$/u, '');
}

export function withBase(path: string, base = basePath()) {
  return path.startsWith('/') && !path.startsWith('//') ? base + path : path;
}
