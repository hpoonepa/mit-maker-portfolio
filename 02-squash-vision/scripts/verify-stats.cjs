// Checks displayed tracking numbers, player filters and evidence seeking.
const { chromium, expect } = require('../src/squashvision/web/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const base = 'http://127.0.0.1:8950';
  const id = '5ebf3351-5a26-48c0-839b-5da930aa7913';
  const out = path.resolve(__dirname, '../runtime/browser-review');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  const checks = [];
  page.on('pageerror', error => errors.push(error.message));
  const response = await page.request.get(`${base}/api/v1/matches/${id}/reports/2/tracking-stats`);
  assert(response.ok(), `Stats API returned ${response.status()}`);
  const stats = await response.json();
  assert.equal(stats.calibrationRevision, 1);
  assert.equal(stats.reportRevision, 2);
  assert(stats.calibrationAvailable);
  await page.goto(`${base}/matches/${id}/analysis`);
  const panel = page.getByRole('region', { name: 'Tracking stats', exact: true });
  await expect(panel).toBeVisible();
  for (const player of stats.players) {
    await expect(panel.locator(`.tracking-stats__metric--${player.playerId.toLowerCase()} dd`))
      .toContainText(player.distanceM.toFixed(1));
  }
  await expect(panel.locator('.tracking-stats__metric').last()).toContainText(stats.ballSpeed.medianMps.toFixed(1));
  await expect(panel).toContainText('Ball speed assumes motion on the floor plane.');
  await expect(panel).toContainText('A/B identities unverified.');
  checks.push('Actual calibrated measurements, partial coverage and assumptions are visible');
  await panel.screenshot({ path: `${out}/stats-compact.png` });
  await panel.locator('.tracking-stats__details > summary').click();
  await expect(panel.locator('tbody tr')).toHaveCount(stats.contacts.length);
  await expect(panel.locator('.tracking-stats__point')).toHaveCount(stats.contacts.filter(c => c.position !== null).length);
  const mapped = stats.contacts.find(c => c.position !== null && c.proxyTimestampUs !== null);
  assert(mapped, 'Expected an actual mapped contact');
  await panel.getByRole('button', { name: `Player ${mapped.hitter}`, exact: true }).click();
  const playerContacts = stats.contacts.filter(c => c.hitter === mapped.hitter);
  await expect(panel.locator('tbody tr')).toHaveCount(playerContacts.length);
  const rowIndex = playerContacts.findIndex(c => c.id === mapped.id);
  const mappedRow = panel.locator('tbody tr').nth(rowIndex);
  await expect(mappedRow).toContainText(`${mapped.position[0].toFixed(2)} / ${mapped.position[1].toFixed(2)}`);
  await mappedRow.getByRole('button').click();
  const video = page.locator('video[aria-label="Match video evidence"]');
  await expect.poll(() => video.evaluate(v => v.currentTime)).toBeCloseTo(mapped.proxyTimestampUs / 1e6, 2);
  checks.push('Player filter, metre coordinates and exact source-to-proxy contact seek work');
  await panel.getByRole('button', { name: 'Unknown', exact: true }).click();
  await expect(panel.locator('tbody tr')).toHaveCount(stats.contacts.filter(c => c.hitter === null).length);
  await expect(panel.locator('.tracking-stats__point')).toHaveCount(0);
  await expect(panel.locator('tbody tr').first()).toContainText('Unavailable');
  checks.push('Unknown hitters retain unavailable positions');
  await panel.getByRole('button', { name: 'All', exact: true }).click();
  await panel.screenshot({ path: `${out}/stats-expanded.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.scrollIntoViewIfNeeded();
  const width = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
  assert(width.document <= width.viewport, `Mobile overflow: ${JSON.stringify(width)}`);
  await panel.screenshot({ path: `${out}/stats-mobile.png` });
  checks.push('Expanded stats fit mobile viewport');
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${out}/stats-verification.json`, JSON.stringify({ checkedAt: new Date().toISOString(), checks, errors, stats }, null, 2));
  console.log(JSON.stringify({ checks, errors, players: stats.players, ballSpeed: stats.ballSpeed }, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
