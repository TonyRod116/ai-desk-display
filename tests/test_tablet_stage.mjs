import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';

// The tablet's scene stage and its three looks: the pure logic (geometry, drift, quality governor, scene info checks, per-look helpers),
// static guards that every shader uniform the code sets is declared and that no look reaches for eval or the network, and the whole
// scene lifecycle on a fake DOM without WebGL (the fallback tier). What a GPU does with the shaders is checked by eye with
// a separate browser preview, not here.
const require = createRequire(import.meta.url);
const web = new URL('../token_tv/tablet_web/', import.meta.url);
const core = require('../token_tv/tablet_web/scene-stage.js');
const crt = require('../token_tv/tablet_web/stage-crt.js');
const lcd = require('../token_tv/tablet_web/stage-lcd.js');
const photo = require('../token_tv/tablet_web/stage-photo.js');
const live = require('../token_tv/tablet_web/stage-live.js');
const {containRect, monitorLayout, coverRect, driftState, driftDirection, sourceGrid, stepLevel, parseFx, normalizeInfo, Governor, LEVELS, GOVERNOR, DRIFT} = core;

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} is not ${b}`);
const AREAS = [{left: 31, top: 100, width: 738, height: 554}, {left: 105, top: 100, width: 590, height: 443}, {left: 0, top: 0, width: 800, height: 720},
               {left: 12, top: 40, width: 300, height: 700}, {left: 0, top: 0, width: 1200, height: 400}];

test('contain: the whole picture fits, centred, never stretched', () => {
  for (const area of AREAS) for (const [w, h] of [[640, 480], [320, 240], [768, 960], [1920, 1080]]) {
    const r = containRect(area.width, area.height, w, h);
    assert.ok(r.w <= area.width + 1e-9 && r.h <= area.height + 1e-9, 'inside');
    close(r.w / r.h, w / h);
    close(r.x, (area.width - r.w) / 2); close(r.y, (area.height - r.h) / 2);
    assert.ok(Math.abs(r.w - area.width) < 1e-6 || Math.abs(r.h - area.height) < 1e-6, 'as big as it can be');
  }
});

test('a monitor (screen plus equal bezel) is contained in the area, centred, with the media aspect and as large as possible', () => {
  for (const area of AREAS) for (const [w, h] of [[640, 480], [320, 240], [800, 600]]) {
    for (const f of [0.014, 0.034]) {
      const m = monitorLayout(area, w, h, f);
      const {frame, screen, bezel} = m;
      assert.ok(frame.x >= area.left - 1e-9 && frame.y >= area.top - 1e-9, 'frame starts inside');
      assert.ok(frame.x + frame.w <= area.left + area.width + 1e-9 && frame.y + frame.h <= area.top + area.height + 1e-9, 'frame ends inside');
      close(screen.w / screen.h, w / h);
      close(bezel, f * screen.w);
      close(screen.x - frame.x, bezel); close(frame.x + frame.w - (screen.x + screen.w), bezel);
      close(screen.y - frame.y, bezel); close(frame.y + frame.h - (screen.y + screen.h), bezel);
      close(frame.x + frame.w / 2, area.left + area.width / 2); close(frame.y + frame.h / 2, area.top + area.height / 2);
      assert.ok(Math.abs(frame.w - area.width) < 1e-6 || Math.abs(frame.h - area.height) < 1e-6, 'touches the area on one axis');
    }
  }
});

test('cover: the area is always covered, the picture is never stretched and the focus stays in view', () => {
  const focuses = [[0.5, 0.5], [0, 0], [1, 1], [0.2, 0.9], [0.5, 0.55]];
  for (const area of AREAS) for (const [w, h] of [[768, 960], [1448, 1086], [1920, 1080], [320, 240]]) for (const focus of focuses) {
    for (const zoom of [1, 1.015, 1.03]) for (const pan of [null, [1, 1], [-1, -1], [1, -1], [-1, 1], [0.5, -0.25]]) {
      const r = coverRect(area, w, h, focus, zoom, pan);
      close(r.w / r.h, w / h, 1e-9);
      assert.ok(r.x <= area.left + 1e-6 && r.y <= area.top + 1e-6, `left/top covered ${JSON.stringify([area, w, h, focus, zoom, pan, r])}`);
      assert.ok(r.x + r.w >= area.left + area.width - 1e-6 && r.y + r.h >= area.top + area.height - 1e-6, 'right/bottom covered');
      close(r.scale, r.w / w);
    }
  }
  // without zoom the focus point sits at the middle of the area whenever the picture allows it
  const area = {left: 0, top: 0, width: 800, height: 720};
  const r = coverRect(area, 768, 960, [0.5, 0.55], 1, null);
  close(r.y + 0.55 * r.h, 360); close(r.x + 0.5 * r.w, 400);
  assert.ok(r.y + r.h > area.height, 'the picture carries on past the area');
});

test('a monitor holds any aspect, not only 4:3 (Versus is 640x398)', () => {
  for (const area of AREAS) {
    const m = monitorLayout(area, 640, 398, 0.034);
    close(m.screen.w / m.screen.h, 640 / 398);
    assert.ok(m.frame.x >= area.left - 1e-9 && m.frame.x + m.frame.w <= area.left + area.width + 1e-9);
    assert.ok(m.frame.y >= area.top - 1e-9 && m.frame.y + m.frame.h <= area.top + area.height + 1e-9);
  }
});

test('the pan stays a few pixels even on a panorama with plenty of margin, and still never uncovers the area', () => {
  const area = {left: 0, top: 0, width: 800, height: 720};            // violet-horizon is 3840x1920: cover crops it hard
  for (const focus of [[0.5, 0.5], [0.2, 0.5], [0.9, 0.4]]) for (const dir of [[1, 1], [-1, -1], [1, -1], [-1, 1]]) {
    for (let t = 0; t <= DRIFT.period; t += 3) {
      const d = driftState(t, DRIFT, dir), still = coverRect(area, 3840, 1920, focus, d.zoom, null), moved = coverRect(area, 3840, 1920, focus, d.zoom, d.pan, DRIFT.panPx);
      assert.ok(Math.abs(moved.x - still.x) <= DRIFT.panPx + 1e-9 && Math.abs(moved.y - still.y) <= DRIFT.panPx + 1e-9, `pan at ${t}: ${moved.x - still.x}`);
      assert.ok(moved.x <= 1e-6 && moved.y <= 1e-6 && moved.x + moved.w >= 800 - 1e-6 && moved.y + moved.h >= 720 - 1e-6);
    }
  }
  assert.ok(DRIFT.panPx <= 16, 'a few pixels');
});

test('cover zooms about the focus point: its place on the screen does not move', () => {
  const area = {left: 0, top: 0, width: 800, height: 720}, focus = [0.5, 0.55];
  const a = coverRect(area, 768, 960, focus, 1, null), b = coverRect(area, 768, 960, focus, 1.03, null);
  close(a.x + focus[0] * a.w, b.x + focus[0] * b.w); close(a.y + focus[1] * a.h, b.y + focus[1] * b.h);
});

test('camera drift is a slow cosine ping-pong: 1.00 to 1.03, a few pixels of pan, no speed at either end and no jump', () => {
  const start = driftState(0), mid = driftState(DRIFT.period / 2), end = driftState(DRIFT.period);
  close(start.zoom, 1); close(start.p, 0); close(mid.zoom, 1 + DRIFT.zoom); close(mid.p, 1); close(end.zoom, 1);
  assert.deepEqual(start.pan, [0, 0]);
  const dir = driftDirection('city');
  let last = driftState(0, DRIFT, dir), maxStep = 0;
  for (let t = 0.1; t <= 2 * DRIFT.period; t += 0.1) {
    const s = driftState(t, DRIFT, dir);
    assert.ok(s.zoom >= 1 - 1e-12 && s.zoom <= 1 + DRIFT.zoom + 1e-12);
    assert.ok(Math.abs(s.pan[0]) <= 1 && Math.abs(s.pan[1]) <= 1);
    maxStep = Math.max(maxStep, Math.abs(s.zoom - last.zoom));
    last = s;
  }
  assert.ok(maxStep < 0.0004, `zoom changes at most ${maxStep} per 0.1 s`);              // 3 % in 60 s is 0.0005 per second at the steepest: far below
  assert.ok(Math.abs(driftState(0.5).zoom - 1) < 1e-4, 'it starts at rest');
  assert.ok(Math.abs(driftState(DRIFT.period / 2 + 0.5).zoom - (1 + DRIFT.zoom)) < 1e-4, 'and turns at rest');
  // 60 s one way, as the brief says
  assert.equal(DRIFT.period / 2, 60);
});

test('drift never uncovers the area, whatever the picture and the moment', () => {
  const area = {left: 0, top: 0, width: 800, height: 720};
  for (const [w, h] of [[1448, 1086], [1600, 1200], [1800, 1200]]) for (const name of ['city', 'neon-city', 'neon-district', 'violet-horizon', 'x']) {
    for (let t = 0; t <= DRIFT.period; t += 2.5) {
      const d = driftState(t, DRIFT, driftDirection(name)), r = coverRect(area, w, h, [0.5, 0.6], d.zoom, d.pan);
      assert.ok(r.x <= 1e-6 && r.y <= 1e-6 && r.x + r.w >= 800 - 1e-6 && r.y + r.h >= 720 - 1e-6, `${name} ${w} at ${t}`);
    }
  }
});

test('drift directions are fixed per scene name and stay in range', () => {
  assert.deepEqual(driftDirection('city'), driftDirection('city'));
  const seen = new Set(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((n) => driftDirection(n).join()));
  assert.ok(seen.size >= 2);
  for (const n of ['', 'x', 'neon-city']) for (const v of driftDirection(n)) assert.ok(Math.abs(v) <= 1);
});

test('scanlines follow the SOURCE rows whatever whole-number scale the media was delivered at, and whatever its aspect', () => {
  assert.deepEqual(sourceGrid(640, 480), {rows: 240, cols: 320, scale: 2, native: true});
  assert.deepEqual(sourceGrid(320, 240), {rows: 240, cols: 320, scale: 1, native: true});
  assert.deepEqual(sourceGrid(960, 720), {rows: 240, cols: 320, scale: 3, native: true});
  assert.deepEqual(sourceGrid(640, 400), {rows: 200, cols: 320, scale: 2, native: true});
  assert.deepEqual(sourceGrid(640, 398), {rows: 199, cols: 320, scale: 2, native: true}, 'Versus: 320x199 doubled');
  assert.deepEqual(sourceGrid(1280, 960), {rows: 240, cols: 320, scale: 4, native: true});
  assert.deepEqual(sourceGrid(1000, 777), {rows: 240, cols: 309, scale: 777 / 240, native: false}, 'nothing divides: 240 lines, smooth sampling');
  assert.deepEqual(sourceGrid(640, 480, 120), {rows: 120, cols: 160, scale: 4, native: true});   // an explicit row count wins
  assert.equal(sourceGrid(640, 480, 'many').rows, 240);
  for (const [w, h] of [[640, 480], [640, 398], [320, 240], [1280, 720], [2, 2], [4000, 3]]) {
    const g = sourceGrid(w, h);
    assert.ok(g.rows >= 1 && g.cols >= 1 && Math.abs(g.cols / g.rows - w / h) < 0.02 * w / h + 0.6, `${w}x${h}`);
  }
});

test('quality steps skip levels that would look the same at this pixel ratio and honour bans', () => {
  assert.deepEqual([0, 1, 2, 3].map((l) => LEVELS[l].name), ['high', 'medium', 'light', 'low']);
  assert.equal(stepLevel(0, 'down', 2), 1);
  assert.equal(stepLevel(1, 'down', 2), 2);
  assert.equal(stepLevel(2, 'down', 2), 3);
  assert.equal(stepLevel(3, 'down', 2), null);
  assert.equal(stepLevel(0, 'down', 1.5), 2, 'at 1.5 the medium level draws the same pixels');
  assert.equal(stepLevel(0, 'down', 1), 3, 'at 1 only the effects can still be dropped');
  assert.equal(stepLevel(3, 'up', 2), 2);
  assert.equal(stepLevel(0, 'up', 2), null);
  assert.equal(stepLevel(3, 'up', 2, new Set([2])), null);
});

test('?fx= overrides the quality, and only for the words we know', () => {
  assert.deepEqual(parseFx('?fx=off'), {off: true, css: false, quality: null});
  assert.deepEqual(parseFx('?a=1&fx=low'), {off: false, css: false, quality: 'low'});
  assert.deepEqual(parseFx('?fx=high'), {off: false, css: false, quality: 'high'});
  assert.deepEqual(parseFx('?fx=css'), {off: false, css: true, quality: null});
  assert.deepEqual(parseFx('?fx=banana'), {off: false, css: false, quality: null});
  assert.deepEqual(parseFx(''), {off: false, css: false, quality: null});
});

const entry = (extra = {}) => ({name: 'surf', look: 'crt', media: {kind: 'video', url: '/assets/scene-surf.webm', width: 640, height: 480, fps: 15, loop_seconds: 19.2},
                                still: '/assets/scene-surf.jpg', focus: [0.5, 0.55], rate: 1, ...extra});

test('scene info from the server is checked again: same origin only, a known look, numbers in range', () => {
  const info = normalizeInfo(entry(), 'https://192.168.1.50:8667');
  assert.equal(info.look, 'crt'); assert.equal(info.media.kind, 'video'); assert.equal(info.media.url, '/assets/scene-surf.webm');
  assert.equal(info.media.loopSeconds, 19.2); assert.equal(info.still, '/assets/scene-surf.jpg'); assert.deepEqual(info.focus, [0.5, 0.55]);
  assert.equal(normalizeInfo(entry({look: 'hologram'}), '').look, 'plain');
  assert.equal(normalizeInfo(entry({look: undefined}), '').look, 'plain');
  assert.equal(normalizeInfo(entry({focus: [3, -1]}), '').focus.join(), '1,0');
  assert.equal(normalizeInfo(entry({focus: 'centre'}), '').focus.join(), '0.5,0.5');
  assert.equal(normalizeInfo(entry({rate: 9}), '').rate, 2);
  assert.equal(normalizeInfo(entry({rate: 0.01}), '').rate, 0.25);
  assert.equal(normalizeInfo(entry({name: 'Bad Name!<x>'}), '').name, 'badnamex');
  assert.equal(normalizeInfo(entry({media: {kind: 'image', url: '/assets/scene-city.jpg', width: 99999, height: 2}}), '').media.width, 8192);
  assert.equal(normalizeInfo(entry({media: {kind: 'film', url: '/assets/x.webm'}}), '').media.kind, 'image');
  for (const url of ['https://evil.example/x.webm', '//evil.example/x.webm', 'javascript:alert(1)', 'data:image/png;base64,AAAA', '', null, 5, '/assets/a b.webm', '/a\nb'])
    assert.equal(normalizeInfo(entry({media: {kind: 'video', url, width: 640, height: 480}}), 'https://192.168.1.50:8667'), null, String(url));
  assert.equal(normalizeInfo(entry({still: 'https://evil.example/s.jpg'}), 'https://192.168.1.50:8667').still, null);
  assert.equal(normalizeInfo(entry({still: 'https://192.168.1.50:8667/assets/s.jpg'}), 'https://192.168.1.50:8667').still, '/assets/s.jpg');
  for (const bad of [null, undefined, 3, 'x', {}, {media: null}, {media: 'x'}]) assert.equal(normalizeInfo(bad, ''), null);
});

// ---- the quality governor ----------------------------------------------------------------------------------------------------

function feed(gov, {from = 0, to, every, late, expected = 33, level = 0}) {
  const actions = [];
  for (let t = from; t < to; t += every) {
    const verdict = typeof late === 'function' ? late(t) : late;
    const a = gov.push(t, verdict, expected, level);
    if (a) { actions.push([t, a]); break; }
  }
  return actions;
}

test('governor: steady lateness for about two seconds steps down, once, then waits', () => {
  const gov = new Governor();
  gov.reset(0, 0);
  const actions = feed(gov, {from: 1600, to: 9000, every: 33, late: true});
  assert.equal(actions.length, 1);
  assert.equal(actions[0][1], 'down');
  assert.ok(actions[0][0] >= 1600 + GOVERNOR.windowMs * 0.75 && actions[0][0] <= 1600 + GOVERNOR.windowMs + 200, `steps at ${actions[0][0]}`);
  const t = actions[0][0];
  gov.stepped('down', t, 1);
  assert.equal(feed(gov, {from: t, to: t + GOVERNOR.holdMs + GOVERNOR.cooldownMs - 50, every: 33, late: true}).length, 0, 'no second step inside the wait');
  const second = feed(gov, {from: t + GOVERNOR.holdMs + GOVERNOR.cooldownMs, to: t + 20000, every: 33, late: true});
  assert.equal(second.length, 1);
  assert.ok(second[0][0] - t >= GOVERNOR.holdMs + GOVERNOR.cooldownMs + GOVERNOR.windowMs * 0.75 - 1, 'and only after a whole window of lateness again');
});

test('governor: a hiccup, a short stall or occasional late frames never lower the quality', () => {
  const gov = new Governor();
  gov.reset(0, 0);
  assert.equal(feed(gov, {from: 1600, to: 60000, every: 33, late: (t) => t >= 10000 && t < 10400}).length, 0, 'a 0.4 s stall');
  const gov2 = new Governor(); gov2.reset(0, 0);
  assert.equal(feed(gov2, {from: 1600, to: 60000, every: 33, late: (t) => Math.floor(t / 33) % 4 === 0}).length, 0, 'one frame in four is late');
  const gov3 = new Governor(); gov3.reset(0, 0);
  assert.equal(feed(gov3, {from: 1600, to: 30000, every: 33, late: (t) => Math.floor(t / 33) % 2 === 0, level: 3}).length, 1, 'half late is the limit: down');
});

test('governor: frames just after a change are ignored (shader compile, texture upload, resize)', () => {
  const gov = new Governor();
  gov.reset(1000, 0);
  for (let t = 1000; t < 1000 + GOVERNOR.holdMs - 10; t += 20) assert.equal(gov.push(t, true, 33, 0), null);
});

test('governor: slow videos need fewer frames to be judged', () => {
  const gov = new Governor();
  gov.reset(0, 0);
  const actions = feed(gov, {from: 1600, to: 12000, every: 400, late: true, expected: 150});
  assert.equal(actions.length, 1);
  assert.equal(actions[0][1], 'down');
});

test('governor: a machine far too slow to deliver even five frames in the window is still judged, not forgotten', () => {
  const gov = new Governor();
  gov.reset(0, 0);
  const actions = feed(gov, {from: 1600, to: 20000, every: 450, late: true, expected: 33});      // about 2 frames a second for a 30 fps picture
  assert.equal(actions.length, 1);
  assert.equal(actions[0][1], 'down');
  assert.ok(actions[0][0] < 1600 + 3 * GOVERNOR.windowMs, `steps at ${actions[0][0]}`);
  const gov2 = new Governor(); gov2.reset(0, 0);
  assert.equal(feed(gov2, {from: 1600, to: 60000, every: 1900, late: (t) => t > 0 && Math.floor(t / 1900) % 9 === 0}).length, 0, 'a lone stall every so often is not enough');
});

test('governor: it climbs one level only after 90 s of clean frames, and never back to a level that failed', () => {
  const gov = new Governor();
  gov.reset(0, 0);
  assert.equal(feed(gov, {from: 1600, to: GOVERNOR.upAfterMs - 100, every: 33, late: false, level: 2}).length, 0, 'not yet');
  const up = feed(gov, {from: GOVERNOR.upAfterMs - 100, to: GOVERNOR.upAfterMs + 5000, every: 33, late: false, level: 2});
  assert.equal(up[0][1], 'up');
  assert.equal(gov.banned.size, 0);
  gov.stepped('up', up[0][0], 1);
  // it did not hold: late again soon after the climb
  const down = feed(gov, {from: up[0][0] + 2000, to: up[0][0] + 20000, every: 33, late: true, level: 1});
  assert.equal(down[0][1], 'down');
  gov.stepped('down', down[0][0], 2);
  assert.ok(gov.banned.has(1), 'level 1 is banned for the session');
  const later = feed(gov, {from: down[0][0] + 10000, to: down[0][0] + 10000 + GOVERNOR.upAfterMs * 3, every: 33, late: false, level: 2});
  assert.equal(later.length, 0, 'it never tries level 1 again');
});

test('governor: noisy but mostly fine frames do not earn a climb (more than 3 % late)', () => {
  const gov = new Governor();
  gov.reset(0, 0);
  const up = feed(gov, {from: 1600, to: GOVERNOR.upAfterMs * 2, every: 33, late: (t) => Math.floor(t / 33) % 20 === 0, level: 2});     // 5 % late
  assert.equal(up.length, 0);
});

test('governor: when a level is simply too heavy it settles on the one below and stops trying (a handful of moves in an hour)', () => {
  const gov = new Governor();
  let level = 0, moves = 0;
  gov.reset(0, 0);
  for (let t = 0; t < 3600 * 1000; t += 33) {
    const late = level <= 1;                 // levels 0 and 1 are too heavy for this tablet, 2 and 3 are fine
    const a = gov.push(t, late, 33, level);
    if (a === 'down' && level < 3) { level++; gov.stepped('down', t, level); moves++; }
    else if (a === 'up') { level--; gov.stepped('up', t, level); moves++; }
  }
  assert.equal(level, 2);
  assert.ok(moves <= 5, `${moves} moves`);
  assert.ok(gov.banned.has(1), 'the level that failed after a climb is banned');
});

test('governor: even a pathological machine that is slow in spells cannot make it flap more than a few times', () => {
  const gov = new Governor();
  let level = 1, ups = 0, moves = 0;
  gov.reset(0, 0);
  for (let t = 0; t < 3 * 3600 * 1000; t += 33) {
    const late = (Math.floor(t / 60000) % 7 === 3) && (t % 60000 < 20000);        // a slow spell every seven minutes, whatever the level
    const a = gov.push(t, late, 33, level);
    if (a === 'down' && level < 3) { level++; gov.stepped('down', t, level); moves++; }
    else if (a === 'up') { level--; gov.stepped('up', t, level); moves++; ups++; }
  }
  assert.ok(ups <= GOVERNOR.maxUps, `${ups} climbs`);
  assert.ok(moves <= 3 * GOVERNOR.maxUps + 3, `${moves} moves in three hours`);
});

// ---- the looks' own helpers ---------------------------------------------------------------------------------------------------

test('looks register themselves, each with its own name', () => {
  assert.equal(typeof core.SceneStage.register, 'function');
  for (const m of [crt, lcd, photo]) assert.equal(typeof m.factory, 'function');
  const kit = {math: {monitorLayout, coverRect, driftState, driftDirection, sourceGrid, clamp: core.clamp, mix: core.mix, smoothstep: core.smoothstep}, px: (n) => n + 'px', glsl: {lib: ''}};
  assert.deepEqual([crt, lcd, photo].map((m) => m.factory(kit).name), ['crt', 'lcd', 'photo']);
  assert.deepEqual([crt, lcd, photo].map((m) => m.factory(kit).opaque), [false, false, true]);
  assert.equal(lcd.factory(kit).history, 1);
  assert.equal(photo.factory(kit).mipmapStills, true);
});

test('crt: the aperture grille is gentle at pixel ratio 1 and strong at 2, and glow stays inside the canvas', () => {
  close(crt.maskStrength(1), crt.MASK_LO); close(crt.maskStrength(2), crt.MASK_HI); close(crt.maskStrength(3), crt.MASK_HI);
  assert.ok(crt.maskStrength(1.5) > crt.MASK_LO && crt.maskStrength(1.5) < crt.MASK_HI);
  assert.ok(crt.MASK_HI > crt.MASK_LO && crt.MASK_HI <= 0.25, 'subtle, not a screen door');
  const kit = {math: {monitorLayout, sourceGrid}};
  for (const area of AREAS) for (const media of [{w: 640, h: 480}, {w: 640, h: 398}]) {
    const container = {w: Math.max(800, area.left + area.width), h: 1280};
    const L = crt.crtLayout({area, container, media, info: {media: {}}}, kit);
    assert.ok(L.canvas.x >= 0 && L.canvas.y >= 0 && L.canvas.x + L.canvas.w <= container.w + 1e-9 && L.canvas.y + L.canvas.h <= 1280 + 1e-9);
    assert.ok(L.frame.x >= L.canvas.x - 1e-9 && L.frame.y >= L.canvas.y - 1e-9 && L.frame.x + L.frame.w <= L.canvas.x + L.canvas.w + 1e-9);
    assert.deepEqual([L.grid.rows, L.grid.cols], media.h === 480 ? [240, 320] : [199, 320]);
    assert.ok(L.radius > 0 && L.radius < L.screen.h / 2);
  }
});

test('lcd: the grid is faint where a cell is tiny and whole from four device pixels', () => {
  close(lcd.gridVisibility(1), 0); close(lcd.gridVisibility(2), 0); close(lcd.gridVisibility(4), 1); close(lcd.gridVisibility(9), 1);
  let last = 0;
  for (let c = 2; c <= 4; c += 0.1) { const v = lcd.gridVisibility(c); assert.ok(v >= last - 1e-12); last = v; }
  const kit = {math: {monitorLayout, sourceGrid}};
  const L = lcd.lcdLayout({area: AREAS[0], container: {w: 800, h: 1280}, media: {w: 320, h: 240}, info: {media: {}}}, kit);
  assert.deepEqual([L.grid.cols, L.grid.rows], [320, 240], 'the grid period is one source pixel');
});

test('lcd: ghosting is soft and depends on the frame rate: a fast film smears a little, a slow one not at all', () => {
  assert.ok(lcd.ghostFor(33) > lcd.ghostFor(66) && lcd.ghostFor(66) > lcd.ghostFor(150), 'monotone in the frame interval');
  assert.ok(lcd.ghostFor(150) < 0.05, 'a 6 fps film: the panel has settled');
  assert.ok(lcd.ghostFor(0) <= lcd.GHOST_MAX && lcd.ghostFor(-5) <= lcd.GHOST_MAX, 'capped');
  assert.ok(lcd.ghostFor(33) <= 0.5, 'soft even at 30 fps');
});

test('photo: a video never drifts, twinkles or gets haze; a still city does; only the camera is the video rule', () => {
  for (const name of ['city', 'neon-city', 'neon-district', 'violet-horizon', 'paradise', 'whatever']) {
    const v = photo.presetFor({name}, true);
    assert.equal(v.drift, 0, name); assert.equal(v.twinkle, 0, name); assert.equal(v.haze, 0, name); assert.equal(v.bloom, 0, name);
  }
  for (const name of ['city', 'neon-city', 'violet-horizon', 'something-new']) {
    const s = photo.presetFor({name}, false);
    assert.ok(s.drift > 0 && s.twinkle > 0 && s.haze > 0 && s.bloom > 0, name);
  }
  const iso = photo.presetFor({name: 'city-iso'}, true);
  assert.equal(iso.drift, 0); assert.equal(iso.twinkle, 0); assert.ok(iso.grade > 0, 'city-iso: the gentle grade, no drift, no twinkle');
  const p = photo.presetFor({name: 'paradise'}, true);
  assert.ok(p.grade > 0 && p.grain > 0 && p.vignette > 0, 'soft grade, faint grain and a vignette stay');
  assert.ok(p.grade < 1 && p.grain < 1, 'and lighter than the night cities');
  assert.ok(photo.BREATH <= 0.2 && photo.OFF_FLOOR >= 0.2, 'restrained: lights dim a little or go to a dim floor, never black');
  assert.ok(photo.GRAIN <= 0.02 && photo.VIGNETTE <= 0.3);
});

test('photo: the picture is still at rest in the low tier, and moves otherwise, always covering the area', () => {
  const kit = {math: {monitorLayout, coverRect, driftState, driftDirection, sourceGrid, clamp: core.clamp}, px: (n) => n};
  const container = {w: 800, h: 1280}, area = {left: 0, top: 0, width: 800, height: 720};
  const info = {name: 'city', focus: [0.5, 0.55]};
  const L = photo.photoLayout({area, container, media: {w: 1448, h: 1086}, info}, kit);
  const rest = photo.pictureAt(L, info, 1448, 1086, 37, false, kit.math), moved = photo.pictureAt(L, info, 1448, 1086, 37, true, kit.math);
  assert.deepEqual(rest, coverRect(area, 1448, 1086, info.focus, 1, null));
  assert.notDeepEqual(rest, moved);
  for (const r of [rest, moved]) assert.ok(r.x <= 1e-6 && r.y <= 1e-6 && r.x + r.w >= 800 - 1e-6 && r.y + r.h >= 720 - 1e-6);
  // the canvas ends where the picture, at its largest, has faded into the page's own background; never taller than the container
  assert.ok(L.canvas.w === 800 && L.canvas.h <= 1280 && L.canvas.h >= 720);
  const tall = photo.photoLayout({area, container, media: {w: 768, h: 960}, info: {name: 'paradise', focus: [0.5, 0.55]}}, kit);
  assert.ok(tall.canvas.h > L.canvas.h - 1 && tall.canvas.h <= 1280, 'the taller picture needs the taller canvas');
});

// ---- static guards on the source ------------------------------------------------------------------------------------------------

const sources = Object.fromEntries(['scene-stage.js', 'stage-crt.js', 'stage-lcd.js', 'stage-photo.js', 'stage-live.js'].map((n) => [n, fs.readFileSync(new URL(n, web), 'utf8')]));

test('no look reaches for eval, the network, inline markup or another origin (CSP: script-src self, media and img self only)', () => {
  for (const [name, text] of Object.entries(sources)) {
    const code = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    for (const word of [/\beval\s*\(/, /new\s+Function/, /\.innerHTML/, /\.outerHTML/, /insertAdjacentHTML/, /document\.write/, /\bfetch\s*\(/, /XMLHttpRequest/, /WebSocket/,
                        /https?:\/\//, /\bimport\s*\(/, /importScripts/, /localStorage/, /createObjectURL/, /setAttribute\(\s*['"]on/])
      assert.ok(!word.test(code), `${name} uses ${word}`);
  }
});

test('every uniform the JavaScript sets is declared in a shader of the same file, and every shader has a main', () => {
  for (const name of ['stage-crt.js', 'stage-lcd.js', 'stage-photo.js']) {
    const text = sources[name];
    const declared = new Set();
    for (const m of text.matchAll(/uniform\s+(?:float|vec2|vec3|vec4|sampler2D)\s+([^;']+);/g)) for (const n of m[1].split(',')) declared.add(n.trim());
    const used = [...text.matchAll(/\.(?:f1|f2|f3|f4|i1)\('(u[A-Za-z0-9]+)'/g)].map((m) => m[1]);
    assert.ok(used.length > 10, `${name} sets uniforms`);
    for (const u of used) assert.ok(declared.has(u), `${name}: ${u} is set but not declared`);
    assert.ok((text.match(/void main\(\) \{/g) || []).length >= 1, `${name} has its shaders`);
    // smoothstep with its edges the wrong way round is undefined in GLSL ES; the constants we write are always ascending
    for (const m of text.matchAll(/smoothstep\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,/g)) assert.ok(Number(m[1]) < Number(m[2]), `${name}: smoothstep(${m[1]}, ${m[2]}) is reversed`);
  }
});

test('the look files are served by name: lower-case letters, digits and dashes only, as the server requires', () => {
  for (const name of Object.keys(sources)) assert.match(name, /^[a-z0-9-]{1,40}\.(js|css)$/);
});

// ---- a whole scene on a fake DOM, without WebGL ---------------------------------------------------------------------------------

class FakeNode {
  constructor(tag) { this.tagName = String(tag).toUpperCase(); this.style = {}; this.children = []; this.parentNode = null; this.attrs = {}; this.listeners = {}; this.nodeType = 1;
    this.clientWidth = 800; this.clientHeight = 1280; this.offsetWidth = 800; this.paused = true; this.readyState = 0; this.videoWidth = 0; this.videoHeight = 0; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(c)); }
  replaceChildren(...cs) { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; cs.forEach((c) => this.appendChild(c)); }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k]; } removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn, options) { (this.listeners[type] ||= []).push({fn, once: !!(options && options.once)}); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((l) => l.fn !== fn); }
  dispatch(type, event = {}) { for (const l of [...(this.listeners[type] || [])]) { if (l.once) this.removeEventListener(type, l.fn); l.fn(event); } }
  getContext() { return null; }
  get parentElement() { return this.parentNode; }
  pause() { this.paused = true; } load() {} play() { this.paused = false; return Promise.resolve(); }
  set src(v) { this._src = v; queueMicrotask(() => { this.naturalWidth = 320; this.naturalHeight = 240; this.dispatch('load'); }); } get src() { return this._src; }
}

function withFakeDom(run) {
  const keep = {};
  const names = ['document', 'Image', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'addEventListener', 'removeEventListener', 'devicePixelRatio', 'location', 'ResizeObserver'];
  for (const n of names) keep[n] = Object.getOwnPropertyDescriptor(globalThis, n);
  const frames = [];
  const doc = new FakeNode('document');
  Object.assign(doc, {hidden: false, createElement: (tag) => new FakeNode(tag)});
  Object.assign(globalThis, {document: doc, Image: class extends FakeNode { constructor() { super('img'); } }, getComputedStyle: () => ({position: 'absolute', backgroundColor: 'rgb(9, 18, 27)'}),
    requestAnimationFrame: (f) => frames.push(f), cancelAnimationFrame: () => {}, addEventListener() {}, removeEventListener() {}, devicePixelRatio: 2,
    location: {search: '', origin: 'http://127.0.0.1:1'}});
  delete globalThis.ResizeObserver;
  const made = [], realCreate = core.SceneStage.create;
  core.SceneStage.create = (...args) => { const st = realCreate(...args); made.push(st); return st; };
  const done = () => {
    core.SceneStage.create = realCreate;
    for (const st of made) { try { st.destroy(); } catch (_) { /* already gone */ } }       // a failed test must not leave timers behind
    for (const n of names) { if (keep[n]) Object.defineProperty(globalThis, n, keep[n]); else delete globalThis[n]; }
  };
  return Promise.resolve(run({frames, container: new FakeNode('div')})).finally(done);
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 5));
const waitFor = async (cond, ms = 2000) => { for (let t = 0; t < ms; t += 5) { if (cond()) return; await tick(); } throw new Error('timed out'); };
const stillInfo = (extra = {}) => ({name: 'city', look: 'photo', media: {kind: 'image', url: '/assets/scene-city.jpg', width: 1448, height: 1086}, focus: [0.5, 0.55], rate: 1, ...extra});

test('scene lifecycle without WebGL: the picture is shown by the CSS tier, switches cleanly and cleans up after itself', () => withFakeDom(async ({container}) => {
  const seen = [];
  const stage = core.SceneStage.create(container, {onStatus: (s) => seen.push(s)});
  assert.equal(container.attrs['aria-hidden'], 'true');
  assert.equal(stage.status().renderer, 'plain', 'nothing yet');
  stage.setArea({left: 0, top: 0, width: 800, height: 720});
  stage.show(stillInfo());
  await waitFor(() => stage.status().ready);
  let s = stage.status();
  assert.equal(s.renderer, 'css'); assert.equal(s.look, 'photo'); assert.equal(s.scene, 'city'); assert.equal(s.tier, 'css'); assert.equal(s.error, 'no WebGL');
  assert.equal(container.children.length, 1);
  assert.ok(seen.length >= 1 && seen.at(-1).ready, 'onStatus heard about it');
  // the picture sits in the root, covering the area (never stretched)
  const root = container.children[0], slot = root.children[0];
  const media = slot.children[0].children[1].children[0];       // slot > css layer > [below, media box, above]; the picture is in the media box
  assert.equal(media.tagName, 'IMG');
  // a second scene replaces the first; the plain look needs neither WebGL nor a look file
  stage.show(stillInfo({name: 'paradise', look: 'plain', media: {kind: 'image', url: '/assets/scene-paradise.jpg', width: 768, height: 960}}));
  await waitFor(() => stage.status().scene === 'paradise');
  assert.equal(stage.status().renderer, 'plain'); assert.equal(stage.status().tier, 'plain');
  // an unusable entry clears the stage; a foreign URL is refused and leaves what is shown alone
  stage.show(stillInfo({media: {kind: 'image', url: 'https://evil.example/a.jpg', width: 10, height: 10}}));
  assert.equal(stage.status().scene, null);
  stage.show(stillInfo());
  await waitFor(() => stage.status().ready);
  stage.setMotion(false); stage.pause(); assert.equal(stage.status().paused, true); stage.resume(); assert.equal(stage.status().paused, false);
  stage.setQuality('low'); assert.equal(stage.status().quality, 'low'); assert.equal(stage.status().level, 3);
  stage.setQuality('auto'); assert.equal(stage.status().level, 0);
  stage.destroy();
  assert.equal(container.children.length, 0, 'the stage removes everything it added');
  stage.show(stillInfo()); stage.setArea({left: 0, top: 0, width: 1, height: 1}); stage.pause(); stage.destroy();    // all harmless after destroy
}));

test('a scene whose files never arrive leaves the previous one in place and says why', () => withFakeDom(async ({container}) => {
  const stage = core.SceneStage.create(container, {});
  stage.show(stillInfo());
  await waitFor(() => stage.status().ready);
  const BadImage = class extends FakeNode { constructor() { super('img'); } set src(v) { queueMicrotask(() => this.dispatch('error')); } get src() { return ''; } };
  globalThis.Image = BadImage;
  stage.show(stillInfo({name: 'neon-city', media: {kind: 'image', url: '/assets/scene-neon-city.jpg', width: 10, height: 10}}));
  await waitFor(() => /could not be shown/.test(stage.status().error || ''));
  assert.equal(stage.status().scene, 'city', 'the picture that was there stays');
  assert.equal(stage.status().ready, true);
  stage.destroy();
}));

test('forcing the CSS tier (and ?fx=off) never needs WebGL and keeps the status honest', () => withFakeDom(async ({container}) => {
  const a = core.SceneStage.create(container, {forceCss: true});
  a.show(stillInfo({look: 'crt', name: 'surf'}));
  await waitFor(() => a.status().ready);
  assert.equal(a.status().renderer, 'css'); assert.equal(a.status().tier, 'css'); assert.equal(a.status().error, undefined);
  a.destroy();
  const b = core.SceneStage.create(new FakeNode('div'), {search: '?fx=off'});
  b.show(stillInfo({look: 'crt', name: 'surf'}));
  await waitFor(() => b.status().ready);
  assert.equal(b.status().renderer, 'plain');
  b.destroy();
}));

// ---- the live effects and touch (stage-live.js) at the stage's own API ----------------------------------------------------------------------

test('the live block of a scene rides along with its info: checked again, dropped when unusable', () => {
  const info = normalizeInfo(entry({look: 'photo', live: {water: {regions: [[0, .7, 1, 1]], amount: 9}, craft: [{kind: 'gull', from: [0, .2], to: [1, .1]}]}}), '');
  assert.equal(info.live.version, 1); assert.equal(info.live.water.amount, 2, 'clamped by the page'); assert.equal(info.live.craft.length, 1);
  for (const bad of [{water: 'x'}, 'wet', 5, [], {}, null]) assert.equal(normalizeInfo(entry({live: bad}), '').live, undefined, JSON.stringify(bad));
  assert.equal(normalizeInfo(entry(), '').live, undefined, 'no block, no key');
  assert.equal(JSON.stringify(normalizeInfo(entry({live: {lights: {}}}), '').live), JSON.stringify(live.normalizeLive({lights: {}})));
});

test('Cozy Mountain Home rejects stale cyberpunk rain and aircraft for all dayparts', () => {
  const effects = {water: {regions: [[0, .7, 1, 1]], amount: 1}, craft: [{kind: 'gull', from: [0, .2], to: [1, .1]}]};
  for (const suffix of ['', '-dawn', '-day', '-dusk', '-night']) {
    assert.equal(normalizeInfo(entry({name: 'neon-district' + suffix, look: 'photo', live: effects}), '').live, undefined);
  }
  assert.ok(normalizeInfo(entry({name: 'city', live: effects}), '').live);
});

test('the Paradise preset works with an older running server without overriding explicit settings', () => {
  const water = {regions: [[0, .7, 1, 1]], glints: .8};
  const info = (name, w) => normalizeInfo(entry({name, look: 'photo', live: {water: w}}), '').live.water;
  assert.equal(info('paradise', water).glint_size, .38);
  assert.equal(info('paradise', water).glint_density, .35);
  assert.equal(info('city', water).glint_size, 1);
  assert.equal(info('paradise', {...water, glint_size: .7, glint_density: .6}).glint_size, .7);
  assert.equal(info('paradise', {...water, glint_size: .7, glint_density: .6}).glint_density, .6);
  assert.equal(info('paradise', {...water, glints: 1}).glint_density, 1);
  assert.equal(info('paradise', {...water, glints: 1.3}).glint_size, .38);
  assert.equal(info('paradise', {...water, glints: 1.3}).glint_density, .55);
});

test('stage.setLive and stage.poke: harmless without WebGL, honest in the status, and the switch is remembered', () => withFakeDom(async ({container}) => {
  const stage = core.SceneStage.create(container, {});
  assert.equal(typeof stage.setLive, 'function'); assert.equal(typeof stage.poke, 'function');
  assert.equal(stage.poke(10, 10), false, 'nothing to touch yet');
  stage.setArea({left: 0, top: 0, width: 800, height: 720});
  stage.show(stillInfo({live: {water: {regions: [[0, .7, 1, 1]]}, lights: {}}}));
  await waitFor(() => stage.status().ready);
  const s = stage.status();
  assert.equal(s.renderer, 'css'); assert.equal(s.live, false, 'at the css tier nothing is live'); assert.deepEqual(s.liveEffects, ['water', 'lights'], 'but the block is known'); assert.equal(s.pokes, 0);
  assert.equal(stage.poke(300, 300), false, 'the css tier does not answer to touch');
  for (const bad of [[NaN, 1], [1, 'a'], [undefined, undefined], [1e9, -1e9]]) assert.equal(stage.poke(...bad), false);
  stage.setLive(false); assert.equal(stage.status().live, false); stage.setLive(true); stage.setLive(true); stage.setLive(0); stage.setLive(1);
  stage.setMotion(false); stage.pause(); assert.equal(stage.poke(300, 300), false); stage.resume();
  stage.destroy();
  assert.equal(stage.poke(1, 1), false, 'harmless after destroy'); stage.setLive(false);
}));

test('the pixel looks and the photo look answer to touch only where they should (pokeKind), and the photo look only with a live block', () => {
  const pick = (name) => ({crt, lcd, photo}[name].factory({math: {monitorLayout, coverRect, driftState, driftDirection, sourceGrid, clamp: core.clamp, mix: core.mix, smoothstep: core.smoothstep}, px: (n) => n, glsl: {lib: ''}}));
  const frame = {x: 100, y: 100, w: 400, h: 300};
  // the renderers are created with a GL context in the browser; here only the pure answer is asked, through a stand-in
  for (const name of ['crt', 'lcd']) assert.equal(typeof pick(name).create, 'function', name);
  assert.equal(typeof photo.factory({math: {}, px: (n) => n, glsl: {lib: ''}}).live, 'function');
  const f = photo.factory({math: {}, px: (n) => n, glsl: {lib: ''}});
  assert.equal(f.live({live: {water: {}}}, {live: true, motion: true, level: 0}), true);
  assert.equal(f.live({live: {water: {}}}, {live: true, motion: true, level: 3}), true, 'the lowest tier keeps its few small effects');
  assert.equal(f.live({live: {water: {}}}, {live: false, motion: true, level: 0}), false, 'the page switched the extras off');
  assert.equal(f.live({live: {water: {}}}, {live: true, motion: false, level: 0}), false, 'reduced motion: a still picture');
  assert.equal(f.live({}, {live: true, motion: true, level: 0}), false, 'no block, no live effects');
  void frame;
});

test('with live effects a still picture draws at the tier\'s own rate: 30, 30, 24 and 20 frames a second, never more than 30', () => {
  const rates = [0, 1, 2, 3].map((l) => Math.round(1000 / live.intervalFor(l)));
  assert.deepEqual(rates, [30, 30, 24, 20]);
  assert.equal(core.STILL_INTERVAL, 1000 / 30); assert.equal(core.LIVE_FILM_FPS, 24);
});

// ---- the picture never ends inside the screen with a dragged last row ---------------------------------------------------------------------

test('a tall picture covers the whole screen, a wide one covers the slot and the shader carries it on as a reflection', () => {
  const slot = {left: 0, top: 0, width: 800, height: 720}, screen = {width: 800, height: 1280}, {placePicture} = photo;
  const wide = placePicture(slot, screen, 1448, 1086, [0.52, 0.5]);
  assert.equal(wide.full, false); assert.deepEqual(wide.cover, slot);
  const same = coverRect(slot, 1448, 1086, [0.52, 0.5], 1, null);
  for (const k of ['x', 'y', 'w', 'h', 'scale']) close(wide[k], same[k], 1e-9);
  const tall = placePicture(slot, screen, 1080, 1920, [0.5, 0.5]);                       // a phone-shaped photograph
  assert.equal(tall.full, true);
  assert.ok(tall.x <= 1e-9 && tall.y <= 1e-9 && tall.x + tall.w >= 800 - 1e-9 && tall.y + tall.h >= 1280 - 1e-9, 'the whole screen is covered: nothing ends inside it');
  assert.deepEqual(tall.cover, {left: 0, top: 0, width: 800, height: 1280});
  close(tall.w / tall.h, 1080 / 1920, 1e-9);
  const para = placePicture(slot, screen, 720, 900, [0.69, 0.55]);                       // Paradise: covering the screen would need 28 % more zoom than the slot
  assert.equal(para.full, false);
  // the limit is the rule: a picture just under it covers the screen, just over it does not
  const limit = photo.FULL_COVER_LIMIT;
  for (const aspect of [0.4, 0.5, 0.6, 0.75, 0.9, 1.0, 1.3, 2]) {
    const mw = 1000 * aspect, mh = 1000, p = placePicture(slot, screen, mw, mh, [0.5, 0.5]);
    const ratio = Math.max(800 / mw, 1280 / mh) / Math.max(800 / mw, 720 / mh);
    assert.equal(p.full, ratio <= limit, `aspect ${aspect}: ratio ${ratio}`);
    assert.ok(p.x <= p.cover.left + 1e-9 && p.y <= p.cover.top + 1e-9 && p.x + p.w >= p.cover.left + p.cover.width - 1e-9 && p.y + p.h >= p.cover.top + p.cover.height - 1e-9, `aspect ${aspect}: its cover is covered`);
  }
  // the focus point sits at the centre of the slot wherever the picture has room for that
  const f = placePicture(slot, screen, 1080, 1920, [0.5, 0.4]);
  assert.ok(Math.abs(f.y + 0.4 * f.h - 360) < 1e-6 || f.y === 0 || f.y + f.h === 1280);
});

test('the layout of a tall picture reaches the bottom of the screen (no fade needed), a wide one ends above it with room for the fade', () => {
  const kit = {math: {monitorLayout, coverRect, driftState, driftDirection, sourceGrid, clamp: core.clamp}, px: (n) => n};
  const container = {w: 800, h: 1280}, area = {left: 0, top: 0, width: 800, height: 720};
  const tall = photo.photoLayout({area, container, media: {w: 1080, h: 1920}, info: {name: 'x', focus: [.5, .5]}}, kit);
  assert.equal(tall.full, true); assert.equal(tall.canvas.h, 1280, 'the canvas covers the screen');
  const wide = photo.photoLayout({area, container, media: {w: 1448, h: 1086}, info: {name: 'city', focus: [.5, .55]}}, kit);
  assert.equal(wide.full, false); assert.ok(wide.picture.y + wide.picture.h < 1280 && wide.canvas.h > wide.picture.y + wide.picture.h, 'the canvas goes on past the picture, for the reflection and its fade');
  // drift keeps the cover covered, for both
  for (const L of [tall, wide]) for (let t = 0; t <= 120; t += 4) {
    const r = photo.pictureAt(L, {name: 'x', focus: [.5, .5]}, L === tall ? 1080 : 1448, L === tall ? 1920 : 1086, t, true, kit.math);
    assert.ok(r.x <= L.cover.left + 1e-6 && r.y <= L.cover.top + 1e-6 && r.x + r.w >= L.cover.left + L.cover.width - 1e-6 && r.y + r.h >= L.cover.top + L.cover.height - 1e-6, `drift at ${t}`);
  }
});

test('City keeps both bridge quota rows inside a portrait picture frame, even during drift', () => {
  const kit = {math: {monitorLayout, coverRect, driftState, driftDirection, sourceGrid, clamp: core.clamp}, px: (n) => n};
  for (const [w, h] of [[390, 844], [601, 961], [800, 1280]]) {
    const area = {left: 0, top: 0, width: w, height: h}, info = {name: 'city', focus: [.5, .55]};
    const L = photo.photoLayout({area, container: {w, h}, media: {w: 1280, h: 960}, info}, kit);
    for (let t = 0; t <= 120; t += 4) {
      const p = photo.pictureAt(L, info, 1280, 960, t, true, kit.math);
      assert.ok(p.x + .225 * p.w > 0 && p.x + .8906 * p.w < w, `bridge is clipped at ${w}x${h}, time ${t}`);
      assert.ok(p.y + .7138 * p.h < h * .75, 'bridge stays clear of the clock and quota panel');
    }
  }
});

test('past its edge the picture is mirrored, not clamped: the shaders say so, and the triangle wave reads what it should', () => {
  const photoSrc = sources['stage-photo.js'], liveSrc = sources['stage-live.js'];
  assert.match(photoSrc, /vec2\(1\.0\) - abs\(vec2\(1\.0\) - mod\(puv, vec2\(2\.0\)\)\)/, 'the still and the classic film');
  assert.match(photoSrc, /uMirror/);
  assert.match(liveSrc, /vec2\(1\.0\) - abs\(vec2\(1\.0\) - mod\(q, vec2\(2\.0\)\)\)/, 'the live film');
  assert.ok(!/clamp\(q, vec2\(0\.0\), vec2\(1\.0\)\) \* uUvScale/.test(liveSrc), 'the live film no longer clamps');
  const mirror = (v) => 1 - Math.abs(1 - (((v % 2) + 2) % 2));
  for (const [v, want] of [[0, 0], [0.3, 0.3], [1, 1], [1.2, 0.8], [1.75, 0.25], [2, 0], [2.3, 0.3], [-0.2, 0.2], [-1.4, 0.6], [3.9, 0.1]]) close(mirror(v), want, 1e-9);
  for (let v = -3; v <= 3; v += 0.01) assert.ok(mirror(v) >= -1e-12 && mirror(v) <= 1 + 1e-12 && Math.abs(mirror(v + 0.01) - mirror(v)) <= 0.0100001, 'always inside the picture and continuous: no seam');
});

test('a touch is accepted inside the area the page gave the stage, whatever the look is, and the pixel looks do not ask their own frame', () => {
  for (const [name, text] of [['stage-crt.js', sources['stage-crt.js']], ['stage-lcd.js', sources['stage-lcd.js']]]) {
    assert.match(text, /pokeKind\(\) \{ return touchOk \? 'bump' : null; \}/, name);
    assert.ok(!/q\.layout\.frame|layout && q\.layout\.frame/.test(text), `${name}: no frame in the answer to a touch`);
  }
  assert.match(sources['scene-stage.js'], /if \(!L\.area\) L\.area = ctx\.area;/, 'every layout knows the area');
  assert.match(sources['scene-stage.js'], /a touch must land on the picture area/);
});
