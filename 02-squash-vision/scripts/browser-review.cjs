const { chromium } = require('../src/squashvision/web/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const out = path.resolve(__dirname, '../runtime/browser-review');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const route = process.argv[2] || '/';
  await page.goto(`http://127.0.0.1:8950${route}`);
  await page.getByRole('heading', { level: 1 }).waitFor();
  await page.waitForTimeout(1800);
  await page.screenshot({ path: `${out}/desktop.png`, fullPage: true });
  console.log(JSON.stringify({ route: page.url(), headings: await page.locator('h1,h2,h3').allTextContents(), text: (await page.locator('main').innerText()).slice(0, 6500), errors }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${out}/mobile.png`, fullPage: true });
  console.log(JSON.stringify({ mobile: await page.evaluate(() => ({ viewport: innerWidth, page: document.documentElement.scrollWidth, overflowing: [...document.querySelectorAll('body *')].map(e => ({ tag: e.tagName, cls: e.className?.baseVal ?? e.className, left: e.getBoundingClientRect().left, right: e.getBoundingClientRect().right })).filter(e => e.right > innerWidth + 2 || e.left < -2).slice(0, 30) })), errors }));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
