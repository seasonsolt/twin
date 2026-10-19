import { expect, test, type Page } from '@playwright/test';
import { mockApi, NOW, weekly } from './mockApi';

// Each key page, on a desktop and a 375px phone (see playwright.config.ts). `ready` is text that only shows once
// the page's data has arrived, so the shot never catches a loading skeleton.
const pages: {
  name: string;
  path: string;
  ready: string;
  /** Dialogs are fixed to the viewport: shoot just that, not the page scrolled behind. */
  viewport?: boolean;
  setup?: (page: Page) => Promise<unknown>;
}[] = [
  { name: 'team', path: '/#/team', ready: '需要你处理' },
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
      .getByRole('link', { name: '聊天', exact: true });
    await expect(active).toHaveCSS('width', '44px');
    await expect(active).toHaveCSS('height', '44px');
    await expect(active).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    await page.getByRole('button', { name: '收起对话列表' }).click();
    await expect(
      page.getByRole('heading', { name: '林舟 / 下周发布怎么安排' }),
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
