import { expect, test, type Page } from '@playwright/test';
import { mockApi, newTwin, NOW, weekly } from './mockApi';

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
  { name: 'team-todo', path: '/#/team?tab=todo', ready: '新出现的声音' },
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
  { name: 'twins', path: '/#/twins', ready: '周石言' },
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
  {
    name: 'system-params',
    path: '/#/team?system=params',
    ready: '每人排队转写上限（条）',
    viewport: true,
  },
  {
    name: 'system-upgrades',
    path: '/#/team?system=upgrades',
    ready: '全部升级（1 个分身）',
    viewport: true,
  },
  { name: 'profile', path: '/#/profile', ready: '最有把握的几点' },
  {
    name: 'memories',
    path: '/#/profile?section=memories',
    ready: '发布流程笔记.md',
  },
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
    // A new twin, opened from the twins page or a member's first sign-in.
    name: 'twins-create',
    path: '/#/twins?create=1',
    ready: '创建并开始',
  },
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
  const panel = page.getByRole('tabpanel', { name: /人物/u });
  // The people's rows of the team table, below its header row.
  const rows = panel
    .getByRole('row')
    .filter({ hasNot: page.getByRole('columnheader') });
  const more = page.getByRole('button', { name: '继续加载人物' });
  await expect(rows).toHaveCount(18);
  await more.scrollIntoViewIfNeeded();
  await expect(rows).toHaveCount(36);
  await more.scrollIntoViewIfNeeded();
  await expect(rows).toHaveCount(41);
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
  await page.goto('/#/profile?section=memories');
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
  // When the answer was made is beside it; what it rests on opens from the "…" at its end.
  await page.locator('summary', { hasText: '处理详情' }).last().click();
  await expect(page.getByRole('button', { name: /^依据 · / })).toBeVisible();
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
      page.getByRole('heading', { name: '林舟 / 下周发布怎么安排' }),
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
  await page
    .getByRole('button', { name: mobile ? '打开形象' : '形象', exact: true })
    .click();
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
