import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

// CITY IN THE SKY (token_tv/tablet_web/game-city-iso.js): the pure logic (readings to lit windows, the sun and the clock, the weather, the traffic, what hides
// what, the camera) and a smoke test of the whole scene against a fake canvas. The scene registers itself with the engine, so the engine is loaded first.
const require = createRequire(import.meta.url);
const games = require('../token_tv/tablet_web/stage-game.js');
globalThis.TabletGames = games;
const city = require('../token_tv/tablet_web/game-city-iso.js');
const {weekCells, sessionCells, dataState, litFlags, sunAltitude, phaseWeights, lightLevel, batchAlphas, dayState, moonPhase, weatherFor, lightState, hiddenBy, isHidden,
  makeTraffic, stepTraffic, cameraAt, rasterise, paintCells, vehicleSprite, heliSprite, pigeonSprite, courierSprite, VEHICLES, MAX_VEHICLES, STALE_MS} = city;

const NOW = Date.parse('2026-11-09T12:00:00Z');
const BARCELONA = {lat: 41.39, lon: 2.17};
const sec = (ms) => ms / 1000;
const week = (remaining, hours = 70) => ({remaining, resets_at: sec(NOW) + hours * 3600});

/* ------------------------------------------------------------------------------------------------------------------------------------------ the data */

test('a week lights one window per percent, rounded down like the dock, at least one while anything is left, none for zero', () => {
  const cases = [[100, 100], [99.9, 99], [99, 99], [73, 73], [72.9, 72], [72.1, 72], [50, 50], [10, 10], [9.99, 9], [1, 1], [0.99, 1], [0.4, 1], [0.0001, 1], [0, 0]];
  for (const [remaining, cells] of cases) assert.equal(weekCells(remaining), cells, `${remaining} %`);
  for (const v of [72.9, 10.5, 33.3]) assert.equal(weekCells(v), Math.floor(v), 'the dock shows Math.floor, the building shows the same number');
});

test('anything that is not a percentage is unknown, never zero and never full', () => {
  for (const bad of [null, undefined, NaN, Infinity, -Infinity, -1, -0.001, 100.01, 101, 1e9, '73', '', {}, [], true]) assert.equal(weekCells(bad), null, String(bad));
  assert.equal(weekCells(0), 0, 'a real zero is not unknown');
});

test('the five hours: left face is the quota at 20 % a floor, right face the time at an hour a floor, at least one window while any is left', () => {
  const at = (quota, hours) => sessionCells({remaining: quota, resets_at: sec(NOW) + hours * 3600}, NOW);
  assert.deepEqual(at(100, 5), {quota: 40, time: 40}, 'five floors of eight windows each');
  assert.deepEqual(at(20, 1), {quota: 8, time: 8}, 'one floor of quota, one hour: one floor of time');
  assert.equal(at(20.1, 1).quota, 9);
  assert.equal(at(2.5, 5).quota, 1);
  assert.equal(at(0.1, 5).quota, 1, 'at least one window while any quota is left');
  assert.equal(at(0, 3).quota, 0, 'a real zero is empty');
  assert.equal(at(50, 0.5).time, 4);
  assert.equal(at(50, 3 / 60).time, 1, 'a few minutes left still show one window');
  assert.equal(at(50, 9).time, 40, 'never more than five hours');
  assert.equal(at(100, 5).quota, 40);
});

test('the five hours need a fresh, known reading: no session, a bad number or a passed reset is unknown', () => {
  assert.equal(sessionCells(null, NOW), null);
  assert.equal(sessionCells(undefined, NOW), null);
  assert.equal(sessionCells({remaining: 50}, NOW), null, 'no reset: unknown');
  assert.equal(sessionCells({remaining: 50, resets_at: sec(NOW) - 1}, NOW), null, 'the window has rolled over');
  assert.equal(sessionCells({remaining: 50, resets_at: sec(NOW)}, NOW), null);
  assert.equal(sessionCells({remaining: 101, resets_at: sec(NOW) + 600}, NOW), null);
  assert.equal(sessionCells({remaining: -5, resets_at: sec(NOW) + 600}, NOW), null);
  assert.equal(sessionCells({remaining: 'x', resets_at: sec(NOW) + 600}, NOW), null);
  assert.equal(sessionCells({remaining: 40, resets_at: 'soon'}, NOW), null);
});

test('what the three buildings show: each provider apart, an unknown one neutral, the page\'s own rules for a passed or missing reset', () => {
  const full = dataState({providers: {codex: {weekly: week(73)}, claude: {weekly: week(58), session: {remaining: 26, resets_at: sec(NOW) + 7200}}}}, NOW, 1000);
  assert.deepEqual(full.codex, {known: true, count: 73});
  assert.deepEqual(full.claude, {known: true, count: 58});
  assert.deepEqual(full.small, {known: true, quota: 11, time: 16});
  const half = dataState({providers: {codex: {weekly: week(40)}, claude: {weekly: null, session: {remaining: 60, resets_at: sec(NOW) + 3600}}}}, NOW, 0);
  assert.equal(half.codex.known, true);
  assert.equal(half.claude.known, false, 'a missing week is unknown, whatever the five hours say');
  assert.equal(half.small.known, true, 'the five hours stand on their own reading');
  const passed = dataState({providers: {codex: {weekly: {remaining: 80, resets_at: sec(NOW) - 5}}, claude: {weekly: {remaining: 80}}}}, NOW, 0);
  assert.equal(passed.codex.known, false, 'a week whose reset has passed is unknown, like on the dock');
  assert.equal(passed.claude.known, false);
  const zero = dataState({providers: {codex: {weekly: week(0)}, claude: {weekly: week(100)}}}, NOW, 0);
  assert.deepEqual(zero.codex, {known: true, count: 0});
  assert.deepEqual(zero.claude, {known: true, count: 100});
});

test('no readings, a broken reading or a disconnected quota feed is unknown everywhere, and an old reading is not shown', () => {
  const unknown = {codex: {known: false, count: 0}, claude: {known: false, count: 0}, small: {known: false, quota: 0, time: 0}};
  for (const r of [null, undefined, {}, {providers: null}, {providers: {}}, {providers: {codex: null, claude: 5}}, 'text', 7, {providers: {codex: {weekly: 'x'}}}]) {
    assert.deepEqual(dataState(r, NOW, 0), unknown, JSON.stringify(r));
  }
  const good = {providers: {codex: {weekly: week(73)}, claude: {weekly: week(58)}}};
  assert.equal(dataState(good, NOW, STALE_MS).codex.known, true, 'right at the limit it is still shown');
  assert.equal(dataState(good, NOW, STALE_MS + 1).codex.known, false, 'a reading the page stopped renewing goes unknown');
  assert.deepEqual(dataState(good, NOW, 10 * 60 * 1000), unknown);
  assert.ok(STALE_MS >= 15000 && STALE_MS <= 120000, 'the page asks every 5 s: tolerate a few missed answers, not minutes');
});

test('lit windows are the first ones in reading order', () => {
  assert.deepEqual(litFlags(3, 5), [true, true, true, false, false]);
  assert.deepEqual(litFlags(0, 4), [false, false, false, false]);
  assert.equal(litFlags(100, 100).every(Boolean), true);
  assert.equal(litFlags(37, 100).filter(Boolean).length, 37);
});

test('a data building is drawn on whole pixels: the first N cells lit in the lit colour, every other one a dark socket, none for unknown', () => {
  const cells = [];
  for (let i = 0; i < 100; i++) cells.push([20 + (i % 10) * 5, 80 - Math.floor(i / 10) * 9, i % 10 < 5 ? 1 : -1]);
  const calls = [];
  const ctx = {fillStyle: '', fillRect(x, y, w, h) { calls.push({colour: this.fillStyle, x, y, w, h}); }};
  const lit = [255, 220, 136], left = [222, 190, 120], socket = [16, 30, 52];
  paintCells(ctx, cells, 3, [[1, 4], [5, 8]], 0, 0, 37, left, lit, socket);
  assert.equal(calls.length, 100 * 3 * 2, 'a window is three pixel columns of two rows');
  const colourOf = (i) => calls[i * 6].colour;
  for (let i = 0; i < 100; i++) {
    const want = i < 37 ? (cells[i][2] > 0 ? 'rgb(222,190,120)' : 'rgb(255,220,136)') : 'rgb(16,30,52)';
    assert.equal(colourOf(i), want, `cell ${i}`);
  }
  for (const c of calls) { assert.ok(Number.isInteger(c.x) && Number.isInteger(c.y) && c.w === 1 && c.h === 3, 'whole pixels, a column three pixels tall'); }
  const left0 = calls.slice(0, 6), ys = left0.filter((c, i) => i % 2 === 0).map((c) => c.y);
  assert.deepEqual(ys, [80 - 4, 80 - 4 + 1, 80 - 4 + 1], 'the edge of a left face descends to the right, two columns to a step');
  calls.length = 0;
  paintCells(ctx, cells, 3, [[1, 4], [5, 8]], 0, 0, 0, left, lit, [92, 98, 112]);
  assert.ok(calls.every((c) => c.colour === 'rgb(92,98,112)'), 'unknown: every window the neutral grey');
  calls.length = 0;
  paintCells(ctx, cells, 3, [[1, 4], [5, 8]], 0, 0, 37, left, lit, socket, true);
  const shaded = Array.from({length: 100}, (_, i) => calls[i * 6].colour);
  assert.ok(new Set(shaded.slice(0, 37)).size >= 4, 'the lights have subtly different shades');
  assert.ok(shaded.slice(0, 37).every(c => c !== 'rgb(16,30,52)'), 'all 37 quota cells remain lit');
  assert.ok(shaded.slice(37).every(c => c === 'rgb(16,30,52)'), 'variation never lights a spent cell');
});

/* ------------------------------------------------------------------------------------------------------------------------------- the sun and the clock */

test('the sun is where it should be: noon in midsummer, sunset in November, the middle of the night', () => {
  const noon = Math.max(...Array.from({length: 60}, (_, i) => sunAltitude(Date.parse('2026-06-21T11:00:00Z') + i * 60000, BARCELONA.lat, BARCELONA.lon)));
  assert.ok(Math.abs(noon - 72.05) < 0.4, `${noon.toFixed(2)} degrees at midsummer noon (72.05 expected)`);
  assert.ok(Math.abs(sunAltitude(Date.parse('2026-11-09T16:35:00Z'), BARCELONA.lat, BARCELONA.lon)) < 1.5, 'sunset in Barcelona on 9 November is about 16:35 UTC');
  assert.ok(sunAltitude(Date.parse('2026-11-09T15:35:00Z'), BARCELONA.lat, BARCELONA.lon) > 5);
  assert.ok(sunAltitude(Date.parse('2026-11-09T00:30:00Z'), BARCELONA.lat, BARCELONA.lon) < -40);
  assert.ok(sunAltitude(Date.parse('2026-12-21T11:15:00Z'), BARCELONA.lat, BARCELONA.lon) < 26, 'winter noon is low');
});

test('the four times of day always add up to one, mix at most two neighbours, and follow the sun', () => {
  const order = ['day', 'gold', 'blue', 'night'];
  for (let alt = -40; alt <= 90; alt += 0.5) {
    const w = phaseWeights(alt), values = order.map((p) => w[p]);
    assert.ok(Math.abs(values.reduce((a, b) => a + b, 0) - 1) < 1e-9, `${alt}`);
    const on = values.map((v, i) => (v > 0 ? i : -1)).filter((i) => i >= 0);
    assert.ok(on.length <= 2 && (on.length === 1 || on[1] - on[0] === 1), `${alt}: ${JSON.stringify(w)}`);
  }
  assert.equal(phaseWeights(60).day, 1);
  assert.equal(phaseWeights(3).gold, 1);
  assert.equal(phaseWeights(-20).night, 1);
  assert.ok(phaseWeights(-8).blue > 0.5);
  let last = phaseWeights(-40).night;
  for (let alt = -40; alt <= 0; alt += 1) { const n = phaseWeights(alt).night; assert.ok(n <= last + 1e-9, 'night only fades as the sun rises'); last = n; }
});

test('the window lights come on batch by batch as the sun goes down and go out as it rises, never all at once', () => {
  let last = -1;
  for (let alt = 60; alt >= -30; alt -= 0.5) { const level = lightLevel(alt); assert.ok(level >= last - 1e-9 && level >= 0 && level <= 1, `${alt}`); last = level; }
  assert.ok(lightLevel(40) < 0.05, 'in full daylight hardly any');
  assert.equal(lightLevel(-30), 1, 'all of them at night');
  assert.ok(lightLevel(0) > 0.1 && lightLevel(0) < 0.4, 'a few at sunset');
  assert.equal(batchAlphas(0, 10).every((a) => a === 0), true);
  assert.equal(batchAlphas(1, 10).every((a) => a === 1), true);
  assert.deepEqual(batchAlphas(0.5, 10), [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]);
  const partial = batchAlphas(0.37, 10);
  assert.equal(partial.filter((a) => a > 0 && a < 1).length, 1, 'one batch is on its way at a time');
  for (let level = 0; level < 1; level += 0.01) { const a = batchAlphas(level, 10), b = batchAlphas(level + 0.01, 10); assert.ok(a.every((v, i) => b[i] >= v - 1e-9), 'a batch never goes out while the sun goes down'); }
});

test('the evening of 9 November in Barcelona: day, then gold, then blue, then night, lights growing all the way, and the reverse at dawn', () => {
  const at = (iso) => dayState(Date.parse(iso), BARCELONA);
  assert.equal(at('2026-11-09T11:00:00Z').weights.day, 1);
  assert.ok(at('2026-11-09T11:00:00Z').lights < 0.05);
  assert.ok(at('2026-11-09T16:00:00Z').weights.gold > 0.9);
  assert.ok(at('2026-11-09T16:55:00Z').weights.blue > 0.4);
  assert.equal(at('2026-11-09T19:30:00Z').weights.night, 1);
  assert.equal(at('2026-11-09T19:30:00Z').lights, 1);
  assert.ok(at('2026-11-09T19:30:00Z').stars > 0.95 && at('2026-11-09T12:00:00Z').stars === 0);
  assert.ok(at('2026-11-09T19:30:00Z').dusk > 0.95 && at('2026-11-09T12:00:00Z').dusk === 0);
  let last = -1;
  for (let m = 14 * 60; m <= 20 * 60; m += 5) { const v = dayState(Date.parse('2026-11-09T00:00:00Z') + m * 60000, BARCELONA).lights; assert.ok(v >= last - 1e-9, 'lights only increase through the evening'); last = v; }
  last = 2;
  for (let m = 4 * 60; m <= 9 * 60; m += 5) { const v = dayState(Date.parse('2026-11-09T00:00:00Z') + m * 60000, BARCELONA).lights; assert.ok(v <= last + 1e-9, 'lights only decrease through the morning'); last = v; }
  assert.equal(at('2026-11-09T04:00:00Z').weights.night, 1);
  assert.ok(at('2026-11-09T06:20:00Z').weights.blue > 0.3, 'blue hour before sunrise');
  assert.ok(at('2026-11-09T07:10:00Z').rising > .9, 'sunrise has morning light');
  assert.ok(at('2026-11-09T16:10:00Z').rising < .1, 'sunset has evening light');
});

test('the moon has a phase that follows the month, and the weather of a night depends only on its date', () => {
  assert.ok(moonPhase(Date.UTC(2000, 0, 6, 18, 14)) < 0.001);
  assert.ok(Math.abs(moonPhase(Date.UTC(2000, 0, 21, 4, 40)) - 0.5) < 0.03, 'full moon on 21 January 2000');
  const nearNew = moonPhase(Date.UTC(2026, 10, 9, 13, 0));
  assert.ok(nearNew < 0.02 || nearNew > 0.98, 'new moon on 9 November 2026');
  for (let i = 0; i < 400; i++) { const p = moonPhase(Date.UTC(2026, 0, 1) + i * 86400000 * 1.7); assert.ok(p >= 0 && p < 1); }
  const offset = -60;                                         // UTC+1: the local day starts an hour early in UTC
  const local = (iso) => weatherFor(Date.parse(iso), offset);
  assert.equal(local('2026-11-09T00:10:00+01:00'), local('2026-11-09T23:50:00+01:00'), 'one date, one weather');
  assert.equal(weatherFor(NOW, offset), weatherFor(NOW + 1000, offset));
  const counts = {clear: 0, rain: 0, fog: 0};
  for (let d = 0; d < 720; d++) counts[weatherFor(Date.UTC(2026, 0, 1) + d * 86400000 + 43200000, offset)]++;
  assert.equal(counts.clear + counts.rain + counts.fog, 720);
  assert.ok(counts.clear > 720 * 0.6 && counts.rain > 720 * 0.08 && counts.fog > 720 * 0.03, JSON.stringify(counts));
});

/* ---------------------------------------------------------------------------------------------------------------------- traffic, lights and what hides what */

test('traffic lights: the two directions are never green together, each has a red, and every crossing is shifted', () => {
  const states = [];
  for (let t = 0; t < 56; t += 0.25) {
    const x = lightState(0, 'x', t), y = lightState(0, 'y', t);
    assert.ok(!(x === 'g' && y === 'g'), `${t}`);
    assert.ok(['g', 'y', 'r'].includes(x));
    states.push(x);
  }
  assert.ok(states.includes('g') && states.includes('y') && states.includes('r'));
  assert.equal(lightState(3, 'x', 5), lightState(3, 'x', 5 + city.LIGHT_PERIOD), 'periodic');
  const set = new Set(Array.from({length: 12}, (_, i) => lightState(i, 'x', 4)));
  assert.ok(set.size > 1, 'neighbouring crossings do not all breathe in step');
  assert.equal(lightState(0, 'x', -3), lightState(0, 'x', city.LIGHT_PERIOD - 3));
});

test('a building hides what is behind it and nothing else: in front, beside, above and under it', () => {
  const box = [12, 12, 14, 14, 0, 30];
  assert.equal(hiddenBy(box, 10, 10, 0), true, 'directly behind');
  assert.equal(hiddenBy(box, 15, 15, 0), false, 'in front');
  assert.equal(hiddenBy(box, 10, 20, 0), false, 'beside');
  assert.equal(hiddenBy(box, 20, 10, 0), false, 'beside, the other way');
  assert.equal(hiddenBy(box, 10, 10, 40), false, 'above its roof line');
  assert.equal(hiddenBy([12, 12, 14, 14, 0, 100], 3, 3, 0), true, 'a long way behind a very tall building is still hidden');
  assert.equal(hiddenBy(box, 3, 3, 0), false, 'but nine cells behind a 30-pixel building the camera sees over it');
  assert.equal(hiddenBy(box, 8, 8, 0), true, 'four cells behind it is hidden');
  const deck = [20, 25.2, 24, 25.8, 11.4, 13.2];                                // a viaduct: a street under it is open, the track on it is not
  assert.equal(hiddenBy(deck, 21, 25.3, 1), false, 'a car under the deck');
  assert.equal(hiddenBy(deck, 18, 23.2, 14), false, 'a train behind it but higher than the deck');
  assert.equal(hiddenBy(deck, 18, 23.5, 0), true, 'a boat low in the water just behind the bridge: the deck is in the way');
  assert.equal(hiddenBy(deck, 18, 21.5, 0), false, 'a boat farther back: the camera looks over the thin deck');
});

test('the id picture decides: no building, a lawn, a rail and a building', () => {
  const ids = new Uint16Array(9);
  ids[4] = 1; ids[5] = 2; ids[7] = 3;
  const boxes = [null, [12, 12, 14, 14, 0, 30, 0], null, [12, 12, 14, 14, 0, 30, 1]];
  assert.equal(isHidden(ids, 3, boxes, 0, 0, 10, 10, 0, false), false, 'nothing drawn there');
  assert.equal(isHidden(ids, 3, boxes, 1, 1, 10, 10, 0, false), true, 'a building there, and the point is behind it');
  assert.equal(isHidden(ids, 3, boxes, 2, 1, 10, 10, 0, false), false, 'a lawn hides nothing');
  assert.equal(isHidden(ids, 3, boxes, 1, 2, 10, 10, 0, false), true, 'a rail hides what is behind it...');
  assert.equal(isHidden(ids, 3, boxes, 1, 2, 10, 10, 0, true), false, '...but not the train that runs on it');
  assert.equal(isHidden(ids, 3, boxes, -1, 0, 10, 10, 0, false), false);
  assert.equal(isHidden(ids, 3, boxes, 5, 0, 10, 10, 0, false), false);
});

const laneWithLight = () => [{a: [0, 26], b: [30, 26], axis: 'x', sign: 1, cross: [[10, 0]]}];
const snapshot = (sim) => JSON.stringify(sim.lanes.map((l) => l.cars.map((c) => [c.kind, +c.s.toFixed(4), +c.v.toFixed(4)])));

test('traffic is the same for the same seed and different for another', () => {
  const run = (seed) => {
    const rnd = games.seeded(seed), sim = makeTraffic(laneWithLight(), rnd);
    for (let i = 0; i < 900; i++) stepTraffic(sim, 1 / 30, i / 30, rnd);
    return snapshot(sim);
  };
  assert.equal(run(11), run(11));
  assert.notEqual(run(11), run(12));
});

test('cars keep a gap, queue at a red light, go on green, and leave at one end to come back at the other', () => {
  const rnd = games.seeded(3), sim = makeTraffic(laneWithLight(), rnd), entry = sim.lanes[0];
  const stop = 10, count = entry.cars.length;
  assert.ok(count >= 2);
  // the light for this crossing is red for the x direction from t = 13 s to t = 28 s: start inside that spell
  entry.cars.forEach((car, i) => { car.s = 8 - i * 3.2; car.v = 0.8; });
  let t = 13, maxBeforeStop = 0;
  for (let i = 0; i < Math.round(14.5 * 30); i++, t += 1 / 30) {
    stepTraffic(sim, 1 / 30, t, rnd);
    assert.equal(lightState(0, 'x', t) !== 'g', true);
    for (const car of entry.cars) if (car.s < stop + 2) maxBeforeStop = Math.max(maxBeforeStop, car.s);
    const sorted = [...entry.cars].sort((a, b) => b.s - a.s);
    for (let k = 1; k < sorted.length; k++) assert.ok(sorted[k - 1].s - sorted[k].s > 0.2, 'no two cars on top of each other');
  }
  assert.ok(maxBeforeStop <= stop + 0.4, `nobody ran the red light (front car at ${maxBeforeStop.toFixed(2)})`);
  for (let i = 0; i < 20 * 30; i++, t += 1 / 30) stepTraffic(sim, 1 / 30, t, rnd);
  assert.ok(Math.max(...entry.cars.map((c) => c.s)) > stop + 1, 'on green they go');
  for (let i = 0; i < 120 * 30; i++, t += 1 / 30) stepTraffic(sim, 1 / 30, t, rnd);
  assert.equal(entry.cars.length, count, 'the same number of vehicles for ever: those that leave come back');
  assert.ok(entry.cars.every((c) => Number.isFinite(c.s) && c.s > -40 && c.s < 40));
});

test('a street with nothing in it makes no lane, and a tiny one is ignored', () => {
  assert.equal(makeTraffic([], games.seeded(1)).lanes.length, 0);
  assert.equal(makeTraffic([{a: [0, 0], b: [0.5, 0], axis: 'x', sign: 1}], games.seeded(1)).lanes.length, 0);
});

test('the city camera stays exactly still, for any time and phase', () => {
  for (let t = 0; t < 3600; t += 1 / 30) assert.deepEqual(cameraAt(t, t / 7, [12, 12]), [12, 12]);
  assert.deepEqual(cameraAt(500, 0.4), [12, 12]);
  assert.deepEqual(cameraAt(20, 0, [8, 6]), [8, 6]);
});

/* ------------------------------------------------------------------------------------------------------------------------------------ sprites */

const fakeCanvas = (w, h) => {
  const ctx = new Proxy({}, {
    get(target, key) {
      if (key in target) return target[key];
      if (key === 'getImageData') return (x, y, ww, hh) => ({data: new Uint8ClampedArray(ww * hh * 4)});
      if (key === 'createImageData') return (ww, hh) => ({data: new Uint8ClampedArray(ww * hh * 4)});
      if (key === 'createRadialGradient') return () => ({addColorStop() {}});
      return () => {};
    },
    set(target, key, value) { target[key] = value; return true; },
  });
  return {width: w, height: h, getContext: () => ctx};
};

test('little isometric boxes become whole pixels, the same every time, with lights on the visible end', () => {
  const box = {x0: 0, y0: 0, x1: 0.62, y1: 0.3, z0: 0, z1: 2.2, body: [200, 30, 30], glass: [0.5, 0.88]};
  const a = rasterise([box], null, [{face: 'right', colour: [255, 255, 255]}], fakeCanvas), b = rasterise([box], null, [{face: 'right', colour: [255, 255, 255]}], fakeCanvas);
  assert.deepEqual(a.pixels, b.pixels);
  assert.ok(a.pixels.length > 12 && a.pixels.length < 80, `${a.pixels.length} pixels`);
  assert.ok(a.pixels.every(([x, y]) => Number.isInteger(x) && Number.isInteger(y) && x >= 0 && y >= 0 && x < a.w && y < a.h));
  assert.ok(a.pixels.filter((p) => p[2].join() === '255,255,255').length >= 1, 'a headlight');
  assert.ok(a.ax >= 0 && a.ax < a.w && a.ay >= 0 && a.ay < a.h, 'the anchor is inside the sprite');
  const tall = rasterise([{...box, z1: 8}], null, null, fakeCanvas);
  assert.ok(tall.h > a.h, 'a taller box is taller');
  const text = city.textStrip('AI', fakeCanvas);
  assert.equal(text.width, 8);
  assert.ok(city.FONT.A.split('|').length === 5 && Object.values(city.FONT).every((g) => g.split('|').length === 5 && g.split('|').every((r) => r.length === 3)), 'a 3 x 5 pixel font');
});

test('vehicles fit the street without losing their shape at tablet resolution', () => {
  const s = {sprites: new Map(), mk: fakeCanvas};
  const size = (kind, lit = false) => { const r = vehicleSprite(s, kind, [200, 30, 30], 'x', 1, lit); return {w: r.w, h: r.h, n: r.pixels.length}; };
  const car = size('car'), taxi = size('taxi'), van = size('van'), truck = size('truck'), bus = size('bus');
  assert.ok(car.w <= 5 && car.h <= 4, `a car is ${car.w} x ${car.h}`);
  assert.ok(car.n >= 5 && car.n <= 10, `${car.n} pixels in a car`);
  assert.ok(taxi.w <= 6 && taxi.h <= 6);
  assert.ok(van.w <= 7 && van.h <= 6 && van.n > car.n);
  assert.ok(truck.w <= 9 && truck.h <= 7);
  assert.ok(bus.w <= 11 && bus.h <= 7, `a bus is ${bus.w} x ${bus.h} (it was 13 x 10)`);
  assert.ok(bus.w >= 1.6 * car.w && bus.n > 2.5 * car.n, 'a bus is much longer than a car');
  assert.ok(VEHICLES.car.len <= .4 && VEHICLES.car.wid <= .17 && VEHICLES.bus.len / VEHICLES.car.len > 2 && VEHICLES.bus.len / VEHICLES.car.len < 3.2, 'cars stay small relative to a street and buses remain visibly longer');
  for (const kind of Object.keys(VEHICLES)) for (const axis of ['x', 'y']) for (const sign of [1, -1]) {
    const r = vehicleSprite(s, kind, [40, 80, 150], axis, sign, false);
    assert.ok(r.pixels.length > 4 && r.pixels.every(([x, y]) => x >= 0 && y >= 0 && x < r.w && y < r.h && Number.isInteger(x) && Number.isInteger(y)), `${kind} ${axis}${sign}`);
  }
});

test('the helicopter faces its diagonal path in both directions with its rotor upright', () => {
  const s = {sprites:new Map(), mk:fakeCanvas};
  const a = heliSprite(s,0,0), b = heliSprite(s,1,0), next = heliSprite(s,0,1);
  assert.ok(a.w >= 15 && a.w <= 40 && a.h >= 8 && a.h <= 25, `${a.w} x ${a.h}`);
  assert.ok(a.pixels.length > 40 && new Set(a.pixels.map(p=>p[3])).size >= 5, 'glass, body, faces and rotors');
  const coords = p => p.pixels.map(([x,y,,colour])=>`${x},${y},${colour}`).sort();
  const centre = (sprite, colour) => {
    const pixels = sprite.pixels.filter(p => p[3] === colour);
    assert.ok(pixels.length, `${colour} is visible`);
    return pixels.reduce((v, p) => [v[0] + p[0] / pixels.length, v[1] + p[1] / pixels.length], [0, 0]);
  };
  for (const [sprite, dir] of [[a,-1], [b,1]]) {
    const nose = centre(sprite, 'rgb(128,204,228)'), rotor = centre(sprite, 'rgb(210,218,221)');
    assert.ok((nose[0] - rotor[0]) * dir > 1, 'cockpit faces its direction of travel');
    assert.ok(nose[1] > rotor[1], 'the cockpit stays below the rotor');
    assert.ok(rotor[1] < sprite.h * .55, 'the rotor stays on top');
  }
  assert.ok(centre(b, 'rgb(128,204,228)')[1] > centre(a, 'rgb(128,204,228)')[1] + 1,
            'the outward-facing cockpit points down the diagonal, the return-facing one up');
  assert.notDeepEqual(coords(a),coords(next), 'the rotor changes its orientation');
  assert.equal(heliSprite(s,0,0),a, 'sprites are cached');
});

test('the occasional pigeons flap and a delivery drone has lights and moving thrusters', () => {
  const s = {sprites:new Map(), mk:fakeCanvas};
  const a = pigeonSprite(s,false,0), b = pigeonSprite(s,false,1);
  assert.notDeepEqual(a.pixels,b.pixels);
  assert.ok(a.w <= 6 && a.h <= 5);
  const hero = courierSprite(s,false,0), flutter = courierSprite(s,false,1);
  const colours = new Set(hero.pixels.map(p=>p[3]));
  assert.ok(colours.has('#d9e6ec') && colours.has('#57dce4') && colours.has('#f68cbb'));
  assert.notDeepEqual(hero.pixels,flutter.pixels);
  assert.ok(hero.w <= 15 && hero.h <= 8, 'the drone remains small and completely opaque');
});

test('the flying hero is drawn at full opacity after the data-building windows', () => {
  const api = fakeApi(7, null), scene = city.scene;
  scene.dbg = {now: NOW, noStale: true};
  scene.init(api);
  Object.assign(scene.s.courier, {active: true, u: .5, dir: 1});
  scene.s.clock = 0;
  const sprite = courierSprite(scene.s, false, 0), calls = [];
  const ctx = new Proxy({globalAlpha: 1, globalCompositeOperation: 'source-over'}, {
    get(target, key) {
      if (key === 'drawImage') return (image) => calls.push({image, alpha: target.globalAlpha, mode: target.globalCompositeOperation});
      if (key in target) return target[key];
      return () => {};
    },
    set(target, key, value) { target[key] = value; return true; },
  });
  scene.draw(api, ctx);
  const heroIndex = calls.findIndex(call => call.image === sprite.canvas);
  const towerIndexes = Object.values(scene.s.towers).map(tower => calls.findIndex(call => call.image === tower.canvas));
  assert.ok(heroIndex >= 0 && towerIndexes.every(index => index >= 0 && index < heroIndex), 'no tower window is painted over the hero');
  assert.equal(calls[heroIndex].alpha, 1);
  assert.equal(calls[heroIndex].mode, 'source-over');
});

test('vehicle lights come on after dusk only: headlights and a beam ahead, tail lights and a glow behind, all in the sprite (nothing more to draw)', () => {
  const s = {sprites: new Map(), mk: fakeCanvas};
  const day = vehicleSprite(s, 'car', [60, 90, 140], 'x', 1, false), night = vehicleSprite(s, 'car', [60, 90, 140], 'x', 1, true);
  const has = (r, f) => r.pixels.some((p) => f(p[2]));
  assert.ok(!has(day, (c) => c.length > 3 || (c[0] > 240 && c[1] > 230)), 'by day: no light at all');
  assert.ok(has(night, (c) => c[0] > 240 && c[1] > 230 && c[2] > 170 && c.length === 3), 'a headlight');
  assert.ok(has(night, (c) => c.length > 3 && c[3] < .5), 'a faint beam on the road');
  const tail = vehicleSprite(s, 'car', [60, 90, 140], 'x', -1, true);
  assert.ok(has(tail, (c) => c[0] > 240 && c[1] < 90 && c.length === 3), 'a vehicle going away shows its red tail lights');
  assert.ok(night.pixels.length > day.pixels.length, 'the beam and the glow are extra pixels');
  assert.equal(vehicleSprite(s, 'car', [60, 90, 140], 'x', 1, true), night, 'sprites are made once');
  const bus = vehicleSprite(s, 'bus', [222, 120, 36], 'x', 1, true), busDay = vehicleSprite(s, 'bus', [222, 120, 36], 'x', 1, false);
  assert.ok(has(bus, (c) => c[0] > 240 && c[1] > 200 && c[2] > 120 && c.length === 3 && c[2] < 200), 'a bus has its windows lit at night');
  assert.ok(!has(busDay, (c) => c[0] > 240 && c[1] > 215 && c[2] > 140 && c[2] < 170), 'and dark by day');
});

test('the traffic is a lot of small vehicles in a fixed budget: about one every three and a half cells of street, never more than the cap, of several kinds and many colours', () => {
  const lanes = Array.from({length: 40}, (_, i) => ({a: [0, 10 + i * 5.3], b: [60, 10 + i * 5.3], axis: 'x', sign: 1, cross: []}));
  const sim = makeTraffic(lanes, games.seeded(8));
  const cars = sim.lanes.flatMap((l) => l.cars);
  assert.ok(cars.length <= MAX_VEHICLES + 40 && cars.length >= 100, `${cars.length} vehicles on 2400 cells of street`);
  const kinds = new Set(cars.map((c) => c.kind));
  assert.ok(['car', 'taxi', 'van', 'bus'].every((k) => kinds.has(k)), [...kinds].join());
  assert.ok(new Set(cars.map((c) => c.colour.join())).size >= 8, 'varied colours');
  assert.ok(cars.filter((c) => c.kind === 'car').length > cars.length * .5, 'mostly cars');
  const few = makeTraffic([{a: [0, 10], b: [20, 10], axis: 'x', sign: 1, cross: []}], games.seeded(8)).lanes[0].cars.length;
  assert.ok(few >= 4 && few <= 8, `${few} vehicles on a street of twenty cells`);
});

test('rasterise can sample each pixel finely (the commonest colour wins) and keeps a translucent colour as one', () => {
  const box = {x0: 0, y0: 0, x1: 0.46, y1: 0.2, z0: 0, z1: 1.9, body: [200, 30, 30]};
  const fine = rasterise([box], [{pts: [[6, 3], [9, 3], [9, 5], [6, 5]], colour: [255, 240, 190, 0.3]}], null, fakeCanvas, 3);
  assert.ok(fine.pixels.some((p) => p[3].startsWith('rgba(255,240,190,0.3)')), 'a beam is a translucent pixel');
  assert.deepEqual(fine.pixels, rasterise([box], [{pts: [[6, 3], [9, 3], [9, 5], [6, 5]], colour: [255, 240, 190, 0.3]}], null, fakeCanvas, 3).pixels, 'repeatable');
  const coarse = rasterise([box], null, null, fakeCanvas);
  assert.ok(coarse.pixels.length > 4);
});

/* ---------------------------------------------------------------------------------------------------------------------------------- the whole scene */

function fakeData() {
  const frames = {idmap: [0, 0, 291, 451]};
  for (const p of ['day', 'gold', 'blue', 'night']) { frames['city-' + p] = [0, 0, 291, 451]; frames['sky-' + p] = [0, 0, 291, 80]; for (let n = 0; n < 3; n++) frames[`cloud-${n}-${p}`] = [0, 0, 54, 15]; }
  for (let k = 0; k < 10; k++) frames['lights-' + k] = [0, 0, 291, 451];
  const cells = (n, x0) => Array.from({length: n}, (_, i) => [x0 + (i % 10) * 5, 150 - Math.floor(i / 10) * 9, i % 10 < 5 ? 1 : -1]);
  const tower = (name, box) => ({box, w: 3, rows: [[1, 4], [5, 8]], cells: cells(100, box[0] + 2), lit: [255, 220, 136], lit_left: [222, 190, 120], socket: [16, 30, 52], unknown: [92, 98, 112], floors: 10, cols: 10});
  return {
    version: 1, size: [267, 427], world: [291, 451], margin: [12, 12], proj: {hw: 6, hh: 3, ox: 146, oy: -48}, phases: ['day', 'gold', 'blue', 'night'], buckets: 10, skyRows: 80,
    place: BARCELONA, sunX: 206, canal: [66, 70], bridges: [], frames, boxes: [null, [40, 40, 44, 44, 0, 30, 0], [-2, 25.2, 2, 25.8, 11.4, 19, 1]],
    towers: {codex: tower('codex', [60, 40, 120, 160]), claude: tower('claude', [140, 40, 200, 160]),
      small: {box: [200, 100, 260, 160], w: 2, rows: [[2, 6]], quota: cells(40, 202), time: cells(40, 232), lit_quota: [226, 220, 207], lit_time: [150, 142, 126], socket: [14, 20, 34], unknown: [92, 98, 112], floors: 5, cols: 8}},
    lanes: [{a: [30, 26.3], b: [50, 26.3], axis: 'x', sign: 1, cross: [[8, 0]]}, {a: [50, 26.7], b: [30, 26.7], axis: 'x', sign: -1, cross: []}, {a: [40.3, 30], b: [40.3, 44], axis: 'y', sign: 1, cross: []}],
    walks: [{a: [30, 26.1], b: [44, 26.1], axis: 'x', sign: 1}, {a: [10, 10], b: [12, 12], axis: 'p', sign: 1}], boats: [{a: [6, 22.5], b: [40, 22.5], kinds: 'fs'}, {a: [16.5, 28], b: [16.5, 60], kinds: 'ts'}],
    lights: [[40, 25]], poles: [[100, 100, 0, 0], [110, 100, 0, 1]], beacons: [[50, 60], [70, 70]], vents: [[60, 120], [90, 130]], manholes: [[80, 190]], fountains: [[70, 180]],
    screens: [{q: [[10, 100], [20, 105], [20, 95], [10, 90]], c: [200, 50, 50]}], poke: [[100, 100, 2, 3], [104, 100, 2, 3], [108, 104, 2, 3]], rail: {a: [-2, 25.5], b: [54, 25.5], z: 13.2},
  };
}
function fakeApi(seed, readings, tier = 'high') {
  const rnd = games.seeded(seed);
  return {name: 'city-iso', size: [267, 427], atlas: {}, json: fakeData(), time: 0, tier, random: rnd, view: {top: 0, bottom: 427}, readings: () => readings, sprite() { return false; }};
}
const recorder = () => {
  const calls = {n: 0, byName: {}};
  const ctx = new Proxy({}, {
    get(target, key) {
      if (key in target) return target[key];
      return (...args) => { calls.n++; calls.byName[key] = (calls.byName[key] || 0) + 1; };
    },
    set(target, key, value) { target[key] = value; return true; },
  });
  return {ctx, calls};
};
globalThis.document = {createElement: () => fakeCanvas(1, 1)};

test('the scene is registered with the engine: portrait native size, needs its atlas, and has the four functions', () => {
  const scene = games.registry['city-iso'];
  assert.ok(scene, 'TabletGames.define was called');
  assert.deepEqual(scene.size, [267, 427]);
  assert.ok(267 * 3 >= 800 && 427 * 3 >= 1280 && 267 <= 512 && 427 <= 768, 'x3 on the panel and within the engine limit');
  assert.equal(scene.needsAtlas, true);
  for (const f of ['init', 'step', 'draw', 'poke']) assert.equal(typeof scene[f], 'function');
});

test('the new visitors enter and leave naturally while the camera remains fixed', () => {
  const scene = games.registry['city-iso'], api = fakeApi(9, null);
  scene.dbg = {now: NOW, noStale:true};
  scene.init(api);
  const s = scene.s, {ctx} = recorder();
  s.pigeons.wait = 0; s.courier.wait = 0;
  scene.step(api, 1/30);
  assert.ok(s.pigeons.active && s.courier.active);
  for (let i = 0; i < 500; i++) {
    scene.step(api, 1/30);
    if (i % 15 === 0) scene.draw(api, ctx);
    assert.deepEqual(s.cam, [12,12]);
  }
  assert.equal(s.pigeons.active,false);
  assert.equal(s.courier.active,false);
  assert.ok(s.pigeons.wait > 0 && s.courier.wait > 0);
  assert.equal(s.off,undefined, JSON.stringify(s.off));
});

test('the helicopter flies diagonally on both its outward and return paths', () => {
  const scene = games.registry['city-iso'], api = fakeApi(9, null);
  scene.dbg = {now: NOW, noStale:true}; scene.init(api);
  const heli = scene.s.heli;
  for (const dir of [1, -1]) {
    Object.assign(heli, {active:true, x:100, y:40, dir, speed:12});
    scene.step(api, 1 / 30);
    assert.ok((heli.x - 100) * dir > 0 && (heli.y - 40) * dir > 0, 'both coordinates follow the diagonal');
  }
});

test('fog banks leave the picture, pause, and enter again without popping into view', () => {
  const fog = [0, 1, 2].map(() => ({canvas: {width: 120}, active: false, x: 0, y: 100, speed: 3, dir: 1}));
  const s = {W: 291, fog, fogLast: 0, fogWait: 0, rnd: () => .2};
  Object.assign(fog[0], {active: true, x: 290});
  city.stepFog(s, 1);
  assert.ok(fog.every(f => !f.active), 'a bank is gone only after leaving the right edge');
  assert.ok(s.fogWait >= 15, 'the city can be clear for a while');
  city.stepFog(s, s.fogWait - .1);
  assert.ok(fog.every(f => !f.active), 'nothing appears during the clear interval');
  city.stepFog(s, .2);
  const next = fog.find(f => f.active);
  assert.ok(next && next !== fog[0], 'a different bank enters next');
  assert.equal(next.x, -next.canvas.width, 'it starts completely outside the left edge');
  const x = next.x;
  city.stepFog(s, 1);
  assert.ok(next.x > x, 'the bank drifts across the city');
  Object.assign(next, {dir: -1, x: -next.canvas.width + .1});
  city.stepFog(s, 1);
  assert.equal(next.active, false, 'a bank can also leave through the left edge');
  s.rnd = () => .9;
  city.stepFog(s, s.fogWait + .1);
  const returning = fog.find(f => f.active);
  assert.ok(returning && returning !== next);
  assert.equal(returning.x, s.W, 'a bank entering from the right starts off-screen too');
  city.stepFog(s, 1);
  assert.ok(returning.x < s.W, 'the return bank drifts left');
});

test('cloud shadows and faint mist drift without moving the camera or hiding the readings', () => {
  const scene = games.registry['city-iso'], api = fakeApi(9, {providers: {codex: {weekly: week(73)}}});
  scene.dbg = {now: NOW, weather:'clear', noStale:true};
  scene.init(api);
  const s = scene.s, shadows = s.cloudShadows.map(c => c.x), fog = s.fog.find(f => f.active), x = fog.x;
  for (let i = 0; i < 150; i++) scene.step(api, 1/30);
  assert.ok(s.cloudShadows.every((c, i) => c.x !== shadows[i]));
  assert.notEqual(fog.x, x);
  assert.ok(s.fogAmount > .03, 'a light animated haze exists even without foggy weather');
  assert.equal(s.data_.codex.count, 73);
  assert.deepEqual(s.cam, [12,12]);
  scene.draw(api, recorder().ctx);
  assert.equal(s.off, undefined, JSON.stringify(s.off));
});

test('the scene runs: init, a thousand steps and draws at every tier, with every kind of reading, and nothing throws or switches itself off', () => {
  const scene = games.registry['city-iso'];
  const readings = [null, {providers: {codex: {weekly: week(73)}, claude: {weekly: week(58), session: {remaining: 26, resets_at: sec(Date.now()) + 7200}}}}, {providers: {codex: {weekly: week(0)}}}, {providers: 3}, {}];
  for (const tier of ['high', 'medium', 'light', 'low']) {
    for (const r of readings) {
      const api = fakeApi(5, r, tier);
      scene.dbg = {now: Date.parse('2026-11-09T19:30:00Z'), weather: 'rain', noStale: true};
      scene.init(api);
      const {ctx, calls} = recorder();
      for (let i = 0; i < 400; i++) { api.time = i / 30; scene.step(api, 1 / 30); if (i % 10 === 0) scene.draw(api, ctx); }
      scene.poke(api, 100, 100);
      scene.draw(api, ctx);
      assert.equal(scene.s.off, undefined, `${tier}: ${JSON.stringify(scene.s.off)}`);
      assert.ok(calls.n > 20);
    }
  }
});

test('one frame costs a bounded number of drawing calls (the tablet is slow), and the light tiers do less', () => {
  const scene = games.registry['city-iso'], count = (tier, now, weather) => {
    const api = fakeApi(9, {providers: {codex: {weekly: week(73)}, claude: {weekly: week(58)}}}, tier);
    scene.dbg = {now: Date.parse(now), weather, noStale: true};
    scene.init(api);
    for (let i = 0; i < 300; i++) scene.step(api, 1 / 30);
    const {ctx, calls} = recorder();
    scene.draw(api, ctx);
    return calls.n;
  };
  const night = count('high', '2026-11-09T19:30:00Z', 'rain'), day = count('high', '2026-11-09T12:00:00Z', 'clear'), low = count('low', '2026-11-09T19:30:00Z', 'rain');
  assert.ok(night < 1500 && day < 1500, `${night} calls at night, ${day} by day`);
  assert.ok(low <= night, 'the low tier draws no more than the high one');
});

test('the simulation is repeatable: the same seed gives the same city, another seed another one', () => {
  const scene = games.registry['city-iso'];
  const run = (seed) => {
    const api = fakeApi(seed, null);
    scene.dbg = {now: NOW, noStale: true};
    scene.init(api);
    for (let i = 0; i < 600; i++) scene.step(api, 1 / 30);
    const s = scene.s;
    return JSON.stringify({cars: snapshot(s.traffic), peds: s.peds.map((p) => [+p.s.toFixed(3), p.dir]), boats: s.boats.map((b) => [b.kind, +b.s.toFixed(3)]), beacons: s.beacons.map((b) => +b.phase.toFixed(3)),
      heli: [s.heli.active, +s.heli.x.toFixed(2)], cam: s.cam});
  };
  assert.equal(run(21), run(21));
  assert.notEqual(run(21), run(22));
});

test('the readings reach the buildings and an old one is dropped by the scene itself', () => {
  const scene = games.registry['city-iso'];
  const live = {providers: {codex: {weekly: week(73)}, claude: {weekly: week(58)}}};
  let current = live;
  const api = fakeApi(2, null);
  api.readings = () => current;
  scene.dbg = {now: NOW};
  scene.init(api);
  scene.step(api, 1 / 30);
  assert.deepEqual(scene.s.data_.codex, {known: true, count: 73});
  const {ctx} = recorder();
  scene.draw(api, ctx);
  assert.match(scene.s.towers.codex.sig, /^k73$/);
  current = {providers: {codex: {weekly: week(10)}, claude: {weekly: week(58)}}};      // a new object from the page: a new reading
  scene.step(api, 1 / 30); scene.draw(api, ctx);
  assert.equal(scene.s.towers.codex.sig, 'k10');
  scene.s.readingSeen = Date.now() - STALE_MS - 5000;                                   // the page stopped renewing it
  scene.step(api, 1 / 30); scene.draw(api, ctx);
  assert.equal(scene.s.data_.codex.known, false);
  assert.equal(scene.s.towers.codex.sig, 'u', 'unknown, not frozen');
});

test('the scene lowers its small things by itself when its own drawing is slow (the engine never tells it again), and brings them back when it is fast', () => {
  const scene = games.registry['city-iso'], real = Object.getOwnPropertyDescriptor(globalThis, 'performance');
  let clock = 0, cost = 30;
  Object.defineProperty(globalThis, 'performance', {configurable: true, value: {now: () => (clock += cost)}});
  try {
    const api = fakeApi(4, null);
    scene.dbg = {now: NOW, noStale: true};
    scene.init(api);
    const {ctx} = recorder();
    const run = (seconds) => { for (let i = 0; i < seconds * 30; i++) { scene.step(api, 1 / 30); if (i % 2 === 0) scene.draw(api, ctx); } };
    run(10);
    assert.ok(scene.s.cap < 1, 'slow frames: one notch down');
    run(60);
    assert.equal(scene.s.cap, 0, 'and further down while they stay slow');
    assert.equal(scene.s.quality, 0, 'no people, steam, wakes, glows, rain or screens; the layers and the data buildings stay');
    run(2);
    const {ctx: ctx2, calls} = recorder();
    scene.draw(api, ctx2);
    assert.ok(calls.n > 10, 'it still draws the city and the data buildings');
    assert.equal(scene.s.off, undefined);
    cost = 0.5;
    run(400);
    assert.equal(scene.s.cap, 1, 'a long spell of quick frames brings everything back');
  } finally {
    if (real) Object.defineProperty(globalThis, 'performance', real);
  }
});

test('an atlas with only the essentials still draws, a broken part switches itself off, and an unusable atlas fails once, at init', () => {
  const scene = games.registry['city-iso'];
  const minimal = fakeApi(6, null);
  for (const key of ['lanes', 'walks', 'boats', 'lights', 'poles', 'beacons', 'vents', 'manholes', 'fountains', 'screens', 'poke', 'rail', 'canal', 'bridges', 'sunX', 'place']) delete minimal.json[key];
  scene.dbg = {now: NOW, noStale: true};
  scene.init(minimal);
  const {ctx} = recorder();
  for (let i = 0; i < 120; i++) { scene.step(minimal, 1 / 30); scene.draw(minimal, ctx); }
  scene.poke(minimal, 50, 50);
  assert.equal(scene.s.off, undefined, 'nothing is needed beyond the layers and the data buildings');
  const broken = fakeApi(6, {providers: {codex: {weekly: week(50)}}});
  broken.json.towers.codex.cells = null;                                              // a tower with no windows: that part stops, the rest goes on
  scene.init(broken);
  for (let i = 0; i < 30; i++) { scene.step(broken, 1 / 30); scene.draw(broken, ctx); }
  assert.ok(scene.s.off && scene.s.off.data, 'the data buildings are switched off, once');
  assert.ok(scene.s.off.data.length > 0);
  for (const bad of [{}, {frames: {}}, {frames: {idmap: [0, 0, 1, 1]}}]) {
    const api = fakeApi(6, null);
    api.json = bad;
    assert.throws(() => scene.init(api), /incomplete/, JSON.stringify(bad));
  }
});
