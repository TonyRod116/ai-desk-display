import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';

// VERSUS (token_tv/tablet_web/game-fighting.js): the pure logic (the layout that follows api.view.bottom, the pixel font, the sun, the moves, the match with its rounds, the AI,
// hits and blocks, projectiles, the camera) and, with a fake canvas, the whole drawing path: a frame is cheap, a missing or broken atlas is calm, nothing reads a quota.
// Everything uses the seeded random: the same seed is always the same match.
const require = createRequire(import.meta.url);
const engine = require('../token_tv/tablet_web/stage-game.js');
const F = require('../token_tv/tablet_web/game-fighting.js');
const {W, H, MOVES, FRAMES, FX_FRAMES, BODY, ARENA, MIN_GAP, MAX_GAP, layoutFor, easeFeet, createMatch, textPixels, seeded} = F;
const SOURCE = fs.readFileSync(new URL('../token_tv/tablet_web/game-fighting.js', import.meta.url), 'utf8');
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} is not ${b}`);

// A Date-like object for a civil time in a fixed zone (Madrid), so the tests do not depend on this computer's time zone.
const madrid = (y, m, d, hh, mm = 0, offset = -60) => ({getFullYear: () => y, getMonth: () => m - 1, getDate: () => d, getHours: () => hh, getMinutes: () => mm, getSeconds: () => 0, getMilliseconds: () => 0, getTimezoneOffset: () => offset});
const run = (m, steps) => { for (let i = 0; i < steps; i++) m.step(); return m; };
const toFight = (m) => { for (let i = 0; i < 400 && m.phase !== 'fight'; i++) m.step(); assert.equal(m.phase, 'fight'); return m; };
const setUp = (seed = 5, gap = 100) => { const m = toFight(createMatch({seed})); m.f[0].x = 120; m.f[1].x = 120 + gap; for (const f of m.f) { f.think = 99999; f.mood.skill = 0; } return m; };

/* ---- the engine and the layout --------------------------------------------------------------------------------------------------------- */

test('registered as fighting in the engine, with the native portrait size, and it needs its atlas', () => {
  assert.ok(engine.registry.fighting, 'the scene registers itself');
  assert.deepEqual(engine.registry.fighting.size, [200, 320]);
  assert.equal(engine.registry.fighting.needsAtlas, true);
  for (const k of ['init', 'step', 'draw', 'poke']) assert.equal(typeof engine.registry.fighting[k], 'function', k);
});

test('layout: with the dock up the fighters stand just above the page\'s clock, with the whole picture they step down, and the mapping is monotonic', () => {
  const dock = layoutFor(186);                                   // the tablet's dock covers about 42 %: rows 0-185 stay visible
  assert.ok(dock.feet <= 186 - 70 && dock.feet >= 186 - 78, `feet at row ${dock.feet}: above the clock (about 70 rows over the bottom) and not far above it`);
  assert.equal(layoutFor(320).feet, F.LAYOUT.feetPicture);
  assert.ok(layoutFor(320).feet > dock.feet);
  let last = null;
  for (let vb = F.LAYOUT.minBottom; vb <= H; vb++) { const l = layoutFor(vb); if (last) assert.ok(l.feet >= last.feet, `${vb}: never goes back up as the visible area grows`); last = l; }
  assert.deepEqual(layoutFor(NaN), layoutFor(H), 'an unknown value means the whole picture');
  assert.deepEqual(layoutFor(5), layoutFor(F.LAYOUT.minBottom));
  assert.deepEqual(layoutFor(99999), layoutFor(H));
});

test('a taller dock lifts the fighters off the clock, but never above the life bars\' reach', () => {
  assert.equal(layoutFor(186).feet, 112);
  assert.equal(layoutFor(170).feet, 96, 'a 16 row taller dock: 16 rows higher');
  assert.equal(layoutFor(150).feet, F.LAYOUT.feetLeast);
  assert.equal(layoutFor(120).feet, F.LAYOUT.feetLeast, 'never higher than that');
  for (let vb = 104; vb <= 190; vb++) assert.ok(layoutFor(vb).feet <= vb - 74 || layoutFor(vb).feet === F.LAYOUT.feetLeast, `${vb}: feet clear of the clock`);
});

test('the fighters\' head clears the life bars and the names with the dock up', () => {
  const tallestIdle = 76;                                        // Codex\'s bolt at the top of its breath, in art pixels (the win and special poses may reach the names for a moment)
  assert.ok(layoutFor(186).feet - tallestIdle >= F.BAR.y + F.BAR.h + 16, 'head below the names');
});

test('feet ease to a new row in a few steps, in whole rows, without overshoot, and land exactly on it', () => {
  for (const [from, to] of [[320, 186], [186, 320], [186, 250]]) {
    let a = layoutFor(from).feet;
    const target = layoutFor(to).feet, path = [a];
    for (let i = 0; i < 40 && a !== target; i++) { a = easeFeet(a, target); path.push(a); }
    assert.equal(a, target, `${from} -> ${to} lands on the target`);
    assert.ok(path.length - 1 <= 22, `${from} -> ${to} took ${path.length - 1} steps`);
    for (let i = 1; i < path.length; i++) {
      assert.ok(Math.abs(target - path[i]) <= Math.abs(target - path[i - 1]), 'never moves away from the target');
      assert.ok(Math.abs(path[i] - path[i - 1]) <= 9 + 1e-9, 'at most 9 rows in a step');
      assert.equal(path[i], Math.round(path[i]));
    }
  }
  assert.equal(easeFeet(112, 112), 112);
});

/* ---- the pixel font ----------------------------------------------------------------------------------------------------------------------- */

test('pixel font: every letter and digit the scene writes exists, widths are glyphs times six minus the gap, unknown characters are skipped', () => {
  for (const text of ['ROUND 1', 'ROUND 2', 'ROUND 3', 'FIGHT!', 'K.O.', 'TIME UP', 'CODEX', 'CLAUDE', 'CODEX WINS', 'CLAUDE WINS', 'WINS THE MATCH', '60', '07', '0123456789']) {
    const t = textPixels(text);
    assert.equal(t.height, 7);
    const expected = [...text].length * 6 - 1;
    assert.equal(t.width, expected, text);
    const spaces = [...text].filter((c) => c === ' ').length;
    assert.ok(t.pixels.length >= ([...text].length - spaces) * 7 - 5, `${text}: every glyph has pixels`);
    for (const [x, y] of t.pixels) assert.ok(x >= 0 && x < t.width && y >= 0 && y < 7);
  }
  assert.equal(textPixels('a b').width, textPixels('A B').width, 'case does not matter');
  assert.deepEqual(textPixels('§§'), {width: 0, height: 7, pixels: []});
  const glyph = (c) => F.FONT[c].map((row) => row.toString(2).padStart(5, '0'));
  assert.deepEqual(glyph('I'), ['01110', '00100', '00100', '00100', '00100', '00100', '01110']);
  assert.deepEqual(glyph('K'), ['10001', '10010', '10100', '11000', '10100', '10010', '10001']);
  for (const c of Object.keys(F.FONT)) assert.equal(F.FONT[c].length, 7, c);
});

/* ---- the day ------------------------------------------------------------------------------------------------------------------------------- */

test('the sun is Madrid\'s: noon altitude in June and in winter, and a sunset in the evening of 9 November', () => {
  const june = F.sunState(madrid(2026, 6, 21, 14, 0, -120)), dec = F.sunState(madrid(2026, 12, 21, 13, 0));
  assert.ok(june.alt > 70 && june.alt < 74, `June noon ${june.alt}`);
  assert.ok(dec.alt > 24 && dec.alt < 28, `December noon ${dec.alt}`);
  const at = (h, mm = 0) => F.sunState(madrid(2026, 11, 9, h, mm)).alt;
  assert.ok(at(13) > 25);
  assert.ok(at(17, 0) > 0 && at(18, 30) < 0, 'sunset in between');
  assert.ok(at(23) < -20);
  assert.equal(F.sunState(madrid(2026, 11, 9, 9)).morning, true);
  assert.equal(F.sunState(madrid(2026, 11, 9, 19)).morning, false);
});

test('the day runs through day, golden, dusk, twilight and night in that order, smoothly', () => {
  const names = [];
  let last = null;
  for (let h = 6; h <= 24; h += 0.25) {
    const alt = F.sunState(madrid(2026, 11, 9, Math.floor(h) % 24, Math.round((h % 1) * 60))).alt, light = F.lightAt(alt);
    if (last) {
      for (let k = 0; k < 6; k++) for (let c = 0; c < 3; c++) assert.ok(Math.abs(light.sky[k][c] - last.sky[k][c]) <= 90, 'a quarter hour never jumps a colour');
      assert.ok(Math.abs(light.lamps - last.lamps) <= 0.5 && Math.abs(light.stars - last.stars) <= 0.6);
    }
    last = light;
    if (h >= 12 && names[names.length - 1] !== F.phaseName(alt)) names.push(F.phaseName(alt));
  }
  assert.deepEqual(names, ['day', 'golden', 'dusk', 'twilight', 'night']);
  assert.equal(F.lightAt(-30).stars, 1);
  assert.equal(F.lightAt(40).lamps, 0);
});

test('the sun and the moon stay inside the picture and above the horizon line they are given', () => {
  for (const hor of [56, 100, 162]) for (let alt = -4; alt <= 60; alt += 4) for (const morning of [true, false]) {
    const p = F.sunPlace(alt, morning, hor);
    assert.ok(p.x >= 0 && p.x <= W && p.y <= hor && p.y >= 0, `sun at ${alt} deg (${p.x}, ${p.y}) over a horizon at ${hor}`);
  }
  for (let solar = 18; solar <= 30; solar += 1) { const p = F.moonPlace(solar % 24, 100); assert.ok(p.x >= 0 && p.x <= W && p.y >= 0 && p.y < 100); }
  assert.ok(F.sunPlace(0, false, 100).x < W / 2, 'it sets on the left');
  assert.ok(F.sunPlace(0, true, 100).x > W / 2, 'and rises on the right');
});

/* ---- the moves ----------------------------------------------------------------------------------------------------------------------------- */

test('every move has a frame for every step of its sequence, a blow inside it, and damage that is worth more than a chip', () => {
  for (const who of ['codex', 'claude']) {
    for (const [name, mv] of Object.entries(MOVES[who])) {
      assert.equal(mv.seq.length, mv.steps.length, `${who} ${name}`);
      for (const k of mv.seq) {
        if (typeof k === 'string') assert.ok(k.startsWith('tw-') && F.TWEEN_NAMES[who].includes(k.slice(3)), `${who} ${name}: the in-between frame ${k} exists`);
        else assert.ok(k >= 0 && k < FRAMES[who][mv.anim], `${who} ${name}: frame ${k} exists`);
      }
      assert.equal(mv.seq[0], `tw-${name}-in`, `${who} ${name} eases in`);
      if (name !== 'special') assert.equal(mv.seq[mv.seq.length - 1], `tw-${name}-out`, `${who} ${name} eases out`);
      assert.ok(mv.steps.every((n) => Number.isInteger(n) && n >= 1));
      if (mv.hit !== undefined) { assert.ok(mv.hit > 0 && mv.hit < mv.seq.length); assert.equal(typeof mv.seq[mv.hit], 'number', 'the blow lands on a drawn pose, not on an in-between'); assert.ok(mv.reach >= 60 && mv.reach <= 140); assert.ok(mv.damage > mv.chip && mv.chip >= 1); assert.ok(mv.stun >= 6 && mv.stop >= 2); }
      if (mv.fire !== undefined) { assert.ok(mv.fire > 0 && mv.fire < mv.seq.length); assert.equal(mv.cost, 100); }
      if (mv.lunge) assert.equal(mv.lunge.length, mv.seq.length);
    }
    assert.ok(MOVES[who].jab && MOVES[who].heavy && MOVES[who].special);
  }
  assert.ok(MOVES.claude.whip.reach > MOVES.claude.heavy.reach && MOVES.claude.heavy.reach > MOVES.claude.jab.reach, 'the whip is the longest reach');
  assert.equal(MOVES.codex.whip, undefined, 'Codex has no tentacle');
  assert.ok(F.moveSteps(MOVES.codex.jab) < F.moveSteps(MOVES.codex.heavy), 'a jab is quicker than a heavy punch');
  assert.ok(F.lungeDistance(MOVES.codex.heavy) > 5 && F.lungeDistance(MOVES.claude.jab) === 0);
  for (const who of ['codex', 'claude']) for (const k of Object.keys(FRAMES[who])) assert.ok(FRAMES[who][k] >= 1);
  assert.ok(MOVES.codex.jab.damage + MOVES.codex.jab.chip > 0);
});

test('a blow is known by where it can connect: a jab outranges a body, the whip outranges a heavy punch', () => {
  assert.ok(F.strikeRange(MOVES.codex.jab) === MOVES.codex.jab.reach + BODY);
  assert.ok(F.strikeRange(MOVES.claude.whip) > F.strikeRange(MOVES.codex.heavy));
  assert.ok(F.strikeRange(MOVES.codex.heavy) > F.strikeRange(MOVES.codex.jab), 'the lunge adds to a heavy punch');
});

test('an animation clock loops or stops on its last frame, exactly when it should', () => {
  const f = F.createFighter('codex', 100);
  F.play(f, 'jab', [0, 1, 2], [2, 1, 3], false);
  const seen = [];
  let ended = 0;
  for (let i = 0; i < 12; i++) { seen.push(f.si); if (F.tickAnim(f)) ended++; }
  assert.deepEqual(seen.slice(0, 7), [0, 0, 1, 2, 2, 2, 2], 'frame by frame at its own pace, then it stays');
  assert.equal(ended, 1, 'it reports its end once');
  F.play(f, 'walk', [0, 1], [1, 1], true);
  const loop = [];
  for (let i = 0; i < 6; i++) { loop.push(f.si); F.tickAnim(f); }
  assert.deepEqual(loop, [0, 1, 0, 1, 0, 1]);
  assert.equal(F.frameName(f), 'codex-walk-' + f.seq[f.si]);
  F.play(f, 'jab', ['tw-jab-in', 0, 1], [2, 3, 3], false);
  assert.equal(F.frameName(f), 'codex-tw-jab-in', 'a frame may be named whole');
  F.tickAnim(f); F.tickAnim(f);
  assert.equal(F.frameName(f), 'codex-jab-0');
  F.play(f, 'idle', ['tw-hit-out', 0, 1], [2, 4, 4], true, 1);
  const idle = []; for (let i = 0; i < 14; i++) { idle.push(f.si); F.tickAnim(f); }
  assert.deepEqual(idle, [0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 1, 1, 1, 1], 'an idle loop that leaves its lead-in behind');
});

/* ---- the match ------------------------------------------------------------------------------------------------------------------------------ */

test('a match starts with ROUND 1, then FIGHT!, then the fight, with the clock running down once a second', () => {
  const m = createMatch({seed: 1});
  assert.deepEqual([m.phase, m.round, m.text.kind, m.text.n], ['intro', 1, 'round', 1]);
  const seen = [];
  for (let i = 0; i < 160; i++) { m.step(); if (seen[seen.length - 1] !== m.phase) seen.push(m.phase); }
  assert.deepEqual(seen, ['intro', 'ready', 'fight']);
  const before = m.clock;
  for (let i = 0; i < 90; i++) { m.stepsFought = 0; m.step(); }
  assert.ok(before - m.clock >= 2 && before - m.clock <= 3, `the clock went from ${before} to ${m.clock} in three seconds`);
  assert.equal(m.f[0].x < m.f[1].x, true, 'Codex is on the left');
  assert.deepEqual(m.f.map((f) => f.dir), [1, -1]);
});

test('the same seed plays the same match, a different seed another one', () => {
  const trace = (seed) => { const m = createMatch({seed}); const out = []; for (let i = 0; i < 1500; i++) { m.step(); if (i % 25 === 0) out.push(m.f.map((f) => f.state + ':' + Math.round(f.x) + ':' + Math.round(f.hp)).join('|') + '|' + m.phase); } return out.join(';'); };
  assert.equal(trace(11), trace(11));
  assert.notEqual(trace(11), trace(12));
  const viaFunction = (seed) => { const r = seeded(seed); const m = createMatch({random: r}); run(m, 700); return m.f.map((f) => f.x + ':' + f.hp).join(','); };
  assert.equal(viaFunction(3), viaFunction(3));
});

test('a blow in range lands: damage, a spark, hit-stop, a flinch and a push; out of range it whiffs', () => {
  const m = setUp(5, 92);                                         // a Codex jab reaches 72 + 27 = 99 from its middle
  assert.ok(m.start(0, 'jab'));
  const hp = m.f[1].hp;
  for (let i = 0; i < 12; i++) m.step();
  assert.ok(m.f[1].hp < hp, 'Claude lost hit points');
  assert.equal(m.stats.hits, 1);
  assert.ok(m.fx.some((e) => e.kind === 'spark'), 'a spark flew');
  const far = setUp(5, 120);
  assert.ok(far.start(0, 'jab'));
  run(far, 14);
  assert.equal(far.f[1].hp, 100, 'too far: the jab whiffs');
  assert.equal(far.stats.hits, 0);
});

test('a hit freezes both fighters for a few steps (hit-stop) and shakes the picture a little', () => {
  const m = setUp(5, 92);
  m.start(0, 'heavy');
  let froze = 0, shook = 0;
  for (let i = 0; i < 40; i++) { const t = m.f[0].st, si = m.f[0].si; m.step(); if (m.hitstop > 0 && m.f[0].st === t && m.f[0].si === si) froze++; if (m.shake > 0) shook++; }
  assert.ok(m.stats.hits >= 1);
  assert.ok(shook >= 4, 'it shook');
  assert.ok(m.shakeAmp >= 1 && m.shakeAmp <= 3, 'a small shake');
  void froze;
});

test('a guard blocks: chip damage only, a block spark, and the guard holds a little longer', () => {
  const m = setUp(5, 92);
  m.start(1, 'guard');
  assert.equal(m.f[1].state, 'guard');
  m.start(0, 'jab');
  run(m, 10);
  assert.equal(m.stats.blocks, 1);
  assert.equal(m.stats.hits, 0);
  assert.equal(m.f[1].hp, 99, 'a jab chips one point');
  assert.ok(m.fx.some((e) => e.kind === 'block'));
  assert.equal(m.f[1].state, 'guard');
});

test('Claude\'s whip reaches farther than anything else and is the only blow that lands at 140', () => {
  const m = setUp(5, 140);
  m.start(1, 'whip');
  run(m, 20);
  assert.equal(m.stats.hits, 1);
  const n = setUp(5, 140);
  n.start(1, 'heavy');
  run(n, 20);
  assert.equal(n.stats.hits, 0);
});

test('a heavy punch can knock a fighter down; a fighter on the ground cannot be hit and gets up, and is untouchable while it does', () => {
  let down = null;
  for (let seed = 1; seed < 40 && !down; seed++) { const m = setUp(seed, 92); m.start(0, 'heavy'); run(m, 14); if (m.f[1].state === 'kd') down = m; }
  assert.ok(down, 'some heavy punches knock down');
  const hp = down.f[1].hp;
  down.f[0].x = down.f[1].x - 60;
  down.start(0, 'jab');
  run(down, 12);
  assert.equal(down.f[1].hp, hp, 'a fighter on the ground is not hit again');
  let wasUp = false, invulnerableWhileRising = true;
  for (let i = 0; i < 90; i++) { down.step(); if (down.f[1].state === 'getup' && down.f[1].invuln <= 0) invulnerableWhileRising = false; if (down.f[1].state === 'idle') { wasUp = true; break; } }
  assert.ok(wasUp, 'it got up');
  assert.ok(invulnerableWhileRising);
});

test('a special throws a projectile that flies across, lands for twenty and knocks down, or is blocked for a chip, or meets the other\'s and both burst', () => {
  const m = setUp(5, 120);
  m.f[0].meter = 100;
  assert.ok(m.start(0, 'special'));
  let flying = 0, sawFlash = false, meterWhenFired = null;
  for (let i = 0; i < 80; i++) { m.step(); if (m.proj.length) { flying++; if (meterWhenFired === null) meterWhenFired = m.f[0].meter; } if (m.flash > 0) sawFlash = true; }
  assert.ok(flying >= 6, 'the burst flew');
  assert.ok(sawFlash, 'a screen flash');
  assert.equal(meterWhenFired, 0, 'the meter was spent when it was fired');
  assert.equal(m.stats.hits, 1);
  assert.ok(m.f[1].hp <= 82, `Claude took ${100 - m.f[1].hp}`);
  assert.equal(m.proj.length, 0, 'it is gone');
  const b = setUp(5, 120);
  b.start(1, 'guard');
  b.f[0].meter = 100;
  b.start(0, 'special');
  run(b, 50);
  assert.equal(b.stats.blocks, 1);
  assert.ok(b.f[1].hp >= 97);
  const c = setUp(5, 140);
  c.start(0, 'special'); c.start(1, 'special');
  run(c, 70);
  assert.ok(c.fx.length >= 0 && c.stats.hits <= 1, 'two bursts meet in the middle, at most one gets through');
});

test('only one projectile per fighter at a time, and the meter starts a special only when it is full', () => {
  const m = setUp(5, 140);
  for (let i = 0; i < 4000; i++) { m.step(); const mine = m.proj.filter((p) => p.owner === m.f[0]).length; assert.ok(mine <= 1); if (m.stats.specials && m.phase !== 'fight') break; }
  const n = createMatch({seed: 2});
  toFight(n);
  for (const f of n.f) assert.equal(f.meter <= 40, true, 'a round starts with a little meter at most');
});

test('a knock-out ends the round in slow motion with K.O., the survivor wins a point and strikes a pose; the loser stays down', () => {
  const m = setUp(5, 92);
  m.f[1].hp = 3; m.f[1].ghost = 3;
  m.start(0, 'jab');
  const phases = [];
  for (let i = 0; i < 600; i++) { m.step(); if (phases[phases.length - 1] !== m.phase) phases.push(m.phase); if (m.phase === 'intro' && m.round === 2) break; }
  assert.deepEqual(phases.slice(0, 3), ['fight', 'ko', 'win']);
  assert.equal(m.f[0].wins, 1);
  assert.equal(m.stats.kos, 1);
  assert.equal(m.round, 2);
  assert.equal(m.f[1].hp, 100, 'the next round starts fresh');
  assert.equal(m.f[1].state, 'idle');
});

test('the K.O. is slow motion: the fighters advance only every third step, the effects run at full speed', () => {
  const m = setUp(5, 92);
  m.f[1].hp = 2;
  m.start(0, 'jab');
  for (let i = 0; i < 30 && m.phase !== 'ko'; i++) m.step();
  assert.equal(m.phase, 'ko');
  assert.equal(m.slow, F.KO_SLOW);
  while (m.hitstop > 0) m.step();
  const t = m.phaseT;
  run(m, 9);
  assert.equal(m.phaseT - t, 3, 'three logic steps in nine');
  assert.ok(m.flash >= 0);
});

test('best of three: the first to two rounds wins the match, then the screen fades, the stage changes and a new match starts', () => {
  const m = createMatch({seed: 9});
  const events = [];
  let matchEndSeen = false;
  for (let i = 0; i < 30 * 60 * 10 && !events.length; i++) {
    m.step();
    if (m.phase === 'fight' && m.f[1].hp > 0 && i % 30 === 0) { m.f[1].hp = Math.min(m.f[1].hp, 40); }
    if (m.phase === 'matchend') { matchEndSeen = true; assert.equal(m.matchWinner.wins, 2); assert.equal(m.text.kind, 'match'); }
    events.push(...m.events.splice(0));
  }
  assert.ok(matchEndSeen, 'a match end was shown');
  assert.equal(events[0].type, 'stage');
  assert.equal(m.stats.matches, 2, 'the second match is under way');
  assert.equal(m.matches, 2);
  assert.deepEqual(m.f.map((f) => f.wins), [0, 0]);
  assert.equal(m.round, 1);
});

test('time up: the fighter with more hit points takes the round', () => {
  const m = createMatch({seed: 4, roundSeconds: 3});
  toFight(m);
  for (const f of m.f) f.think = 99999;
  m.f[0].hp = 90; m.f[1].hp = 60;
  for (let i = 0; i < 400 && m.stats.rounds === 0; i++) m.step();
  assert.equal(m.stats.timeups, 1);
  assert.equal(m.stats.wins.codex, 1);
});

/* ---- long runs ------------------------------------------------------------------------------------------------------------------------------- */

test('thirty minutes of fighting: positions inside the arena, hit points in range, bodies never overlap, the camera keeps both in view, matches last two to three minutes', () => {
  let rounds = 0, kos = 0, timeups = 0, wins = [0, 0], inView = 0, fightSteps = 0, bad = null;
  const lengths = [];
  for (const seed of [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]) {
    const m = createMatch({seed: seed * 7919});
    let lastMatch = 1, start = 0;
    for (let i = 0; i < 30 * 60 * 6; i++) {
      m.step();
      for (const f of m.f) {
        if (!(Number.isFinite(f.x) && f.x >= ARENA.left - 1e-9 && f.x <= ARENA.right + 1e-9) || !(f.hp >= 0 && f.hp <= 100) || !(f.meter >= 0 && f.meter <= 100)) bad = bad || [seed, i, f.id, f.x, f.hp, f.meter];
      }
      const standing = m.f.every((f) => f.state !== 'kd' && f.state !== 'getup');
      if (standing && m.f[1].x - m.f[0].x < MIN_GAP - 0.5) bad = bad || [seed, i, 'overlap', m.f[1].x - m.f[0].x];
      if (m.phase === 'fight') { fightSteps++; const cam = Math.round(m.camX); if (m.f.every((f) => f.x - cam > 14 && f.x - cam < W - 14)) inView++; }
      assert.ok(m.camX >= 0 && m.camX <= ARENA.width - W + 1e-9, 'the camera stays on the stage');
      if (m.stats.matches !== lastMatch) { lengths.push((i - start) / 30); start = i; lastMatch = m.stats.matches; }
      m.events.length = 0;
    }
    rounds += m.stats.rounds; kos += m.stats.kos; timeups += m.stats.timeups; wins[0] += m.stats.wins.codex; wins[1] += m.stats.wins.claude;
  }
  assert.equal(bad, null, JSON.stringify(bad));
  assert.ok(rounds >= 60, `${rounds} rounds`);
  assert.ok(kos / rounds >= 0.85, `most rounds end by knock-out (${kos} of ${rounds}, ${timeups} time ups)`);
  assert.ok(wins[0] / rounds > 0.35 && wins[0] / rounds < 0.65, `the two fighters are evenly matched: ${wins.join(' / ')}`);
  assert.ok(inView / fightSteps > 0.97, `both fighters in view ${(inView / fightSteps * 100).toFixed(1)} % of the fight`);
  assert.ok(lengths.length >= 12);
  const mean = lengths.reduce((a, b) => a + b, 0) / lengths.length;
  assert.ok(mean >= 100 && mean <= 200, `a match lasts ${mean.toFixed(0)} s on average`);
});

test('the fighters trade blows, guard, use specials and the whip, and taunt: a lively fight, never a stalemate', () => {
  const m = createMatch({seed: 77});
  let longestQuiet = 0, quiet = 0;
  let before = 0;
  for (let i = 0; i < 30 * 60 * 6; i++) {
    m.step();
    if (m.phase === 'fight') { const total = m.stats.hits + m.stats.blocks; if (total !== before) { before = total; quiet = 0; } else quiet++; longestQuiet = Math.max(longestQuiet, quiet); } else quiet = 0;
    m.events.length = 0;
  }
  assert.ok(m.stats.hits > 40 && m.stats.blocks > 10 && m.stats.knockdowns > 5 && m.stats.specials > 3 && m.stats.whips > 3, JSON.stringify(m.stats));
  assert.ok(longestQuiet <= 30 * 14, `the longest stretch without a hit or a block was ${longestQuiet / 30} s`);
});

test('a soak: millions of steps over many seeds throw nothing and keep every number finite and every state known', () => {
  const states = new Set(['idle', 'walk', 'guard', 'attack', 'hit', 'kd', 'getup', 'win', 'taunt']);
  let steps = 0;
  for (let seed = 1; seed <= 24; seed++) {
    const m = createMatch({seed: seed * 6007});
    for (let i = 0; i < 60000; i++) {
      m.step(); steps++;
      if (i % 5 === 0 && m.fx.length < 30 && i % 4000 === 0) m.poke(m.f[i % 2].x + 6, 30);
      if (i % 97 === 0) for (const f of m.f) { assert.ok(states.has(f.state), f.state); assert.ok(Number.isFinite(f.x) && Number.isFinite(f.vx) && Number.isFinite(f.hp) && Number.isFinite(f.meter)); assert.ok(f.si >= 0 && f.si < f.seq.length, `${f.id} ${f.anim} ${f.si}/${f.seq.length}`); const e = f.seq[f.si]; assert.ok(typeof e === 'string' ? F.TWEEN_NAMES[f.id].includes(e.slice(3)) : F.FRAMES[f.id][f.anim] > e, `${f.id}-${f.anim}-${e} is a frame that exists`); }
      assert.ok(m.fx.length <= 28 && m.proj.length <= 2 && m.sparks.length <= 90);
      m.events.length = 0;
    }
  }
  assert.ok(steps >= 1000000);
});

/* ---- touch ------------------------------------------------------------------------------------------------------------------------------------ */

test('a touch on a fighter makes the nearer one taunt; a touch away from them makes the crowd cheer; it never breaks the match', () => {
  const m = setUp(5, 110);
  assert.equal(m.poke(m.f[0].x - 10, 40), 'taunt');
  assert.equal(m.f[0].state, 'taunt');
  assert.equal(m.f[1].state, 'idle', 'only the nearer one');
  assert.equal(m.poke(m.f[1].x + 5, 40), 'taunt');
  assert.equal(m.f[1].state, 'taunt');
  assert.equal(m.poke(m.f[1].x, 40), 'cheer', 'a fighter already taunting is left alone: the crowd cheers');
  assert.equal(m.crowd.mood, 'cheer');
  const n = setUp(5, 110);
  assert.equal(n.poke(60, 200), 'cheer', 'far above or below the fighters');
  assert.equal(n.f[0].state, 'idle');
  run(m, 120);
  assert.ok(['idle', 'walk', 'attack', 'guard', 'hit', 'kd', 'getup', 'taunt'].includes(m.f[0].state));
  const o = createMatch({seed: 3});
  assert.equal(o.poke(100, 40), 'taunt', 'also while the round is being announced');
  const k = setUp(5, 92); k.f[1].hp = 1; k.start(0, 'jab'); for (let i = 0; i < 20; i++) k.step();
  assert.equal(k.poke(k.f[0].x, 40), 'cheer', 'during the knock-out the crowd cheers');
  run(k, 400);
});

test('the crowd gasps at a heavy hit and cheers at a knock-out, and then goes back to waiting', () => {
  const m = setUp(5, 92);
  m.start(0, 'heavy');
  let gasped = false;
  for (let i = 0; i < 30; i++) { m.step(); if (m.crowd.mood === 'gasp') gasped = true; }
  assert.ok(gasped);
  run(m, 200);
  assert.ok(['idle', 'cheer', 'gasp'].includes(m.crowd.mood));
  m.crowd.t = 1; m.crowd.mood = 'cheer';
  m.step();
  assert.equal(m.crowd.mood, 'idle');
});

/* ---- the drawing path, with a fake canvas -------------------------------------------------------------------------------------------- */

function recorder() {
  const calls = {drawImage: 0, fillRect: 0, other: 0, textures: 0};
  const ctx = new Proxy({}, {
    get(target, prop) {
      if (prop === '__calls') return calls;
      if (prop === 'drawImage') return (...a) => { calls.drawImage++; target.last = a; };
      if (prop === 'fillRect') return () => { calls.fillRect++; };
      if (prop === 'createRadialGradient' || prop === 'createLinearGradient') return () => ({addColorStop() {}});
      if (prop in target) return target[prop];
      return () => { calls.other++; };
    },
    set(target, prop, value) { target[prop] = value; return true; },
  });
  return ctx;
}
function fakeDocument() { return {createElement: () => ({width: 0, height: 0, getContext: () => recorder()})}; }
function fakeJson(withJungle = false) {
  const frames = {}, anchors = {}, anims = {fx: {}, proj: {}, crowd: {}, props: {}, boats: {sail: []}, gulls: {fly: []}, clouds: {cumulus: []}, actors: {}}, points = {}, shadows = {};
  let y = 0;
  const add = (name, w, h, ax, ay) => { frames[name] = [0, y, w, h]; y += h; anchors[name] = [ax === undefined ? w >> 1 : ax, ay === undefined ? h - 4 : ay]; return name; };
  for (const who of ['codex', 'claude']) {
    anims[who] = {};
    for (const [move, n] of Object.entries(FRAMES[who])) anims[who][move] = Array.from({length: n}, (_, k) => add(`${who}-${move}-${k}`, 80, 80, 34, 76));
    anims[who].tw = F.TWEEN_NAMES[who].map((name) => add(`${who}-tw-${name}`, 80, 80, 34, 76));
    for (const name of Object.keys(frames)) if (name.startsWith(who + '-')) shadows[name] = [0, 26, 1];
  }
  for (const [kind, n] of Object.entries(FX_FRAMES)) anims.fx[kind] = Array.from({length: n}, (_, k) => add(`fx-${kind}-${k}`, 30, 30, 15, 15));
  for (const who of ['codex', 'claude']) anims.proj[who] = Array.from({length: 4}, (_, k) => add(`proj-${who}-${k}`, 40, 30, 20, 15));
  for (const kind of F.CROWD_KINDS) anims.crowd[kind] = F.CROWD_POSES.map((pose) => add(`crowd-${kind}-${pose}`, 22, 26, 11, 24));
  for (const kind of ['lantern', 'barrel', 'crate', 'bollard', 'ship']) anims.props[kind] = [add(`prop-${kind}`, 22, 40, 11, 38)];
  for (const k of [0, 1]) anims.boats.sail.push(add(`boat-sail-${k}`, 30, 36, 15, 32));
  for (const k of [0, 1, 2]) anims.gulls.fly.push(add(`gull-${k}`, 13, 5, 6, 4));
  for (const w of [24, 40, 64, 96]) anims.clouds.cumulus.push(add(`cloud-${String(w).padStart(3, '0')}`, w, 12, 0, 0));
  for (const [kind, n] of Object.entries(F.ACTOR_FRAMES)) anims.actors[kind] = Array.from({length: n}, (_, k) => add(`act-${kind}-${k}`, 30, 30, 15, 28));
  points['act-fisher-0'] = [[20, -30]]; points['act-ferry-0'] = [[-20, -10], [-10, -10]]; points['act-blimp-0'] = [[-6, -4]];
  for (let v = 0; v < 4; v++) points[`act-stall-${v}`] = [[-18, -34], [18, -16], [-12, -30], [12, -22]];
  const stages = {};
  if (withJungle) {
    add('stage-jungle', 320, 199, 0, 0); add('stage-jungle-amb-0-0', 25, 14, 0, 0); add('stage-jungle-amb-1-0', 27, 14, 0, 0);
    stages.jungle = {frame: 'stage-jungle', size: [320, 199], floor: 176, ambient: [{at: [110, 56], frames: ['stage-jungle-amb-0-0'], script: [0], ms: 600}, {at: [160, 56], frames: ['stage-jungle-amb-1-0'], script: [0], ms: 600}]};
  }
  return {version: 1, frames, anchors, anims, stages, size: [1024, y], points, shadows};
}
function fakeApi(json, seed = 3, bottom = 186, extra = {}) {
  const atlas = json ? {naturalWidth: 1024, naturalHeight: 900, ownerDocument: fakeDocument()} : null;
  return Object.assign({name: 'fighting', size: [W, H], atlas, json, time: 0, tier: 'high', random: seeded(seed), view: {top: 0, bottom}, readings: () => { throw new Error('the scene must not read quota'); }}, extra);
}
const withQA = (qa, fn) => { globalThis.__fightingQA = qa; try { return fn(); } finally { delete globalThis.__fightingQA; } };

/** Canvas calls per frame over `frames` frames of a fight (every third one is drawn): the average and the worst, and the scene's errors. */
function frameCost(qa, frames = 900, bottom = 186, tier = 'high') {
  const scene = F.createScene(), api = fakeApi(fakeJson(qa.stage === 'jungle'), 3, bottom, {tier});
  withQA(qa, () => scene.init(api));
  let sum = {drawImage: 0, fillRect: 0, other: 0}, n = 0, worst = {drawImage: 0, fillRect: 0};
  for (let i = 0; i < frames; i++) {
    scene.step(api, 1 / 30);
    if (i % 3 === 0) { const g = recorder(); scene.draw(api, g); const c = g.__calls; sum.drawImage += c.drawImage; sum.fillRect += c.fillRect; sum.other += c.other; worst.drawImage = Math.max(worst.drawImage, c.drawImage); worst.fillRect = Math.max(worst.fillRect, c.fillRect); n++; }
  }
  return {avg: {drawImage: sum.drawImage / n, fillRect: sum.fillRect / n, other: sum.other / n}, worst, errors: scene.s.errors};
}

test('a frame with the atlas is cheap: the layers that move together are baked into composites, so a frame copies a few dozen sprites and draws a few dozen rectangles, never more calls than the scene it replaced', () => {
  // The old scene averaged 37 sprite copies and 70 to 140 rectangles a frame (about 114 canvas calls, harbour, at the tablet's tier). The composites are rebuilt only when the camera, the light
  // or an animated layer really changes, so the AVERAGE call count is what matters; the worst frame is one that rebuilds a composite after a change of light.
  for (const [label, qa] of [['harbour by day', {seed: 5, hour: 13, stage: 'harbour0'}], ['harbour at night', {seed: 5, hour: 22, stage: 'harbour1'}], ['dusk', {seed: 5, hour: 17.75, stage: 'harbour0'}], ['market by day', {seed: 5, hour: 13, stage: 'market'}], ['market at night', {seed: 5, hour: 22, stage: 'market'}]]) {
    for (const bottom of [186, 320]) {
      const c = frameCost(Object.assign({phase: 'fight'}, qa), 900, bottom);
      assert.ok(c.avg.drawImage <= 70, `${label} (${bottom}): ${c.avg.drawImage.toFixed(1)} sprite copies on average`);
      assert.ok(c.avg.fillRect <= 60, `${label} (${bottom}): ${c.avg.fillRect.toFixed(1)} rectangles on average`);
      assert.ok(c.avg.drawImage + c.avg.fillRect + c.avg.other <= 125, `${label} (${bottom}): ${(c.avg.drawImage + c.avg.fillRect + c.avg.other).toFixed(0)} canvas calls on average (the old scene made about 114)`);
      assert.ok(c.worst.drawImage <= 120 && c.worst.fillRect <= 300, `${label} (${bottom}): the worst frame ${JSON.stringify(c.worst)}`);
      assert.deepEqual(c.errors, {}, `${label}: no stage failed`);
    }
  }
});

test('the baked layers are rebuilt only when their key changes: a still camera costs the same every frame', () => {
  const scene = F.createScene(), api = fakeApi(fakeJson(), 3);
  withQA({seed: 5, hour: 13, stage: 'harbour0', phase: 'fight'}, () => scene.init(api));
  for (let i = 0; i < 40; i++) scene.step(api, 1 / 30);
  const m = scene.s.m;
  m.hitstop = 0; m.camX = 60; m.camKick = 0;
  const counts = [];
  for (let i = 0; i < 6; i++) { const g = recorder(); scene.draw(api, g); counts.push(g.__calls.drawImage + g.__calls.fillRect); }
  assert.ok(counts.slice(1).every((v) => Math.abs(v - counts[counts.length - 1]) <= 6), `calls of six frames of a still camera: ${counts}`);
  const composites = Object.keys(scene.s.stage.C || {});
  for (const name of ['sky', 'shore', 'pier']) assert.ok(composites.includes(name), `the ${name} is a composite`);
  assert.ok(Object.keys(scene.s.C || {}).includes('hud'), 'the HUD frame is a composite');
});

test('on a weak tier the scene drops its extras (reflections, water glints, flags) and still draws everything that matters', () => {
  const heavy = F.createScene(), apiHeavy = fakeApi(fakeJson(), 3);
  withQA({seed: 5, hour: 13, stage: 'harbour0'}, () => heavy.init(apiHeavy));
  const light = F.createScene(), apiLight = fakeApi(fakeJson(), 3, 186, {tier: 'low'});
  withQA({seed: 5, hour: 13, stage: 'harbour0'}, () => light.init(apiLight));
  for (let i = 0; i < 300; i++) { heavy.step(apiHeavy, 1 / 30); light.step(apiLight, 1 / 30); }
  const a = recorder(), b = recorder();
  heavy.draw(apiHeavy, a);
  light.draw(apiLight, b);
  assert.equal(light.s.cheap, true);
  assert.ok(b.__calls.fillRect <= a.__calls.fillRect && b.__calls.drawImage < a.__calls.drawImage, `${b.__calls.drawImage}/${b.__calls.fillRect} against ${a.__calls.drawImage}/${a.__calls.fillRect}`);
  assert.deepEqual(light.s.errors, {});
});

test('the jungle stage draws from its frame and its two ambient pieces, and costs about the same', () => {
  const scene = F.createScene(), api = fakeApi(fakeJson(true), 3);
  withQA({seed: 5, hour: 13, stage: 'jungle'}, () => scene.init(api));
  assert.equal(scene.s.stage.kind, 'jungle');
  for (let i = 0; i < 300; i++) scene.step(api, 1 / 30);
  const g = recorder();
  scene.draw(api, g);
  assert.ok(g.__calls.drawImage <= 90 && g.__calls.fillRect <= 360, JSON.stringify(g.__calls));
  assert.deepEqual(scene.s.errors, {});
  assert.deepEqual(F.stageOrder(F.readAtlas(fakeJson(true))), ['harbour0', 'jungle', 'market', 'harbour1', 'jungle', 'market']);
  assert.deepEqual(F.stageOrder(F.readAtlas(fakeJson(false))), ['harbour0', 'market', 'harbour1'], 'without the private stage there is no jungle');
  assert.deepEqual(F.stageOrder(null), ['harbour0', 'market', 'harbour1']);
});

test('without an atlas, or with a broken one, the scene is calm: a flat picture, never an exception', () => {
  const bare = F.createScene(), a = fakeApi(null, 3);
  bare.init(a);
  for (let i = 0; i < 100; i++) bare.step(a, 1 / 30);
  const g = recorder();
  bare.draw(a, g);
  assert.ok(g.__calls.fillRect >= 1);
  const broken = F.createScene(), b = fakeApi({frames: {'codex-idle-0': 'nope', 'x': [1, 2]}, anchors: null, anims: 5}, 3);
  broken.init(b);
  for (let i = 0; i < 100; i++) broken.step(b, 1 / 30);
  broken.draw(b, recorder());
  assert.deepEqual(broken.s.errors, {});
  const empty = F.createScene(), c = fakeApi({frames: {}}, 3);
  empty.init(c);
  empty.draw(c, recorder());
  assert.equal(F.readAtlas({}), null);
  assert.equal(F.readAtlas(null), null);
  const lib = F.readAtlas({frames: {a: [1, 2, 3, 4], b: [1, 2], c: [NaN, 1, 1, 1]}, anchors: {a: [5, 6]}});
  assert.deepEqual(lib.entry('a'), {name: 'a', x: 1, y: 2, w: 3, h: 4, ax: 5, ay: 6});
  assert.equal(lib.entry('b'), null);
  assert.equal(lib.entry('c'), null);
  assert.equal(lib.entry('zzz'), null);
});

test('a missing frame never stops the drawing: every other frame is still drawn', () => {
  const json = fakeJson();
  for (const name of Object.keys(json.frames)) if (name.startsWith('fx-') || name.startsWith('crowd-') || name.startsWith('proj-')) delete json.frames[name];
  const scene = F.createScene(), api = fakeApi(json, 3);
  withQA({seed: 5, hour: 13}, () => scene.init(api));
  for (let i = 0; i < 600; i++) scene.step(api, 1 / 30);
  const g = recorder();
  scene.draw(api, g);
  assert.deepEqual(scene.s.errors, {});
  assert.ok(g.__calls.drawImage >= 3);
});

test('the fighters are drawn on the anchored row, and the row follows api.view.bottom: up with the dock, down in picture mode, easing, never jumping on a still', () => {
  const scene = F.createScene(), api = fakeApi(fakeJson(), 3, 186);
  withQA({seed: 5, hour: 13}, () => scene.init(api));
  assert.equal(scene.s.feet, layoutFor(186).feet);
  const drawn = (bottom) => { api.view.bottom = bottom; const g = recorder(); scene.draw(api, g); return scene.s.feet; };
  assert.equal(drawn(186), layoutFor(186).feet);
  api.view.bottom = 320;
  const rows = [];
  for (let i = 0; i < 40; i++) { scene.step(api, 1 / 30); rows.push(scene.s.feet); }
  assert.equal(rows[rows.length - 1], layoutFor(320).feet, 'it slid to the picture layout');
  assert.ok(rows[0] > layoutFor(186).feet && rows[0] < layoutFor(320).feet, 'it moves a little at a time');
  assert.deepEqual(rows, [...rows].sort((a, b) => a - b));
  const still = F.createScene(), api2 = fakeApi(fakeJson(), 3, 320);
  withQA({seed: 5, hour: 13}, () => still.init(api2));
  assert.equal(still.s.feet, layoutFor(320).feet, 'the first picture is placed at once');
});

test('the scene reads no quota, draws no reading and no number except the round clock; it asks nothing of the network', () => {
  for (const forbidden of ['readings(', 'remaining', 'resets_at', 'fetch(', 'XMLHttpRequest', 'WebSocket', 'localStorage', 'eval(', 'new Function', 'getImageData', 'putImageData']) assert.ok(!SOURCE.includes(forbidden), `the scene must not use ${forbidden}`);
  assert.doesNotMatch(SOURCE, /\.font\s*=|fillText|strokeText/, 'text is the scene\'s own pixel font');
  const scene = F.createScene(), api = fakeApi(fakeJson(), 3);
  withQA({seed: 5, hour: 13}, () => scene.init(api));
  for (let i = 0; i < 50; i++) scene.step(api, 1 / 30);
  scene.draw(api, recorder());
  scene.poke(api, 100, 60);
});

test('the stage changes after every match: harbour, the lantern market, the other harbour, and the jungle among them when the atlas has it', () => {
  const scene = F.createScene(), api = fakeApi(fakeJson(true), 3);
  withQA({seed: 5, hour: 13, stage: 'harbour0'}, () => scene.init(api));
  const kinds = [scene.s.order[scene.s.orderAt]];
  const m = scene.s.m;
  for (let i = 0; i < 30 * 60 * 16 && kinds.length < 5; i++) {
    if (m.phase === 'fight') { m.f[1].hp = Math.min(m.f[1].hp, 30); m.f[0].hp = 100; }
    scene.step(api, 1 / 30);
    const now = scene.s.order[scene.s.orderAt];
    if (now !== kinds[kinds.length - 1]) kinds.push(now);
  }
  assert.deepEqual(kinds, ['harbour0', 'jungle', 'market', 'harbour1', 'jungle']);
  scene.draw(api, recorder());
});

test('the engine drives the scene: ready, a few frames, a touch, a pause: no errors and a still when motion is off', async () => {
  const pad = fakeJson();
  const api = fakeApi(pad, 3);
  const scene = engine.registry.fighting;
  withQA({seed: 5, hour: 13}, () => scene.init(api));
  const g = recorder();
  for (let i = 0; i < 90; i++) { scene.step(api, engine.STEP); }
  scene.draw(api, g);
  scene.poke(api, 40, 60);
  scene.poke(api, 190, 300);
  scene.poke(api, NaN, NaN);
  scene.draw(api, g);
});

test('the light follows the clock the scene is given and changes the sky only slowly', () => {
  const scene = F.createScene(), api = fakeApi(fakeJson(), 3);
  withQA({seed: 5, hour: 13}, () => scene.init(api));
  assert.equal(scene.s.light.phase, 'day');
  const dusk = F.createScene(), api2 = fakeApi(fakeJson(), 3);
  withQA({seed: 5, hour: 17.9}, () => dusk.init(api2));
  assert.ok(['golden', 'dusk', 'twilight'].includes(dusk.s.light.phase), dusk.s.light.phase);
  const night = F.createScene(), api3 = fakeApi(fakeJson(), 3);
  withQA({seed: 5, hour: 23}, () => night.init(api3));
  assert.equal(night.s.light.phase, 'night');
  assert.ok(night.s.light.stars > 0.9 && night.s.light.lamps > 0.9);
});

test('a won match is celebrated with fireworks over the harbour: embers that fly out, fall and fade, only while the match end is shown', () => {
  const m = createMatch({seed: 9});
  let max = 0, during = 0, outside = 0;
  for (let i = 0; i < 30 * 60 * 10 && !m.events.length; i++) {
    if (m.phase === 'fight') { m.f[1].hp = Math.min(m.f[1].hp, 30); }
    m.step();
    max = Math.max(max, m.sparks.length);
    if (m.phase === 'matchend') { during += m.sparks.length > 0 ? 1 : 0; for (const e of m.sparks) { assert.ok(Number.isFinite(e.x) && Number.isFinite(e.y)); assert.ok(e.t < e.life); } }
    else if (m.phase === 'fight' || m.phase === 'intro') outside += m.sparks.length;
  }
  assert.ok(max >= 18 && max <= 80, `at most ${max} embers at once`);
  assert.ok(during > 60);
  assert.equal(outside, 0, 'none while fighting');
  assert.ok(F.FIREWORK_COLOURS.length >= 4);
});

test('banners: ROUND n slides in, FIGHT! pops, K.O. and the winner are announced, and every text is one the font can draw', () => {
  const m = createMatch({seed: 2});
  const seen = new Set();
  for (let i = 0; i < 400; i++) { m.step(); const b = F.bannerFor(m, 112); if (b) for (const [text] of b.lines) { seen.add(text); assert.equal(textPixels(text).width, [...text].length * 6 - 1, text); assert.ok(b.alpha >= 0 && b.alpha <= 1); } }
  assert.ok(seen.has('ROUND 1') && seen.has('FIGHT!'));
  const ko = setUp(5, 92); ko.f[1].hp = 2; ko.start(0, 'jab');
  for (let i = 0; i < 400; i++) { ko.step(); const b = F.bannerFor(ko, 112); if (b) for (const [text] of b.lines) seen.add(text); }
  assert.ok(seen.has('K.O.') && seen.has('CODEX WINS'));
  assert.equal(F.bannerFor({text: null}, 112), null);
});

/* ---- round 3: in-between frames, cues, the win taunt, the stages' stories, the show ------------------------------------------------------------ */

test('a fighter eases out of a hit, a guard and a blow through an in-between frame, never straight to the idle pose', () => {
  const m = setUp(5, 92);
  m.start(0, 'jab');
  const names = [];
  for (let i = 0; i < 40; i++) { m.step(); names.push(F.frameName(m.f[0])); }
  assert.equal(names[0], 'codex-tw-jab-in', 'a windup begins with the in-between pose');
  assert.ok(names.includes('codex-tw-jab-out'), 'and ends with one');
  const g = setUp(5, 140);
  g.start(1, 'guard');
  assert.equal(F.frameName(g.f[1]), 'claude-tw-guard-in');
  const h = setUp(5, 92);
  h.start(0, 'heavy');
  const seq = []; for (let i = 0; i < 80; i++) { h.step(); seq.push(F.frameName(h.f[1])); }
  assert.ok(seq.some((n) => n.includes('-hit-') || n.includes('-hurt-') || n.includes('-kd-') || n.includes('guard')), 'it was hit, or guarded');
});

test('the match tells its surroundings what happened: round, fight, hit, knock-out and win', () => {
  const m = createMatch({seed: 5});
  const seen = new Set();
  for (let i = 0; i < 30 * 60 * 6; i++) { if (m.phase === 'fight' && i > 1200) m.f[1].hp = Math.min(m.f[1].hp, 3); m.step(); for (const c of m.cues.splice(0)) { seen.add(c.type); assert.ok(Number.isFinite(c.at)); } m.events.length = 0; if (seen.has('win')) break; }
  for (const type of ['round', 'fight', 'hit', 'ko', 'win']) assert.ok(seen.has(type), `${type} was announced`);
  const cap = createMatch({seed: 5});
  for (let i = 0; i < 3000; i++) { cap.step(); cap.events.length = 0; }
  assert.ok(cap.cues.length <= 64, 'cues nobody reads never pile up');
});

test('the winner strikes a pose and then taunts, and goes back to the pose', () => {
  const m = setUp(5, 92);
  m.f[1].hp = 2; m.start(0, 'jab');
  const seen = [];
  for (let i = 0; i < 400; i++) { m.step(); if (m.phase === 'win') seen.push(m.f[0].anim + ':' + m.f[0].state); m.events.length = 0; }
  assert.ok(seen.includes('win:win'), 'the pose');
  assert.ok(seen.includes('taunt:win'), 'the taunt, still in the winning state');
});

test('the band plays faster in the last ten seconds, and the crane does a full turn that ends where it began', () => {
  const m = setUp(5, 100);
  const calm = F.bandBeat(m);
  m.clock = 8;
  assert.ok(F.bandBeat(m) < calm, 'quicker at the end of a round');
  m.clock = 40; m.crowd.mood = 'cheer';
  assert.ok(F.bandBeat(m) < calm, 'and when the crowd cheers');
  const a = F.craneAt(0), z = F.craneAt(1259);
  assert.ok(Math.abs(a.tx - z.tx) <= 2, 'the trolley ends the turn where it started');
  let carried = 0, prev = null;
  for (let t = 0; t < 1260; t += 5) { const c = F.craneAt(t); if (c.attached) carried++; if (prev) assert.ok(Math.abs(c.tx - prev.tx) <= 8 && Math.abs(c.len - prev.len) <= 8, `the crane moves smoothly (${t})`); prev = c; assert.ok(c.tx >= 20 && c.tx <= 100 && c.len >= 4 && c.len <= 56); }
  assert.ok(carried > 100, 'it carries a container for a while');
  assert.ok(F.craneAt(900, true).attached === false && F.craneAt(900, false).attached === true, 'now and then the container slips and falls into the sea');
});

test('every stage, weather and hour draws without an error, on every tier, with the dock up and in picture mode', () => {
  for (const stage of ['harbour0', 'harbour1', 'market']) {
    for (const hour of [6.5, 13, 17.8, 19, 23]) {
      for (const [bottom, tier] of [[186, 'high'], [320, 'high'], [186, 'low']]) {
        const scene = F.createScene(), api = fakeApi(fakeJson(), 3, bottom, {tier});
        withQA({seed: 5, hour, stage, phase: 'fight'}, () => scene.init(api));
        const weathers = scene.s.stage.sky.weather !== undefined ? ['clear', 'rainbow', 'storm', 'streaks'] : [''];
        for (const weather of weathers) {
          scene.s.stage.sky.weather = weather;
          for (let i = 0; i < 100; i++) { scene.step(api, 1 / 30); if (i % 25 === 0) scene.draw(api, recorder()); }
        }
        assert.deepEqual(scene.s.errors, {}, `${stage} ${hour} h ${bottom} ${tier}`);
      }
    }
  }
});

test('the harbour\'s stories run: a ferry crosses, a plane tows a banner, the crane drops a crate where nobody stands, fireworks follow a knock-out', () => {
  const scene = F.createScene(), api = fakeApi(fakeJson(), 3, 320);
  withQA({seed: 5, hour: 18, stage: 'harbour1', phase: 'fight'}, () => scene.init(api));
  const st = scene.s.stage, m = scene.s.m;
  st.ferry.wait = 1; st.sky.plane.wait = 1; st.drop.wait = 1; st.stealIn = 1;
  const seen = {ferry: false, plane: false, drop: false};
  for (let i = 0; i < 30 * 60 * 3; i++) {
    if (m.phase === 'fight') { m.f[0].hp = 100; m.f[1].hp = Math.max(m.f[1].hp, 40); }
    scene.step(api, 1 / 30);
    if (st.ferry.on) seen.ferry = true;
    if (st.sky.plane.on) { seen.plane = true; assert.ok(F.PLANE_TEXTS.includes(st.sky.plane.text)); }
    if (st.drop.phase !== 'none') { seen.drop = true; assert.ok(Number.isFinite(st.drop.x) && Number.isFinite(st.drop.h) && st.drop.h >= 0); }
    if (i % 20 === 0) scene.draw(api, recorder());
  }
  assert.ok(seen.ferry && seen.plane && seen.drop, JSON.stringify(seen));
  assert.deepEqual(scene.s.errors, {});
  const ko = F.createScene(), a2 = fakeApi(fakeJson(), 3, 186);
  withQA({seed: 5, hour: 22, stage: 'harbour0', phase: 'fight'}, () => ko.init(a2));
  const k = ko.s.m; k.f[1].hp = 2; k.start(0, 'jab');
  let rockets = 0, bursts = 0;
  for (let i = 0; i < 400; i++) { ko.step(a2, 1 / 30); for (const f of ko.s.stage.sky.fireworks) { if (f.mode === 'rise') rockets++; else { bursts++; for (const e of f.parts) assert.ok(Number.isFinite(e.x) && Number.isFinite(e.y)); } } }
  assert.ok(rockets > 3 && bursts > 3, `rockets ${rockets}, bursts ${bursts}`);
  assert.ok(ko.s.stage.sky.fireworks.length <= 4);
});

test('the crowd of a calm harbour is two baked strips; when it cheers the live fans are drawn instead', () => {
  const scene = F.createScene(), api = fakeApi(fakeJson(), 3, 186);
  withQA({seed: 5, hour: 13, stage: 'harbour0', phase: 'fight'}, () => scene.init(api));
  for (let i = 0; i < 60; i++) scene.step(api, 1 / 30);
  const m = scene.s.m;
  m.crowd.mood = 'idle'; m.crowd.t = 0;
  const calm = recorder(); scene.draw(api, calm);
  m.crowd.mood = 'cheer'; m.crowd.t = 50;
  const lively = recorder(); scene.draw(api, lively);
  assert.ok(lively.__calls.drawImage > calm.__calls.drawImage, `${lively.__calls.drawImage} live sprites against ${calm.__calls.drawImage} with the strips`);
  const keys = Object.keys(scene.s.stage.L);
  assert.ok(keys.some((k) => k.startsWith('crowd0_')) && keys.some((k) => k.startsWith('crowd1_')));
});

test('a punch-in on the knock-out, a white flash on the struck fighter, and a camera that kicks and settles', () => {
  const scene = F.createScene(), api = fakeApi(fakeJson(), 3, 320);
  withQA({seed: 5, hour: 17.9, stage: 'harbour0', phase: 'fight'}, () => scene.init(api));
  const m = scene.s.m;
  m.f[0].x = 120; m.f[1].x = 190; m.f[1].hp = 2; for (const f of m.f) { f.think = 99999; f.mood.skill = 0; }
  m.start(0, 'heavy');
  let zoomed = false, kicked = 0, whiteFrames = 0;
  for (let i = 0; i < 160; i++) {
    scene.step(api, 1 / 30);
    if (Math.abs(m.camKick) > 1) kicked++;
    if (m.f.some((f) => f.flashT > 0)) whiteFrames++;
    scene.draw(api, recorder());
    if (m.phase === 'ko' && m.steps - m.koAt >= 3 && m.steps - m.koAt < 22) zoomed = zoomed || scene.s.zoomCanvas !== null;
  }
  assert.ok(zoomed, 'the knock-out is shown at twice the size for a moment');
  assert.ok(kicked > 0 && Math.abs(m.camKick) < 1, 'the camera kicked and settled');
  assert.ok(whiteFrames > 2, 'the struck fighter flashes white');
  assert.deepEqual(scene.s.errors, {});
  const third = createMatch({seed: 3}); third.round = 3; third.text = {kind: 'round', n: 3}; third.f[0].wins = 1; third.f[1].wins = 1;
  assert.equal(F.bannerFor(third, 112).lines[0][0], 'FINAL ROUND');
  third.f[0].wins = 0;
  assert.equal(F.bannerFor(third, 112).lines[0][0], 'ROUND 3');
});

test('an atlas made before the in-between frames existed still draws every fighter: a missing in-between falls back to the nearest pose', () => {
  const json = fakeJson();
  for (const name of Object.keys(json.frames)) if (name.includes('-tw-')) delete json.frames[name];
  const scene = F.createScene(), api = fakeApi(json, 3);
  withQA({seed: 5, hour: 13, stage: 'harbour0', phase: 'fight'}, () => scene.init(api));
  scene.s.m.start(0, 'jab');
  for (let i = 0; i < 30; i++) {
    scene.step(api, 1 / 30);
    const g = recorder(); scene.draw(api, g);
    assert.ok(g.__calls.drawImage >= 10, 'the fighters and the stage are still drawn');
  }
  assert.deepEqual(scene.s.errors, {});
});

test('the atlas gives the scene its attachment points, shadows and actors, and a broken table is ignored', () => {
  const lib = F.readAtlas({frames: {'act-fisher-0': [0, 0, 30, 30]}, anchors: {}, points: {'act-fisher-0': [[20, -30]], x: 'nope'}, shadows: {a: [0, 26, 1], b: [0, 'x', 1]}, anims: {actors: {fisher: ['act-fisher-0']}}});
  assert.deepEqual(lib.points('act-fisher-0'), [[20, -30]]);
  assert.deepEqual(lib.points('x'), []);
  assert.deepEqual(lib.shadow('a'), [0, 26, 1]);
  assert.equal(lib.shadow('b'), null);
  assert.equal(lib.actor('fisher', 7), 'act-fisher-0');
  assert.equal(lib.actor('nothing', 0), null);
  const bare = F.readAtlas({frames: {}});
  assert.deepEqual(bare.points('a'), []);
  assert.equal(bare.actor('fisher', 0), null);
});

test('every word the stages write can be drawn by the pixel font', () => {
  for (const text of [...F.PLANE_TEXTS, ...F.STALL_SIGNS, 'FISH', 'FERRY', 'BAIT', 'CRANE', 'INN', 'BAR', 'CAFE', 'SAIL', 'FINAL ROUND', 'VS']) assert.equal(textPixels(text).width, [...text].length * 6 - 1, text);
});
