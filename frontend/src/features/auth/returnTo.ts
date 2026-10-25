/** Paths on this site only: never send the browser, or a form, to another origin. */
export const local = (path: string | null | undefined) =>
  path && path.startsWith('/') && !path.startsWith('//') ? path : '';

/**
 * The sign-in address for someone signed out at ``path``: it keeps the page they came for (a 请某某补充 or 问某某本人
 * link) so signing in goes back to it. The start page needs no keeping.
 */
export function loginPath(path: string) {
  const back = local(path);
  return back && back !== '/' && !back.startsWith('/login')
    ? `/login?next=${encodeURIComponent(back)}`
    : '/login';
}

const KEY = 'twin-return-to';
// The company sign-in leaves the page and comes back to the site's start: an attempt abandoned long ago is not kept.
const FRESH_MS = 10 * 60 * 1000;

/** Before leaving for the company sign-in, which comes back to the start page, remember where to go after it. */
export function rememberReturn(path: string) {
  const back = local(path);
  try {
    if (back)
      sessionStorage.setItem(KEY, JSON.stringify({ back, at: Date.now() }));
    else sessionStorage.removeItem(KEY);
  } catch {
    // Without storage the company sign-in lands on the start page, as it did before.
  }
}

/** The page remembered before the company sign-in, once; '' when there is none or it is stale. */
export function takeReturn() {
  try {
    const saved = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    if (!saved) return '';
    const { back, at } = JSON.parse(saved) as { back?: unknown; at?: unknown };
    return typeof back === 'string' &&
      typeof at === 'number' &&
      Date.now() - at < FRESH_MS
      ? local(back)
      : '';
  } catch {
    return '';
  }
}
