import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Runs the dashboard's real visibleWindows() on a clock the tests move, for the browser-backup quota source.
const source = fs.readFileSync(new URL('../token_tv/web/app.js', import.meta.url), 'utf8');
let clock = 1_000_000;
const context = {offline: false, Number, Date: {now: () => clock * 1000}};
vm.createContext(context);
vm.runInContext(source.match(/function visibleWindows\(a\) \{[\s\S]*?\n\}\n/)[0], context);

const account = (origin, fiveHourReset, weekReset = clock + 86400, extra = {}) =>
  ({status: 'ok', quota_origin: origin, fetched_at: clock - 30,
    windows: [{label: '5H', used_percent: 20, resets_at: fiveHourReset}, {label: 'WEEK', used_percent: 9, resets_at: weekReset}], ...extra});
const labels = a => context.visibleWindows(a).map(w => w.label).join(',');

test('the browser backup follows the same window rules as the official client', () => {
  assert.equal(labels(account('claude_browser', clock + 600)), '5H,WEEK');
  for (const reset of [clock - 5, null]) assert.equal(labels(account('claude_browser', reset)), 'WEEK');
  for (const reset of [clock - 1, null]) assert.equal(labels(account('claude_browser', clock + 600, reset)), '');
  assert.equal(labels(account('claude_browser', clock + 600, clock + 86400, {status: 'stale'})), '');
  assert.equal(labels(account('claude_browser', clock + 600, clock + 86400, {fetched_at: clock - 100000})), '');
  assert.equal(labels(account('claude_browser', clock + 600, clock + 86400, {fetched_at: clock + 600})), '');
  assert.equal(labels(account('claude_browser', clock + 600, clock + 86400, {status: 'identity_mismatch'})), '');
  context.offline = true;
  try { assert.equal(labels(account('claude_browser', clock + 600)), ''); } finally { context.offline = false; }
});
