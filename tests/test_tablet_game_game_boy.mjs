import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

// GAME BOY (token_tv/tablet_web/game-game-boy.js): the pure logic (the readings-to-HUD mapping with its edge cases, the clock, the level, the physics, the auto-player, the console's
// layout) and, with a fake canvas and a FICTIONAL atlas, the drawing path. Everything uses the seeded random. No cartridge art is needed or used.
const require = createRequire(import.meta.url);
const engine = require('../token_tv/tablet_web/stage-game.js');
const gb = require('../token_tv/tablet_web/game-game-boy.js');
const {W, H, LCD, TILE, ROWS, GROUND, GROUND_Y, T, PHY, seeded} = gb;

const NOW = Date.UTC(2026, 10, 9, 12, 0, 0);                               // a fixed moment (ms)
const secs = (ms) => ms / 1000;
const week = (remaining, hours = 100) => ({remaining, resets_at: secs(NOW) + hours * 3600});
const provider = (weekly, resets = {count: 2, old: false}, session = null) => ({weekly, session, aged: false, resets, credits: null});

/* ---- the readings-to-HUD mapping -------------------------------------------------------------------------------------------------------------------- */

test('registered as game-boy: only the screen uses crisp pixels, without a grid on the casing', () => {
  const scene = engine.registry['game-boy'];
  assert.ok(scene, 'the scene registers itself');
  assert.deepEqual(scene.size, [200, 320]);
  assert.equal(scene.post, 'handheld');
  assert.deepEqual(scene.pixelRect(), [LCD.x, LCD.y, LCD.w, LCD.h]);
  for (const name of ['init', 'step', 'draw', 'poke']) assert.equal(typeof scene[name], 'function', name);
  assert.equal(scene.needsAtlas, undefined, 'the console and a plain LCD draw without the atlas');
});

test('percent text: rounded down like the dock, a sliver shows 1, a real zero 0, and anything that is not a percentage is unknown (null)', () => {
  assert.equal(gb.percentText(87.6), '87%');
  assert.equal(gb.percentText(100), '100%');
  assert.equal(gb.percentText(0), '0%');
  assert.equal(gb.percentText(0.4), '1%', 'a positive fraction never reads as the zero of an empty quota');
  assert.equal(gb.percentText(1), '1%');
  assert.equal(gb.percentText(99.99), '99%');
  for (const bad of [-0.1, 100.5, NaN, Infinity, null, undefined, '87', {}, [], true]) assert.equal(gb.percentText(bad), null, String(bad));
});

test('reset text: at most four characters, floored (never more time than there is), null when missing or past', () => {
  const at = (hours) => gb.resetText(secs(NOW) + hours * 3600, NOW);
  assert.equal(at(7 * 24), '7.0D');
  assert.equal(at(3 * 24 + 4), '3.1D', '3 days 4 hours is 3.16 days: floored to 3.1');
  assert.equal(at(24), '1.0D');
  assert.equal(at(23.99), '23H');
  assert.equal(at(12.5), '12H');
  assert.equal(at(10), '10H');
  assert.equal(at(5.35), '5.3H');
  assert.equal(at(1), '1.0H');
  assert.equal(at(0.9), '54M');
  assert.equal(at(0.5), '30M');
  assert.equal(at(0.001), '1M', 'a moment left is one minute, never zero');
  assert.equal(at(250), '10D');
  for (const hours of [7 * 24, 3.5 * 24, 30, 12.9, 5.01, 0.3, 0.01]) assert.ok(at(hours).length <= 4, `${hours} h -> ${at(hours)}`);
  assert.equal(gb.resetText(secs(NOW) - 5, NOW), null, 'a passed reset');
  assert.equal(gb.resetText(secs(NOW), NOW), null, 'a reset right now');
  for (const bad of [null, undefined, NaN, Infinity, '1700000000']) assert.equal(gb.resetText(bad, NOW), null, String(bad));
  const exact = gb.resetText(secs(NOW) + 3 * 24 * 3600, NOW);
  assert.equal(exact, '3.0D', 'exactly three days is 3.0, not 2.9 through rounding noise');
});

test('hearts for the saved resets follow the board: three slots, a dot when the count is unknown or old, a plus beyond three, a real zero shows no dot', () => {
  assert.deepEqual(gb.heartsModel({count: 2, old: false}, true), {full: 2, plus: false, dot: false});
  assert.deepEqual(gb.heartsModel({count: 3, old: false}, true), {full: 3, plus: false, dot: false});
  assert.deepEqual(gb.heartsModel({count: 7, old: false}, true), {full: 3, plus: true, dot: false});
  assert.deepEqual(gb.heartsModel({count: 0, old: false}, true), {full: 0, plus: false, dot: false}, 'zero is known: three faint hearts and no dot');
  assert.deepEqual(gb.heartsModel({count: 2, old: true}, true), {full: 2, plus: false, dot: true}, 'old: the count stays and ONE dot marks it');
  assert.deepEqual(gb.heartsModel({count: null, old: false}, true), {full: 0, plus: false, dot: true}, 'unknown: hearts without a count and the dot');
  for (const bad of [{count: -1}, {count: 1.5}, {count: '2'}, {count: 1000}, {}, null, undefined]) assert.equal(gb.heartsModel(bad, true).dot, true, JSON.stringify(bad));
  assert.equal(gb.heartsModel({count: 2, old: false}, false).dot, true, 'a stale reading marks every count');
});

test('the HUD for no readings, stale readings and broken readings is unknown everywhere: dashes, dotted gauges, no five hours, never a zero', () => {
  for (const readings of [null, undefined, {}, {providers: null}, {providers: {codex: 5, claude: 'x'}}, {providers: {codex: provider(null, {count: null, old: false}), claude: provider(undefined, {count: null, old: false})}}]) {
    const m = gb.hudModel(readings, NOW, 0);
    for (const name of ['codex', 'claude']) {
      assert.equal(m[name].known, false);
      assert.equal(m[name].text, '--');
      assert.equal(m[name].fill, null, 'unknown is not an empty gauge (that would be a real zero)');
      assert.equal(m[name].reset, '--');
      assert.equal(m[name].hearts.dot, true);
    }
    assert.equal(m.session, null);
  }
  const known = gb.hudModel({providers: {codex: provider(null, {count: 2, old: false})}}, NOW, 0);
  assert.deepEqual([known.codex.text, known.codex.hearts.full, known.codex.hearts.dot], ['--', 2, false], 'the saved resets are known even when the week is not');
  const fresh = {providers: {codex: provider(week(80)), claude: provider(week(50), {count: 1, old: false}, week(30, 2))}};
  assert.equal(gb.hudModel(fresh, NOW, 44000).codex.known, true, 'up to 45 s old is fine');
  assert.equal(gb.hudModel(fresh, NOW, 45001).codex.known, false, 'older than 45 s is unknown');
  assert.equal(gb.hudModel(fresh, NOW, 45001).session, null);
  assert.equal(gb.hudModel(fresh, NOW, Infinity).claude.known, false);
});

test('a known week: number, ten-part gauge fraction, countdown, hearts; zero and full are known and different from unknown', () => {
  const m = gb.hudModel({providers: {codex: provider(week(87.6, 76), {count: 2, old: false}), claude: provider(week(64.2, 36), {count: 3, old: true})}}, NOW, 0);
  assert.deepEqual([m.codex.known, m.codex.text, m.codex.reset, m.codex.hearts.full, m.codex.hearts.dot], [true, '87%', '3.1D', 2, false]);
  assert.ok(Math.abs(m.codex.fill - 0.876) < 1e-9);
  assert.deepEqual([m.claude.text, m.claude.reset, m.claude.hearts.full, m.claude.hearts.dot], ['64%', '1.5D', 3, true]);
  const zero = gb.hudModel({providers: {codex: provider(week(0, 5)), claude: provider(week(100, 5))}}, NOW, 0);
  assert.deepEqual([zero.codex.known, zero.codex.text, zero.codex.fill], [true, '0%', 0]);
  assert.deepEqual([zero.claude.known, zero.claude.text, zero.claude.fill], [true, '100%', 1]);
  assert.notEqual(zero.codex.fill, gb.hudModel(null, NOW, 0).codex.fill, 'a real zero differs from unknown');
  // a week is known only with a percentage and a reset still ahead
  for (const weekly of [{remaining: NaN, resets_at: secs(NOW) + 100}, {remaining: 120, resets_at: secs(NOW) + 100}, {remaining: -3, resets_at: secs(NOW) + 100}, {remaining: 50},
    {remaining: 50, resets_at: secs(NOW) - 1}, {remaining: '50', resets_at: secs(NOW) + 100}, null, 'x']) {
    const bad = gb.hudModel({providers: {codex: provider(weekly)}}, NOW, 0);
    assert.equal(bad.codex.known, false, JSON.stringify(weekly));
    assert.equal(bad.codex.text, '--');
  }
});

test('Claude\'s five hours: two five-part lines (quota in 5 % steps, time in quarter hours) only from a known, current reading; Codex never has them', () => {
  const m = gb.hudModel({providers: {codex: provider(week(80), undefined, week(30, 2)), claude: provider(week(50), undefined, week(41, 2.6))}}, NOW, 0);
  assert.equal(m.session.text, '41%');
  assert.equal(m.session.quota, 2.25, '41 % left is nine 5 % steps: two and a quarter of five hours-sized parts');
  assert.equal(m.session.time, 2.5, '2.6 hours left to the nearest quarter');
  const full = gb.hudModel({providers: {claude: provider(week(50), undefined, week(100, 5))}}, NOW, 0).session;
  assert.deepEqual([full.quota, full.time], [5, 5]);
  const low = gb.hudModel({providers: {claude: provider(week(50), undefined, week(1, 0.1))}}, NOW, 0).session;
  assert.deepEqual([low.text, low.quota, low.time], ['1%', 0.25, 0.0], 'a sliver of quota still shows a sliver; a few minutes left round to no time');
  const empty = gb.hudModel({providers: {claude: provider(week(50), undefined, week(0, 1))}}, NOW, 0).session;
  assert.deepEqual([empty.text, empty.quota], ['0%', 0], 'a real zero is a known, empty line');
  for (const session of [null, undefined, {remaining: 40}, {resets_at: secs(NOW) + 3600}, {remaining: 40, resets_at: secs(NOW) - 1}, {remaining: NaN, resets_at: secs(NOW) + 3600}, {remaining: 140, resets_at: secs(NOW) + 3600}]) {
    assert.equal(gb.hudModel({providers: {claude: provider(week(50), undefined, session)}}, NOW, 0).session, null, JSON.stringify(session));
  }
  assert.equal(gb.hudModel({providers: {codex: provider(week(80), undefined, week(30, 2))}}, NOW, 0).session, null, 'the session is Claude\'s alone');
});

test('the HUD key changes when anything shown changes and only then (the HUD picture is repainted on it)', () => {
  const a = {providers: {codex: provider(week(80)), claude: provider(week(50), undefined, week(40, 2))}};
  const k = (readings, now = NOW) => gb.hudModel(readings, now, 0).key;
  assert.equal(k(a), k(JSON.parse(JSON.stringify(a))), 'an identical reading is the same picture');
  assert.notEqual(k(a), k({providers: {codex: provider(week(79)), claude: a.providers.claude}}));
  assert.notEqual(k(a), k({providers: {codex: a.providers.codex, claude: provider(week(50), undefined, week(35, 2))}}));
  assert.notEqual(k(a), k({providers: {codex: provider(week(80), {count: null, old: false}), claude: a.providers.claude}}));
  assert.notEqual(k(a), k(null));
  assert.notEqual(k(a), k(a, NOW + 3 * 3600 * 1000), 'the countdown moves with the clock');
});

test('the clock: HH:MM in 24 hours with the leading zeros, and the colon off on odd seconds when it blinks', () => {
  const d = (h, m, s = 0) => ({getHours: () => h, getMinutes: () => m, getSeconds: () => s});
  assert.equal(gb.clockText(d(0, 0), false), '00:00');
  assert.equal(gb.clockText(d(9, 5), false), '09:05');
  assert.equal(gb.clockText(d(23, 59, 59), false), '23:59');
  assert.equal(gb.clockText(d(12, 34, 2), true), '12:34');
  assert.equal(gb.clockText(d(12, 34, 3), true), '12 34');
  assert.equal(gb.clockText(d(12, 34, 3), false), '12:34');
  assert.equal(gb.clockText(new Date(2026, 10, 9, 7, 8, 0), true), '07:08');
  assert.equal(gb.worldLabel(0), 'WORLD 1-1');
  assert.equal(gb.worldLabel(4), 'WORLD 2-1');
  assert.equal(gb.worldLabel(7), 'WORLD 2-4');
});

test('gauge segments fill from the left and partly: ten parts for a week, five for Claude\'s hours', () => {
  assert.equal(gb.segmentFill(0.876, 10, 7), 1);
  assert.ok(Math.abs(gb.segmentFill(0.876, 10, 8) - 0.76) < 1e-9);
  assert.equal(gb.segmentFill(0.876, 10, 9), 0);
  assert.equal(gb.segmentFill(0, 10, 0), 0);
  assert.equal(gb.segmentFill(1, 10, 9), 1);
  assert.equal(gb.segmentFill(0.5, 5, 2), 0.5);
});

/* ---- the console's layout --------------------------------------------------------------------------------------------------------------------------- */

test('layout: the LCD is 160 x 144 at one pixel per pixel, above the dock line, centred in the bezel; every control sits inside the picture and apart', () => {
  assert.equal(LCD.w, 160); assert.equal(LCD.h, 144);
  assert.equal(LCD.x * 2 + LCD.w, W, 'centred');
  assert.ok(LCD.y + LCD.h <= 186, 'the whole LCD stays above the dock\'s top (rows 0-185 are visible)');
  const L = gb.LAYOUT;
  assert.ok(L.bezel.x < LCD.x - 3 && L.bezel.y < LCD.y - 3 && L.bezel.x + L.bezel.w > LCD.x + LCD.w + 3 && L.bezel.y + L.bezel.h > LCD.y + LCD.h + 3, 'the bezel surrounds the LCD');
  for (const b of [L.a, L.b]) assert.ok(b.cx - b.r - 3 >= 0 && b.cx + b.r + 3 <= W && b.cy + b.r + 12 <= H, 'buttons inside the picture');
  assert.ok(Math.hypot(L.a.cx - L.b.cx, L.a.cy - L.b.cy) > L.a.r + L.b.r + 6, 'A and B do not touch');
  assert.ok(L.dpad.cx - L.dpad.arm >= 4 && L.dpad.cy + L.dpad.arm <= H - 4);
  assert.ok(L.select.x + L.select.w < L.start.x, 'Select left of Start');
  assert.ok(L.speaker.x + 6 * 7 <= W && L.speaker.y + 18 <= H);
});

test('touch: A, Up and the LCD make a jump, B and Right a faster run, everything else is a decoration; the touch follows the console when it slides up', () => {
  const L = gb.LAYOUT;
  assert.equal(gb.hitTest(L.a.cx, L.a.cy), 'a');
  assert.equal(gb.hitTest(L.b.cx, L.b.cy), 'b');
  assert.equal(gb.hitTest(L.dpad.cx, L.dpad.cy), 'dpad');
  assert.equal(gb.hitTest(L.dpad.cx, L.dpad.cy - 14), 'up');
  assert.equal(gb.hitTest(L.dpad.cx, L.dpad.cy + 14), 'down');
  assert.equal(gb.hitTest(L.dpad.cx - 14, L.dpad.cy), 'left');
  assert.equal(gb.hitTest(L.dpad.cx + 14, L.dpad.cy), 'right');
  assert.equal(gb.hitTest(L.select.x + 5, L.select.y + 2), 'select');
  assert.equal(gb.hitTest(L.start.x + 5, L.start.y + 2), 'start');
  assert.equal(gb.hitTest(100, 100), 'lcd');
  assert.equal(gb.hitTest(2, 2), null);
  assert.equal(gb.hitTest(100, 205), null, 'bare casing');
  assert.deepEqual(['a', 'up', 'lcd', 'b', 'right', 'left', 'down', 'start', 'select', 'dpad', null].map(gb.pokeAction), ['jump', 'jump', 'jump', 'boost', 'boost', null, null, null, null, null, null]);
});

test('the console slides up only when the visible area is shorter than the LCD needs, eases in whole pixels and lands exactly', () => {
  assert.equal(gb.shiftFor(186), 0, 'the tablet with its dock up');
  assert.equal(gb.shiftFor(320), 0, 'picture mode');
  assert.equal(gb.shiftFor(NaN), 0);
  assert.equal(gb.shiftFor(170), -16);
  assert.equal(gb.shiftFor(100), -24, 'never more than 24 rows');
  let s = 0;
  const seen = [];
  for (let i = 0; i < 20; i++) { const next = gb.easeShift(s, -24); assert.ok(Number.isInteger(next) && next <= s && s - next <= 12); s = next; seen.push(s); }
  assert.equal(s, -24);
  for (let i = 0; i < 20; i++) s = gb.easeShift(s, 0);
  assert.equal(s, 0);
  assert.ok(seen.slice(0, 5).some((v) => v > -24), 'a slide, not a jump');
});

/* ---- the level -------------------------------------------------------------------------------------------------------------------------------------- */

const countOf = (level, code) => { let n = 0; for (const v of level.tiles) if (v === code) n++; return n; };

test('a level is the same for a seed and different for another, and has the right shape: ground, pits of two or three cells, pipes, blocks on one row, walkers, a goal', () => {
  const a = gb.buildLevel(seeded(11)), b = gb.buildLevel(seeded(11)), c = gb.buildLevel(seeded(12));
  assert.deepEqual(Array.from(a.tiles), Array.from(b.tiles));
  assert.deepEqual(a.enemies, b.enemies);
  assert.notDeepEqual(Array.from(a.tiles), Array.from(c.tiles));
  let pitLevels = 0;
  for (const seed of [1, 2, 3, 4, 5, 6, 7, 8]) {
    const level = gb.buildLevel(seeded(seed));
    assert.equal(level.tiles.length, level.cols * ROWS);
    assert.equal(level.width, level.cols * TILE);
    const kinds = new Set(level.features.map((f) => f.kind));
    assert.ok(kinds.has('pipe') || kinds.has('wall'), 'obstacles');
    assert.ok(level.enemies.length >= 2 && level.enemies.length <= 30, `${level.enemies.length} walkers`);
    // the start is clear and flat, the goal is near the end
    for (let c2 = 0; c2 < 20; c2++) { assert.equal(level.tiles[GROUND * level.cols + c2], T.GROUND_TOP); for (let r = 0; r < GROUND; r++) assert.equal(level.tiles[r * level.cols + c2], T.AIR, `cell ${c2},${r} in the start`); }
    assert.equal(level.goal.col, level.cols - 28);
    for (let c2 = level.goal.col - 6; c2 < level.cols; c2++) for (let r = 0; r < GROUND; r++) assert.equal(level.tiles[r * level.cols + c2], T.AIR, 'the goal area is clear');
    // pits: two or three cells wide, ground gone in both rows, never next to another
    pitLevels += level.pits.length ? 1 : 0;
    for (const pit of level.pits) {
      assert.ok(pit.width >= 2 && pit.width <= 3);
      for (let i = 0; i < pit.width; i++) { assert.equal(level.tiles[GROUND * level.cols + pit.col + i], T.AIR); assert.equal(level.tiles[(GROUND + 1) * level.cols + pit.col + i], T.AIR); }
      assert.equal(level.tiles[GROUND * level.cols + pit.col - 1], T.GROUND_TOP);
      assert.equal(level.tiles[GROUND * level.cols + pit.col + pit.width], T.GROUND_TOP);
    }
    // pipes: two wide, two or three tall; blocks on row 12 only
    for (const f of level.features.filter((x) => x.kind === 'pipe')) { assert.ok(f.h === 2 || f.h === 3); for (let r = GROUND - f.h; r < GROUND; r++) assert.equal(level.tiles[r * level.cols + f.col], T.PIPE); assert.equal(level.tiles[(GROUND - f.h - 1) * level.cols + f.col], T.AIR); }
    for (let r = 0; r < ROWS; r++) for (let c2 = 0; c2 < level.cols; c2++) { const t = level.tiles[r * level.cols + c2]; if (t === T.Q || t === T.BRICK && r !== GROUND - 1 && r !== GROUND - 2) assert.equal(r, 12, `a block at row ${r}`); }
    assert.ok(countOf(level, T.Q) >= 1);
    // coins only in the air, walkers only on ground, scenery present
    for (let i = 0; i < level.coins.length; i++) if (level.coins[i]) assert.equal(level.tiles[i], T.AIR, 'a coin inside a solid cell');
    for (const e of level.enemies) { assert.ok(e.x > 100 && e.x < level.width - 200); assert.equal(e.y, GROUND_Y); assert.ok(gb.solidAt(level, Math.floor(e.x / TILE), GROUND)); }
    assert.ok(level.decor.clouds.length > 5 && level.decor.pyramids.length > 3 && level.decor.palms.length > 3);
    for (const cloud of level.decor.clouds) assert.ok(cloud.y >= 36 && cloud.y <= 62, 'clouds stay under the HUD and above the action');
  }
  assert.ok(pitLevels >= 4, `${pitLevels} of 8 levels have a pit`);
});

test('walkers keep their distance: a beat of about four cells and room all round, so the player always has a clear place to jump', () => {
  for (const seed of [1, 2, 3, 4, 5, 6]) {
    const level = gb.buildLevel(seeded(seed));
    for (const e of level.enemies) {
      const near = level.features.filter((f) => f.kind !== 'blobs' && f.kind !== 'tall' && f.kind !== 'coinrow' && f.kind !== 'coinarc');
      for (const f of near) {
        const from = f.col * TILE, to = (f.col + (f.w || 2 * (f.h || 1) + 2)) * TILE;
        assert.ok(e.x + PHY.beat + 16 < from || e.x - PHY.beat - 16 > to, `seed ${seed}: a walker at ${e.x} patrols into a ${f.kind} at ${from}-${to}`);
      }
    }
  }
});

/* ---- the physics ------------------------------------------------------------------------------------------------------------------------------------ */

const flatLevel = () => {
  const level = gb.buildLevel(seeded(1));
  level.tiles.fill(T.AIR); level.coins.fill(0);
  for (let c = 0; c < level.cols; c++) { level.tiles[GROUND * level.cols + c] = T.GROUND_TOP; level.tiles[(GROUND + 1) * level.cols + c] = T.GROUND; }
  level.enemies = []; level.features = []; level.pits = [];
  return level;
};
const body = (x = 40, y = GROUND_Y) => ({x, y, vx: 0, vy: 0, onGround: true});
const put = (level, c, r, t = T.HARD) => { level.tiles[r * level.cols + c] = t; };

test('physics: a body on the ground stays on it, runs at its speed, and a jump rises about 35 pixels (21 for the low one) and lands where the arc says', () => {
  const level = flatLevel(), p = body(), ev = {};
  for (let i = 0; i < 30; i++) gb.stepPlayer(level, p, {speed: PHY.speed, jump: 0}, ev);
  assert.equal(p.y, GROUND_Y); assert.equal(p.onGround, true); assert.ok(Math.abs(p.x - 100) < 1e-9);
  for (const [variant, lo, hi] of [['high', 33, 37], ['low', 19, 23]]) {
    const q = body(), e = {}; let top = GROUND_Y, steps = 0, started = false;
    for (let i = 0; i < 80; i++) { gb.stepPlayer(level, q, {speed: PHY.speed, jump: i === 0 ? variant : 0}, e); top = Math.min(top, q.y); if (!q.onGround) started = true; if (started && q.onGround) { steps = i + 1; break; } }
    assert.ok(GROUND_Y - top >= lo && GROUND_Y - top <= hi, `${variant}: ${GROUND_Y - top} px`);
    assert.ok(steps >= 20 && steps <= 30, `${variant}: ${steps} steps in the air`);
    assert.equal(q.y, GROUND_Y);
  }
  const b = body(); gb.stepPlayer(level, b, {speed: 0, jump: 'high'}, ev);
  assert.equal(ev.jumped, true);
  const air = body(40, 100); air.onGround = false; gb.stepPlayer(level, air, {speed: 2, jump: 'high'}, ev);
  assert.equal(ev.jumped, false, 'no jump in the air');
});

test('physics: a wall stops the body (and says so), a ledge is stood on, a low ceiling bumps the head and hands out the cell', () => {
  const level = flatLevel();
  put(level, 20, GROUND - 1); put(level, 20, GROUND - 2);                                    // a wall two cells high at x = 160
  const p = body(130), ev = {}; let blocked = false;
  for (let i = 0; i < 40; i++) { gb.stepPlayer(level, p, {speed: PHY.speed, jump: 0}, ev); blocked = blocked || ev.blocked; }
  assert.equal(blocked, true); assert.ok(p.x <= 160 - PHY.halfW + 1e-9, `at ${p.x}`);
  // a jump over a three-cell pipe lands on its top: feet exactly on the cell's top edge
  const tall = flatLevel(); for (let r = GROUND - 3; r < GROUND; r++) put(tall, 20, r, T.PIPE), put(tall, 21, r, T.PIPE);
  let onTop = false;
  for (let start = 0; start < 30 && !onTop; start++) {                                       // some take-off point lands on the top, and never inside the pipe
    const q = body(100);
    for (let i = 0; i < 70; i++) {
      gb.stepPlayer(tall, q, {speed: PHY.speed, jump: i === start ? 'high' : 0}, ev);
      assert.ok(!gb.solidAt(tall, Math.floor((q.x + PHY.halfW - 1e-6) / TILE), Math.floor((q.y - 4) / TILE)) || q.y <= (GROUND - 3) * TILE + 1e-9 || q.x < 160 - PHY.halfW + 1e-9, 'inside the pipe');
      if (q.onGround && q.y === (GROUND - 3) * TILE) onTop = true;
    }
  }
  assert.equal(onTop, true, 'the body came down on the pipe\'s top');
  // a block above the head: the head stops under it and the cell is reported
  const roof = flatLevel(); put(roof, 5, 12, T.Q);
  const r = body(44); let bumped = null; let top = 999;
  for (let i = 0; i < 40; i++) { gb.stepPlayer(roof, r, {speed: 0, jump: i === 0 ? 'high' : 0}, ev); if (ev.bump) bumped = ev.bump; top = Math.min(top, r.y - PHY.height); }
  assert.deepEqual(bumped, [5, 12]);
  assert.ok(top >= 12 * TILE + TILE - 1e-9, 'the head never went into the block');
});

test('physics: a pit swallows the body; walkers turn at walls and at the edge of a pit and keep to their beat; a stomped walker counts down and goes', () => {
  const level = flatLevel();
  for (let c = 12; c < 15; c++) { level.tiles[GROUND * level.cols + c] = T.AIR; level.tiles[(GROUND + 1) * level.cols + c] = T.AIR; }
  const p = body(70), ev = {}; let fell = false;
  for (let i = 0; i < 60; i++) { gb.stepPlayer(level, p, {speed: PHY.speed, jump: 0}, ev); if (p.y > GROUND_Y + 30) fell = true; }
  assert.equal(fell, true);
  const w = {kind: 'round', x: 130, y: GROUND_Y, dir: 1, home: 130, alive: true, state: 'walk', t: 0, anim: 0};
  let turns = 0, last = w.dir;
  for (let i = 0; i < 600; i++) { gb.stepEnemy(level, w); if (w.dir !== last) { turns++; last = w.dir; } assert.ok(Math.abs(w.x - 130) <= PHY.beat + 1, `wandered to ${w.x}`); assert.ok(gb.solidAt(level, Math.floor(w.x / TILE), GROUND), 'never over a pit'); }
  assert.ok(turns >= 4, `${turns} turns`);
  const flat = {kind: 'round', x: 50, y: GROUND_Y, dir: -1, alive: true, state: 'flat', t: 3, anim: 0};
  for (let i = 0; i < 3; i++) gb.stepEnemy(level, flat);
  assert.equal(flat.alive, false);
});

test('a touch on a walker is a stomp only when falling onto its top, and a hurt from the side, from below or when standing', () => {
  const walker = {kind: 'round', x: 100, y: GROUND_Y, dir: -1, alive: true, state: 'walk', t: 0};
  assert.equal(gb.touch({x: 100, y: GROUND_Y - 5, vy: 3}, walker), 'stomp');
  assert.equal(gb.touch({x: 100, y: GROUND_Y, vy: 0}, walker), 'hurt', 'standing on the same ground');
  assert.equal(gb.touch({x: 100 + 6, y: GROUND_Y, vy: 0}, walker), 'hurt', 'from the side');
  assert.equal(gb.touch({x: 100, y: GROUND_Y - 30, vy: 3}, walker), null, 'far above');
  assert.equal(gb.touch({x: 140, y: GROUND_Y, vy: 0}, walker), null, 'far aside');
  assert.equal(gb.touch({x: 100, y: GROUND_Y - 4, vy: -2}, walker), 'hurt', 'rising into it');
  assert.equal(gb.touch({x: 100, y: GROUND_Y - 5, vy: 3}, Object.assign({}, walker, {state: 'flat'})), null, 'a stomped one is harmless');
  assert.equal(gb.touch({x: 100, y: GROUND_Y - 5, vy: 3}, Object.assign({}, walker, {alive: false})), null);
});

/* ---- the auto-player -------------------------------------------------------------------------------------------------------------------------------- */

function play(seed, levels, extra) {
  const game = gb.createGame({rand: seeded(seed * 104729)});
  let steps = 0, maxStall = 0, minX = 1e9;
  while (game.stats.levels < levels && steps < 5200 * levels) {
    if (extra) extra(game, steps);
    const before = game.p.x;
    game.step(); steps++;
    if (game.phase === 'play') {
      maxStall = Math.max(maxStall, game.stall);
      assert.ok(!gb.solidAt(game.level, Math.floor(game.p.x / TILE), Math.floor((game.p.y - 8) / TILE)) || game.p.dead, `the body is inside a solid cell at step ${steps}`);
    }
    minX = Math.min(minX, game.p.x - before);
  }
  return {game, steps, maxStall};
}

test('the auto-player plays level after level without ever dying, being rescued or getting stuck, for many seeds', () => {
  for (let seed = 1; seed <= 24; seed++) {
    const {game, steps, maxStall} = play(seed, 1);
    assert.equal(game.stats.levels, 1, `seed ${seed} did not finish its level in ${steps} steps`);
    assert.equal(game.stats.deaths, 0, `seed ${seed}: died`);
    assert.equal(game.stats.rescues, 0, `seed ${seed}: the rescue had to step in`);
    assert.ok(maxStall < 40, `seed ${seed}: stood still for ${maxStall} steps`);
    assert.ok(steps >= 1000 && steps <= 1500, `seed ${seed}: a level took ${steps} steps (${(steps / 30).toFixed(0)} s)`);
    assert.ok(game.stats.jumps >= 10, `${game.stats.jumps} jumps`);
  }
  const {game} = play(99, 4);
  assert.equal(game.stats.levels, 4);
  assert.equal(game.number, 4, 'the fifth level is the next one');
  assert.deepEqual([game.stats.deaths, game.stats.rescues], [0, 0]);
});

test('the player does what a player does: stomps walkers, bumps ? blocks for coins, picks coins up, grabs the pole, slides, walks off and fades into the next level', () => {
  let stomps = 0, bumped = 0, coins = 0, phases = new Set(), events = new Set();
  for (let seed = 1; seed <= 6; seed++) {
    const {game} = play(seed, 1, (g) => { phases.add(g.phase); for (const e of g.events) events.add(e.t); });
    stomps += game.stats.stomps; bumped += game.stats.bumped; coins += game.stats.coins;
  }
  assert.ok(stomps >= 3, `${stomps} stomps in six levels`);
  assert.ok(bumped >= 10, `${bumped} blocks bumped`);
  assert.ok(coins >= 30, `${coins} coins`);
  for (const phase of ['intro', 'play', 'grab', 'win', 'walk', 'fade']) assert.ok(phases.has(phase), phase);
  for (const ev of ['level', 'cell', 'goal']) assert.ok(events.has(ev), ev);
});

test('a ? block becomes a used block when it is bumped and gives a coin once; a brick only hops', () => {
  const game = gb.createGame({rand: seeded(5)});
  game.phase = 'play';
  const level = game.level;
  level.tiles.fill(T.AIR); for (let c = 0; c < level.cols; c++) { level.tiles[GROUND * level.cols + c] = T.GROUND_TOP; level.tiles[(GROUND + 1) * level.cols + c] = T.GROUND; }
  level.enemies = []; game.enemies = []; level.coins.fill(0);
  put(level, 7, 12, T.Q); put(level, 8, 12, T.BRICK);
  game.p.x = 60; game.p.y = GROUND_Y; game.p.onGround = true;
  game.pendingJump = 0; game.boost = 0;
  const popsBefore = game.stats.coins;
  for (let i = 0; i < 40; i++) game.step();
  const cell = (c) => level.tiles[12 * level.cols + c];
  assert.ok(cell(7) === T.USED || cell(7) === T.Q);
  if (cell(7) === T.USED) assert.equal(game.stats.coins, popsBefore + 1);
  assert.equal(cell(8), T.BRICK, 'a brick stays a brick');
});

test('touches: a jump touch starts a jump within a moment; a boost touch is faster and waits for the ground when made in the air; neither ever kills', () => {
  const run = (kind, at) => { const g = gb.createGame({rand: seeded(7)}); for (let i = 0; i < at; i++) g.step(); const j0 = g.stats.jumps, x0 = g.p.x; g.poke(kind); for (let i = 0; i < 60; i++) g.step(); return {g, j: g.stats.jumps - j0, dx: g.p.x - x0}; };
  const base = run(null, 120), boosted = run('boost', 120);
  assert.ok(boosted.dx > base.dx + 20, `boost ${boosted.dx} px against ${base.dx}`);
  assert.equal(run('jump', 120).g.pendingJump >= 0, true);
  let jumped = 0;
  for (const at of [100, 130, 160, 190, 220, 250, 280, 310, 340, 400]) { const g = gb.createGame({rand: seeded(9)}); for (let i = 0; i < at; i++) g.step(); if (g.p.onGround) { const j0 = g.stats.jumps; g.poke('jump'); for (let i = 0; i < 30; i++) g.step(); if (g.stats.jumps > j0) jumped++; } }
  assert.ok(jumped >= 3, `${jumped} jump touches were answered with a jump`);
  const intro = gb.createGame({rand: seeded(7)});
  assert.equal(intro.poke('jump'), false, 'nothing during the level card');
  assert.equal(intro.poke('fly'), false);
  for (let seed = 1; seed <= 12; seed++) {
    const r = seeded(seed), {game} = play(seed, 2, (g) => { if (r() < 0.02) g.poke(r() < 0.5 ? 'jump' : 'boost'); });
    assert.equal(game.stats.levels, 2, `seed ${seed}`);
    assert.deepEqual([game.stats.deaths, game.stats.rescues], [0, 0], `seed ${seed}: a touch must never get the player hurt`);
  }
});

test('the planner never mutates the world it looks into: looking ahead twice gives the same answer and leaves tiles, coins, walkers and the player as they were', () => {
  const game = gb.createGame({rand: seeded(3)});
  for (let i = 0; i < 300; i++) game.step();
  const snap = () => JSON.stringify({p: game.p, e: game.enemies, t: Array.from(game.level.tiles), c: Array.from(game.level.coins), b: game.boost});
  const before = snap();
  const a = gb.look(game, 'high', 90, 5), b = gb.look(game, 'high', 90, 5);
  assert.deepEqual(a, b);
  assert.equal(snap(), before);
  assert.equal(gb.runSafe(game, 30), gb.runSafe(game, 30));
  assert.equal(snap(), before);
});

test('the same seed plays the same game, step for step; another seed another one', () => {
  const trace = (seed) => { const g = gb.createGame({rand: seeded(seed)}); const out = []; for (let i = 0; i < 700; i++) { g.step(); if (i % 10 === 0) out.push([g.p.x, g.p.y, g.phase, g.stats.jumps].join(',')); } return out.join(';'); };
  assert.equal(trace(5), trace(5));
  assert.notEqual(trace(5), trace(6));
});

/* ---- drawing, with a fake canvas and a fictional atlas ---------------------------------------------------------------------------------------------- */

function fakeContext(width, height) {
  const calls = {fillRect: 0, clearRect: 0, drawImage: 0, save: 0, restore: 0, getImageData: 0, putImageData: 0, other: 0, last: []};
  const ctx = {calls, canvas: null, imageSmoothingEnabled: true, fillStyle: '', globalAlpha: 1, globalCompositeOperation: 'source-over', width, height};
  for (const name of ['fillRect', 'clearRect', 'drawImage', 'save', 'restore']) ctx[name] = (...args) => { calls[name]++; if (name === 'drawImage') calls.last.push(args); };
  ctx.translate = () => { calls.other++; }; ctx.scale = () => { calls.other++; };
  ctx.getImageData = (x, y, w, h) => { calls.getImageData++; const data = new Uint8ClampedArray(w * h * 4); for (let i = 0; i < w * h; i++) { data[i * 4] = (i % 4) * 85; data[i * 4 + 3] = i % 7 ? 255 : 0; } return {data, width: w, height: h}; };
  ctx.putImageData = () => { calls.putImageData++; };
  return ctx;
}
function installDocument() {
  const made = [];
  globalThis.document = {createElement(tag) {
    assert.equal(tag, 'canvas');
    const canvas = {width: 0, height: 0, getContext() { if (!this.ctx) { this.ctx = fakeContext(this.width, this.height); this.ctx.canvas = this; } return this.ctx; }};
    made.push(canvas);
    return canvas;
  }};
  return made;
}
function fictionalAtlas(omit) {
  const frames = {}; let x = 0, y = 0;
  const size = (name) => /^hero/.test(name) ? [16, 16] : name === 'walker-b-0' || name === 'walker-b-1' ? [8, 16] : name === 'pipe-top' ? [16, 16] : name === 'pipe-body' ? [16, 8] : /^cloud-l/.test(name) ? [48, 16]
    : /^cloud-m/.test(name) ? [32, 16] : /^cloud-s/.test(name) ? [24, 16] : /^(pyr-peak|palm-crown|flag-cloth)$/.test(name) ? [16, 8] : [8, 8];
  const names = gb.REQUIRED_FRAMES.concat(Array.from('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ:-%.,!x ', (c) => 'g-' + c));
  for (const name of names) {
    if (name === omit) continue;
    const [w, h] = size(name);
    if (x + w > 256) { x = 0; y += 16; }
    frames[name] = [x, y, w, h]; x += w + 1;
  }
  const glyphs = {};
  for (const c of '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ:-%.,!x ') glyphs[c] = 'g-' + c;
  return {version: 1, scene: 'game-boy', size: [256, 64], shades: 4, step: 85, tile: 8, lcd: [160, 144], frames, glyphs};
}
function makeScene(options = {}) {
  const made = installDocument();
  const scene = Object.create(engine.registry['game-boy']);
  scene.dbg = Object.assign({now: NOW, noStale: true}, options.dbg || {});
  const api = {name: 'game-boy', size: [200, 320], atlas: options.atlas === false ? null : {naturalWidth: 256, naturalHeight: 64}, json: options.atlas === false ? null : (options.json || fictionalAtlas()),
    time: 0, tier: options.tier || 'high', random: seeded(0x5eed ^ 9 * 7919), view: {top: 0, bottom: options.bottom || 186}, readings: () => (options.readings === undefined ? null : typeof options.readings === 'function' ? options.readings() : options.readings)};
  scene.init(api);
  const g = fakeContext(200, 320);
  return {scene, api, g, made};
}
const KNOWN = () => ({providers: {codex: provider(week(87.6, 76)), claude: provider(week(64.2, 36), {count: 3, old: false}, week(41, 2.6))}});

test('atlas reader: frames and glyphs by name, anything missing makes it unusable (the plain LCD is drawn instead), junk is ignored', () => {
  const art = gb.readArt(fictionalAtlas());
  assert.ok(art);
  assert.equal(art.step, 85);
  assert.deepEqual(art.frames['hero-stand'], [art.frames['hero-stand'][0], art.frames['hero-stand'][1], 16, 16]);
  assert.ok(art.glyphs['A'] && art.glyphs['%'] && art.glyphs[':'] && art.glyphs['0']);
  for (const missing of ['hero-stand', 'ground', 'block-q', 'flag-cloth', 'cloud-l']) assert.equal(gb.readArt(fictionalAtlas(missing)), null, missing);
  for (const bad of [null, undefined, 1, 'x', {}, {frames: null}, {frames: []}, {frames: {a: [1, 2, 3, 4]}}]) assert.equal(gb.readArt(bad), null, JSON.stringify(bad));
  const withJunk = fictionalAtlas(); withJunk.frames.junk = [1, 2, 3]; withJunk.frames.nan = [NaN, 0, 8, 8]; withJunk.glyphs.Q2 = 'g-A'; withJunk.glyphs['?'] = 'nope';
  const art2 = gb.readArt(withJunk);
  assert.ok(art2.frames.junk === undefined && art2.frames.nan === undefined && art2.glyphs['?'] === undefined && art2.glyphs.Q2 === undefined);
});

test('the atlas is re-coloured: the four greys become the LCD\'s four greens, transparent stays transparent', () => {
  const data = new Uint8ClampedArray([0, 0, 0, 255, 85, 85, 85, 255, 170, 170, 170, 255, 255, 255, 255, 255, 170, 170, 170, 0, 90, 90, 90, 255]);
  gb.recolorPixels(data, 85, gb.SHADES);
  const px = (i) => Array.from(data.slice(i * 4, i * 4 + 4));
  assert.deepEqual(px(0), [...gb.SHADES[0], 255]); assert.deepEqual(px(1), [...gb.SHADES[1], 255]); assert.deepEqual(px(2), [...gb.SHADES[2], 255]); assert.deepEqual(px(3), [...gb.SHADES[3], 255]);
  assert.equal(px(4)[3], 0, 'transparent stays transparent');
  assert.deepEqual(px(5), [...gb.SHADES[1], 255], 'a grey near a step takes its nearest shade');
  for (let i = 0; i < 3; i++) assert.ok(gb.SHADES[i][1] > gb.SHADES[i + 1][1], 'lightest to darkest');
  assert.ok(Math.abs(gb.SHADES[0][1] - gb.SHADES[1][1]) >= 25, 'the two lightest greens stay apart');
});

test('every frame is painted and stays cheap: the console, the LCD, a few dozen calls, with and without readings, atlas or fast tiers', () => {
  for (const options of [{readings: KNOWN()}, {readings: null}, {atlas: false, readings: KNOWN()}, {tier: 'low'}, {tier: 'light', readings: KNOWN()}]) {
    const {scene, api, g} = makeScene(options);
    let worstMain = 0, worstLcd = 0;
    for (let i = 0; i < 1300; i++) {
      scene.step(api, 1 / 30);
      if (i % 25) continue;
      const lcd = scene.s.canvases.lcd.g;
      const before = {main: g.calls.drawImage + g.calls.fillRect, lcd: lcd.calls.drawImage + lcd.calls.fillRect};
      scene.draw(api, g);
      worstMain = Math.max(worstMain, g.calls.drawImage + g.calls.fillRect - before.main);
      worstLcd = Math.max(worstLcd, lcd.calls.drawImage + lcd.calls.fillRect - before.lcd);
    }
    assert.ok(worstMain >= 8 && worstMain <= 40, `${JSON.stringify(Object.keys(options))}: ${worstMain} calls on the picture`);
    assert.ok(worstLcd >= 4 && worstLcd <= 90, `${JSON.stringify(Object.keys(options))}: ${worstLcd} calls on the LCD`);
    assert.equal(scene.s.game.stats.deaths, 0);
  }
});

test('the picture is built from the casing, the LCD at its place, the recess shadow and the buttons; the LCD ghost is used at the high tiers only', () => {
  const high = makeScene({readings: KNOWN()});
  high.scene.step(high.api, 1 / 30); high.scene.draw(high.api, high.g);
  const placed = high.g.calls.last.filter((a) => a.length === 3);
  assert.ok(placed.some((a) => a[1] === 0 && a[2] === 0), 'the casing at the origin');
  assert.ok(placed.some((a) => a[1] === LCD.x && a[2] === LCD.y), 'the LCD at its window');
  assert.ok(placed.length >= 8, 'casing, LCD, overlay, cross, A, B, Start, Select');
  const lcdHigh = high.scene.s.canvases.lcd.g.calls.drawImage;
  const low = makeScene({readings: KNOWN(), tier: 'low'});
  low.scene.step(low.api, 1 / 30); low.scene.draw(low.api, low.g);
  assert.ok(low.scene.s.canvases.lcd.g.calls.drawImage < lcdHigh, 'no ghost at the lowest tier');
});

test('the HUD is repainted only when something shown changed, and shows the fresh readings, the unknown ones and the clock', () => {
  let readings = KNOWN();
  const {scene, api} = makeScene({readings: () => readings});
  const hud = () => scene.s.canvases.hud.g.calls;
  scene.step(api, 1 / 30);
  const first = scene.s.hudKey;
  assert.ok(scene.s.model.codex.text === '87%' && scene.s.model.claude.hearts.full === 3);
  const painted = hud().fillRect + hud().drawImage;
  for (let i = 0; i < 60; i++) scene.step(api, 1 / 30);
  assert.equal(scene.s.hudKey, first, 'nothing changed');
  assert.equal(hud().fillRect + hud().drawImage, painted, 'so nothing was repainted');
  readings = JSON.parse(JSON.stringify(KNOWN())); readings.providers.codex.weekly.remaining = 12;
  for (let i = 0; i < 12; i++) scene.step(api, 1 / 30);
  assert.equal(scene.s.model.codex.text, '12%');
  assert.notEqual(scene.s.hudKey, first);
  assert.ok(hud().fillRect + hud().drawImage > painted, 'a changed number is repainted');
  readings = null;
  for (let i = 0; i < 12; i++) scene.step(api, 1 / 30);
  assert.equal(scene.s.model.codex.text, '--', 'a lost feed is unknown at once');
  assert.ok(scene.s.hudKey.endsWith('|' + gb.clockText(new Date(NOW), true)), 'the clock is part of the picture');
});

test('a reading the page stopped renewing is dropped after 45 seconds, and a renewed one comes back', () => {
  const object = KNOWN();
  const {scene, api} = makeScene({readings: () => object, dbg: {noStale: false}});
  scene.step(api, 1 / 30); for (let i = 0; i < 6; i++) scene.step(api, 1 / 30);
  assert.equal(scene.s.model.codex.known, true);
  scene.s.readingSeen = Date.now() - 46000;
  for (let i = 0; i < 6; i++) scene.step(api, 1 / 30);
  assert.equal(scene.s.model.codex.known, false, 'the same old object, older than 45 s');
});

test('the scene never throws: a broken or missing atlas, an odd view, taps everywhere, a paused clock, hundreds of levels\' worth of steps', () => {
  const broken = fictionalAtlas(); delete broken.frames['hero-jump'];
  for (const options of [{atlas: false}, {json: broken}, {json: {frames: {}}}, {json: {}}, {bottom: 100}, {bottom: 320}, {bottom: NaN}]) {
    const {scene, api, g} = makeScene(options);
    for (let i = 0; i < 400; i++) { scene.step(api, 1 / 30); scene.draw(api, g); if (i % 37 === 0) scene.poke(api, (i * 13) % 200, (i * 29) % 320); }
    assert.ok(scene.s.canvases.casing, JSON.stringify(Object.keys(options)));
  }
  const plain = makeScene({atlas: false});
  assert.equal(plain.scene.s.art, null, 'a missing atlas means the plain LCD');
  for (let i = 0; i < 100; i++) { plain.scene.step(plain.api, 1 / 30); plain.scene.draw(plain.api, plain.g); }
  assert.ok(plain.g.calls.drawImage > 0);
});

test('a short visible area slides the console up and a touch still lands on the right button', () => {
  const {scene, api, g} = makeScene({bottom: 120});
  for (let i = 0; i < 20; i++) { scene.step(api, 1 / 30); scene.draw(api, g); }
  assert.equal(scene.s.shift, -24);
  assert.deepEqual(scene.pixelRect(), [LCD.x, LCD.y - 24, LCD.w, LCD.h], 'the crisp screen moves with the console');
  const L = gb.LAYOUT;
  scene.poke(api, L.b.cx, L.b.cy - 24);
  assert.ok(scene.s.taps.b > 0, 'B was pressed through the slide');
  scene.poke(api, L.b.cx, L.b.cy);
  assert.equal(scene.s.taps.a, undefined);
});

test('a touch on a button presses it for a moment and starts the reaction', () => {
  const {scene, api} = makeScene({readings: KNOWN()});
  for (let i = 0; i < 80; i++) scene.step(api, 1 / 30);
  const L = gb.LAYOUT;
  scene.poke(api, L.b.cx, L.b.cy);
  assert.ok(scene.s.taps.b > 0);
  assert.ok(scene.s.game.boost > 0 || scene.s.game.boostNext > 0, 'a faster run');
  scene.poke(api, L.a.cx, L.a.cy);
  assert.ok(scene.s.taps.a > 0);
  assert.ok(scene.s.game.pendingJump > 0 || scene.s.game.p.hold > 0, 'a jump');
  scene.poke(api, L.start.x + 3, L.start.y + 2);
  assert.ok(scene.s.taps.start > 0, 'a decoration: pressed and nothing else');
  for (let i = 0; i < 10; i++) scene.step(api, 1 / 30);
  assert.equal(scene.s.taps.start, undefined, 'a tap is short');
  assert.equal(scene.s.taps.b, undefined);
});

test('one more look at the pieces that must never break: whole-pixel logic, the module\'s shape and the four greens', () => {
  const scene = engine.registry['game-boy'];
  assert.equal(scene.post, 'handheld');
  const game = gb.createGame({rand: seeded(2)});
  for (let i = 0; i < 500; i++) game.step();
  assert.ok(Number.isInteger(game.cam) && Number.isInteger(game.steps));
  assert.equal(gb.SHADES.length, 4);
  assert.equal(gb.playerFrame(game).startsWith('hero-'), true);
  const walker = {kind: 'tall', state: 'walk', anim: 0, dir: 1, t: 0};
  assert.deepEqual(gb.walkerFrame(walker), ['walker-b-0', true]);
  assert.deepEqual(gb.walkerFrame(Object.assign({}, walker, {state: 'shell', t: 20})), ['shell-0', false]);
  assert.deepEqual(gb.walkerFrame({kind: 'round', state: 'flat', anim: 3, dir: -1, t: 5}), ['walker-a-flat', false]);
  assert.equal(H, 320);
});

test('the first level starts playing at once (a still picture shows the game), every later one opens with its level card for about a second and a half', () => {
  const {scene, api, g} = makeScene({readings: KNOWN()});
  assert.equal(scene.s.game.phase, 'play');
  scene.draw(api, g);                                                          // the engine draws once right after init (and once for a still)
  const fresh = gb.createGame({rand: seeded(4)});
  assert.equal(fresh.phase, 'intro');
  let cardSteps = 0;
  while (fresh.phase === 'intro') { fresh.step(); cardSteps++; }
  assert.equal(cardSteps, gb.INTRO);
  assert.ok(gb.INTRO / 30 > 1.2 && gb.INTRO / 30 < 2);
  const long = gb.createGame({rand: seeded(4)});
  long.startLevel(1);
  assert.equal(long.phase, 'intro');
  // the card is drawn on the LCD over the sky: its text comes from the glyph pictures
  const second = makeScene({readings: KNOWN()});
  second.scene.s.game.startLevel(2);
  second.scene.step(second.api, 1 / 30);
  assert.equal(second.scene.s.game.phase, 'intro');
  const lcd = second.scene.s.canvases.lcd.g, before = lcd.calls.drawImage;
  second.scene.draw(second.api, second.g);
  assert.ok(lcd.calls.drawImage - before >= 9, 'the nine letters of WORLD 1-3, then the HUD');
});

test('the Game Boy replaces each exhausted week with its supplied credit balance', () => {
  const codex={...provider(week(0)),credits:'2468'},claude={...provider(week(0)),credits:'12.5'};
  const model=gb.hudModel({providers:{codex,claude}},NOW,0);
  assert.equal(model.codex.text,'CR 2468');
  assert.equal(model.claude.text,'CR 12.5');
  assert.equal(model.codex.fill,0,'the weekly meter still truthfully shows the empty week');
  assert.notEqual(model.key,gb.hudModel({providers:{codex:{...codex,credits:'2467'},claude}},NOW,0).key,'credit changes repaint the HUD');
  for (const credits of ['?',null,'0','0.00','-2.35','-<0.01','12<script>']) {
    assert.equal(gb.hudModel({providers:{claude:{...claude,credits}}},NOW,0).claude.text,'0%','no credit mode without positive confirmed credit');
  }
  assert.equal(gb.hudModel({providers:{claude:{...claude,weekly:week(0.2),credits:'12.5'}}},NOW,0).claude.text,'1%');
  assert.equal(gb.hudModel({providers:{codex:{...codex,weekly:week(1)}}},NOW,0).codex.text,'1%');
  assert.equal(gb.hudModel({providers:{codex:{...codex,weekly:week(0,-1)}}},NOW,0).codex.text,'--');
  assert.equal(gb.hudModel({providers:{codex}},NOW,46000).codex.text,'--','old data never displays a balance');
});
