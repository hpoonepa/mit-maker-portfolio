import assert from 'node:assert/strict';

const site = process.env.PRINCE_SITE_URL || 'http://127.0.0.1:4330';
const api = process.env.PRINCE_API_URL || 'http://127.0.0.1:18766';
const origin = new URL(site).origin;
const request = (url, options = {}) => fetch(url, { ...options, signal: AbortSignal.timeout(60_000) });
const post = (payload, requestOrigin = origin) => request(`${api}/api/analyze`, {
  method: 'POST', headers: { 'Content-Type': 'application/json', Origin: requestOrigin },
  body: JSON.stringify(payload),
});

for (const route of ['/', '/workspace/', '/guide/', '/method/', '/validation/', '/resources/']) {
  const response = await request(`${site}${route}`);
  assert.equal(response.status, 200, route);
  assert.match(await response.text(), /PRINCE|Prince/);
}
for (const file of ['model-evaluation.json', 'site-evaluation.json', 'site-uncertainty.json',
  'fit-protocol.json', 'connected-manifest.csv', 'antigen-context-audit.json',
  'bepipred-comparison.json', 'bepipred-inference-provenance.json',
  'bepipred-verification.json', 'LICENSE.txt']) {
  assert.equal((await request(`${site}/prince/${file}`)).status, 200, file);
}
assert.equal((await (await request(`${api}/api/health`)).json()).status, 'ok');
assert.equal((await request(`${api}/api/validation`)).status, 200);
const analysis = await post({ pdb_id: '1ubq', chain: 'A', top: 3 });
assert.equal(analysis.status, 200);
assert.equal(analysis.headers.get('access-control-allow-origin'), origin);
const result = await analysis.json();
assert.equal(result.schema_version, 1);
assert.equal(result.proposal.patches.length, 3);
assert.equal(result.checks.length, 3);
assert.equal(result.selected_check, null);
assert(result.proposal.patches.every(patch => Number.isFinite(patch.score) && patch.residues.length > 0));
const selected = await post({ pdb_id: '6f5j', chain: 'C', assembly: '1', hotspots: 'C405,C408', top: 3 });
assert.equal(selected.status, 200);
assert.equal((await selected.json()).selected_check.verdict, 'STOP');
assert.equal((await post({ pdb_id: '1ubq', top: 0 })).status, 400);
assert.equal((await post({ pdb_id: '1ubq', unknown: true })).status, 400);
assert.equal((await post({ pdb_id: '1ubq' }, 'https://untrusted.example')).status, 403);
console.log('Verified six routes, ten downloads, API metadata, two real structure analyses, selected STOP, invalid inputs, and origin enforcement.');
