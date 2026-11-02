import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

const root = resolve('dist');
if (!existsSync(root)) throw new Error('Build the site before checking links.');
const walk = dir => readdirSync(dir).flatMap(name => {
  const file = join(dir, name);
  return statSync(file).isDirectory() ? walk(file) : [file];
});
const failures = [];
let checked = 0;
const pages = walk(root).filter(file => file.endsWith('.html'));
if (pages.length < 7) throw new Error('Expected the seven PRINCE HTML routes in dist/.');
for (const file of pages) {
  const html = readFileSync(file, 'utf8');
  for (const [, raw] of html.matchAll(/(?:href|src|poster)=["']([^"']+)["']/g)) {
    if (/^(?:[a-z][a-z\d+.-]*:|\/\/|#)/i.test(raw)) continue;
    const url = decodeURI(raw.split(/[?#]/)[0]);
    if (!url) continue;
    const target = url.startsWith('/') ? join(root, url.slice(1)) : resolve(dirname(file), url);
    if (!existsSync(target) || (statSync(target).isDirectory() && !existsSync(join(target, 'index.html')))) {
      failures.push(`${file.slice(root.length)} -> ${raw}`);
    }
    checked++;
  }
}
if (failures.length) throw new Error(`Broken local links:\n${failures.join('\n')}`);
console.log(`Verified ${checked} internal page and asset references.`);
