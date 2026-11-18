import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';

// The live effects of the tablet's scene stage (stage-live.js): the page's second check of a scene's `live` block, the region masks, the
// craft paths, the touch bank, the sparkles and sparks, and static guards on the shaders it builds. What a GPU does with those shaders is looked
// at in a real browser (in a separate browser preview), not here.
const require = createRequire(import.meta.url);
const live = require('../token_tv/tablet_web/stage-live.js');
const {normalizeLive, normalizeRegion, rasterRegions, regionWeightAt, weightBilinear, effectiveFeather, craftState, PokeBank, sparkles, sparks, LIMITS, AMP, POKE, BUDGET, budgetFor, intervalFor,
  effectRect, buildGrid, extractLights, placeGlints, placeRain, placeMist, estimateCost} = live;

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} is not ${b}`);
const sample = () => ({
  water: {regions: [[0, .74, 1, 1]], glints: 1.2},
  clouds: {regions: [[[0, 0], [1, 0], [1, .6], [0, .7]]]},
  lights: {}, mist: {regions: [[0, .6, 1, .8]], amount: .4}, rain: {amount: .3},
  craft: [{kind: 'gull', from: [-.1, .2], to: [1.1, .12], seconds: 40}],
});

test('photo wildlife and the extracted craft repeat on a closed 64 second timeline', () => {
  const asset = '/assets/scene-wildlife.png';
  assert.equal(normalizeLive({wildlife: asset}).wildlife, asset);
  assert.equal(normalizeLive({wildlife: 'https://example.com/scene-wildlife.png'}), null);
  for (const name of ['paradise', 'neon-district', 'midnight-video-club', 'city', 'violet-horizon']) {
    assert.deepEqual(live.wildlifeState(name, 0), live.wildlifeState(name, 64));
    for (let frame = 0; frame < 64 * 24; frame++) {
      const t = frame / 24;
      const items = live.wildlifeState(name, t);
      assert.ok(items.every(i => i.alpha >= 0 && i.alpha <= 1 && i.size > 0
        && (i.tile >= 0 && i.tile < 22 || i.tile >= 24 && i.tile < 32)));
      assert.equal(items.length, live.wildlifeState(name, t + 64).length);
    }
  }
  const front = live.wildlifeState('violet-horizon', 6)[0], distant = live.wildlifeState('violet-horizon', 31)[0];
  assert.ok(distant.x > front.x && distant.y > front.y && distant.size < front.size);
  assert.equal(distant.foreground, 'violet');
  assert.ok(live.wildlifeState('midnight-video-club', 54, 'day').some(i => i.tile >= 24));
  assert.ok(!live.wildlifeState('midnight-video-club', 54, 'night').some(i => i.tile >= 24));
});

test('local shoreline and branch motion loop and settle to rest around the bird visit', () => {
  for (const time of [0, 1, 18, 19, 21, 27, 63.5]) {
    for (const kind of ['water', 'clouds']) {
      assert.deepEqual(live.photographMotion('paradise', kind, time, 'day'), live.photographMotion('paradise', kind, time + 64, 'day'));
    }
  }
  assert.deepEqual(live.photographMotion('midnight-video-club', 'clouds', 12, 'day'), [1, 0]);
  assert.ok(live.photographMotion('midnight-video-club', 'clouds', 19, 'day')[1] > 0);
  assert.deepEqual(live.photographMotion('midnight-video-club', 'clouds', 19, 'night'), [0, 0]);
});

test('Paradise gulls cross briskly and have distinct downstrokes and glides', () => {
  const frames = Array.from({length: 42}, (_, i) => live.gullBeat(i / 25, 0).frame);
  assert.ok(frames.some(frame => frame > 1.5 && frame < 2.5), 'the wing reaches the lowered pose');
  assert.ok(frames.some(frame => frame > 5.5 && frame < 6.5), 'the wing reaches the raised pose');
  assert.equal(live.gullBeat(2.4, 0).frame, 0, 'a steady glide follows the stroke burst');
  assert.notEqual(live.gullBeat(.42, 0).frame, live.gullBeat(.42, 1).frame);
  const entering = live.wildlifeState('paradise', 5)[0], leaving = live.wildlifeState('paradise', 11)[0];
  assert.ok(entering.x > .8 && leaving.x < .27);
  assert.ok(live.wildlifeState('paradise', 19).length === 0, 'birds have exited the photograph by then');
});

test('a block is checked again by the page: defaults filled, numbers clamped, nothing usable gives null', () => {
  const cfg = normalizeLive(sample());
  assert.equal(cfg.version, 1);
  assert.deepEqual(Object.keys(cfg).sort(), ['clouds', 'craft', 'lights', 'mist', 'rain', 'version', 'water']);
  assert.equal(cfg.water.amount, 1); assert.equal(cfg.water.glints, 1.2); assert.equal(cfg.water.glint_size, 1); assert.equal(cfg.water.glint_density, 1); assert.equal(cfg.water.horizon, 0.74, 'the horizon defaults to the top of the regions');
  assert.deepEqual(cfg.mist.tint, [0.7, 0.76, 0.9]); assert.deepEqual(cfg.rain.tint, [0.7, 0.8, 1]);
  assert.equal(cfg.craft[0].count, 3); assert.equal(cfg.craft[0].every, 68); assert.equal(cfg.craft[0].size, 0.028);
  const wild = normalizeLive({water: {regions: [[0, .5, 1, 1]], amount: 99, speed: -3, glints: 'lots'}, rain: {amount: 7, angle: 400}, lights: {out: 0.9, cell: 1}});
  assert.equal(wild.water.amount, 2); assert.equal(wild.water.speed, 0.25); assert.equal(wild.water.glints, 1, 'not a number: the default');
  assert.equal(wild.rain.amount, 1); assert.equal(wild.rain.angle, 45); assert.equal(wild.lights.out, 0.5); assert.equal(wild.lights.cell, 3);
  for (const bad of [null, undefined, 3, 'x', [], {}, {version: 1}, {water: {}}, {water: 'wet'}, {water: {regions: []}}, {clouds: {regions: [[0, 0, 0, 1]]}}, {craft: []}, {craft: [{kind: 'ufo', from: [0, 0], to: [1, 1]}]}])
    assert.equal(normalizeLive(bad), null, JSON.stringify(bad));
  assert.notEqual(normalizeLive({lights: {}}), null, 'lights and rain need no regions');
  assert.equal(normalizeLive({water: {regions: [[0, 0, 1, 1]], unknown: 5}}).water.unknown, undefined, 'unknown keys are dropped');
});

test('regions: rectangles and polygons inside the picture, in range and with some area, else refused', () => {
  assert.deepEqual(normalizeRegion([0, .5, 1, 1]), [0, .5, 1, 1]);
  assert.deepEqual(normalizeRegion([[0, 0], [1, 0], [.5, 1]]), [[0, 0], [1, 0], [.5, 1]]);
  assert.deepEqual(normalizeRegion([-1, 0.5, 2, 0.9]), [0, .5, 1, .9], 'clamped into the picture');
  for (const bad of [[], 'a', [1, 2, 3], [.5, .5, .2, .9], [0, .5, 1, .5], [[0, 0], [1, 1]], [[0, 0], [1, 0], [2, 0]], [[0, 0], [1, 0], 'x'], [[0, 0, 0], [1, 0, 0], [1, 1, 0]], null, 5])
    assert.equal(normalizeRegion(bad), null, JSON.stringify(bad));
  const many = Array.from({length: 30}, (_, i) => [Math.cos(i) / 2 + .5, Math.sin(i) / 2 + .5]);
  assert.equal(normalizeRegion(many), null, 'too many points');
  const regions = Array.from({length: 12}, () => [0, 0, .5, .5]);
  assert.equal(normalizeLive({water: {regions}}).water.regions.length, live.MAX_REGIONS, 'only so many regions are kept');
});

test('water glints can be resized and made sparser without changing brightness', () => {
  const w = normalizeLive({water: {regions: [[0, .5, 1, 1]], glints: .8, glint_size: .48, glint_density: .35}}).water;
  assert.equal(w.glints, .8); assert.equal(w.glint_size, .48); assert.equal(w.glint_density, .35);
  const bounded = normalizeLive({water: {regions: [[0, .5, 1, 1]], glint_size: 0, glint_density: 4}}).water;
  assert.equal(bounded.glint_size, .1); assert.equal(bounded.glint_density, 1);
});

test('craft: the same limits as the server, a count that fits the kind, at most four', () => {
  const c = (extra) => normalizeLive({craft: [{kind: 'gull', from: [0, 0], to: [1, 1], ...extra}]});
  assert.equal(c({count: 50}).craft[0].count, 6); assert.equal(c({count: 0}).craft[0].count, 1);
  assert.equal(normalizeLive({craft: [{kind: 'ship', from: [0, 0], to: [1, 1], count: 5}]}).craft[0].count, 1);
  const swallow = extra => normalizeLive({craft: [{kind: 'swallow', from: [-.1, .2], to: [1.1, .2], ...extra}]}).craft[0];
  assert.equal(swallow({}).count, 2); assert.equal(swallow({}).size, .013);
  assert.equal(swallow({count: 1}).count, 1); assert.equal(swallow({count: 9}).count, 2);
  assert.deepEqual(c({from: [-9, 9]}).craft[0].from, [-0.3, 1.3]);
  assert.equal(c({seconds: 1}).craft[0].seconds, 8); assert.equal(c({seconds: 100, every: 20}).craft[0].every, 100, 'a craft never starts again before it has crossed');
  assert.equal(normalizeLive({craft: Array.from({length: 9}, () => ({kind: 'drone', from: [0, 0], to: [1, 0]}))}).craft.length, 4);
  assert.equal(c({from: [.5, .5], to: [.5, .5]}), null, 'no journey');
});

const lampRows = () => [
  {provider: 'codex', x: [.225, .55], y: .7138, count: 26},
  {provider: 'claude', x: [.5656, .8906], y: .7138, count: 26},
];

test('lamps: rows of modules for each provider, defaults filled, any bad row drops the whole effect (half a circuit would read as half a quota)', () => {
  const cfg = normalizeLive({lamps: {rows: lampRows()}});
  assert.deepEqual(Object.keys(cfg).sort(), ['lamps', 'version']);
  assert.equal(cfg.lamps.amount, 1);
  const [codex, claude] = cfg.lamps.rows;
  assert.equal(codex.anchor, 'start', 'Codex is lit from its left (outer) end'); assert.equal(claude.anchor, 'end', 'Claude from its right (outer) end');
  assert.deepEqual(codex.colour, [1, 0.725, 0.27]); assert.deepEqual(claude.colour, [0.318, 0.863, 1]);
  assert.equal(codex.height, 0.0125); assert.equal(codex.count, 26);
  assert.equal(normalizeLive({lamps: {rows: [{provider: 'codex', x: [.2, .5], y: .7}]}}).lamps.rows[0].count, 26, 'the board has 26 modules a half');
  assert.equal(normalizeLive({lamps: {amount: 9, rows: [{provider: 'codex', x: [.2, .5], y: .7, height: 9}]}}).lamps.amount, 2);
  assert.equal(normalizeLive({lamps: {rows: [{provider: 'codex', x: [.2, .5], y: .7, height: 9}]}}).lamps.rows[0].height, 0.05, 'numbers are clamped, like every other effect');
  const bad = [{provider: 'grok'}, {x: [.2, .5], y: .7}, {provider: 'codex', x: [.5, .2], y: .7}, {provider: 'codex', x: [.2, .21], y: .7}, {provider: 'codex', x: [.2, 1.2], y: .7}, {provider: 'codex', x: [.2], y: .7},
    {provider: 'codex', x: [.2, .5]}, {provider: 'codex', x: [.2, .5], y: 2}, {provider: 'codex', x: [.2, .5], y: .7, count: 1}, {provider: 'codex', x: [.2, .5], y: .7, count: 65},
    {provider: 'codex', x: [.2, .5], y: .7, count: 2.5}, {provider: 'codex', x: [.2, .5], y: .7, anchor: 'middle'}];
  for (const row of bad) assert.equal(normalizeLive({lamps: {rows: [...lampRows(), row]}}), null, JSON.stringify(row));
  for (const lamps of [null, 3, 'on', [], {}, {rows: []}, {rows: 'x'}, {rows: Array.from({length: 5}, () => lampRows()[0])}]) assert.equal(normalizeLive({lamps}), null, JSON.stringify(lamps));
  assert.notEqual(normalizeLive({lamps: {rows: Array.from({length: 4}, () => lampRows()[0])}}), null, 'four rows at most');
  assert.deepEqual(live.effectNames(cfg), ['lamps']);
  assert.deepEqual(live.effectNames(normalizeLive({...sample(), lamps: {rows: lampRows()}})).slice(-2), ['craft', 'lamps']);
});

test('lamps: the quota left is the provider\'s WEEK, from a reading the page renewed in the last 45 s whose week has not rolled over; anything else is unknown, never zero', () => {
  const now = Date.UTC(2026, 10, 9, 22, 0, 0), future = now / 1000 + 86400;
  const status = (codex, claude, extra = {}) => ({providers: {codex: {weekly: {remaining: codex, resets_at: future, ...extra}}, claude: {weekly: {remaining: claude, resets_at: future}, session: {remaining: 10, resets_at: future}}}});
  assert.deepEqual(live.lampReadings(status(68, 38), now, 1000), {codex: 68, claude: 38});
  assert.deepEqual(live.lampReadings(status(68, 38), now), {codex: 68, claude: 38}, 'no age given: fresh');
  assert.deepEqual(live.lampReadings(status(0, 100), now, 0), {codex: 0, claude: 100}, 'a real zero is a zero');
  assert.deepEqual(live.lampReadings(status(68, 38), now, 45001), {codex: null, claude: null}, 'a reading the page stopped renewing goes unknown');
  assert.deepEqual(live.lampReadings(status(68, 38), now, 45000), {codex: 68, claude: 38});
  assert.deepEqual(live.lampReadings(null, now, 0), {codex: null, claude: null});
  for (const junk of [undefined, 3, 'x', [], {}, {providers: null}, {providers: {}}, {providers: {codex: null, claude: {weekly: 5}}}]) assert.deepEqual(live.lampReadings(junk, now, 0), {codex: null, claude: null}, JSON.stringify(junk));
  for (const bad of [-1, 101, NaN, Infinity, '68', null, undefined, true]) assert.equal(live.lampReadings(status(bad, 50), now, 0).codex, null, `remaining ${String(bad)}`);
  assert.equal(live.lampReadings(status(68, 38, {resets_at: now / 1000 - 1}), now, 0).codex, null, 'a week that has rolled over is unknown');
  assert.equal(live.lampReadings(status(68, 38, {resets_at: undefined}), now, 0).codex, null, 'no reset time: unknown');
  const only = {providers: {codex: {weekly: {remaining: 50, resets_at: future}}}};
  assert.deepEqual(live.lampReadings(only, now, 0), {codex: 50, claude: null}, 'one provider missing does not blank the other');
});

test('lamps: the lit length follows the quota inside a lamp, any quota left shows a little light, zero shows none, unknown is null', () => {
  assert.equal(live.lampLit(26, 100), 26); close(live.lampLit(26, 50), 13); close(live.lampLit(26, 4), 1.04); close(live.lampLit(26, 68), 17.68);
  assert.equal(live.lampLit(26, 0), 0, 'nothing left, nothing lit');
  assert.equal(live.lampLit(26, 0.1), 0.4, 'a sliver left still shows a sliver of light');
  for (const bad of [null, undefined, NaN, -1, 100.5, '50']) assert.equal(live.lampLit(26, bad), null, String(bad));
  const lamps = normalizeLive({lamps: {rows: lampRows()}}).lamps, now = Date.now(), future = now / 1000 + 3600;
  const plan = live.lampPlan(lamps, {providers: {codex: {weekly: {remaining: 50, resets_at: future}}, claude: {weekly: {remaining: 100, resets_at: future}}}}, now, 100);
  assert.deepEqual(plan.map((r) => [r.provider, r.anchor, r.lit]), [['codex', 'start', 13], ['claude', 'end', 26]]);
  assert.deepEqual(live.lampPlan(lamps, null, now, 0).map((r) => r.lit), [null, null], 'no reading: both unknown');
  assert.deepEqual(live.lampPlan(null, null, now, 0), []); assert.deepEqual(live.lampPlan({}, null, now, 0), []);
});

test('the page and the server share their limits (the same numbers as token_tv/tablet_live.py)', () => {
  const py = fs.readFileSync(new URL('../token_tv/tablet_live.py', import.meta.url), 'utf8');
  assert.match(py, new RegExp(`MAX_LAMP_ROWS = ${live.LAMPS.maxRows}`)); assert.match(py, /LAMP_COUNT = \(2, 64\)/); assert.match(py, /LAMP_HEIGHT = \(0\.004, 0\.05, 0\.0125\)/); assert.match(py, /LAMP_AMOUNT = \(0, 2, 1\)/);
  assert.deepEqual(live.LAMPS.count, [2, 64]); assert.deepEqual(live.LAMPS.height, [0.004, 0.05, 0.0125]); assert.deepEqual(live.LAMPS.amount, [0, 2, 1]);
  assert.match(py, /'codex': \(1\.0, 0\.725, 0\.27\)/); assert.match(py, /'claude': \(0\.318, 0\.863, 1\.0\)/);
  for (const [effect, specs] of Object.entries(LIMITS)) for (const [key, [lo, hi, def]] of Object.entries(specs)) {
    const numbers = (n) => String(n).replace(/^0\./, '0\\.?0*\\.?');                // 0.25 may be written .25 or 0.25 in the source
    const row = new RegExp(`'${key}': \\(${numbers(lo)}, ${numbers(hi)}, ${numbers(def)}\\)`);
    assert.ok(row.test(py.replace(/(\W)\.(\d)/g, '$10.$2')), `${effect}.${key} ${lo}..${hi} (${def}) is not in tablet_live.py`);
  }
  assert.match(py, new RegExp(`MAX_REGIONS = ${live.MAX_REGIONS}`)); assert.match(py, new RegExp(`MAX_POINTS = ${live.MAX_POINTS}`)); assert.match(py, new RegExp(`MAX_CRAFT = ${live.MAX_CRAFT}`));
});

test('region masks: full weight inside, none outside, a feather that fades in from the edge, and the picture border keeps its weight', () => {
  const cfg = normalizeLive({water: {regions: [[0, .5, 1, 1]], feather: 0.1, amount: 0.2}, clouds: {regions: [[[.2, 0], [.8, 0], [.8, .4], [.2, .4]]]}, lights: {regions: [[.5, .5, 1, 1]]}});
  const r = rasterRegions(cfg, 2, 128);
  assert.deepEqual([r.w, r.h, r.data.length], [128, 64, 128 * 64 * 4]);
  assert.equal(regionWeightAt(r, 0, .5, .95), 1); assert.equal(regionWeightAt(r, 0, .5, .2), 0);
  assert.equal(regionWeightAt(r, 0, 0.001, .95), 1, 'at the picture border the weight does not fade');
  assert.ok(regionWeightAt(r, 0, .5, .5) < 0.2, 'right at the region edge the effect has not started');
  let last = 0;
  for (let y = .5; y <= .65; y += .01) { const w = regionWeightAt(r, 0, .5, y); assert.ok(w >= last - 1e-9, `monotone at ${y}`); last = w; }
  assert.ok(last > 0.95, 'and full weight a feather inside');
  assert.equal(regionWeightAt(r, 1, .5, .2), 1); assert.equal(regionWeightAt(r, 1, .05, .2), 0); assert.equal(regionWeightAt(r, 1, .5, .6), 0, 'clouds: the polygon, nothing below it');
  assert.equal(regionWeightAt(r, 3, .9, .9), 1); assert.equal(regionWeightAt(r, 3, .1, .1), 0, 'lights only where they are asked for');
  assert.equal(regionWeightAt(rasterRegions({water: normalizeLive({water: {regions: [[0, 0, .5, .5]]}}).water, lights: {amount: 1}}, 1.5, 64), 3, .9, .9), 255 / 255, 'lights without regions: everywhere');
  assert.equal(regionWeightAt(null, 0, .5, .5), 0); assert.equal(regionWeightAt(r, 0, NaN, .5), 0);
});

test('a triangle region is a triangle: its middle is inside, its far corner is not', () => {
  const cfg = normalizeLive({water: {regions: [[[0, 1], [1, 1], [.5, 0]]], feather: 0.002}});
  const r = rasterRegions(cfg, 1, 128);
  assert.equal(regionWeightAt(r, 0, .5, .8), 1); assert.equal(regionWeightAt(r, 0, .05, .2), 0); assert.equal(regionWeightAt(r, 0, .95, .2), 0); assert.equal(regionWeightAt(r, 0, .5, .1), 1);
});

test('the feather is never less than the farthest an effect moves the picture, so no pixel ever fetches across its region edge', () => {
  for (const [name, effect] of [['water', {amount: 2, feather: 0.002}], ['clouds', {amount: 2, feather: 0.002}], ['clouds', {amount: 1, feather: 0.1}]]) {
    const f = effectiveFeather(name, effect);
    assert.ok(f >= AMP[name] * effect.amount * 1.5, `${name} ${JSON.stringify(effect)}: ${f}`);
    assert.ok(f >= effect.feather);
  }
});

test('craft cross calmly: not before their delay, a straight journey, then a quiet spell until the next one', () => {
  const cfg = normalizeLive({craft: [{kind: 'ship', from: [-.1, .3], to: [1.1, .2], seconds: 60, every: 100, delay: 10, bob: 0}]});
  assert.equal(craftState(cfg.craft, 5, 2).length, 0, 'not yet');
  const at = (t) => craftState(cfg.craft, t, 2)[0];
  close(at(10.001).x, -.1, 1e-3); close(at(40).x, .5, 1e-9); close(at(40).y, .25, 1e-9); close(at(69.99).x, 1.1, 1e-3);
  assert.equal(craftState(cfg.craft, 80, 2).length, 0, 'the quiet spell between two crossings');
  close(craftState(cfg.craft, 110.001, 2)[0].x, -.1, 1e-3);                           // and again after `every`
  const s = at(40);
  close(s.heading, Math.atan2(-.1, 1.2 * 2), 1e-9);
  assert.ok(at(10.001).alpha < .05 && at(69.99).alpha < .05 && at(40).alpha === 1, 'it fades in and out at the ends');
  let last = null, step = 0;
  for (let t = 10.1; t < 69.9; t += .1) { const x = at(t).x; if (last !== null) step = Math.max(step, Math.abs(x - last)); last = x; }
  assert.ok(step < .003, `a craft moves at most ${step} of the picture width in a tenth of a second`);
  assert.deepEqual(craftState(cfg.craft, 40, 2), craftState(cfg.craft, 40, 2), 'deterministic');
  assert.equal(craftState(null, 3, 1).length, 0);
});

test('the touch bank: a few at once, the oldest makes way, a repeat in the same place is ignored, each ends by itself', () => {
  const bank = new PokeBank();
  assert.equal(bank.alive(0), false);
  assert.equal(bank.add(100, 100, 1, 'ripple'), true);
  assert.equal(bank.add(103, 102, 1.05, 'ripple'), false, 'a moment later, a few pixels away: the same touch');
  assert.equal(bank.add(300, 100, 1.05, 'glow'), true, 'but elsewhere is another');
  assert.equal(bank.add(100, 100, 1.5, 'ripple'), true, 'and the same place after a pause');
  assert.equal(bank.add(50, 50, 1.7, 'bump'), true);
  const list = bank.list(1.8);
  assert.equal(list.length, POKE.max, 'at most three alive: the oldest was dropped');
  assert.deepEqual(list.map((p) => p.kind), ['glow', 'ripple', 'bump']);
  assert.ok(list.every((p) => p.age >= 0 && p.age < 1) && close(list[2].age, .1, 1e-9) === undefined);
  assert.equal(bank.alive(1.8), true);
  assert.equal(bank.alive(1.7 + POKE.ripple + 1), false, 'every touch ends by itself');
  assert.equal(bank.list(1.7 + POKE.ripple + 1).length, 0);
  for (const bad of [[NaN, 1, 1], [1, Infinity, 1], [1, 1, NaN], [undefined, 1, 1]]) assert.equal(new PokeBank().add(...bad), false);
  bank.add(9, 9, 100, 'glow'); bank.clear(); assert.equal(bank.alive(100), false);
});

test('sparkles and sparks: bounded, born over time, fading, the same for the same touch', () => {
  const poke = {x: 200, y: 300, seed: 7};
  assert.equal(sparkles(poke, 0, []).length, 0, 'none at the very first moment');
  let most = 0;
  for (let age = 0; age < 2; age += .05) {
    const list = sparkles(poke, age, []);
    most = Math.max(most, list.length);
    for (const k of list) { assert.ok(k.alpha >= 0 && k.alpha <= 1 && k.size >= 3 && k.size <= 7.01); assert.ok(Math.hypot(k.x - poke.x, k.y - poke.y) < 110, 'they stay near the finger'); }
  }
  assert.ok(most >= 3 && most <= POKE.sparkles, `${most} sparkles at once`);
  assert.equal(sparkles(poke, 3, []).length, 0, 'gone after a second or two');
  assert.deepEqual(sparkles(poke, .4, []), sparkles({...poke}, .4, []));
  assert.notDeepEqual(sparkles(poke, .4, []), sparkles({...poke, seed: 8}, .4, []));
  const s = sparks(poke, .2, []);
  assert.ok(s.length > 0 && s.length <= POKE.sparks);
  assert.ok(s.every((k) => k.alpha > 0 && k.alpha <= 1 && k.heat > 0 && k.heat <= 1));
  assert.equal(sparks(poke, 1.5, []).length, 0);
  const early = sparks(poke, .05, [])[0], late = sparks(poke, .5, []).find((k) => k) || {alpha: 0};
  assert.ok(early.alpha > late.alpha, 'they cool and fade');
});

// ---- tiers: counts of small things, never per-pixel work --------------------------------------------------------------------------------

test('each tier pays for fewer small things than the one above, the lowest has no mesh, and no tier aims above 30 frames a second', () => {
  assert.equal(BUDGET.length, 4);
  for (let i = 1; i < BUDGET.length; i++) {
    for (const key of ['lights', 'glints', 'mist', 'rain', 'craft']) assert.ok(BUDGET[i][key] <= BUDGET[i - 1][key], `${key} at tier ${i}`);
    assert.ok(BUDGET[i].fps <= BUDGET[i - 1].fps);
  }
  assert.equal(BUDGET[3].cell, 0, 'low: no mesh');
  assert.ok(BUDGET.every((b) => b.fps <= 30 && b.fps >= 20), 'about 30 frames a second, 20 at the lowest');
  assert.ok(BUDGET[2].cell >= BUDGET[1].cell, 'a lighter tier never has a finer mesh');
  assert.ok(BUDGET[0].lights <= 4000 && BUDGET[0].rain <= 500 && BUDGET[0].glints <= 300 && BUDGET[0].mist <= 8, 'a few hundred sprites, not thousands of drawn things');
  assert.equal(budgetFor(99), BUDGET[3]); assert.equal(budgetFor(-4), BUDGET[0]); assert.equal(budgetFor(NaN), BUDGET[0]);
  assert.ok(Math.abs(intervalFor(0) - 1000 / 30) < 1e-9 && intervalFor(3) > intervalFor(2) && intervalFor(2) > intervalFor(1));
});

test('weights between texels are smooth: a vertex between two values gets something between them', () => {
  const raster = {w: 2, h: 1, data: new Uint8Array([0, 0, 0, 0, 255, 0, 0, 0])};
  close(weightBilinear(raster, 0, 0.25, 0.5), 0); close(weightBilinear(raster, 0, 0.75, 0.5), 1); close(weightBilinear(raster, 0, 0.5, 0.5), 0.5);
  assert.equal(weightBilinear(null, 0, .5, .5), 0); assert.equal(weightBilinear(raster, 0, NaN, .5), 0);
});

test('an effect covers a canvas rectangle, cut to the canvas and to the picture slot, or nothing', () => {
  const pic = {x: -300, y: 0, w: 1440, h: 720};
  const rect = effectRect([[0.0, 0.7, 1, 1]], pic, 800, 760);
  assert.deepEqual([rect.x0, rect.x1, rect.y1], [0, 800, 720], 'the water strip of a wide picture, cut at the canvas sides and bottom'); close(rect.y0, 504, 1e-6);
  const tri = effectRect([[[0.5, 0.2], [0.6, 0.2], [0.55, 0.4]]], pic, 800, 760);
  close(tri.x0, 420, 1e-6); close(tri.y0, 144, 1e-6); close(tri.x1, 564, 1e-6); close(tri.y1, 288, 1e-6);       // a polygon: its bounding box
  assert.equal(effectRect([[0, 0.9, 1, 1]], pic, 800, 600), null, 'below the slot: nothing to draw');
  assert.equal(effectRect([[0, 0, 0.001, 0.001]], pic, 800, 760), null, 'too small');
  assert.equal(effectRect([], pic, 800, 760), null);
});

test('a mesh is a regular grid of vertices with whole triangles, the weights asked for and a cap on its size', () => {
  const g = buildGrid({x0: 0, y0: 0, x1: 100, y1: 40}, 10, (x, y) => [x / 100, y / 40]);
  assert.deepEqual([g.nx, g.ny, g.vertices, g.count], [10, 4, 55, 240]);
  assert.equal(g.verts.length, 55 * 4); assert.equal(g.idx.length, 240);
  assert.ok(g.idx.every((i) => i < g.vertices), 'every index names a vertex');
  assert.deepEqual([...g.verts.slice(0, 4)], [0, 0, 0, 0]); assert.deepEqual([...g.verts.slice(-4)], [100, 40, 1, 1]);
  close(g.area, 4000);
  const big = buildGrid({x0: 0, y0: 0, x1: 5000, y1: 5000}, 4, () => [0, 0]);
  assert.ok(big.vertices <= 121 * 65 && big.vertices < 65536, 'capped: a mesh never needs more than 16 bits of index');
  const tiny = buildGrid({x0: 0, y0: 0, x1: 3, y1: 3}, 8, () => [0, 0]);
  assert.deepEqual([tiny.nx, tiny.ny], [1, 1]);
});

test('lights: local maxima of the detection, strongest first, only where they may twinkle and not under a mesh, never more than asked', () => {
  const w = 40, h = 20, buf = new Uint8Array(w * h * 4);
  const put = (x, y, v, spread = 0) => { for (let dy = -spread; dy <= spread; dy++) for (let dx = -spread; dx <= spread; dx++) buf[((y + dy) * w + x + dx) * 4] = Math.max(buf[((y + dy) * w + x + dx) * 4], v - 30 * (Math.abs(dx) + Math.abs(dy))); };
  put(5, 5, 250); put(20, 10, 180, 1); put(33, 15, 120); put(10, 16, 30);             // the last is too faint
  const found = extractLights(buf, w, h, {});
  assert.equal(found.length, 3 * 4, 'three lights');
  assert.deepEqual([found[0], found[1]].map((v) => Math.round(v * 1000) / 1000), [Math.round(5.5 / w * 1000) / 1000, Math.round(5.5 / h * 1000) / 1000], 'the strongest first, at its place');
  assert.ok(found[2 + 4] > found[2], 'the bigger light has the bigger footprint');
  assert.equal(extractLights(buf, w, h, {max: 2}).length, 8, 'at most as many as asked');
  assert.ok(found.every((v) => Number.isFinite(v)));
  // regions: lights only where the A channel of the region raster allows; none where the water or the sky mesh moves the picture
  const cfg = normalizeLive({lights: {regions: [[0, 0, 0.7, 1]]}, water: {regions: [[0.7, 0, 1, 1]]}});
  const raster = rasterRegions(cfg, w / h, 64);
  const kept = extractLights(buf, w, h, {raster});
  assert.equal(kept.length, 2 * 4, 'the lights in the lights region, and not the one in the water');
  assert.equal(extractLights(new Uint8Array(w * h * 4), w, h, {}).length, 0);
});

test('glints, rain and mist are placed where they belong, the same way every time', () => {
  const raster = rasterRegions(normalizeLive({water: {regions: [[0, 0.6, 1, 1]]}, mist: {regions: [[0, 0.3, 1, 0.5]]}}), 1.5, 96);
  const glints = placeGlints(raster, 120, 7);
  assert.equal(glints.length % 4, 0); assert.ok(glints.length / 4 >= 100 && glints.length / 4 <= 120);
  for (let i = 0; i < glints.length; i += 4) { assert.ok(regionWeightAt(raster, 0, glints[i], glints[i + 1]) > 0.5, 'on the water'); assert.ok(glints[i + 2] >= 0.0045 && glints[i + 2] <= 0.0115 && glints[i + 3] >= 0 && glints[i + 3] < 1); }
  assert.deepEqual([...placeGlints(raster, 20, 7)], [...placeGlints(raster, 20, 7)]); assert.notDeepEqual([...placeGlints(raster, 20, 7)], [...placeGlints(raster, 20, 8)]);
  assert.equal(placeGlints(rasterRegions(normalizeLive({lights: {}}), 1, 32), 50, 1).length, 0, 'no water, no glints');
  const rain = placeRain(100, 3);
  assert.equal(rain.length, 100 * 2 * 5);
  for (let i = 0; i < 100; i++) { const a = rain.slice(i * 10, i * 10 + 5), b = rain.slice(i * 10 + 5, i * 10 + 10); assert.deepEqual([...a.slice(0, 4)], [...b.slice(0, 4)], 'both ends of a drop agree'); assert.deepEqual([a[4], b[4]], [0, 1]); assert.ok(a[2] >= 380 && a[2] <= 1080 && a[3] >= 14 && a[3] <= 48); }
  const mist = placeMist(raster, 6, 5);
  assert.ok(mist.count >= 1 && mist.count <= 6 && mist.data.length === mist.count * 4 * 6);
  for (let i = 0; i < mist.count; i++) { const k = i * 24; assert.ok(regionWeightAt(raster, 2, mist.data[k + 2], mist.data[k + 3]) > 0.5, 'inside the mist region'); assert.ok(mist.data[k + 4] >= 0.07 && mist.data[k + 4] <= 0.15); }
  assert.equal(placeMist(raster, 0, 5).count, 0);
});

test('the cost estimate adds up what a frame reads: the picture once, the meshes once more, the sprites, never the blended things', () => {
  const c = estimateCost({pixels: 1000000, waterPx: 200000, cloudsPx: 300000, lightsPx: 40000, glintsPx: 10000, craftPx: 5000, mistPx: 400000, rainPx: 20000, draws: 7, vertices: 9000});
  assert.equal(c.reads, 1555000); assert.equal(c.readsPerPixel, 1.56); assert.equal(c.meshPixels, 500000); assert.equal(c.spritePixels, 55000); assert.equal(c.draws, 7);
  assert.equal(c.blendedPixels, 430000);
  assert.equal(estimateCost({}).readsPerPixel, 0);
  assert.equal(estimateCost({pixels: 100}).readsPerPixel, 1, 'a frame that is only the picture reads each pixel once');
});

// ---- the shaders, as text -------------------------------------------------------------------------------------------------------------

const lib = 'float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }';
const pairs = () => {
  const out = [];
  for (const video of [false, true]) {
    for (const grade of video ? [false, true] : [false]) {
      for (const kind of ['water', 'clouds']) out.push([`mesh ${kind} ${video} ${grade}`, live.meshVS(kind, video), live.meshFS(lib, video, grade)]);
      out.push([`lights ${video} ${grade}`, live.lightsVS(video), live.lightsFS(lib, video, grade)], [`glints ${video} ${grade}`, live.glintsVS(video), live.glintsFS(lib, video, grade)]);
      out.push([`base ${video} ${grade}`, video ? live.baseVideoVS : live.BASE_VS, video ? live.baseVideoFS(lib, grade) : live.BASE_FS]);
    }
  }
  out.push(['mist', live.MIST_VS, live.MIST_FS], ['rain', live.RAIN_VS, live.RAIN_FS], ['glow', live.QUAD_VS, live.GLOW_FS], ['ring', live.RING_VS, live.RING_FS], ['points', live.POINT_VS, live.POINT_FS],
    ['lamps', live.CRAFT_VS, live.lampsFragment()]);
  return out;
};

test('every shader has a main, balanced braces, and its fragment shader reads only the varyings its vertex shader writes', () => {
  for (const [name, vs, fs] of pairs()) {
    for (const src of [vs, fs]) {
      assert.equal((src.match(/void main\(\) \{/g) || []).length, 1, name);
      assert.equal(src.split('{').length, src.split('}').length, 'braces balance: ' + name);
      assert.equal(src.split('(').length, src.split(')').length, 'parentheses balance: ' + name);
      assert.ok(!/\bwhile\b|\bdo\s*\{|\bdiscard\b/.test(src), name);
      assert.ok(!/pow\(/.test(src), `${name}: pow of a negative number is undefined in GLSL ES, the shaders square by hand`);
    }
    const varyings = (src) => new Set([...src.matchAll(/varying\s+\w+\s+([^;]+);/g)].flatMap((m) => m[1].split(',').map((n) => n.trim())));
    const written = varyings(vs), read = varyings(fs);
    for (const v of read) assert.ok(written.has(v), `${name}: the fragment shader reads ${v}, the vertex shader does not write it`);
    assert.match(vs, /attribute \w+ aPos;/, `${name}: attribute 0 is aPos`);
  }
});

test('the per-pixel work of the live frame is a read or two: no loops anywhere, at most one read in the picture and mesh shaders, a few in a sprite', () => {
  for (const [name, , fs] of pairs()) {
    assert.ok(!/\bfor\s*\(/.test(fs), `${name}: no loop in a fragment shader`);
    const reads = (fs.match(/texture2D\(/g) || []).length;
    if (/^(base|mesh)/.test(name)) assert.ok(reads <= 1, `${name}: one read per pixel, ${reads}`);
    if (/^(mist|rain|glow|ring|points|lamps)/.test(name)) assert.equal(reads, 0, `${name}: no read at all`);
    if (/^(lights|glints)/.test(name)) assert.ok(reads <= 3, `${name}: a sprite reads at most three times (itself and its two neighbours)`);
  }
  for (const kind of ['ship', 'drone', 'gull', 'swallow']) {
    const src = live.craftFragment(kind, lib);
    assert.ok(!/\bfor\s*\(/.test(src), `${kind}: no loop in a fragment shader, not even a small one`);
    assert.equal(src.split('{').length, src.split('}').length, kind);
    assert.equal((src.match(/texture2D\(/g) || []).length, 0, `${kind}: a craft reads nothing`);
  }
  assert.equal((live.craftFragment('gull', lib).match(/uB\.w > \d\.5/g) || []).length, 6, 'six guarded blocks, one per possible gull');
});

test('every uniform the renderer sets is declared in a shader of this file, and every smoothstep has ascending edges', () => {
  const text = fs.readFileSync(new URL('../token_tv/tablet_web/stage-live.js', import.meta.url), 'utf8');
  const declared = new Set();
  for (const m of text.matchAll(/uniform\s+(?:float|vec2|vec3|vec4|sampler2D)\s+([^;']+);/g)) for (const n of m[1].split(',')) declared.add(n.trim().replace(/\[.*\]$/, ''));
  const used = [...text.matchAll(/\.(?:f1|f2|f3|f4|fv4|i1)\('(u[A-Za-z0-9]+)'/g)].map((m) => m[1]);
  assert.ok(used.length > 40);
  for (const u of used) assert.ok(declared.has(u), `${u} is set but not declared`);
  for (const m of text.matchAll(/smoothstep\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,/g)) assert.ok(Number(m[1]) < Number(m[2]), `smoothstep(${m[1]}, ${m[2]}) is reversed`);
});

test('stage-live.js is served by name, uses no eval, network, storage or inline markup', () => {
  assert.match('stage-live.js', /^[a-z0-9-]{1,40}\.(js|css)$/);
  const text = fs.readFileSync(new URL('../token_tv/tablet_web/stage-live.js', import.meta.url), 'utf8');
  const code = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  for (const word of [/\beval\s*\(/, /new\s+Function/, /\.innerHTML/, /\.outerHTML/, /insertAdjacentHTML/, /document\.write/, /\bfetch\s*\(/, /XMLHttpRequest/, /WebSocket/, /https?:\/\//, /\bimport\s*\(/, /importScripts/, /localStorage/, /createObjectURL/])
    assert.ok(!word.test(code), `stage-live.js uses ${word}`);
});
