const { chromium, expect } = require('../src/squashvision/web/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const base = 'http://127.0.0.1:8950';
  const id = process.argv[2] || '5ebf3351-5a26-48c0-839b-5da930aa7913';
  const revision = Number(process.argv[3] || 2);
  const out = path.resolve(__dirname, '../runtime/browser-review');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], checks = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    const original = HTMLVideoElement.prototype.requestVideoFrameCallback;
    if (original) HTMLVideoElement.prototype.requestVideoFrameCallback = function (callback) {
      return original.call(this, (now, metadata) => {
        window.__presentedTime = metadata.mediaTime;
        callback(now, metadata);
      });
    };
  });
  const response = await page.request.get(`${base}/api/v1/matches/${id}/reports/${revision}/tracking-timeline?startUs=0&endUs=120000000`);
  assert(response.ok(), `Timeline HTTP ${response.status()}`);
  const data = await response.json();
  assert.equal(data.ballSpeedMethod, 'court_scaled_image_speed');
  await page.goto(`${base}/matches/${id}/analysis`);
  const panel = page.getByRole('region', { name: 'On court', exact: true });
  const video = page.getByLabel('Match video evidence', { exact: true });
  await expect(panel).toBeVisible();
  await expect.poll(() => video.evaluate(v => v.readyState)).toBeGreaterThanOrEqual(2);
  await expect(page.locator('.analysis-inspector')).not.toBeVisible();
  await expect(page.locator('.review-tools')).not.toHaveAttribute('open', '');
  await expect(page.locator('.video-stage .overlay-legend')).toHaveCount(0);
  await expect(panel.getByRole('region', { name: 'Player A landings' })).toBeVisible();
  await expect(panel.getByRole('region', { name: 'Player B landings' })).toBeVisible();
  await expect(panel.locator('.playback-stats__activity, .playback-stats__legend, .playback-stats__method, .playback-stats__racket, .playback-stats__wall-hit, .playback-stats__player-dot')).toHaveCount(0);
  assert((await panel.locator('.playback-stats__court-heading').allTextContents()).every(text => !/\bshots?\b/.test(text)), 'Unvalidated shot counts must not appear');
  await expect(panel.getByTestId('live-distance-A')).not.toContainText('26.4');
  checks.push('Clean default layout: no review sidebar, video labels, or future totals');

  const seek = async (seconds) => {
    await page.getByRole('slider', { name: 'Match playback position' }).fill(String(seconds));
    await expect.poll(() => video.evaluate(v => v.currentTime)).toBeCloseTo(seconds, 2);
    await expect.poll(() => page.evaluate(() => window.__presentedTime)).toBeCloseTo(seconds, 1);
  };
  const assertSnapshot = async () => {
    const t = await page.evaluate(() => Math.round(window.__presentedTime * 1e6));
    for (const player of ['A', 'B']) {
      const samples = data.playerSamples.filter(s => s.playerId === player && s.proxyTimestampUs !== null && s.proxyTimestampUs <= t);
      const sample = samples.at(-1);
      if (sample?.cumulativeDistanceM !== null && sample?.cumulativeDistanceM !== undefined) {
        await expect(panel.getByTestId(`live-distance-${player}`)).toContainText(sample.cumulativeDistanceM.toFixed(1));
      }
    }
    const speed = data.ballSpeeds.find(s => s.proxyTimestampUs !== null && s.proxyTimestampUs <= t && s.proxyEndTimestampUs > t);
    await expect(panel.getByTestId('live-ball-speed')).toContainText(speed ? speed.speedMps.toFixed(1) : '—');
    const floors = data.contacts.filter(c => c.kind === 'floor' && c.floorPosition && c.shotHitter !== null && c.proxyTimestampUs !== null && c.proxyTimestampUs <= t);
    await expect(panel.locator('.playback-stats__landing')).toHaveCount(floors.length);
    for (const player of ['A', 'B']) {
      const court = panel.locator(`[data-court-player="${player}"]`);
      await expect(court.locator('.playback-stats__landing')).toHaveCount(floors.filter(c => c.shotHitter === player).length);
      const ids = await court.locator('[data-contact-id]').evaluateAll(markers => markers.map(m => m.dataset.contactId));
      assert(ids.every(id => data.contacts.find(c => c.id === id)?.shotHitter === player), `Wrong player impact on ${player}'s court`);
    }
    return t;
  };
  await seek(5);
  await assertSnapshot();
  const a5 = await panel.getByTestId('live-distance-A').innerText();
  await seek(12.5);
  await assertSnapshot();
  assert.notEqual(await panel.getByTestId('live-distance-A').innerText(), a5);
  await seek(2);
  await assertSnapshot();
  checks.push('Movement, speed and progressive impact map follow seeking and rewind');

  const floor = data.contacts.find(c => c.kind === 'floor' && c.floorPosition && c.shotHitter !== null && c.proxyTimestampUs !== null);
  assert(floor);
  await seek(floor.proxyTimestampUs / 1e6 + 1);
  await panel.locator(`[data-contact-id="${floor.id}"]`).click();
  await expect.poll(() => video.evaluate(v => v.currentTime)).toBeCloseTo(floor.proxyTimestampUs / 1e6, 3);
  const marker = page.locator('.playback-impact-marker');
  await expect(marker).toHaveAttribute('data-kind', 'floor');
  const xy = await marker.locator('circle').evaluate(c => [Number(c.getAttribute('cx')), Number(c.getAttribute('cy'))]);
  assert.deepEqual(xy, floor.ballImagePosition);
  checks.push('A court landing seeks its exact proxy frame and marks the ball location on video');
  await seek(12.5);
  await assertSnapshot();
  const colors = await page.locator('.playback-stats__player-court').evaluateAll(courts => courts.map(c => getComputedStyle(c).getPropertyValue('--court-player').trim()));
  assert.equal(colors.length, 2);
  assert.notEqual(colors[0], colors[1], 'Player courts must have distinct colors');
  await page.screenshot({ path: `${out}/live-court-desktop.png`, fullPage: true });
  const bounds = await page.evaluate(() => ({ video: document.querySelector('.analysis-video-stage').getBoundingClientRect().toJSON(), courts: Array.from(document.querySelectorAll('.playback-stats__court'), court => court.getBoundingClientRect().toJSON()), viewport: innerHeight }));
  assert(bounds.video.bottom <= bounds.viewport && bounds.courts.every(court => court.bottom <= bounds.viewport), 'Video and both courts must fit together in desktop viewport');
  checks.push('Separate A/B courts show only their assigned landings, without unreliable shot counts or the event list');

  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await expect.poll(() => video.evaluate(v => v.currentTime)).toBeGreaterThan(13.5);
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await assertSnapshot();
  checks.push('Real playback advances the court and measurements on presented frames');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => scrollTo(0, 0));
  const width = await page.evaluate(() => [innerWidth, document.documentElement.scrollWidth]);
  assert(width[1] <= width[0], `Mobile overflow: ${width}`);
  await page.screenshot({ path: `${out}/live-court-mobile.png`, fullPage: true });
  checks.push('Mobile layout has no page overflow');
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${out}/live-verification.json`, JSON.stringify({ checkedAt: new Date().toISOString(), matchId: id, revision, checks, errors, bounds, floorImpact: floor }, null, 2));
  console.log(JSON.stringify({ checks, errors, floorImpact: floor }, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
