const { chromium, expect } = require('../src/squashvision/web/node_modules/@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const out = path.resolve(__dirname, '../runtime/browser-review');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    const prototype = CanvasRenderingContext2D.prototype;
    const clear = prototype.clearRect;
    prototype.clearRect = function (...args) {
      if (this.canvas.closest('.video-overlay')) window.overlayDraw = { arcs: [], rectangles: [], ellipses: [], lines: [] };
      return clear.apply(this, args);
    };
    for (const [method, key] of [['arc', 'arcs'], ['rect', 'rectangles'], ['ellipse', 'ellipses'], ['lineTo', 'lines']]) {
      const original = prototype[method];
      prototype[method] = function (...args) {
        if (this.canvas.closest('.video-overlay') && window.overlayDraw) {
          const matrix = this.getTransform();
          window.overlayDraw[key].push({ args, scale: matrix.a });
        }
        return original.apply(this, args);
      };
    }
  });
  await page.goto('http://127.0.0.1:8950/matches/5ebf3351-5a26-48c0-839b-5da930aa7913/analysis?revision=2');
  await expect.poll(() => page.locator('video').evaluate(video => video.readyState)).toBeGreaterThanOrEqual(2);
  await page.getByRole('slider', { name: 'Match playback position' }).fill('12.5');
  await expect.poll(() => page.evaluate(() => window.overlayDraw?.arcs.length ?? 0)).toBe(1);
  const drawing = await page.evaluate(() => window.overlayDraw);
  assert(Math.abs(drawing.arcs[0].args[0] - 242.02899) < 0.1, 'Ball x does not match source frame 313');
  assert(Math.abs(drawing.arcs[0].args[1] - 644.53384) < 0.1, 'Ball y does not match source frame 313');
  assert(Math.abs(drawing.arcs[0].args[2] * drawing.arcs[0].scale - 3) < 0.01, 'Ball radius is not 3 display pixels');
  assert.equal(drawing.rectangles.length, 0, 'Boxes drawn by default');
  assert.equal(drawing.ellipses.length, 0, 'Uncertainty spread drawn by default');
  assert(drawing.lines.length >= 10, 'Player skeletons were not drawn');
  await page.locator('.video-stage').screenshot({ path: `${out}/limbs-small-ball.png` });
  await page.locator('.overlay-settings summary').click();
  await expect(page.getByRole('checkbox', { name: 'Skeleton', exact: true })).toBeChecked();
  await page.getByRole('checkbox', { name: 'Boxes', exact: true }).check();
  await expect.poll(() => page.evaluate(() => window.overlayDraw?.rectangles.length ?? 0)).toBe(2);
  await page.getByRole('checkbox', { name: 'Boxes', exact: true }).uncheck();
  await page.locator('.overlay-settings summary').click();
  await page.getByRole('slider', { name: 'Match playback position' }).fill('6');
  await expect.poll(() => page.evaluate(() => window.overlayDraw?.arcs.length ?? -1)).toBe(0);
  await page.getByRole('slider', { name: 'Match playback position' }).fill('12.5');
  await expect.poll(() => page.evaluate(() => window.overlayDraw?.arcs.length ?? 0)).toBe(1);
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await expect.poll(() => page.locator('video').evaluate(v => v.currentTime)).toBeGreaterThan(13.2);
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  assert.deepEqual(errors, []);
  const result = { checkedAt: new Date().toISOString(), sourceFrameIndex: 313, proxyTimeSeconds: 12.5, sourceTimeSeconds: 12.52, ballSourcePoint: drawing.arcs[0].args.slice(0, 2), displayedRadiusPixels: drawing.arcs[0].args[2] * drawing.arcs[0].scale, defaultBoxCount: drawing.rectangles.length, defaultSpreadCount: drawing.ellipses.length, skeletonSegments: drawing.lines.length, unavailableFrameMarkerHidden: true, optionalBoxesWork: true, playbackWorks: true, errors };
  fs.writeFileSync(`${out}/overlay-verification.json`, `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify(result, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
