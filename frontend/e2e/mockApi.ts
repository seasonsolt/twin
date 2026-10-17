// Fixed answers to every API call the screenshot pages make: a small fictional team, so the pages look lived in and
// render the same on every run. Anything the pages ask for that is not listed here fails the test (see `missing`),
// so a new request is noticed instead of silently rendering an error state.
import type { Page, Route } from '@playwright/test';

/** The moment the pages think it is: relative times ("3 天前") and timers count from here. */
export const NOW = new Date('2026-10-17T10:00:00+08:00');

type Handler = (url: URL, route: Route) => unknown;
const reply = (body: unknown) => () => body;

const personas = [
  {
    id: 'default',
    name: '林舟',
    avatar_url: null,
    avatar_preset: 'chestnut',
    sources: 12,
    created_at: '2026-09-01T02:00:00Z',
    is_default: true,
    can_manage: true,
  },
  {
    id: 'p-qinghe',
    name: '许清禾',
    avatar_url: null,
    avatar_preset: 'wave',
    sources: 5,
    created_at: '2026-09-12T02:00:00Z',
    is_default: false,
    can_manage: true,
  },
  {
    id: 'p-shiyan',
    name: '周石言',
    avatar_url: null,
    avatar_preset: 'stone',
    sources: 3,
    created_at: '2026-09-20T02:00:00Z',
    is_default: false,
    can_manage: true,
  },
];

const egress = [
  {
    kind: 'llm',
    provider: 'openai-compatible',
    host: 'llm.example.com',
    external: true,
    declared: true,
  },
];

const status = {
  target_name: '林舟',
  counts: { sources: 12, items: 48 },
  memory_updating: false,
  kernel: {
    version: { schema: 1, prompt: 'persona-v6', taxonomy: 't3' },
    built: { schema: 1, prompt: 'persona-v6', taxonomy: 't3' },
    scope: 'none',
    pending_chunks: 0,
    state: 'ready',
  },
  llm: { provider: 'openai-compatible', model: 'example-model' },
  embed: { provider: 'ollama' },
  egress,
};

const identity = {
  name: '林舟',
  about:
    '产品负责人，带一个八人的小团队，做会议纪要和知识整理工具。喜欢先写清楚问题再动手。',
  name_source: 'user',
  onboarding_pending: false,
  aliases: ['小林'],
  voice: null,
  avatar: null,
  avatar_preset: 'chestnut',
  avatar_presets: [
    { id: 'chestnut', name: '栗' },
    { id: 'wave', name: '澜' },
    { id: 'bun', name: '禾' },
    { id: 'stone', name: '石' },
    { id: 'silver', name: '岚' },
  ],
  egress,
};

const capabilities = {
  available: false,
  video: { available: false },
  backend: null,
  avatar_preset: 'chestnut',
  avatar_presets: identity.avatar_presets,
  avatar_model: null,
  avatar_image: null,
};

const recordings = [
  {
    id: 'r-weekly',
    filename: '2026-10-15 产品周会.m4a',
    size: 48_000_000,
    kind: 'audio',
    status: 'ready',
    error: '',
    duration_s: 3420,
    transcribed_s: 3420,
    speakers: 4,
    segments: 312,
    created_at: '2026-10-15T08:00:00Z',
    people: ['林舟', '许清禾', '周石言'],
    unsettled: 1,
  },
  {
    id: 'r-review',
    filename: '2026-10-12 需求评审.mp4',
    size: 210_000_000,
    kind: 'video',
    status: 'ready',
    error: '',
    duration_s: 2700,
    transcribed_s: 2700,
    speakers: 3,
    segments: 240,
    created_at: '2026-10-12T06:00:00Z',
    people: ['林舟', '许清禾'],
    unsettled: 0,
  },
  {
    id: 'r-retro',
    filename: '2026-10-16 迭代复盘.m4a',
    size: 30_000_000,
    kind: 'audio',
    status: 'transcribing',
    error: '',
    duration_s: 1800,
    transcribed_s: 720,
    speakers: 0,
    segments: 0,
    created_at: '2026-10-16T09:00:00Z',
    people: [],
    unsettled: 0,
  },
  {
    id: 'r-broken',
    filename: '电话会议.amr',
    size: 2_000_000,
    kind: 'audio',
    status: 'failed',
    error: '无法读取音频，请换一种格式再试',
    duration_s: null,
    transcribed_s: 0,
    speakers: 0,
    segments: 0,
    created_at: '2026-10-16T10:00:00Z',
    people: [],
    unsettled: 0,
  },
];

const people = [
  {
    id: 'u-linzhou',
    name: '林舟',
    persona_id: 'default',
    speakers: 6,
    seconds: 5400,
    samples: 3,
    updating: false,
    auto: false,
    gender: 'male',
    recording_id: 'r-weekly',
  },
  {
    id: 'u-qinghe',
    name: '许清禾',
    persona_id: 'p-qinghe',
    speakers: 4,
    seconds: 2600,
    samples: 3,
    updating: true,
    auto: false,
    gender: 'female',
    recording_id: 'r-weekly',
  },
  {
    id: 'u-shiyan',
    name: '周石言',
    persona_id: null,
    speakers: 2,
    seconds: 900,
    samples: 2,
    updating: false,
    auto: false,
    gender: '',
    recording_id: 'r-weekly',
  },
  {
    id: 'u-auto-1',
    name: '未命名 1',
    persona_id: null,
    speakers: 2,
    seconds: 420,
    samples: 1,
    updating: false,
    auto: true,
    gender: '',
    recording_id: 'r-weekly',
  },
];

const speaker = (
  id: string,
  seconds: number,
  extra: Record<string, unknown> = {},
) => ({
  id,
  seconds,
  decision: 'none',
  person_id: null,
  rejected: [],
  sample: false,
  auto: false,
  candidates: [],
  near: false,
  samples: 2,
  ...extra,
});

const weekly = {
  ...recordings[0],
  transcript_id: 't-weekly',
  revision: 3,
  speakers: [
    speaker('S1', 1500, {
      decision: 'confirmed',
      person_id: 'u-linzhou',
      auto: true,
      sample: true,
    }),
    speaker('S2', 980, {
      decision: 'confirmed',
      person_id: 'u-qinghe',
    }),
    speaker('S3', 640, {
      candidates: [
        { person_id: 'u-shiyan', name: '周石言', score: 0.71 },
        { person_id: 'u-qinghe', name: '许清禾', score: 0.52 },
      ],
      near: true,
    }),
    speaker('S4', 300, { decision: 'unknown' }),
  ],
  segments: [
    {
      start: 4,
      end: 12,
      speaker: 'S1',
      text: '我们先过一下上周的进展，再看这周要定的两件事。',
    },
    {
      start: 13,
      end: 25,
      speaker: 'S2',
      text: '导入那边已经支持文件夹了，大文件还要再测一轮。',
    },
    {
      start: 26,
      end: 34,
      speaker: 'S3',
      text: '测试环境周三之前能准备好，我来跟。',
    },
    { start: 35, end: 41, speaker: 'S1', text: '好，那发布时间先按下周二排。' },
    { start: 42, end: 50, speaker: 'S4', text: '我补充一下客户那边的反馈。' },
  ],
};

const conversation = {
  id: 'c-plan',
  title: '下周发布怎么安排',
  turns: [
    {
      id: 't1',
      role: 'user',
      content: '下周的发布你打算怎么安排？',
      timestamp: '2026-10-17T01:30:00Z',
    },
    {
      id: 't2',
      role: 'twin',
      content:
        '我会先把发布时间定在下周二，周三之前把测试环境准备好。大文件导入还要再测一轮，测完再决定要不要放进这次发布。',
      timestamp: '2026-10-17T01:30:08Z',
      reply: {
        reply:
          '我会先把发布时间定在下周二，周三之前把测试环境准备好。大文件导入还要再测一轮，测完再决定要不要放进这次发布。',
        citations: ['i-1'],
        confidence: 0.82,
        abstain: false,
        abstain_reason: '',
        retrieved_ids: ['i-1'],
        mode: 'grounded',
        elapsed_ms: 4200,
        completed_at: '2026-10-17T01:30:08Z',
        cited: [
          {
            id: 'i-1',
            kind: 'item',
            text: '发布前会先确认测试环境和回滚方案',
            facet: '工作方式',
            date: '2026-10-15',
          },
        ],
      },
    },
  ],
};

const history = [
  {
    id: 'c-plan',
    title: '下周发布怎么安排',
    updated_at: '2026-10-17T01:30:08Z',
    turns: 2,
    preview: '我会先把发布时间定在下周二……',
  },
  {
    id: 'c-hiring',
    title: '招聘面试的问题',
    updated_at: '2026-10-14T07:00:00Z',
    turns: 6,
    preview: '我一般会先问候选人最近做过的一件事……',
  },
];

const dimensions = [
  ['d1', '做事方式', 18],
  ['d2', '沟通风格', 12],
  ['d3', '价值观', 9],
  ['d4', '专业领域', 9],
] as const;

const itemSummary = {
  total: 48,
  conflicts: 1,
  dimensions: dimensions.map(([dimension_id, name, total]) => ({
    dimension_id,
    name,
    total,
  })),
};

const statements: [string, string, string, string][] = [
  ['d1', 'f-plan', '计划', '发布前会先确认测试环境和回滚方案'],
  ['d1', 'f-plan', '计划', '习惯把一周要定的事写在周会开头'],
  ['d1', 'f-decide', '怎么做决定', '拿不准的事先找最了解情况的人聊，再拍板'],
  ['d2', 'f-tone', '说话方式', '开会时先讲结论，再补原因'],
  ['d2', 'f-feedback', '反馈', '给同事反馈时会举具体的例子'],
  ['d3', 'f-care', '在意什么', '在意团队成员能按时下班'],
  ['d4', 'f-domain', '熟悉的领域', '熟悉会议纪要和知识库类产品'],
];
const items = statements.map(
  ([dimension_id, facet_id, facet_name, statement], i) => ({
    item_id: `i-${i + 1}`,
    dimension_id,
    dimension_name: dimensions.find(([id]) => id === dimension_id)![1],
    facet_id,
    facet_name,
    statement,
    extracted_statement: statement,
    applies_when: '',
    conflict: i === 3 ? '另一段录音里他说过会先讲背景' : '',
    occasions: 3 - (i % 3),
    review: i === 1 ? 'edited' : 'unreviewed',
    evidence: [
      {
        expression_id: `e-${i + 1}`,
        source_id: 's-weekly',
        source_kind: 'interview',
        quote: statement,
        date: '2026-10-15',
        own_words: i !== 5,
      },
    ],
  }),
);

const coverage = {
  taxonomy: 't3',
  as_of: '2026-10-17',
  level_labels: {
    '0': '还不了解',
    '1': '有一点',
    '2': '比较了解',
    '3': '很了解',
  },
  kind_labels: { chat: '聊天', document: '文档', interview: '访谈' },
  dimensions: dimensions.map(([dimension_id, name], i) => ({
    dimension_id,
    name,
    facets: 4,
    consented: 4,
    covered: 4 - i,
    sufficient: 3 - Math.min(i, 2),
    verified: 1,
    conflicts: i === 1 ? 1 : 0,
  })),
  facets: [],
  suggestions: [
    {
      facet_id: 'f-decide',
      name: '怎么做决定',
      reason: '只在一段录音里提到过',
      sources: ['interview'],
    },
  ],
};

const memory = (
  source_id: string,
  title: string,
  status: string,
  extra: Record<string, unknown> = {},
) => ({
  source_id,
  title,
  first_date: '2026-10-15',
  detected_kind_label: '会议录音',
  status,
  remembered: status === 'remembered' ? 6 : 0,
  ...extra,
});

const memories = [
  memory('s-weekly', '2026-10-15 产品周会', 'needs_speaker', {
    kind: 'audio',
    duration_s: 3420,
  }),
  memory('s-notes', '发布流程笔记.md', 'remembered', {
    detected_kind_label: '文档',
  }),
  memory('s-chat', '和清禾的聊天记录.txt', 'remembered', {
    detected_kind_label: '聊天记录',
    remembered: 11,
  }),
  memory('s-retro', '迭代复盘.m4a', 'transcribing', {
    kind: 'audio',
    duration_s: 1800,
    transcribed_s: 720,
  }),
];

const sourceSummary = {
  total: memories.length,
  duration_s: 5220,
  needs_speaker: 1,
  busy: 1,
  remembered: 2,
  nothing_found: 0,
  failed: 0,
};

// The GPU health card administrators see on the start page: one service healthy all day, one with a bad hour.
const gpuNow = NOW.getTime() / 1000;
const gpuHours = (failing: number) =>
  Array.from({ length: 24 }, (_, i) => ({
    start: gpuNow - (24 - i) * 3600,
    checks: 60,
    failures: i === failing ? 12 : 0,
  }));
const gpu = {
  now: gpuNow,
  interval: 60,
  window: 86400,
  services: [
    {
      key: 'asr',
      name: '转写服务',
      address: '127.0.0.1:18790',
      latest: {
        at: gpuNow - 30,
        ok: true,
        latency_ms: 12,
        reason: null,
        version: '1.2',
        device: 'cuda',
        busy: false,
        model: null,
        embeddings_ms: null,
      },
      since: gpuNow - 86400,
      checks: 1440,
      failures: 0,
      availability: 1,
      first_at: gpuNow - 86400,
      last_failure: null,
      buckets: gpuHours(-1),
    },
    {
      key: 'embed',
      name: '文本向量服务',
      address: '127.0.0.1:11434',
      latest: {
        at: gpuNow - 30,
        ok: true,
        latency_ms: 20,
        reason: null,
        version: null,
        device: null,
        busy: null,
        model: 'bge-m3',
        embeddings_ms: 35,
      },
      since: gpuNow - 7 * 3600,
      checks: 1440,
      failures: 12,
      availability: 1428 / 1440,
      first_at: gpuNow - 86400,
      last_failure: { at: gpuNow - 7 * 3600 - 600, reason: '连接超时' },
      buckets: gpuHours(16),
    },
  ],
};

const handlers: Record<string, Handler> = {
  'GET /api/whoami': reply({ email: null, admin: true, auth_enabled: false }),
  'GET /api/admin/gpu': reply(gpu),
  'GET /api/personas': reply(personas),
  'GET /api/status': reply(status),
  'GET /api/identity': reply(identity),
  'GET /api/media/capabilities': reply(capabilities),
  'GET /api/library': reply({
    recordings,
    pending: 0,
    max_pending: 20,
    asr: true,
    capacity: {
      free_bytes: 120 * 1024 ** 3,
      arriving_bytes: 0,
      arriving: 0,
      headroom_bytes: 20 * 1024 ** 3,
    },
  }),
  'GET /api/library/people': reply({ items: people }),
  'GET /api/library/review': reply({
    items: [
      {
        ...weekly.speakers[2],
        recording_id: 'r-weekly',
        filename: weekly.filename,
      },
    ],
  }),
  'GET /api/library/recordings/r-weekly': reply(weekly),
  'GET /api/persona/state': reply({ stale: false }),
  'GET /api/conversations': reply(history),
  'GET /api/conversations/c-plan': reply(conversation),
  'GET /api/persona/coverage': reply(coverage),
  'GET /api/persona/items/summary': reply(itemSummary),
  'GET /api/persona/items': (url) => {
    const wanted = url.searchParams.getAll('dimension');
    const rows = items.filter(
      (item) => !wanted.length || wanted.includes(item.dimension_id),
    );
    return { items: rows, total: rows.length };
  },
  'GET /api/persona/processing': reply({ state: 'idle' }),
  'GET /api/persona/sources': (url) =>
    url.searchParams.get('limit') === '0'
      ? { items: [], total: memories.length, summary: sourceSummary }
      : {
          items: memories,
          total: memories.length,
          summary: sourceSummary,
          ...(url.searchParams.get('attention') === 'true'
            ? {
                attention: memories.filter(
                  (row) => row.status !== 'remembered',
                ),
              }
            : {}),
        },
};

/** Media the pages point <audio>/<img> at: an empty answer keeps the element in its idle state. */
const media = /\/samples\/\d+$|\/api\/me\/|\/api\/media\/(avatar|voice)/u;

export async function mockApi(page: Page, missing: string[]) {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const handler = handlers[`${request.method()} ${url.pathname}`];
    if (handler) return route.fulfill({ json: await handler(url, route) });
    if (media.test(url.pathname)) return route.fulfill({ status: 404 });
    missing.push(`${request.method()} ${url.pathname}${url.search}`);
    return route.fulfill({ status: 404, json: { detail: '找不到请求的资源' } });
  });
}
