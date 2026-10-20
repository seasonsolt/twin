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
    unsettled: 2,
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
    speaker_id: 'S1',
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
    speaker_id: 'S2',
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
    speaker_id: 'S3',
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
    speaker_id: 'S4',
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

export const weekly = {
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
    speaker('S4', 300),
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
  ['D1', '经历与身份', 6],
  ['D2', '看重什么', 12],
  ['D3', '怎么做决定', 9],
  ['D4', '怎么思考', 5],
  ['D5', '擅长什么', 8],
  ['D6', '说话方式', 6],
  ['D7', '和人相处', 2],
  ['D8', '最近在关注', 0],
  ['D9', '生活与喜好', 0],
] as const;

const itemSummary = {
  total: 48,
  conflicts: 1,
  dimensions: dimensions
    .filter(([, , total]) => total > 0)
    .map(([dimension_id, name, total]) => ({ dimension_id, name, total })),
};

const statements: [string, string, string, string, string][] = [
  ['D2', '2.1', '核心价值排序', '在意团队成员能按时下班', '排期紧的时候'],
  ['D2', '2.3', '做事的原则', '答应别人的事一定按时给回复', ''],
  ['D2', '2.3', '做事的原则', '发布前会先确认测试环境和回滚方案', '上线前'],
  ['D3', '3.3', '依据偏好', '拿不准的事先找最了解情况的人聊，再拍板', ''],
  ['D3', '3.4', '常见取舍', '赶进度时宁可砍范围，也不降低质量', '临近发布'],
  ['D6', '6.2', '句式与结构', '开会时先讲结论，再补原因', ''],
  ['D5', '5.1', '拿手的事', '熟悉会议纪要和知识库类产品', ''],
];
const items = statements.map(
  ([dimension_id, facet_id, facet_name, statement, applies_when], i) => ({
    item_id: `i-${i + 1}`,
    dimension_id,
    dimension_name: dimensions.find(([id]) => id === dimension_id)![1],
    facet_id,
    facet_name,
    statement,
    extracted_statement: statement,
    applies_when,
    conflict: i === 4 ? '另一段录音里他说过赶工时可以先上线再修' : '',
    occasions: 7 - i,
    review: i === 1 ? 'edited' : 'unreviewed',
    evidence: [
      {
        expression_id: `e-${i + 1}`,
        source_id: 's-weekly',
        source_kind: 'interview',
        quote: statement,
        date: '2026-10-15',
        own_words: i !== 3,
      },
    ],
  }),
);

// Facet levels per dimension, in facet order (see docs/PERSONA_DIMENSIONS.md).
const facetLevels: [string, string, number][] = [
  ['1.1', '现在的身份', 2],
  ['1.2', '重要经历与转折', 1],
  ['1.3', '常讲的经历与故事', 0],
  ['1.4', '和身边人的协作', 1],
  ['2.1', '核心价值排序', 3],
  ['2.2', '不愿放弃的底线', 2],
  ['2.3', '做事的原则', 3],
  ['2.4', '怎么看待人与信任', 1],
  ['3.1', '风险偏好', 2],
  ['3.3', '依据偏好', 2],
  ['3.4', '常见取舍', 2],
  ['3.6', '做决定的节奏', 0],
  ['4.1', '拆解问题的方式', 2],
  ['4.2', '追问习惯', 1],
  ['4.4', '对不确定性的处理', 0],
  ['5.1', '拿手的事', 3],
  ['5.2', '熟悉领域的看法', 2],
  ['5.3', '自认不懂的领域', 0],
  ['6.1', '用词与口头禅', 1],
  ['6.2', '句式与结构', 2],
  ['6.4', '和不同的人说话', 1],
  ['7.3', '日常交往与合作', 1],
  ['7.4', '冲突处理', 0],
  ['8.1', '近期重点', 0],
  ['8.2', '正在做的事', 0],
  ['9.1', '兴趣爱好', 0],
  ['9.2', '生活习惯与作息', 0],
];

const coverage = {
  taxonomy: 't3',
  as_of: '2026-10-17',
  level_labels: {
    '0': '还不了解',
    '1': '已了解一些',
    '2': '了解较多',
    '3': '回答经过检查',
  },
  kind_labels: { chat: '聊天', document: '文档', interview: '访谈' },
  dimensions: dimensions.map(([dimension_id, name]) => {
    const own = facetLevels.filter(([id]) => `D${id[0]}` === dimension_id);
    return {
      dimension_id,
      name,
      facets: own.length,
      consented: own.length,
      covered: own.filter(([, , level]) => level > 0).length / own.length,
      sufficient: own.filter(([, , level]) => level > 1).length / own.length,
      verified: own.filter(([, , level]) => level > 2).length / own.length,
      conflicts: dimension_id === 'D3' ? 1 : 0,
    };
  }),
  facets: facetLevels.map(([facet_id, name, level]) => ({
    facet_id,
    name,
    dimension_id: `D${facet_id[0]}`,
    consented: true,
    level,
    sufficiency: level / 3,
    confirmed: 0,
    asked: 0,
    abstained: 0,
    conflicts: 0,
    by_kind: {},
  })),
  suggestions: [
    {
      facet_id: '8.1',
      name: '近期重点',
      reason: '还没有提到过',
      sources: ['interview'],
    },
    {
      facet_id: '9.1',
      name: '兴趣爱好',
      reason: '还没有提到过',
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
  memory('s-review', '2026-10-12 方案评审纪要.pdf', 'needs_name', {
    detected_kind_label: '访谈',
  }),
];

// Text transcripts waiting for 林舟 to say which speaker is them: two names across files, one label-only file.
const transcriptRoster = {
  pending: 3,
  names: [
    {
      name: '许清禾',
      segments: 42,
      chars: 3180,
      files: 3,
      samples: [
        '留存口径我建议按自然周算，不然和上个季度的报表对不上，回头解释成本更高。',
        '发布前那一周我们只修阻塞问题，新需求一律排到下个迭代。',
      ],
      likely: '说得最多',
    },
    {
      name: '林舟老师',
      segments: 27,
      chars: 2210,
      files: 2,
      samples: [
        '发布时间我倾向定在下周二，周一留给回归和灰度，出问题还有一天能回滚。',
        '这个口径先按清禾说的来，季度报表我去和财务对一下。',
        '不挪了，先把数据核对完。',
      ],
      likely: '和你的名字相近',
    },
    {
      name: '周石言',
      segments: 9,
      chars: 520,
      files: 1,
      samples: ['灰度比例先放 5%，看两天崩溃率再说。'],
      likely: null,
    },
  ],
  names_total: 3,
  files: [
    {
      source_id: 's-standup',
      title: '2026-10-14 站会',
      first_date: '2026-10-14',
      speakers: [
        {
          label: '发言人1',
          segments: 6,
          chars: 310,
          files: 1,
          samples: ['今天先把登录页的埋点补上，下午和测试对一下用例。'],
        },
        {
          label: '发言人2',
          segments: 4,
          chars: 180,
          files: 1,
          samples: ['我这边接口已经联调完了，等前端发版。'],
        },
      ],
    },
  ],
  files_total: 1,
  aliases: [],
  fixed: ['林舟'],
  not_me: 0,
};

const sourceSummary = {
  total: memories.length,
  duration_s: 5220,
  needs_speaker: 1,
  needs_name: 3,
  busy: 1,
  remembered: 2,
  nothing_found: 0,
  failed: 0,
};

// The system dialog administrators open from the rail: two services on the GPU machine, healthy now (the embedding
// service had a bad hour), speech switched off, video not configured.
const gpuNow = NOW.getTime() / 1000;
const gpuHours = (failing: number) =>
  Array.from({ length: 24 }, (_, i) => ({
    start: gpuNow - (24 - i) * 3600,
    checks: 60,
    failures: i === failing ? 12 : 0,
  }));
const system = {
  now: gpuNow,
  interval: 60,
  window: 86400,
  services: [
    {
      key: 'asr',
      name: '转写服务',
      enabled: true,
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
      enabled: true,
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
    {
      key: 'tts',
      name: '朗读服务',
      enabled: false,
      address: '127.0.0.1:8001',
      latest: null,
      since: null,
      checks: 0,
      failures: 0,
      availability: null,
      first_at: null,
      last_failure: null,
      buckets: gpuHours(-1).map((bucket) => ({ ...bucket, checks: 0 })),
    },
  ],
  switches: {
    tts: {
      configured: true,
      enabled: false,
      missing: null,
      changed_at: '2026-10-16T01:20:00+00:00',
      changed_by: 'admin@example.com',
    },
    video: {
      configured: false,
      enabled: false,
      missing: 'twin.toml 里没有配置 [video]',
      changed_at: null,
      changed_by: null,
    },
  },
  config: {
    embed: [
      ['接口', 'OpenAI 兼容'],
      ['地址', '127.0.0.1:11434'],
      ['模型', 'bge-m3'],
      ['每批 / 超时 / 重试', '32 · 30 秒 · 2 次'],
    ],
    asr: [
      ['接口', '命令'],
      ['地址', '127.0.0.1:18790'],
    ],
    tts: [
      ['接口', 'OpenAI 兼容'],
      ['地址', '127.0.0.1:8001'],
      ['模型', 'tts-example'],
      ['预置音色', 'alloy'],
    ],
    video: [['接口', '未配置']],
  },
  models: [
    {
      use: '整理记忆、校对转写',
      section: '[llm]',
      provider: 'OpenAI 兼容',
      model: 'example-model',
      address: 'llm.example.com',
      external: true,
    },
  ],
  features: {
    work: { label: '工作', enabled: true, changed_at: null, changed_by: null },
    ledger: {
      label: '承诺账本',
      enabled: true,
      changed_at: null,
      changed_by: null,
    },
  },
  editable_models: [
    {
      name: 'llm',
      section: '[llm]',
      use: '整理记忆、校对转写',
      base_url: 'https://llm.example.com/v1',
      model: 'example-model',
      locked: null,
      custom: false,
      changed_at: null,
      changed_by: null,
    },
    {
      name: 'chat_llm',
      section: '[chat_llm]',
      use: '聊天回答',
      base_url: null,
      model: null,
      locked: 'twin.toml 里没有配置 [chat_llm]，聊天用整理记忆的模型',
      custom: false,
      changed_at: null,
      changed_by: null,
    },
    {
      name: 'embed',
      section: '[embed]',
      use: '检索向量',
      base_url: 'http://127.0.0.1:18791/v1',
      model: 'bge-m3',
      locked: null,
      custom: false,
      changed_at: null,
      changed_by: null,
    },
  ],
  keys: [
    { env: 'TWIN_LLM_KEY', use: '文字模型', set: true },
    { env: 'TWIN_TTS_KEY', use: '朗读服务', set: false },
    { env: 'TWIN_API_TOKEN', use: '外部调用 /api', set: false },
  ],
  env_file: '.env',
  audit: [
    {
      at: '2026-10-17T01:30:00+00:00',
      by: 'admin@example.com',
      action: 'key',
      env: 'TWIN_LLM_KEY',
      set: true,
    },
  ],
  quota: {
    limit: 2_000_000,
    hours: 24,
    used: 640_000,
    exhausted: false,
    resets_at: null,
    custom: false,
    default_limit: 2_000_000,
    default_hours: 24,
  },
};

const handlers: Record<string, Handler> = {
  'GET /api/whoami': reply({ email: null, admin: true, auth_enabled: false }),
  'GET /api/auth/methods': reply({ sso: null, password: false, email: true }),
  'GET /api/admin/system': reply(system),
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
  // 员工 1b: voices like theirs in colleagues' meetings, one already said to be theirs.
  'GET /api/library/voice': reply({
    available: true,
    enrolled: true,
    items: [
      {
        id: 'vc_1',
        state: 'mine',
        quote: '续费方案我周四前给到大家，先把老用户这块做透。',
        title: '周一经营会',
        date: '2026-10-12',
        more: 3,
        unsure: false,
        sample_url: '/api/library/voice/items/vc_1/sample',
      },
      {
        id: 'vo_2',
        state: 'offered',
        quote: '留存口径我来重算，周五前按活跃用户出一版。',
        title: '产品周会',
        date: '2026-10-15',
        more: 1,
        unsure: false,
        sample_url: '/api/library/voice/items/vo_2/sample',
      },
      {
        id: 'vo_3',
        state: 'offered',
        quote: '……我同意，先上灰度。',
        title: '季度复盘',
        date: '2026-09-28',
        more: 0,
        unsure: true,
        sample_url: '/api/library/voice/items/vo_3/sample',
      },
    ],
    persona_id: 'p-zhaoqing',
  }),
  'GET /api/library/review': reply({
    items: [],
    voices: [
      {
        id: 'voice_shiyan',
        members: [
          {
            recording_id: 'r-weekly',
            filename: weekly.filename,
            transcript_id: weekly.transcript_id,
            speaker_id: 'S3',
            seconds: 640,
          },
          {
            recording_id: 'r-review',
            filename: '2026-10-12 需求评审.mp4',
            transcript_id: 't-review',
            speaker_id: 'S2',
            seconds: 410,
          },
        ],
        seconds: 1050,
        candidates: weekly.speakers[2].candidates,
        near: false,
      },
    ],
    fragments: [
      {
        recording_id: 'r-weekly',
        filename: weekly.filename,
        transcript_id: weekly.transcript_id,
        speaker_id: 'S4',
        seconds: 6,
      },
    ],
    unsorted: [],
  }),
  'GET /api/library/recordings/r-weekly': reply(weekly),
  'POST /api/library/recordings/r-broken/retry': reply({
    ...recordings.find((r) => r.id === 'r-broken'),
    status: 'queued',
    error: '',
  }),
  'GET /api/persona/state': reply({ stale: false }),
  'GET /api/conversations': reply(history),
  'GET /api/conversations/c-plan': reply(conversation),
  'GET /api/persona/coverage': reply(coverage),
  'GET /api/persona/items/summary': reply(itemSummary),
  'GET /api/persona/items': (url) => {
    const wanted = url.searchParams.getAll('dimension');
    const limit = Number(url.searchParams.get('limit') ?? items.length);
    const rows = items.filter(
      (item) => !wanted.length || wanted.includes(item.dimension_id),
    );
    if (url.searchParams.get('sort') === 'evidence')
      rows.sort((a, b) => b.occasions - a.occasions);
    return { items: rows.slice(0, limit), total: rows.length };
  },
  'GET /api/persona/processing': reply({ state: 'idle' }),
  'GET /api/persona/work': reply({
    tasks: [
      {
        task_id: 'w_000000000001',
        title: '按我的口吻写一份本周周报',
        status: 'idle',
        updated_at: '2026-10-17T01:20:00Z',
        turns: 2,
      },
      {
        task_id: 'w_000000000002',
        title: '把最近会上答应别人的事整理成 Excel',
        status: 'idle',
        updated_at: '2026-10-15T08:00:00Z',
        turns: 2,
      },
    ],
  }),
  'GET /api/persona/followups': reply({
    pending: 1,
    items: [
      {
        followup_id: 'q-1',
        question: '你怎么看远程办公？',
        previous: '我还没听你聊过远程办公。',
        reason: '记忆里没有相关的内容',
        asked: 2,
        first_at: '2026-10-16T02:00:00Z',
        last_at: '2026-10-17T03:00:00Z',
        status: 'pending',
        handled_at: null,
        asked_since: 0,
        source_id: null,
        unresolved: true,
      },
    ],
  }),
  'GET /api/persona/transcripts/speakers': () => transcriptRoster,
  'GET /api/persona/aliases': () => ({
    aliases: ['林总'],
    fixed: ['林舟'],
    not_me: 2,
  }),
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
                  (row) => !['remembered', 'needs_name'].includes(row.status),
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
