import { expect, test, type Page } from '@playwright/test';
import {
  awayMerged,
  lensChoices,
  lensList,
  mockApi,
  newTwin,
  NOW,
  ownAssistant,
  personas,
  status,
  weekly,
} from './mockApi';

// Each key page, on a desktop and a 375px phone (see playwright.config.ts). `ready` is text that only shows once
// the page's data has arrived, so the shot never catches a loading skeleton.
/** Signed out, with the company sign-in and twin's own accounts offered (`byEmail`: a code by e-mail, not a password). */
async function signInWithSso(page: Page, byEmail = false) {
  await page.route('**/api/whoami', (route) =>
    route.fulfill({
      status: 401,
      json: { detail: '请先登录', code: 'login_required' },
    }),
  );
  await page.route('**/api/auth/methods', (route) =>
    route.fulfill({
      json: {
        sso: {
          start_url: '/auth/start?next=/twin/',
          login_url: '/login?next=/twin/',
        },
        password: !byEmail,
        email: byEmail,
        team_name: '产品研发部',
      },
    }),
  );
}

const pages: {
  name: string;
  path: string;
  ready: string;
  /** Dialogs are fixed to the viewport: shoot just that, not the page scrolled behind. */
  viewport?: boolean;
  setup?: (page: Page) => Promise<unknown>;
}[] = [
  { name: 'team', path: '/#/team', ready: '全部录音（' },
  // 第 8 屏: what waits for the owner, the new voices first, each answered with a button.
  { name: 'inbox', path: '/#/inbox', ready: '新的声音' },
  // 第 9 屏: the same voices one at a time, with who they may be to hear beside them.
  { name: 'inbox-focus', path: '/#/inbox?view=focus', ready: '这是谁？' },
  // 承诺: one person's commitments, chosen in the page.
  {
    name: 'commitments',
    path: '/#/commitments',
    ready: '周五前按活跃用户重算留存口径',
  },
  // 承诺 · 全部: every twin's ledger as one list.
  {
    name: 'commitments-all',
    path: '/#/commitments?who=all',
    ready: '周三前补齐渠道数据',
  },
  { name: 'library', path: '/#/library', ready: '2026-10-15 产品周会.m4a' },
  {
    name: 'recording',
    path: '/#/library/r-weekly',
    ready: 'S3 是谁？',
  },
  {
    // Someone identified in a colleague's meeting reads it, and may say a speaker given to them is not them.
    name: 'recording-attendee',
    path: '/#/library/r-weekly',
    ready: '你参加了这场会',
    setup: (page) =>
      page.route('**/api/library/recordings/r-weekly', (route) =>
        route.fulfill({
          json: {
            ...weekly,
            can_edit: false,
            mine: ['S2'],
            // Whom the voices resemble is for the uploader only.
            speakers: weekly.speakers.map((speaker) => ({
              ...speaker,
              candidates: undefined,
              rejected: undefined,
              near: undefined,
            })),
          },
        }),
      ),
  },
  {
    name: 'chat',
    path: '/#/chat',
    ready: '我会先把发布时间定在下周二',
    setup: (page) =>
      page.addInitScript(() =>
        localStorage.setItem('twin.current.conversation', 'c-plan'),
      ),
  },
  {
    // What the twin left to its person, and the person's own reply under it, marked as theirs.
    name: 'chat-handoff',
    path: '/#/chat',
    ready: '方案周五前给你。大文件导入先不放这次。',
    setup: (page) =>
      page.addInitScript(() =>
        localStorage.setItem('twin.current.conversation', 'c-handoff'),
      ),
  },
  {
    // 第 15 屏: the team's answer as a card of its own above what the twin says, and a doubtful one dashed.
    name: 'chat-team-answer',
    path: '/#/chat',
    ready: '这条可能变了，以林舟本人为准。',
    setup: (page) =>
      page.addInitScript(() =>
        localStorage.setItem('twin.current.conversation', 'c-team'),
      ),
  },
  {
    // A colleague talking to someone else's public twin: a line under the box says its person reads the answers.
    name: 'chat-colleague',
    path: '/#/chat',
    ready: '本人看得到分身的回答',
    setup: async (page) => {
      await page.route('**/api/whoami', (route) =>
        route.fulfill({
          json: {
            email: 'me@example.com',
            admin: false,
            auth_enabled: true,
            team_name: '产品研发部',
          },
        }),
      );
      await page.route('**/api/personas', (route) =>
        route.fulfill({ json: personas.filter((p) => p.id === 'p-public') }),
      );
      await page.addInitScript(() => {
        localStorage.setItem('twin:persona', 'p-public');
        localStorage.setItem('twin.current.conversation', 'c-plan');
      });
    },
  },
  {
    // 第 12 屏的另一端: a colleague asked the lens of someone else's twin; the statements, their basis and who to ask.
    name: 'chat-lens',
    path: '/#/chat',
    ready: '根据王屿说过的话推测，不代表王屿的意见',
    setup: async (page) => {
      await page.route('**/api/whoami', (route) =>
        route.fulfill({
          json: {
            email: 'me@example.com',
            admin: false,
            auth_enabled: true,
            team_name: '产品研发部',
          },
        }),
      );
      await page.route('**/api/personas', (route) =>
        route.fulfill({ json: personas.filter((p) => p.id === 'p-public') }),
      );
      await page.route('**/api/status', (route) =>
        route.fulfill({ json: { ...status, target_name: '王屿' } }),
      );
      await page.route('**/api/persona/lenses/available', (route) =>
        route.fulfill({ json: lensChoices }),
      );
      await page.addInitScript(() => {
        localStorage.setItem('twin:persona', 'p-public');
        localStorage.setItem(
          'twin.persona:p-public:twin.current.conversation',
          'c-lens',
        );
      });
    },
  },
  {
    // Right after a twin is made: its chat, with a recording added and the speakers to pick from.
    name: 'chat-setup',
    path: '/#/chat',
    ready: '这个版本先别上',
    setup: async (page) => {
      for (const [path, json] of [
        ['**/api/identity', newTwin.identity],
        ['**/api/status', newTwin.status],
        [/\/api\/persona\/sources\?/u, newTwin.sources],
        ['**/api/persona/sources/s-new/speakers', newTwin.speakers],
        ['**/api/conversations', []],
      ] as const)
        await page.route(path, (route) => route.fulfill({ json }));
    },
  },
  // 第 4 屏: the twins deleted in the last days, to bring back.
  { name: 'team-deleted', path: '/#/team?tab=trash', ready: '旧版助手' },
  { name: 'work', path: '/#/work', ready: '按我的口吻写一份本周周报' },
  {
    name: 'system',
    path: '/#/team?system=monitor',
    ready: 'GPU 机器上的服务',
    viewport: true,
  },
  {
    name: 'system-tokens',
    path: '/#/team?system=tokens',
    ready: 'TWIN_LLM_KEY',
    viewport: true,
  },
  // The team's name, for the side bar and the way in.
  {
    name: 'system-team',
    path: '/#/team?system=team',
    ready: '团队名',
    viewport: true,
  },
  {
    name: 'system-params',
    path: '/#/team?system=params',
    ready: '每人排队转写上限（条）',
    viewport: true,
  },
  {
    name: 'system-library',
    path: '/#/team?system=library',
    ready: '排队转写',
    viewport: true,
  },
  {
    name: 'system-upgrades',
    path: '/#/team?system=upgrades',
    ready: '全部升级（1 个分身）',
    viewport: true,
  },
  // 第 5 屏: a member's page, from the team table (林舟, whose twin is the one in view).
  { name: 'member', path: '/#/team/u-linzhou', ready: '最有把握的几点' },
  // Someone else's page, seen by whoever looks after the twin: each aspect ends with the way to ask her for more.
  {
    name: 'member-ask',
    path: '/#/team/u-qinghe',
    ready: '请许清禾补充 ›',
    setup: (page) =>
      page.route('**/api/whoami', (route) =>
        route.fulfill({
          json: {
            email: 'chen.yi@example.com',
            name: '陈一',
            admin: true,
            auth_enabled: true,
            team_name: '产品研发部',
          },
        }),
      ),
  },
  {
    name: 'member-memories',
    path: '/#/team/u-linzhou?section=memories',
    ready: '发布流程笔记.md',
  },
  // 第 10 屏: what the twin left to the person, the answers it guessed, for the person themselves.
  {
    name: 'member-away',
    path: '/#/team/u-linzhou?section=away',
    ready: '分身推测 2',
  },
  // 第 14 屏: three people asked the same thing, one card; a reply the twin keeps giving; the answers set so far.
  {
    name: 'member-away-merged',
    path: '/#/team/u-linzhou?section=away',
    ready: '3 人问同一件事',
    setup: (page) =>
      page.route('**/api/persona/handoffs', (route) =>
        route.fulfill({ json: awayMerged }),
      ),
  },
  // 我设的团队答案: what the person made the team's, one of them possibly out of date.
  {
    name: 'member-team-answers',
    path: '/#/team/u-linzhou?section=memories&view=answers',
    ready: '续约折扣谁能批？',
  },
  // 第 13 屏: the person's lens, what it was used for and not by whom, and a facet corrected out.
  {
    name: 'member-lens',
    path: '/#/team/u-linzhou?section=lens',
    ready: '最近被用在哪',
  },
  {
    name: 'member-assets',
    path: '/#/team/u-linzhou?section=assets',
    ready: '预置音色',
  },
  // A twin made by hand, which no recording belongs to, at its own address.
  {
    name: 'member-twin',
    path: '/#/team/twin/p-helper',
    ready: '记下我随手想到的事。',
  },
  // Someone someone else made public: its name and the way to talk to it.
  { name: 'member-public', path: '/#/team/twin/p-public', ready: '和王屿聊天' },
  // Someone found in the recordings who has no twin yet: the meetings they spoke in.
  { name: 'member-no-twin', path: '/#/team/u-shiyan', ready: '参加过的录音' },
  {
    // 员工 1b: signed in through the company login with no twin made for them.
    name: 'member-voice',
    path: '/#/chat',
    ready: '留存口径我来重算',
    setup: async (page) => {
      await page.route('**/api/whoami', (route) =>
        route.fulfill({
          json: {
            email: 'sso:1001',
            name: '赵晴',
            address: 'zhaoqing@acme.cn',
            admin: false,
            auth_enabled: true,
            provider: 'sso',
          },
        }),
      );
      await page.route('**/api/personas', (route) =>
        route.fulfill({ json: [] }),
      );
      for (const path of ['**/api/identity', '**/api/status'])
        await page.route(path, (route) =>
          route.fulfill({
            status: 409,
            json: { detail: '先新建一个分身', code: 'no_persona' },
          }),
        );
    },
  },
  {
    // 第 2 屏: nothing uploaded yet. The way to the first recording, what happens to it, and asking colleagues in.
    name: 'first-run',
    path: '/#/team',
    ready: '把会议录音拖到这里',
    setup: async (page) => {
      await page.route('**/api/library', (route) =>
        route.fulfill({
          json: {
            recordings: [],
            pending: 0,
            max_pending: 20,
            asr: true,
            capacity: {
              free_bytes: 120 * 1024 ** 3,
              arriving_bytes: 0,
              arriving: 0,
              headroom_bytes: 20 * 1024 ** 3,
            },
          },
        }),
      );
      await page.route('**/api/library/people', (route) =>
        route.fulfill({ json: { items: [] } }),
      );
      await page.route('**/api/library/review', (route) =>
        route.fulfill({
          json: { items: [], voices: [], fragments: [], unsorted: [] },
        }),
      );
    },
  },
  {
    // 第 3 屏, step 2: the twin made from the voices they recognised, to look at before colleagues can ask it.
    name: 'welcome-claim',
    path: '/#/chat',
    ready: '赵晴，你的分身已经建好了',
    setup: async (page) => {
      await page.route('**/api/whoami', (route) =>
        route.fulfill({
          json: {
            email: 'sso:1001',
            name: '赵晴',
            address: 'zhaoqing@acme.cn',
            admin: false,
            auth_enabled: true,
            provider: 'sso',
          },
        }),
      );
      await page.route('**/api/personas', (route) =>
        route.fulfill({
          json: [
            {
              id: 'p-zhaoqing',
              name: '赵晴',
              avatar_url: null,
              avatar_preset: 'wave',
              sources: 3,
              created_at: '2026-10-16T02:00:00Z',
              is_default: false,
              can_manage: true,
              mine: true,
              from_meetings: true,
              approved: false,
            },
          ],
        }),
      );
    },
  },
  {
    // A twin account with no twin yet, opening 工作: the workspace stays, with the new-twin card over it.
    name: 'work-no-twin',
    path: '/#/work',
    ready: '创建并开始',
    setup: async (page) => {
      await page.route('**/api/whoami', (route) =>
        route.fulfill({
          json: {
            email: 'user:onboard1',
            name: '测试新人1',
            admin: false,
            auth_enabled: true,
            provider: 'sso',
          },
        }),
      );
      await page.route('**/api/personas', (route) =>
        route.fulfill({ json: [] }),
      );
      for (const path of ['**/api/identity', '**/api/status'])
        await page.route(path, (route) =>
          route.fulfill({
            status: 409,
            json: { detail: '先新建一个分身', code: 'no_persona' },
          }),
        );
    },
  },
  {
    name: 'login',
    path: '/#/chat',
    ready: '用邮箱登录',
    setup: (page) =>
      page.route('**/api/whoami', (route) =>
        route.fulfill({
          status: 401,
          json: { detail: '请先登录', code: 'login_required' },
        }),
      ),
  },
  {
    // The company sign-in, borrowed from another app on the site, with twin's own accounts below it.
    name: 'login-sso',
    path: '/#/chat',
    ready: '用享佳统一身份登录',
    setup: signInWithSso,
  },
  {
    // The company sign-in first; the e-mail code is right below it, already open.
    name: 'login-sso-email',
    path: '/#/chat',
    ready: '或用邮箱验证码',
    setup: (page) => signInWithSso(page, true),
  },
  // The other palettes, as picked on the sign-in page and remembered in this browser.
  ...(['blue', 'ink'] as const).map((theme) => ({
    name: `login-${theme}`,
    path: '/#/chat',
    ready: '用享佳统一身份登录',
    setup: async (page: Page) => {
      await page.addInitScript(
        (picked) => localStorage.setItem('twin:theme', picked),
        theme,
      );
      await signInWithSso(page);
    },
  })),
  {
    name: 'team-ink',
    path: '/#/team',
    ready: '全部录音（',
    setup: (page) =>
      page.addInitScript(() => localStorage.setItem('twin:theme', 'ink')),
  },
];

for (const { name, path, ready, viewport, setup } of pages) {
  test(name, async ({ page }) => {
    const missing: string[] = [];
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.clock.setFixedTime(NOW);
    await mockApi(page, missing);
    await setup?.(page);
    await page.goto(path);
    await expect(page.getByText(ready).first()).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await expect(page).toHaveScreenshot(
      `${name}-${test.info().project.name}.png`,
      { fullPage: !viewport },
    );
    expect(errors, 'page errors').toEqual([]);
    expect(missing, 'requests without a mock in e2e/mockApi.ts').toEqual([]);
  });
}

test('team continues the roster when its last rows scroll into view', async ({
  page,
}) => {
  const missing: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({
    width: page.viewportSize()!.width,
    height: 600,
  });
  await mockApi(page, missing);
  await page.route('**/api/library/people', (route) =>
    route.fulfill({
      json: {
        items: Array.from({ length: 41 }, (_, i) => ({
          id: `scroll-person-${i}`,
          name: `同事${String(i + 1).padStart(2, '0')}`,
          persona_id: null,
          speakers: 1,
          seconds: 5000 - i,
          samples: 1,
          updating: false,
          auto: false,
          gender: '',
        })),
      },
    }),
  );
  await page.goto('/#/team');
  const panel = page.getByRole('tabpanel', { name: /成员/u });
  // The people's rows of the team table, below its header row.
  const rows = panel
    .getByRole('row')
    .filter({ hasNot: page.getByRole('columnheader') });
  const more = page.getByRole('button', { name: '继续加载人物' });
  await expect(rows).toHaveCount(18);
  await more.scrollIntoViewIfNeeded();
  await expect(rows).toHaveCount(36);
  // The 41 people and the twins no recording belongs to (four, in the mock).
  await more.scrollIntoViewIfNeeded();
  await expect(rows).toHaveCount(45);
  await expect(more).toHaveCount(0);
  expect(errors, 'page errors').toEqual([]);
  expect(missing, 'requests without a mock').toEqual([]);
});

test('transcript claim', async ({ page }, info) => {
  const missing: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.clock.setFixedTime(NOW);
  await mockApi(page, missing);
  await page.goto('/#/team/u-linzhou?section=memories');
  await page
    .getByRole('button', { name: '有 3 份文字记录需要确认哪位是你' })
    .click();
  const dialog = page.getByRole('dialog', { name: '哪位是你' });
  await expect(dialog.getByText('2026-10-14 站会')).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await expect(page).toHaveScreenshot(
    `transcript-claim-${info.project.name}.png`,
  );
  expect(errors, 'page errors').toEqual([]);
  expect(missing, 'requests without a mock in e2e/mockApi.ts').toEqual([]);
});

test('import transcript', async ({ page }, info) => {
  const missing: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.clock.setFixedTime(NOW);
  await mockApi(page, missing);
  await page.goto('/#/library');
  await expect(page.getByText('2026-10-11 客户访谈.txt')).toBeVisible();
  // 第 19 屏: the file is read first, and shown with who each speaker would be.
  await page.getByLabel('选择转写稿').setInputFiles({
    name: '运营周会-10月18日.docx',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('x'),
  });
  const dialog = page.getByRole('dialog', { name: '导入转写稿' });
  await expect(dialog.getByText('✓ 林舟')).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await expect(page).toHaveScreenshot(
    `import-transcript-${info.project.name}.png`,
  );
  expect(errors, 'page errors').toEqual([]);
  expect(missing, 'requests without a mock in e2e/mockApi.ts').toEqual([]);
});

test('fill in what the twin does not know', async ({ page }, info) => {
  const missing: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.clock.setFixedTime(NOW);
  await mockApi(page, missing);
  await page.goto('/#/team/u-linzhou');
  await page.getByRole('button', { name: '补一补' }).first().click();
  // 第 18 屏: a question, the answer read into drafts to choose a tier for, and what keeping them is worth.
  const dialog = page.getByRole('dialog', { name: '补一补' });
  await dialog
    .getByRole('textbox', { name: '你的回答' })
    .fill(
      '在推知识库检索改版，月底前要把命中率提上去。另外在带两个新人熟悉评审。',
    );
  await dialog.getByRole('button', { name: '整理' }).click();
  await expect(dialog.getByText('整理成 2 条')).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await expect(page).toHaveScreenshot(`fill-in-${info.project.name}.png`);
  expect(errors, 'page errors').toEqual([]);
  expect(missing, 'requests without a mock in e2e/mockApi.ts').toEqual([]);
});

test('publish a lens', async ({ page }, info) => {
  const missing: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.clock.setFixedTime(NOW);
  await mockApi(page, missing);
  // 第 12 屏: nothing published yet.
  await page.route('**/api/persona/lenses', (route) =>
    route.fulfill({ json: { ...lensList, lenses: [] } }),
  );
  await page.goto('/#/team/u-linzhou?section=lens');
  await page.getByRole('button', { name: '发布赋能' }).click();
  const dialog = page.getByRole('dialog', { name: '发布赋能' });
  await dialog.getByRole('textbox', { name: '名字' }).fill('大客户谈判');
  await dialog.getByRole('checkbox', { name: /依据偏好/ }).check();
  await dialog.getByRole('checkbox', { name: /做事的原则/ }).check();
  await expect(dialog.getByRole('region', { name: '预览' })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await expect(page).toHaveScreenshot(`lens-publish-${info.project.name}.png`);
  expect(errors, 'page errors').toEqual([]);
  expect(missing, 'requests without a mock in e2e/mockApi.ts').toEqual([]);
});

test('ask the whole team with ⌘K', async ({ page }, info) => {
  // The side bar holds the search, and a phone has none (the phones' navigation is not part of this design).
  test.skip(info.project.name === 'mobile', 'no side bar on a phone');
  const missing: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.clock.setFixedTime(NOW);
  await mockApi(page, missing);
  await page.goto('/#/team');
  await expect(page.getByText('全部录音（').first()).toBeVisible();
  // 第 16 屏: the answer the team already has, whom to ask, and the meetings it came up in.
  await page.keyboard.press('ControlOrMeta+k');
  const dialog = page.getByRole('dialog', { name: '问一句、找人' });
  await dialog.getByRole('combobox').fill('续约折扣谁能批');
  await expect(dialog.getByRole('region', { name: '该问谁' })).toBeVisible();
  await expect(dialog.getByRole('region', { name: '会议' })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await expect(page).toHaveScreenshot(`ask-team-${info.project.name}.png`);
  expect(errors, 'page errors').toEqual([]);
  expect(missing, 'requests without a mock in e2e/mockApi.ts').toEqual([]);
});

test('recording controls', async ({ page }) => {
  const missing: string[] = [];
  await mockApi(page, missing);
  await page.goto('/#/library/r-weekly');
  await expect(page.getByRole('heading', { name: 'S3 是谁？' })).toBeVisible();
  await expect(page.locator('audio')).toHaveCount(1);
  await page.getByRole('button', { name: /片段 2/u }).click();
  await expect(page.locator('audio')).toHaveAttribute('src', /samples\/1$/u);
  await page.getByRole('button', { name: /周石言.*声音像 71%/u }).click();
  const confirm = page.getByRole('button', { name: '确认是周石言' });
  await expect(confirm).toBeEnabled();
  const select = page.getByLabel('这是谁');
  await select.click();
  await page.keyboard.press('Escape');
  await select.selectOption('u-qinghe');
  await expect(
    page.getByRole('button', { name: '确认是许清禾' }),
  ).toBeEnabled();
  expect(missing).toEqual([]);
});

test('reply details', async ({ page }, info) => {
  const missing: string[] = [];
  await page.clock.setFixedTime(NOW);
  await mockApi(page, missing);
  await page.addInitScript(() =>
    localStorage.setItem('twin.current.conversation', 'c-plan'),
  );
  await page.goto('/#/chat');
  await expect(
    page.getByText('我会先把发布时间定在下周二').first(),
  ).toBeVisible();
  // When the answer was made is beside it; what it rests on opens from its badge, right under the answer.
  await page.getByRole('button', { name: /^有本人资料支持/ }).click();
  await expect(page.getByRole('list', { name: '回答依据' })).toBeVisible();
  await expect(page).toHaveScreenshot(
    `chat-reply-details-${info.project.name}.png`,
  );
  expect(missing).toEqual([]);
});

test('chat presentation controls', async ({ page }, info) => {
  const missing: string[] = [];
  await page.clock.setFixedTime(NOW);
  await mockApi(page, missing);
  await page.addInitScript(() =>
    localStorage.setItem('twin.current.conversation', 'c-plan'),
  );
  await page.goto('/#/chat');
  await expect(
    page.getByText('我会先把发布时间定在下周二').first(),
  ).toBeVisible();
  const mobile = info.project.name === 'mobile';
  if (!mobile) {
    const active = page
      .getByRole('navigation', { name: '主导航', exact: true })
      .getByRole('link', { name: '对话', exact: true });
    // A full-width row of the wide side bar, raised white when current.
    await expect(active).toHaveCSS('width', '200px');
    await expect(active).toHaveCSS('height', '40px');
    await expect(active).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    await page.getByRole('button', { name: '收起对话列表' }).click();
    await expect(
      page.getByRole('heading', { level: 1, name: '下周发布怎么安排' }),
    ).toBeVisible();
    // With the list folded away, the twin is still switched from its portrait in the header.
    await expect(
      page.getByRole('button', { name: '切换分身（当前：林舟）' }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole('button', { name: '展开对话列表' }),
    ).toBeVisible();
  }
  // The voice and the portrait are behind the header's "…".
  await page.getByLabel('更多：语音、形象').click();
  await page.getByRole('button', { name: '形象', exact: true }).click();
  await expect(
    page.getByRole('complementary', { name: '林舟的形象' }),
  ).toBeVisible();
  await expect
    .soft(page)
    .toHaveScreenshot(`chat-stage-${info.project.name}.png`);
  await page.getByRole('button', { name: '关闭形象' }).click();
  if (!mobile) await page.getByRole('button', { name: '展开对话列表' }).click();
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  if (!mobile) await page.getByRole('button', { name: '收起对话列表' }).click();
  await expect(page.getByRole('heading', { name: '和林舟聊聊' })).toBeVisible();
  await expect(page).toHaveScreenshot(`chat-empty-${info.project.name}.png`);
  expect(missing).toEqual([]);
});

test('the person’s own assistant, set apart above the conversations', async ({
  page,
}, info) => {
  const missing: string[] = [];
  await page.clock.setFixedTime(NOW);
  await mockApi(page, missing);
  await ownAssistant(page);
  await page.goto('/#/chat');
  if (info.project.name === 'mobile')
    await page.getByRole('button', { name: '对话列表' }).click();
  // Only the person has it: it is chosen from the pinned row, and its list is its own.
  await page.getByRole('button', { name: /^我的分身/ }).click();
  await page
    .getByRole('button', { name: /^我上周答应过谁什么(?!的更多操作)/ })
    .click();
  if (info.project.name === 'mobile')
    await expect(page.getByRole('dialog', { name: '对话记录' })).toBeHidden();
  const tiers = page.getByRole('radiogroup', { name: '谁能用这条记忆' });
  await expect(tiers.getByRole('radio', { name: '只有我' })).toBeChecked();
  await expect(page.getByText('仅你可见').first()).toBeVisible();
  await expect(page).toHaveScreenshot(`chat-self-${info.project.name}.png`);
  expect(missing).toEqual([]);
});

test('the assistant asks colleagues’ twins in the person’s name', async ({
  page,
}, info) => {
  const missing: string[] = [];
  await page.clock.setFixedTime(NOW);
  await page.addInitScript(() =>
    localStorage.setItem('twin.current.conversation', 'c-deleg'),
  );
  await mockApi(page, missing);
  await ownAssistant(page, true);
  await page.goto('/#/chat');
  // 第 17 屏: a card for each twin that was asked, what one could not settle, and the assistant's own note.
  await expect(page.getByText('我的归纳 · 非原话')).toBeVisible();
  // The list of the assistant's own has what it asked under 问同事 (a phone has the list behind a button).
  if (info.project.name !== 'mobile') {
    await page.getByRole('button', { name: /^我的分身/ }).click();
    await expect(page.getByRole('region', { name: '问同事' })).toBeVisible();
  }
  await expect(page.getByRole('button', { name: '转给本人' })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await expect(page).toHaveScreenshot(
    `chat-delegation-${info.project.name}.png`,
  );
  expect(missing).toEqual([]);
});

test('a task in the conversation list', async ({ page }, info) => {
  const missing: string[] = [];
  await page.clock.setFixedTime(NOW);
  await mockApi(page, missing);
  await page.goto('/#/chat?mode=task');
  await expect(page.getByRole('radio', { name: '交代任务' })).toBeChecked();
  if (info.project.name === 'mobile')
    await page.getByRole('button', { name: '对话列表' }).click();
  // Tasks sit among the conversations, marked as tasks.
  await page
    .getByRole('button', {
      name: /^按我的口吻写一份本周周报\s*林舟\s*·\s*任务/,
    })
    .click();
  await expect(page.getByText('周报写好了', { exact: false })).toBeVisible();
  await expect(page.getByRole('link', { name: /周报\.docx/ })).toBeVisible();
  await expect(page).toHaveScreenshot(`work-task-${info.project.name}.png`);
  expect(missing).toEqual([]);
});
