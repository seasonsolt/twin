// Fixed answers to every API call the screenshot pages make: a small fictional team, so the pages look lived in and
// render the same on every run. Anything the pages ask for that is not listed here fails the test (see `missing`),
// so a new request is noticed instead of silently rendering an error state.
import type { Page, Route } from '@playwright/test';

/** The moment the pages think it is: relative times ("3 天前") and timers count from here. */
export const NOW = new Date('2026-10-17T10:00:00+08:00');

type Handler = (url: URL, route: Route) => unknown;
const reply = (body: unknown) => () => body;

type Listed = {
  seconds?: number;
  enough?: boolean;
  stranger?: boolean;
  roi?: number;
};
/** A page of the review queue as the server cuts it (``review_queue.page``): the first so many of each list the
 * page asks for, and how many each holds in all. */
const reviewPage = (
  url: URL,
  reading: Record<'items' | 'voices' | 'unsorted', Listed[]> &
    Record<string, unknown>,
) => {
  const kind = (voice: Listed) =>
    voice.stranger
      ? 'strangers'
      : voice.enough
        ? 'enough'
        : voice.roi === 4
          ? 'once'
          : 'voices';
  const lists: Record<string, Listed[]> = {
    voices: [],
    once: [],
    enough: [],
    strangers: [],
    items: reading.items,
    unsorted: reading.unsorted,
    suspects: (reading.suspects as Listed[] | undefined) ?? [],
  };
  for (const voice of reading.voices) lists[kind(voice)].push(voice);
  const totals: Record<
    string,
    { count: number; seconds?: number; parts?: Record<string, number> }
  > = {};
  for (const [name, rows] of Object.entries(lists)) {
    totals[name] = { count: rows.length };
    if (['voices', 'once', 'enough', 'strangers'].includes(name))
      totals[name].seconds = rows.reduce((n, row) => n + (row.seconds ?? 0), 0);
    if (name === 'voices')
      totals[name].parts = Object.fromEntries(
        [1, 2, 3].map((n) => [n, rows.filter((row) => row.roi === n).length]),
      );
    const limit = url.searchParams.get(name);
    if (limit !== null) lists[name] = rows.slice(0, Number(limit));
  }
  return {
    ...reading,
    voices: [
      ...lists.voices,
      ...lists.once,
      ...lists.enough,
      ...lists.strangers,
    ],
    items: lists.items,
    unsorted: lists.unsorted,
    suspects: lists.suspects,
    totals,
  };
};

export const personas = [
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
    // Made for her work address: whoever looks after it can ask her for more.
    claim: 'xu.qinghe@example.com',
  },
  // A twin made by hand, which no recording belongs to: a row of the team table like the others.
  {
    id: 'p-helper',
    name: '备忘助手',
    avatar_url: null,
    avatar_preset: 'stone',
    sources: 3,
    created_at: '2026-09-20T02:00:00Z',
    is_default: false,
    can_manage: true,
  },
  // Someone else's public twin: to talk to, nothing to manage.
  {
    id: 'p-public',
    name: '王屿',
    avatar_url: null,
    avatar_preset: 'bun',
    sources: 9,
    created_at: '2026-09-25T02:00:00Z',
    is_default: false,
    can_manage: false,
    public: true,
    owner: 'wang.yu@example.com',
  },
];

/** A twin deleted in the last days, which can still be brought back. */
const trash = [
  {
    id: 'p-old',
    name: '旧版助手',
    deleted_at: '2026-10-14T02:00:00Z',
    expires_at: '2026-10-21T02:00:00Z',
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

export const status = {
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
  // A transcript brought in as text: no sound, a length that is about, every speaker already named.
  {
    id: 'r-interview',
    filename: '2026-10-11 客户访谈.txt',
    size: 64_000,
    kind: 'transcript',
    status: 'ready',
    error: '',
    duration_s: 2400,
    transcribed_s: 2400,
    speakers: 3,
    segments: 180,
    created_at: '2026-10-11T08:00:00Z',
    people: ['林舟', '许清禾', '周石言'],
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
    retryable: true,
    reupload: true,
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
    // Speakers given to 林舟 by voice alone, to spot-check.
    checks: 3,
    about: '产品负责人',
    last_meeting: {
      recording_id: 'r-weekly',
      title: '产品周会',
      date: '2026-10-15',
    },
  },
  {
    id: 'u-qinghe',
    name: '许清禾',
    persona_id: 'p-qinghe',
    speakers: 4,
    seconds: 2600,
    samples: 3,
    updating: true,
    // Her twin is merging what it read: the card shows the step and how far it has gone.
    build: {
      state: 'running',
      progress: {
        phase: 'merge',
        done: 406,
        total: 406,
        merged: 30,
        to_merge: 130,
      },
    },
    auto: false,
    gender: 'female',
    recording_id: 'r-weekly',
    speaker_id: 'S2',
    last_meeting: {
      recording_id: 'r-review',
      title: '需求评审',
      date: '2026-10-12',
    },
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
    last_meeting: {
      recording_id: 'r-weekly',
      title: '产品周会',
      date: '2026-10-15',
    },
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
  denoised: true,
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
        { person_id: 'u-qinghe', name: '许清禾', score: 0.62 },
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

// A colleague's question the twin left to the person, and the person's own reply under it.
const handoffConversation = {
  id: 'c-handoff',
  title: '下周发布怎么安排',
  turns: [
    {
      id: 'h1',
      role: 'user',
      content: '下周发布怎么安排？周五前给我方案。',
      timestamp: '2026-10-17T01:30:00Z',
    },
    {
      id: 'h2',
      role: 'twin',
      content: '发布定在下周二，周三前备好测试环境。大文件导入再测一轮再定。',
      timestamp: '2026-10-17T01:30:08Z',
      reply: {
        reply: '发布定在下周二，周三前备好测试环境。大文件导入再测一轮再定。',
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
      handoff: {
        id: 'hf-1',
        kind: 'commit',
        status: 'replied',
        status_label: '已回复',
        owner_name: '林舟',
      },
    },
    {
      id: 'h3',
      role: 'self',
      content: '方案周五前给你。大文件导入先不放这次。',
      timestamp: '2026-10-17T03:05:00Z',
      handoff_id: 'hf-1',
    },
  ],
};

// 第 10 屏: what the twin left to the person, the answers it guessed, and how many it answered from the profile.
const handoffRow = {
  kind: 'decide',
  kind_label: '要你决定',
  status: 'delivered',
  status_label: '已送达',
  context: '',
  ask: '',
  source_known: true,
  commit: null,
  reply: null,
  replied_at: null,
};
const away = {
  waiting: [
    {
      ...handoffRow,
      id: 'hf-1',
      kind: 'commit',
      kind_label: '要你答应',
      asker_name: '沈从',
      question: '下周的发布你打算怎么安排？周五前给我一版方案。',
      answer: '发布定在下周二，周三前备好测试环境。这个我先看看安排。',
      created_at: '2026-10-16T13:14:00Z',
      expires_at: '2026-10-19T13:14:00Z',
      days_left: 2,
      commit: {
        entry_id: 'le-1',
        what: '周五前给沈从一版发布方案',
        due: '2026-10-25',
        pending: true,
      },
    },
    {
      ...handoffRow,
      id: 'hf-2',
      kind: 'missing',
      kind_label: '无出处',
      asker_name: '许清禾',
      question: '需求评审里那组接口，你倾向这次就改，还是下个版本再说？',
      answer: null,
      created_at: '2026-10-17T01:02:00Z',
      expires_at: '2026-10-22T01:02:00Z',
      days_left: 5,
    },
    {
      ...handoffRow,
      id: 'hf-3',
      kind: 'evaluate',
      kind_label: '涉及评价',
      asker_name: '陈一',
      question: '你觉得新来的实习生能不能独立负责导入模块？',
      answer: null,
      created_at: '2026-10-17T02:40:00Z',
      expires_at: '2026-10-22T02:40:00Z',
      days_left: 5,
    },
  ],
  guessed: [
    {
      conversation_id: 'c-g1',
      turn: 2,
      asker_name: '沈从',
      question: '要是发布延期一周，你能接受吗？',
      answer: '能接受，但我会先把大文件导入拿出这次发布。',
      at: '2026-10-17T02:00:00Z',
    },
    {
      conversation_id: 'c-g2',
      turn: 2,
      asker_name: '王屿',
      question: '周报你更喜欢按项目写还是按人写？',
      answer: '按项目写，每个项目一句结论加下周要做的事。',
      at: '2026-10-17T02:10:00Z',
    },
  ],
  sourced: [],
  sourced_count: 7,
  answered: 12,
  shelved: [],
  settled: [],
  groups: [],
  often: [],
  answers: { total: 0, stale: 0 },
  pending: 3,
  days: 7,
};

// 第 14 屏: three people asked the same thing in their own words, one card, and a reply the twin keeps giving.
const sameMatter = (
  id: string,
  who: string,
  question: string,
  at: string,
  mode: 'abstain' | 'grounded',
) => ({
  ...handoffRow,
  id,
  kind: 'decide',
  asker_name: who,
  question,
  answer:
    mode === 'abstain' ? null : '旧模板这次之后还能导出，具体到哪天要问林舟。',
  twin_mode: mode,
  created_at: at,
  expires_at: '2026-10-24T09:00:00Z',
  days_left: 5,
});
export const awayMerged = {
  ...away,
  waiting: [
    sameMatter(
      'hf-4',
      '许清禾',
      '旧版 Word 模板导出，这次之后还支持吗？',
      '2026-10-17T01:12:00Z',
      'abstain',
    ),
    sameMatter(
      'hf-5',
      '陈一',
      '客户问旧模板还能不能导出，我该怎么回？',
      '2026-10-17T02:05:00Z',
      'abstain',
    ),
    sameMatter(
      'hf-6',
      '王屿',
      '销售那边听说旧模板要停用了，是真的吗？',
      '2026-10-17T03:30:00Z',
      'grounded',
    ),
    {
      ...handoffRow,
      id: 'hf-3',
      kind: 'evaluate',
      kind_label: '涉及评价',
      asker_name: '陈一',
      question: '你觉得新来的实习生能不能独立负责导入模块？',
      answer: null,
      created_at: '2026-10-17T02:40:00Z',
      expires_at: '2026-10-22T02:40:00Z',
      days_left: 5,
    },
  ],
  groups: [['hf-4', 'hf-5', 'hf-6']],
  often: [
    {
      handoff_id: 'hf-9',
      title: '周报按项目写还是按人写？',
      reply: '按项目写，每个项目一句结论加下周要做的事。',
      askers: ['王屿', '周宁'],
      uses: 2,
      days: 7,
    },
  ],
  answers: { total: 3, stale: 1 },
  guessed: [],
  pending: 4,
};

// 第 15 屏: a colleague asks someone's twin; the team's answer is a card of its own, and a doubtful one is dashed.
const teamAnswerCard = {
  id: 'ta-1',
  persona_id: 'default',
  owner_name: '林舟',
  title: '旧版 Word 模板导出，这次之后还支持吗？',
  body: '旧版 Word 模板支持到 12 月 31 日，之后导出只保留新模板。客户要迁移的话，找陈一要转换脚本，旧文件一次就能转完。',
  confirmed_at: '2026-10-22T09:00:00Z',
  status: 'valid',
  stale_note: '',
  partial: false,
};
const teamReply = (reply: string, cards: unknown[]) => ({
  reply,
  citations: [],
  confidence: 0.8,
  abstain: false,
  abstain_reason: '',
  retrieved_ids: [],
  mode: 'general',
  verified: true,
  elapsed_ms: 3100,
  completed_at: '2026-10-17T01:30:08Z',
  cited: [],
  team_answers: cards,
});
const teamConversation = {
  id: 'c-team',
  title: '客户问旧模板还能导出吗',
  audience: 'colleague',
  turns: [
    {
      id: 't1',
      role: 'user',
      content: '客户问旧版 Word 模板还能导出吗？我该怎么回？',
      timestamp: '2026-10-17T01:30:00Z',
    },
    {
      id: 't2',
      role: 'twin',
      content: '我一般先发迁移说明，再约陈一帮客户转。',
      timestamp: '2026-10-17T01:30:08Z',
      reply: teamReply('我一般先发迁移说明，再约陈一帮客户转。', [
        teamAnswerCard,
      ]),
    },
    {
      id: 't3',
      role: 'user',
      content: '那旧模板 12 月底就停了对吧？客户在催排期。',
      timestamp: '2026-10-27T01:30:00Z',
    },
    {
      id: 't4',
      role: 'twin',
      content: '这条可能变了，以林舟本人为准。',
      timestamp: '2026-10-27T01:30:08Z',
      reply: teamReply('这条可能变了，以林舟本人为准。', [
        {
          ...teamAnswerCard,
          status: 'stale',
          body: '旧模板支持到 12 月 31 日，之后只保留新模板。',
          stale_note: '10 月 27 日「产品周会」里说：旧模板 10 月底就停了。',
        },
      ]),
    },
  ],
};
// 第 12、13 屏: the facets the person could open and what stands in the way of the rest, the lens they published, what
// it was used for (never by whom), and a colleague's question answered by it.
const lensFacet = (
  facet_id: string,
  name: string,
  dimension: string,
  more: Record<string, unknown> = {},
) => ({
  facet_id,
  name,
  dimension_id: `D${facet_id.split('.')[0]}`,
  dimension,
  level: 3,
  label: '了解较多',
  checked: false,
  checked_label: '',
  occasions: 4,
  ok: true,
  reasons: [],
  ...more,
});
export const lensFacets = [
  lensFacet('2.1', '核心价值排序', '看重什么', {
    ok: false,
    level: 2,
    label: '了解一些',
    occasions: 2,
    reasons: ['了解还不够多'],
  }),
  lensFacet('2.3', '做事的原则', '看重什么', {
    ok: false,
    level: 0,
    label: '还不了解',
    occasions: 0,
    reasons: ['还没有记忆'],
  }),
  lensFacet('3.1', '风险偏好', '怎么做决定', {
    ok: false,
    level: 1,
    label: '提到过',
    occasions: 1,
    reasons: ['了解还不够多'],
  }),
  lensFacet('3.3', '依据偏好', '怎么做决定', {
    checked: true,
    checked_label: '回答经过检查',
  }),
  lensFacet('3.4', '常见取舍', '怎么做决定'),
  lensFacet('4.2', '追问习惯', '怎么思考'),
  lensFacet('4.4', '对不确定性的处理', '怎么思考', {
    ok: false,
    level: 2,
    label: '了解一些',
    reasons: ['了解还不够多', '内容有矛盾'],
  }),
  lensFacet('5.1', '拿手的事', '擅长什么', {
    checked: true,
    checked_label: '回答经过检查',
  }),
];
const lensFacetOf = (facet_id: string) => {
  const found = lensFacets.find((f) => f.facet_id === facet_id)!;
  return {
    facet_id,
    name: found.name,
    dimension_id: found.dimension_id,
    dimension: found.dimension,
  };
};
const lens = {
  id: 'l-1',
  name: '大客户谈判',
  status: 'active',
  published_at: '2026-10-12T09:00:00Z',
  audience: { scope: 'team', twins: [] },
  facets: ['3.1', '3.3', '3.4', '4.2', '4.4', '5.1'].map(lensFacetOf),
  speaking: ['3.3', '4.2', '5.1'],
  failing: ['3.1', '4.4'],
  stopped: [{ facet_id: '3.4', name: '常见取舍', corrected: 3 }],
  uses_week: 12,
};
export const lensList = {
  lenses: [lens],
  facets: lensFacets,
  stop_after: 3,
  colleagues: [
    { id: 'p-shen', name: '沈从' },
    { id: 'p-chen', name: '陈一' },
  ],
};
const lensUses = [
  {
    id: 'lu-1',
    question: '客户嫌报价高，要求再降 10%，我该怎么回？',
    said: '先问清预算是谁定的、什么时候定\n让价换条件，比如拉长合同期或预付，不单方面降',
    facets: [{ facet_id: '3.3', name: '依据偏好' }],
    corrected: false,
    at: '2026-10-17',
  },
  {
    id: 'lu-2',
    question: '新客户第一次见面，要不要带方案过去？',
    said: '第一次只带问题清单，听完再出方案',
    facets: [{ facet_id: '4.2', name: '追问习惯' }],
    corrected: false,
    at: '2026-10-16',
  },
  {
    id: 'lu-3',
    question: '渠道商要独家代理，答应吗？',
    said: '',
    facets: [],
    corrected: false,
    at: '2026-10-16',
  },
  {
    id: 'lu-4',
    question: '大客户续约前要做哪些准备？',
    said: '先复盘上一年的使用数据，再约决策人',
    facets: [{ facet_id: '2.3', name: '做事的原则' }],
    corrected: true,
    at: '2026-10-14',
  },
];
const lensPreview = {
  views: [
    {
      facet_id: '3.3',
      facet: '依据偏好',
      text: '先不谈价格，先问清预算是谁定的、什么时候定。',
      basis: [
        {
          quote: '我一般先问预算是谁定的',
          date: '2026-10-08',
          kind: '音频',
        },
      ],
    },
    {
      facet_id: '2.3',
      facet: '做事的原则',
      text: '让价换条件，比如拉长合同期或预付，不单方面降。',
      basis: [
        {
          quote: '降价可以，但要换合同期',
          date: '2026-09-28',
          kind: '聊天记录',
        },
      ],
    },
  ],
  settled_by_person: true,
};
const lensCard = {
  id: 'l-1',
  name: '大客户谈判',
  owner_name: '王屿',
  views: lensPreview.views,
  empty: false,
  settled_by_person: true,
  note: '根据王屿说过的话推测，不代表王屿的意见',
};
const lensConversation = {
  id: 'c-lens',
  title: '客户嫌报价高怎么回',
  audience: 'colleague',
  turns: [
    {
      id: 't1',
      role: 'user',
      content: '客户嫌报价高，要求再降 10%，我该怎么回？',
      timestamp: '2026-10-17T01:30:00Z',
    },
    {
      id: 't2',
      role: 'twin',
      content: lensPreview.views.map((v) => v.text).join('\n'),
      timestamp: '2026-10-17T01:30:02Z',
      reply: {
        reply: lensPreview.views.map((v) => v.text).join('\n'),
        citations: [],
        confidence: 1,
        abstain: false,
        abstain_reason: '',
        retrieved_ids: [],
        mode: 'general',
        verified: true,
        lens: lensCard,
      },
    },
  ],
};
export const lensChoices = {
  lenses: [
    {
      id: 'l-1',
      name: '大客户谈判',
      owner_name: '王屿',
      facets: lensCard.views.map((v) => ({
        facet_id: v.facet_id,
        name: v.facet,
      })),
    },
  ],
};
// 我设的团队答案: what the person made the team's, as the server lists them: those possibly out of date first, then
// the newest confirmed first.
const myTeamAnswers = [
  {
    ...teamAnswerCard,
    id: 'ta-2',
    title: '续约折扣谁能批？',
    body: '15% 以内销售负责人自己定，超过 15% 报沈从批，当天回复。',
    confirmed_at: '2026-10-09T09:00:00Z',
    status: 'stale',
    stale_note: '10 月 27 日「经营会」里说：超过 20% 才报沈总。',
    handoff_id: 'hf-7',
  },
  { ...teamAnswerCard, handoff_id: 'hf-4' },
  {
    ...teamAnswerCard,
    id: 'ta-3',
    title: '发布前要备哪些环境？',
    body: '测试环境和回滚方案，周三前备好。',
    confirmed_at: '2026-10-05T09:00:00Z',
    handoff_id: 'hf-8',
  },
];

/** An heir's own conversation with the twin, once they opened it (P2.7); the twin speaks only from what the will
 * gives them. */
export const heirConversation = {
  id: 'c-heir',
  title: '小时候的事',
  turns: [
    {
      id: 'h1',
      role: 'user',
      content: '你还记得我小时候学骑车的事吗？',
      timestamp: '2026-10-17T01:30:00Z',
    },
    {
      id: 'h2',
      role: 'twin',
      content:
        '记得。那年夏天在小区后面的空地上，你摔了好几次也不肯回家，最后是自己骑到了路口。我常说你做事认准了就不撒手。',
      timestamp: '2026-10-17T01:30:08Z',
      reply: {
        reply:
          '记得。那年夏天在小区后面的空地上，你摔了好几次也不肯回家，最后是自己骑到了路口。我常说你做事认准了就不撒手。',
        citations: [],
        confidence: 0.7,
      },
    },
  ],
  audience: 'heir:heir_yu',
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

/** 第 6 屏: everything the person has talked about across twins, from the team's index, newest first. */
const everyone = (mine: { persona_id: string; pending: number } | null) => ({
  mine,
  conversations: [
    {
      id: 'c-plan',
      persona_id: 'default',
      title: '下周发布怎么安排',
      preview: history[0].preview,
      updated_at: history[0].updated_at,
      via: 'direct',
      handoff: null,
    },
    {
      id: 'c-api',
      persona_id: 'p-qinghe',
      title: '评审定的接口',
      preview: '接口先按 v2 评审的结论来。',
      updated_at: '2026-10-16T08:00:00Z',
      via: 'direct',
      handoff: null,
    },
    {
      id: 'c-hiring',
      persona_id: 'default',
      title: '招聘面试的问题',
      preview: history[1].preview,
      updated_at: history[1].updated_at,
      via: 'direct',
      handoff: null,
    },
  ],
  tasks: [
    {
      task_id: 'w_000000000001',
      persona_id: 'default',
      title: '按我的口吻写一份本周周报',
      status: 'idle',
      updated_at: '2026-10-17T01:20:00Z',
    },
    {
      task_id: 'w_000000000002',
      persona_id: 'default',
      title: '把最近会上答应别人的事整理成 Excel',
      status: 'idle',
      updated_at: '2026-10-15T08:00:00Z',
    },
  ],
  more: false,
});

/** 第 11 屏: the person's own conversation with their assistant, and what it took down. */
const selfConversation = {
  id: 'c-self',
  title: '我上周答应过谁什么',
  audience: 'self',
  turns: [
    {
      id: 's1',
      role: 'user',
      content: '我上周答应过谁什么？',
      timestamp: '2026-10-17T01:00:00Z',
    },
    {
      id: 's2',
      role: 'twin',
      content:
        '三件：给许清禾重算留存口径（已交）；下周二前和王屿定发布时间；帮陈一看导入方案。后两件还开着。',
      timestamp: '2026-10-17T01:00:08Z',
      reply: {
        reply:
          '三件：给许清禾重算留存口径（已交）；下周二前和王屿定发布时间；帮陈一看导入方案。后两件还开着。',
        citations: ['i-1'],
        confidence: 0.85,
        abstain: false,
        abstain_reason: '',
        retrieved_ids: ['i-1'],
        mode: 'grounded',
        elapsed_ms: 3100,
        completed_at: '2026-10-17T01:00:08Z',
        cited: [
          {
            id: 'i-1',
            kind: 'item',
            text: '答应别人的事一定按时给回复',
            facet: '做事的原则',
            date: '2026-10-15',
          },
        ],
      },
    },
    {
      id: 's3',
      role: 'user',
      content: '记一下，下周三我请假陪家人复查。',
      timestamp: '2026-10-17T01:12:00Z',
    },
    {
      id: 's4',
      role: 'twin',
      content: '记下了，先设为只有你能用。',
      timestamp: '2026-10-17T01:12:01Z',
      reply: {
        reply: '记下了，先设为只有你能用。',
        citations: [],
        confidence: 1,
        abstain: false,
        abstain_reason: '',
        retrieved_ids: [],
        mode: 'general',
        note: {
          id: 'src_note',
          text: '下周三请假，陪家人复查',
          tier: 'self',
        },
      },
    },
  ],
};

// 第 17 屏: the person told their assistant to ask two colleagues' twins; what came back.
const delegationQuestion =
  '旧模板延到明年 3 月，客户能接受吗？脚本还按 12 月做完吗？';
const delegationConversation = {
  id: 'c-deleg',
  title: '旧模板延到 3 月行不行',
  audience: 'self',
  turns: [
    {
      id: 'd1',
      role: 'user',
      content: `帮我问问王屿和陈一：${delegationQuestion}`,
      timestamp: '2026-10-17T02:40:00Z',
    },
    {
      id: 'd2',
      role: 'twin',
      content: '已用你的名义问了王屿、陈一，本人看得到。',
      timestamp: '2026-10-17T02:42:00Z',
      reply: {
        reply: '已用你的名义问了王屿、陈一，本人看得到。',
        citations: [],
        confidence: 1,
        abstain: false,
        abstain_reason: '',
        retrieved_ids: [],
        mode: 'general',
        delegation: {
          id: 'd-1',
          summary: '客户能接受；脚本排期等陈一；合同那家等沈从。齐了再定。',
          asked: 2,
        },
      },
    },
  ],
};
const delegationView = {
  id: 'd-1',
  question: delegationQuestion,
  limit: 3,
  targets: [
    {
      persona_id: 'p-public',
      name: '王屿',
      conversation_id: 'c-deleg-wang',
      state: 'answered',
      answer: '能接受。两家大客户都说 3 月前不急，希望年底别动。',
      mode: 'grounded',
      ask: '',
      team_answer: null,
      handoff: null,
      owner_reply: null,
      also: [{ persona_id: 'p-shen', name: '沈从' }],
    },
    {
      persona_id: 'p-chen',
      name: '陈一',
      conversation_id: 'c-deleg-chen',
      state: 'needs_owner',
      answer: '脚本做完七成。排期我回头答复你。',
      mode: 'general',
      ask: '脚本排期怎么定',
      team_answer: null,
      handoff: null,
      owner_reply: null,
      also: [],
    },
  ],
};

/** The signed-in person has taken their twin: what the page lists apart as 我的分身, and the twins around it. */
export async function ownAssistant(page: Page, delegated = false) {
  await page.route(/\/api\/personas$/u, (route) =>
    route.fulfill({
      json: personas.map((twin) =>
        twin.id === 'default' ? { ...twin, mine: true, approved: true } : twin,
      ),
    }),
  );
  await page.route(/\/api\/personas\/conversations/u, (route) => {
    const mine = new URL(route.request().url()).searchParams.get('mine');
    const own = { persona_id: 'default', pending: 3 };
    return route.fulfill({
      json:
        mine === 'true'
          ? {
              mine: own,
              conversations: [
                {
                  id: 'c-self',
                  persona_id: 'default',
                  title: selfConversation.title,
                  preview: '记下了，先设为只有你能用。',
                  updated_at: '2026-10-17T01:12:01Z',
                  via: 'direct',
                  handoff: null,
                },
                // What the assistant asked in the person's name, apart under 问同事.
                ...(delegated
                  ? [
                      {
                        id: 'c-deleg',
                        persona_id: 'default',
                        title: delegationConversation.title,
                        preview: '已用你的名义问了王屿、陈一，本人看得到。',
                        updated_at: '2026-10-17T02:42:00Z',
                        via: 'direct',
                        handoff: null,
                        delegated: 2,
                      },
                      {
                        id: 'c-deleg-wang',
                        persona_id: 'p-public',
                        title: '旧模板延期客户能接受吗',
                        preview: '能接受。两家大客户都说 3 月前不急。',
                        updated_at: '2026-10-17T02:41:00Z',
                        via: 'delegate',
                        handoff: null,
                      },
                      {
                        id: 'c-deleg-chen',
                        persona_id: 'p-qinghe',
                        title: '转换脚本还按 12 月做完吗',
                        preview: '脚本做完七成。排期我回头答复你。',
                        updated_at: '2026-10-17T02:40:00Z',
                        via: 'delegate',
                        handoff: null,
                      },
                    ]
                  : []),
              ],
              tasks: [
                {
                  task_id: 'w_000000000003',
                  persona_id: 'default',
                  title: '起草发布方案',
                  status: 'idle',
                  updated_at: '2026-10-16T08:00:00Z',
                },
              ],
              more: false,
            }
          : {
              ...everyone(own),
              conversations: everyone(own).conversations.slice(1),
            },
    });
  });
  await page.route(/\/api\/conversations\/c-self$/u, (route) =>
    route.fulfill({ json: selfConversation }),
  );
}

const dimensions = [
  ['D1', '经历与身份', 6],
  ['D2', '看重什么', 12],
  ['D3', '怎么做决定', 9],
  ['D4', '怎么思考', 5],
  ['D5', '擅长什么', 8],
  ['D6', '说话方式', 6],
  ['D7', '和人相处', 2],
  ['D8', '最近在关注', 0],
  ['D9', '生活与喜好', 1],
  ['D10', '存在与意义', 0],
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
  ['D9', '9.2', '生活习惯与作息', '晚上十点以后不看工作消息', ''],
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
    // What colleagues may use: every facet but the personal ones, unless the person said otherwise.
    tier: dimension_id === 'D9' ? 'self' : 'colleague',
    tier_changed: false,
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
  ['9.2', '生活习惯与作息', 1],
  ['10.1', '想留下什么', 0],
];

// Facets at the third level whose answers held up when the twin was asked about them.
const checkedFacets = new Set(['2.1', '5.1']);

const willHeir = (heir_id: string, name: string, relation: string) => ({
  heir_id,
  name,
  relation,
  aspects: [] as string[],
  facets: [] as string[],
  avoid: [] as string[],
  voice: false,
  likeness: false,
  retire_on: null as string | null,
  farewell: null as string | null,
  created_at: '2026-10-12T21:05:00',
  updated_at: '2026-10-16T20:12:00',
});

export const willHeirs = [
  {
    ...willHeir('heir_yu', '小雨', '女儿'),
    aspects: ['D1', 'D2', 'D9'],
    facets: ['3.1'],
    avoid: ['前一段婚姻'],
    voice: true,
    retire_on: '2066-06-01',
  },
  willHeir('heir_zhou', '老周', '老友'),
];

/**
 * 预演 as 小雨: the streamed answer to a question of hers, from what the will gives her, with what the person's own
 * retrieval also found that she is not given; a topic the will says not to talk about gets the fixed reply.
 */
export const willRehearsal = (question: string) => {
  const avoided = question.includes('婚姻');
  const reply = avoided
    ? '这件事林舟生前交代过，不和你谈。我们聊点别的吧。'
    : '周末多半在河边，钓不钓得到都无所谓，图个安静。你小时候总嫌我坐不住，其实我是在等你。';
  const final = {
    reply,
    citations: [],
    confidence: avoided ? 1 : 0.86,
    abstain: false,
    mode: avoided ? 'general' : 'grounded',
    retrieved_ids: [],
    cited: [],
    preview: {
      withheld: avoided
        ? []
        : [
            { id: 'pi_rule', facet: '底线与原则', text: '他做事不欠人情' },
            { id: 'pi_health', facet: '身体与健康', text: '他这两年在复查' },
          ],
    },
  };
  return (
    `event: delta\ndata: ${JSON.stringify({ text: reply })}\n\n` +
    `event: final\ndata: ${JSON.stringify(final)}\n\n`
  );
};

const coverage = {
  taxonomy: 't3',
  as_of: '2026-10-17',
  // How much the twin knows of a facet, each more than the last; a facet whose answers held up carries a tick.
  level_labels: {
    '0': '还不了解',
    '1': '提到过',
    '2': '了解一些',
    '3': '了解较多',
  },
  checked_label: '回答经过检查',
  kind_labels: { chat: '聊天', document: '文档', interview: '访谈' },
  dimensions: dimensions.map(([dimension_id, name]) => {
    const own = facetLevels.filter(
      ([id]) => `D${id.split('.')[0]}` === dimension_id,
    );
    return {
      dimension_id,
      name,
      facets: own.length,
      consented: own.length,
      covered: own.filter(([, , level]) => level > 0).length / own.length,
      sufficient: own.filter(([, , level]) => level > 2).length / own.length,
      verified: own.filter(([id]) => checkedFacets.has(id)).length / own.length,
      conflicts: dimension_id === 'D3' ? 1 : 0,
    };
  }),
  facets: facetLevels.map(([facet_id, name, level]) => ({
    facet_id,
    name,
    dimension_id: `D${facet_id.split('.')[0]}`,
    consented: true,
    level,
    checked: checkedFacets.has(facet_id),
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
      reason: '还没有任何证据',
      sources: ['interview'],
    },
    {
      facet_id: '9.1',
      name: '兴趣爱好',
      reason: '还没有任何证据',
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
  imported_at: '2026-10-16T09:30:00',
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

/** A twin made a moment ago: its chat shows how it gets to know its person, waiting on which speaker is them. */
const newRecording = memory('s-new', '2026-10-18 周会', 'needs_speaker', {
  kind: 'audio',
  duration_s: 2520,
});
export const newTwin = {
  identity: { ...identity, about: '', onboarding_pending: true },
  status: { ...status, counts: { sources: 1, items: 0 } },
  sources: {
    items: [newRecording],
    total: 1,
    summary: {
      ...sourceSummary,
      total: 1,
      duration_s: 2520,
      needs_speaker: 1,
      needs_name: 0,
      busy: 0,
      remembered: 0,
    },
    attention: [newRecording],
  },
  speakers: {
    diarized: true,
    speakers: [
      ['S1', 1080, '这个版本先别上，等客户那边确认了再说'],
      ['S2', 900, '客户下周要看演示，我们得先把流程走通'],
      ['S3', 540, '设计稿我今晚再改一版，明早发群里'],
    ].map(([id, seconds, quote], i) => ({
      id,
      seconds,
      similarity: null,
      suggested: false,
      also_suggested: false,
      quote,
      samples: [`/api/persona/sources/s-new/samples/${i}/0`],
    })),
  },
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
  team_name: '产品研发部',
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
  params: [
    {
      key: 'kernel.auto_rebuild',
      label: '自动升级记忆内核',
      help: '新版本发布后，启动时自动按新内核重新整理记忆；关闭后在设置的“记忆”里手动升级。',
      unit: '',
      value: false,
      default: true,
      custom: true,
      changed_at: '2026-10-16T08:00:00+00:00',
      changed_by: 'admin@example.com',
    },
    {
      key: 'kernel.max_auto_rebuild_chunks',
      label: '自动升级上限',
      help: '需要重新整理的段数超过这个数时不自动升级，等管理员确认；每段调用一次模型。',
      unit: '段',
      value: 400,
      default: 400,
      custom: false,
      changed_at: null,
      changed_by: null,
    },
    {
      key: 'library.max_pending',
      label: '每人排队转写上限',
      help: '每位成员同时等待转写的录音最多这么多条。',
      unit: '条',
      value: 20,
      default: 20,
      custom: false,
      changed_at: null,
      changed_by: null,
    },
    {
      key: 'library.headroom_gb',
      label: '磁盘安全余量',
      help: '添加录音后可用空间会低于这个值时，拒绝上传。',
      unit: 'GB',
      value: 50,
      default: 20,
      custom: true,
      changed_at: '2026-10-15T03:20:00+00:00',
      changed_by: 'admin@example.com',
    },
    {
      key: 'library.failed_keep_days',
      label: '转写失败的原件保留天数',
      help: '过期后删除原件；0 表示一直保留，转写服务恢复后还能重试。',
      unit: '天',
      value: 0,
      default: 0,
      custom: false,
      changed_at: null,
      changed_by: null,
    },
  ],
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

const kernelVersion = { schema: 4, prompt: 'persona-v7', taxonomy: 'v2' };
const components = {
  kernel: {
    version: kernelVersion,
    twins: [
      {
        id: 'default',
        name: '林舟',
        version: kernelVersion,
        built: kernelVersion,
        scope: 'none',
        pending_chunks: 0,
        state: 'ready',
      },
      {
        id: 'p-qinghe',
        name: '许清禾',
        version: kernelVersion,
        built: { schema: 4, prompt: 'persona-v6', taxonomy: 'v2' },
        scope: 'full',
        pending_chunks: 186,
        state: 'awaiting_confirmation',
      },
    ],
  },
  ledger: {
    version: 'ledger-v1',
    enabled: true,
    twins: [
      { id: 'default', name: '林舟', meetings: 9, pending: 0, running: false },
      {
        id: 'p-qinghe',
        name: '许清禾',
        meetings: 3,
        pending: 3,
        running: false,
      },
    ],
  },
  library: { attribution: 'attribution-v2', cleanup: 'cleanup-v1' },
};

const handlers: Record<string, Handler> = {
  'GET /api/whoami': reply({
    email: null,
    admin: true,
    auth_enabled: false,
    team_name: '产品研发部',
  }),
  'GET /api/auth/methods': reply({
    sso: null,
    password: false,
    email: true,
    team_name: '产品研发部',
  }),
  'GET /api/admin/system': reply(system),
  'GET /api/admin/system/components': reply(components),
  'GET /api/personas': reply(personas),
  'GET /api/personas/trash': reply(trash),
  'GET /api/status': reply(status),
  // Each twin is asked for by its own header: the ones with a name of their own.
  'GET /api/identity': (_url, route) => {
    const asked = route.request().headers()['x-twin-persona'];
    return asked === 'p-helper'
      ? {
          ...identity,
          name: '备忘助手',
          about: '记下我随手想到的事。',
          avatar_preset: 'stone',
        }
      : asked === 'p-public'
        ? {
            ...identity,
            name: '王屿',
            about: '做增长的，爱跑步。',
            avatar_preset: 'bun',
          }
        : asked === 'p-qinghe'
          ? {
              ...identity,
              name: '许清禾',
              about: '做需求评审，也带新人。',
              avatar_preset: 'wave',
            }
          : identity;
  },
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
      headroom_bytes: 50 * 1024 ** 3,
    },
  }),
  // 第 19 屏: a transcript file read before it is brought in; two names are members', two are not.
  'POST /api/library/transcripts/preview': reply({
    title: '运营周会-10月18日',
    date: '2026-10-18',
    speakers: [
      {
        label: '林舟',
        segments: 23,
        sample: '大家好，今天过一下渠道数据。',
        person: { id: 'u-linzhou', name: '林舟' },
      },
      {
        label: '许清禾',
        segments: 17,
        sample: '我这边周三前补齐。',
        person: { id: 'u-qinghe', name: '许清禾' },
      },
      {
        label: '说话人 3',
        segments: 6,
        sample: '下周把渠道数据拉一下',
        person: null,
      },
      {
        label: 'Kevin',
        segments: 4,
        sample: '合同这周能签吗',
        person: null,
      },
    ],
  }),
  // Bringing it in: filed as a transcript with the two speakers the names did not settle left to settle.
  'POST /api/library/transcripts': reply({
    id: 'r-transcript',
    filename: '运营周会-10月18日.docx',
    kind: 'transcript',
    status: 'ready',
    new: true,
    decided: 2,
    unsettled: 2,
  }),
  // Read for what each file is: one with 纪要 in its name is minutes, the rest are transcripts, named back.
  'POST /api/library/minutes/read': (_url, route) => {
    const names = [
      ...(route.request().postDataBuffer()?.toString('utf8') ?? '').matchAll(
        /filename="([^"]+)"/gu,
      ),
    ].map((found) => found[1]);
    const minutes = names.filter((name) => name.includes('纪要'));
    return {
      transcripts: names.filter((name) => !name.includes('纪要')),
      unreadable: [],
      skipped: minutes.length ? 1 : 0,
      added: minutes.length ? 2 : 0,
    };
  },
  // One file of two meetings' minutes: one matched by its day, the other to choose.
  'GET /api/library/minutes/pending': reply({
    items: [
      {
        id: 'pm-1',
        filename: '10月会议纪要汇总.docx',
        title: '10月15日 产品周会',
        part: 1,
        parts: 2,
        day: '2026-10-15',
        how: '当天唯一',
        matched: true,
        proposal: {
          id: 'r-weekly',
          filename: '2026-10-15 产品周会.m4a',
          day: '2026-10-15',
        },
        choices: [],
      },
      {
        id: 'pm-2',
        filename: '10月会议纪要汇总.docx',
        title: '评审会',
        part: 2,
        parts: 2,
        day: null,
        how: '没有日期',
        matched: false,
        proposal: null,
        choices: [
          {
            id: 'r-retro',
            filename: '2026-10-16 迭代复盘.m4a',
            day: '2026-10-16',
          },
          {
            id: 'r-review',
            filename: '2026-10-12 需求评审.mp4',
            day: '2026-10-12',
          },
        ],
      },
    ],
  }),
  'GET /api/library/people': reply({ items: people, matches: [] }),
  // A sample of 许清禾's sounds like 林舟: the team page offers the administrator to hear the two side by side.
  'GET /api/library/voice-clashes': reply([
    {
      score: 0.91,
      together: true,
      samples: [
        {
          id: 1,
          person_id: 'u-linzhou',
          name: '林舟',
          recording_id: 'r-weekly',
          filename: '2026-10-15 产品周会.m4a',
          speaker_id: 'S1',
          seconds: 1260,
          unlike_own: false,
          gone: false,
        },
        {
          id: 2,
          person_id: 'u-qinghe',
          name: '许清禾',
          recording_id: 'r-review',
          filename: '2026-10-12 需求评审.mp4',
          speaker_id: 'S2',
          seconds: 540,
          unlike_own: true,
          gone: false,
        },
      ],
    },
  ]),
  // 需求评审 was transcribed by an older service: the library offers to collect it again.
  'GET /api/library/recollect': reply({
    service: '1.4.1/overlap',
    recordings: [
      {
        id: 'r-review',
        filename: '2026-10-12 需求评审.mp4',
        asr: '1.3.3',
        asked: null,
      },
    ],
    done: [],
  }),
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
  'GET /api/library/review': (url) =>
    reviewPage(url, {
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
          roi: 3,
        },
        // Many voices wait, the quickest to answer first (``team.roi``); those heard in one recording only and like
        // nobody known, and the rest, folded away.
        ...[
          {
            id: 'voice_sure',
            seconds: 800,
            candidates: [
              {
                person_id: 'u-qinghe',
                name: '许清禾',
                score: 0.93,
                sure: true,
              },
            ],
            roi: 1,
          },
          // Not surely 周石言, but far ahead of everyone else: offered for Enter.
          {
            id: 'voice_mid',
            seconds: 750,
            tier: 'mid',
            candidates: [
              { person_id: 'u-shiyan', name: '周石言', score: 0.66 },
            ],
            roi: 1,
          },
          {
            id: 'voice_called',
            seconds: 700,
            called: '老宋',
            quote: '老宋你那边排期怎么样',
            candidates: [],
            roi: 1,
          },
          { id: 'voice_blank', seconds: 500, candidates: [], roi: 4 },
          {
            id: 'voice_split',
            seconds: 400,
            candidates: [
              { person_id: 'u-linzhou', name: '林舟', score: 0.8, split: true },
            ],
            roi: 3,
          },
          // Two people too alike to tell apart: one of the two.
          {
            id: 'voice_short_1',
            seconds: 120,
            near: true,
            candidates: [
              { person_id: 'u-linzhou', name: '林舟', score: 0.62 },
              { person_id: 'u-qinghe', name: '许清禾', score: 0.6 },
            ],
            roi: 2,
          },
          { id: 'voice_short_2', seconds: 90, candidates: [], roi: 4 },
          {
            id: 'voice_enough',
            seconds: 60,
            enough: true,
            had: 3000,
            candidates: [
              { person_id: 'u-linzhou', name: '林舟', score: 0.9, sure: true },
            ],
          },
          { id: 'voice_stranger', seconds: 50, stranger: true, candidates: [] },
        ].map((voice) => ({
          near: false,
          members: [
            {
              recording_id: 'r-weekly',
              filename: weekly.filename,
              transcript_id: weekly.transcript_id,
              speaker_id: 'S4',
              seconds: voice.seconds,
            },
          ],
          ...voice,
        })),
      ],
      fragments: [
        {
          recording_id: 'r-weekly',
          filename: weekly.filename,
          transcript_id: weekly.transcript_id,
          speaker_id: 'S4',
          seconds: 6,
          like: null,
        },
      ],
      unsorted: [],
      heard: { settled: 7920, total: 12600 },
    }),
  'GET /api/library/recordings/r-weekly': reply(weekly),
  'POST /api/library/recordings/r-broken/retry': reply({
    ...recordings.find((r) => r.id === 'r-broken'),
    status: 'queued',
    error: '',
  }),
  'GET /api/me/assets': reply({
    portrait: null,
    voice: null,
    speech_clone: false,
    video: false,
    consent: { portrait: false, voice: false },
    consent_texts: { portrait: '', voice: '' },
  }),
  'GET /api/persona/state': reply({ stale: false }),
  'GET /api/persona/pace': reply({
    pace: { kind: 'off', limit: 30 },
    used: null,
    reminder: null,
  }),
  'GET /api/conversations': reply(history),
  'GET /api/personas/conversations': reply(everyone(null)),
  'GET /api/conversations/c-plan': reply(conversation),
  'GET /api/conversations/c-heir': reply(heirConversation),
  // 我是继承人 (P2.7): the right name and word, the first time, before the seal is confirmed.
  'POST /api/heir/open': reply({ status: 'confirm' }),
  'GET /api/conversations/c-handoff': reply(handoffConversation),
  'GET /api/conversations/c-team': reply(teamConversation),
  'GET /api/conversations/c-deleg': reply(delegationConversation),
  'GET /api/persona/delegations/d-1': reply(delegationView),
  'GET /api/persona/team-answers': reply({ team_answers: myTeamAnswers }),
  'GET /api/conversations/c-lens': reply(lensConversation),
  // 第 12、13 屏: the person's lens, its uses, and how a lens reads before it is published.
  'GET /api/persona/lenses': reply(lensList),
  'GET /api/persona/lenses/l-1/uses': reply({ uses: lensUses }),
  'POST /api/persona/lenses/preview': reply(lensPreview),
  // A colleague is offered no lens unless a page says so.
  'GET /api/persona/lenses/available': reply({ lenses: [] }),
  // 第 16 屏: one question to the whole team: the answer it has, whom to ask, the meetings.
  'GET /api/personas/ask': reply({
    team_answers: [
      {
        ...teamAnswerCard,
        id: 'ta-9',
        persona_id: 'p-qinghe',
        owner_name: '许清禾',
        title: '续约折扣谁能批？',
        body: '15% 以内销售负责人自己定，超过 15% 报许清禾批，当天回复。',
        confirmed_at: '2026-10-09T09:00:00Z',
      },
    ],
    people: [
      {
        persona_id: 'p-public',
        name: '王屿',
        level: 3,
        label: '了解较多',
        occasions: 7,
        last_seen: '2026-10-18',
        facets: ['熟悉领域的看法'],
      },
      {
        persona_id: 'p-qinghe',
        name: '许清禾',
        level: 2,
        label: '了解一些',
        occasions: 3,
        last_seen: '2026-10-09',
        facets: ['各领域立场'],
      },
    ],
    meetings: [
      {
        recording_id: 'r-weekly',
        title: '季度复盘',
        date: '2026-10-18',
        speaker: '王屿',
        quote: '续约这两家我都让到了 12%，再往下就得找沈总……',
        start: 312,
        line: 2,
      },
    ],
    decision: true,
    degraded: false,
  }),
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
  // 承诺 · 全部: the ledgers of the twins looked after, a meeting several were in counted once.
  'GET /api/personas/commitments': reply({
    entries: [
      {
        entry_id: 'l-retention',
        source_id: 'src_lib_r-weekly_aaaaaaaaaaaa',
        meeting: 'r-weekly',
        persona_id: 'default',
        persona_name: '林舟',
        kind: 'commitment',
        kind_label: '承诺',
        speaker: '赵晴',
        quote: '留存口径我来重算，周五前按活跃用户出一版。',
        quote_exact: true,
        owner: '赵晴',
        counterpart: '林舟',
        what: '周五前按活跃用户重算留存口径',
        due: '2026-10-16',
        due_text: '周五前',
        condition: '',
        relates_to: null,
        status: null,
        status_label: null,
        current_status: 'open',
        current_status_label: '进行中',
        confidence: 0.9,
        review: 'confirmed',
        version: 1,
        thread: 'l-retention',
        confirmation_message: null,
        meeting_title: '产品周会',
        meeting_date: '2026-10-15',
      },
      {
        entry_id: 'l-channel',
        source_id: 'src_lib_r-weekly_bbbbbbbbbbbb',
        meeting: 'r-weekly',
        persona_id: 'p-qinghe',
        persona_name: '许清禾',
        kind: 'commitment',
        kind_label: '承诺',
        speaker: '许清禾',
        quote: '渠道数据我这边周三前补齐。',
        quote_exact: true,
        owner: '许清禾',
        counterpart: '',
        what: '周三前补齐渠道数据',
        due: '2026-10-21',
        due_text: '周三前',
        condition: '',
        relates_to: null,
        status: null,
        status_label: null,
        current_status: 'open',
        current_status_label: '进行中',
        confidence: 0.8,
        review: 'unreviewed',
        version: 1,
        thread: 'l-channel',
        confirmation_message: null,
        meeting_title: '产品周会',
        meeting_date: '2026-10-15',
      },
    ],
    people: ['赵晴', '许清禾'],
    meetings: { total: 2, pending: 0 },
    twins: [
      { id: 'default', name: '林舟' },
      { id: 'p-qinghe', name: '许清禾' },
    ],
    job_id: null,
    kind_labels: {
      decision: '决定',
      commitment: '承诺',
      objection: '异议',
      progress: '进展',
    },
    status_labels: {
      open: '进行中',
      claimed_done: '本人称已完成',
      evidenced: '已有交付证据',
      confirmed_done: '对方确认完成',
      not_done: '未完成',
      reopened: '重新打开',
      unknown: '未知',
      pending_accept: '待你接受',
    },
  }),
  // 补一补: the next questions, an answer read into drafts, and what keeping them is worth.
  'GET /api/persona/fill': reply({
    questions: [
      {
        id: 'q17',
        text: '最近有什么事占了你比较多的时间或心思？现在怎么样了？',
        facet: '8.1',
        facet_name: '近期重点',
        level: 0,
        level_label: '还不了解',
        tier: 'colleague',
      },
      {
        id: 'q03',
        text: '生活里你最看重什么？可以举一件让你觉得值得的事。',
        facet: '2.1',
        facet_name: '核心价值排序',
        level: 1,
        level_label: '提到过',
        tier: 'colleague',
      },
    ],
  }),
  'POST /api/persona/fill/draft': reply({
    drafts: [
      {
        facet: '8.1',
        facet_name: '近期重点',
        statement: '在推知识库检索改版，月底前要提高命中率',
        tier: 'colleague',
      },
      {
        facet: '8.2',
        facet_name: '正在做的事',
        statement: '在带两个新人熟悉评审流程',
        tier: 'colleague',
      },
    ],
    changes: [
      {
        facet_id: '8.1',
        facet: '近期重点',
        before: 0,
        after: 1,
        before_label: '还不了解',
        after_label: '提到过',
      },
    ],
  }),
  // 员工 1b: what the twin made from a person's recognised voices has gathered of their commitments.
  'GET /api/persona/ledger': reply({
    entries: [
      {
        entry_id: 'l-retention',
        source_id: 'm-weekly',
        kind: 'commitment',
        kind_label: '承诺',
        speaker: '赵晴',
        quote: '留存口径我来重算，周五前按活跃用户出一版。',
        quote_exact: true,
        owner: '赵晴',
        counterpart: '林舟',
        what: '周五前按活跃用户重算留存口径',
        due: '2026-10-16',
        due_text: '周五前',
        condition: '',
        relates_to: null,
        status: null,
        status_label: null,
        current_status: 'open',
        current_status_label: '进行中',
        confidence: 0.9,
        review: 'confirmed',
        version: 1,
        thread: 'l-retention',
        confirmation_message: null,
        meeting_title: '产品周会',
        meeting_date: '2026-10-15',
      },
      {
        entry_id: 'l-renewal',
        source_id: 'm-monday',
        kind: 'commitment',
        kind_label: '承诺',
        speaker: '赵晴',
        quote: '续费方案我周四前给到大家。',
        quote_exact: true,
        owner: '赵晴',
        counterpart: '',
        what: '周四前给出续费方案',
        due: '2026-10-15',
        due_text: '周四前',
        condition: '',
        relates_to: null,
        status: null,
        status_label: null,
        current_status: 'claimed_done',
        current_status_label: '本人称已完成',
        confidence: 0.9,
        review: 'confirmed',
        version: 1,
        thread: 'l-renewal',
        confirmation_message: null,
        meeting_title: '周一经营会',
        meeting_date: '2026-10-12',
      },
    ],
    people: ['赵晴'],
    meetings: { total: 2, pending: 0 },
    job_id: null,
    kind_labels: {
      decision: '决定',
      commitment: '承诺',
      objection: '异议',
      progress: '进展',
    },
    status_labels: {
      open: '进行中',
      claimed_done: '本人称已完成',
      evidenced: '已有交付证据',
      confirmed_done: '对方确认完成',
      not_done: '未完成',
      reopened: '重新打开',
      unknown: '未知',
    },
  }),
  'GET /api/jobs': reply([]),
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
  // A task done: the ask, what came back and the file made.
  'GET /api/persona/work/w_000000000001': reply({
    task_id: 'w_000000000001',
    title: '按我的口吻写一份本周周报',
    status: 'idle',
    error: null,
    job_id: null,
    created_at: '2026-10-17T01:10:00Z',
    updated_at: '2026-10-17T01:20:00Z',
    turns: [
      {
        role: 'user',
        content: '按我的口吻写一份本周周报',
        at: '2026-10-17T01:10:00Z',
        steps: [],
        files: [],
      },
      {
        role: 'assistant',
        content: '周报写好了：本周发布排期定在下周二，大文件导入再测一轮。',
        at: '2026-10-17T01:20:00Z',
        steps: ['回想：本周的会议', '写 Word：周报.docx'],
        files: ['周报.docx'],
      },
    ],
    files: [{ path: '周报.docx', size: 37337 }],
    progress: [],
    stopping: false,
  }),
  // The years the person's own conversation can look back to (时间切片) start at ``since``.
  'GET /api/persona/life-story': () => ({
    years: [],
    undated: [],
    since: 2019,
  }),
  // 数字遗嘱: two heirs, one given whole aspects and a facet until a day, one given nothing yet.
  'GET /api/persona/will': () => ({ heirs: willHeirs, sealed: false }),
  'GET /api/persona/will/history': () => ({
    changes: [
      {
        at: '2026-10-12T21:05:00',
        actor: 'self',
        action: 'add',
        heir_id: 'heir_yu',
        changes: [],
        heirs: willHeirs.slice(0, 1),
      },
      {
        at: '2026-10-15T09:30:00',
        actor: 'self',
        action: 'add',
        heir_id: 'heir_zhou',
        changes: [],
        heirs: willHeirs,
      },
      {
        at: '2026-10-16T20:12:00',
        actor: 'self',
        action: 'update',
        heir_id: 'heir_yu',
        changes: ['aspects', 'retire_on'],
        heirs: willHeirs,
      },
    ],
  }),
  'GET /api/persona/handoffs': reply(away),
  'GET /api/persona/handoffs/count': reply({ pending: away.pending }),
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
