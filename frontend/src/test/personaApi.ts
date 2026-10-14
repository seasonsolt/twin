// Test doubles for the paged persona endpoints: they page, filter and count fixture rows the way the server does.

type Row = Record<string, unknown>;

const path = (url: string) => url.split('?')[0];
const params = (url: string) => new URLSearchParams(url.split('?')[1] ?? '');

export const isSourcesUrl = (url: string) =>
  path(url) === '/api/persona/sources';
export const isItemsUrl = (url: string) => path(url) === '/api/persona/items';
export const isItemSummaryUrl = (url: string) =>
  path(url) === '/api/persona/items/summary';

const mediaPending = ['queued', 'extracting', 'transcribing'];
const attention = [...mediaPending, 'failed', 'needs_asr', 'needs_speaker'];

export function sourcesPage(url: string, fixtures: readonly object[]) {
  const rows = fixtures as Row[];
  const query = params(url);
  const limit = Number(query.get('limit') ?? 50);
  const offset = Number(query.get('offset') ?? 0);
  const statuses = query.getAll('status');
  const matching = rows.filter(
    (row) =>
      (!statuses.length || statuses.includes(String(row.status))) &&
      (query.get('candidates') !== 'true' ||
        Number(row.voice_candidates ?? 0) > 0 ||
        Number(row.portrait_candidates ?? 0) > 0),
  );
  const busy = (row: Row) =>
    mediaPending.includes(String(row.status)) ||
    row.status === 'processing' ||
    (!!row.candidates_pending &&
      !['failed', 'needs_asr', 'needs_speaker'].includes(String(row.status)));
  return {
    items: matching.slice(offset, offset + limit),
    total: matching.length,
    summary: {
      total: rows.length,
      duration_s: rows.reduce(
        (sum, row) => sum + Number(row.duration_s ?? 0),
        0,
      ),
      needs_speaker: rows.filter((row) => row.status === 'needs_speaker')
        .length,
      busy: rows.filter(busy).length,
    },
    ...(query.get('attention') === 'true'
      ? {
          attention: rows
            .filter((row) => attention.includes(String(row.status)))
            .slice(0, 50),
        }
      : {}),
  };
}

const evidenceOf = (row: Row) =>
  (row.evidence as { source_id: string; quote: string }[] | undefined) ?? [];

export function itemsPage(
  url: string,
  fixtures: readonly object[],
  sources: Record<string, object> = {},
) {
  const rows = fixtures as Row[];
  const query = params(url);
  const limit = Number(query.get('limit') ?? 50);
  const offset = Number(query.get('offset') ?? 0);
  const dimensions = query.getAll('dimension');
  const review = query.get('review');
  const needle = (query.get('q') ?? '').toLocaleLowerCase();
  const source = query.get('source_id');
  let matching = rows.filter(
    (row) =>
      (query.get('include_rejected') === 'true' || review
        ? true
        : row.review !== 'rejected') &&
      (!dimensions.length || dimensions.includes(String(row.dimension_id))) &&
      (!review || row.review === review) &&
      (!needle ||
        String(row.statement).toLocaleLowerCase().includes(needle) ||
        evidenceOf(row).some((e) =>
          e.quote.toLocaleLowerCase().includes(needle),
        )) &&
      (!source || evidenceOf(row).some((e) => e.source_id === source)),
  );
  if (query.get('sort') === 'evidence')
    matching = [...matching].sort(
      (a, b) => evidenceOf(b).length - evidenceOf(a).length,
    );
  const page = matching.slice(offset, offset + limit);
  const cited = new Set(
    page.flatMap((row) => evidenceOf(row)).map((e) => e.source_id),
  );
  return {
    items: page,
    total: matching.length,
    ...(query.get('with_sources') === 'true'
      ? {
          sources: Object.fromEntries(
            Object.entries(sources).filter(([id]) => cited.has(id)),
          ),
        }
      : {}),
  };
}

export function itemSummary(fixtures: readonly object[]) {
  const rows = fixtures as Row[];
  const shown = rows.filter((row) => row.review !== 'rejected');
  const ids = [...new Set(shown.map((row) => String(row.dimension_id)))].sort();
  const dimensions = ids.map((id) => {
    const inDimension = shown.filter((row) => row.dimension_id === id);
    return {
      dimension_id: id,
      name: String(inDimension[0].dimension_name ?? id),
      total: inDimension.length,
      unreviewed: inDimension.filter((row) => row.review === 'unreviewed')
        .length,
    };
  });
  return {
    total: shown.length,
    unreviewed: shown.filter((row) => row.review === 'unreviewed').length,
    dimensions,
  };
}
