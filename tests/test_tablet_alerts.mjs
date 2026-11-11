import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

// The tablet's alert rules (what just happened) and its synthesised chime (against a stand-in AudioContext).
const require = createRequire(import.meta.url);
const {create, createSound, worst, TUNES} = require('../token_tv/tablet_web/alerts.js');
const NOW = Date.UTC(2026, 10, 9, 12);
const future = days => NOW / 1000 + days * 86400;
const reading = (codexWeek, claudeWeek, claudeFive, disks = []) => ({
  providers: {codex: {weekly: {remaining: codexWeek, resets_at: future(5)}}, claude: {weekly: {remaining: claudeWeek, resets_at: future(3)}, session: {remaining: claudeFive, resets_at: future(0.1)}}},
  metrics: {disks}});
const RULES = {quota: 10, disk: 5, resets: true};

test('the first reading only sets the baseline: a page opened with a low quota or a full disk is not news', () => {
  const alerts = create();
  assert.deepEqual(alerts.feed(reading(4, 8, 2, [{name: 'C:', total: 1000, free: 20}]), RULES, NOW), []);
  assert.deepEqual(alerts.feed(reading(4, 8, 2, [{name: 'C:', total: 1000, free: 20}]), RULES, NOW + 5000), []);
});

test('a quota that falls under its limit alerts once, a critical one once more, and re-arms after a recovery', () => {
  const alerts = create();
  alerts.feed(reading(80, 12, 90), RULES, NOW);
  let raised = alerts.feed(reading(80, 9, 90), RULES, NOW + 5000);
  assert.deepEqual(raised.map(a => [a.kind, a.provider, a.window, a.value, a.level]), [['quota-low', 'claude', 'week', 9, 'warning']]);
  assert.deepEqual(alerts.feed(reading(80, 8, 90), RULES, NOW + 10000), [], 'still low: silent');
  raised = alerts.feed(reading(80, 4.5, 90), RULES, NOW + 15000);
  assert.deepEqual(raised.map(a => [a.kind, a.level]), [['quota-critical', 'critical']]);
  assert.deepEqual(alerts.feed(reading(80, 11, 90), RULES, NOW + 20000), [], 'not yet recovered enough (limit + margin)');
  assert.deepEqual(alerts.feed(reading(80, 9, 90), RULES, NOW + 25000), [], 'so no second alert');
  alerts.feed(reading(80, 14, 90), RULES, NOW + 30000);
  assert.equal(alerts.feed(reading(80, 9, 90), RULES, NOW + 35000).length, 1, 'after a real recovery it can alert again');
});

test('each window and provider is watched separately, and the limit comes from the settings', () => {
  const alerts = create();
  alerts.feed(reading(30, 30, 30), {quota: 25, disk: 5, resets: true}, NOW);
  const raised = alerts.feed(reading(24, 40, 20), {quota: 25, disk: 5, resets: true}, NOW + 5000);
  assert.deepEqual(raised.map(a => `${a.provider}:${a.window}`).sort(), ['claude:five', 'codex:week']);
});

test('a renewed window is a reset; jitter in the reset time is not; it can be switched off', () => {
  const alerts = create();
  alerts.feed(reading(5, 50, 50), RULES, NOW);
  const jitter = reading(5, 50, 50); jitter.providers.codex.weekly.resets_at += 20;
  assert.deepEqual(alerts.feed(jitter, RULES, NOW + 5000), []);
  const renewed = reading(100, 50, 50); renewed.providers.codex.weekly.resets_at += 7 * 86400;
  assert.deepEqual(alerts.feed(renewed, RULES, NOW + 10000).map(a => [a.kind, a.provider, a.window, a.level]), [['reset', 'codex', 'week', 'info']]);
  const again = create(); again.feed(reading(5, 50, 50), {...RULES, resets: false}, NOW);
  const off = reading(100, 50, 50); off.providers.codex.weekly.resets_at += 7 * 86400;
  assert.deepEqual(again.feed(off, {...RULES, resets: false}, NOW + 5000), []);
});

test('unknown, malformed or expired readings change nothing and say nothing', () => {
  const alerts = create();
  alerts.feed(reading(50, 50, 50), RULES, NOW);
  assert.deepEqual(alerts.feed(null, RULES, NOW + 1000), []);
  assert.deepEqual(alerts.feed({providers: {codex: {weekly: {remaining: null}}, claude: {weekly: {remaining: 140, resets_at: future(1)}, session: {remaining: -3}}}}, RULES, NOW + 2000), []);
  const expired = reading(2, 50, 50); expired.providers.codex.weekly.resets_at = NOW / 1000 - 60;
  assert.deepEqual(alerts.feed(expired, RULES, NOW + 3000), [], 'a window that already ended is not a reading');
  assert.deepEqual(alerts.feed({providers: 'x', metrics: {disks: 'y'}}, RULES, NOW + 4000), []);
});

test('a disk alerts when its free share falls under the limit, once; the cloud drive and bad numbers never do', () => {
  const alerts = create();
  const disks = free => [{name: 'C:', total: 1000, free}, {name: 'G:', kind: 'google_drive', total: 1000, free: 1}, {name: 'X:', total: 0, free: 0}, {name: 'Y:', total: 10, free: 20}, {total: 5, free: 1}];
  alerts.feed(reading(50, 50, 50, disks(120)), RULES, NOW);
  const raised = alerts.feed(reading(50, 50, 50, disks(40)), RULES, NOW + 5000);
  assert.deepEqual(raised.map(a => [a.kind, a.name, a.value, a.level]), [['disk-low', 'C:', 4, 'critical']]);
  assert.deepEqual(alerts.feed(reading(50, 50, 50, disks(30)), RULES, NOW + 10000), []);
});

test('the most severe alert decides the sound', () => {
  assert.equal(worst([]), null);
  assert.equal(worst([{level: 'info'}, {level: 'critical'}, {level: 'warning'}]).level, 'critical');
  assert.equal(worst([{level: 'info'}, {level: 'warning'}]).level, 'warning');
});

class FakeContext {
  constructor() { this.state = 'suspended'; this.currentTime = 10; this.destination = {}; this.made = []; this.resumed = 0; }
  resume() { this.resumed++; this.state = 'running'; return Promise.resolve(); }
  createGain() { const g = {gain: {values: [], setValueAtTime(v) { this.values.push(v); }, exponentialRampToValueAtTime(v) { this.values.push(v); }}, connect() {}}; return g; }
  createOscillator() { const o = {type: '', frequency: {value: 0}, connect() {}, start(t) { o.at = t; }, stop(t) { o.until = t; }}; this.made.push(o); return o; }
}

test('the chime is locked until the page has been touched, then plays the right notes softly', () => {
  let context;
  const sound = createSound(class extends FakeContext { constructor() { super(); context = this; } });
  assert.equal(sound.state(), 'locked');
  assert.equal(sound.play('warning', 60), false, 'a suspended context plays nothing');
  assert.equal(sound.unlock(), 'ready');
  assert.equal(context.resumed, 1);
  assert.equal(sound.play('critical', 60), true);
  assert.equal(context.made.length, TUNES.critical.notes.length);
  assert.ok(context.made.every(o => o.until > o.at && o.at >= context.currentTime));
  assert.equal(sound.play('warning', 0), false, 'volume zero is silence');
  assert.equal(sound.play('unknown-level', 100), true, 'an unknown level falls back to the warning chime');
  assert.equal(createSound(undefined).state(), 'unsupported');
  assert.equal(createSound(undefined).play('warning', 60), false);
  assert.equal(createSound(class { constructor() { throw new Error('no audio'); } }).unlock(), 'locked');
});
