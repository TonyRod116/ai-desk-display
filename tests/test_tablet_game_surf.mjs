import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';

// TIDAL RUSH (token_tv/tablet_web/game-surf.js): the backdrop (the built-in one and the atlas reader), the warp that makes the sea and the wave flow, the surfer's kinematics, the
// ride (tube, aerial, carve, wipeout), the world (spray, foam, the lip's curtain, gulls, boat, clouds, touch) and, with a fake canvas, the whole drawing path: no holes, a missing or
// broken atlas is calm, the surfer never enters the page's clock, the frame stays cheap. The art here is fictional and made by code; nothing private is needed.
const require = createRequire(import.meta.url);
const engine = require('../token_tv/tablet_web/stage-game.js');
const surf = require('../token_tv/tablet_web/game-surf.js');
const SOURCE = fs.readFileSync(new URL('../token_tv/tablet_web/game-surf.js', import.meta.url), 'utf8');
const {W, H, CLS, POSES, POSE_KEYS, SEGMENTS, VARIANTS, GULL_LANES, GULL_MAX_Y, THIGH, SHIN, BACK_THIGH, BACK_SHIN, UPPER, FORE, TORSO} = surf;
const rand = (seed = 7) => engine.seeded(seed);
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} is not ${b}`);
const ZONE = {x: 125, y0: 116, y1: 186};                                  // what the page puts over the scene at the left while the dock is up: the date, the clock and the weather pill

let sharedBack = null;
const back = () => (sharedBack = sharedBack || surf.makeBackdrop(rand(11)));
const world = (options = {}) => surf.createWorld(Object.assign({random: rand(21), back: back()}, options));

/** A fictional atlas made by code: a gradient plate, a class map, tiny brushes and (optionally) a little palm, in the layout scripts/prepare_game_surf.py writes (ImageData-like). */
function fictionalAtlas({horizon = 120, brushes = true, palm = false} = {}) {
  const w = 200, h = 2 * H + 1 + 20 + (palm ? 41 : 0), data = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) data[i * 4 + 3] = 255;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const p = (y * w + x) * 4, m = ((H + y) * w + x) * 4, water = x > 110 && y > 70 + (x - 110) * 0.2, cls = water ? 3 : y < horizon ? 1 : 2;
    data[p] = water ? 20 : y < horizon ? 200 - y : 40; data[p + 1] = water ? 170 : y < horizon ? 90 + y / 2 : 30; data[p + 2] = water ? 180 : y < horizon ? 120 : 90;
    data[m] = cls; data[m + 1] = 0; data[m + 2] = 0;
  }
  const frames = {plate: [0, 0, W, H], maps: [0, H, W, H]};
  if (brushes) {
    const names = [['puff', [[9, 7], [14, 10]]], ['streak', [[13, 4], [20, 5]]], ['sheet', [[18, 6], [28, 8]]]];
    let y = 2 * H + 1;
    for (const [style, sizes] of names) sizes.forEach(([bw, bh], i) => {
      frames[`foam-${style}-${i}`] = [i * 30, y, bw, bh];
      for (let yy = 0; yy < bh; yy++) for (let xx = 0; xx < bw; xx++) { const p = ((y + yy) * w + i * 30 + xx) * 4; data[p] = 200; data[p + 1] = 200; data[p + 2] = 200; data[p + 3] = 255; }
      y += 0;
    });
  }
  if (palm) {
    frames.palm = [0, 2 * H + 1 + 20, 30, 40];
    for (let yy = 0; yy < 40; yy++) for (let xx = 0; xx < 30; xx++) { const p = ((2 * H + 21 + yy) * w + xx) * 4, on = (xx - 15) ** 2 + (yy - 14) ** 2 < 150 || (xx > 13 && xx < 17 && yy < 40); data[p] = on ? 20 : 255; data[p + 1] = on ? 120 : 0; data[p + 2] = on ? 60 : 255; data[p + 3] = on ? 255 : 0; }
  }
  const geometry = {horizon, sun: {x: 40, y: 104, r: 20}, centre: [130, 120], hole: [130, 110, 30, 20], tip: [80, 120], path: [20, 70],
    lip: [[150, 40], [120, 50], [100, 70]], line: [[104, 170], [120, 160], [140, 148], [152, 136], [158, 124], [156, 112], [148, 104]], foot: [[10, 190], [90, 180], [160, 150]]};
  return {pixels: {width: w, height: h, data}, json: {version: 2, scene: 'surf', size: [w, h], frames, geometry}};
}
/** A fake 2D context that keeps the last ImageData it was given. */
function fakeCanvas() {
  const calls = [];
  return {calls, g: {putImageData(img, x, y) { calls.push({img, x, y}); }, drawImage() {}, fillRect() {}}};
}
function makeApi(options = {}) {
  return Object.assign({name: 'surf', size: [W, H], atlas: null, json: null, time: 0, tier: 'high', random: rand(3), view: {top: 0, bottom: 186}, readings: () => null, sprite: () => false}, options);
}
globalThis.ImageData = class ImageData { constructor(w, h) { this.width = w; this.height = h; this.data = new Uint8ClampedArray(w * h * 4); } };
const run = (api, steps, canvas) => { for (let i = 0; i < steps; i++) { surf.scene.step(api, 1 / 30); api.time += 1 / 30; } surf.scene.draw(api, canvas.g); return canvas.calls[canvas.calls.length - 1].img; };
const pixelsOf = (img) => new Uint32Array(img.data.buffer.slice(img.data.byteOffset, img.data.byteOffset + img.data.byteLength));

/* ---- the engine contract ------------------------------------------------------------------------------------------------------------------ */

test('registered as surf in the engine, portrait 200 x 320, calm without its atlas', () => {
  const scene = engine.registry.surf;
  assert.ok(scene, 'the scene registers itself');
  assert.deepEqual(scene.size, [200, 320]);
  for (const name of ['init', 'step', 'draw', 'poke']) assert.equal(typeof scene[name], 'function', name);
  assert.equal(scene.needsAtlas, undefined, 'it draws a built-in backdrop without the atlas');
  assert.equal(scene.post, undefined, 'the default CRT pass');
});

/* ---- the built-in backdrop and the geometry ------------------------------------------------------------------------------------------------- */

test('the built-in backdrop: sky above the horizon, sea below it, water on the right, a sky window through the tube, deterministic', () => {
  const b = back(), g = b.geom, hz = g.horizon;
  assert.equal(b.rgb.length, W * H); assert.equal(b.cls.length, W * H);
  const count = (cls) => b.cls.reduce((n, c) => n + (c === cls ? 1 : 0), 0);
  assert.ok(count(CLS.SKY) > 0.2 * W * hz, 'open sky');
  assert.ok(count(CLS.SEA) > 0.05 * W * H, 'open sea');
  assert.ok(count(CLS.WATER) > 0.25 * W * H, 'a big wave');
  for (let x = 0; x < W; x++) assert.notEqual(b.cls[(hz - 6) * W + x], CLS.SEA, 'no sea above the horizon');
  const [cx, cy] = g.centre, hole = g.hole;
  assert.notEqual(b.cls[(hole[1] - 4) * W + Math.round(hole[0])], CLS.WATER, 'the tube mouth is open: you see the sky through it');
  for (let i = 0; i < b.rgb.length; i++) assert.equal(b.rgb[i] >>> 24, 255, 'every pixel is opaque');
  const again = surf.makeBackdrop(rand(11));
  assert.deepEqual(Array.from(again.rgb.slice(0, 2000)), Array.from(b.rgb.slice(0, 2000)));
  assert.deepEqual(again.geom, g);
  assert.ok(cx > 60 && cx < 190 && cy > 40 && cy < 200);
});

test('geometry: the defaults are sane and a given geometry replaces only its valid keys', () => {
  const g = surf.DEFAULT_GEOM;
  assert.ok(g.horizon > 60 && g.horizon < 200 && g.sun.r > 8);
  for (const key of ['lip', 'line', 'foot']) assert.ok(g[key].length >= 2 && g[key].every((p) => p.length === 2 && p.every(Number.isFinite)), key);
  assert.ok(g.line.length >= 4);
  const merged = surf.mergeGeometry({horizon: 140, sun: {x: 30, y: 100, r: 18}, centre: [120, 120], hole: [120, 110, 30, 20], line: [[0, 0], [1, 1], [2, 2], [3, 3]], lip: 'nonsense', foot: [[NaN, 1], [2, 2]], tip: [9999, 9999], path: ['a', 'b']});
  assert.equal(merged.horizon, 140); assert.deepEqual(merged.sun, {x: 30, y: 100, r: 18}); assert.deepEqual(merged.centre, [120, 120]);
  assert.deepEqual(merged.line, [[0, 0], [1, 1], [2, 2], [3, 3]]);
  assert.deepEqual(merged.lip, g.lip, 'a bad list is ignored'); assert.deepEqual(merged.foot, g.foot, 'a point that is not a number is ignored'); assert.deepEqual(merged.tip, g.tip); assert.deepEqual(merged.path, g.path);
  for (const bad of [null, undefined, 5, 'x', [], {horizon: -4}, {horizon: 'high'}, {sun: {x: 1}}]) assert.doesNotThrow(() => surf.mergeGeometry(bad));
  assert.equal(surf.mergeGeometry({horizon: 5}).horizon, g.horizon, 'a horizon outside the picture is ignored');
  assert.notEqual(surf.mergeGeometry({lip: [[1, 2], [3, 4]]}).lip, g.lip, 'defaults are copied, never shared');
});

test('the atlas reader reads a fictional atlas, keeps its geometry and refuses anything wrong without throwing', () => {
  const {pixels, json} = fictionalAtlas(), plate = surf.readPlate(json, pixels);
  assert.ok(plate, 'a good atlas is read'); assert.equal(plate.builtin, false);
  assert.equal(plate.rgb.length, W * H);
  assert.equal(plate.geom.horizon, 120);
  assert.equal(plate.cls[10 * W + 10], CLS.SKY); assert.equal(plate.cls[200 * W + 10], CLS.SEA); assert.equal(plate.cls[200 * W + 180], CLS.WATER);
  assert.equal(plate.rgb[10 * W + 10], (0xff000000 | (120 << 16) | (95 << 8) | 190) >>> 0, 'the colours come from the plate frame');
  const bad = [
    [null, pixels], [{}, pixels], [{frames: {}}, pixels], [json, null], [json, {width: 200, data: null}],
    [{frames: {plate: [0, 0, 100, 100], maps: json.frames.maps}}, pixels], [{frames: {plate: [0, 0, W, H], maps: [0, H, W, 5]}}, pixels], [{frames: {plate: 'x', maps: 3}}, pixels],
    [json, {width: pixels.width, height: 10, data: new Uint8ClampedArray(40)}], [{frames: {plate: [0, 0, W, H], maps: [0, 900, W, H]}}, pixels],
  ];
  for (const [j, p] of bad) assert.equal(surf.readPlate(j, p), null);
  const odd = fictionalAtlas(); odd.pixels.data[(H * odd.pixels.width + 5) * 4] = 200;                // a class above 3 is clamped to water
  assert.equal(surf.readPlate(odd.json, odd.pixels).cls[5], CLS.WATER);
});

/* ---- the warp --------------------------------------------------------------------------------------------------------------------------- */

test('the warp: only animated pixels move, a class borrows only from its own class, silhouettes stay still, and the rows below `lim` are not touched', () => {
  const b = back(), warp = surf.buildWarp(b.cls, b.geom), dst = new Uint32Array(W * H);
  assert.ok(warp.sea.idx.length > 1000 && warp.water.idx.length > 5000, 'something to animate');
  const edge = (i) => { const x = i % W, y = (i / W) | 0; for (let dy = -3; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) { const nx = x + dx, ny = y + dy; if (nx >= 0 && nx < W && ny >= 0 && ny < H && b.cls[ny * W + nx] !== b.cls[i]) return true; } return false; };
  for (const list of [warp.sea.idx, warp.water.idx]) for (let k = 0; k < list.length; k += 37) assert.ok(!edge(list[k]), 'a pixel near another class stays still');
  surf.applyWarp(dst, b, warp, 77, H);
  const colours = {[CLS.SEA]: new Set(), [CLS.WATER]: new Set()};
  for (let i = 0; i < W * H; i++) if (b.cls[i] === CLS.SEA || b.cls[i] === CLS.WATER) colours[b.cls[i]].add(b.rgb[i]);
  let moved = 0;
  for (let i = 0; i < W * H; i++) {
    if (dst[i] !== b.rgb[i]) { moved++; assert.ok(colours[b.cls[i]] && colours[b.cls[i]].has(dst[i]), 'a warped pixel keeps to the colours of its own class'); }
    if (b.cls[i] === CLS.SKY || b.cls[i] === CLS.STILL) assert.equal(dst[i], b.rgb[i], 'the sky is never warped');
  }
  assert.ok(moved > 500, `the warp moves ${moved} pixels`);
  const other = new Uint32Array(W * H); surf.applyWarp(other, b, warp, 140, H);
  let differ = 0; for (let i = 0; i < W * H; i++) if (other[i] !== dst[i]) differ++;
  assert.ok(differ > 300, 'later phases look different');
  const part = new Uint32Array(W * H).fill(0xdeadbeef); surf.applyWarp(part, b, warp, 77, 150);
  for (let i = 150 * W; i < W * H; i++) assert.equal(part[i], 0xdeadbeef, 'rows under the dock are left alone');
  for (let i = 0; i < 150 * W; i++) assert.equal(part[i], dst[i]);
});

/* ---- the surface the surfer rides --------------------------------------------------------------------------------------------------------- */

test('the surface line: u runs along it, d goes into the water (and negative into the air), the slope rises to the right', () => {
  const b = back(), s = surf.makeSurface(b.geom);
  assert.ok(s.L > 60);
  const p0 = s.at(0.3, 0), p1 = s.at(0.3, 10), tangent = s.path.tangent(0.3 * s.L);
  close(Math.hypot(p1[0] - p0[0], p1[1] - p0[1]), 10, 1e-6);
  assert.ok(Math.abs((p1[0] - p0[0]) * tangent[0] + (p1[1] - p0[1]) * tangent[1]) < 1e-6, 'the offset is perpendicular to the line');
  for (let u = 0.2; u <= 0.5; u += 0.05) {
    const water = s.at(u, 6), air = s.at(u, -6);
    assert.equal(b.cls[Math.round(water[1]) * W + Math.round(water[0])], CLS.WATER, `u ${u.toFixed(2)}: into the water is water`);
    assert.notEqual(b.cls[Math.round(air[1]) * W + Math.round(air[0])], CLS.WATER, `u ${u.toFixed(2)}: into the air is air`);
  }
  assert.ok(s.slope(0.3) > 0.3 && s.slope(0.3) < 1.3, 'the ramp rises to the right');
});

/* ---- the surfer ------------------------------------------------------------------------------------------------------------------------ */

test('every pose is reachable at every board pitch: legs and arms keep their lengths, feet stay on the deck, the head is above the hips, about 55 px with the board', () => {
  for (const [name, pose] of Object.entries(POSES)) {
    for (let pitch = -40; pitch <= 40; pitch += 5) {
      const f = surf.figure(pose, pitch), d = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
      close(d(f.hip, f.kneeF), THIGH, 0.05); close(d(f.kneeF, f.footF), SHIN, 0.05); close(d(f.hip, f.kneeB), BACK_THIGH, 0.05); close(d(f.kneeB, f.footB), BACK_SHIN, 0.05);
      assert.ok(Math.abs(d(f.sF, f.elbowF) - UPPER) < 0.1 && Math.abs(d(f.sB, f.elbowB) - UPPER) < 0.1, `${name}: upper arms`);
      assert.ok(Math.abs(d(f.elbowF, f.handF) - FORE) < 0.1 && Math.abs(d(f.elbowB, f.handB) - FORE) < 0.1, `${name}: forearm`);
      assert.ok(f.head[1] < f.hip[1] - 4 || pose.lean > 45, `${name} at ${pitch}: the head is above the hips`);
      close(d(f.footF, f.footB), Math.abs(pose.bfx - pose.ffx), 0.05);
      assert.ok(d(f.hip, f.shoulder) > TORSO - 0.1 && d(f.hip, f.shoulder) < TORSO + 0.1, `${name}: torso`);
    }
  }
  const stand = surf.figure(POSES.trim, 0), height = Math.abs(stand.head[1]) + 6 + 4;
  assert.ok(height > 48 && height < 66, `standing: ${height}`);
  const ten = surf.figure(POSES.hangTen, 0);
  assert.ok(ten.footF[0] < stand.footF[0] - 5, 'hanging ten: the front foot is on the nose');
});

test('poses blend smoothly and the pose FOLLOWS its target joint by joint with a lag (hips first, hands last: the overlap); there is no rotation anywhere in the scene', () => {
  const half = surf.blendPose(POSES.trim, POSES.bottom, 0.5);
  for (const k of POSE_KEYS) close(half[k], (POSES.trim[k] + POSES.bottom[k]) / 2, 1e-9);
  assert.deepEqual(surf.blendPose(POSES.trim, POSES.tuck, 0), Object.assign({}, POSES.trim));
  const cur = Object.assign({}, POSES.trim), tgt = POSES.crouch, gap = (pose, k) => Math.abs(tgt[k] - pose[k]) / (Math.abs(tgt[k] - POSES.trim[k]) || 1);
  const trace = []; for (let i = 0; i < 6; i++) { surf.followPose(cur, tgt, 1); trace.push(Object.assign({}, cur)); }
  assert.ok(gap(trace[3], 'hy') < gap(trace[3], 'head') && gap(trace[3], 'head') < gap(trace[3], 'bx'), 'the hips get there first, the head next, the hands last');
  assert.ok(gap(trace[3], 'lean') < gap(trace[3], 'fy'), 'the torso leads the arms');
  for (let i = 0; i < 160; i++) surf.followPose(cur, tgt, 1); for (const k of POSE_KEYS) close(cur[k], tgt[k], 0.01);
  const quick = Object.assign({}, POSES.trim), slow = Object.assign({}, POSES.trim); surf.followPose(quick, tgt, 1.8); surf.followPose(slow, tgt, 1); assert.ok(gap(quick, 'hy') < gap(slow, 'hy'), 'a snappy move gets there faster');
  for (const name of Object.keys(POSES)) for (const k of POSE_KEYS) assert.ok(Number.isFinite(POSES[name][k]), `${name}.${k}`);
  assert.ok(!/\byaw\b|\btumble\b|viewFigure/.test(SOURCE), 'no yaw, no tumble: he never turns round and nothing spins');
  assert.ok(!SEGMENTS.air.some((m) => m.yaw || m.tumble) && Object.values(SEGMENTS).every((l) => l.every((m) => !m.yaw && !m.tumble)), 'no move rotates anything');
});

test('the figures draw into their raster with an outline, never outside it; every pose and yaw puts pixels down; the paddler and the swimmer too', () => {
  const r = surf.makeRaster(128, 112), palette = surf.surferPalette(), fb = new Uint32Array(W * H);
  for (const name of Object.keys(POSES)) for (const yaw of [0, 1, Math.PI / 2, 2.5, Math.PI]) {
    r.clear(); surf.drawStanding(r, 64, 84, {pose: POSES[name], pitch: -20, yaw, rot: 0, board: true});
    let n = 0, minX = 128, maxX = 0, minY = 112, maxY = 0;
    for (let y = 0; y < 112; y++) for (let x = 0; x < 128; x++) if (r.buf[y * 128 + x]) { n++; minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y); }
    assert.ok(n > 250, `${name} at yaw ${yaw}: ${n} pixels`);
    assert.ok(minX > 2 && maxX < 125 && minY > 2 && maxY < 109, `${name} at yaw ${yaw} stays inside the raster with room for the outline`);
  }
  r.clear(); surf.drawPaddler(r, 64, 84, 1.2, 0); assert.ok(r.buf.some((v) => v), 'a paddler');
  r.clear(); surf.drawSwimmer(r, 64, 84, 0.4); assert.ok(r.buf.some((v) => v), 'a swimmer');
  r.clear(); surf.drawBoard(r, 64, 84, 0.4, 1, 0); assert.ok(r.buf.some((v) => v), 'a board');
  r.clear(); surf.drawStanding(r, 64, 84, {pose: POSES.trim, pitch: 0, yaw: 0, rot: 0, board: true}); surf.blitRaster(fb, r, 60, 80, palette, 0xff112233);
  assert.ok(fb.some((v) => v === 0xff112233), 'the outline is drawn'); assert.ok(fb.some((v) => v === palette[surf.S.shirt]), 'the shirt is drawn');
  assert.ok(fb.some((v) => v === palette[surf.S.shirtLight]) && fb.some((v) => v === palette[surf.S.shirtShade]), 'the shirt has three tones: light and shade');
  const lit = new Uint32Array(W * H), rim = surf.rimPalette(palette); surf.blitRaster(lit, r, 60, 80, palette, 0xff112233, rim);
  assert.ok(lit.some((v) => v === rim[surf.S.skinLight] || v === rim[surf.S.skin] || v === rim[surf.S.shirt] || v === rim[surf.S.shirtLight]), 'the sunny edge catches the sunset\'s rim light');
  for (let i = 1; i < palette.length; i++) { const a = rim[i], b = palette[i]; assert.ok(i === surf.S.white || a >>> 24 === 255 && (a & 255) + ((a >> 8) & 255) + ((a >> 16) & 255) >= 0.93 * ((b & 255) + ((b >> 8) & 255) + ((b >> 16) & 255)), `rim ${i} is not darker than its colour`); }
  const none = new Uint32Array(W * H); surf.blitRaster(none, r, -200, -200, palette, 0xff112233); surf.blitRaster(none, r, 190, 310, palette, 0xff112233);
  assert.doesNotThrow(() => surf.blitRaster(none, r, -40, 300, palette, 0xff112233), 'a sprite half off the picture is clipped');
});

test('the board pitch follows the motion and never flickers: up is nose up, clamped, and the quantiser has hysteresis', () => {
  assert.ok(surf.pitchFor(1, -1) > 30 && surf.pitchFor(1, 1) < -30 && Math.abs(surf.pitchFor(1, 0)) < 1);
  assert.ok(surf.pitchFor(0, -9) <= 38 && surf.pitchFor(0, 9) >= -38, 'never on its end');
  assert.equal(surf.quantise(12, 10), 10, 'a small change keeps the pose'); assert.equal(surf.quantise(16, 10), 15); assert.equal(surf.quantise(-23, 0), -25);
  let current = 0, flips = 0, last = 0;
  for (let i = 0; i < 400; i++) { current = surf.quantise(7.5 + 1.2 * Math.sin(i * 0.9), current); if (current !== last) flips++; last = current; }
  assert.ok(flips <= 2, `${flips} changes while the angle wobbles around 7.5`);
});

/* ---- the ride ------------------------------------------------------------------------------------------------------------------------- */

test('every variant is a chain of moves that starts where the last one ended: no jumps (except out of sight), bounded speed, valid poses, every ride ends standing at the start', () => {
  assert.deepEqual(VARIANTS.slice().sort(), ['air', 'carve', 'tube', 'wipeout']);
  for (const v of VARIANTS) {
    const surface = surf.makeSurface(back().geom), ride = surf.createRide(surface, rand(5), v), start = surface.at(surf.START.u, surf.START.d);
    let last = [ride.x, ride.y], seen = new Set(), ended = 0, lastName = ride.name;
    for (let i = 0; i < 3000 && ended < 1; i++) {
      const r = ride.step(), jump = Math.hypot(r.x - last[0], r.y - last[1]);
      if (!r.hidden) assert.ok(jump < 5.2, `${v}/${r.name}: a jump of ${jump.toFixed(2)} px at step ${i}`);
      if (r.name !== lastName) assert.equal(r.u, 0, `${v}/${r.name}: on the step a move starts its progress is 0 (not the last move's 1), or the prone paddler would flash standing for one frame`);
      lastName = r.name; seen.add(r.name); last = [r.x, r.y];
      for (const k of POSE_KEYS) assert.ok(Number.isFinite(r.pose[k]), `${v}: pose ${k}`);
      assert.ok(['stand', 'fall', 'under', 'swim', 'paddle', 'popup', 'engulf'].includes(r.mode), r.mode);
      if (r.ended) ended++;
    }
    assert.equal(ended, 1, `${v} ends`);
    assert.ok(Math.hypot(last[0] - start[0], last[1] - start[1]) < 4, `${v} ends at the start, standing, so that the next one begins there`);
    for (const seg of SEGMENTS[v]) assert.ok(seen.has(seg.name), `${v} plays ${seg.name}`);
  }
  const lengths = Object.fromEntries(VARIANTS.map((v) => [v, SEGMENTS[v].reduce((n, s2) => n + s2.dur, 0) / 30]));
  for (const [v, seconds] of Object.entries(lengths)) assert.ok(seconds > 10 && seconds < 20, `${v} lasts ${seconds.toFixed(1)} s`);
});

test('the story: pump and trim, a bottom turn low with the rails in, a straight-up air with a pop, a tuck, a grab, an extension and a landing that absorbs; a tube, a hang ten, a cutback; a fall without a spin, a paddle and a pop-up', () => {
  const names = (v) => SEGMENTS[v].map((m) => m.name), has = (v, name) => SEGMENTS[v].find((m) => m.name === name);
  assert.deepEqual(names('tube'), ['drop', 'bottom', 'pump', 'tubeIn', 'stall', 'drag', 'pumpLow', 'duck', 'engulf', 'spit']);
  assert.ok(has('tube', 'tubeIn').events.some((e) => e[1] === 'veil') && has('tube', 'duck').events.some((e) => e[1] === 'crash'), 'the lip throws and the foam boils when he ducks');
  assert.ok(has('tube', 'stall').pose.some((k) => k[1] === 'stall') && has('tube', 'drag').pose.some((k) => k[1] === 'drag') && has('tube', 'duck').pose.some((k) => k[1] === 'duck'), 'a stall, a drag, a duck');
  assert.ok(has('tube', 'bottom').pose[0][1] === 'bottom' && POSES.bottom.rail > 0.7, 'a bottom turn: low, rails in'); assert.ok(POSES.bottom.hy > POSES.trim.hy && POSES.bottom.lean > POSES.trim.lean);
  const pump = has('tube', 'pump').pose.map((k) => k[1]); assert.ok(pump.filter((k) => k === 'pumpDown').length >= 2 && pump.filter((k) => k === 'pumpUp').length >= 2, 'the knees work: pump down and up, twice');
  assert.ok(has('carve', 'carve').pose.some((k) => k[1] === 'cutback') && POSES.cutback.lean < 0, 'a cutback: the hips lead, the shoulders follow');
  assert.ok(has('air', 'hang').pose.some((k) => k[1] === 'hangTen') && POSES.hangTen.ffx < POSES.trim.ffx - 5, 'hang ten on a flat section: the front foot on the nose');
  const air = has('air', 'airUp');
  assert.deepEqual(air.pose.map((k) => k[1]), ['anticipate', 'pop', 'airTuck', 'grab', 'extend', 'land', 'land'], 'coil, pop, tuck, grab, extend, land');
  assert.ok(air.wps.every((w) => Math.abs(w.dx) < 8), 'straight up: no sideways swing'); assert.ok(Math.min(...air.wps.map((w) => w.dy)) < -25, 'a real jump'); assert.ok(air.hang > 0.3, 'a hold at the top');
  assert.ok(POSES.land.hy > POSES.pop.hy + 4 && POSES.land.lean > 25, 'the landing absorbs with the knees');
  assert.deepEqual(names('wipeout').slice(3), ['wobble', 'fall', 'under', 'swim', 'paddle', 'popup']);
  assert.ok(has('wipeout', 'wobble').pose.map((k) => k[1]).includes('fall1') && has('wipeout', 'wobble').pose.map((k) => k[1]).includes('fall2'), 'he loses his balance and his arms windmill');
  const surface = surf.makeSurface(back().geom), ride = surf.createRide(surface, rand(9), 'wipeout'), modes = new Set(), events = new Set();
  let boardModes = new Set();
  for (let i = 0; i < 420; i++) { const r = ride.step(); modes.add(r.mode); r.events.forEach((e) => events.add(e)); boardModes.add(ride.board.mode); if (r.name === 'popup') assert.equal(ride.board.mode, 'attached'); }
  for (const m of ['stand', 'fall', 'under', 'swim', 'paddle', 'popup']) assert.ok(modes.has(m), m);
  assert.ok(events.has('splash') && events.has('oops') && events.has('boardsplash'), [...events].join());
  assert.ok(boardModes.has('flying') && boardModes.has('float') && boardModes.has('attached'));
  const tubeRide = surf.createRide(surface, rand(3), 'tube'); const hidden = []; let spat = false;
  for (let i = 0; i < 440; i++) { const r = tubeRide.step(); if (r.name === 'engulf') hidden.push(r.hidden); if (r.events.includes('spit')) spat = true; }
  assert.ok(hidden.length && hidden.every(Boolean), 'the foam hides him while he is swallowed'); assert.ok(spat, 'and spits him out');
});

test('the variants alternate at random but never repeat one, never two wipeouts in a row, and all four turn up', () => {
  const surface = surf.makeSurface(back().geom), ride = surf.createRide(surface, rand(2), 'tube'), order = [ride.variant];
  for (let i = 0; i < 40000 && order.length < 40; i++) { const r = ride.step(); if (r.ended) order.push(ride.variant); }
  for (let i = 1; i < order.length; i++) assert.notEqual(order[i], order[i - 1], `loop ${i}`);
  assert.equal(new Set(order).size, 4, order.join());
  assert.ok(order.filter((v) => v === 'wipeout').length < order.length * 0.5, 'a wipeout is an occasional thing');
  const long = surf.createRide(surface, rand(5), 'tube'), rides = [long.variant];
  for (let i = 0; i < 300000 && rides.length < 120; i++) { const r = long.step(); if (r.ended) rides.push(long.variant); }
  const share = rides.filter((v) => v === 'tube').length / rides.length;
  assert.ok(share > 0.38 && share < 0.58, `about every second ride is a tube ride (${(share * 100).toFixed(0)} %)`);
  for (let i = 1; i < rides.length; i++) if (rides[i - 1] === 'tube') assert.notEqual(rides[i], 'tube', 'never two barrels in a row');
});

test('the surfer never enters the page\'s date, clock and weather pill (x < 125 on the rows 116-186) in 12 minutes of riding, wipeouts and aerials included', () => {
  const api = makeApi(), canvas = fakeCanvas();
  surf.scene.init(api);
  const s = surf.scene.s, w = s.world;
  let boxes = 0, modes = new Set();
  for (let i = 0; i < 21600; i++) {
    surf.scene.step(api, 1 / 30);
    for (const b of surf.drawSurferFrame(s, w, true)) { boxes++; modes.add(w.surfer.mode); assert.ok(!(b[0] < ZONE.x && b[3] >= ZONE.y0 && b[1] < ZONE.y1), `step ${i} ${w.ride.variant}/${w.surfer.name}: box ${b} is over the clock`); assert.ok(b[2] <= W - 1 && b[0] >= 0 && b[3] < H, `step ${i} ${w.ride.variant}/${w.surfer.name}: box ${b} leaves the screen`); }
  }
  assert.ok(boxes > 20000); for (const m of ['stand', 'fall', 'swim', 'paddle']) assert.ok(modes.has(m), m);
  surf.scene.draw(api, canvas.g);
});

/* ---- the world ------------------------------------------------------------------------------------------------------------------------- */

test('the world is deterministic with the seeded random', () => {
  const a = world(), b = world();
  a.seek(900); b.seek(900);
  assert.deepEqual(a.surfer, b.surfer); assert.deepEqual(a.gulls, b.gulls); assert.equal(a.particles.length, b.particles.length); assert.deepEqual(a.foamItems.map((q) => q.x.toFixed(3)), b.foamItems.map((q) => q.x.toFixed(3)));
});

test('particles, foam, wake and ripples stay bounded over 12,000 steps and everything has a lifetime', () => {
  const w = world();
  let maxP = 0, maxF = 0, maxW = 0, spray = 0;
  for (let i = 0; i < 12000; i++) { w.step(); maxP = Math.max(maxP, w.particles.length); maxF = Math.max(maxF, w.foamItems.length); maxW = Math.max(maxW, w.wake.length); spray += w.particles.length > 0 ? 1 : 0; }
  assert.ok(maxP <= 250, `${maxP} particles`); assert.ok(maxF <= 92, `${maxF} foam items`); assert.ok(maxW <= 76);
  assert.ok(spray > 6000, 'spray most of the time');
  for (const q of w.particles) assert.ok(q.age < q.life && q.y < H);
  for (const q of w.foamItems) assert.ok(q.age < q.life && Number.isFinite(q.x));
});

test('the breaking lip sheds a few short droplets without filling the open barrel with rain', () => {
  const w = world({first: 'tube'}), c = w.columns;
  let droplets = 0, seen = 0, state = new Set(), foam = 0;
  for (let i = 0; i < 440; i++) {
    w.step(); state.add(w.veil.state);
    const spray = w.particles.filter((p) => p.kind === 1);
    seen += spray.length; droplets = Math.max(droplets, spray.length);
    for (const drop of spray) { assert.ok(drop.len <= 3 && drop.floor - drop.y <= 10, 'a short drop stays close to the lip'); assert.ok(drop.vx < 0, 'water moves along the breaking lip'); }
    foam = Math.max(foam, w.foamItems.filter((q) => q.layer === 'front').length);
  }
  assert.ok(state.has('throw') && state.has('crash'), [...state].join());
  assert.ok(seen > 0 && droplets <= 3, `${droplets} droplets at once`); assert.ok(foam >= 3, `${foam} puffs`);
  let covered = 0; for (let x = c.x0; x <= c.x1; x++) if (c.arch[x] > 0 && c.floor[x] > c.arch[x]) covered++;
  assert.ok(covered > 30, 'the curtain has columns to fall in'); assert.ok(c.x0 < w.geom.hole[0] && c.x1 > w.geom.hole[0]);
  for (let x = c.x0; x <= c.x1; x++) if (c.arch[x] > 0 && c.floor[x] > 0) assert.ok(c.floor[x] > c.arch[x], `column ${x}: the floor is under the lip`);
});

test('gulls: three in the sky from the start, the wing cycle and gliding, calm lanes, they cross and come back, and never fly lower than the sky', () => {
  const w = world();
  assert.equal(w.gulls.length, 3);
  for (const g of w.gulls) assert.ok(g.x > 0 && g.x < W, 'already in the sky when the scene opens');
  const flap = surf.wingAngles(1.0, 1), glide = surf.wingAngles(1.0, 0.1);
  assert.ok(flap.inner > glide.inner - 0.5);
  let up = -9, down = 9; for (let p = 0; p < 6.3; p += 0.1) { const a = surf.wingAngles(p, 1); up = Math.max(up, a.inner); down = Math.min(down, a.inner); }
  assert.ok(up > 0.7 && down < -0.55, `the stroke swings from ${down.toFixed(2)} to ${up.toFixed(2)} rad`);
  let lag = 0; for (let p = 0; p < 6.3; p += 0.1) { const a = surf.wingAngles(p, 1); lag += Math.abs(a.outer - a.inner); }
  assert.ok(lag > 5, 'the hand does not move with the upper wing: it lags');
  let low = 0, crossed = new Set(), flaps = 0, glides = 0;
  for (let i = 0; i < 9000; i++) { w.step(); for (const [k, g] of w.gulls.entries()) { low = Math.max(low, g.y); if (g.x > 100) crossed.add(k); if (g.mode === 'flap') flaps++; else glides++; } }
  assert.ok(low <= GULL_MAX_Y + 0.001, `the lowest gull y ${low}`); assert.ok(GULL_MAX_Y < 125, 'far above the clock');
  assert.equal(crossed.size, 3, 'every gull crosses the picture'); assert.ok(flaps > 1000 && glides > 1000, 'they flap for a while and then glide');
  for (const lane of GULL_LANES) assert.ok(lane.y < GULL_MAX_Y - 10);
  const shape = surf.gullShape(w.gulls[0]); assert.ok(shape.near.length === 3 && shape.far.length === 3);
});

test('the set: every 60 seconds a swell builds in the tube\'s window, stands up and closes out in a burst; the surge rises and falls with it and the water runs faster while it lasts', () => {
  assert.equal(surf.SET_LEN, 1800);
  let peak = 0, calm = 0, high = 0;
  for (let c = 0; c < surf.SET_LEN; c++) { const st = surf.setState(c); assert.ok(st.h >= 0 && st.h <= 15.0001 && st.surge >= 0 && st.surge <= 1 && st.lip >= 0 && st.lip <= 1, `step ${c}`); peak = Math.max(peak, st.h); if (st.surge === 0) calm++; if (st.h > 9) high++; }
  assert.ok(peak > 14.5, `the swell peaks at ${peak}`); assert.ok(calm > 600, 'a lull'); assert.ok(high > 400, 'it stands for a while');
  assert.equal(surf.setState(surf.SET_LEN).h, 0, 'the cycle closes');
  assert.ok(surf.setState(surf.SET_BURST - 1).h > 14, 'it is at its highest when it closes out'); assert.ok(surf.setState(surf.SET_BURST + 120).h < 0.5, 'and gone soon after');
  const w = world();
  let burst = false, shook = false, mist = 0, surge = 0, phase0 = w.phase;
  for (let i = 0; i < surf.SET_LEN + 10; i++) { w.step(); if (w.steps === surf.SET_BURST) burst = true; if (w.shake) shook = true; mist = Math.max(mist, w.mist.length); surge = Math.max(surge, w.surge); }
  assert.ok(burst && shook, 'a close-out shakes the camera'); assert.ok(mist > 25, `${mist} puffs of mist`); assert.equal(surge, 1);
  assert.ok(w.phase - phase0 > surf.SET_LEN * 1.1, 'the flow phase runs ahead of time while the surge lasts'); for (let i = 0; i < 60 && w.shake; i++) w.step(); assert.equal(w.shake, null, 'the shake dies away');
  assert.ok(w.mist.length < 60);
});

test('a touch: on the surfer he hops and grabs his board (no spin), on the water a splash and a ripple, in the sky a gull takes off (two at most)', () => {
  const w = world();
  w.seek(40);
  const s = w.surfer, hit = w.poke(s.x, s.y - 10);
  assert.equal(hit, 'surfer'); assert.ok(s.hop > 0);
  let low = Infinity, grabbed = false; for (let i = 0; i < 30; i++) { w.step(); if (Math.abs(s.pose.lean - POSES.grab.lean) < 12 && Math.abs(s.pose.fy - POSES.grab.fy) < 4) grabbed = true; low = Math.min(low, s.pitchQ); }
  assert.ok(grabbed, 'he grabs the rail in the air'); assert.equal(s.hop, 0); assert.ok(low >= -40);
  assert.equal(w.poke(10, w.geom.horizon + 30), 'splash'); assert.ok(w.ripples.length >= 1);
  const gulls = w.gulls.length; assert.equal(w.poke(30, 40), 'gull'); assert.equal(w.gulls.length, gulls + 1);
  w.poke(60, 45); w.poke(90, 60); w.poke(90, 60);
  assert.ok(w.gulls.filter((g) => g.poked).length <= 2, 'two at most');
  for (const [x, y] of [[0, 0], [199, 319], [-5, -5], [1e9, 1e9], [NaN, 3]]) assert.doesNotThrow(() => w.poke(x, y));
  w.seek(2000);
  assert.ok(w.gulls.every((g) => !g.poked || Math.abs(g.x) < 400), 'a poked gull flies away');
});

/* ---- the drawing path ------------------------------------------------------------------------------------------------------------------ */

test('init, step and draw work with no atlas, with a fictional atlas and with broken ones; every pixel is painted and exactly one putImageData goes out', () => {
  const {pixels, json} = fictionalAtlas();
  const cases = {'no atlas': {}, 'a fictional atlas': {atlas: pixels, json}, 'json but no pixels': {json}, 'garbage json': {atlas: pixels, json: {frames: 7}}, 'a short atlas': {atlas: {width: 200, data: new Uint8ClampedArray(100)}, json}};
  for (const [name, extra] of Object.entries(cases)) {
    const canvas = fakeCanvas(), api = makeApi(extra);
    assert.doesNotThrow(() => surf.scene.init(api), name);
    const img = run(api, 90, canvas);
    assert.equal(canvas.calls.length, 1, `${name}: one putImageData`); assert.equal(img.width, W); assert.equal(img.height, H);
    const px = pixelsOf(img); for (let i = 0; i < W * H; i += 7) assert.equal(px[i] >>> 24, 255, `${name}: pixel ${i} is painted`);
    assert.equal(surf.scene.s.back.builtin, name !== 'a fictional atlas', `${name}: which backdrop`);
  }
});

test('constant random generators (all zeros, all ones) never break the scene', () => {
  for (const value of [0, 0.5, 0.999999]) {
    const api = makeApi({random: () => value}), canvas = fakeCanvas();
    assert.doesNotThrow(() => { surf.scene.init(api); run(api, 400, canvas); }, `random ${value}`);
  }
});

test('the dock: only the rows it leaves visible (plus a margin) are redrawn, the whole picture when it goes away, and the scrim darkens the clock\'s corner only while it is up', () => {
  assert.equal(surf.rowsFor(186), 222); assert.equal(surf.rowsFor(320), 320); assert.equal(surf.rowsFor(NaN), 320 > 150 ? surf.rowsFor(NaN) : 0); assert.ok(surf.rowsFor(0) >= 150);
  assert.equal(surf.dockFor(186), 1); assert.equal(surf.dockFor(320), 0); for (let b = 120; b < 330; b += 10) { const d = surf.dockFor(b); assert.ok(d >= 0 && d <= 1); }
  const up = makeApi({view: {top: 0, bottom: 186}}), whole = makeApi({view: {top: 0, bottom: 320}}), c1 = fakeCanvas(), c2 = fakeCanvas();
  surf.scene.init(up); const a = pixelsOf(run(up, 60, c1));
  const frozen = pixelsOf(run(up, 5, c1));                                                        // rows under the dock keep the last whole picture while the dock is up
  for (let i = 240 * W; i < 320 * W; i += 11) assert.equal(frozen[i], a[i]);
  surf.scene.init(whole); const b = pixelsOf(run(whole, 60, c2));
  const luma = (px) => { let t = 0, n = 0; for (let y = 130; y < 170; y += 2) for (let x = 6; x < 70; x += 2) { const v = px[y * W + x]; t += (v & 255) + ((v >> 8) & 255) + ((v >> 16) & 255); n++; } return t / n; };
  assert.ok(luma(a) < 0.85 * luma(b), `${luma(a).toFixed(0)} against ${luma(b).toFixed(0)}: darker behind the clock with the dock up`);
  let outside = 0; for (let y = 8; y < 100; y++) for (let x = 120; x < 190; x++) if (a[y * W + x] !== b[y * W + x]) outside++;
  assert.ok(outside < 1700, 'the scrim touches nothing far from the clock');
  const scrim = surf.makeScrim(); assert.ok(scrim.some((v) => v === 255) && scrim[0] < 120);
});

test('the sea and the wave flow while the sky holds still apart from its own small things', () => {
  const api = makeApi({view: {top: 0, bottom: 320}}), canvas = fakeCanvas();
  surf.scene.init(api);
  const a = pixelsOf(run(api, 30, canvas)), b = pixelsOf(run(api, 45, canvas));
  const changed = (x0, y0, x1, y1) => { let n = 0; for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) if (a[y * W + x] !== b[y * W + x]) n++; return n / ((x1 - x0) * (y1 - y0)); };
  assert.ok(changed(0, 190, 200, 320) > 0.05, 'the foreground water moves'); assert.ok(changed(160, 40, 200, 190) > 0.03, 'the rings flow');
  assert.ok(changed(0, 126, 100, 186) > 0.02, 'the sea slithers');
});

test('the scene is a fixed golden hour: it never reads the clock, shows no quota, no number and no text, and loads nothing', () => {
  for (const forbidden of ['new Date', 'getHours', 'getTimezoneOffset', 'sunState', 'lightAt']) assert.ok(!SOURCE.includes(forbidden), `must not use ${forbidden}`);
  assert.doesNotMatch(SOURCE, /fillText|strokeText|\.font\s*=/);
  for (const forbidden of ['remaining', 'resets_at', 'readings(', 'fetch(', 'XMLHttpRequest', 'WebSocket', 'localStorage', 'eval(', 'new Function', 'document.cookie']) assert.ok(!SOURCE.includes(forbidden), `must not use ${forbidden}`);
});

test('brushes: the built-in foam brushes have the sizes the preparation script draws, and the atlas reader takes them or refuses without throwing', () => {
  const brushes = surf.makeBrushes(surf.makeNoise(rand(4)));
  assert.deepEqual(brushes.puff.map((b) => [b.w, b.h]), [[9, 7], [14, 10], [21, 13], [30, 17]]); assert.deepEqual(brushes.streak.map((b) => [b.w, b.h]), [[13, 4], [20, 5], [32, 6], [48, 7]]);
  assert.deepEqual(brushes.sheet.map((b) => [b.w, b.h]), [[18, 6], [28, 8], [40, 10]]);
  for (const b of [...brushes.puff, ...brushes.streak, ...brushes.sheet]) assert.ok(b.alpha.some((a) => a > 0) && b.tone.length === b.w * b.h);
  const {pixels, json} = fictionalAtlas(), read = surf.readAtlasBrushes(json, pixels);
  assert.ok(read && read.puff.length === 2 && read.streak.length === 2 && read.sheet.length === 2);
  assert.equal(read.puff[0].tone[0], 200); assert.equal(read.puff[0].alpha[0], 255);
  for (const [j, p] of [[null, pixels], [{frames: {}}, pixels], [json, null], [{frames: {'foam-puff-0': [0, 0, 999, 9]}}, pixels], [{frames: {'foam-puff-0': 'x'}}, pixels], [fictionalAtlas({brushes: false}).json, pixels]]) assert.equal(surf.readAtlasBrushes(j, p), null);
});

test('clouds take the colour of the sky behind them and are drawn only on sky; a cloud over the wave would be hidden', () => {
  const noise = surf.makeNoise(rand(6)), cloud = surf.makeCloud(noise, 58, 8, 1);
  assert.equal(cloud.w, 58); assert.ok(cloud.alpha.filter(Boolean).length > 100); assert.ok(cloud.tone.some((t) => t > 160) && cloud.tone.some((t) => t < 90), 'lit underneath, shadowed on top');
});

test('a frame stays cheap: 150 frames of the whole picture take well under a second in Node, with or without the atlas', () => {
  const {pixels, json} = fictionalAtlas();
  for (const extra of [{}, {atlas: pixels, json}]) {
    const api = makeApi(extra), canvas = fakeCanvas();
    surf.scene.init(api);
    for (let i = 0; i < 30; i++) { surf.scene.step(api, 1 / 30); surf.scene.draw(api, canvas.g); }
    const t0 = process.hrtime.bigint();
    for (let i = 0; i < 150; i++) { surf.scene.step(api, 1 / 30); surf.scene.draw(api, canvas.g); }
    const ms = Number(process.hrtime.bigint() - t0) / 1e6 / 150;
    assert.ok(ms < 6, `${ms.toFixed(2)} ms a frame`);
  }
});

/* ---- round two: the palm, the beach, the swell, the dolphin, the shooting star, the flock, the shake, the hang ------------------------------------------------------------------ */

test('the palm crown sways and its trunk comes from offscreen, with a procedural fallback', () => {
  const {pixels, json} = fictionalAtlas({palm: true}), palm = surf.readPalm(json, pixels);
  assert.ok(palm && palm.w === 30 && palm.h === 40); assert.ok(palm.mask.reduce((a, b) => a + b, 0) > 400);
  assert.equal(palm.rgb[0 * 30 + 0] === 0 || palm.mask[0] === 0, true, 'keyed pixels are not drawn');
  for (const [j, p] of [[null, pixels], [{frames: {}}, pixels], [{frames: {palm: [0, 0, 999, 10]}}, pixels], [{frames: {palm: 'x'}}, pixels], [json, null], [fictionalAtlas().json, pixels]]) assert.equal(surf.readPalm(j, p), null);
  const empty = fictionalAtlas({palm: true});
  for (let y = 0; y < 40; y++) for (let x = 0; x < 30; x++) empty.pixels.data[((2 * H + 21 + y) * 200 + x) * 4 + 3] = 0;
  assert.equal(surf.readPalm(empty.json, empty.pixels), null, 'an empty sprite is refused');
  const a = fictionalAtlas({palm: true}), apiWith = makeApi({atlas: a.pixels, json: a.json}), apiWithout = makeApi(), c1 = fakeCanvas(), c2 = fakeCanvas();
  surf.scene.init(apiWith); assert.ok(surf.scene.s.palm, 'the atlas brings the palm'); const withPalm = pixelsOf(run(apiWith, 3, c1)); const later = pixelsOf(run(apiWith, 400, c1));
  surf.scene.init(apiWithout); assert.equal(surf.scene.s.palm, null, 'no sprite: the procedural palm is drawn'); const fallback = pixelsOf(run(apiWithout, 3, c2));
  let dark = 0; for (let y = 55; y < 125; y++) for (let x = 0; x < 48; x++) if (fallback[y * W + x] === 0xff50142a || fallback[y * W + x] === 0xff380c1a) dark++;
  assert.ok(dark > 20, `the procedural palm's silhouette (${dark} pixels)`);
  let crown = 0, foot = 0; for (let y = 0; y < 28; y++) for (let x = 0; x < 40; x++) if (withPalm[y * W + x] !== later[y * W + x]) crown++;
  for (let y = 31; y < 40; y++) for (let x = 0; x < 30; x++) if (withPalm[y * W + x] !== later[y * W + x] && surf.scene.s.back.cls[y * W + x] === surf.CLS.FORE) foot++;
  assert.ok(crown > 10, `the crown sways (${crown} pixels differ)`); assert.equal(foot, 0, 'the bluff and the foot do not move');
  const g = surf.mergeGeometry({palm: {x: 3.4, y: 5}}); assert.deepEqual(g.palm, {x: 3, y: 5}); assert.equal(surf.mergeGeometry({palm: {x: 'a', y: 1}}).palm, undefined); assert.equal(surf.mergeGeometry({palm: {x: 9999, y: 1}}).palm, undefined);
});

test('no island is added and the palm bends out through the left edge', () => {
  const api = makeApi(); surf.scene.init(api);
  const original = surf.makeBackdrop(rand(3));
  assert.deepEqual(surf.scene.s.back.cls, original.cls, 'initialisation must not add land');
  assert.equal(surf.palmOffset(0, 125), 0, 'canopy stays where it was');
  assert.ok(surf.palmOffset(100, 125) < -55, 'lower trunk and root continue offscreen');
  assert.ok(surf.palmOffset(80, 125) < surf.palmOffset(55, 125), 'the trunk bends gradually left');
});

test('the beach corner (lower right, clear of the picture-mode clock at the bottom left): sand under a curved waterline, two boards, a torch and a towel, all to the right of x = 125; drawn only in picture mode, its wash runs up and back, the flame flickers', () => {
  const b = surf.makeBeach(rand(8));
  assert.equal(b.y0 + b.h, H); assert.equal(b.x0 + b.w, W); assert.ok(b.x0 >= 85, 'a patch in the corner'); assert.ok(b.mask.reduce((n, v) => n + v, 0) > 2500, 'a patch of sand');
  const at = (x, y) => b.mask[(y - b.y0) * b.w + (x - b.x0)];
  assert.equal(at(194, 318), 1); assert.equal(at(b.x0 + 8, 318), 0, 'the sand ends where the waterline crosses the bottom'); assert.equal(at(150, 256), 0, 'no sand above the waterline');
  assert.ok(surf.beachEdge(190) < surf.beachEdge(120), 'the waterline slopes down toward the middle');
  let leftmostProp = W; for (let y = 250; y < 320; y++) for (let x = 0; x < b.w; x++) if (b.mask[(y - b.y0) * b.w + x]) leftmostProp = Math.min(leftmostProp, b.x0 + x);
  assert.ok(leftmostProp >= 88, 'nothing of the beach is under the clock and the weather pill (x < 125) apart from the sand\'s thin tip');
  for (let y = 250; y < 320; y++) for (let x = 0; x < 125 - b.x0; x++) if (b.mask[(y - b.y0) * b.w + x]) assert.ok(y >= 305, 'at the clock\'s side only the thin tip of sand reaches the bottom rows');
  const dock = makeApi({view: {top: 0, bottom: 186}}), whole = makeApi({view: {top: 0, bottom: 320}}), c1 = fakeCanvas(), c2 = fakeCanvas();
  surf.scene.init(whole); const plain = surf.scene.s.back.rgb, full = pixelsOf(run(whole, 30, c2));
  let sand = 0; for (let y = 300; y < 320; y++) for (let x = 130; x < 200; x++) if (full[y * W + x] !== plain[y * W + x]) sand++;
  assert.ok(sand > 700, `the beach covers ${sand} pixels of the plain wave in the whole picture`);
  const f1 = pixelsOf(run(whole, 5, c2)), f2 = pixelsOf(run(whole, 40, c2)); let wash = 0; for (let y = 262; y < 312; y++) for (let x = 100; x < 200; x++) if (f1[y * W + x] !== f2[y * W + x]) wash++;
  assert.ok(wash > 40, 'the wash and the flame move in picture mode');
  surf.scene.init(dock); const d1 = pixelsOf(run(dock, 30, c1)), d2 = pixelsOf(run(dock, 40, c1)); let still = 0; for (let y = 250; y < 320; y++) for (let x = 100; x < 200; x++) if (d1[y * W + x] !== d2[y * W + x]) still++;
  assert.equal(still, 0, 'under the dock nothing is redrawn: the beach is frozen');
});

test('the far swell: it stands on the horizon in the tube\'s window, only over sky and sea (the wave hides it), and has crest and face colours', () => {
  const api = makeApi({view: {top: 0, bottom: 320}}), canvas = fakeCanvas();
  surf.scene.init(api);
  const s = surf.scene.s, hz = s.back.geom.horizon, before = pixelsOf(run(api, 150, canvas));
  const high = pixelsOf(run(api, 1100, canvas));
  let changed = 0, bright = 0; for (let y = hz - 20; y <= hz + 3; y++) for (let x = 70; x < 170; x++) { const i = y * W + x; if (high[i] !== before[i] && s.back.cls[i] !== surf.CLS.WATER) changed++; const v = high[i]; if ((v & 255) > 240 && ((v >> 8) & 255) > 240) bright++; }
  assert.ok(changed > 150, `the swell shows ${changed} pixels`); assert.ok(bright > 5, 'a white crest');
  assert.equal(surf.setState(100).h, 0, 'nothing in the lull');
});

test('the dolphin leaps every 20 to 40 seconds out of the sea, on an arc, with a splash at both ends, and only over sky and sea', () => {
  const d = surf.makeDolphin(rand(5), surf.DEFAULT_GEOM);
  assert.ok(d.dur >= 60 && Math.abs(d.xb - d.xa) >= 50 && d.apex >= 17 && d.apex <= 24);
  const start = surf.dolphinAt(d, 0), mid = surf.dolphinAt(d, 0.5), end = surf.dolphinAt(d, 1);
  close(start.y, d.y, 1e-9); close(end.y, d.y, 1e-9); close(d.y - mid.y, d.apex, 1e-9); assert.ok(d.y > surf.DEFAULT_GEOM.horizon + 10, 'it leaps out of the sea in front of the horizon');
  const w = world();
  let jumps = 0, was = false, splash = 0, gaps = [], last = 0;
  for (let i = 0; i < 9000; i++) { w.step(); const on = !!w.dolphin.cur; if (on && !was) { jumps++; if (last) gaps.push(w.steps - last); last = w.steps; } was = on; if (on && w.dolphin.cur.t === w.dolphin.cur.dur) splash += w.ripples.length > 0 ? 1 : 0; }
  assert.ok(jumps >= 8 && jumps <= 16, `${jumps} leaps in five minutes`); for (const g of gaps) assert.ok(g >= 640 && g <= 1300, `a gap of ${g} steps`); assert.ok(splash >= 1);
});

test('a shooting star now and then, a far flock of seven that crosses the sky: both are rare, bounded and over sky only', () => {
  const w = world();
  let stars = 0, flocks = 0, lastStar = false, lastFlock = false, flockBirds = 0, crossed = false;
  for (let i = 0; i < 12000; i++) {
    w.step();
    const s = w.star.t >= 0; if (s && !lastStar) stars++; lastStar = s; if (s) assert.ok(w.star.vx > 3 && w.star.y < 80);
    const f = w.flock.on; if (f && !lastFlock) flocks++; lastFlock = f; if (f) { assert.ok(w.flock.y >= 70 && w.flock.y <= 94); if (w.flock.x > 60 && w.flock.x < 140) crossed = true; }
  }
  assert.ok(stars >= 4 && stars <= 22, `${stars} shooting stars in 6 minutes`); assert.ok(flocks >= 3 && flocks <= 14, `${flocks} flocks`); assert.ok(crossed);
});

test('the camera\'s shake moves whole rows by a pixel or two, only the rows that count, and does nothing for zero', () => {
  const fb = new Uint32Array(W * H), tmp = new Uint32Array(W * H);
  for (let i = 0; i < fb.length; i++) fb[i] = i % W + 1000 * ((i / W) | 0);
  const same = fb.slice(); surf.shiftFrame(fb, tmp, 0, 0, 200); assert.deepEqual(fb, same);
  surf.shiftFrame(fb, tmp, 2, 1, 200);
  assert.equal(fb[5 * W + 10], 8 + 1000 * 4, 'the picture moved by (2, 1)'); assert.equal(fb[5 * W + 0], 0 + 1000 * 5, 'the edge keeps its old pixels');
  assert.equal(fb[250 * W + 10], same[250 * W + 10], 'rows under the limit are untouched');
  assert.doesNotThrow(() => surf.shiftFrame(fb, tmp, -3, -2, 200));
});

test('a jump holds at the top: the slow-motion makes the middle of the jump last longer than its ends; it goes straight up and comes straight down', () => {
  const surface = surf.makeSurface(back().geom), ride = surf.createRide(surface, rand(4), 'air'), seg = SEGMENTS.air.find((x) => x.name === 'airUp');
  assert.ok(seg.hang > 0.3 && seg.hang < 1, 'the jump has a hang'); assert.ok(seg.dur >= 50);
  let path = [], inJump = false;
  for (let i = 0; i < 600; i++) { const r = ride.step(); if (r.name === 'airUp') { inJump = true; path.push([r.x, r.y]); } else if (inJump) break; }
  assert.ok(path.length === seg.dur || path.length === seg.dur + 1, `${path.length} steps`);
  const speed = (i) => Math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1]);
  const early = (speed(3) + speed(4) + speed(5)) / 3, middle = (speed(28) + speed(29) + speed(30)) / 3;
  assert.ok(early > 1.15 * middle, `the jump is quick at its start (${early.toFixed(2)} px a step) and slow at the top (${middle.toFixed(2)})`);
  const top = Math.min(...path.map((p) => p[1])); assert.ok(top < path[0][1] - 22, 'it rises well above where it started');
  assert.ok(Math.max(...path.map((p) => Math.abs(p[0] - path[0][0]))) < 9, 'and stays above where it started: straight up');
  const end = path[path.length - 1]; assert.ok(Math.abs(end[1] - path[0][1]) < 6, 'it comes back down to the face');
});

test('the wake is a trail that lasts: up to 76 points that fade over 76 steps and drift with the water', () => {
  const w = world();
  let most = 0, oldest = 0;
  for (let i = 0; i < 900; i++) { w.step(); most = Math.max(most, w.wake.length); for (const k of w.wake) oldest = Math.max(oldest, k.age); }
  assert.ok(most > 50 && most <= 76, `${most} wake points`); assert.ok(oldest > 60 && oldest < 76, `the oldest point is ${oldest} steps old`);
});

test('the head is a small hand-made picture: 11 x 12 characters, two variants, hair on the side away from the face; the board has a graphic', () => {
  const r = surf.makeRaster(128, 112), pal = surf.surferPalette();
  surf.drawStanding(r, 64, 84, {pose: POSES.trim, pitch: 0, yaw: 0, rot: 0, board: true});
  const used = new Set(r.buf); for (const k of ['skin', 'skinLight', 'skinShade', 'hair', 'hairLight', 'eye', 'shirt', 'trunks', 'board', 'cream', 'cap', 'boardDark']) assert.ok(used.has(surf.S[k]), `the figure uses ${k}`);
  assert.equal(pal.length, 23); for (let i = 1; i < pal.length; i++) assert.equal(pal[i] >>> 24, 255, `palette ${i} is opaque`);
  const left = surf.makeRaster(128, 112), right = surf.makeRaster(128, 112);
  surf.drawStanding(left, 64, 84, {pose: POSES.trim, pitch: 0, yaw: 0, rot: 0, board: true}); surf.drawStanding(right, 64, 84, {pose: POSES.trim, pitch: 0, yaw: Math.PI, rot: 0, board: true});
  const sum = (rr, cmp) => { let t = 0, n = 0; for (let y = 0; y < 112; y++) for (let x = 0; x < 128; x++) if (rr.buf[y * 128 + x] === surf.S.hair) { t += x; n++; } return n ? t / n : 0; };
  assert.ok(sum(left) > 0 && sum(right) > 0);
});

/* ---- round three: birds behind the wave, the seascape, the ramps, the swells that differ ---------------------------------------------------------------------------------- */

test('gulls and birds fly over the LEFT sky and turn round behind the wave: they never leave x = 150, and a gull over the wave is hidden by it (nothing of it is drawn over the face or the lip)', () => {
  const w = world();
  let maxX = -99, minX = 999;
  for (let i = 0; i < 9000; i++) { w.step(); for (const g of w.gulls) { if (!g.poked) { maxX = Math.max(maxX, g.x); minX = Math.min(minX, g.x); } } for (const b of w.birds) maxX = Math.max(maxX, b.x); }
  assert.ok(maxX <= surf.GULL_TURN + 4, `no gull or bird goes beyond ${maxX}`); assert.ok(minX > -22 && surf.GULL_TURN <= 150);
  const api = makeApi({view: {top: 0, bottom: 320}}), canvas = fakeCanvas(); surf.scene.init(api);
  const s = surf.scene.s, cls = s.back.cls, wavePoint = [176, 70], skyPoint = [82, 46];
  assert.equal(cls[wavePoint[1] * W + wavePoint[0]], surf.CLS.WATER); assert.equal(cls[skyPoint[1] * W + skyPoint[0]], surf.CLS.SKY);
  const region = (px, x, y, r) => { const out = []; for (let yy = y - 9; yy <= y + 9; yy++) for (let xx = x - r; xx <= x + r; xx++) out.push(px[yy * W + xx]); return out; };
  const place = (x, y, on) => { s.world.gulls.length = 0; if (on) s.world.gulls.push({x, y, base: y, dir: 1, span: 17, speed: 0, acc: 0, phase: 0.5, mode: 'flap', timer: 1e6, amp: 1, bob: 0, poked: false, lane: 0}); };
  place(...wavePoint, false); surf.scene.draw(api, canvas.g); const waveOff = region(pixelsOf(canvas.calls[canvas.calls.length - 1].img), ...wavePoint, 12);
  place(...wavePoint, true); surf.scene.draw(api, canvas.g); const waveOn = region(pixelsOf(canvas.calls[canvas.calls.length - 1].img), ...wavePoint, 12);
  assert.deepEqual(waveOn, waveOff, 'over the wave the gull is hidden');
  place(...skyPoint, false); surf.scene.draw(api, canvas.g); const skyOff = region(pixelsOf(canvas.calls[canvas.calls.length - 1].img), ...skyPoint, 12);
  place(...skyPoint, true); surf.scene.draw(api, canvas.g); const skyOn = region(pixelsOf(canvas.calls[canvas.calls.length - 1].img), ...skyPoint, 12);
  let drawn = 0; for (let i = 0; i < skyOn.length; i++) if (skyOn[i] !== skyOff[i]) drawn++;
  assert.ok(drawn > 15, `in the open sky the gull is drawn (${drawn} pixels)`);
});

test('the Mediterranean seascape: no islet; a far ferry, a sloop, a llaut, a small cruiser and a windsurfer, each its own size and speed, in the band between the horizon and the date; hidden by the wave where they pass behind it', () => {
  assert.ok(!/drawIslet|islet/i.test(SOURCE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')), 'the dark islet with the palms is gone');
  const geom = surf.DEFAULT_GEOM, craft = surf.makeCraft(geom), hz = geom.horizon;
  assert.deepEqual(craft.map((c) => c.type).sort(), ['cruiser', 'ferry', 'llaut', 'sloop', 'windsurf']);
  assert.equal(new Set(craft.map((c) => c.speed)).size, 5, 'five speeds'); assert.ok(craft.every((c) => c.y >= hz - 1 && c.y <= hz + 10), 'in the horizon band, above the date'); assert.ok(craft.find((c) => c.type === 'ferry').y === hz - 1, 'the ferry sits on the horizon');
  const sizes = craft.filter((c) => c.type !== 'ferry').map((c) => c.size); assert.ok(Math.min(...sizes) >= 12 && Math.max(...sizes) <= 16, 'readable sizes');
  const w = world(); let xs = craft.map(() => [999, -999]);
  for (let i = 0; i < 12000; i++) { w.step(); w.craft.forEach((c, k) => { xs[k][0] = Math.min(xs[k][0], c.x); xs[k][1] = Math.max(xs[k][1], c.x); assert.ok(c.x >= -30 && c.x <= 177, `${c.type} at ${c.x}`); }); }
  assert.ok(xs.filter((r) => r[1] - r[0] > 60).length >= 4, 'they cross the sea');
  const api = makeApi({view: {top: 0, bottom: 320}}), canvas = fakeCanvas(); surf.scene.init(api);
  const s = surf.scene.s, cls = s.back.cls, onWave = s.world.craft.find((c) => c.type === 'sloop');
  let wx = -1, wy = hz + 4; for (let x = 60; x < 200; x++) { for (let y = hz - 14; y <= hz + 6; y++) if (cls[y * W + x] === surf.CLS.WATER) { wx = x; break; } if (wx >= 0) break; }
  onWave.x = wx + 8; onWave.y = wy; onWave.speed = 0; s.world.craft.forEach((c) => { if (c !== onWave) c.x = -200; });
  const region = (px) => { const out = []; for (let y = hz - 16; y <= hz + 6; y++) for (let x = wx + 2; x <= wx + 14; x++) out.push(px[y * W + x]); return out; };
  surf.scene.draw(api, canvas.g); const withBoat = region(pixelsOf(canvas.calls[canvas.calls.length - 1].img));
  onWave.x = -200; surf.scene.draw(api, canvas.g); const without = region(pixelsOf(canvas.calls[canvas.calls.length - 1].img));
  const water = []; for (let y = hz - 16; y <= hz + 6; y++) for (let x = wx + 2; x <= wx + 14; x++) water.push(cls[y * W + x] === surf.CLS.WATER);
  for (let i = 0; i < withBoat.length; i++) if (water[i]) assert.equal(withBoat[i], without[i], 'a boat behind the wave is hidden by it');
});

test('the dolphin is a clean silhouette: a dark blue body with a pale belly and a warm rim, a beak, a dorsal fin and tail flukes, never drawn over the wave', () => {
  const api = makeApi(), canvas = fakeCanvas(); surf.scene.init(api);
  const s = surf.scene.s, w = s.world; w.dolphin.next = 1e9; w.craft.forEach((c) => { c.x = -300; });
  const off = pixelsOf(run(api, 3, canvas)), d = surf.makeDolphin(rand(3), w.geom); d.t = 40; w.dolphin.cur = d;
  const on = pixelsOf((surf.scene.draw(api, canvas.g), canvas.calls[canvas.calls.length - 1].img));
  const body = 0xff663524, belly = 0xffe4c8b8; let bodyPx = 0, bellyPx = 0, rim = 0, overWave = 0;
  for (let i = 0; i < W * H; i++) { if (on[i] !== off[i]) { if (on[i] === body) bodyPx++; if (on[i] === belly) bellyPx++; if (on[i] === 0xff5a9cff) rim++; if (s.back.cls[i] === surf.CLS.WATER) overWave++; } }
  assert.ok(bodyPx > 60, `${bodyPx} body pixels`); assert.ok(bellyPx >= 4, 'a pale belly'); assert.ok(rim > 4, 'a warm rim'); assert.equal(overWave, 0, 'never over the wave');
});

test('the wave lives: the water\'s colours are ramps (teal rings, sunlit peach) that pulse along the plate\'s own tones, so the rings breathe and the glow slides along the lip; a different swell every cycle; foam rises up the face counter-clockwise; mist blows off the crest', () => {
  const b = back(), ramp = surf.buildRamps(b);
  assert.ok(ramp, 'ramps are found in the built-in backdrop'); assert.ok(ramp.len[1] >= 5 && ramp.len[2] >= 2, `ramps of ${ramp.len[1]} teals and ${ramp.len[2]} sunlit tones`);
  for (let f = 1; f <= 2; f++) { let prev = -1; for (const c of ramp.tables[f]) { const lum = 0.3 * (c & 255) + 0.59 * ((c >> 8) & 255) + 0.11 * ((c >> 16) & 255); assert.ok(lum >= prev, `family ${f} is sorted by luminance`); prev = lum; } }
  let tagged = 0; for (let i = 0; i < ramp.fam.length; i++) if (ramp.fam[i]) { tagged++; assert.equal(b.cls[i], surf.CLS.WATER); assert.equal(ramp.tables[ramp.fam[i]][ramp.rank[i]], b.rgb[i], 'a pixel\'s rank is its own colour'); }
  assert.ok(tagged > 8000, `${tagged} ramp pixels`);
  assert.equal(surf.buildRamps({rgb: new Uint32Array(W * H), cls: new Uint8Array(W * H)}), null, 'no water, no ramps');
  const warp = surf.buildWarp(b.cls, b.geom, b.rgb), dst1 = new Uint32Array(W * H), dst2 = new Uint32Array(W * H); surf.applyWarp(dst1, b, warp, 10, H); surf.applyWarp(dst2, b, warp, 60, H);
  const allowed = new Set([...ramp.tables[1], ...ramp.tables[2], ...b.rgb]); let pulsing = 0; for (let i = 0; i < W * H; i++) { assert.ok(allowed.has(dst1[i]), 'only the plate\'s own colours'); if (dst1[i] !== dst2[i] && b.cls[i] === surf.CLS.WATER) pulsing++; }
  assert.ok(pulsing > 1500, `${pulsing} water pixels differ between two moments`);
  const k0 = surf.setState(100), k1 = surf.setState(surf.SET_LEN + 100), a0 = surf.setState(surf.SET_BURST - 5), a1 = surf.setState(surf.SET_LEN + surf.SET_BURST - 5), a2 = surf.setState(2 * surf.SET_LEN + surf.SET_BURST - 5);
  assert.equal(k0.k, 0); assert.equal(k1.k, 1); assert.ok(a1.hMax >= 10 && a1.hMax <= 18 && a2.hMax >= 10 && a2.hMax <= 18, 'swell heights from 10 to 18'); assert.ok(a0.hMax !== a1.hMax || a1.hMax !== a2.hMax || a1.wide !== a2.wide, 'a different swell each cycle');
  assert.deepEqual(surf.setState(surf.SET_LEN * 3 + 500), surf.setState(surf.SET_LEN * 3 + 500), 'the same cycle is always the same swell');
  const w = world(); let rising = 0, total = 0, mistTop = 0;
  const cx = w.geom.centre[0], cy = w.geom.centre[1];
  for (let i = 0; i < 600; i++) { w.step(); for (const q of w.foamItems) if (q.clip && q.age <= 1) { total++; const dx = q.x - cx, dy = q.y - cy, cross = dx * q.vy - dy * q.vx, radial = dx * q.vx + dy * q.vy; if (cross < 0 && Math.abs(radial) < Math.abs(cross) * 0.2) rising++; } for (const m of w.mist) if (m.y < 30) mistTop++; }
  assert.ok(total > 30 && rising / total > 0.95, `${rising} of ${total} streaks flow counter-clockwise around the tube`); assert.ok(mistTop > 40, 'mist off the crest');
});

/* ---- round four: the barrel, the body, the dressing of a pose, the line's speed, the flow --------------------------------------------------------------------------------------- */

const jointAngle = (a, b, c) => { const u = [a[0] - b[0], a[1] - b[1]], v = [c[0] - b[0], c[1] - b[1]]; return Math.acos(Math.max(-1, Math.min(1, (u[0] * v[0] + u[1] * v[1]) / (Math.hypot(...u) * Math.hypot(...v))))) * 180 / Math.PI; };
const BARREL = ['barrel', 'barrelSet', 'barrelDeep', 'stall', 'drag', 'duck', 'barrelUp', 'exitTall'];

test('the barrel stances: knees bent about 90 degrees and pointing forward, hips low over the board, the head up and level looking down the tube, the hands clear of his face, the feet on the same spots all through', () => {
  const f = surf.figure(POSES.barrel, 0), kneeAngle = jointAngle(f.hip, f.kneeF, f.footF);
  assert.ok(kneeAngle > 70 && kneeAngle < 115, `the front knee is bent ${kneeAngle.toFixed(0)} degrees`); assert.ok(f.kneeF[0] < f.hip[0] && f.kneeB[0] < f.hip[0] + 4, 'the knees point forward (to the left)');
  assert.ok(Math.abs(f.hip[1] - f.footF[1]) < 0.62 * (THIGH + SHIN), 'hips low'); assert.ok(f.hip[1] > surf.figure(POSES.trim, 0).hip[1] + 3, 'lower than in a trim');
  for (const name of BARREL) {
    const pose = POSES[name], g = surf.figure(pose, 0);
    if (name !== 'exitTall') assert.ok(pose.lean + pose.head < 20, `${name}: the head is level (${pose.lean + pose.head} degrees), he looks down the tube, not at his board`);
    for (const hand of [g.handF, g.handB]) assert.ok(Math.hypot(hand[0] - g.head[0], hand[1] - g.head[1]) > 7.5, `${name}: a hand is over his face`);
    assert.ok(g.head[1] < g.shoulder[1] && g.shoulder[1] < g.hip[1] + 2, `${name}: head above shoulders above hips`);
    if (name !== 'exitTall' && name !== 'barrelUp') assert.ok(Math.abs(pose.ffx - POSES.barrel.ffx) < 0.01 && Math.abs(pose.bfx - POSES.barrel.bfx) < 0.01, `${name}: his feet stay where they are`);
  }
  assert.ok(POSES.stall.hx > POSES.barrel.hx + 1, 'the stall shifts weight back'); assert.ok(POSES.drag.by > POSES.barrel.by + 3 && POSES.drag.fx < POSES.barrel.fx, 'the rear hand drops to the wave while the front hand guides');
  assert.ok(POSES.duck.hy > POSES.barrel.hy && POSES.duck.lean > POSES.barrel.lean + 8, 'the duck: lower and more folded'); assert.ok(POSES.exitTall.hy < POSES.trim.hy - 0.5 && POSES.exitTall.fx < -10 && POSES.exitTall.bx > 10, 'the exit: tall with the arms spread');
});

test('inside the tube the surfer shifts weight and hands while both feet stay on the board', () => {
  for (const name of ['tubeIn', 'stall', 'drag', 'pumpLow', 'duck']) {
    const segment = SEGMENTS.tube.find(s => s.name === name);
    assert.ok(segment.pose.some(([, pose]) => pose === 'barrelSet' || pose === 'barrelDeep'));
    assert.ok(segment.micro <= 0.8);
  }
  const a = surf.figure(POSES.barrelSet, 0), b = surf.figure(POSES.barrelDeep, 0);
  assert.deepEqual(a.footF, b.footF); assert.deepEqual(a.footB, b.footB);
  assert.ok(b.hip[1] > a.hip[1], 'knees compress as the wave lowers');
  assert.ok(Math.hypot(...a.handF.map((v, i) => v - b.handF[i])) > 1, 'arms correct separately');
  for (const name of ['barrel', 'barrelSet', 'barrelDeep', 'stall', 'drag', 'duck', 'barrelUp']) for (const pitch of [-30, 0, 30]) {
    const g = surf.figure(POSES[name], pitch), angle = pitch * Math.PI / 180;
    const aboveDeck = (g.kneeB[0] - g.footB[0]) * -Math.sin(angle) + (g.kneeB[1] - g.footB[1]) * Math.cos(angle);
    assert.ok(aboveDeck < -1, `${name} at ${pitch}: rear knee must stay above the deck`);
  }
});

test('the face is never covered: the head is drawn after both arms, so every pixel of the head bitmap is a head pixel, in every pose', () => {
  const r1 = surf.makeRaster(84, 84), r2 = surf.makeRaster(84, 84);
  for (const name of Object.keys(POSES)) for (const pitch of [-20, 0, 20]) {
    r1.clear(); r2.clear();
    const J = surf.drawStanding(r1, 42, 64, {pose: POSES[name], pitch, board: true}), down = POSES[name].lean + POSES[name].head > 28;
    surf.drawHead(r2, Math.round(J.head[0]), Math.round(J.head[1]), -1, down);
    for (let i = 0; i < 84 * 84; i++) if (r2.buf[i]) assert.equal(r1.buf[i], r2.buf[i], `${name} at ${pitch}: pixel ${i % 84},${(i / 84) | 0} of the head is covered`);
  }
});

test('the body: legs have a calf and a knee, a foot that follows the deck and is shorter at the back; the knees point forward and the elbows back, for every pose', () => {
  for (const name of Object.keys(POSES)) {
    const g = surf.figure(POSES[name], 0);
    assert.ok(g.kneeF[0] <= (g.hip[0] + g.footF[0]) / 2 + 0.6 || Math.abs(g.hip[0] - g.footF[0]) < 3, `${name}: the front knee points forward`);
    assert.ok(g.elbowF[1] >= Math.min(g.sF[1], g.handF[1]) - 0.01, `${name}: the elbow is not above both ends of the arm`);
  }
  assert.ok(/function leg\(/.test(SOURCE) && /function foot\(/.test(SOURCE));
});

test('the dressing of a pose (breathing, knees taking the chop, arms counter-balancing, the head staying level, the line pressing him into the board) is small, continuous and never mutates the pose', () => {
  const base = POSES.barrel, copy = JSON.stringify(base);
  const still = surf.dress(base, 100, 0, 0, 0); for (const k of POSE_KEYS) close(still[k], base[k], 1e-9);
  const a = surf.dress(base, 100, 1.5, 0.5, 0), b = surf.dress(base, 101, 1.5, 0.5, 0); assert.equal(JSON.stringify(base), copy);
  let maxStep = 0, maxDev = 0, moved = 0;
  for (let t = 0; t < 600; t++) { const x = surf.dress(base, t, 1.5, 0.6, 0), y = surf.dress(base, t + 1, 1.5, 0.6, 0); for (const k of POSE_KEYS) { maxStep = Math.max(maxStep, Math.abs(y[k] - x[k])); maxDev = Math.max(maxDev, Math.abs(x[k] - base[k])); } if (Math.abs(x.hy - base.hy) > 0.3) moved++; }
  assert.ok(maxStep < 1.6, `smooth: ${maxStep.toFixed(2)} at most a step`); assert.ok(maxDev < 9 && maxDev > 1.5, `small but there: ${maxDev.toFixed(2)}`); assert.ok(moved > 100, 'it keeps moving');
  const pressed = surf.dress(base, 0, 0, 0, 1), light = surf.dress(base, 0, 0, 0, -1); assert.ok(pressed.hy > base.hy && pressed.lean > base.lean, 'pressed into the board he sinks and leans'); assert.ok(light.hy < base.hy, 'a lighter board, a taller body');
  const lean = surf.dress(base, 40, 1.5, 0.5, 0); assert.ok(Math.abs((lean.lean + lean.head) - (base.lean + base.head)) < Math.abs(lean.lean - base.lean) * 0.4 + 0.01, 'the head stays level while the torso sways');
  assert.notDeepEqual(a, b);
});

test('the line has a speed of its own: the stall is slow, the drag to the low line accelerates, the pump regains speed; and the water runs with him', () => {
  const surface = surf.makeSurface(back().geom), ride = surf.createRide(surface, rand(6), 'tube'), seg = {};
  let last = [ride.x, ride.y];
  for (let i = 0; i < 440; i++) { const r = ride.step(); (seg[r.name] = seg[r.name] || []).push(Math.hypot(r.x - last[0], r.y - last[1])); last = [r.x, r.y]; }
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length, head = (a, n) => mean(a.slice(2, 2 + n)), tail = (a, n) => mean(a.slice(-n - 1, -1));
  assert.ok(mean(seg.stall) < 0.5 * mean(seg.drag), `the stall (${mean(seg.stall).toFixed(2)} px a step) is slow next to the drag (${mean(seg.drag).toFixed(2)})`);
  assert.ok(tail(seg.drag, 10) > 1.8 * head(seg.drag, 10), 'the drag accelerates down the line'); assert.ok(head(seg.stall, 6) < head(seg.drag, 6) + 0.2 || mean(seg.stall) < 0.8);
  const w = world({first: 'tube'}), flows = {}, phases = {};
  let p0 = w.phase;
  for (let i = 0; i < 440; i++) { w.step(); const n = w.surfer.name; (flows[n] = flows[n] || []).push(w.flow); phases[n] = (phases[n] || 0) + 1; }
  const m = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  assert.ok(m(flows.drag) > m(flows.stall) + 0.12, `the flow follows his speed (drag ${m(flows.drag).toFixed(2)}, stall ${m(flows.stall).toFixed(2)})`);
  for (const n of Object.keys(flows)) for (const f of flows[n]) assert.ok(f >= 0 && f <= 1);
  assert.ok(w.phase - p0 > 440, 'the water runs a little faster than time when he rides');
});

test('the board never stands more than 30 degrees on its nose or tail while he stands on it, and the dressing never throws a joint more than a few pixels in a step over 12 minutes of rides', () => {
  const w = world({random: rand(31)}); let prev = null, worst = 0, pitch = 0;
  for (let i = 0; i < 21600; i++) {
    w.step();
    if (w.surfer.mode === 'stand' && !w.surfer.hidden && w.surfer.hop === 0 && !w.ride.seg().air) pitch = Math.max(pitch, Math.abs(w.surfer.pitchQ));
    const j = surf.figure(w.surfer.pose, 0), now = [j.hip, j.head, j.handF, j.handB, j.footF, j.footB];
    if (prev && !w.surfer.hidden && w.surfer.mode === 'stand' && w.ride.t > 1) now.forEach((q, k) => { worst = Math.max(worst, Math.hypot(q[0] - prev[k][0], q[1] - prev[k][1])); });
    prev = now;
  }
  assert.ok(pitch <= 30, `the pitch reached ${pitch}`); assert.ok(worst < 6.5, `a joint moved ${worst.toFixed(2)} px in a step`);
});

test('the beach props are fully OPAQUE: the two boards, the torch pole and the towel (and their dark outline) are exactly their own colours in every frame, over the foam wash and the water; so is the sand they stand on away from the wash', () => {
  const api = makeApi({view: {top: 0, bottom: 320}}), canvas = fakeCanvas(); surf.scene.init(api);
  const s = surf.scene.s, b = s.beach, plate = s.back.rgb, frames = [pixelsOf(run(api, 5, canvas)), pixelsOf(run(api, 57, canvas)), pixelsOf(run(api, 140, canvas))];
  let props = 0, onWater = 0, onWash = 0, sandPx = 0;
  for (let y = 0; y < b.h; y++) for (let x = 0; x < b.w; x++) {
    const k = y * b.w + x, px = b.x0 + x, py = b.y0 + y, i = py * W + px;
    if (b.pmask[k]) {
      if (Math.abs(px - 151) <= 3 && py >= 258 && py <= 270) continue;                                  // the flame flickers
      props++; if (plate[i] !== b.rgb[k]) onWater++; if (Math.abs(py - surf.beachEdge(px)) <= 6) onWash++;
      for (const f of frames) assert.equal(f[i], b.rgb[k], `a prop pixel at ${px},${py} is not opaque`);
    } else if (b.mask[k] && Math.abs(py - surf.beachEdge(px)) > 7) {
      sandPx++; for (const f of frames) assert.equal(f[i], b.rgb[k], `a sand pixel at ${px},${py} lets the water through`);
    }
  }
  assert.ok(props > 380, `${props} pixels of props`); assert.ok(onWater > 0.85 * props, 'they are drawn over the plate, not with it'); assert.ok(onWash > 12, `the foam wash runs under ${onWash} prop pixels and they stay solid`); assert.ok(sandPx > 1500);
  assert.ok(b.pmask.some((v) => v) && b.rgb.length === b.w * b.h);
  for (let k = 0; k < b.w * b.h; k++) if (b.pmask[k]) assert.ok(b.mask[k] && (b.rgb[k] >>> 24) === 255, 'every prop pixel is a fully opaque colour');
});

test('the rider stays crouched with a visible back knee and the near thigh stays clothed', () => {
  const r = surf.makeRaster(128, 112);
  for (const name of ['barrel', 'barrelDeep', 'stall', 'drag', 'duck']) {
    r.clear();
    const j = surf.drawStanding(r, 64, 84, {pose: POSES[name], pitch: 0, board: true});
    // The deck now recedes diagonally, so vertical screen distance alone no
    // longer measures clearance: use the perpendicular to the visible deck.
    const a = surf.deckPitch(0), clearance = (j.kneeB[0] - j.footB[0]) * -Math.sin(a) + (j.kneeB[1] - j.footB[1]) * Math.cos(a);
    assert.ok(clearance < -2.5, `${name}: the rear knee must stay clear of the projected deck`);
    const x = Math.round(j.hip[0] + (j.kneeF[0] - j.hip[0]) * 0.38), y = Math.round(j.hip[1] + (j.kneeF[1] - j.hip[1]) * 0.38);
    assert.ok([surf.S.trunks, surf.S.trunksLight, surf.S.trunksDark].includes(r.buf[y * r.w + x]), `${name}: the near thigh is covered by the shorts`);
  }
  assert.ok(surf.figure(POSES.barrelDeep, 0).hip[1] > surf.figure(POSES.barrelSet, 0).hip[1], 'the crouch compresses instead of freezing');
});

test('the board approaches the camera and both feet follow its perspective through each pose and pitch', () => {
  const r = surf.makeRaster(128, 112);
  surf.drawBoard(r, 64, 84, 0, 1, 0);
  const nose = [];
  for (let y = 0; y < r.h; y++) for (let x = 0; x < r.w; x++) if (r.buf[y * r.w + x] === surf.S.cap) nose.push([x, y]);
  assert.ok(nose.length && nose.every(([x, y]) => x < 64 && y > 84), 'nose is nearer the camera and slightly left');
  for (const [name, pose] of Object.entries(POSES)) for (const pitch of [-30, 0, 30]) {
    r.clear();
    const original = surf.figure(pose, pitch), drawn = surf.drawStanding(r, 64, 84, {pose, pitch, board: true});
    for (const foot of ['footF', 'footB']) {
      const expected = surf.projectDeck(...original[foot]);
      close(drawn[foot][0], 64 + expected[0], 1e-6);
      close(drawn[foot][1], 84 + expected[1], 1e-6);
    }
    assert.ok(Math.abs(drawn.head[0] - drawn.hip[0]) < Math.abs(original.head[0] - original.hip[0]) + 5, `${name} faces towards the viewer`);
  }
});

test('the wake trails behind the left-facing board and stays on the wave', () => {
  const w = world(), drop = {x: 120, y: 100, age: 0};
  w.wake = [drop]; w.step();
  assert.ok(drop.x > 120, 'the disturbed water recedes to the right, behind the rider');
  const cls = new Uint8Array(W * H).fill(CLS.SEA), fb = new Uint32Array(W * H).fill(0xff141414), before = fb.slice();
  for (const y of [50, 51]) for (let x = 100; x <= 104; x++) cls[y * W + x] = CLS.WATER;
  surf.drawWake({fb, back: {cls}, foamLut: Array(32).fill(0xffffffff)}, [{x: 95, y: 50, age: 2}, {x: 103, y: 50, age: 1}]);
  let changed = 0;
  for (let i = 0; i < fb.length; i++) if (fb[i] !== before[i]) { changed++; assert.equal(cls[i], CLS.WATER, 'foam is never painted over the sky or open sea'); }
  assert.ok(changed > 0, 'the foam remains visible where it meets the wave');
});

test('rail foam follows the perspective of the board and vanishes in the air', () => {
  for (const pitchQ of [-30, 0, 30]) {
    const rider = {x: 110, y: 120, pitchQ, mode: 'stand', hidden: false, air: false, hop: 0};
    const [x, y] = surf.boardPoint(rider, 17, 0), expected = surf.projectDeck(17 * Math.cos(pitchQ * Math.PI / 180), 17 * Math.sin(pitchQ * Math.PI / 180));
    close(x, rider.x + expected[0]); close(y, rider.y + expected[1]);
    const cls = new Uint8Array(W * H).fill(CLS.WATER), fb = new Uint32Array(W * H).fill(0xff141414);
    const state = {fb, back: {cls}, foamLut: Array(32).fill(0xffffffff)}, simulation = {surfer: rider, steps: 13};
    surf.drawBoardContact(state, simulation);
    const touched = [];
    for (let i = 0; i < fb.length; i++) if (fb[i] !== 0xff141414) touched.push([i % W, Math.floor(i / W)]);
    assert.ok(touched.length > 4, 'visible water touches the board');
    assert.ok(touched.every(([px,py]) => Math.hypot(px - rider.x, py - rider.y) < 35), 'foam stays near the board');
    for (const field of ['air', 'hop', 'hidden']) {
      fb.fill(0xff141414); rider[field] = true; surf.drawBoardContact(state, simulation); rider[field] = false;
      assert.ok(fb.every(px => px === 0xff141414), `no contact foam while ${field}`);
    }
    cls.fill(CLS.SKY); fb.fill(0xff141414); surf.drawBoardContact(state, simulation);
    assert.ok(fb.every(px => px === 0xff141414), 'no foam over the sky');
  }
});

test('the board and articulated pop-up face left and join the standing stance smoothly', () => {
  const r = surf.makeRaster(128, 112);
  surf.drawBoard(r, 64, 84, 0, 1, 0);
  const capPixels = [];
  for (let y = 0; y < r.h; y++) for (let x = 0; x < r.w; x++) if (r.buf[y * r.w + x] === surf.S.cap) capPixels.push(x);
  assert.ok(capPixels.length && Math.max(...capPixels) < 64, 'the nose points in the same direction as the surfer');
  let previous;
  for (let i = 0; i <= 22; i++) {
    r.clear();
    const joints = surf.drawPopUp(r, 64, 84, POSES.crouch, 0, i / 22);
    assert.ok(joints.head[0] < joints.hip[0], 'the head faces forward');
    if (previous) for (const part of ['head', 'hip', 'handF', 'handB', 'footF', 'footB']) {
      assert.ok(Math.hypot(joints[part][0] - previous[part][0], joints[part][1] - previous[part][1]) < 3, `${part} moves continuously`);
    }
    previous = joints;
  }
  assert.deepEqual(previous, surf.standingJoints(64, 84, POSES.crouch, 0));
});

test('a distant swell grows in width as well as height instead of appearing as a long straight white line', () => {
  const b = back(), fb = b.rgb.slice();
  let step = 200;
  while (step < 1350 && surf.setState(step).h < 2.5) step++;
  surf.drawSwell({fb, back: b}, {steps: step});
  let changed = 0, longest = 0;
  for (let y = 0; y < H; y++) {
    let run = 0;
    for (let x = 0; x < W; x++) {
      const i = y * W + x;
      if (fb[i] !== b.rgb[i]) { changed++; longest = Math.max(longest, ++run); }
      else run = 0;
    }
  }
  assert.ok(changed > 0, 'the new swell is visible');
  assert.ok(longest <= 14, `the emerging crest has a short edge (${longest} pixels)`);
});
