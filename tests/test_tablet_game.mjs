import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

// The game engine's pure parts: the cover layout, the visible rows above the dock, the fixed-step clock, the seeded random numbers, the governor and the registry.
const require = createRequire(import.meta.url);
const games = require('../token_tv/tablet_web/stage-game.js');
const {coverLayout, visibleRows, makeClock, seeded, Governor, define, registry, STEP, LEVELS, FRAG} = games;
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} is not ${b}`);

test('the art covers the whole screen, top aligned, and never leaves a gap', () => {
  for (const [w, h] of [[601, 961], [768, 1024], [480, 854], [1200, 1740], [800, 1280]]) {
    const l = coverLayout(w, h, 200, 320);
    assert.ok(l.w >= w - 1e-6 && l.h >= h - 1e-6, `${w}x${h} is covered`);
    close(l.y, 0); close(l.x, (w - l.w) / 2); close(l.w / l.h, 200 / 320);
  }
  const tablet = coverLayout(601, 961, 200, 320);
  assert.ok(Math.abs(tablet.scale - 3.005) < 0.005, 'about 3 CSS px per art pixel: 4 device pixels at 1.33');
});

test('the rows above the dock follow the area, and the whole picture shows when the dock is gone', () => {
  const l = coverLayout(601, 961, 200, 320);
  assert.equal(visibleRows(l, 320, 961, 961).bottom, 320);
  const above = visibleRows(l, 320, 961 * 0.58, 961).bottom;
  assert.ok(above > 170 && above < 200, `${above} rows above a dock that takes 42 %`);
  assert.equal(visibleRows(l, 320, -50, 961).bottom, 1, 'never zero rows');
  assert.equal(visibleRows(l, 320, 99999, 961).bottom, 320);
});

test('the clock owes whole 30 Hz steps, never spirals and forgives a very long frame', () => {
  const clock = makeClock();
  assert.equal(clock.advance(STEP), 1);
  assert.equal(clock.advance(STEP / 2), 0);
  assert.equal(clock.advance(STEP / 2 + 1e-9), 1);
  assert.equal(clock.advance(0.1), 3);
  assert.ok(clock.advance(5) <= 4, 'a stall costs a handful of steps, not hundreds');
  assert.equal(clock.advance(-1), 0);
  let total = 0; const c2 = makeClock();
  for (let i = 0; i < 60; i++) total += c2.advance(1 / 60);
  assert.ok(total >= 29 && total <= 31, `${total} steps in a second of 60 Hz frames`);
});

test('the seeded generator repeats and spreads', () => {
  const a = seeded(7), b = seeded(7), c = seeded(8);
  const run = (r) => Array.from({length: 6}, () => r());
  assert.deepEqual(run(a), run(b));
  assert.notDeepEqual(run(seeded(7)), run(c));
  const many = Array.from({length: 2000}, seeded(3));
  assert.ok(many.every(v => v >= 0 && v < 1));
  const mean = many.reduce((x, y) => x + y, 0) / many.length;
  assert.ok(mean > 0.45 && mean < 0.55);
});

test('the governor goes down after a spell of late frames, up after a long clean one, and not at once', () => {
  const g = new Governor({hold: 1, calm: 10});
  let now = 0;
  const run = (dt, frames) => { let last = null; for (let i = 0; i < frames; i++) { now += dt; const v = g.feed(dt, now); if (v) last = v; } return last; };
  assert.equal(run(0.2, 20), null, 'held back at the start');
  assert.equal(run(0.2, 60), 'down');
  g.reset(now);                                  // a fresh start after the verdict
  assert.equal(run(1 / 30, 45), null, 'a clean spell too short');
  assert.equal(run(1 / 30, 400), 'up');
});

test('only well-formed scene names register, and a scene needs a draw function', () => {
  assert.equal(define('platform', {draw() {}}), true);
  assert.ok(registry.platform);
  for (const bad of ['Platform', 'a b', '', 'x'.repeat(41), '../x', null]) assert.equal(define(bad, {draw() {}}), false, String(bad));
  assert.equal(define('nodraw', {}), false);
  assert.equal(define('nodraw', null), false);
});

test('the quality levels only lower, the CRT pass has no curvature and the shader is what the code expects', () => {
  assert.deepEqual(LEVELS.map(l => l.name), ['high', 'medium', 'light', 'low']);
  for (let i = 1; i < LEVELS.length; i++) assert.ok(LEVELS[i].scale <= LEVELS[i - 1].scale && LEVELS[i].fx <= LEVELS[i - 1].fx && LEVELS[i].every >= LEVELS[i - 1].every);
  assert.doesNotMatch(FRAG, /barrel|curv|pow\(.*uv/i, 'no curvature: nothing may be lost at the edges');
  for (const u of ['base', 'glow', 'native', 'fx', 'time']) assert.match(FRAG, new RegExp('uniform [A-Za-z0-9 ,]*\\b' + u + '\\b'));
  assert.ok((FRAG.match(/texture2D/g) || []).length <= 5, 'at most four reads per pixel (the source mentions one more in the guarded bleed)');
});
