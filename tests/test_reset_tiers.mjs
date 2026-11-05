import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Runs the dashboard's real saved-reset code without a browser, on a clock the tests move.
const source = fs.readFileSync(new URL('../token_tv/web/app.js', import.meta.url), 'utf8');
const pick = pattern => source.match(pattern)[0];
let clock = 1_000_000;
const el = (tag, text, cls) => ({tag, text, cls, children: [], dataset: {}, attrs: {}, append(...c) {this.children.push(...c)}, setAttribute(k, v) {this.attrs[k] = v}});
const context = {offline: false, Number, Date: {now: () => clock * 1000}, el, svgNode: (tag, attrs) => ({tag, attrs, children: [], dataset: {}, append() {}})};
vm.createContext(context);
for (const code of [/const RESET_FRESH[^\n]*\n/, /function resetReading\(info, unavailable = offline\) \{[\s\S]*?\n\}\n/,
                    /function knownResetCount\([^\n]*\n/, /function savedHearts\(info, aged = false\) \{[\s\S]*?\n\}\n/])
  vm.runInContext(pick(code), context);
const reading = info => JSON.parse(JSON.stringify(context.resetReading(info)));   // out of the vm: same shape, this realm's objects

const automatic = (age, extra = {}, source = 'claude_web') =>
  ({available: 2, confirmed_at: clock - age, source, ...(source === 'claude_web' ? {valid_until: clock + 3600} : {}), ...extra});

test('an automatic saved-reset count is current to 180 s, then kept old for up to 72 h', () => {
  for (const source of ['claude_web', 'codex_cli']) {
    for (const [age, count, old] of [[0, 2, false], [180, 2, false], [181, 2, true], [300, 2, true], [480, 2, true], [481, 2, true], [3000, 2, true]])
      assert.deepEqual(reading(automatic(age, {}, source)), {count, old}, `${source} at ${age} s`);
  }
});

test('the server keeps an old count as last_known with available unknown: the dashboard shows it the same way', () => {
  const kept = (age, extra = {}) => ({available: null, confirmed_at: clock - age, source: 'stale', last_known: 2, valid_until: clock + 100, ...extra});
  assert.deepEqual(reading(kept(200)), {count: 2, old: true});
  assert.deepEqual(reading(kept(481)), {count: 2, old: true});
  assert.deepEqual(reading(kept(72 * 3600, {valid_until: clock + 999999})), {count: 2, old: true});
  for (const changed of [kept(72 * 3600 + 1, {valid_until: clock + 999999}), kept(200, {valid_until: clock - 1}), kept(200, {valid_until: 'soon'}), kept(200, {confirmed_at: null}),
                         kept(-120), kept(200, {last_known: true}), kept(200, {last_known: -1}), kept(200, {last_known: 1.5}), kept(200, {last_known: '2'})])
    assert.deepEqual(reading(changed), {count: null, old: false}, JSON.stringify(changed));
  assert.deepEqual(reading({available: null, confirmed_at: null, source: 'unknown'}), {count: null, old: false});
});

test('a grant that has ended, a missing expiry, an offline panel or a future date is never a count', () => {
  for (const changed of [automatic(10, {valid_until: clock - 1}), automatic(10, {valid_until: null}), automatic(10, {valid_until: NaN}),
                         automatic(10, {confirmed_at: clock + 120}), automatic(10, {confirmed_at: undefined}), automatic(10, {available: -1}),
                         automatic(10, {available: 1.5}), automatic(10, {available: true}), automatic(10, {available: '2'})])
    assert.equal(context.knownResetCount(changed), null, JSON.stringify(changed));
  assert.equal(context.knownResetCount(automatic(10, {available: 0})), 0, 'a confirmed zero is a count');
  assert.equal(context.knownResetCount(automatic(10), true), null, 'an unreachable panel');
  context.offline = true;
  try { assert.equal(context.knownResetCount(automatic(10)), null); } finally { context.offline = false; }
});

test('Claude saying the account has no saved resets is a zero that never ages and has no dot', () => {
  assert.deepEqual(reading({available: 0, confirmed_at: clock - 9_999_999, source: 'claude_not_eligible'}), {count: 0, old: false});
});

test('a count confirmed by hand never ages into unknown or old', () => {
  assert.deepEqual(reading({available: 1, confirmed_at: clock - 99999, source: 'user_confirmed'}), {count: 1, old: false});
  assert.deepEqual(reading({available: 0, confirmed_at: null, source: 'user_confirmed'}), {count: 0, old: false});
});

test('the hearts show the discreet dot for an old or unknown count and + for more than three, never a question mark', () => {
  const marks = info => context.savedHearts(info).children.filter(child => child.tag === 'span' || child.tag === 'i').map(child => child.tag === 'i' ? 'dot' : child.text);
  assert.deepEqual(marks(automatic(10)), []);
  assert.deepEqual(marks(automatic(300)), ['dot']);
  assert.deepEqual(marks(automatic(10, {available: 5})), ['+']);
  assert.deepEqual(marks({available: null, confirmed_at: clock - 300, source: 'stale', last_known: 1, valid_until: clock + 60}), ['dot']);
  assert.deepEqual(marks(null), ['dot']);
  assert.match(context.savedHearts(automatic(300)).attrs['aria-label'], /^2 saved resets · checked a few minutes ago$/);
  assert.match(context.savedHearts(automatic(10)).attrs['aria-label'], /^2 saved resets$/);
  const filled = info => context.savedHearts(info).children.filter(child => child.tag === 'svg').map(child => child.dataset.filled);
  assert.deepEqual(filled(automatic(300)), ['true', 'true', 'false']);
  assert.deepEqual(filled(automatic(600)), ['true', 'true', 'false']);
  assert.deepEqual(filled(null), ['false', 'false', 'false']);
});
