import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const games = require('../token_tv/tablet_web/stage-game.js');
const blue = require('../token_tv/tablet_web/game-blue-lightning.js');

test('the scene is registered at the portrait resolution', () => {
  assert.deepEqual(games.registry['blue-lightning'].size, [200, 320]);
});

test('the plane remains visible above the clock in normal and picture modes', () => {
  for (const bottom of [110, 150, 186, 240, 320]) {
    const geo = blue.layout(bottom);
    assert.ok(geo.planeY > geo.horizon + 20);
    assert.ok(geo.planeY + 18 < bottom);
    for (let t = 0; t < 144; t += .25) {
      const p = blue.aircraft(t, geo);
      assert.ok(p.x >= 75 && p.x <= 125);
      assert.ok(p.y > geo.horizon + 20 && p.y + 18 < bottom);
      assert.ok(p.frame >= 0 && p.frame <= 5);
    }
  }
  const positions = Array.from({length: 1200}, (_, i) => blue.aircraft(i / 10, blue.layout(320)).y);
  assert.ok(Math.max(...positions) - Math.min(...positions) >= 18, 'the aircraft visibly climbs and dives');
});

test('large fictional poses fit every layout with one uniform scale and no frame jumps', () => {
  const bounds = {left: 59, right: 59, top: 52, bottom: 52};
  for (const bottom of [110, 150, 186, 240, 320]) {
    const geo = blue.layout(bottom, bounds);
    assert.ok(geo.planeScale > 0 && geo.planeScale <= 1);
    for (let i = 0; i < 3600; i++) {
      const p = blue.aircraft(i / 30, geo, 12345), s = geo.planeScale;
      assert.ok(p.x - bounds.left * s >= 0 && p.x + bounds.right * s <= blue.W);
      assert.ok(p.y - bounds.top * s >= 0, `top of pose fits at bottom=${bottom}`);
      assert.ok(p.y + bounds.bottom * s < bottom, `pose stays above the dock at bottom=${bottom}`);
    }
  }
});

test('the smallest layout reserves visible sky without shrinking other layouts', () => {
  const bounds = {left: 50, right: 50, top: 51, bottom: 51}, compact = blue.layout(110, bounds);
  assert.ok(compact.planeScale < .7);
  let checked = 0;
  for (let i = 0; i < 3600; i++) {
    const player = blue.aircraft(i / 30, compact, 12345);
    if (player.altitude < .99) continue;
    const camera = blue.cameraAt(i / 30, compact, player), top = bounds.top * compact.planeScale;
    assert.ok(blue.cloudCeiling(compact, camera, top) >= 15, 'high flight leaves at least 15 pixels of sky');
    checked++;
  }
  assert.ok(checked > 100);
  for (const [bottom, horizon, planeY] of [[150, 51, 86], [186, 63, 116], [320, 109, 220]]) {
    const geo = blue.layout(bottom, bounds);
    assert.equal(geo.planeScale, 1); assert.equal(geo.horizon, horizon); assert.equal(geo.planeY, planeY);
  }
});

test('flight moves much faster and boost gives a further short burst', () => {
  const world = blue.makeWorld();
  for (let i = 0; i < 30; i++) blue.stepWorld(world, 1 / 30);
  const normal = world.distance;
  world.boost = 3;
  for (let i = 0; i < 30; i++) blue.stepWorld(world, 1 / 30);
  assert.ok(normal >= 6800, `${normal} units per second`);
  assert.ok(world.distance - normal >= normal * 1.25, 'boost must add visible speed');
});

test('forward speed is independent of the number of simulation steps', () => {
  const worlds = [15, 30, 60].map(hz => {
    const world = blue.makeWorld();
    for (let i = 0; i < hz * 2; i++) blue.stepWorld(world, 1 / hz);
    return world;
  });
  for (const world of worlds) {
    assert.ok(Math.abs(world.time - 2) < 1e-9);
    assert.ok(Math.abs(world.distance - worlds[0].distance) < 1e-8);
  }
});

test('the jet changes direction and altitude briskly but without jumps', () => {
  const geo = blue.layout(320), samples = Array.from({length: 3601}, (_, i) => blue.aircraft(i / 30, geo));
  const travel = samples.slice(0, -12).map((p, i) => ({x: Math.abs(samples[i + 12].x - p.x), y: Math.abs(samples[i + 12].y - p.y)}));
  assert.ok(Math.max(...travel.map(p => p.x)) >= 9, 'a turn covers at least 9 pixels in 0.4 seconds');
  assert.ok(Math.max(...travel.map(p => p.y)) >= 6, 'a climb or dive covers at least 6 pixels in 0.4 seconds');
  for (let i = 1; i < samples.length; i++) {
    assert.ok(Math.abs(samples[i].x - samples[i - 1].x) < 7);
    assert.ok(Math.abs(samples[i].y - samples[i - 1].y) < 5);
  }
});

test('the jet makes fast maneuvers separated by brief settled intervals', () => {
  const geo = blue.layout(320), p = Array.from({length: 3601}, (_, i) => blue.aircraft(i / 30, geo, 7));
  const dx = p.slice(1).map((v, i) => Math.abs(v.x - p[i].x));
  const vertical = Array.from({length: 3601}, (_, i) => blue.aircraft(i / 30, geo, 6));
  const dy = vertical.slice(1).map((v, i) => Math.abs(v.y - vertical[i].y));
  assert.ok(Math.max(...dx) >= 4 && Math.max(...dx) < 7, 'lateral movement is fast but continuous');
  assert.ok(Math.max(...dy) >= .4 && Math.max(...dy) < 1, 'altitude transitions are visible and gradual');
  assert.ok(p.some((v, i) => i + 6 < p.length && p.slice(i, i + 7).every(q => Math.hypot(q.x - v.x, q.y - v.y) < .1)), 'the aircraft sometimes settles for at least 0.2 seconds');
  assert.ok(p.some(v => v.pitch > .4) && p.some(v => v.pitch < -.4), 'climb and dive use different procedural attitudes');
});

test('an optional five-angle aircraft atlas uses its original pose families', () => {
  const families = Object.fromEntries(['level', 'up', 'down'].map(family => [family, Array.from({length: 5}, (_, i) => `player-${family}-${i}`)]));
  const poses = {version: 1, bank_angles: [0, 22.5, 45, 67.5, 90], right_flip: true,
    ...families, up_transition: 'player-up-transition', down_transition: 'player-down-transition'};
  const names = [...families.level, ...families.up, ...families.down, poses.up_transition, poses.down_transition];
  const frames = Object.fromEntries(names.map((name, i) => [name, [i * 10, 0, 10, 10]]));
  const anchors = Object.fromEntries(names.map(name => [name, [5, 5]]));
  const json = {frames, anchors, aircraft_poses: poses}, atlas = {width: 512, height: 331};
  const grid = blue.readPoseGrid(json, blue.readAtlas(json), atlas);
  assert.ok(grid);
  assert.deepEqual(blue.aircraftLayers({bank: 0, pitch: 0}, grid), [{name: 'player-level-0', opacity: 1}]);
  assert.ok(blue.aircraftLayers({bank: .5, pitch: 1}, grid).some(layer => layer.name === 'player-up-2' && layer.opacity === 1));
  assert.ok(blue.aircraftLayers({bank: -1, pitch: -1}, grid).some(layer => layer.name === 'player-down-4' && layer.opacity === 1));
  assert.ok(blue.aircraftLayers({bank: 0, pitch: .35}, grid).some(layer => layer.name === 'player-up-transition' && layer.opacity > .99));
  for (const bank of [0, .25, .5, .75, 1]) for (const pitch of [-1, -.6, -.35, 0, .35, .6, 1]) {
    const layers = blue.aircraftLayers({bank, pitch}, grid);
    assert.equal(layers.length, 1); assert.equal(layers[0].opacity, 1, 'original poses are never drawn translucent or doubled');
  }
  assert.equal(blue.readPoseGrid({frames, anchors}, blue.readAtlas(json), atlas), null, 'an old atlas falls back safely');
  delete frames['player-up-4'];
  assert.equal(blue.readPoseGrid(json, blue.readAtlas(json), atlas), null, 'an incomplete pose grid falls back safely');
});

test('a new pose manifest cannot use boxes outside an older image during an update', () => {
  const families = Object.fromEntries(['level', 'up', 'down'].map(family => [family, Array.from({length: 5}, (_, i) => `player-${family}-${i}`)]));
  const poses = {version: 1, bank_angles: [0, 22.5, 45, 67.5, 90], right_flip: true,
    ...families, up_transition: 'player-up-transition', down_transition: 'player-down-transition'};
  const names = [...families.level, ...families.up, ...families.down, poses.up_transition, poses.down_transition];
  const frames = Object.fromEntries(names.map((name, i) => [name, [i * 10, 126, 10, 10]]));
  frames['player-0'] = [0, 0, 10, 10];
  const anchors = Object.fromEntries(Object.keys(frames).map(name => [name, [5, 5]]));
  const json = {frames, anchors, aircraft_poses: poses}, frame = blue.readAtlas(json);
  const oldImage = {naturalWidth: 512, naturalHeight: 126}, newImage = {naturalWidth: 512, naturalHeight: 331};
  assert.equal(blue.readPoseGrid(json, frame, oldImage), null, 'new metadata with an old image uses legacy poses');
  assert.ok(blue.readPoseGrid(json, frame, newImage), 'new metadata with the complete image enables the new poses');
  const oldJson = {frames: {'player-0': [0, 0, 10, 10]}, anchors: {'player-0': [5, 5]}};
  assert.deepEqual(blue.readAtlas(oldJson)('player-0'), frame('player-0'), 'new image with old metadata keeps legacy coordinates');
  const old = globalThis.ImageData;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    const scene = Object.create(blue.scene);
    scene.init({json, atlas: oldImage, flightSeed: 1});
    assert.equal(scene.s.poses, null);
    assert.deepEqual(scene.s.frame('player-0'), frame('player-0'));
  } finally { globalThis.ImageData = old; }
});

test('enemy pose families require all original frames to fit the loaded image', () => {
  const widths = [5, 7, 10, 14, 18, 24, 32, 42, 54], frames = {}, anchors = {};
  const poses = Array.from({length: 12}, (_, pose) => ({
    frames: widths.map((width, index) => {
      const name = `enemy-pose-${pose}-${width}`, n = pose * widths.length + index;
      frames[name] = [(n % 32) * 12, 345 + Math.floor(n / 32) * 12, 10, 10]; anchors[name] = [5, 5];
      return name;
    }),
    flips: [[false, false], [true, false]],
  }));
  poses[4].flips = [[true, false]];
  for (const model of [0, 1]) for (const width of widths) {
    const name = `enemy-${model}-${width}`; frames[name] = [0, 0, 10, 10]; anchors[name] = [5, 5];
  }
  frames['enemy-pose-7-54'] = [0, 345, 9, 51]; anchors['enemy-pose-7-54'] = [4, 28];
  const json = {frames, anchors, enemy_poses: {version: 1, reference_width: 72, widths, poses, sequence: [4, 5, 6, 7, 8, 7, 6, 5, 4]}};
  const frame = blue.readAtlas(json), oldImage = {naturalWidth: 512, naturalHeight: 345}, newImage = {naturalWidth: 512, naturalHeight: 437};
  assert.equal(blue.readEnemyPoseGrid(json, frame, oldImage), null, 'new metadata with the old image falls back');
  const grid = blue.readEnemyPoseGrid(json, frame, newImage); assert.ok(grid);
  assert.deepEqual(frame('enemy-pose-7-54'), {x: 0, y: 345, w: 9, h: 51, ax: 4, ay: 28}, 'nominal width does not stretch a narrow original');
  const indices = new Set(), spec = blue.MISSIONS[0];
  const slopes = {1: 1, 2: 1, 3: -1, 5: 1, 6: 1, 7: 1, 10: 1, 11: 1};
  for (let seed = 0; seed < 500; seed++) for (let age = 0; age < 7; age += .3) for (const bank of [-1, -.4, 0, .4, 1]) {
    const selected = blue.enemyPose({age, cycle: 0, side: seed % 2 ? 1 : -1, width: 18, bank}, spec, grid, seed);
    assert.ok(poses[selected.index].flips.some(([x, y]) => x === selected.flipX && y === selected.flipY));
    if (selected.index in slopes) assert.equal(slopes[selected.index] * (selected.flipX ? -1 : 1), Math.sign(bank));
    indices.add(selected.index);
  }
  assert.equal(indices.size, 12, 'all twelve confirmed forms can appear');
  const sequenceSeed = Array.from({length: 500}, (_, i) => i).find(seed => blue.enemyPose({age: 2.5, cycle: 0, side: 1, width: 18, bank: -1}, spec, grid, seed).sequence);
  for (const [bank, expected] of [[-1, [4, 5, 6, 7, 8, 7, 6, 5, 4]], [1, [5, 6, 7, 6, 5]]]) {
    const sequence = [];
    for (let age = 0; age < 7; age += .03) {
      const pose = blue.enemyPose({age, cycle: 0, side: 1, width: 18, bank}, spec, grid, sequenceSeed);
      if (!pose.sequence) continue;
      assert.equal(pose.flipX, bank < 0); assert.equal(pose.flipY, false);
      if (sequence.at(-1) !== pose.index) sequence.push(pose.index);
    }
    assert.deepEqual(sequence, expected, 'the appropriate observed sequence runs only once per encounter');
  }
  const geo = blue.layout(320), seed = 12345;
  for (const mission of blue.MISSIONS) {
    let previous = null;
    for (let i = 0; i < 1800; i++) {
      const time = i / 30, player = blue.aircraft(time, geo, seed), camera = blue.cameraAt(time, geo, player);
      const enemy = blue.enemyAt(time, mission, {...geo, horizon: camera.horizon}, camera, seed);
      if (!enemy || enemy.exploding) { previous = null; continue; }
      const pose = blue.enemyPose(enemy, mission, grid, seed);
      const visibleSign = (slopes[pose.index] || 0) * (pose.flipX ? -1 : 1);
      if (previous && previous.cycle === enemy.cycle && previous.sign && visibleSign) {
        assert.notEqual(previous.sign, -visibleSign, 'orientation changes pass through a neutral pose');
      }
      previous = {cycle: enemy.cycle, sign: visibleSign};
    }
  }
  const old = globalThis.ImageData;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    for (const [atlas, expectNew] of [[oldImage, false], [newImage, true]]) {
      const images = [], rotations = [], ctx = new Proxy({}, {get: (o, k) => {
        if (k === 'drawImage') return (...args) => images.push(args);
        if (k === 'rotate') return angle => rotations.push(angle);
        return o[k] || (() => {});
      }, set: (o, k, v) => (o[k] = v, true)});
      const scene = Object.create(blue.scene), api = {json, atlas, flightSeed: 12345, view: {bottom: 320}};
      scene.init(api); scene.s.world.time = 3.6; scene.draw(api, ctx);
      assert.equal(!!scene.s.enemyPoses, expectNew);
      assert.ok(images.length && images.every(args => expectNew ? args[2] >= 345 : args[2] < 345));
      if (expectNew) {
        assert.equal(rotations.length, 0, 'traced poses are not given an extra procedural bank');
        assert.ok(images.every(args => args[7] === args[3] && args[8] === args[4]), 'nominal sizes do not distort a pose');
      }
    }
  } finally { globalThis.ImageData = old; }
  delete frames['enemy-pose-11-54'];
  assert.equal(blue.readEnemyPoseGrid(json, blue.readAtlas(json), newImage), null, 'one missing frame disables the whole family');
  assert.equal(blue.readEnemyPoseGrid({frames, anchors}, blue.readAtlas(json), newImage), null, 'old metadata stays legacy');
});

test('fictional large pose families use one undistorted scale and remain above the dock', () => {
  const families = Object.fromEntries(['level', 'up', 'down'].map(family => [family, Array.from({length: 5}, (_, i) => `player-${family}-${i}`)]));
  const poses = {version: 1, bank_angles: [0, 22.5, 45, 67.5, 90], right_flip: true,
    ...families, up_transition: 'player-up-transition', down_transition: 'player-down-transition'};
  const names = [...families.level, ...families.up, ...families.down, poses.up_transition, poses.down_transition];
  const frames = {}, anchors = {};
  names.forEach((name, i) => { const h = 26 + (i % 5) * 19; frames[name] = [0, 126, 100, h]; anchors[name] = [50, Math.floor(h / 2)]; });
  const json = {frames, anchors, aircraft_poses: poses}, atlas = {width: 512, height: 345};
  const frame = blue.readAtlas(json), grid = blue.readPoseGrid(json, frame, atlas), bounds = blue.poseEnvelope(grid, frame);
  assert.ok(bounds.top >= 50 && bounds.bottom >= 50);
  const old = globalThis.ImageData;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    for (const bottom of [110, 150, 186, 240, 320]) {
      const scales = [], images = [], ctx = new Proxy({}, {get: (o, k) => {
        if (k === 'scale') return (x, y) => scales.push([x, y]);
        if (k === 'drawImage') return (...args) => images.push(args);
        return o[k] || (() => {});
      }, set: (o, k, v) => (o[k] = v, true)});
      const scene = Object.create(blue.scene), api = {json, atlas, flightSeed: 12345, view: {bottom}};
      scene.init(api); scene.s.world.time = 3.6; scene.draw(api, ctx);
      const geo = blue.layout(bottom, bounds), player = blue.aircraft(3.6, geo, 12345);
      assert.ok(scales.some(([x, y]) => x === geo.planeScale && y === geo.planeScale), 'pose scaling is uniform');
      assert.ok(player.y - bounds.top * geo.planeScale >= 0 && player.y + bounds.bottom * geo.planeScale < bottom);
      assert.ok(images.every(args => args[1] >= 0 && args[2] >= 0 && args[1] + args[3] <= atlas.width && args[2] + args[4] <= atlas.height));
    }
  } finally { globalThis.ImageData = old; }
});

test('a seeded flight varies without a short repeated choreography', () => {
  const geo = blue.layout(320), sample = seed => Array.from({length: 180}, (_, i) => blue.aircraft(i * .5, geo, seed));
  const a = sample(12345), repeat = sample(12345), different = sample(67890);
  assert.deepEqual(a, repeat);
  assert.ok(a.some((p, i) => Math.abs(p.x - different[i].x) > 3), 'different seeds give different flights');
  assert.ok(a.filter((p, i) => i + 30 < a.length && Math.abs(p.x - a[i + 30].x) > 2).length > 60, 'the flight does not repeat every 15 seconds');
});

test('each live scene gets a new seed while a fixture can supply its own', () => {
  const oldImageData = globalThis.ImageData, oldRandom = Math.random;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    let next = .1; Math.random = () => { const value = next; next += .1; return value; };
    const a = Object.create(blue.scene), b = Object.create(blue.scene), fixed = Object.create(blue.scene);
    a.init({}); b.init({}); fixed.init({flightSeed: 12345});
    assert.notEqual(a.s.world.seed, b.s.world.seed);
    assert.equal(fixed.s.world.seed, 12345);
  } finally { globalThis.ImageData = oldImageData; Math.random = oldRandom; }
});

test('turns are infrequent, with variable pauses and maneuver durations', () => {
  const geo = blue.layout(320), dt = 1 / 30, durations = [], pauses = [];
  let active = false, start = 0, ended = 0;
  for (let i = 0; i < 240 * 30; i++) {
    const time = i * dt, turning = Math.abs(blue.aircraft(time, geo, 12345).bank) > .05;
    if (turning && !active) { if (ended) pauses.push(time - ended); start = time; }
    if (!turning && active) { durations.push(time - start); ended = time; }
    active = turning;
  }
  assert.ok(durations.length >= 12 && durations.length <= 38, `${durations.length} turns in four minutes`);
  assert.ok(Math.min(...durations) < .8 && Math.max(...durations) > 1.6, 'both short and sustained turns occur');
  assert.ok(Math.min(...pauses) >= 2 && Math.max(...pauses) - Math.min(...pauses) > 1, 'turns have varied pauses');
});

test('the banked aircraft and horizon lean in the same visible direction', () => {
  const geo = blue.layout(320), seed = 12345, old = globalThis.ImageData;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    // Abstract wing heights follow the measured orientation: unreflected has the right wing higher.
    const wings = [{x: -12, y: 20}, {x: 12, y: 10}], times = [];
    for (const direction of [-1, 1]) {
      const time = Array.from({length: 3600}, (_, i) => i / 30).find(t => blue.aircraft(t, geo, seed).bank * direction > .3);
      assert.notEqual(time, undefined);
      times.push([time, direction]);
    }
    const frames = {}, anchors = {};
    for (let i = 0; i < 6; i++) { frames['player-' + i] = [0, 0, 10, 10]; anchors['player-' + i] = [5, 5]; }
    for (const [time, direction] of times) {
      const scales = [], ctx = new Proxy({}, {get: (o, k) => k === 'scale' ? (x, y) => scales.push([x, y]) : o[k] || (() => {}), set: (o, k, v) => (o[k] = v, true)});
      const api = {json: {frames, anchors}, atlas: {}, flightSeed: seed, view: {bottom: 320}};
      const scene = Object.create(blue.scene); scene.init(api); scene.s.world.time = time; scene.draw(api, ctx);
      const reflected = scales.some(([x, y]) => x === -1 && y === 1);
      const visibleWings = wings.map(p => ({x: reflected ? -p.x : p.x, y: p.y})).sort((a, b) => a.x - b.x);
      assert.equal(Math.sign(visibleWings[1].y - visibleWings[0].y), direction, 'the lower wing indicates the intended turn');
      const player = blue.aircraft(time, geo, seed), camera = blue.cameraAt(time, geo, player);
      assert.equal(Math.sign(camera.roll), direction, 'the horizon leans with the lower wing');
    }
  } finally { globalThis.ImageData = old; }
});

test('the shared camera banks and pitches with the jet', () => {
  const geo = blue.layout(320), views = Array.from({length: 3601}, (_, i) => blue.cameraAt(i / 30, geo));
  assert.ok(Math.max(...views.map(v => v.roll)) >= .04 && Math.min(...views.map(v => v.roll)) <= -.04);
  assert.ok(Math.max(...views.map(v => v.horizon)) - Math.min(...views.map(v => v.horizon)) >= 8);
  for (const view of views) {
    assert.ok(view.roll * view.player.bank >= 0, 'the world banks in the same visible direction as the jet');
    assert.ok((view.horizon - geo.horizon) * (view.player.y - geo.planeY) <= 0, 'a climb reveals more sky');
    assert.ok(Math.abs(view.roll) < .12);
  }
});

test('both the horizon and scenery follow the visible left and right turn', () => {
  const geo = blue.layout(320), directions = new Set();
  for (let i = 0; i < 300; i++) {
    const a = blue.cameraAt(i / 30, geo), b = blue.cameraAt((i + 1) / 30, geo);
    const dx = b.player.x - a.player.x;
    if (Math.abs(dx) < .1 || Math.abs(b.player.bank) < .02) continue;
    const scenery = blue.projectGround(2000, 0, b).x - blue.projectGround(2000, 0, a).x;
    assert.ok(Math.sign(b.roll) === Math.sign(dx), 'the horizon banks with the visible turn');
    assert.ok(Math.sign(scenery) === Math.sign(dx), 'nearby scenery moves with the visible turn');
    directions.add(Math.sign(dx));
  }
  assert.deepEqual([...directions].sort(), [-1, 1]);
});

test('a large turn shifts the ground appreciably while keeping an object anchored', () => {
  const geo = blue.layout(320), seed = 12345;
  const views = Array.from({length: 1800}, (_, i) => {
    const time = i / 30, player = blue.aircraft(time, geo, seed);
    return {time, player, camera: blue.cameraAt(time, geo, player)};
  });
  const left = views.reduce((a, b) => a.player.x < b.player.x ? a : b);
  const right = views.reduce((a, b) => a.player.x > b.player.x ? a : b);
  const a = blue.projectGround(2000, 0, left.camera), b = blue.projectGround(2000, 0, right.camera);
  assert.ok(b.x - a.x >= 22, `${b.x - a.x} pixels of middle-distance lateral parallax`);
  for (const view of [left, right]) {
    const world = {time: view.time, distance: 10000, seed};
    for (const f of blue.groundFeatures(world, geo, view.camera)) {
      const projected = blue.projectGround(f.position - world.distance, f.lateral, view.camera);
      assert.ok(Math.abs(f.x - projected.x) < 1e-9 && Math.abs(f.y - projected.y) < 1e-9);
    }
  }
});

test('each landscape lasts about fifty-five seconds with a multi-second transition', () => {
  const world = blue.makeWorld();
  for (let i = 0; i < 48 * 30; i++) blue.stepWorld(world, 1 / 30);
  const early = blue.terrainAtDistance(world.distance);
  assert.equal(early.kind, 'fields'); assert.equal(early.blend, 0);
  for (let i = 0; i < 4 * 30; i++) blue.stepWorld(world, 1 / 30);
  const transition = blue.terrainAtDistance(world.distance);
  assert.equal(transition.kind, 'fields'); assert.ok(transition.blend > .1 && transition.blend < .9);
  for (let i = 0; i < 4 * 30; i++) blue.stepWorld(world, 1 / 30);
  assert.equal(blue.terrainAtDistance(world.distance).kind, 'desert');
});

test('clouds occupy different depths and grow as their fixed world positions approach', () => {
  const geo = blue.layout(320), camera = blue.cameraAt(0, geo), world = {time: 0, distance: 10000, seed: 12345, boost: 0};
  const before = blue.cloudFeatures(world, geo, camera);
  const after = blue.cloudFeatures({...world, distance: world.distance + 3000}, geo, camera);
  assert.ok(before.length >= 2 && Math.max(...before.map(c => c.ahead)) - Math.min(...before.map(c => c.ahead)) > 5000);
  const pairs = before.map(a => [a, after.find(b => b.id === a.id)]).filter(([, b]) => b);
  assert.ok(pairs.length > 0);
  for (const [a, b] of pairs) {
    assert.ok(b.width > a.width && (a.cloudLevel - camera.altitude) * (b.y - a.y) < 0,
      'a cloud grows and moves away from the horizon as it approaches');
    assert.equal(a.lateral, b.lateral, 'its world position remains fixed');
  }
});

test('the cloud projection follows camera movement and bank without changing its world position', () => {
  const geo = blue.layout(320), world = {time: 0, distance: 10000, seed: 12345, boost: 0};
  const base = blue.cameraAt(0, geo), left = {...base, lateral: -15, roll: -.05}, right = {...base, lateral: 15, roll: .05};
  const a = blue.cloudFeatures(world, geo, left), b = blue.cloudFeatures(world, geo, right);
  const first = a.find(c => b.some(d => d.id === c.id));
  assert.ok(first);
  const second = b.find(c => c.id === first.id);
  assert.ok(second.x < first.x && second.lateral === first.lateral);
  const raised = blue.cloudFeatures(world, geo, {...left, altitude: left.altitude + .2}).find(c => c.id === first.id);
  assert.ok(raised && raised.y > first.y, 'clouds move downward as altitude increases');
  assert.ok((first.y + left.roll * (first.x - 100)) !== (first.y + right.roll * (first.x - 100)), 'bank changes the projected screen position');
});

test('clouds move visibly downward on ascent and upward on descent at every layout', () => {
  const bounds = {left: 50, right: 50, top: 51, bottom: 51};
  const shape = [{width: 118 / 159, height: 14 / 159}, {width: 1, height: 30 / 159}];
  for (const bottom of [110, 150, 186, 320]) {
    const geo = blue.layout(bottom, bounds), top = bounds.top * geo.planeScale, seed = 12345;
    const views = [0, .5, 1].map(altitude => {
      const player = {...blue.aircraft(0, geo, seed), altitude, bank: 0, x: 100,
        y: geo.planeY + (.5 - altitude) * 24};
      return blue.cameraAt(0, geo, player);
    });
    let checked = 0, largest = 0;
    for (let distance = 0; distance < 60000; distance += 500) {
      const world = {time: 0, distance, seed, boost: 0};
      const clouds = views.map(camera => blue.cloudFeatures(world, geo, camera, shape, top));
      for (const low of clouds[0]) {
        const middle = clouds[1].find(c => c.id === low.id), high = clouds[2].find(c => c.id === low.id);
        if (!middle || !high || Math.min(low.opacity, middle.opacity, high.opacity) < .1 || low.width < 3) continue;
        assert.ok(low.y < middle.y && middle.y < high.y, 'climbing moves the same cloud down');
        largest = Math.max(largest, high.y - low.y); checked++;
      }
    }
    assert.ok(checked > 0 && largest >= (bottom === 110 ? 3 : 6), `visible vertical parallax in layout ${bottom}`);
  }
});

test('visible clouds predominantly follow altitude direction during real forward flight', () => {
  const bounds = {left: 50, right: 50, top: 51, bottom: 51};
  const shape = [{width: 118 / 159, height: 14 / 159}, {width: 1, height: 30 / 159}];
  for (const bottom of [110, 186, 320]) for (const seed of [1, 12345]) {
    const geo = blue.layout(bottom, bounds), top = bounds.top * geo.planeScale, world = blue.makeWorld(seed);
    let player = blue.aircraft(0, geo, seed), camera = blue.cameraAt(0, geo, player);
    let previous = blue.cloudFeatures(world, geo, camera, shape, top);
    const up = [0, 0], down = [0, 0];
    for (let i = 0; i < 1800; i++) {
      blue.stepWorld(world, 1 / 30);
      const nextPlayer = blue.aircraft(world.time, geo, seed), nextCamera = blue.cameraAt(world.time, geo, nextPlayer);
      const current = blue.cloudFeatures(world, geo, nextCamera, shape, top), byId = new Map(previous.map(c => [c.id, c]));
      const altitudeChange = nextPlayer.altitude - player.altitude;
      for (const cloud of current) {
        const before = byId.get(cloud.id);
        if (!before || cloud.opacity < .2 || before.opacity < .2 || Math.abs(altitudeChange) < .002) continue;
        const screenMove = cloud.y + nextCamera.roll * (cloud.x - 100) - before.y - camera.roll * (before.x - 100);
        const counts = altitudeChange > 0 ? up : down;
        counts[(altitudeChange > 0 ? screenMove > 0 : screenMove < 0) ? 0 : 1]++;
      }
      previous = current; player = nextPlayer; camera = nextCamera;
    }
    assert.ok(up[0] > 100 && up[0] / (up[0] + up[1]) > .8, 'ascent visibly carries the cloud layer downward');
    assert.ok(down[0] > 100 && down[0] / (down[0] + down[1]) > .85, 'descent visibly carries the cloud layer upward');
  }
});

test('clouds remain finite and fade before leaving view at cruise and boost speeds', () => {
  const shapes = [undefined, [{width: 118 / 159, height: 14 / 159}, {width: 1, height: 30 / 159}]];
  for (const bottom of [110, 186, 320]) for (const boost of [0, 3]) for (const seed of [1, 12345]) for (const shape of shapes) {
    const geo = blue.layout(bottom), world = {time: 0, distance: 10000, seed, boost};
    let previous = blue.cloudFeatures(world, geo, undefined, shape);
    for (let i = 0; i < 600; i++) {
      blue.stepWorld(world, 1 / 30);
      const current = blue.cloudFeatures(world, geo, undefined, shape), ids = new Set(current.map(c => c.id));
      const before = new Map(previous.map(c => [c.id, c]));
      const visible = c => c.x + c.width / 2 > 0 && c.x - c.width / 2 < blue.W && c.y + c.height / 2 > 0 && c.y - c.height / 2 < bottom;
      const effectiveAlpha = c => c.opacity;
      for (const c of current) {
        assert.ok([c.x, c.y, c.width, c.height, c.opacity].every(Number.isFinite));
        assert.ok(c.width > 0 && c.height > 0 && c.opacity >= 0 && c.opacity <= 1);
        const p = before.get(c.id);
        if (!p && visible(c)) assert.ok(effectiveAlpha(c) < .12, 'a cloud fades in before appearing');
        if (p && c.opacity > .2 && p.opacity > .2) {
          assert.ok(Math.hypot(c.x - p.x, c.y - p.y) < 25 && Math.abs(c.width - p.width) < 25, 'visible clouds move and grow continuously');
        }
      }
      for (const c of previous) {
        if (!ids.has(c.id) && visible(c)) assert.ok(effectiveAlpha(c) < .12, 'a visible cloud fades before removal');
      }
      previous = current;
    }
  }
});

test('crossing a world cell boundary cannot reveal an already-visible cloud', () => {
  const geo = blue.layout(320), camera = blue.cameraAt(0, geo);
  for (let seed = 0; seed < 50; seed++) for (const boundary of [5000, 10000, 15000]) {
    const before = blue.cloudFeatures({time: 0, distance: boundary - .001, seed, boost: 0}, geo, camera);
    const after = blue.cloudFeatures({time: 0, distance: boundary + .001, seed, boost: 0}, geo, camera);
    const ids = new Set(before.map(c => c.id));
    for (const cloud of after) if (!ids.has(cloud.id)) {
      assert.ok(cloud.opacity < .001, `cloud ${cloud.id} appeared abruptly at distance ${boundary}`);
    }
  }
});

test('flight visits three stable altitudes and uses the correct attitude during transitions', () => {
  const geo = blue.layout(320), seed = 12345, states = new Set();
  let up = 0, down = 0, diagonal = 0, previous = blue.aircraft(0, geo, seed);
  for (let i = 1; i < 6000; i++) {
    const p = blue.aircraft(i / 30, geo, seed), change = p.altitude - previous.altitude;
    assert.ok(p.altitude >= 0 && p.altitude <= 1 && Math.abs(change) < .03, 'altitude changes continuously');
    if (Math.abs(p.pitch) < .01) {
      for (const [index, level] of [0, .5, 1].entries()) if (Math.abs(p.altitude - level) < .04) states.add(index);
    }
    if (Math.abs(change) > .001) {
      assert.equal(Math.sign(p.pitch), Math.sign(change), 'the player pitches up when climbing and down when descending');
      if (change > 0) up++; else down++;
      if (Math.abs(p.bank) > .2) diagonal++;
    }
    previous = p;
  }
  assert.deepEqual([...states].sort(), [0, 1, 2]);
  assert.ok(up > 20 && down > 20 && diagonal > 10);
});

test('pitch follows altitude even when a compact layout clamps the plane position', () => {
  const geo = {horizon: 37, bottom: 110, planeY: 60}, seed = 12345;
  let previous = blue.aircraft(0, geo, seed), checked = 0;
  for (let i = 1; i < 6000; i++) {
    const p = blue.aircraft(i / 30, geo, seed), change = p.altitude - previous.altitude;
    if (p.y === geo.horizon + 23 && Math.abs(change) > .001) {
      assert.equal(Math.sign(p.pitch), Math.sign(change)); checked++;
    }
    previous = p;
  }
  assert.ok(checked > 10, 'the clamp case was exercised');
});

test('ground and clouds respond coherently to low and high altitude', () => {
  const geo = blue.layout(320), player = blue.aircraft(0, geo, 12345);
  const low = blue.cameraAt(0, geo, {...player, altitude: 0}), high = blue.cameraAt(0, geo, {...player, altitude: 1});
  assert.ok(low.groundZoom > high.groundZoom && low.groundProjection < high.groundProjection);
  const lowPoint = blue.projectGround(2000, 20, low), highPoint = blue.projectGround(2000, 20, high);
  assert.ok(Math.abs(lowPoint.x - 100) > Math.abs(highPoint.x - 100));
  const world = {time: 0, distance: 10000, seed: 12345, boost: 0};
  const lowObjects = blue.groundFeatures(world, geo, low), highObjects = blue.groundFeatures(world, geo, high);
  const objectPair = lowObjects.map(a => [a, highObjects.find(b => b.id === a.id)]).find(([, b]) => b);
  assert.ok(objectPair && objectPair[0].size > objectPair[1].size, 'the same ground object is smaller at high altitude');
  const lowClouds = blue.cloudFeatures(world, geo, low), highClouds = blue.cloudFeatures(world, geo, high);
  const pair = lowClouds.map(a => [a, highClouds.find(b => b.id === a.id)]).find(([, b]) => b);
  assert.ok(pair && pair[1].y > pair[0].y, 'clouds move down relative to a climbing camera');
});

test('clouds stay above the full aircraft envelope, the ground and the dock', () => {
  const bounds = {left: 50, right: 50, top: 51, bottom: 51};
  const shapes = [undefined, [{width: 118 / 159, height: 14 / 159}, {width: 1, height: 30 / 159}]];
  for (const bottom of [110, 150, 186, 320]) for (const altitude of [0, .5, 1]) for (const direction of [-1, 0, 1]) for (const shape of shapes) {
    const geo = blue.layout(bottom, bounds), top = bounds.top * geo.planeScale;
    const player = {...blue.aircraft(0, geo, 12345), altitude, bank: direction,
      y: geo.planeY + (0.5 - altitude) * 24, x: 100 + direction * 24};
    const camera = blue.cameraAt(0, geo, player), ceiling = blue.cloudCeiling(geo, camera, top);
    for (let distance = 0; distance < 30000; distance += 500) {
      const clouds = blue.cloudFeatures({time: 0, distance, seed: 12345, boost: 0}, geo, camera, shape, top);
      for (const cloud of clouds) if (cloud.opacity > .01) {
        const bottomY = cloud.y + camera.roll * (cloud.x - 100) + cloud.height / 2 + Math.abs(camera.roll) * cloud.width / 2;
        assert.ok(bottomY <= ceiling && bottomY < player.y - top, 'cloud never covers the plane or dock');
        assert.ok(bottomY < camera.horizon + camera.roll * (cloud.x - 100) - Math.abs(camera.roll) * cloud.width / 2, 'cloud never covers the ground');
      }
    }
  }
});

test('the cloud ceiling has many visible, bounded and horizontally distributed clouds', () => {
  const bounds = {left: 50, right: 50, top: 51, bottom: 51};
  const shape = [{width: 118 / 159, height: 14 / 159}, {width: 1, height: 30 / 159}];
  for (const bottom of [110, 150, 186, 320]) for (const altitude of [0, .5, 1]) {
    const geo = blue.layout(bottom, bounds), top = bounds.top * geo.planeScale, counts = [];
    let left = 0, right = 0;
    for (const seed of [1, 7, 12345]) for (let distance = 0; distance < 60000; distance += 1000) {
      const player = {...blue.aircraft(0, geo, seed), altitude, y: geo.planeY + (0.5 - altitude) * 24};
      const camera = blue.cameraAt(0, geo, player);
      const clouds = blue.cloudFeatures({time: 0, distance, seed, boost: 0}, geo, camera, shape, top)
        .filter(c => c.opacity >= .2 && c.width >= 3);
      counts.push(clouds.length);
      left += clouds.filter(c => c.x < 80).length; right += clouds.filter(c => c.x > 120).length;
      assert.ok(clouds.length <= 42, 'draw work remains bounded');
    }
    counts.sort((a, b) => a - b);
    assert.ok(counts[Math.floor(counts.length / 2)] >= 20, `visible median for bottom=${bottom}, altitude=${altitude}`);
    assert.ok(left > 0 && right > 0, 'clouds appear on both sides of the sky');
  }
});

test('the cloud ceiling stays safe and continuous during actual flight in every layout', () => {
  const bounds = {left: 50, right: 50, top: 51, bottom: 51};
  const shape = [{width: 118 / 159, height: 14 / 159}, {width: 1, height: 30 / 159}];
  for (const bottom of [110, 150, 186, 320]) for (const seed of [1, 12345]) {
    const geo = blue.layout(bottom, bounds), top = bounds.top * geo.planeScale;
    const world = {time: 0, distance: 10000, seed, boost: 3};
    const snapshot = () => {
      const player = blue.aircraft(world.time, geo, seed), camera = blue.cameraAt(world.time, geo, player);
      const ceiling = blue.cloudCeiling(geo, camera, top), values = blue.cloudFeatures(world, geo, camera, shape, top);
      const visible = cloud => {
        const y = cloud.y + camera.roll * (cloud.x - 100), half = cloud.height / 2 + Math.abs(camera.roll) * cloud.width / 2;
        assert.ok(y + half <= ceiling && y + half < player.y - top, 'cloud stays above the aircraft');
        return cloud.x + cloud.width / 2 > 0 && cloud.x - cloud.width / 2 < blue.W && y + half > 0 && y - half < ceiling;
      };
      return new Map(values.map(cloud => [cloud.id, {opacity: cloud.opacity, visible: visible(cloud)}]));
    };
    let previous = snapshot();
    for (let i = 0; i < 900; i++) {
      blue.stepWorld(world, 1 / 30);
      const current = snapshot();
      for (const [id, cloud] of current) if (!previous.has(id) && cloud.visible) {
        assert.ok(cloud.opacity < .12, 'a visible cloud enters gradually');
      }
      for (const [id, cloud] of previous) if (!current.has(id) && cloud.visible) {
        assert.ok(cloud.opacity < .12, 'a visible cloud exits gradually');
      }
      previous = current;
    }
  }
});

test('confirmed cloud sprites require a complete atlas and preserve their original aspect ratios', () => {
  const widths = [16, 24, 36, 54, 80, 120, 180], frames = {}, anchors = {};
  const poses = [[118, 14], [159, 30]].map(([width, height], index) => ({
    source_size: [width, height], source_anchor: index ? [0, -1] : [-25, -14], flips: [[false, false]],
    frames: widths.map((nominal, i) => {
      const name = `cloud-pose-${index}-${nominal}`;
      frames[name] = [index * 200, 437 + i * 20, Math.max(1, Math.round(nominal * width / 159)), 10];
      anchors[name] = [Math.floor(frames[name][2] / 2), 5];
      return name;
    }),
  }));
  frames['player-0'] = [0, 0, 10, 10]; anchors['player-0'] = [5, 5];
  const json = {frames, anchors, cloud_poses: {version: 1, anchor_mode: 'visual_center', reference_width: 159, widths, poses}};
  const frame = blue.readAtlas(json), oldImage = {naturalWidth: 512, naturalHeight: 437}, newImage = {naturalWidth: 512, naturalHeight: 650};
  assert.equal(blue.readCloudPoseGrid(json, frame, oldImage), null, 'new metadata with an old image uses procedural clouds');
  assert.equal(blue.readCloudPoseGrid({frames, anchors}, frame, newImage), null, 'an updated image with old metadata keeps the fallback');
  const grid = blue.readCloudPoseGrid(json, frame, newImage); assert.ok(grid);
  const geo = blue.layout(320), world = {time: 0, distance: 10000, seed: 12345, boost: 0};
  for (const cloud of blue.cloudFeatures(world, geo, blue.cameraAt(0, geo), grid.shapes)) {
    assert.ok(Math.abs(cloud.width / cloud.height - poses[cloud.style].source_size[0] / poses[cloud.style].source_size[1]) < 1e-9);
  }
  const old = globalThis.ImageData;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    for (const [atlas, expected] of [[oldImage, false], [newImage, true]]) {
      const images = [], ctx = new Proxy({}, {get: (o, k) => k === 'drawImage' ? (...args) => images.push(args) : o[k] || (() => {}), set: (o, k, v) => (o[k] = v, true)});
      const scene = Object.create(blue.scene), api = {json, atlas, flightSeed: 12345, view: {bottom: 320}};
      scene.init(api); scene.s.world.distance = 10000; scene.draw(api, ctx);
      assert.equal(!!scene.s.cloudPoses, expected);
      if (expected) {
        const lastCloud = images.findLastIndex(args => args[2] >= 437), player = images.findIndex(args => args[2] === 0);
        assert.ok(lastCloud >= 0 && player > lastCloud, 'all clouds are drawn before the player');
      }
      else assert.ok(images.every(args => args[2] < 437), 'an older image never uses cloud rectangles');
    }
  } finally { globalThis.ImageData = old; }
  delete frames['cloud-pose-1-180'];
  assert.equal(blue.readCloudPoseGrid(json, blue.readAtlas(json), newImage), null, 'one missing frame disables the family');
});

test('ground sampling remains in bounds at all altitude and bank extremes', () => {
  for (const bottom of [110, 150, 186, 320]) for (const altitude of [0, .5, 1]) for (const direction of [-1, 1]) {
    const geo = blue.layout(bottom), player = {...blue.aircraft(0, geo, 12345), altitude,
      x: 100 + direction * 24, y: geo.planeY + (0.5 - altitude) * 24, bank: direction};
    const camera = blue.cameraAt(0, geo, player), pixels = new Uint32Array(blue.W * blue.H);
    blue.paintBackdrop(pixels, {time: 0, distance: 10000, seed: 12345, boost: 0}, geo, camera);
    assert.ok(pixels.every(pixel => (pixel >>> 24) === 255), `no unpainted pixels at bottom=${bottom}, altitude=${altitude}`);
  }
});

test('fixed terrain and its objects share a perspective as they approach', () => {
  const geo = blue.layout(320), time = 10, camera = blue.cameraAt(time, geo);
  const far = blue.projectGround(4000, 20, camera), near = blue.projectGround(1000, 20, camera);
  assert.ok(near.y > far.y && Math.abs(near.x - 100) > Math.abs(far.x - 100));
  const road = (0xff000000 | 125 << 16 | 186 << 8 | 205) >>> 0;
  let previousY = 0;
  for (const distance of [11800, 11950, 12050]) {
    const pixels = new Uint32Array(blue.W * blue.H), world = {time, distance};
    blue.paintBackdrop(pixels, world, geo);
    // This field road lies at world distance 12,618, across the three flight positions.
    const point = blue.projectGround(12618 - distance, 0, camera);
    assert.ok(point.y > previousY);
    assert.equal(pixels[Math.round(point.y) * blue.W + Math.round(point.x)], road);
    previousY = point.y;
    for (const feature of blue.groundFeatures(world, geo, camera)) {
      const expected = blue.projectGround(feature.position - distance, feature.lateral, camera);
      assert.ok(Math.abs(feature.x - expected.x) < 1e-9 && Math.abs(feature.y - expected.y) < 1e-9);
    }
  }
});

test('a near road visibly approaches quickly without skipping out of view', () => {
  const geo = blue.layout(320), time = 0, roadPosition = 12618, camera = blue.cameraAt(time, geo);
  let low = 11500, high = 12200;
  for (let i = 0; i < 30; i++) {
    const middle = (low + high) / 2;
    if (blue.projectGround(roadPosition - middle, 0, camera).y < 250) low = middle; else high = middle;
  }
  const world = {time, distance: (low + high) / 2, boost: 0};
  const colour = (0xff000000 | 125 << 16 | 186 << 8 | 205) >>> 0;
  function roadCenter(min, max) {
    const pixels = new Uint32Array(blue.W * blue.H);
    blue.paintBackdrop(pixels, world, geo);
    const rows = [];
    for (let y = min; y <= max; y++) if (pixels[y * blue.W + 100] === colour) rows.push(y);
    assert.ok(rows.length, 'the same road remains visible');
    return rows.reduce((sum, y) => sum + y, 0) / rows.length;
  }
  const before = roadCenter(240, 260);
  blue.stepWorld(world, 1 / 30);
  const projected = blue.projectGround(roadPosition - world.distance, 0, blue.cameraAt(world.time, geo)).y;
  const after = roadCenter(Math.max(0, Math.floor(projected) - 10), Math.min(blue.H - 1, Math.ceil(projected) + 10));
  assert.ok(after - before >= 50 && after - before <= 75, `${after - before} visible pixels per frame`);
});

test('the flight path and biome colours do not jump at cycle boundaries', () => {
  const geo = blue.layout(320);
  for (const time of [8.5, 9.2, blue.CYCLE, blue.CYCLE * 2]) {
    const a = blue.aircraft(time - .001, geo), b = blue.aircraft(time + .001, geo);
    assert.ok(Math.hypot(a.x - b.x, a.y - b.y) < .5);
  }
  for (const boundary of [0, 379500, 759000, 1138500]) {
    const a = blue.terrainAtDistance(boundary - .01), b = blue.terrainAtDistance(boundary + .01);
    for (const key of ['sky', 'far', 'near', 'shade']) {
      assert.ok(a[key].every((value, i) => Math.abs(value - b[key][i]) <= 1));
    }
  }
});

test('encounters are frequent without letting the number of aircraft grow unbounded', () => {
  const geo = blue.layout(320), counts = [];
  for (let t = 0; t < blue.CYCLE; t += .25) counts.push(blue.MISSIONS.filter(spec => blue.enemyAt(t, spec, geo)).length);
  assert.ok(counts.filter(n => n >= 2).length >= counts.length * .9);
  assert.ok(Math.max(...counts) >= 3 && Math.max(...counts) <= 6);
  assert.ok(blue.MISSIONS.filter(spec => spec.hit).length >= 5);
});

test('enemy encounters are more numerous and vary across cycles and seeds', () => {
  const geo = blue.layout(320), counts = [], seed = 12345;
  for (let i = 0; i < 1200; i++) {
    const time = i / 10;
    counts.push(blue.MISSIONS.filter(spec => {
      const e = blue.enemyAt(time, spec, geo, null, seed);
      return e && e.opacity > .2 && !e.exploding;
    }).length);
  }
  counts.sort((a, b) => a - b);
  assert.ok(counts[Math.floor(counts.length / 2)] >= 3, 'at least three attackers are usually visible');
  assert.ok(counts[Math.floor(counts.length * .95)] <= 6, 'encounters remain bounded');
  const spec = blue.MISSIONS[0];
  const sequence = (start, flightSeed) => Array.from({length: 100}, (_, i) => blue.enemyAt(start + i / 10, spec, geo, null, flightSeed));
  assert.notDeepEqual(sequence(0, seed), sequence(blue.CYCLE, seed), 'successive cycles vary');
  assert.notDeepEqual(sequence(blue.CYCLE, seed), sequence(blue.CYCLE, seed + 1), 'session seeds vary encounters');
});

test('rear encounters enter below the picture and recede toward the horizon', () => {
  for (const bottom of [110, 150, 186, 320]) {
    const geo = blue.layout(bottom), seed = 12345;
    const starts = blue.MISSIONS.map(spec => ({spec, first: blue.enemyAt(spec.offset, spec, geo, null, seed)}));
    const rearHit = starts.find(item => item.spec.hit && item.first && item.first.rear);
    const rearEscape = starts.find(item => !item.spec.hit && item.first && item.first.rear);
    assert.ok(rearHit && rearEscape && starts.some(item => item.first && !item.first.rear));
    for (const {spec, first} of [rearHit, rearEscape]) {
      const near = blue.enemyAt(spec.offset + 3.2, spec, geo, null, seed);
      const far = blue.enemyAt(spec.offset + 5.8, spec, geo, null, seed);
      assert.ok(first.y - first.width / 2 > bottom && first.opacity === 0, 'the first frame is outside the visible area');
      assert.ok(near && far && near.y > far.y && near.width > far.width, 'the aircraft rises and shrinks as it recedes');
      assert.ok(far.y < geo.planeY, 'the aircraft reaches the space ahead of the player');
    }
    const {spec: hit} = rearHit, hitTime = hit.offset + blue.HIT;
    const player = blue.aircraft(hitTime - .001, geo, seed);
    const shot = blue.shotAt(hitTime - .001, hit, geo, player, null, seed);
    const explosion = blue.enemyAt(hitTime + .001, hit, geo, null, seed);
    assert.ok(shot && explosion && explosion.exploding && Math.hypot(shot.x - shot.target.x, shot.y - shot.target.y) < 1);
    const {spec: escape} = rearEscape, last = blue.enemyAt(escape.offset + blue.LIFE - .001, escape, geo, null, seed);
    assert.ok(last.x < -last.width || last.x > blue.W + last.width, 'an unhit aircraft escapes through a side');
  }
});

test('enemy drawing is clipped above the dock for every layout', () => {
  const old = globalThis.ImageData;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    for (const bottom of [110, 150, 186, 320]) {
      const rectangles = [], calls = [], ctx = new Proxy({}, {get: (o, k) => {
        if (k === 'rect') return (...args) => { rectangles.push(args); calls.push('rect'); };
        if (k === 'clip') return () => calls.push('clip');
        return o[k] || (() => {});
      }, set: (o, k, v) => (o[k] = v, true)});
      const scene = Object.create(blue.scene), api = {json: null, atlas: null, flightSeed: 12345, view: {bottom}};
      scene.init(api); scene.s.world.time = 3; scene.draw(api, ctx);
      assert.ok(rectangles.some(rect => rect.join(',') === [0, 0, blue.W, bottom].join(',')) && calls.includes('clip'));
    }
  } finally { globalThis.ImageData = old; }
});

test('enemies maneuver vertically and bank with their actual lateral motion', () => {
  const geo = blue.layout(320), signs = new Set(); let climbs = 0, checked = 0;
  for (const spec of blue.MISSIONS) for (let i = 0; i < 1200; i++) {
    const time = i / 20, a = blue.enemyAt(time, spec, geo, null, 12345);
    const b = blue.enemyAt(time + .001, spec, geo, null, 12345);
    if (!a || !b || a.exploding || b.exploding || b.age < a.age) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    if (Math.abs(dx) > .002) { assert.equal(Math.sign(a.bank), Math.sign(dx)); signs.add(Math.sign(dx)); checked++; }
    if (dy < -.001) climbs++;
  }
  assert.ok(checked > 100 && signs.has(-1) && signs.has(1));
  assert.ok(climbs > 10, 'some enemies climb as well as descend');
});

test('enemy bank follows screen motion while the player camera also turns', () => {
  const geo = blue.layout(320), seed = 12345; let checked = 0;
  const state = time => {
    const player = blue.aircraft(time, geo, seed), camera = blue.cameraAt(time, geo, player);
    return {camera, enemyGeo: {...geo, horizon: camera.horizon}};
  };
  for (const spec of blue.MISSIONS) for (let i = 0; i < 900; i++) {
    const time = i / 20, first = state(time), second = state(time + .001);
    const a = blue.enemyAt(time, spec, first.enemyGeo, first.camera, seed);
    const b = blue.enemyAt(time + .001, spec, second.enemyGeo, second.camera, seed);
    if (!a || !b || a.exploding || b.exploding || b.age < a.age) continue;
    const dx = b.x - a.x;
    if (Math.abs(dx) > .003) { assert.equal(Math.sign(a.bank), Math.sign(dx)); checked++; }
  }
  assert.ok(checked > 100);
});

test('maneuvering enemies move continuously and leave the picture before removal', () => {
  const geo = blue.layout(320);
  for (const seed of [1, 7, 12345]) for (const spec of blue.MISSIONS) for (let i = 0; i < 1800; i++) {
    const at = time => {
      const player = blue.aircraft(time, geo, seed), camera = blue.cameraAt(time, geo, player);
      return blue.enemyAt(time, spec, {...geo, horizon: camera.horizon}, camera, seed);
    };
    const a = at(i / 30), b = at((i + 1) / 30);
    if (a && b && b.age > a.age && !a.exploding && !b.exploding) {
      assert.ok(Math.abs(b.x - a.x) < 11 && Math.abs(b.y - a.y) < 5);
    }
    if (a && !b && !a.exploding && a.opacity > .1) {
      assert.ok(a.x < -a.width || a.x > blue.W + a.width, 'an unhit enemy leaves the edge before disappearing');
    }
  }
});

test('the existing enemy sprites visibly bank in both directions', () => {
  const old = globalThis.ImageData;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    const frames = {}, anchors = {};
    for (const m of [0, 1]) for (const n of [5, 7, 10, 14, 18, 24, 32, 42, 54]) {
      frames[`enemy-${m}-${n}`] = [0, 0, 10, 10]; anchors[`enemy-${m}-${n}`] = [5, 5];
    }
    const angles = [], ctx = new Proxy({}, {get: (o, k) => k === 'rotate' ? value => angles.push(value) : o[k] || (() => {}), set: (o, k, v) => (o[k] = v, true)});
    const api = {json: {frames, anchors}, atlas: {}, flightSeed: 12345, view: {bottom: 320}};
    const scene = Object.create(blue.scene); scene.init(api);
    for (const time of [3, 4, 5]) { scene.s.world.time = time; scene.draw(api, ctx); }
    assert.ok(angles.some(value => value > .02) && angles.some(value => value < -.02));
  } finally { globalThis.ImageData = old; }
});

test('a shot starts at the plane, reaches its moving target and becomes an explosion', () => {
  const spec = blue.MISSIONS.find(x => x.hit), geo = blue.layout(320);
  const start = blue.shotAt(spec.offset + blue.HIT - blue.SHOT, spec, geo, blue.aircraft(spec.offset + blue.HIT - blue.SHOT, geo));
  assert.equal(start.t, 0);
  const justBefore = spec.offset + blue.HIT - .001;
  const shot = blue.shotAt(justBefore, spec, geo, blue.aircraft(justBefore, geo));
  assert.ok(Math.hypot(shot.x - shot.target.x, shot.y - shot.target.y) < 1);
  const hit = blue.enemyAt(spec.offset + blue.HIT + .001, spec, geo);
  assert.equal(hit.exploding, true);
  assert.equal(blue.shotAt(spec.offset + blue.HIT + .001, spec, geo, blue.aircraft(0, geo)), null);
  assert.equal(blue.enemyAt(spec.offset + blue.HIT + blue.EXPLOSION + .01, spec, geo), null);
  const camera = blue.cameraAt(justBefore, geo), cameraGeo = {...geo, horizon: camera.horizon};
  const movingShot = blue.shotAt(justBefore, spec, cameraGeo, camera.player, camera);
  const movingTarget = blue.enemyAt(justBefore, spec, cameraGeo, camera);
  assert.ok(Math.hypot(movingShot.x - movingTarget.x, movingShot.y - movingTarget.y) < 1, 'the shot follows the target while the camera banks');
});

test('shots keep tracking the same maneuvering enemy across different flight seeds', () => {
  const geo = blue.layout(320);
  for (const seed of [1, 7, 12345]) for (const spec of blue.MISSIONS.filter(s => s.hit)) {
    const time = spec.offset + blue.HIT - .01, player = blue.aircraft(time, geo, seed);
    const camera = blue.cameraAt(time, geo, player), cameraGeo = {...geo, horizon: camera.horizon};
    const enemy = blue.enemyAt(time, spec, cameraGeo, camera, seed);
    const shot = blue.shotAt(time, spec, cameraGeo, player, camera, seed, enemy);
    assert.ok(enemy && shot && shot.target === enemy);
    assert.ok(Math.hypot(shot.x - enemy.x, shot.y - enemy.y) < 2);
  }
});

test('unhit aircraft leave through the edge and individual cycles restart invisibly', () => {
  const spec = blue.MISSIONS.find(x => !x.hit), geo = blue.layout(320);
  assert.equal(blue.enemyAt(spec.offset, spec, geo).opacity, 0);
  const last = blue.enemyAt(spec.offset + blue.LIFE - .001, spec, geo);
  assert.ok(last.x < -20 || last.x > blue.W + 20);
  assert.equal(blue.enemyAt(spec.offset + blue.LIFE + .01, spec, geo), null);
  let next = null;
  for (let t = spec.offset + blue.CYCLE - 1; t < spec.offset + blue.CYCLE + 1; t += .001) {
    const e = blue.enemyAt(t, spec, geo);
    if (e && e.age >= 0 && e.age < .0011) { next = e; break; }
  }
  assert.ok(next && next.opacity < .001, 'a jittered encounter still starts invisibly');
});

test('the terrain closes continuously and the ground actually moves', () => {
  for (const key of ['sky', 'far', 'near', 'shade']) assert.deepEqual(blue.terrainAt(0)[key], blue.terrainAt(165)[key]);
  const a = new Uint32Array(blue.W * blue.H), b = new Uint32Array(a.length), world = blue.makeWorld(), geo = blue.layout(320);
  blue.paintBackdrop(a, world, geo);
  for (let i = 0; i < 30; i++) blue.stepWorld(world, 1 / 30);
  blue.paintBackdrop(b, world, geo);
  let changed = 0;
  for (let i = geo.horizon * blue.W; i < a.length; i++) if (a[i] !== b[i]) changed++;
  assert.ok(changed > 5000, `${changed} pixels changed after a second`);
  assert.ok(world.distance >= 2600);
});

test('fields, desert and water have different shapes, not just different colours', () => {
  const geo = blue.layout(320);
  const images = [10000, 389500, 769000].map(distance => {
    const pixels = new Uint32Array(blue.W * blue.H), world = {time: distance / 1000, distance, boost: 0};
    blue.paintBackdrop(pixels, world, geo);
    return pixels;
  });
  const kinds = [10000, 389500, 769000].map(blue.terrainAtDistance).map(t => t.kind);
  assert.deepEqual(kinds, ['fields', 'desert', 'water']);
  for (const [a, b] of [[0,1], [1,2], [0,2]]) {
    let different = 0, edges = 0;
    for (let y = geo.horizon + 8; y < blue.H; y++) for (let x = 1; x < blue.W; x++) {
      const i = y * blue.W + x;
      const edgeA = images[a][i] !== images[a][i-1], edgeB = images[b][i] !== images[b][i-1];
      if (edgeA !== edgeB) different++;
      if (edgeA || edgeB) edges++;
    }
    assert.ok(edges > 100 && different / edges > .5, `the ground geometry differs at ${(different / edges * 100).toFixed(1)}% of visible edges`);
  }
});

test('water has continuous bands and broken crests instead of large checkerboard blocks', () => {
  const geo = blue.layout(320), world = {time: 0, distance: 769000, boost: 0};
  const pixels = new Uint32Array(blue.W * blue.H); blue.paintBackdrop(pixels, world, geo);
  let calmRows = 0, crestRows = 0, rows = 0;
  for (let y = geo.horizon + 15; y < blue.H; y++) {
    let edges = 0;
    for (let x = 1; x < blue.W; x++) if (pixels[y * blue.W + x] !== pixels[y * blue.W + x - 1]) edges++;
    rows++; if (edges <= 1) calmRows++; if (edges >= 2) crestRows++;
  }
  assert.ok(calmRows / rows > .45, 'water has broad continuous tones');
  assert.ok(crestRows > 5, 'water still has visible broken crests');
});

test('the broad water colour does not jump abruptly between adjacent rows', () => {
  const geo = blue.layout(320), pixels = new Uint32Array(blue.W * blue.H);
  blue.paintBackdrop(pixels, {time: 0, distance: 769000, boost: 0}, geo);
  let previous = null;
  for (let y = geo.horizon + 15; y < blue.H; y++) {
    const counts = new Map();
    for (let x = 0; x < blue.W; x++) {
      const colour = pixels[y * blue.W + x]; counts.set(colour, (counts.get(colour) || 0) + 1);
    }
    const [colour] = [...counts].sort((a, b) => b[1] - a[1])[0];
    if (previous !== null) {
      const delta = [0, 8, 16].map(shift => Math.abs((colour >>> shift & 255) - (previous >>> shift & 255)));
      assert.ok(Math.max(...delta) <= 4, `a water edge jumps by ${Math.max(...delta)} colour levels at row ${y}`);
    }
    previous = colour;
  }
});

test('moving water limits one-frame flashes at cruising speed', () => {
  const geo = blue.layout(320), camera = blue.cameraAt(0, geo), world = {time: 0, distance: 769000, boost: 0};
  const buffers = Array.from({length: 3}, () => new Uint32Array(blue.W * blue.H)), shares = [];
  blue.paintBackdrop(buffers[0], world, geo, camera); blue.stepWorld(world, 1 / 30);
  blue.paintBackdrop(buffers[1], world, geo, camera);
  for (let frame = 2; frame < 92; frame++) {
    blue.stepWorld(world, 1 / 30); blue.paintBackdrop(buffers[2], world, geo, camera);
    let reverting = 0, total = 0;
    for (let y = geo.horizon + 10; y < blue.H; y++) for (let x = 0; x < blue.W; x++) {
      const i = y * blue.W + x; total++;
      if (buffers[0][i] === buffers[2][i] && buffers[0][i] !== buffers[1][i]) reverting++;
    }
    shares.push(reverting / total);
    buffers.push(buffers.shift());
  }
  shares.sort((a, b) => a - b);
  assert.ok(shares[Math.floor(shares.length * .95)] < .04 && shares.at(-1) < .06, 'brief colour reversals stay limited');
});

test('ground details match their biome and approach continuously with bounded work', () => {
  const geo = blue.layout(320);
  for (const [distance, expected] of [[10000, 'tree'], [389500, 'mesa'], [769000, 'ship']]) {
    const features = blue.groundFeatures({time: distance / 1000, distance}, geo);
    assert.ok(features.some(feature => feature.type === expected), `${expected} is visible`);
    assert.ok(features.length <= 32);
    const first = features.find(feature => feature.type === expected && feature.y < geo.planeY - 15);
    assert.ok(first);
    const later = blue.groundFeatures({time: distance / 1000 + .2, distance: distance + 200}, geo)
      .find(feature => feature.id === first.id);
    assert.ok(later && later.y > first.y, 'a fixed detail approaches rather than jumping');
  }
});

test('ground details are spread across the scene without unbounded density', () => {
  const geo = blue.layout(320), counts = []; let total = 0, outsideCenter = 0;
  const world = {time: 0, distance: 10000, boost: 0, seed: 12345};
  for (let i = 0; i < 450; i++) {
    const visible = blue.groundFeatures(world, geo).filter(f => f.x >= 0 && f.x <= blue.W && f.opacity > .2);
    counts.push(visible.length);
    for (const f of visible) { total++; if (f.x < 80 || f.x > 120) outsideCenter++; }
    blue.stepWorld(world, 1 / 30);
  }
  counts.sort((a, b) => a - b);
  assert.ok(outsideCenter / total > .45, `${(outsideCenter / total * 100).toFixed(1)}% outside the centre`);
  assert.ok(counts[Math.floor(counts.length / 2)] >= 5 && counts[Math.floor(counts.length * .95)] <= 16);
});

test('nearby ground details leave through the bottom smoothly instead of disappearing inside the picture', () => {
  const geo = blue.layout(320), id = '1:-1:1:0';
  const time = 1.133;
  const featureAt = distance => blue.groundFeatures({time, distance}, geo).find(feature => feature.id === id);
  const before = featureAt(600), after = featureAt(633);
  assert.ok(before && after, 'a fully visible tree stays in the picture while it approaches');
  assert.ok(after.y > before.y && after.y < blue.H - 32);
  assert.equal(after.opacity, 1);
  let previous = after;
  for (let distance = 637; distance < 1800; distance += 4) {
    const current = featureAt(distance);
    if (!current) {
      const camera = blue.cameraAt(time, geo);
      const screenY = previous.y + camera.roll * (previous.x - 100);
      assert.ok(screenY > blue.H - 3 && previous.opacity < .03, 'the detail fades at the bottom before being removed');
      return;
    }
    assert.ok(current.y > previous.y);
    assert.ok(current.opacity <= previous.opacity);
    previous = current;
  }
  assert.fail('the detail should eventually leave the picture');
});

test('ground details have faded before they can cross the bottom in one fast frame', () => {
  const geo = blue.layout(320);
  for (const distance of [10000, 389500, 769000]) {
    const world = {time: 0, distance, boost: 0};
    let previous = blue.groundFeatures(world, geo);
    for (let i = 0; i < 180; i++) {
      const camera = blue.cameraAt(world.time, geo);
      blue.stepWorld(world, 1 / 30);
      const current = blue.groundFeatures(world, geo), ids = new Set(current.map(f => f.id));
      const previousIds = new Set(previous.map(f => f.id));
      for (const f of current) {
        if (!previousIds.has(f.id) && f.x >= 0 && f.x <= blue.W && f.y > geo.horizon + 10) {
          assert.ok(f.opacity < .2, `${f.id} would appear with opacity ${f.opacity}`);
        }
      }
      for (const f of previous) {
        const screenY = f.y + camera.roll * (f.x - 100);
        if (!ids.has(f.id) && f.x > 20 && f.x < 180 && screenY < blue.H - 20) {
          assert.ok(f.opacity < .2, `${f.id} would disappear with opacity ${f.opacity}`);
        }
      }
      previous = current;
    }
  }
});

test('fast terrain streams in coherent patches instead of flashing into new noise every frame', () => {
  const a = new Uint32Array(blue.W * blue.H), b = new Uint32Array(a.length), world = blue.makeWorld(), geo = blue.layout(320);
  blue.paintBackdrop(a, world, geo);
  blue.stepWorld(world, 1 / 30);
  blue.paintBackdrop(b, world, geo);
  let changed = 0, total = 0;
  for (let y = geo.horizon + 5; y < blue.H; y++) for (let x = 0; x < blue.W; x++) {
    total++;
    if (a[y * blue.W + x] !== b[y * blue.W + x]) changed++;
  }
  assert.ok(changed > total * .02 && changed < total * .35, `${(changed / total * 100).toFixed(1)}% changed in one frame`);
});

test('the full drawing path works with fictional atlas data and without any atlas', () => {
  const old = globalThis.ImageData;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    const frames = {}, anchors = {};
    for (const name of ['player-0','player-1','player-2','player-3','player-4','player-5', ...[0,1].flatMap(m => [5,7,10,14,18,24,32,42,54].map(n => `enemy-${m}-${n}`)), ...[12,18,26,38,55,80,110].map(n => `mesa-${n}`), ...[10,16,24,36,52,72].map(n => `ship-${n}`)]) {
      frames[name] = [0, 0, 10, 10]; anchors[name] = [5, 5];
    }
    const calls = [];
    const ctx = new Proxy({}, {get: (o, k) => o[k] || ((...args) => { calls.push(k); }), set: (o,k,v) => (o[k] = v, true)});
    for (const withAtlas of [false, true]) {
      const scene = Object.create(blue.scene), api = {json: withAtlas ? {frames, anchors} : null, atlas: withAtlas ? {} : null, view: {bottom: 186}};
      scene.init(api);
      for (const t of [0, 7.5, 8.2, 22, 40, 75]) { scene.s.world.time = t; scene.s.world.distance = t * 305; scene.draw(api, ctx); }
      scene.poke(api, 20, 20); assert.equal(scene.s.world.boost, 3);
      scene.step(api, 1 / 30); assert.ok(scene.s.world.boost < 3);
    }
    assert.ok(calls.includes('putImageData'));
    assert.ok(calls.includes('drawImage'));
  } finally { globalThis.ImageData = old; }
});

test('climbing and diving visibly transform the aircraft in opposite directions', () => {
  const old = globalThis.ImageData;
  globalThis.ImageData = class { constructor(w, h) { this.data = new Uint8ClampedArray(w * h * 4); } };
  try {
    const scales = [];
    const ctx = new Proxy({}, {get: (o, k) => k === 'scale' ? (x, y) => scales.push([x, y]) : o[k] || (() => {}), set: (o, k, v) => (o[k] = v, true)});
    const seed = 12345, geo = blue.layout(320);
    const scene = Object.create(blue.scene), api = {json: null, atlas: null, flightSeed: seed, view: {bottom: 320}};
    scene.init(api);
    for (const direction of [-1, 1]) {
      const time = Array.from({length: 7200}, (_, i) => i / 30).find(t => blue.aircraft(t, geo, seed).pitch * direction > .6);
      assert.notEqual(time, undefined);
      scene.s.world.time = time; scene.draw(api, ctx);
    }
    assert.ok(scales.some(([x, y]) => x === 1 && y > 1.04));
    assert.ok(scales.some(([x, y]) => x === 1 && y < .96));
  } finally { globalThis.ImageData = old; }
});
