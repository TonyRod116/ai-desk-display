import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Runs the dashboard's real visibleWindows() without a browser.
const source = fs.readFileSync(new URL('../token_tv/web/app.js', import.meta.url), 'utf8');
const body = source.match(/function visibleWindows\(a\) \{[\s\S]*?\n\}\n/)[0];
const context = {offline: false, Date, Number};
vm.createContext(context);
vm.runInContext(body, context);

const now = () => Date.now() / 1000;
function account(origin, fiveHourReset, weekReset = now() + 86400) {
  return {status: 'ok', quota_origin: origin, fetched_at: now() - 30, ordinary_usage_allowed: true,
          windows: [{label: '5H', used_percent: 20, resets_at: fiveHourReset},
                    {label: 'WEEK', used_percent: 9, resets_at: weekReset}]};
}
const labels = a => context.visibleWindows(a).map(w => w.label).join(',');

test('claude keeps both windows while the five-hour reset is live', () => {
  assert.equal(labels(account('claude_official_cli', now() + 600)), '5H,WEEK');
});

test('claude drops only a rolled-over or unconfirmed five-hour window', () => {
  for (const reset of [now() - 5, null]) {
    assert.equal(labels(account('claude_official_cli', reset)), 'WEEK');
  }
});

test('claude blanks everything when the week has no live reset', () => {
  for (const reset of [now() - 1, null]) {
    assert.equal(labels(account('claude_official_cli', now() + 600, reset)), '');
  }
});

test('codex keeps the original rule: a passed five-hour reset blanks it', () => {
  assert.equal(labels(account('codex_official_cli', now() - 5)), '');
});

test('codex blocked with explicit exhausted week keeps only its zero', () => {
  const a = account('codex_official_cli', now() + 600);
  a.ordinary_usage_allowed = false;
  a.windows[1].used_percent = 100;
  assert.equal(labels(a), 'WEEK');
  for (const changed of [
    {...a, ordinary_usage_allowed: null}, {...a, status: 'quota_unavailable'},
    {...a, fetched_at: now() - 181},
    {...a, windows: a.windows.map(w => ({...w, used_percent: 99.9}))},
    {...a, windows: a.windows.map(w => ({...w, resets_at: null}))},
    {...a, windows: a.windows.map(w => ({...w, resets_at: now() - 1}))},
  ]) assert.equal(labels(changed), '');
  context.offline = true;
  try { assert.equal(labels(a), ''); } finally { context.offline = false; }
});
