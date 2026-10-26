import { expect, test } from '@playwright/test';
import { mockApi, weekly } from './mockApi';

type TestRecording = Omit<typeof weekly, 'speakers'> & {
  speakers: (Omit<(typeof weekly.speakers)[number], 'person_id'> & {
    person_id: string | null;
  })[];
};
function meeting(): TestRecording {
  return {
    ...weekly,
    speakers: weekly.speakers.map((s) => ({
      ...s,
      decision: s.id === 'S4' ? 'unknown' : s.decision,
    })),
  };
}

test('a saved decision waits for readback and refresh never repeats the write', async ({
  page,
}, info) => {
  const missing: string[] = [];
  await mockApi(page, missing);
  let recording = meeting();
  let unavailable = false;
  let writes = 0;
  await page.route('**/api/library/recordings/r-weekly', (route) =>
    unavailable
      ? route.fulfill({ status: 503, json: { detail: '读取暂不可用' } })
      : route.fulfill({ json: recording }),
  );
  await page.route(
    '**/api/library/recordings/r-weekly/speakers/S3',
    (route) => {
      ++writes;
      recording = {
        ...recording,
        revision: recording.revision + 1,
        speakers: recording.speakers.map((s) =>
          s.id === 'S3'
            ? {
                ...s,
                decision: 'confirmed',
                person_id: 'u-qinghe',
                auto: false,
              }
            : s,
        ),
      };
      unavailable = true;
      return route.fulfill({ json: { revision: recording.revision } });
    },
  );
  await page.goto('/#/library/r-weekly');
  await page.getByLabel('这是谁').selectOption('u-qinghe');
  const confirm = page.getByRole('button', {
    name: '确认是许清禾',
    exact: true,
  });
  await confirm.click();
  await expect(page.getByRole('alert')).toHaveText('修改已保存，请刷新确认');
  await expect(confirm).toBeDisabled();
  await expect(page.getByLabel('这是谁')).toHaveValue('u-qinghe');
  if (info.project.name === 'desktop')
    await page.screenshot({
      path: info.outputPath('saved-readback-unavailable.png'),
      fullPage: true,
    });
  unavailable = false;
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(
    page.getByText('这段录音的说话人都确认好了', { exact: true }),
  ).toBeVisible();
  expect(writes).toBe(1);
  if (info.project.name === 'desktop')
    await page.screenshot({
      path: info.outputPath('saved-readback-recovered.png'),
      fullPage: true,
    });
  expect(missing).toEqual([]);
});

for (const saved of [false, true]) {
  test(`a dropped write response reads the actual result without resubmitting (saved=${saved})`, async ({
    page,
  }) => {
    const missing: string[] = [];
    await mockApi(page, missing);
    let recording = meeting();
    let writes = 0;
    await page.route('**/api/library/recordings/r-weekly', (route) =>
      route.fulfill({ json: recording }),
    );
    await page.route(
      '**/api/library/recordings/r-weekly/speakers/S3',
      (route) => {
        ++writes;
        if (saved)
          recording = {
            ...recording,
            revision: recording.revision + 1,
            speakers: recording.speakers.map((s) =>
              s.id === 'S3'
                ? {
                    ...s,
                    decision: 'confirmed',
                    person_id: 'u-qinghe',
                    auto: false,
                  }
                : s,
            ),
          };
        return route.abort('failed');
      },
    );
    await page.goto('/#/library/r-weekly');
    await page.getByLabel('这是谁').selectOption('u-qinghe');
    await page
      .getByRole('button', { name: '确认是许清禾', exact: true })
      .click();
    if (saved)
      await expect(
        page.getByText('这段录音的说话人都确认好了', { exact: true }),
      ).toBeVisible();
    else {
      await expect(
        page.getByRole('button', { name: '确认是许清禾', exact: true }),
      ).toBeEnabled();
      await expect(page.getByLabel('这是谁')).toHaveValue('u-qinghe');
      await expect(
        page.getByText('这段录音的说话人都确认好了', { exact: true }),
      ).toHaveCount(0);
    }
    expect(writes).toBe(1);
    expect(missing).toEqual([]);
  });
}
