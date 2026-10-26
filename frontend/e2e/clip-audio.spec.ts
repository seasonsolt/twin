import { expect, test } from '@playwright/test';
import { mockApi } from './mockApi';

// A playable, synthetic five-second WAV: no codec tool or private meeting is needed to exercise native media.
function silence() {
  const bytes = Buffer.alloc(44 + 16000 * 2 * 5);
  bytes.write('RIFF');
  bytes.writeUInt32LE(bytes.length - 8, 4);
  bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20);
  bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(16000, 24);
  bytes.writeUInt32LE(32000, 28);
  bytes.writeUInt16LE(2, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write('data', 36);
  bytes.writeUInt32LE(bytes.length - 44, 40);
  return bytes;
}

for (const status of [404, 503]) {
  test(`clip retries a real HTTP ${status} and stops when its comparison starts`, async ({
    page,
  }, info) => {
    const missing: string[] = [];
    await mockApi(page, missing);
    let failing = true;
    let failedRequests = 0;
    let successfulRequests = 0;
    await page.route(
      '**/api/library/recordings/demo/speakers/S1/samples/0',
      (route) => {
        if (failing) {
          failedRequests++;
          return route.fulfill({
            status,
            contentType: 'text/plain',
            body: 'synthetic media failure',
          });
        }
        successfulRequests++;
        return route.fulfill({ contentType: 'audio/wav', body: silence() });
      },
    );
    await page.route(
      '**/api/library/recordings/demo/speakers/S2/samples/0',
      (route) => route.fulfill({ contentType: 'audio/wav', body: silence() }),
    );
    await page.goto('/#/gallery');
    await page
      .getByRole('button', { name: '试听片段 ClipButton', exact: true })
      .click();
    const failure = page
      .getByRole('alert')
      .filter({ hasText: '无法试听，请重试' });
    const retry = page.getByRole('button', {
      name: '重试试听片段 ClipButton',
      exact: true,
    });
    await expect(retry).toBeVisible();
    await expect(retry).toHaveAttribute('title', '无法试听，请重试');
    await expect(retry).toHaveAccessibleDescription('无法试听，请重试');
    await expect(failure).toHaveClass('sr-only');
    expect(failedRequests).toBeGreaterThan(0);
    const controls = page
      .getByRole('heading', { name: '控件补充', exact: true })
      .locator('..');
    if (info.project.name === 'desktop')
      await controls.screenshot({ path: info.outputPath('clip-error.png') });
    failing = false;
    await retry.click();
    await expect(
      page.getByRole('button', {
        name: '暂停试听片段 ClipButton',
        exact: true,
      }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(successfulRequests).toBeGreaterThan(0);
    await expect(failure).toHaveCount(0);
    if (info.project.name === 'desktop')
      await controls.screenshot({
        path: info.outputPath('clip-recovered.png'),
      });
    await page
      .getByRole('button', { name: '对照试听 ClipButton caption', exact: true })
      .click();
    await expect(
      page.getByRole('button', {
        name: '暂停对照试听 ClipButton caption',
        exact: true,
      }),
    ).toHaveAttribute('aria-pressed', 'true');
    await expect(
      page.getByRole('button', { name: '试听片段 ClipButton', exact: true }),
    ).toHaveAttribute('aria-pressed', 'false');
    await expect
      .poll(() =>
        controls
          .locator(
            'audio[src="/api/library/recordings/demo/speakers/S1/samples/0"]',
          )
          .evaluate((audio) => (audio as HTMLAudioElement).paused),
      )
      .toBe(true);
    expect(missing).toEqual([]);
  });
}

test('a failed clip stays inside its compact task row', async ({ page }) => {
  const missing: string[] = [];
  await mockApi(page, missing);
  let failing = true;
  await page.route(
    '**/api/library/recordings/demo/speakers/S1/samples/0',
    (route) =>
      failing
        ? route.fulfill({ status: 503, body: 'synthetic media failure' })
        : route.fulfill({ contentType: 'audio/wav', body: silence() }),
  );
  await page.goto('/#/gallery');
  await page.evaluate(() => document.fonts.ready);
  const row = page.getByRole('listitem').filter({ hasText: '像林舟' });
  await expect(row).toHaveCount(1);
  const before = await row.boundingBox();
  expect(before).not.toBeNull();
  await page.getByRole('button', { name: '试听待办示例', exact: true }).click();
  const retry = page.getByRole('button', {
    name: '重试试听待办示例',
    exact: true,
  });
  await expect(retry).toBeVisible();
  await expect(retry).toHaveAccessibleDescription('无法试听，请重试');
  expect(
    await row.evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true);
  expect((await row.boundingBox())?.height).toBe(before!.height);
  failing = false;
  await retry.click();
  await expect(
    page.getByRole('button', { name: '暂停试听待办示例', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  expect(missing).toEqual([]);
});
