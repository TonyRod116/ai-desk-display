/* Tests for the tablet's DEEP BLUE underwater pixel-art scene (token_tv/tablet_web/game-underwater.js). */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const engine = require('../token_tv/tablet_web/stage-game.js');
globalThis.TabletGames = engine;
const uw = require('../token_tv/tablet_web/game-underwater.js');

function fakeCanvas() {
  const calls = { fillRect: 0, fill: 0, drawImage: 0 };
  return {
    calls,
    g: {
      fillStyle: '#000',
      fillRect(x, y, w, h) {
        assert.ok(Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(w) && Number.isFinite(h));
        calls.fillRect++;
      },
      beginPath() {},
      moveTo(x, y) { assert.ok(Number.isFinite(x) && Number.isFinite(y)); },
      lineTo(x, y) { assert.ok(Number.isFinite(x) && Number.isFinite(y)); },
      closePath() {},
      fill() { calls.fill++; },
      drawImage() { calls.drawImage++; },
    },
  };
}

function fakeImageBuf(w, h) {
  const data = new Uint8ClampedArray(w * h * 4);
  const img = { data, width: w, height: h };
  return {
    canvas: { width: w, height: h },
    g: { putImageData() {} },
    img,
    u32: new Uint32Array(data.buffer),
  };
}

test('underwater registers cleanly as a 267 x 427 crt-clear scene', () => {
  const scene = engine.registry.underwater;
  assert.ok(scene, 'underwater scene registered');
  assert.deepEqual(scene.size, [267, 427]);
  assert.equal(scene.post, 'crt-clear');
});

test('surface wave field and volumetric sunbeams animate smoothly over time', () => {
  const s0 = uw.surfaceWave(144, 22, 0);
  const s1 = uw.surfaceWave(144, 22, 1.5);
  assert.notEqual(s0, s1, 'surface ripples move over time');
  assert.ok(uw.surfaceWave(144, 6, 0) > uw.surfaceWave(144, 88, 0), 'Snell window brightest near top');
  const r0 = uw.rayAt(uw.RAYS[2], 0);
  const r1 = uw.rayAt(uw.RAYS[2], 2.0);
  assert.notEqual(r0.topX, r1.topX, 'sunbeams sway smoothly');
  assert.ok(uw.inSunbeam(148, 120, 0) > 0, 'mid-water sunbeam illumination detectable');
});

test('world simulation is deterministic, keeps diver in view and runs diving events', () => {
  const a = uw.createWorld(777);
  const b = uw.createWorld(777);
  for (let i = 0; i < 360; i++) {
    uw.stepWorld(a, uw.STEP, 290);
    uw.stepWorld(b, uw.STEP, 290);
  }
  assert.equal(a.diver.x, b.diver.x);
  assert.equal(a.diver.y, b.diver.y);
  assert.ok(a.diver.y >= 88 && a.diver.y <= 290, 'diver stays within visible view window');
  assert.ok(a.stats.breaths >= 2, 'diver exhales periodic bubble clusters');
  assert.ok(a.stats.rings >= 1, 'diver blows rising scuba bubble rings');
  assert.ok(a.stats.chestOpens >= 1, 'treasure chest opens with gold coins');
  assert.equal(a.sardines.length, 20, 'shimmering 20-sardine bait-ball active');
});

test('context-aware touch pokes trigger chest coins, octopus ink, clam snap and bubble rings', () => {
  const w = uw.createWorld(99);
  uw.pokeWorld(w, uw.CHEST.x, uw.CHEST.y);
  assert.equal(w.stats.chestOpens, 1);
  assert.ok(w.coins.length > 0, 'chest tap releases spinning gold coins');

  uw.pokeWorld(w, w.octopus.x, w.octopus.y);
  assert.equal(w.stats.inks, 1);
  assert.ok(w.octopus.inks.length > 0, 'octopus tap releases indigo ink cloud');

  uw.pokeWorld(w, uw.CLAM.x, uw.CLAM.y);
  assert.ok(w.clam.timer > 0, 'clam tap snaps shell closed');

  const ringsBefore = w.stats.rings;
  uw.pokeWorld(w, 160, 140);
  assert.equal(w.stats.rings, ringsBefore + 1, 'open-water tap launches a rising bubble ring');
  assert.deepEqual(w.diver.target, [160, 140]);
});

test('all four time-of-day phases and high/low tiers draw cleanly with atlas plates', () => {
  const frames = { bg: [0, 0, 267, 427], fg: [268, 0, 267, 427] };
  for (const phase of ['day', 'dawn', 'dusk', 'night']) {
    const world = uw.createWorld(4242);
    for (let i = 0; i < 60; i++) uw.stepWorld(world, uw.STEP, 427);
    for (const tier of ['high', 'low']) {
      const cv = fakeCanvas();
      uw.renderFrame(cv.g, { world, atlas: 'atlas', frames, phase }, tier);
      assert.ok(cv.calls.fillRect > 500, `${phase}/${tier} draws full animated frame`);
      assert.equal(cv.calls.drawImage, 2, `${phase}/${tier} composites bg and fg plates`);
    }
  }
  assert.equal(uw.phaseFromClock(new Date(2026, 5, 1, 13, 0)), 'day');
  assert.equal(uw.phaseFromClock(new Date(2026, 5, 1, 7, 0)), 'dawn');
  assert.equal(uw.phaseFromClock(new Date(2026, 5, 1, 19, 30)), 'dusk');
  assert.equal(uw.phaseFromClock(new Date(2026, 5, 1, 23, 0)), 'night');
});

test('offscreen buffers and 16-bit sprite atlas keep per-frame draw calls under 450 for smooth tablet 30 fps', () => {
  const frames = { bg: [0, 0, 267, 427], fg: [268, 0, 267, 427] };
  const addDir = (p, n, w, h) => { for (let i = 0; i < n; i++) { frames[`${p}_${i}_r`] = [0, 428, w, h]; frames[`${p}_${i}_l`] = [0, 428, w, h]; } };
  const addSym = (p, n, w, h) => { for (let i = 0; i < n; i++) frames[`${p}_${i}`] = [0, 428, w, h]; };
  addDir('diver', 12, 58, 32); addDir('whale', 8, 108, 40); addDir('manta', 8, 70, 32);
  addDir('shark', 8, 66, 26); addDir('dolphin', 10, 54, 24); addDir('turtle', 10, 40, 24);
  addDir('fish_teal', 6, 20, 14); addDir('fish_crimson', 6, 20, 14); addDir('fish_clown', 6, 20, 14);
  addSym('octo', 10, 34, 28); addSym('jelly_pink', 8, 26, 40); addSym('jelly_cyan', 8, 26, 40);
  addSym('chest', 5, 34, 28); addSym('clam', 5, 28, 22);
  const world = uw.createWorld(4242);
  const surfBuf = fakeImageBuf(uw.SW, uw.SH);
  const causticBuf = fakeImageBuf(uw.CW, uw.CH);
  const backdrops = { day: 'bd-day', dawn: 'bd-dawn', dusk: 'bd-dusk', night: 'bd-night' };
  const state = {
    world, atlas: 'atlas', frames, phase: 'day',
    backdrops, surfBuf, causticBuf,
    surfTick: -99, surfPhase: '', causticTick: -99, causticPhase: '',
  };
  let maxCalls = 0;
  for (let i = 0; i < 60; i++) {
    uw.stepWorld(world, uw.STEP, 427);
    const cv = fakeCanvas();
    uw.renderFrame(cv.g, state, 'high');
    const total = cv.calls.fillRect + cv.calls.fill + cv.calls.drawImage;
    if (total > maxCalls) maxCalls = total;
    assert.ok(cv.calls.drawImage >= 20, `expected baked sprites + buffers via drawImage, got ${cv.calls.drawImage}`);
  }
  assert.ok(maxCalls < 450, `expected < 450 draw calls/frame with offscreen buffers + sprite atlas, got ${maxCalls}`);
  assert.ok(surfBuf.u32.some((px) => px !== 0), 'surface ImageData buffer rendered non-zero pixels');
  assert.ok(causticBuf.u32.some((px) => px !== 0), 'caustic ImageData buffer rendered non-zero pixels');
});

test('directional swimmers match velocity direction and fall back gracefully on stale 2-frame atlases', () => {
  const frames = {
    bg: [0, 0, 267, 427], fg: [268, 0, 267, 427],
    dolphin_0_r: [10, 500, 54, 24], dolphin_1_r: [70, 500, 54, 24],
    dolphin_0_l: [130, 500, 54, 24], dolphin_1_l: [190, 500, 54, 24],
    whale_0_r: [10, 540, 108, 40], whale_0_l: [130, 540, 108, 40],
    shark_0_r: [10, 590, 66, 26], shark_0_l: [130, 590, 66, 26],
  };
  const world = uw.createWorld(7);
  world.dolphin = { x: 130, y: 110, vx: -0.9, vy: 0, animPh: 2.8, cooldown: 0 };
  world.megafauna = { kind: 'whale', x: 140, y: 150, vx: 0.2, animPh: 3.1, cooldown: 0 };
  world.shark = { x: 120, y: 185, vx: -0.5, animPh: 4.0, cooldown: 0 };

  const drawn = [];
  const g = {
    fillStyle: '#000',
    fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {}, fill() {},
    drawImage(_img, sx, sy, sw, sh) { drawn.push([sx, sy, sw, sh]); },
  };
  uw.renderFrame(g, { world, atlas: 'atlas', frames, phase: 'day' }, 'high');

  // Dolphin moving left with phase > 1 must gracefully reuse dolphin_0_l / dolphin_1_l (sx 130 or 190)!
  assert.ok(drawn.some(([sx, sy]) => sy === 500 && (sx === 130 || sx === 190)), 'dolphin facing left picks _l sprite even on stale 2-frame atlas');
  // Whale moving right picks whale_0_r (sx 10)!
  assert.ok(drawn.some(([sx, sy]) => sy === 540 && sx === 10), 'whale facing right picks _r sprite');
  // Shark moving left picks shark_0_l (sx 130)!
  assert.ok(drawn.some(([sx, sy]) => sy === 590 && sx === 130), 'shark facing left picks _l sprite');

  // Now flip dolphin right and confirm it switches to _r!
  drawn.length = 0;
  world.dolphin.vx = 0.9;
  uw.renderFrame(g, { world, atlas: 'atlas', frames, phase: 'day' }, 'high');
  assert.ok(drawn.some(([sx, sy]) => sy === 500 && (sx === 10 || sx === 70)), 'dolphin facing right picks _r sprite');
});

test('tapping dark temple rooms guides diver through entrance, lights full room, preserves 3D column order & triggers relic magic', () => {
  const frames = {
    bg: [0, 0, 267, 427], fg: [268, 0, 267, 427],
    room_left_lit: [0, 900, 106, 134], occ_left: [110, 900, 122, 174],
    room_right_lit: [240, 900, 51, 98], occ_right: [300, 900, 59, 146],
  };
  for (let i = 0; i < 12; i++) {
    frames[`diver_${i}_r`] = [0, 500, 58, 32];
    frames[`diver_${i}_l`] = [60, 500, 58, 32];
  }
  const w = uw.createWorld(321);
  // Tap inside Left Atlantis Sanctuary -> diver must approach entrance FIRST, then enter behind columns!
  uw.pokeWorld(w, 66, 268);
  assert.equal(w.diver.visit.id, 'left');
  assert.equal(w.diver.visit.stage, 'approach');

  let entered = false, maxLight = 0, inspectedOrder = null;
  for (let i = 0; i < 420; i++) {
    uw.stepWorld(w, uw.STEP, 427);
    if (w.diver.inRoom === 'left') entered = true;
    if (w.rooms.left.light > maxLight) maxLight = w.rooms.left.light;
    if (w.diver.visit && w.diver.visit.stage === 'inspect' && w.rooms.left.light > 0.7 && !inspectedOrder) {
      const order = [];
      const g = {
        fillStyle: '#000', globalAlpha: 1,
        fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {}, fill() {},
        drawImage(_img, sx, sy) {
          if (sy === 900 && sx === 0) order.push('room_left_lit');
          else if (sy === 500) order.push('diver');
          else if (sy === 900 && sx === 110) order.push('occ_left');
        },
      };
      uw.renderFrame(g, { world: w, atlas: 'atlas', frames, phase: 'day' }, 'high');
      inspectedOrder = order;
    }
  }
  assert.ok(entered, 'diver entered the left ancient chamber');
  assert.ok(maxLight > 0.85, `whole left room illuminated smoothly (got ${maxLight})`);
  assert.ok(w.stats.roomVisits >= 1, 'recorded completed room entry');
  assert.ok(w.stats.roomInteractions >= 1, 'diver interacted with the Atlantean crystal relic');
  assert.deepEqual(inspectedOrder, ['room_left_lit', 'diver', 'occ_left'], '3D order: lit cave wall BEHIND diver, front columns IN FRONT of diver');

  // Now tap Right Poseidon Vault: if still inside Left, diver MUST exit Left entrance first with `queued = 'right'`!
  uw.pokeWorld(w, 250, 290);
  assert.ok(w.diver.visit.id === 'right' || (w.diver.visit.id === 'left' && w.diver.visit.queued === 'right'), 'respects 3D walls by exiting left entrance before swimming to right vault');
  let maxRightLight = 0, maxEel = 0;
  for (let i = 0; i < 620; i++) {
    uw.stepWorld(w, uw.STEP, 427);
    if (w.rooms.right.light > maxRightLight) maxRightLight = w.rooms.right.light;
    if (w.rooms.right.eel > maxEel) maxEel = w.rooms.right.eel;
  }
  assert.ok(maxRightLight > 0.85, `whole right Poseidon vault illuminated smoothly (got ${maxRightLight})`);
  assert.ok(maxEel > 0.6, `friendly cave moray eel emerged when vault lit (got ${maxEel})`);
  assert.ok(w.stats.roomInteractions >= 2, 'diver also interacted inside right Poseidon vault');
});

test('treasure chest coins fade smoothly to transparent in <= 0.5 seconds instead of vanishing abruptly', () => {
  assert.ok(uw.COIN_FADE > 0 && uw.COIN_FADE <= 0.5, `coin fade duration <= 0.5s (got ${uw.COIN_FADE})`);
  const w = uw.createWorld(55);
  uw.triggerChest(w);
  assert.ok(w.coins.length > 0);
  let sawPartialFade = false;
  for (let i = 0; i < 240; i++) {
    uw.stepWorld(w, uw.STEP, 427);
    if (w.coins.some((c) => c.landed && c.fade > 0.1 && c.fade < 0.9)) sawPartialFade = true;
  }
  assert.ok(sawPartialFade, 'coins transition through partial transparency before disappearing');
});

test('real ray-refraction caustics render pure translucent white bands + focused sharp white peaks that morph over time', () => {
  const buf = fakeImageBuf(uw.CW, uw.CH);
  uw.updateCausticBuffer(buf, uw.PALETTES.day, 1.2);
  const d0 = Uint8ClampedArray.from(buf.img.data);
  let softCount = 0, sharpCount = 0, coloredCount = 0;
  for (let k = 0; k < d0.length; k += 4) {
    const r = d0[k], g = d0[k + 1], b = d0[k + 2], a = d0[k + 3];
    if (a < 10) continue;
    if (a <= 90) softCount++;
    if (a >= 145) sharpCount++;
    if (r < 235 || g < 235 || b < 235) coloredCount++;
  }
  assert.ok(softCount > 400, `expected wide soft semi-transparent defocused caustic bands (got ${softCount})`);
  assert.ok(sharpCount > 80, `expected focused bright white caustic filaments & crossings (got ${sharpCount})`);
  assert.equal(coloredCount, 0, `expected pure white + transparency with zero blue/yellow tint (got ${coloredCount})`);

  // Verify dynamic refraction morphing (not a static frozen pattern)
  uw.updateCausticBuffer(buf, uw.PALETTES.day, 2.4);
  let diff = 0;
  for (let k = 3; k < d0.length; k += 4) if (Math.abs(buf.img.data[k] - d0[k]) > 25) diff++;
  assert.ok(diff > 1000, `expected caustics to continuously merge, defocus & refocus over time (diff=${diff})`);
});

test('dawn, dusk and night dramatically darken the reef while boosting headlamp and bioluminescence', () => {
  assert.equal(uw.PALETTES.day.veilMid, null, 'day keeps full sunlit clarity with zero dark veil');
  assert.ok(uw.PALETTES.dawn.veilMid, 'dawn adds golden-blue atmospheric wash');
  assert.ok(uw.PALETTES.dusk.veilMid && uw.PALETTES.dusk.bioCoral && uw.PALETTES.dusk.bioRipple, 'dusk darkens reef and wakes bioluminescence');
  assert.ok(uw.PALETTES.night.veilMid && uw.PALETTES.night.bioCoral && uw.PALETTES.night.bioRipple, 'night applies midnight veil + full bioluminescence');
  assert.ok(uw.PALETTES.night.causticAlphaMax < uw.PALETTES.dusk.causticAlphaMax && uw.PALETTES.dusk.causticAlphaMax < uw.PALETTES.day.causticAlphaMax,
    'caustic intensity steps down from bright sunlit day to dusk and gentle silver moon-caustics at night');
  assert.ok(uw.PALETTES.night.torchGain > uw.PALETTES.dusk.torchGain && uw.PALETTES.dusk.torchGain > uw.PALETTES.day.torchGain,
    'diver headlamp steps up dramatically from day to dusk and night');
});

test('scene lifecycle init, step, poke and draw never throw', () => {
  const scene = uw.scene;
  const api = {
    random: uw.seeded(12),
    view: { top: 0, bottom: 290 },
    tier: 'high',
    atlas: 'atlas',
    json: { frames: { bg: [0, 0, 267, 427], fg: [268, 0, 267, 427] } },
  };
  scene.dbg = { phase: 'day' };
  scene.init(api);
  for (let i = 0; i < 30; i++) scene.step(api, uw.STEP);
  scene.poke(api, 160, 170);
  const cv = fakeCanvas();
  scene.draw(api, cv.g);
  assert.ok(cv.calls.fillRect > 500);
  assert.equal(cv.calls.drawImage, 2);
});
