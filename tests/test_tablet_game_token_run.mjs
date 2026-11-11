import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

// TOKEN RUN (token_tv/tablet_web/game-token-run.js): the pure logic (layout anchors, road geometry and projection, hills, traffic, scenery, the day schedule, the palette, the atlas
// reader) and, with a fake canvas, the whole drawing path: the picture has no holes, a missing atlas is calm, the frame stays cheap. Everything uses the seeded random.
const require = createRequire(import.meta.url);
const engine = require('../token_tv/tablet_web/stage-game.js');
const run = require('../token_tv/tablet_web/game-token-run.js');
const {W, H, HORIZON, CX, SEG, ROAD, LANE, CAM_H, FX, ZP, DRAW, KINDS, ANCHOR, anchorsFor, geometry, easeAnchors, DEFAULT_GEO} = run;
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} is not ${b}`);

// A Date-like object for a civil time in a fixed zone (Madrid: UTC+1 in winter, UTC+2 in summer), so the tests do not depend on this computer's time zone.
const madrid = (y, m, d, hh, mm = 0, offset = -60) => ({
  getFullYear: () => y, getMonth: () => m - 1, getDate: () => d, getHours: () => hh, getMinutes: () => mm, getSeconds: () => 0, getMilliseconds: () => 0, getTimezoneOffset: () => offset,
});
const NOV9 = (hh, mm = 0) => madrid(2026, 11, 9, hh, mm);
const JUN21 = (hh, mm = 0) => madrid(2026, 6, 21, hh, mm, -120);

/* ---- the layout follows the visible rows ------------------------------------------------------------------------------------------------ */

test('registered as token-run in the engine, with the native portrait size', () => {
  assert.ok(engine.registry['token-run'], 'the scene registers itself');
  assert.deepEqual(engine.registry['token-run'].size, [200, 320]);
  assert.equal(typeof engine.registry['token-run'].draw, 'function');
});

test('anchors: with the dock up the horizon is a third of the visible rows and the car sits just above the clock; with the whole picture the car is at the bottom', () => {
  const dock = anchorsFor(186);                                   // the tablet's dock covers about 42 %: rows 0-185 stay visible
  assert.equal(dock.horizon, 62, 'a third of the 186 visible rows');
  assert.ok(dock.carRow <= 186 - 24 && dock.carRow >= 186 - 46, `the car's tyres at row ${dock.carRow} are above the page's date and clock`);
  const picture = anchorsFor(320);
  assert.equal(picture.horizon, Math.round(320 / 3));
  assert.equal(picture.carRow, 320 - 84, 'the car is above the picture-mode clock and usage lines');
  assert.ok(picture.carRow > dock.carRow && picture.horizon > dock.horizon, 'the picture mode is lower on both');
});

test('anchors: for every visible bottom the horizon is above the car, the car is inside the visible rows and the mapping is monotonic', () => {
  let last = null;
  for (let vb = ANCHOR.minBottom; vb <= H; vb++) {
    const a = anchorsFor(vb);
    assert.ok(a.horizon + 24 <= a.carRow, `${vb}: the road has rows above the car`);
    assert.ok(a.carRow <= vb - 24, `${vb}: the car (${a.carRow}) is visible with its body above the bottom row`);
    assert.ok(a.horizon >= vb / 3 - 1 && a.horizon <= vb / 3 + 1, `${vb}: the horizon stays about a third down`);
    if (last) assert.ok(a.horizon >= last.horizon && a.carRow >= last.carRow, `${vb}: never goes back up as the visible area grows`);
    last = a;
  }
  assert.deepEqual(anchorsFor(NaN), anchorsFor(H), 'an unknown value means the whole picture');
  assert.deepEqual(anchorsFor(5), anchorsFor(ANCHOR.minBottom), 'a tiny area is clamped, never a degenerate layout');
  assert.deepEqual(anchorsFor(99999), anchorsFor(H));
});

test('geometry: the car\'s tyres touch their row at depth ZP and the focal length follows from the two rows', () => {
  for (const vb of [120, 186, 240, 320]) {
    const a = anchorsFor(vb), g = geometry(a.horizon, a.carRow);
    close(g.horizon + CAM_H * g.fy / ZP, g.carRow, 1e-9);
    assert.ok(g.fy > 0 && g.contrast > 0 && g.zCut > 0 && g.zCut < ZP);
  }
  assert.deepEqual(DEFAULT_GEO, geometry(HORIZON, run.CAR_ROW));
  assert.ok(geometry(50, 20).carRow >= 50 + 24, 'a car above its horizon is lifted below it');
});

test('anchors ease to a new target in about a dozen steps, in whole rows, without overshoot, and land exactly on it', () => {
  for (const [from, to] of [[320, 186], [186, 320], [186, 250]]) {
    let a = anchorsFor(from);
    const target = anchorsFor(to), path = [a];
    for (let i = 0; i < 40 && (a.horizon !== target.horizon || a.carRow !== target.carRow); i++) { a = easeAnchors(a, target); path.push(a); }
    assert.deepEqual(a, target, `${from} -> ${to} lands on the target`);
    assert.ok(path.length - 1 <= 16, `${from} -> ${to} took ${path.length - 1} steps`);
    for (let i = 1; i < path.length; i++) {
      for (const key of ['horizon', 'carRow']) {
        const before = Math.abs(target[key] - path[i - 1][key]), after = Math.abs(target[key] - path[i][key]);
        assert.ok(after <= before, `${key} never moves away from the target`);
        assert.ok(Math.abs(path[i][key] - path[i - 1][key]) <= 18 + 1e-9, 'at most 18 rows in a step');
        assert.equal(path[i][key], Math.round(path[i][key]), 'whole rows');
      }
    }
  }
  const same = anchorsFor(186);
  assert.deepEqual(easeAnchors(same, same), same, 'nothing moves when nothing changes');
});

/* ---- the track and the projection -------------------------------------------------------------------------------------------------------- */

test('the track repeats the same for a seed, closes on itself and begins and ends straight', () => {
  const a = run.buildTrack(run.seeded(7)), b = run.buildTrack(run.seeded(7)), c = run.buildTrack(run.seeded(8));
  assert.deepEqual(Array.from(a.curve), Array.from(b.curve));
  assert.deepEqual(Array.from(a.height), Array.from(b.height));
  assert.notDeepEqual(Array.from(a.curve), Array.from(c.curve));
  assert.equal(a.height.length, a.count + 1);
  close(a.height[a.count], a.height[0], 1e-3);
  for (let i = 0; i < 70; i++) { assert.equal(a.curve[i], 0); assert.equal(a.curve[a.count - 1 - i], 0); }
  assert.ok(Math.max(...a.curve) <= 1 && Math.min(...a.curve) >= -1, 'gentle bends');
  let steepest = 0;
  for (let i = 0; i < a.count; i++) steepest = Math.max(steepest, Math.abs(a.height[i + 1] - a.height[i]) / SEG);
  assert.ok(steepest < 0.16, `the steepest grade is ${(steepest * 100).toFixed(1)} %`);
  assert.ok(a.curve.some((v) => v > 0.2) && a.curve.some((v) => v < -0.2), 'bends to both sides');
});

const flatTrack = (curve = 0) => ({ count: 400, length: 400 * SEG, curve: new Float32Array(400).fill(curve), height: new Float32Array(401) });

test('projection: the road tiles the rows from the nearest to the horizon with no gap, narrowing with distance', () => {
  const out = run.makeProjection();
  run.projectRoad(flatTrack(), 5000, 0, CAM_H, out, DEFAULT_GEO);
  let covered = H;
  for (let k = 0; k < DRAW; k++) {
    if (out.bot[k] <= out.top[k]) continue;
    assert.equal(out.bot[k], covered, `segment ${k} starts where the nearer ones ended`);
    covered = out.top[k];
  }
  assert.ok(covered <= HORIZON + 6 && covered >= HORIZON - 1, `the road reaches row ${covered}, almost the horizon`);
  for (let k = 1; k < DRAW; k++) { assert.ok(out.hn[k] <= out.hn[k - 1] + 1e-6 && out.zn[k] > out.zn[k - 1]); assert.ok(out.y1[k] <= out.y1[k - 1] + 1e-6); }
  const road = run.sampleRoad(out, ZP);
  close(road.y, DEFAULT_GEO.carRow, 0.8);
  close(road.half, ROAD * FX / ZP, 1e-6);
  close(road.x, CX, 0.001);
  assert.ok(road.half * 2 / 3 > 52, 'a lane is wider than the 46 px car');
  assert.equal(run.sampleRoad(out, DRAW * SEG + 500), null);
});

test('projection: a bend to the right sends the far road to the right, a bend to the left to the left, a straight keeps it in the middle', () => {
  const far = (curve) => { const out = run.makeProjection(); run.projectRoad(flatTrack(curve), 0, 0, CAM_H, out, DEFAULT_GEO); return out.xf[DRAW - 1]; };
  assert.ok(far(0.5) > CX + 10);
  assert.ok(far(-0.5) < CX - 10);
  close(far(0), CX, 1e-3);
});

test('projection: the layout changes where the road sits but not how wide it is at the car', () => {
  for (const vb of [186, 250, 320]) {
    const a = anchorsFor(vb), geo = geometry(a.horizon, a.carRow), out = run.makeProjection();
    run.projectRoad(flatTrack(), 5000, 0, CAM_H, out, geo);
    const road = run.sampleRoad(out, ZP);
    close(road.y, a.carRow, 1, `${vb}`);
    close(road.half, ROAD * FX / ZP, 1e-6);
    assert.ok(out.top0 <= a.horizon + 8, `${vb}: the road reaches the horizon`);
  }
});

test('projection: a crest hides the road behind it, and the road behind rises into view again past the dip', () => {
  const track = flatTrack();
  for (let i = 0; i <= 400; i++) track.height[i] = 700 * Math.exp(-(((i - 30) / 8) ** 2));            // a hill 3000 units ahead of the camera at 0
  const out = run.makeProjection();
  run.projectRoad(track, 0, 0, CAM_H, out, DEFAULT_GEO);
  const hidden = [];
  for (let k = 0; k < DRAW; k++) if (out.bot[k] <= out.top[k]) hidden.push(k);
  assert.ok(hidden.length > 20, 'segments behind a crest are not drawn');
  let monotonic = true, lastTop = H;
  for (let k = 0; k < DRAW; k++) if (out.bot[k] > out.top[k]) { if (out.top[k] > lastTop) monotonic = false; lastTop = out.top[k]; }
  assert.ok(monotonic, 'what is drawn never goes back down the screen');
  const behind = run.sampleRoad(out, 4800);
  assert.ok(behind.hidden, 'a point just behind the crest is below the clip');
});

test('projection: something fixed in the world moves toward the viewer and down the screen as the camera advances', () => {
  const rows = [];
  for (const camZ of [0, 100, 200, 300]) {
    const out = run.makeProjection();
    run.projectRoad(flatTrack(), camZ, 0, CAM_H, out, DEFAULT_GEO);
    rows.push(run.sampleRoad(out, 3000 - camZ).y);                                          // a point at world z = 3000
  }
  for (let i = 1; i < rows.length; i++) assert.ok(rows[i] > rows[i - 1], 'it comes down the screen');
});

/* ---- scenery ----------------------------------------------------------------------------------------------------------------------------- */

test('scenery: seeded, only known kinds, beach things on the left, the land side on the right, boats out in the sea, never on the road', () => {
  const track = run.buildTrack(run.seeded(3)), a = run.buildScenery(run.seeded(4), track), b = run.buildScenery(run.seeded(4), track);
  assert.deepEqual(JSON.stringify(a), JSON.stringify(b));
  const counts = {};
  a.forEach((list, seg) => {
    for (const o of list || []) {
      counts[o.kind] = (counts[o.kind] || 0) + 1;
      assert.ok(KINDS[o.kind] > 0, o.kind);
      if (o.kind === 'bridge') { assert.equal(o.off, 0); continue; }
      assert.ok(Math.abs(o.off) > ROAD, `${o.kind} at ${o.off} is off the tarmac`);
      if (o.kind === 'boat' || o.kind === 'windsurf') assert.ok(o.off < -(ROAD + run.beachAt(seg)), `${o.kind} floats in the sea, not on the sand`);
      if (o.kind === 'parasol') assert.ok(o.off < 0, `${o.kind} stands on the beach`);
      if (o.kind.startsWith('house') || o.kind === 'block' || o.kind === 'billboard' || o.kind === 'lamp') assert.ok(o.off > 0, `${o.kind} stands on the land side`);
    }
  });
  for (const kind of ['palm0', 'palm1', 'pine', 'bush', 'rock0', 'post', 'sign0', 'house0', 'boat', 'bridge', 'lamp']) assert.ok(counts[kind] > 0, `some ${kind}`);
  assert.ok(counts.bridge >= 3 && counts.bridge <= 8, `${counts.bridge} overpasses on the whole track: now and then`);
  assert.ok(counts.palm0 + counts.palm1 > counts.house0 / 2, 'palms are a main part of the coast');
});

/* ---- the world: the car, the autopilot and the traffic ----------------------------------------------------------------------------------- */

const world = (seed = 20261109, hour = 14) => run.createWorld({seed, clock: () => NOV9(hour)});
const relZ = (w, r) => run.wrapZ(r.z - (w.camZ + ZP), w.track.length);

test('the world is deterministic: the same seed gives the same road, rivals and drive, another seed a different one', () => {
  const snapshot = (w) => JSON.stringify([w.camZ, w.speed, w.player, w.rivals, w.clouds, w.gulls.map((g) => [g.x, g.y, g.phase])]);
  const a = world(), b = world(), c = world(99);
  for (let i = 0; i < 3000; i++) { a.step(); b.step(); c.step(); }
  assert.equal(snapshot(a), snapshot(b));
  assert.notEqual(snapshot(a), snapshot(c));
});

test('the car drives quickly, changes lanes and passes traffic without being overtaken or colliding', () => {
  const w = world();
  let passedByRival = 0, passedRival = 0, fastest = 0, slowest = 1e9, speedTotal = 0, widest = 0;
  const before = new Map(w.rivals.map((r) => [r, relZ(w, r) > 0]));
  for (let i = 0; i < 60000; i++) {                                                    // about half an hour
    w.step();
    fastest = Math.max(fastest, w.speed); slowest = Math.min(slowest, w.speed); speedTotal += w.speed; widest = Math.max(widest, Math.abs(w.player.x));
    for (const r of w.rivals) {
      const d = relZ(w, r);
      assert.ok(!(Math.abs(d) < 520 && Math.abs(r.x - w.player.x) < 430), `step ${i}: the car and a rival overlap (dz ${Math.round(d)}, dx ${Math.round(r.x - w.player.x)})`);
      const ahead = d > 0;
      if (before.get(r) !== ahead && Math.abs(d) < 4000) { if (ahead) passedByRival++; else passedRival++; }
      before.set(r, ahead);
    }
  }
  assert.equal(passedByRival, 0, `${passedByRival} cars passed us`);
  assert.ok(passedRival >= 3, `${passedRival} cars were passed by us`);
  assert.ok(fastest > 6750 && fastest < 8700 && slowest > 4050 && speedTotal / 60000 > 5175,
    `the faster drive keeps moving: ${Math.round(slowest)}-${Math.round(fastest)}, average ${Math.round(speedTotal / 60000)} units/s`);
  assert.ok(widest <= LANE + 60, 'the car never leaves its three lanes');
  assert.ok(w.player.changes >= 8, `the car changed lane ${w.player.changes} times: it drives, it does not sit`);
});

test('different traffic patterns do not trap the faster car or cause a collision', () => {
  for (const seed of [5, 99, 1234]) {
    const w = world(seed);
    let speedTotal = 0;
    for (let i = 0; i < 20000; i++) {
      w.step();
      speedTotal += w.speed;
      for (const rival of w.rivals) {
        const dz = relZ(w, rival), dx = rival.x - w.player.x;
        assert.ok(!(Math.abs(dz) < 520 && Math.abs(dx) < 430), `seed ${seed}, step ${i}: the cars overlap`);
      }
    }
    assert.ok(speedTotal / 20000 > 4950, `seed ${seed}: average speed fell to ${Math.round(speedTotal / 20000)}`);
    assert.ok(w.player.changes >= 3, `seed ${seed}: the car did not pass enough traffic`);
  }
});

test('a car alongside falls back so our car keeps overtaking even during a long drive', () => {
  // These seeds previously left a neighbour beside us and a leader ahead,
  // both matching our speed, for more than fourteen real-time minutes.
  for (const seed of [5, 711]) {
    const w = world(seed);
    const previous = new Map(w.rivals.map((r) => [r, relZ(w, r) > 0]));
    const nearby = new Map(w.rivals.map((r) => [r, 0]));
    let longest = 0, passed = 0, overtookUs = 0;
    for (let i = 0; i < 15 * 60 * 30; i++) {
      w.step();
      for (const r of w.rivals) {
        const d = relZ(w, r), ahead = d > 0;
        if (previous.get(r) !== ahead && Math.abs(d) < 4000) ahead ? overtookUs++ : passed++;
        previous.set(r, ahead);
        const duration = d > 0 && d < 6000 ? nearby.get(r) + 1 : 0;
        nearby.set(r, duration);
        longest = Math.max(longest, duration);
        assert.ok(!(Math.abs(d) < 520 && Math.abs(r.x - w.player.x) < 430), `seed ${seed}: vehicles overlap`);
      }
    }
    assert.equal(overtookUs, 0, `seed ${seed}: another car passed us`);
    assert.ok(passed >= 20, `seed ${seed}: only ${passed} cars passed in fifteen minutes`);
    assert.ok(longest < 45 * 30, `seed ${seed}: one car lingered ahead for ${Math.round(longest / 30)} seconds`);
  }
});

test('the traffic stays spread out: rivals of one lane keep their distance and every rival comes back around, none is lost far away', () => {
  const w = world(5);
  for (let i = 0; i < 40000; i++) {
    w.step();
    if (i % 50) continue;
    for (const lane of [0, 1, 2]) {
      const zs = w.rivals.filter((r) => r.lane === lane).map((r) => r.z).sort((p, q) => p - q);
      for (let k = 1; k < zs.length; k++) assert.ok(zs[k] - zs[k - 1] > 2500 || w.track.length - (zs[zs.length - 1] - zs[0]) > 2500, `lane ${lane} bunches up at step ${i}`);
    }
    for (const r of w.rivals) { const d = relZ(w, r); assert.ok(d > -16000 && d < DRAW * SEG + 9500, `a rival is ${Math.round(d)} away at step ${i}`); }
  }
});

test('lean follows the sideways motion in whole poses and never flickers', () => {
  const w = world();
  let flips = 0, last = w.player.lean;
  for (let i = 0; i < 20000; i++) { w.step(); assert.ok([-2, -1, 0, 1, 2].includes(w.player.lean)); if (w.player.lean !== last) { flips++; last = w.player.lean; } }
  assert.ok(flips > 4 && flips < 2000, `${flips} changes of pose`);
});

test('a touch below the horizon honks and hops (whole-pixel bounces), a touch in the sky sends up a gull', () => {
  const w = world();
  assert.equal(w.poke(100, 250), 'honk');
  assert.equal(w.player.hop, run.HOP.length);
  assert.ok(w.player.honk > 0);
  assert.ok(run.HOP.every(Number.isInteger) && run.HOP.every((v) => v <= 0) && run.HOP[0] === 0 && run.HOP[run.HOP.length - 1] === 0, 'a hop starts and ends on the road, in whole pixels');
  for (let i = 0; i < 40; i++) w.step();
  assert.equal(w.player.hop, 0);
  const gulls = w.gulls.length;
  assert.equal(w.poke(150, 30), 'gull');
  assert.equal(w.gulls.length, gulls + 1);
  assert.equal(w.poke(100, 30, 20), 'honk', 'the horizon decides which is which');
  for (let i = 0; i < 20; i++) w.poke(150, 30);
  assert.ok(w.gulls.length <= 7, 'at most a handful of gulls');
  for (let i = 0; i < 1500; i++) w.step();
  assert.ok(w.gulls.length <= 4, 'a gull that was sent off leaves and is gone');
});

test('clouds and gulls move a whole pixel at a time', () => {
  const w = world();
  const before = w.clouds.map((c) => c.x);
  for (let i = 0; i < 400; i++) {
    const last = w.clouds.map((c) => c.x);
    w.step();
    w.clouds.forEach((c, k) => { assert.ok(Number.isInteger(c.x)); assert.ok(Math.abs(c.x - last[k]) <= 1 || c.x < -50, 'at most a pixel a step'); });
  }
  assert.ok(w.clouds.some((c, k) => c.x !== before[k]), 'they drift');
});

/* ---- the day ----------------------------------------------------------------------------------------------------------------------------- */

test('the sun: Madrid\'s noon altitude in June and November, below the horizon at midnight, east in the morning and west in the evening', () => {
  const summer = run.sunState(JUN21(14, 15));            // solar noon in Madrid in summer is about 14:15 civil time
  assert.ok(summer.alt > 71 && summer.alt < 74.5, `${summer.alt}`);
  const winter = run.sunState(madrid(2026, 12, 21, 13, 15));
  assert.ok(winter.alt > 25 && winter.alt < 27.5, `${winter.alt}`);
  const november = run.sunState(NOV9(13, 15));
  assert.ok(november.alt > 27 && november.alt < 32, `${november.alt}`);
  assert.ok(run.sunState(NOV9(1, 0)).alt < -40 && run.sunState(JUN21(0, 30)).alt < -20);
  assert.equal(run.sunState(NOV9(10, 0)).morning, true);
  assert.equal(run.sunState(NOV9(16, 0)).morning, false);
  const sunset = [];
  for (let m = 16 * 60; m < 19 * 60; m += 5) { const s = run.sunState(NOV9(Math.floor(m / 60), m % 60)); if (s.alt < 0 && !sunset.length) sunset.push(m); }
  assert.ok(sunset[0] >= 17 * 60 + 35 && sunset[0] <= 18 * 60 + 5, `sunset on 9 November in Madrid at ${Math.floor(sunset[0] / 60)}:${sunset[0] % 60}`);
});

test('the day goes night, dusk, golden, day, golden, dusk, night with a big low sun at the ends, stars and lamps only in the dark', () => {
  const phases = [], brightAt = {};
  for (let h = 0; h < 24; h += 0.25) {
    const s = run.sunState(JUN21(Math.floor(h), (h % 1) * 60)), l = run.lightAt(s.alt), name = run.phaseName(s.alt);
    if (phases[phases.length - 1] !== name) phases.push(name);
    brightAt[h] = l.tint[0] + l.tint[1] + l.tint[2];
    if (name === 'day') assert.ok(l.stars === 0 && l.lamps === 0 && l.r <= 12, 'noon: no stars, no lamps, a small sun');
    if (name === 'night') assert.ok(l.stars >= 0.7 && l.lamps >= 0.9, 'night: stars and lamps');
    if (name === 'dusk') assert.ok(l.r >= 18, `dusk: a big sun (${l.r})`);
  }
  assert.deepEqual(phases, ['night', 'twilight', 'dusk', 'golden', 'day', 'golden', 'dusk', 'twilight', 'night']);
  const peak = Math.max(...Object.values(brightAt));
  assert.ok(Math.abs(brightAt[14.25] - peak) < 1e-9, 'solar noon (14:15 in Madrid in summer) has the brightest light');
  assert.ok(brightAt[6] < peak - 0.4 && brightAt[22] < peak - 0.4, 'dark at the ends of the day');
  for (const alt of [-30, -12, -5, 0, 3, 8, 20, 45, 80]) {
    const l = run.lightAt(alt);
    assert.equal(l.sky.length, 6);
    assert.ok(l.tint.every((v) => v > 0.2 && v <= 1.0001), 'never black, never brighter than daylight');
    assert.equal(l.alt, alt);
  }
});

test('the light changes smoothly: a minute never changes the picture much', () => {
  let last = run.lightAt(-20);
  for (let alt = -20; alt <= 60; alt += 0.1) {
    const l = run.lightAt(alt);
    for (let k = 0; k < 6; k++) for (let c = 0; c < 3; c++) assert.ok(Math.abs(l.sky[k][c] - last.sky[k][c]) <= 12, `sky band ${k} jumps at ${alt}`);
    for (let c = 0; c < 3; c++) assert.ok(Math.abs(l.tint[c] - last.tint[c]) < 0.03);
    last = l;
  }
});

test('the sun crosses the sky from the right in the morning to the left in the evening, always inside the picture, low and big at the horizon', () => {
  const morning = run.sunPlace(5, true), evening = run.sunPlace(5, false), noon = run.sunPlace(60, true);
  assert.ok(morning.x > CX && evening.x < CX && Math.abs(noon.x - CX) <= 20);
  assert.ok(noon.y < morning.y, 'higher at noon');
  for (const horizon of [62, 107]) for (let alt = -4; alt <= 60; alt += 2) for (const side of [true, false]) {
    const p = run.sunPlace(alt, side, horizon);
    assert.ok(p.x >= 20 && p.x <= W - 20 && p.y >= 20 && p.y <= horizon, `${alt} ${p.x},${p.y} for a horizon at ${horizon}`);
  }
  const moon = run.moonPlace(0), later = run.moonPlace(5);
  assert.ok(moon.x > later.x, 'the moon moves left');
});

/* ---- the palette ------------------------------------------------------------------------------------------------------------------------- */

test('the palette: daylight is the board\'s colours, night is darker, and distance flattens the stripes into haze', () => {
  const day = run.buildPalette(run.lightAt(40)), night = run.buildPalette(run.lightAt(-20));
  const sum = (c) => (c & 255) + ((c >> 8) & 255) + ((c >> 16) & 255);
  assert.equal(day.road[0], run.pack(run.rgb('#687184')));
  assert.equal(day.road[1], run.pack(run.rgb('#555d6d')));
  assert.ok(sum(night.road[0]) < sum(day.road[0]) * 0.6, 'night is dark');
  assert.ok(sum(night.sand[0]) < sum(day.sand[0]) * 0.6);
  for (const name of ['road', 'grass', 'sand', 'sea', 'kerb']) {
    assert.equal(day[name].length, run.LEVELS * 2);
    const contrast = (l) => Math.abs(sum(day[name][l * 2]) - sum(day[name][l * 2 + 1]));
    assert.ok(contrast(run.LEVELS - 1) <= contrast(0) / 1.5 + 2, `${name}: far stripes are flatter than near ones`);
  }
  const haze = run.lightAt(40).haze, distance = (c) => Math.abs((c & 255) - haze[0]) + Math.abs(((c >> 8) & 255) - haze[1]) + Math.abs(((c >> 16) & 255) - haze[2]);
  assert.ok(distance(day.grass[(run.LEVELS - 1) * 2]) < distance(day.grass[0]), 'far grass fades toward the haze');
  for (const table of ['road', 'grass', 'sea']) for (const c of day[table]) assert.equal(c >>> 24, 255, 'every colour is opaque');
  assert.equal(day.sky.length, 6);
});

/* ---- the atlas --------------------------------------------------------------------------------------------------------------------------- */

const LADDER_HEIGHTS = [6, 8, 10, 12, 15, 18, 22, 27, 33, 40, 49, 60, 74, 90, 110];
const RIVALS = ['blue', 'yellow', 'white', 'teal', 'orange', 'violet', 'green', 'black'];
function fictionalAtlas() {
  const frames = {}, anchors = {}, ladders = {};
  let count = 0;                                                                         // every frame gets its own x, so a drawImage call tells which frame it drew
  const add = (ladder, name, w, h, anchor) => { frames[name] = [count++, 4, w, h]; anchors[name] = anchor || [w >> 1, h - 1]; (ladders[ladder] = ladders[ladder] || []).push(name); };
  for (const kind of Object.keys(KINDS)) {
    if (kind === 'bridge') { for (const w of [24, 32, 42, 54, 70, 90, 116, 150, 190, 240]) add('bridge', `bridge-${String(w).padStart(3, '0')}`, w, Math.round(w * 0.44)); continue; }
    for (const h of LADDER_HEIGHTS) add(kind, `${kind}-${String(h).padStart(3, '0')}`, Math.max(3, Math.round(h * 0.8)), h);
  }
  for (const colour of RIVALS) for (const w of [5, 6, 8, 10, 12, 15, 18, 22, 27, 33, 40, 49]) add(`rival-${colour}`, `rival-${colour}-${String(w).padStart(2, '0')}`, w + 2, Math.round(w * 0.7) + 3);
  for (const w of [16, 24, 34, 48, 66, 90]) add('cloud', `cloud-${String(w).padStart(3, '0')}`, w + 4, Math.round(w * 0.34) + 3, [0, 0]);
  for (const kind of ['gull-s', 'gull-m']) for (let k = 0; k < 3; k++) add(kind, `${kind}-${k}`, 9, 4);
  for (let lean = 0; lean < 5; lean++) for (let phase = 0; phase < 4; phase++) add('car', `car-${lean}-${phase}`, 52, 28, [26, 25]);
  return {frames, anchors, ladders, version: 1};
}

test('the atlas reader: ladders sorted by height, anchors default to the foot, junk is ignored, the nearest rung is picked in ratio', () => {
  const lib = run.readAtlas(fictionalAtlas());
  const palm = lib.ladders.palm0;
  assert.equal(palm.length, LADDER_HEIGHTS.length);
  assert.deepEqual(palm.map((e) => e.h), LADDER_HEIGHTS);
  assert.deepEqual(lib.frame('car-2-0').ax, 26);
  const plain = run.readAtlas({frames: {a: [0, 0, 10, 20]}, ladders: {x: ['a', 'missing']}});
  assert.deepEqual([plain.ladders.x[0].ax, plain.ladders.x[0].ay], [5, 19]);
  assert.equal(plain.ladders.x.length, 1);
  for (const bad of [null, 5, {}, {frames: 4}, {frames: {a: [1, 2, 3]}, ladders: {x: ['a']}}]) {
    const read = run.readAtlas(bad);
    assert.ok(read === null || Object.keys(read.ladders).length === 0, JSON.stringify(bad));
  }
  assert.equal(run.pickRung(palm, 10.9).h, 10);
  assert.equal(run.pickRung(palm, 13.4).h, 12);
  assert.equal(run.pickRung(palm, 14).h, 15);
  assert.equal(run.pickRung(palm, 500).h, 110, 'the biggest rung for something huge');
  assert.equal(run.pickRung(palm, 2), null, 'too small to draw');
  assert.equal(run.pickRung(palm, 0), null);
  assert.equal(run.pickRung(undefined, 10), null);
  const rivals = lib.ladders['rival-blue'];
  assert.equal(run.pickRung(rivals, 20, 'nominal').nominal, 22, 'cars are picked by the width they were drawn for');
});

/* ---- drawing, with a fake canvas --------------------------------------------------------------------------------------------------------- */

test('headlights illuminate only the road ahead at night and fade away at both ends', () => {
  const base = run.pack([35, 48, 65]);
  const row = (distance, amount, left = 40, right = 160) => {
    const pixels = new Uint32Array(W * H).fill(base);
    run.headlightRow(pixels, 120, left, right, 100, 1 / (ZP + distance), amount);
    return pixels;
  };
  const sum = (p) => p.reduce((n, colour) => n + (colour & 255) - (base & 255), 0);
  const lit = row(2000, 1);
  assert.ok(sum(lit) > 0, 'a dark road is lit');
  assert.equal(sum(row(2000, 0)), 0, 'no lights in daylight');
  assert.equal(sum(row(-20, 1)), 0, 'not behind the car');
  assert.equal(sum(row(4001, 1)), 0, 'not beyond the beams');
  assert.ok(sum(row(20, 1)) < sum(lit), 'no hard edge by the car');
  assert.ok(sum(row(3980, 1)) < sum(lit), 'no hard edge in the distance');
  const clipped = row(2000, 1, 90, 110);
  for (let x = 0; x < W; x++) if (x < 90 || x >= 110) assert.equal(clipped[120 * W + x], base, 'never spills onto scenery');
});

globalThis.ImageData = globalThis.ImageData || class ImageData { constructor(w, h) { this.width = w; this.height = h; this.data = new Uint8ClampedArray(w * h * 4); } };
function fakeContext() {
  const calls = {drawImage: [], fillRect: 0, putImageData: 0, save: 0, restore: 0, other: 0};
  return {calls, canvas: {}, imageSmoothingEnabled: false, fillStyle: '', globalCompositeOperation: 'source-over',
    putImageData() { calls.putImageData++; }, drawImage(...args) { calls.drawImage.push(args); }, fillRect() { calls.fillRect++; }, save() { calls.save++; }, restore() { calls.restore++; }};
}
function makeScene(options = {}) {
  const scene = Object.create(engine.registry['token-run']);
  const api = {name: 'token-run', size: [200, 320], atlas: options.atlas === false ? null : {naturalWidth: 1024, naturalHeight: 600}, json: options.atlas === false ? null : (options.json || fictionalAtlas()),
    time: 0, tier: 'high', random: engine.seeded(0x5eed ^ 9 * 7919), view: {top: 0, bottom: options.bottom || 320}, readings: () => null};
  scene.init(api);
  return {scene, api};
}
const opaque = (buf) => { let holes = 0; for (let i = 0; i < buf.length; i++) if ((buf[i] >>> 24) !== 255) holes++; return holes; };

test('every pixel is painted: the picture has no holes at any hour, layout or point of the drive', () => {
  for (const bottom of [186, 320, 240]) for (const hour of [3, 7.5, 13, 18, 20.5]) {
    const clock = () => NOV9(Math.floor(hour), (hour % 1) * 60);
    const w = run.createWorld({clock});
    const scene = Object.create(engine.registry['token-run']);
    const api = {name: 'token-run', size: [200, 320], atlas: null, json: null, time: 0, tier: 'high', random: () => 0.5, view: {top: 0, bottom: bottom}, readings: () => null};
    scene.init(api);
    scene.s.world = w;
    const g = fakeContext();
    for (let i = 0; i < 1500; i++) { scene.step(api, 1 / 30); if (i % 300 === 0) { scene.draw(api, g); assert.equal(opaque(scene.s.buf), 0, `holes at ${hour} h, bottom ${bottom}, step ${i}`); } }
  }
});

test('without the atlas the scene still draws the road, sea and sky and a plain car, and never throws', () => {
  const {scene, api} = makeScene({atlas: false});
  const g = fakeContext();
  for (let i = 0; i < 300; i++) { scene.step(api, 1 / 30); scene.draw(api, g); }
  assert.equal(g.calls.putImageData, 300);
  assert.ok(g.calls.fillRect >= 300 * 5, 'a few rectangles make the car');
  assert.equal(g.calls.drawImage.length, 0);
  assert.equal(scene.s.lib, null);
  for (const json of [{}, {frames: {}}, {frames: {a: 1}}, {frames: {a: [1, 2, 3, 4]}, ladders: {palm0: ['a']}}]) {
    const broken = makeScene({json});
    const h = fakeContext();
    for (let i = 0; i < 60; i++) { broken.scene.step(broken.api, 1 / 30); broken.scene.draw(broken.api, h); }
  }
});

test('a frame stays cheap: one putImageData and a few dozen sprites, a few hundred canvas calls at the very most, even at night', () => {
  for (const hour of [13, 20.5]) {
    const w = run.createWorld({clock: () => NOV9(Math.floor(hour), (hour % 1) * 60)});
    const scene = Object.create(engine.registry['token-run']);
    const api = {name: 'token-run', size: [200, 320], atlas: {naturalWidth: 1024, naturalHeight: 600}, json: fictionalAtlas(), time: 0, tier: 'high', random: () => 0.5, view: {top: 0, bottom: 186}, readings: () => null};
    scene.init(api);
    scene.s.world = w;
    let worst = 0;
    for (let i = 0; i < 1800; i++) {
      scene.step(api, 1 / 30);
      if (i % 60) continue;
      const g = fakeContext();
      scene.draw(api, g);
      assert.equal(g.calls.putImageData, 1);
      worst = Math.max(worst, g.calls.drawImage.length + g.calls.fillRect);
    }
    assert.ok(worst > 8 && worst <= 170, `${worst} canvas calls in the worst frame at ${hour} h`);
  }
});

test('the car is drawn at the anchor row, and the picture slides to the new anchors after the dock is hidden, in whole rows', () => {
  const w = run.createWorld({clock: () => NOV9(14)});
  const scene = Object.create(engine.registry['token-run']);
  const json = fictionalAtlas();
  const api = {name: 'token-run', size: [200, 320], atlas: {naturalWidth: 1024, naturalHeight: 600}, json, time: 0, tier: 'high', random: () => 0.5, view: {top: 0, bottom: 320}, readings: () => null};
  scene.init(api);
  scene.s.world = w;
  const carFrames = new Set(Object.entries(json.frames).filter(([name]) => name.startsWith('car-')).map(([, f]) => f[0]));
  const carRows = () => {
    const g = fakeContext();
    scene.draw(api, g);
    const car = g.calls.drawImage.find((c) => carFrames.has(c[1]));
    return car[6] + 25;                                                                 // the sprite's destination row plus its anchor row: where the tyres touch
  };
  api.view = {top: 0, bottom: 186};                                                    // the page's first layout: no sliding before anything ran
  assert.equal(carRows(), anchorsFor(186).carRow, 'the very first picture is already in place');
  const rows = [];
  api.view = {top: 0, bottom: 320};                                                    // a tap on the clock hides the dock
  for (let i = 0; i < 30; i++) { scene.step(api, 1 / 30); rows.push(carRows()); }
  assert.ok(rows[0] > anchorsFor(186).carRow, 'it starts moving down at once');
  assert.ok(rows[0] < anchorsFor(320).carRow, 'and does not jump all the way');
  for (let i = 1; i < rows.length; i++) assert.ok(rows[i] >= rows[i - 1] && rows[i] - rows[i - 1] <= 18, 'a smooth slide in whole rows');
  assert.equal(rows[rows.length - 1], anchorsFor(320).carRow, 'and it lands on the new anchor');
  api.view = {top: 0, bottom: 186};
  for (let i = 0; i < 30; i++) scene.step(api, 1 / 30);
  assert.equal(carRows(), anchorsFor(186).carRow, 'and back');
});

test('sprites are drawn from far to near on a flat road, so a nearer thing always covers a farther one', () => {
  const w = run.createWorld({clock: () => NOV9(14)});
  w.track.height.fill(0); w.track.curve.fill(0);
  const scene = Object.create(engine.registry['token-run']);
  const json = fictionalAtlas();
  const api = {name: 'token-run', size: [200, 320], atlas: {naturalWidth: 1024, naturalHeight: 600}, json, time: 0, tier: 'high', random: () => 0.5, view: {top: 0, bottom: 320}, readings: () => null};
  scene.init(api);
  scene.s.world = w;
  for (let i = 0; i < 600; i++) scene.step(api, 1 / 30);
  const g = fakeContext();
  scene.draw(api, g);
  const feet = [], byX = new Map(Object.entries(json.frames).map(([name, f]) => [f[0], {name, ay: json.anchors[name][1]}]));
  for (const call of g.calls.drawImage) {
    const e = byX.get(call[1]);
    if (e && !/^(cloud|gull)/.test(e.name)) feet.push(call[6] + e.ay);
  }
  assert.ok(feet.length > 12, `${feet.length} sprites on the road`);
  let ok = 0;
  for (let i = 1; i < feet.length; i++) if (feet[i] >= feet[i - 1] - 1) ok++;
  assert.ok(ok >= (feet.length - 1) * 0.85, 'sprites are ordered from the horizon down (the ladder frames share sizes, so a one-row tolerance)');
});

test('an overpass rises out of the picture as the car drives under it, in every layout, and never comes down on the car', () => {
  for (const bottom of [186, 250, 320]) {
    const w = run.createWorld({clock: () => NOV9(14)});
    const scene = Object.create(engine.registry['token-run']);
    const json = fictionalAtlas();
    const api = {name: 'token-run', size: [200, 320], atlas: {naturalWidth: 1024, naturalHeight: 600}, json, time: 0, tier: 'high', random: () => 0.5, view: {top: 0, bottom}, readings: () => null};
    scene.init(api);
    scene.s.world = w;
    let bridgeZ = -1;
    w.scenery.forEach((list, seg) => { if (bridgeZ < 0 && (list || []).some((o) => o.kind === 'bridge')) bridgeZ = seg * SEG; });
    // Settle the layout one second before the approach: at higher cruise speeds
    // otherwise most of the bridge has already passed before observation starts.
    w.camZ = bridgeZ - 7800 - run.CRUISE;
    for (let i = 0; i < 30; i++) scene.step(api, 1 / 30);                              // the layout settles
    const frames = new Map(json.ladders.bridge.map((name) => [json.frames[name][0], json.frames[name]]));
    const carTop = anchorsFor(bottom).carRow - 28, tops = [];
    for (let i = 0; i < 240 && bridgeZ - w.camZ > 130; i++) {
      scene.step(api, 1 / 30);
      const g = fakeContext();
      scene.draw(api, g);
      const call = g.calls.drawImage.find((c) => frames.has(c[1]));
      if (!call) continue;
      const rel = bridgeZ - w.camZ, h = call[8];
      tops.push([rel, call[6]]);
      assert.ok(call[6] + Math.round(h * 0.27) <= carTop, `${bottom}: the deck (rows ${call[6]}-${call[6] + Math.round(h * 0.27)}) must stay above the car (top row ${carTop}) at ${Math.round(rel)} units`);
    }
    assert.ok(tops.length > 20, `${bottom}: the overpass remains in view while the faster car approaches (${tops.length} frames)`);
    for (let i = 1; i < tops.length; i++) if (tops[i][0] < 1500) assert.ok(tops[i][1] <= tops[i - 1][1] + 1, `${bottom}: the deck keeps rising (${tops[i - 1][1]} -> ${tops[i][1]} at ${Math.round(tops[i][0])} units)`);
    assert.ok(tops[tops.length - 1][1] <= 30, `${bottom}: by the time it is overhead the deck has left the picture's lower part (row ${tops[tops.length - 1][1]})`);
  }
});

test('one more look at the pieces that must never break: the clock hook, whole-pixel positions and the registered module shape', () => {
  const scene = engine.registry['token-run'];
  for (const name of ['init', 'step', 'draw', 'poke']) assert.equal(typeof scene[name], 'function', name);
  assert.equal(scene.needsAtlas, undefined, 'the scene draws calmly without its atlas');
  const w = world();
  for (let i = 0; i < 200; i++) w.step();
  assert.ok(Number.isInteger(w.player.hop) && Number.isInteger(w.player.lean) && Number.isInteger(w.steps));
  assert.equal(w.light.phase, 'day');
  assert.ok(w.sun.alt > 20 && w.sun.alt < 32, 'a November afternoon');
});
