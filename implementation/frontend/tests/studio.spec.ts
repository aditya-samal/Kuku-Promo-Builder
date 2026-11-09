import { expect, test } from '@playwright/test';

test('create a project, resume the dashboard, save and export a cut', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Create your first project' })).toBeVisible();
  await page.getByRole('link', { name: 'New project' }).first().click();
  await page.getByLabel('Project name').fill('Browser Studio');
  await page.getByLabel('Episode scripts ZIP').setInputFiles({
    name: 'broken.zip', mimeType: 'application/zip', buffer: Buffer.from('invalid archive'),
  });
  await page.getByRole('button', { name: 'Create project' }).click();
  await expect(page.getByRole('alert')).toContainText('Could not read the ZIP');
  await expect(page.getByLabel('Project name')).toHaveValue('Browser Studio');
  const zip = await request.get('/test/fixture.zip');
  await page.getByLabel('Episode scripts ZIP').setInputFiles({
    name: 'scripts.zip', mimeType: 'application/zip', buffer: await zip.body(),
  });
  await page.getByRole('button', { name: 'Create project' }).click();
  await expect(page.getByRole('heading', { name: 'Browser Studio' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Processing progress' })).toContainText('0 of 1 episodes');
  await page.getByRole('link', { name: 'Back to projects' }).click();
  await expect(page.getByRole('heading', { name: 'Browser Studio' })).toBeVisible();
  await page.getByRole('link', { name: 'Open project' }).click();

  expect((await request.post('/test/process')).ok()).toBeTruthy();
  await expect(page.getByRole('region', { name: 'Ranked promos' })).toContainText('Test promo');
  await page.getByRole('button', { name: /Test promo/ }).click();
  await expect(page.getByRole('heading', { name: 'Script excerpts' })).toBeVisible();
  await expect(page.getByText('JANE', { exact: true })).toBeVisible();
  await expect(page.getByRole('progressbar', { name: 'hook' })).toHaveAttribute('value', '85');
  await page.getByRole('button', { name: 'Save promo' }).click();
  await expect(page.getByRole('button', { name: 'Saved', exact: true })).toBeVisible();
  await page.getByRole('link', { name: /Saved promos/ }).click();
  await expect(page.getByRole('region', { name: 'Saved promos' })).toContainText('Test promo');
  await page.reload();
  await expect(page.getByRole('region', { name: 'Saved promos' })).toContainText('Test promo');
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export CSV' }).click();
  expect((await download).suggestedFilename()).toBe('kuku-promos.csv');
  await page.getByRole('button', { name: 'Remove' }).click();
  await expect(page.getByRole('heading', { name: 'No saved promos yet' })).toBeVisible();
  await page.getByRole('link', { name: 'Go to Results' }).click();
  await expect(page.getByRole('region', { name: 'Ranked promos' })).toContainText('Test promo');
});
