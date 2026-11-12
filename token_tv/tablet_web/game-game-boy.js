/* GAME BOY for the tablet: the whole portrait screen is a handheld console, and on its LCD a platformer plays itself. 200 x 320 art pixels (x4 on the panel), 30 Hz.
 *
 * What you see: a grey casing with its dark bezel, power lamp, speaker grille, cross, A and B buttons, Start and Select, all drawn once in code (crisp, with plastic shading
 * and a little wear); in the bezel a 160 x 144 LCD at exactly one art pixel per LCD pixel, in four greens, with a faint ghost of the previous frame. On the LCD a small plumber
 * runs through a generated level (ground, bricks, ? blocks that bump, pipes, clouds, pyramids, palms, coins, walkers, shells, a flagpole), then through the next one. The
 * console's buttons press in time with the play. A touch on a button makes him jump or run faster for a moment; a touch on the LCD makes him jump.
 *
 * Quota INSIDE the picture (Tony's rule: only the isometric city, this console and Neon City's bridge show it): the top rows of the LCD are the game's own HUD, rewritten
 * with the board's Game Boy page: each provider's WEEK left as a number and a ten-part gauge, its saved resets as three hearts (unknown or old: one dot after them), the reset
 * as a short countdown, Claude's five hours as two five-part lines (quota above, time below; nothing at all while unknown), and the REAL TIME where the game keeps its clock.
 * Unknown is never zero: it is `--`, hearts without a count and a dotted, empty gauge.
 *
 * Files: the engine is stage-game.js (window.TabletGames, with `post: 'handheld'`). An optional compatible sprite atlas can be supplied locally; this file contains no game artwork. The console is drawn in code. Without an atlas the scene still draws the
 * console and a calm, plain LCD with the HUD in a tiny font of its own.
 *
 * The file is also a Node module: the readings-to-HUD mapping, the clock, the level, the physics and the auto-player are pure and have tests
 * (tests/test_tablet_game_game_boy.mjs).
 */
(function (global) {
  'use strict';

  /* ---- sizes and helpers */
  const W = 200, H = 320;
  const LCD = { x: 20, y: 30, w: 160, h: 144 };
  const TILE = 8, ROWS = 18, GROUND = 16, HUD_ROWS = 4;
  const GROUND_Y = GROUND * TILE;                   // the row where the feet stand (128)
  const STEP = 1 / 30;
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const pad2 = (n) => (n < 10 ? '0' : '') + n;
  function seeded(seed) {                           // the engine's own mulberry32, so the pure logic needs no engine
    let a = (seed >>> 0) || 1;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* ---- the colours: the four shades of the LCD, lightest first (a DMG's yellow-greens, a little richer than the classic four so the two lightest stay apart), and the casing */
  const SHADES = [[190, 208, 90], [140, 172, 52], [56, 104, 56], [16, 54, 26]];
  const rgb = (c) => 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')';
  const SHADE_CSS = SHADES.map(rgb);

  /* ==================================================================================================== the HUD: readings to what the LCD shows */

  const STALE_MS = 45000;                            // the page asks every 5 s; a reading not renewed for this long is not shown (unknown, never old numbers)
  const isPercent = (v) => finite(v) && v >= 0 && v <= 100;
  const future = (epoch, nowMs) => finite(epoch) && epoch * 1000 > nowMs;

  /** The number for a quota left: `87%`. Rounded DOWN like the number on the dock, but a positive fraction shows 1 (a real zero is the only 0). Anything that is not a percentage is null. */
  function percentText(v) {
    if (!isPercent(v)) return null;
    if (v > 0 && v < 1) return '1%';
    return Math.floor(v + 1e-9) + '%';
  }
  /** A reset as at most four characters: days with a tenth (`6.5D`), whole hours from ten (`12H`), hours with a tenth (`5.3H`), minutes (`45M`). Floored, so it never promises more time
   *  than there is. Null for a reset that is missing or already past. */
  function resetText(epoch, nowMs) {
    if (!future(epoch, nowMs)) return null;
    const hours = (epoch * 1000 - nowMs) / 3600000;
    if (hours >= 240) return Math.floor(hours / 24) + 'D';
    if (hours >= 24) return (Math.floor(hours * 10 / 24 + 1e-9) / 10).toFixed(1) + 'D';
    if (hours >= 10) return Math.floor(hours) + 'H';
    if (hours >= 1) return (Math.floor(hours * 10 + 1e-9) / 10).toFixed(1) + 'H';
    return Math.max(1, Math.floor(hours * 60)) + 'M';
  }
  /** The saved resets as hearts, like the board's `hearts(..., quiet=True)`: a heart for each of the first three, a `+` beyond three, and ONE dot when the count is unknown or old.
   *  A real zero is three empty hearts and no dot. */
  function heartsModel(resets, known) {
    const count = resets && Number.isInteger(resets.count) && resets.count >= 0 && resets.count <= 999 ? resets.count : null;
    return { full: count === null ? 0 : Math.min(3, count), plus: count !== null && count > 3, dot: count === null || !known || !!(resets && resets.old) };
  }
  const creditBalance = (row, remaining) => remaining === 0 && typeof row.credits === 'string'
    && (row.credits === '<0.01' || (/^\d{1,10}(?:\.\d{1,2})?$/.test(row.credits) && Number(row.credits) > 0)) ? row.credits : null;
  const emptyProvider = () => ({ known: false, text: '--', fill: null, hearts: { full: 0, plus: false, dot: true }, reset: '--' });
  /** What the HUD shows for the page's latest readings. `ageMs` is how long ago the page last renewed them (older than 45 s: unknown). A week is known only with a percentage left and a
   *  reset still ahead; Claude's five hours only with both too (nothing at all otherwise). */
  function hudModel(readings, nowMs, ageMs) {
    const out = { codex: emptyProvider(), claude: emptyProvider(), session: null, key: '' };
    const live = readings && typeof readings === 'object' && !(ageMs > STALE_MS) && readings.providers && typeof readings.providers === 'object';
    if (live) {
      for (const name of ['codex', 'claude']) {
        const row = readings.providers[name];
        if (!row || typeof row !== 'object') continue;
        const week = row.weekly;
        const known = !!week && typeof week === 'object' && isPercent(week.remaining) && future(week.resets_at, nowMs);
        const credit = known ? creditBalance(row, week.remaining) : null;
        out[name] = {
          known, text: credit !== null ? 'CR ' + credit : known ? percentText(week.remaining) : '--', fill: known ? clamp(week.remaining, 0, 100) / 100 : null,
          hearts: heartsModel(row.resets, true), reset: known ? resetText(week.resets_at, nowMs) || '--' : '--',
        };
      }
      const session = readings.providers.claude && readings.providers.claude.session;
      if (session && typeof session === 'object' && isPercent(session.remaining) && future(session.resets_at, nowMs)) {
        const hours = clamp((session.resets_at * 1000 - nowMs) / 3600000, 0, 5);
        out.session = { text: percentText(session.remaining), quota: Math.max(0, Math.ceil(session.remaining / 5 - 1e-9)) / 4, time: Math.round(hours * 4) / 4 };
      }
    }
    out.key = ['codex', 'claude'].map((n) => { const p = out[n]; return [p.text, p.reset, p.hearts.full, p.hearts.plus ? 1 : 0, p.hearts.dot ? 1 : 0, p.fill === null ? '-' : Math.round(p.fill * 1000)].join(','); }).join('|')
      + '|' + (out.session ? [out.session.text, out.session.quota, out.session.time].join(',') : '-');
    return out;
  }
  /** The real time as the HUD writes it: `HH:MM`, 24 hours, the colon dark on odd seconds (a digital clock's blink) when `blink`. */
  function clockText(date, blink) {
    const colon = !blink || date.getSeconds() % 2 === 0;
    return pad2(date.getHours()) + (colon ? ':' : ' ') + pad2(date.getMinutes());
  }
  /** The fill of segment k (0-based) of a gauge of `n` equal segments for a fraction 0-1: 0 to 1 (a partial segment is partly filled). */
  const segmentFill = (fraction, n, k) => clamp(fraction * n - k, 0, 1);
  /** World and stage names of the level cards (WORLD 1-1, 1-2, 1-3, 1-4, 2-1, ...). */
  const worldLabel = (n) => 'WORLD ' + (1 + Math.floor(n / 4)) + '-' + (1 + (n % 4));

  /* ==================================================================================================== the level */

  const T = { AIR: 0, GROUND_TOP: 1, GROUND: 2, BRICK: 3, Q: 4, USED: 5, HARD: 6, PIPE: 7 };
  const SOLID = [0, 1, 1, 1, 1, 1, 1, 1];
  const FEATURES = [['pipe', 3], ['wall', 1], ['stairs', 1], ['pit', 2], ['blocks', 3], ['coinrow', 1], ['coinarc', 1], ['blobs', 3], ['tall', 2]];

  /** A level is a map of 8 x 8 cells (18 rows: the HUD, the sky, two rows of ground), the coins, the walkers, the scenery behind it and a goal. Everything comes from `rand`. */
  function buildLevel(rand, options) {
    const o = Object.assign({ cols: 288, number: 0 }, options);
    const cols = o.cols, tiles = new Uint8Array(cols * ROWS), coins = new Uint8Array(cols * ROWS);
    const level = { cols, width: cols * TILE, tiles, coins, enemies: [], features: [], pits: [], decor: { clouds: [], pyramids: [], palms: [] }, goal: null, number: o.number, start: { x: 36, y: GROUND_Y } };
    const put = (c, r, t) => { if (c >= 0 && c < cols && r >= 0 && r < ROWS) tiles[r * cols + c] = t; };
    const coin = (c, r) => { if (c >= 0 && c < cols && r >= 0 && r < ROWS && !tiles[r * cols + c]) coins[r * cols + c] = 1; };
    const between = (a, b) => a + Math.floor(rand() * (b - a + 1));
    for (let c = 0; c < cols; c++) { put(c, GROUND, T.GROUND_TOP); put(c, GROUND + 1, T.GROUND); }
    const total = FEATURES.reduce((s, f) => s + f[1], 0);
    const pick = () => { let r = rand() * total; for (const [name, w] of FEATURES) { r -= w; if (r < 0) return name; } return 'pipe'; };
    const goalCol = cols - 28, last = goalCol - 12;
    const walker = (kind) => kind === 'blobs' || kind === 'tall';
    let c = 22, previous = '', kind = pick();
    while (c < last) {
      if (kind === previous && (kind === 'pit' || kind === 'pipe')) kind = 'blocks';
      previous = kind;
      let width = 0;
      if (kind === 'pipe') {
        const h = rand() < 0.65 ? 2 : 3;
        for (let r = GROUND - h; r < GROUND; r++) { put(c, r, T.PIPE); put(c + 1, r, T.PIPE); }
        level.features.push({ kind, col: c, h });
        width = 2;
      } else if (kind === 'wall') {
        for (let r = GROUND - 2; r < GROUND; r++) { put(c, r, T.BRICK); put(c + 1, r, T.BRICK); }
        level.features.push({ kind, col: c, h: 2 });
        width = 2;
      } else if (kind === 'stairs') {
        const k = between(1, 2);
        for (let i = 0; i < k; i++) for (let r = GROUND - 1 - i; r < GROUND; r++) { put(c + i, r, T.HARD); put(c + 2 * k + 1 - i, r, T.HARD); }
        for (let i = 0; i < 2; i++) for (let r = GROUND - k; r < GROUND; r++) put(c + k + i, r, T.HARD);
        level.features.push({ kind, col: c, h: k });
        width = 2 * k + 2;
      } else if (kind === 'pit') {
        width = between(2, 3);
        for (let i = 0; i < width; i++) { put(c + i, GROUND, T.AIR); put(c + i, GROUND + 1, T.AIR); }
        level.pits.push({ col: c, width });
        level.features.push({ kind, col: c, w: width });
      } else if (kind === 'blocks') {
        width = between(3, 5);
        let hasQ = false;
        for (let i = 0; i < width; i++) { const q = rand() < 0.45 || (i === width - 1 && !hasQ); hasQ = hasQ || q; put(c + i, 12, q ? T.Q : T.BRICK); }
        if (rand() < 0.5) for (let i = 1; i < width - 1; i++) coin(c + i, 10);
        level.features.push({ kind, col: c, w: width });
      } else if (kind === 'coinrow') {
        width = between(4, 6);
        for (let i = 0; i < width; i++) coin(c + i, 14);
        level.features.push({ kind, col: c, w: width });
      } else if (kind === 'coinarc') {
        width = 5;
        [12, 11, 10, 11, 12].forEach((r, i) => coin(c + i, r));
        level.features.push({ kind, col: c, w: width });
      } else if (kind === 'blobs') {
        const n = between(1, 2);
        for (let i = 0; i < n; i++) level.enemies.push({ kind: 'round', x: (c + 4 * i) * TILE + 4, y: GROUND_Y, dir: -1, home: (c + 4 * i) * TILE + 4 });
        width = 4 * n - 1;
        level.features.push({ kind, col: c, w: width });
      } else {
        level.enemies.push({ kind: 'tall', x: c * TILE + 4, y: GROUND_Y, dir: -1, home: c * TILE + 4 });
        width = 2;
        level.features.push({ kind, col: c, w: width });
      }
      const next = pick();
      c += width + (walker(kind) || walker(next) ? between(11, 14) : between(7, 11));       // walkers keep their distance from everything else: their beat is short
      kind = next;
    }
    level.goal = { col: goalCol, x: goalCol * TILE + 4, top: GROUND_Y - 56 };
    // scenery behind everything: clouds high up, pyramids with palms in front of their feet
    for (let x = between(0, 40); x < level.width; x += between(52, 100)) level.decor.clouds.push({ x, y: between(36, 62), kind: ['cloud-s', 'cloud-m', 'cloud-l'][between(0, 2)] });
    for (let k = between(2, 8); k < cols - 10; k += between(14, 28)) level.decor.pyramids.push({ col: k, h: between(3, 6) });
    for (let k = between(4, 12); k < cols - 4; k += between(9, 22)) level.decor.palms.push({ col: k, h: between(2, 4) });
    return level;
  }
  const solidAt = (level, c, r) => {
    if (c < 0 || c >= level.cols) return true;
    if (r < 0) return false;
    if (r >= ROWS) return false;
    return SOLID[level.tiles[r * level.cols + c]] === 1;
  };
  const solidColumn = (level, c, y0, y1) => { for (let r = Math.floor(y0 / TILE); r <= Math.floor((y1 - 1e-6) / TILE); r++) if (solidAt(level, c, r)) return true; return false; };
  const solidRow = (level, r, x0, x1) => { for (let c = Math.floor(x0 / TILE); c <= Math.floor((x1 - 1e-6) / TILE); c++) if (solidAt(level, c, r)) return true; return false; };

  /* ==================================================================================================== the physics, the walkers and the auto-player */

  const PHY = { speed: 2, boost: 3, gravity: 0.42, high: -5.6, low: -4.4, maxFall: 6.5, halfW: 5, height: 14, bounce: -3.6, walker: 0.5, beat: 34 };
  const INTRO = 50, FADE = 22;

  /** One step of the player's body against the level's cells. `ctl` = {speed, jump: 0 | 'high' | 'low'}; `ev` is filled with what happened. Whole cells only, 8 x 8. */
  function stepPlayer(level, p, ctl, ev) {
    ev.bump = null; ev.landed = false; ev.blocked = false; ev.jumped = false;
    p.vx = ctl.speed;
    if (ctl.jump && p.onGround) { p.vy = ctl.jump === 'low' ? PHY.low : PHY.high; p.onGround = false; ev.jumped = true; }
    p.vy = Math.min(PHY.maxFall, p.vy + PHY.gravity);
    let nx = p.x + p.vx;
    if (p.vx > 0) {
      const col = Math.floor((nx + PHY.halfW - 1e-6) / TILE);
      if (solidColumn(level, col, p.y - PHY.height, p.y)) { nx = col * TILE - PHY.halfW; ev.blocked = true; }
    }
    p.x = nx;
    let ny = p.y + p.vy, landed = false;
    if (p.vy >= 0) {
      const r = Math.floor(ny / TILE);
      if (r * TILE >= p.y - 1e-6 && solidRow(level, r, p.x - PHY.halfW, p.x + PHY.halfW)) { ny = r * TILE; p.vy = 0; landed = true; }
    } else {
      const r = Math.floor((ny - PHY.height) / TILE);
      if (r >= 0 && solidRow(level, r, p.x - PHY.halfW, p.x + PHY.halfW)) {
        ny = (r + 1) * TILE + PHY.height; p.vy = 0;
        const cx = Math.floor(p.x / TILE);
        ev.bump = solidAt(level, cx, r) ? [cx, r] : [solidAt(level, cx - 1, r) ? cx - 1 : cx + 1, r];
      }
    }
    p.y = ny;
    ev.landed = landed && !p.onGround;
    p.onGround = landed;
  }
  const walkerBox = (e) => ({ hw: 3.5, h: e.kind === 'tall' ? 14 : 7 });
  /** A walker's step: straight ahead, turning at a wall or at the edge of a pit; a stomped one counts down and goes. */
  function stepEnemy(level, e) {
    if (!e.alive) return;
    if (e.state !== 'walk') { if (--e.t <= 0) e.alive = false; return; }
    const nx = e.x + e.dir * PHY.walker, edge = nx + e.dir * 4, c = Math.floor(edge / TILE);
    const wall = solidAt(level, c, Math.floor((e.y - 3) / TILE)) || (e.kind === 'tall' && solidAt(level, c, Math.floor((e.y - 12) / TILE)));
    if (wall || !solidAt(level, c, GROUND) || edge < 4 || (e.home !== undefined && Math.abs(nx - e.home) > PHY.beat)) e.dir = -e.dir; else e.x = nx;
    e.anim = (e.anim || 0) + 1;
  }
  /** Does the player touch a walker, and how: 'stomp' (falling onto its top) or 'hurt' (anything else). */
  function touch(p, e) {
    if (!e.alive || e.state !== 'walk') return null;
    const b = walkerBox(e);
    if (Math.abs(p.x - e.x) >= PHY.halfW + b.hw) return null;
    const top = e.y - b.h;
    if (p.y <= top + 0.001 || p.y - PHY.height >= e.y) return null;
    return p.vy > 0 && p.y - p.vy <= top + 3 ? 'stomp' : 'hurt';
  }
  const makeWalker = (d) => ({ kind: d.kind, x: d.x, y: d.y, dir: d.dir, home: d.home, alive: true, state: 'walk', t: 0, anim: 0 });
  const newPlayer = (x, y) => ({ x, y, vx: 0, vy: 0, onGround: true, dead: false, anim: 0, face: 1, hold: 0 });

  /** Look ahead without touching the real world: the player's body and the walkers near it, `horizon` steps, running or starting a jump now. `out.ok` is false for a wall, a pit or a
   *  walker's side; `out.landed` says the body was back on the ground afterwards (and `tail` steps clean beyond), `out.bump` the first ? block it would hit, `out.coins` the coins it
   *  would pick up and `out.stomp` the walkers it would land on. */
  function look(game, mode, horizon, tail) {
    const level = game.level, p0 = game.p;
    const p = { x: p0.x, y: p0.y, vx: 0, vy: p0.vy, onGround: p0.onGround };
    const walkers = [];
    for (const e of game.enemies) if (e.alive && e.state === 'walk' && Math.abs(e.x - p0.x) < 170) walkers.push({ kind: e.kind, x: e.x, y: e.y, dir: e.dir, home: e.home, alive: true, state: 'walk', t: 0 });
    const out = { ok: true, landed: false, bump: null, coins: 0, stomp: 0, steps: 0 };
    const ev = {}, seen = [];
    let boost = game.boost, airborne = !p0.onGround, after = 0;
    for (let k = 0; k < horizon; k++) {
      const spd = boost > 0 ? PHY.boost : PHY.speed;
      if (boost > 0) boost--;
      stepPlayer(level, p, { speed: spd, jump: k === 0 && mode !== 'run' ? mode : 0 }, ev);
      out.steps = k + 1;
      if (ev.blocked || p.y > GROUND_Y + 22) { out.ok = false; break; }
      if (ev.bump && !out.bump && level.tiles[ev.bump[1] * level.cols + ev.bump[0]] === T.Q) out.bump = ev.bump;
      for (let r = Math.floor((p.y - PHY.height) / TILE); r <= Math.floor((p.y - 1e-6) / TILE); r++) {
        for (let c = Math.floor((p.x - PHY.halfW) / TILE); c <= Math.floor((p.x + PHY.halfW - 1e-6) / TILE); c++) {
          const i = r * level.cols + c;
          if (r >= 0 && r < ROWS && c >= 0 && c < level.cols && level.coins[i] && seen.indexOf(i) < 0) { seen.push(i); out.coins++; }
        }
      }
      for (const e of walkers) {
        stepEnemy(level, e);
        const t = touch(p, e);
        if (t === 'stomp') { e.alive = false; p.vy = PHY.bounce; p.onGround = false; out.stomp++; } else if (t === 'hurt') { out.ok = false; break; }
      }
      if (!out.ok) break;
      if (!p.onGround) airborne = true; else if (airborne) { out.landed = true; airborne = false; }
      if (out.landed && ++after >= tail) break;
    }
    return out;
  }
  const runSafe = (game, n) => look(game, 'run', n, 99).ok;
  const jumpSafe = (game, variant, tail) => { const o = look(game, variant, 90, tail === undefined ? 5 : tail); return o.ok && o.landed ? o : null; };

  /** The auto-player: what to do this step. 'high', 'low' (a jump) or 0 (keep running). It runs the level in its head: when running on would meet a wall, a pit or a walker within a
   *  second it jumps as soon as a jump is safe; now and then it jumps for a ? block or a coin it can reach; it jumps for the flagpole. Never touches the real world. */
  function plan(game) {
    const p = game.p;
    if (!p.onGround || game.phase !== 'play') return 0;
    if (game.pendingJump > 0) { for (const v of ['high', 'low']) if (jumpSafe(game, v)) return v; return 0; }
    if (!runSafe(game, 28)) {
      for (const v of ['high', 'low']) if (jumpSafe(game, v)) return v;
      return runSafe(game, 6) ? 0 : 'high';
    }
    const goal = game.level.goal;
    if (goal && goal.x - p.x < 30 && goal.x - p.x > 14 && jumpSafe(game, 'high', 0)) return 'high';
    if (game.steps % 3 === 0) {
      const col = Math.floor(p.x / TILE), level = game.level;
      let wantQ = false, wantCoin = false;
      for (let c = col + 1; c <= col + 5; c++) {
        if (level.tiles[12 * level.cols + c] === T.Q) wantQ = true;
        for (let r = 9; r <= 13; r++) if (level.coins[r * level.cols + c]) wantCoin = true;
      }
      if (wantQ || wantCoin) {
        const o = jumpSafe(game, 'high');
        if (o && ((wantQ && o.bump && game.rand() < 0.8) || (wantCoin && o.coins >= 2 && game.rand() < 0.55))) return 'high';
      }
    }
    return 0;
  }

  /** The whole game: a level after a level, the player, the walkers, the events the picture needs. `step()` is one 30 Hz tick. */
  function createGame(options) {
    const o = Object.assign({ rand: seeded(1), cols: 288, number: 0, intro: true }, options);
    const game = { rand: o.rand, cols: o.cols, number: o.number, steps: 0, phase: 'intro', t: 0, events: [], ev: {}, level: null, enemies: [], p: null, cam: 0, boost: 0, boostNext: 0, pendingJump: 0,
      invul: 0, bumps: [], pops: [], flag: 0, stall: 0, lastX: 0, stats: { deaths: 0, rescues: 0, jumps: 0, stomps: 0, bumped: 0, coins: 0, levels: 0 }, fade: 0, buttons: { a: 0, b: 0 } };

    game.startLevel = function (number) {
      game.number = number;
      game.level = buildLevel(game.rand, { cols: game.cols, number });
      game.enemies = game.level.enemies.map(makeWalker);
      game.p = newPlayer(game.level.start.x, game.level.start.y);
      game.cam = 0; game.boost = 0; game.boostNext = 0; game.pendingJump = 0; game.invul = 0; game.bumps = []; game.pops = []; game.flag = 0; game.stall = 0; game.lastX = game.p.x; game.fade = 0;
      game.phase = game.skipIntro ? 'play' : 'intro'; game.t = 0; game.skipIntro = false;               // the very first level may start playing at once (a still picture shows the game, not a card)
      game.events.push({ t: 'level' });
    };
    const bumpCell = (c, r) => {
      const i = r * game.level.cols + c, code = game.level.tiles[i];
      if (code !== T.Q && code !== T.BRICK) return;
      if (game.bumps.some((b) => b.c === c && b.r === r)) return;
      game.bumps.push({ c, r, t: 0, code });
      game.events.push({ t: 'cell', c, r });                              // the picture hides the cell while it hops
      if (code === T.Q) { game.level.tiles[i] = T.USED; game.pops.push({ x: c * TILE + 4, y: r * TILE - 2, t: 0, kind: 'coin' }); game.stats.coins++; }
      game.stats.bumped++;
    };
    const collect = () => {
      const p = game.p, level = game.level;
      for (let r = Math.floor((p.y - PHY.height) / TILE); r <= Math.floor((p.y - 1e-6) / TILE); r++) {
        for (let c = Math.floor((p.x - PHY.halfW) / TILE); c <= Math.floor((p.x + PHY.halfW - 1e-6) / TILE); c++) {
          const i = r * level.cols + c;
          if (r >= 0 && r < ROWS && c >= 0 && c < level.cols && level.coins[i]) { level.coins[i] = 0; game.events.push({ t: 'cell', c, r }); game.pops.push({ x: c * TILE + 4, y: r * TILE, t: 0, kind: 'spark' }); game.stats.coins++; }
        }
      }
    };
    const die = () => { const p = game.p; p.dead = true; p.vy = -5; p.t = 0; game.stats.deaths++; };
    /** Put the player on the nearest safe ground at or before x (for a respawn or a rescue): flat ground, no wall within three cells ahead. */
    const safeSpot = (x, forward) => {
      const level = game.level, dir = forward ? 1 : -1;
      for (let c = Math.floor(x / TILE); c > 2 && c < level.cols - 4; c += dir) {
        let ok = true;
        for (let k = -1; k <= 4; k++) if (!solidAt(level, c + k, GROUND) || solidAt(level, c + k, GROUND - 1) || solidAt(level, c + k, GROUND - 2)) ok = false;
        if (ok && !game.enemies.some((e) => e.alive && Math.abs(e.x - (c * TILE + 4)) < 30)) return c * TILE + 4;
      }
      return level.start.x;
    };
    const playStep = () => {
      const p = game.p;
      if (p.dead) {
        p.t++; p.vy = Math.min(PHY.maxFall, p.vy + PHY.gravity); p.y += p.vy;
        if (p.t > 55) { p.dead = false; p.x = safeSpot(p.x - 60, false); p.y = GROUND_Y; p.vy = 0; p.onGround = true; game.invul = 60; game.pendingJump = 0; }
        return;
      }
      if (game.boost > 0) game.boost--;
      if (p.onGround && game.boostNext > 0) { game.boost = game.boostNext; game.boostNext = 0; }          // a touch in the air waits for the ground: the planner's lookahead keeps its speed
      const speed = game.boost > 0 ? PHY.boost : PHY.speed;
      const jump = p.onGround ? plan(game) : 0;
      if (game.pendingJump > 0) game.pendingJump--;
      stepPlayer(game.level, p, { speed, jump }, game.ev);
      if (game.ev.jumped) { game.stats.jumps++; game.pendingJump = 0; p.hold = 14; }
      if (game.ev.bump) bumpCell(game.ev.bump[0], game.ev.bump[1]);
      collect();
      if (game.invul > 0) game.invul--;
      for (const e of game.enemies) stepEnemy(game.level, e);
      for (const e of game.enemies) {
        const t = touch(p, e);
        if (t === 'stomp') { e.state = e.kind === 'tall' ? 'shell' : 'flat'; e.t = e.kind === 'tall' ? 80 : 26; p.vy = PHY.bounce; p.onGround = false; game.stats.stomps++; game.pops.push({ x: e.x, y: e.y - 8, t: 0, kind: 'spark' }); }
        else if (t === 'hurt' && game.invul === 0) { die(); break; }
      }
      p.anim += speed;
      if (p.hold > 0) p.hold--;
      // never stuck: no progress for three seconds means the planner is lost; put the player on safe ground a little ahead
      if (Math.abs(p.x - game.lastX) < 0.3) { if (++game.stall > 90) { p.x = safeSpot(p.x + 24, true); p.y = GROUND_Y; p.vy = 0; p.onGround = true; game.stall = 0; game.stats.rescues++; game.invul = 40; } }
      else { game.stall = 0; game.lastX = p.x; }
      if (p.x >= game.level.goal.x - 7) { game.phase = 'grab'; game.t = 0; p.x = game.level.goal.x - 7; p.vy = 0; p.vx = 0; p.onGround = false; game.events.push({ t: 'goal' }); }
    };
    game.step = function () {
      game.steps++;
      const p = game.p;
      for (let i = game.bumps.length - 1; i >= 0; i--) { const b = game.bumps[i]; if (++b.t > 8) { game.bumps.splice(i, 1); game.events.push({ t: 'cell', c: b.c, r: b.r }); } }
      for (let i = game.pops.length - 1; i >= 0; i--) if (++game.pops[i].t > (game.pops[i].kind === 'coin' ? 22 : 8)) game.pops.splice(i, 1);
      if (game.buttons.a > 0) game.buttons.a--;
      if (game.buttons.b > 0) game.buttons.b--;
      if (game.phase === 'intro') { if (++game.t >= INTRO) { game.phase = 'play'; game.t = 0; } }
      else if (game.phase === 'play') playStep();
      else if (game.phase === 'grab') {                                  // down the pole, the flag with him
        p.y = Math.min(GROUND_Y, p.y + 1.6); game.flag = clamp((p.y - (game.level.goal.top + 14)) / (GROUND_Y - game.level.goal.top - 14), 0, 1);
        if (p.y >= GROUND_Y) { p.y = GROUND_Y; game.phase = 'win'; game.t = 0; game.flag = 1; }
      } else if (game.phase === 'win') { if (++game.t >= 18) { game.phase = 'walk'; game.t = 0; } }
      else if (game.phase === 'walk') { p.x += 1.6; p.anim += 1.6; p.onGround = true; if (++game.t >= 46) { game.phase = 'fade'; game.t = 0; } }
      else if (game.phase === 'fade') { game.fade = ++game.t / FADE; if (game.t >= FADE) { game.stats.levels++; game.startLevel(game.number + 1); } }
      const target = clamp(Math.round(p.x) - 108, 0, game.level.width - LCD.w);
      game.cam += clamp(target - game.cam, -4, 4);
    };
    /** A touch: 'jump' (the next safe jump, within a moment) or 'boost' (faster for two seconds). */
    game.poke = function (kind) {
      if (game.phase !== 'play') return false;
      if (kind === 'jump') { game.pendingJump = 24; game.buttons.a = 9; return true; }
      if (kind === 'boost') { if (game.p.onGround) game.boost = 66; else game.boostNext = 66; game.buttons.b = 9; return true; }
      return false;
    };
    game.skipIntro = !o.intro;
    game.startLevel(o.number);
    return game;
  }

  /* ==================================================================================================== the console: where things are */

  const LAYOUT = {
    bezel: { x: 6, y: 12, w: 188, h: 172 },
    dpad: { cx: 40, cy: 248, arm: 17, thick: 6 },
    a: { cx: 168, cy: 236, r: 11 }, b: { cx: 139, cy: 252, r: 11 },
    select: { x: 66, y: 290, w: 21, h: 6 }, start: { x: 98, y: 290, w: 21, h: 6 },
    speaker: { x: 154, y: 291 },
    led: { x: 11, y: 62 },
  };
  /** What a touch at native (x, y) is: a button of the console, the LCD, or nothing. */
  function hitTest(x, y) {
    const L = LAYOUT, near = (c, r) => Math.hypot(x - c.cx, y - c.cy) <= r;
    if (near(L.a, L.a.r + 4)) return 'a';
    if (near(L.b, L.b.r + 4)) return 'b';
    const d = L.dpad;
    if (Math.abs(x - d.cx) <= d.arm + 1 && Math.abs(y - d.cy) <= d.arm + 1) {
      const dx = x - d.cx, dy = y - d.cy;
      if (Math.abs(dx) < d.thick && Math.abs(dy) < d.thick) return 'dpad';
      return Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up');
    }
    for (const name of ['select', 'start']) { const b = L[name]; if (x >= b.x - 3 && x < b.x + b.w + 3 && y >= b.y - 8 && y < b.y + b.h + 4) return name; }
    if (x >= LCD.x && x < LCD.x + LCD.w && y >= LCD.y && y < LCD.y + LCD.h) return 'lcd';
    return null;
  }
  /** What a touch does to the game: 'jump', 'boost' or null. */
  const pokeAction = (hit) => (hit === 'a' || hit === 'up' || hit === 'lcd' ? 'jump' : hit === 'b' || hit === 'right' ? 'boost' : null);
  /** Where the console sits: with the page's dock up the LCD is above it (rows 0-185 stay visible); a shorter visible area slides the whole console up so the LCD's last row stays in view. */
  const shiftFor = (viewBottom) => clamp(Math.round((finite(viewBottom) ? viewBottom : H) - (LCD.y + LCD.h + 12)), -24, 0);
  function easeShift(current, target) { const d = target - current; return Math.abs(d) <= 2 ? target : Math.round(current + Math.sign(d) * Math.max(2, Math.min(Math.abs(d) * 0.35, 12))); }

  /* ---- a tiny 3 x 5 font of its own: the casing's lettering, and the HUD when the atlas is missing */
  const MINI = {
    A: '010101111101101', B: '110101110101110', C: '011100100100011', D: '110101101101110', E: '111100110100111', F: '111100110100100', G: '011100101101011', H: '101101111101101',
    I: '111010010010111', J: '001001001101010', K: '101101110101101', L: '100100100100111', M: '101111111101101', N: '110101101101101', O: '010101101101010', P: '110101110100100',
    Q: '010101101110011', R: '110101110101101', S: '011100010001110', T: '111010010010010', U: '101101101101111', V: '101101101101010', W: '101101111111101', X: '101101010101101',
    Y: '101101010010010', Z: '111001010100111', 0: '111101101101111', 1: '010110010010111', 2: '110001010100111', 3: '110001010001110', 4: '101101111001001', 5: '111100110001110',
    6: '011100111101111', 7: '111001010010010', 8: '111101111101111', 9: '111101111001110', ':': '000010000010000', '-': '000000111000000', '%': '101001010100101', '.': '000000000000010',
    '/': '001001010100100', '<': '001010100010001', '?': '110001010000010', ' ': '000000000000000',
  };
  const miniWidth = (text, scale) => text.length * 4 * scale - scale;
  function drawMini(g, text, x, y, color, scale = 1, lean = 0, scaleY = scale) {          // `lean`: pixels the top row is pushed right, in steps down the letter (an italic); `scaleY`: a different height
    g.fillStyle = color;
    for (let k = 0; k < text.length; k++) {
      const bits = MINI[text[k].toUpperCase()];
      if (!bits) continue;
      for (let i = 0; i < 15; i++) if (bits[i] === '1') g.fillRect(x + (k * 4 + (i % 3)) * scale + Math.round(lean * (4 - Math.floor(i / 3)) / 4 * scale), y + Math.floor(i / 3) * scaleY, scale, scaleY);
    }
  }
  const pxRect = (g, x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x, y, w, h); };
  function disc(g, cx, cy, r, color) {                      // a filled circle of diameter 2r + 1: flat top and bottom rows, no pointed tip
    g.fillStyle = color;
    for (let y = -r; y <= r; y++) { const half = Math.floor(Math.sqrt((r + 0.5) * (r + 0.5) - y * y)); g.fillRect(cx - half, cy + y, half * 2 + 1, 1); }
  }
  function ring(g, cx, cy, r, color) {                      // the one-pixel outline of that disc
    g.fillStyle = color;
    for (let y = -r; y <= r; y++) {
      const half = Math.floor(Math.sqrt((r + 0.5) * (r + 0.5) - y * y));
      if (Math.abs(y) === r) { g.fillRect(cx - half, cy + y, half * 2 + 1, 1); continue; }
      const inner = Math.floor(Math.sqrt((r - 0.5) * (r - 0.5) - y * y));
      g.fillRect(cx - half, cy + y, Math.max(1, half - inner), 1); g.fillRect(cx + inner + 1, cy + y, Math.max(1, half - inner), 1);
    }
  }
  function line(g, x0, y0, x1, y1, color, thick = 1) {
    g.fillStyle = color;
    const dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx - dy, x = x0, y = y0;
    for (let guard = 0; guard < 400; guard++) {
      g.fillRect(x, y, thick, 1);
      if (x === x1 && y === y1) break;
      const e2 = 2 * err;
      if (e2 > -dy) { err -= dy; x += sx; }
      if (e2 < dx) { err += dx; y += sy; }
    }
  }
  const mixHex = (a, b, t) => rgb([0, 1, 2].map((i) => Math.round(lerp(parseInt(a.slice(1 + 2 * i, 3 + 2 * i), 16), parseInt(b.slice(1 + 2 * i, 3 + 2 * i), 16), t))));

  /** The casing, the bezel and everything fixed on the console's face, once (crisp: whole pixels only). `lcdHole` is left to the LCD. */
  function paintCasing(g, rnd) {
    const bands = 40;
    for (let k = 0; k < bands; k++) pxRect(g, 0, k * 8, W, 8, mixHex('#d4d2c8', '#b9b7ad', k / (bands - 1)));              // the plastic, a little lighter at the top
    pxRect(g, 0, 0, W, 1, '#ebe9e0'); pxRect(g, 0, 1, W, 1, '#dedcd2'); pxRect(g, 0, 0, 2, H, '#e2e0d6'); pxRect(g, 2, 0, 1, H, '#d8d6cc');           // the lit edges
    pxRect(g, W - 2, 0, 2, H, '#a3a198'); pxRect(g, W - 3, 0, 1, H, '#aeaca3'); pxRect(g, 0, H - 2, W, 2, '#9f9d94');                                  // the shaded ones
    pxRect(g, 5, 0, 1, H, 'rgba(255,255,255,.10)'); pxRect(g, W - 6, 0, 1, H, 'rgba(0,0,0,.07)');                                                   // the shell's seams
    pxRect(g, 0, 8, W, 1, 'rgba(0,0,0,.08)'); pxRect(g, 0, 9, W, 1, 'rgba(255,255,255,.14)');
    // the bezel: dark plastic with a lit top-left rim, a dark bottom-right one and a recessed frame round the LCD
    const b = LAYOUT.bezel;
    pxRect(g, b.x - 1, b.y - 1, b.w + 2, b.h + 2, '#8e8d96');
    pxRect(g, b.x, b.y, b.w, b.h, '#6e6d78');
    pxRect(g, b.x, b.y, b.w, 1, '#9a99a3'); pxRect(g, b.x, b.y, 1, b.h, '#8d8c97');
    pxRect(g, b.x, b.y + b.h - 1, b.w, 1, '#53525d'); pxRect(g, b.x + b.w - 1, b.y, 1, b.h, '#5a5964');
    for (const [cx, cy] of [[b.x, b.y], [b.x + b.w - 1, b.y], [b.x, b.y + b.h - 1]]) { pxRect(g, cx, cy, 1, 1, '#c9c6bb'); }                      // rounded corners: the casing shows
    pxRect(g, b.x + b.w - 3, b.y + b.h - 3, 3, 3, '#c0beb4'); pxRect(g, b.x + b.w - 5, b.y + b.h - 1, 5, 1, '#c0beb4'); pxRect(g, b.x + b.w - 1, b.y + b.h - 5, 1, 5, '#c0beb4');
    pxRect(g, LCD.x - 3, LCD.y - 3, LCD.w + 6, LCD.h + 6, '#2d3027');
    pxRect(g, LCD.x - 3, LCD.y - 3, LCD.w + 6, 1, '#1f221b'); pxRect(g, LCD.x - 3, LCD.y - 3, 1, LCD.h + 6, '#1f221b');
    pxRect(g, LCD.x - 3, LCD.y + LCD.h + 2, LCD.w + 6, 1, '#4b4f43'); pxRect(g, LCD.x + LCD.w + 2, LCD.y - 3, 1, LCD.h + 6, '#4b4f43');
    pxRect(g, LCD.x - 1, LCD.y - 1, LCD.w + 2, LCD.h + 2, '#171a14');
    // the lettering between the two coloured lines, in the bezel's top margin
    const title = 'DOT MATRIX WITH STEREO SOUND', tx = Math.round((W - miniWidth(title, 1)) / 2);
    drawMini(g, title, tx, 17, '#e3e1dc');
    for (const x of [14, 160]) { pxRect(g, x, 17, 26, 2, '#9a3a68'); pxRect(g, x, 20, 26, 1, '#3b4676'); }
    // the power lamp, in the left margin
    const led = LAYOUT.led;
    pxRect(g, led.x - 1, led.y - 1, 6, 6, '#3a2a31'); pxRect(g, led.x, led.y, 4, 4, '#a3283a'); pxRect(g, led.x + 1, led.y, 2, 2, '#ff6a78');
    // the lettering under the bezel: the project's own name and a model name of its own
    drawMini(g, 'DESK DISPLAY', 14, 189, '#363f6c');
    drawMini(g, 'TOKEN PAL', 84, 187, '#363f6c', 2, 1);
    // the speaker's slots, slanted
    const sp = LAYOUT.speaker;
    for (let k = 0; k < 6; k++) { const x = sp.x + k * 7; line(g, x, sp.y, x - 6, sp.y + 17, '#7f7e76', 3); line(g, x + 3, sp.y + 1, x - 3, sp.y + 18, '#e6e4da', 1); }
    // the buttons' sockets
    const d = LAYOUT.dpad;
    disc(g, d.cx, d.cy, 25, '#b1afa5'); ring(g, d.cx, d.cy, 25, '#c9c7bd'); ring(g, d.cx, d.cy, 24, '#9d9b92');
    for (const btn of [LAYOUT.a, LAYOUT.b]) { disc(g, btn.cx, btn.cy, btn.r + 3, '#a9a79d'); ring(g, btn.cx, btn.cy, btn.r + 3, '#9b998f'); }
    drawMini(g, 'B', LAYOUT.b.cx - 1, LAYOUT.b.cy + 17, '#363f6c'); drawMini(g, 'A', LAYOUT.a.cx - 1, LAYOUT.a.cy + 17, '#363f6c');
    drawMini(g, 'SELECT', LAYOUT.select.x - 2, LAYOUT.select.y + 13, '#363f6c'); drawMini(g, 'START', LAYOUT.start.x, LAYOUT.start.y + 13, '#363f6c');
    // wear: scuffs and a few scratches, seeded (the same every time)
    for (let k = 0; k < 90; k++) {
      const x = Math.floor(rnd() * W), y = Math.floor(rnd() * H);
      if (x > LCD.x - 4 && x < LCD.x + LCD.w + 4 && y > LCD.y - 4 && y < LCD.y + LCD.h + 4) continue;
      pxRect(g, x, y, rnd() < 0.3 ? 2 : 1, 1, rnd() < 0.5 ? 'rgba(255,255,255,.28)' : 'rgba(40,38,30,.22)');
    }
    for (let k = 0; k < 7; k++) { const x = 10 + Math.floor(rnd() * 180), y = 196 + Math.floor(rnd() * 120), len = 3 + Math.floor(rnd() * 5); line(g, x, y, x + len, y - Math.floor(len / 2), 'rgba(255,255,255,.22)', 1); line(g, x, y + 1, x + len, y + 1 - Math.floor(len / 2), 'rgba(40,38,30,.16)', 1); }
    for (let k = 0; k < 10; k++) { const x = b.x + 4 + Math.floor(rnd() * (b.w - 8)), y = b.y + b.h - 6 + Math.floor(rnd() * 5); pxRect(g, x, y, 2, 1, 'rgba(255,255,255,.14)'); }
  }
  /** Shadow from the LCD recess; the engine adds a fine pixel grid inside the LCD only. */
  function paintOverlay(g) {
    for (let k = 0; k < 4; k++) pxRect(g, LCD.x, LCD.y + k, LCD.w, 1, 'rgba(10,20,10,' + [0.34, 0.22, 0.12, 0.06][k] + ')');
    for (let k = 0; k < 2; k++) pxRect(g, LCD.x + k, LCD.y, 1, LCD.h, 'rgba(10,20,10,' + [0.22, 0.10][k] + ')');
  }
  /** The cross with one arm pressed (or none): arms `thick` x 2 and `arm` long each way, a lit top-left edge, a dark bottom-right one and a dimple in the middle. */
  function paintDpad(g, ox, oy, pressed) {
    const d = LAYOUT.dpad, cx = ox + d.arm + 1, cy = oy + d.arm + 1, t = d.thick, a = d.arm;
    const arm = (x, y, w, h, on) => { pxRect(g, x, y, w, h, on ? '#262733' : '#3b3c4f'); pxRect(g, x, y, w, 1, on ? '#1e1f29' : '#5b5d76'); pxRect(g, x, y, 1, h, on ? '#1e1f29' : '#53556d'); pxRect(g, x, y + h - 1, w, 1, '#1f202b'); pxRect(g, x + w - 1, y, 1, h, '#1f202b'); };
    arm(cx - a, cy - t, 2 * a + 1, 2 * t, false); arm(cx - t, cy - a, 2 * t, 2 * a + 1, false);
    const on = { left: [cx - a, cy - t, a - t + 1, 2 * t], right: [cx + t, cy - t, a - t + 1, 2 * t], up: [cx - t, cy - a, 2 * t, a - t + 1], down: [cx - t, cy + t, 2 * t, a - t + 1] }[pressed];
    if (on) arm(on[0], on[1], on[2], on[3], true);
    pxRect(g, cx - t, cy - t, 2 * t, 2 * t, '#3b3c4f'); pxRect(g, cx - t, cy - t, 2 * t, 1, '#5b5d76'); pxRect(g, cx - t, cy - t, 1, 2 * t, '#53556d');
    disc(g, cx, cy, 4, '#2c2d3b'); disc(g, cx, cy + 1, 3, '#23242f');
    for (const [x, y, w, h] of [[cx - a + 3, cy - 1, 4, 1], [cx + a - 6, cy - 1, 4, 1], [cx - 1, cy - a + 3, 1, 4], [cx - 1, cy + a - 6, 1, 4]]) pxRect(g, x, y, w, h, 'rgba(0,0,0,.35)');
  }
  /** A round button, up or pressed (a pixel lower, its lit rim gone): burgundy with a highlight arc and a shadow. */
  function paintRound(g, ox, oy, r, pressed) {
    const cx = ox + r + 1, cy = oy + r + 1 + (pressed ? 1 : 0);
    disc(g, cx, cy, r, pressed ? '#6d2145' : '#7e2a50'); disc(g, cx - 1, cy - 1, r - 2, pressed ? '#823055' : '#97385f');
    if (!pressed) { line(g, cx - r + 3, cy - 3, cx - 4, cy - r + 3, '#bd6a8b', 2); pxRect(g, cx - 3, cy - r + 2, 3, 1, '#c98099'); }
    ring(g, cx, cy, r, '#4f1832');
  }
  /** Start or Select: a slanted pill of dark rubber. */
  function paintPill(g, ox, oy, w, h, pressed) {
    for (let i = 0; i < w; i++) {
      const y = oy + Math.round((w - 1 - i) * 0.26), top = i === 0 || i === w - 1 ? 1 : 0, rows = h - top * 2;
      pxRect(g, ox + i, y + top + (pressed ? 1 : 0), 1, rows, pressed ? '#5b5a68' : '#6e6d7d');
      if (!top) { pxRect(g, ox + i, y + (pressed ? 1 : 0), 1, 1, pressed ? '#6a6978' : '#8c8b9c'); pxRect(g, ox + i, y + h - 1 + (pressed ? 1 : 0), 1, 1, '#454452'); }
    }
  }

  /* ==================================================================================================== the art: the atlas, re-coloured with the LCD's greens */

  const REQUIRED_FRAMES = ['hero-stand', 'hero-walk-0', 'hero-walk-1', 'hero-walk-2', 'hero-jump', 'hero-dead', 'walker-a-0', 'walker-a-1', 'walker-a-flat', 'walker-b-0', 'walker-b-1', 'shell-0', 'shell-1',
    'coin-0', 'coin-1', 'coin-2', 'ground-top', 'ground', 'brick', 'block-q', 'block-used', 'block-hard', 'coin-tile', 'band-fill', 'band-lines', 'pyr-left', 'pyr-right',
    'pyr-peak', 'palm-crown', 'palm-trunk', 'pipe-top', 'pipe-body', 'cloud-s', 'cloud-m', 'cloud-l', 'flag-ball', 'flag-pole', 'flag-cloth'];
  /** The atlas's JSON as the scene needs it: frames by name, the glyphs of the HUD font, the grey step of the four shades. Null when anything the scene draws is missing. */
  function readArt(json) {
    if (!json || typeof json !== 'object' || !json.frames || typeof json.frames !== 'object') return null;
    const frames = {};
    for (const [name, f] of Object.entries(json.frames)) if (Array.isArray(f) && f.length === 4 && f.every(finite) && f[2] > 0 && f[3] > 0) frames[name] = f;
    for (const name of REQUIRED_FRAMES) if (!frames[name]) return null;
    const glyphs = {};
    if (json.glyphs && typeof json.glyphs === 'object') for (const [ch, name] of Object.entries(json.glyphs)) if (ch.length === 1 && frames[name]) glyphs[ch] = frames[name];
    return { frames, glyphs, step: finite(json.step) && json.step > 0 ? json.step : 85 };
  }
  /** Re-colour RGBA pixels whose grey is shade x `step` with the LCD's greens, in place (transparent pixels stay transparent). */
  function recolorPixels(data, step, shades) {
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] === 0) continue;
      const c = shades[clamp(Math.round(data[i] / step), 0, shades.length - 1)];
      data[i] = c[0]; data[i + 1] = c[1]; data[i + 2] = c[2]; data[i + 3] = 255;
    }
    return data;
  }
  function makeCanvas(w, h, opaque) {
    if (typeof document === 'undefined') return null;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d', opaque ? { alpha: false } : undefined);
    if (g) g.imageSmoothingEnabled = false;
    return { canvas: c, g };
  }
  function recolorAtlas(image, art) {
    const w = image.naturalWidth || image.width, h = image.naturalHeight || image.height, m = makeCanvas(w, h);
    if (!m) return null;
    m.g.drawImage(image, 0, 0);
    try { const data = m.g.getImageData(0, 0, w, h); recolorPixels(data.data, art.step, SHADES); m.g.putImageData(data, 0, 0); } catch (_) { return null; }
    return m.canvas;
  }

  /* ==================================================================================================== drawing: the level's layers, the sprites, the HUD, the console */

  function blit(g, sheet, art, name, x, y, flip) {
    const f = art.frames[name];
    if (!f) return false;
    x = Math.round(x); y = Math.round(y);
    if (flip) { g.save(); g.translate(x + f[2], y); g.scale(-1, 1); g.drawImage(sheet, f[0], f[1], f[2], f[3], 0, 0, f[2], f[3]); g.restore(); }
    else g.drawImage(sheet, f[0], f[1], f[2], f[3], x, y, f[2], f[3]);
    return true;
  }
  /** Draw text in the game's font (8 x 8 a letter) from the glyph frames; a character it has no glyph for is skipped. */
  function drawText(g, sheet, art, text, x, y) {
    for (let k = 0; k < text.length; k++) { const f = art.glyphs[text[k].toUpperCase()]; if (f && text[k] !== ' ') g.drawImage(sheet, f[0], f[1], f[2], f[3], x + 8 * k, y, f[2], f[3]); }
  }
  /** One cell of the level's foreground (ground, blocks, coins); pipes are drawn as wholes. */
  function drawCell(g, sheet, art, level, c, r) {
    const code = level.tiles[r * level.cols + c], x = c * TILE, y = r * TILE;
    g.clearRect(x, y, TILE, TILE);
    const name = { 1: 'ground-top', 2: 'ground', 3: 'brick', 4: 'block-q', 5: 'block-used', 6: 'block-hard' }[code];
    if (name) blit(g, sheet, art, name, x, y);
    else if (code === T.AIR && level.coins[r * level.cols + c]) blit(g, sheet, art, 'coin-tile', x, y);
  }
  /** The scenery behind the level and the level itself, drawn once into two long pictures (each as tall as the LCD). */
  function paintLevel(back, front, sheet, art, level) {
    back.clearRect(0, 0, level.width, LCD.h); front.clearRect(0, 0, level.width, LCD.h);
    back.fillStyle = SHADE_CSS[0]; back.fillRect(0, 0, level.width, LCD.h);
    for (const p of level.decor.pyramids) {
      const top = GROUND - p.h;
      blit(back, sheet, art, 'pyr-peak', p.col * TILE, top * TILE);
      for (let k = 1; k < p.h; k++) { blit(back, sheet, art, 'pyr-left', (p.col - k) * TILE, (top + k) * TILE); blit(back, sheet, art, 'pyr-right', (p.col + 1 + k) * TILE, (top + k) * TILE); }
    }
    for (const p of level.decor.palms) {
      const top = GROUND - 1 - p.h;
      blit(back, sheet, art, 'palm-crown', p.col * TILE, top * TILE);
      for (let r = top + 1; r < GROUND; r++) blit(back, sheet, art, 'palm-trunk', p.col * TILE, r * TILE);
    }
    for (const c of level.decor.clouds) blit(back, sheet, art, c.kind, c.x, c.y);
    for (let r = 0; r < ROWS; r++) for (let c = 0; c < level.cols; c++) if (level.tiles[r * level.cols + c] !== T.PIPE) drawCell(front, sheet, art, level, c, r);
    for (const f of level.features) if (f.kind === 'pipe') {
      blit(front, sheet, art, 'pipe-top', f.col * TILE, (GROUND - f.h) * TILE);
      for (let r = GROUND - f.h + 2; r < GROUND; r++) blit(front, sheet, art, 'pipe-body', f.col * TILE, r * TILE);
    }
  }
  /** One cell of the plain stand-in for the foreground: flat shapes in the four greens. */
  function drawCellPlain(g, level, c, r) {
    const code = level.tiles[r * level.cols + c], x = c * TILE, y = r * TILE;
    g.clearRect(x, y, TILE, TILE);
    if (code) {
      g.fillStyle = SHADE_CSS[code === T.PIPE ? 2 : 3]; g.fillRect(x, y, TILE, TILE);
      if (code !== T.GROUND && code !== T.GROUND_TOP) { g.fillStyle = SHADE_CSS[code === T.Q ? 0 : 1]; g.fillRect(x + 2, y + 2, 4, 4); }
    } else if (level.coins[r * level.cols + c]) { g.fillStyle = SHADE_CSS[2]; g.fillRect(x + 2, y + 1, 4, 6); }
  }
  /** The plain stand-in when the atlas is missing: flat shapes in the four greens, the same level. */
  function paintLevelPlain(back, front, level) {
    back.clearRect(0, 0, level.width, LCD.h); front.clearRect(0, 0, level.width, LCD.h);
    back.fillStyle = SHADE_CSS[0]; back.fillRect(0, 0, level.width, LCD.h);
    for (const c of level.decor.clouds) { back.fillStyle = SHADE_CSS[1]; back.fillRect(c.x, c.y + 4, c.kind === 'cloud-l' ? 40 : 24, 6); back.fillRect(c.x + 6, c.y, 12, 6); }
    for (const p of level.decor.pyramids) { back.fillStyle = SHADE_CSS[2]; for (let k = 0; k < p.h; k++) back.fillRect((p.col - k) * TILE + 4, (GROUND - p.h + k) * TILE, 2 * k * TILE + 8, 1); }
    for (let r = 0; r < ROWS; r++) for (let c = 0; c < level.cols; c++) if (level.tiles[r * level.cols + c] || level.coins[r * level.cols + c]) drawCellPlain(front, level, c, r);
  }
  /** A gauge of `n` segments `w` wide with a one-pixel gap: filled segments dark, the rest an empty track; unknown draws only a dotted track. */
  function drawGauge(g, x, y, w, h, n, fraction) {
    for (let k = 0; k < n; k++) {
      const left = x + k * (w + 1);
      if (fraction === null) { g.fillStyle = SHADE_CSS[1]; for (let i = 0; i < w; i += 2) g.fillRect(left + i, y + (h >> 1), 1, 1); continue; }
      g.fillStyle = SHADE_CSS[1]; g.fillRect(left, y, w, h);
      g.fillStyle = SHADE_CSS[0]; g.fillRect(left + 1, y + 1, w - 2, h - 2);
      const fill = segmentFill(fraction, n, k);
      if (fill > 0) { g.fillStyle = SHADE_CSS[3]; g.fillRect(left, y, Math.max(1, Math.round(w * fill)), h); }
    }
  }
  function hudText(g, sheet, art, text, x, y) {
    if (art && sheet) drawText(g, sheet, art, text, x, y);
    else drawMini(g, text, x, y + 1, SHADE_CSS[3], 2, 0, 1);              // twice as wide as high: six by five pixels in an eight-pixel cell
  }
  function hudNumber(g, sheet, art, text, x, y) {
    // Full-size game glyphs fit seven characters per player. Use the compact
    // local font for long balances or symbols missing from the original atlas.
    if (text.length > 7 || /[<?]/.test(text)) drawMini(g, text, x, y + 1, SHADE_CSS[3], 1, 0, 1);
    else hudText(g, sheet, art, text, x, y);
  }
  const HEART = ['.##.##.', '#######', '#######', '.#####.', '..###..', '...#...'];
  const HEART_EDGE = HEART.map((row, r) => Array.from(row, (cell, c) => cell === '#' && [[r - 1, c], [r + 1, c], [r, c - 1], [r, c + 1]].some(([nr, nc]) => !(HEART[nr] && HEART[nr][nc] === '#'))));
  /** Three hearts for the saved resets: a filled one for each available (dark), an outline (light inside) for the rest; then ONE dot when the count is unknown or old, and a plus for more than three. */
  function drawHeartRow(g, hearts, x, y) {
    for (let k = 0; k < 3; k++) {
      for (let r = 0; r < 6; r++) for (let c = 0; c < 7; c++) {
        if (HEART[r][c] !== '#') continue;
        g.fillStyle = SHADE_CSS[HEART_EDGE[r][c] || k < hearts.full ? 3 : 0];
        g.fillRect(x + 8 * k + c, y + 1 + r, 1, 1);
      }
    }
    g.fillStyle = SHADE_CSS[3];
    if (hearts.dot) g.fillRect(x + 24, y + 5, 2, 2);                                  // unknown or old: ONE dot, like the board's quiet hearts
    if (hearts.plus) { const px = x + (hearts.dot ? 26 : 25); g.fillRect(px, y + 3, 3, 1); g.fillRect(px + 1, y + 2, 1, 3); }        // more than three
  }
  /** The HUD into its own 160 x 32 picture: labels and numbers in the game's font, the hearts, the countdowns, the gauges and the real time. */
  function paintHud(g, sheet, art, model, clock) {
    g.fillStyle = SHADE_CSS[0]; g.fillRect(0, 0, LCD.w, 32);
    g.fillStyle = SHADE_CSS[1]; g.fillRect(0, 16, LCD.w, 8);
    g.fillStyle = SHADE_CSS[2]; g.fillRect(0, 31, LCD.w, 1);
    hudText(g, sheet, art, 'CODEX', 0, 0); hudText(g, sheet, art, 'CLAUDE', 64, 0); hudText(g, sheet, art, clock, 120, 0);
    hudNumber(g, sheet, art, model.codex.text, 0, 8); hudNumber(g, sheet, art, model.claude.text, 64, 8);
    drawHeartRow(g, model.codex.hearts, 0, 16); drawHeartRow(g, model.claude.hearts, 64, 16);
    hudText(g, sheet, art, model.codex.reset, 30, 16); hudText(g, sheet, art, model.claude.reset, 94, 16);
    drawGauge(g, 2, 26, 5, 4, 10, model.codex.fill); drawGauge(g, 66, 26, 5, 4, 10, model.claude.fill);
    const s = model.session;
    if (s) {
      hudText(g, sheet, art, '5H', 104, 8); hudText(g, sheet, art, s.text, 160 - 8 * s.text.length, 8);
      drawGauge(g, 130, 18, 5, 4, 5, s.quota / 5 > 1 ? 1 : s.quota / 5); drawGauge(g, 130, 26, 5, 4, 5, s.time / 5);
    }
  }
  const HERO_WALK = ['hero-walk-0', 'hero-walk-1', 'hero-walk-2', 'hero-walk-1'];
  /** Which picture of the player: dead, in the air, running (a faster cycle when he runs faster) or standing. */
  function playerFrame(game) {
    const p = game.p;
    if (p.dead) return 'hero-dead';
    if (game.phase === 'grab') return 'hero-jump';
    if (!p.onGround) return 'hero-jump';
    if (game.phase === 'intro' || game.phase === 'win') return 'hero-stand';
    return HERO_WALK[Math.floor(p.anim / 5) % 4];
  }
  function walkerFrame(e) {
    if (e.kind === 'round') return e.state === 'walk' ? ['walker-a-' + (Math.floor((e.anim || 0) / 8) % 2), false] : ['walker-a-flat', false];
    return e.state === 'walk' ? ['walker-b-' + (Math.floor((e.anim || 0) / 10) % 2), e.dir > 0] : ['shell-' + (Math.floor((e.t || 0) / 8) % 2), false];
  }
  const BUMP_UP = [0, 2, 3, 3, 2, 1, 1, 0, 0];

  /** The moving things on the LCD, far to near: coins and sparks popping, walkers, hopping blocks, the flag, the player. Positions in whole pixels. */
  function drawActors(g, sheet, art, game) {
    const cam = Math.round(game.cam), level = game.level;
    if (!art) {                                                             // plain stand-ins
      g.fillStyle = SHADE_CSS[3];
      for (const e of game.enemies) if (e.alive) g.fillRect(Math.round(e.x - cam - 4), Math.round(e.y - (e.kind === 'tall' ? 14 : 7)), 8, e.kind === 'tall' ? 14 : 7);
      const p = game.p; g.fillRect(Math.round(p.x - cam - 6), Math.round(p.y - 16), 12, 16); g.fillStyle = SHADE_CSS[1]; g.fillRect(Math.round(p.x - cam - 3), Math.round(p.y - 14), 6, 5);
      return;
    }
    const g0 = level.goal, gx = g0.x - cam;
    if (gx > -16 && gx < LCD.w + 16) {
      for (let y = g0.top + 8; y < GROUND_Y; y += 8) blit(g, sheet, art, 'flag-pole', gx - 4, y);
      blit(g, sheet, art, 'flag-ball', gx - 4, g0.top);
      blit(g, sheet, art, 'flag-cloth', gx + 1, g0.top + 8 + Math.round(game.flag * (GROUND_Y - g0.top - 24)));
      blit(g, sheet, art, 'block-hard', gx - 4, GROUND_Y - 8);
    }
    for (const b of game.bumps) {
      const up = BUMP_UP[Math.min(b.t, BUMP_UP.length - 1)], x = b.c * TILE - cam;
      blit(g, sheet, art, b.code === T.Q ? (b.t < 3 ? 'block-q' : 'block-used') : 'brick', x, b.r * TILE - up);
    }
    for (const pop of game.pops) {
      const x = pop.x - cam;
      if (pop.kind === 'coin') { if (pop.t < 17 || (pop.t & 1)) blit(g, sheet, art, ['coin-0', 'coin-1', 'coin-2', 'coin-1'][Math.floor(pop.t / 2) % 4], x - 4, pop.y - 6 - Math.round(Math.sin(Math.min(1, pop.t / 16) * Math.PI / 2) * 22)); }
      else { g.fillStyle = SHADE_CSS[3]; g.fillRect(Math.round(x) - 3 - pop.t, Math.round(pop.y) - pop.t, 2, 2); g.fillRect(Math.round(x) + 2 + pop.t, Math.round(pop.y) - pop.t, 2, 2); g.fillRect(Math.round(x) - 1, Math.round(pop.y) - 4 - pop.t, 2, 2); }
    }
    for (const e of game.enemies) {
      if (!e.alive || e.x - cam < -16 || e.x - cam > LCD.w + 16) continue;
      if (e.state !== 'walk' && e.t < 10 && (e.t & 1)) continue;             // blinks out
      const [name, flip] = walkerFrame(e), f = art.frames[name];
      blit(g, sheet, art, name, e.x - cam - (f[2] >> 1), e.y - f[3], flip);
    }
    const p = game.p;
    if (!(game.invul > 0 && !p.dead && (game.steps & 2))) blit(g, sheet, art, playerFrame(game), p.x - cam - 8, p.y - 16 + (p.dead ? 0 : 0), false);
  }

  /* ==================================================================================================== the scene */

  const now = (s) => { const d = s.dbg || {}; return d.now !== undefined ? (typeof d.now === 'function' ? d.now() : d.now) : Date.now(); };
  const viewBottom = (api) => (api && api.view && finite(api.view.bottom) ? api.view.bottom : H);
  const scene = {
    size: [W, H],
    post: 'handheld',
    pixelRect() { return [LCD.x, LCD.y + (this.s ? this.s.shift : 0), LCD.w, LCD.h]; },
    dbg: {},
    init(api) {
      const s = { api, art: null, sheet: null, game: null, hud: null, hudKey: '', clockKey: '', model: null, readingObj: undefined, readingSeen: 0, shift: shiftFor(viewBottom(api)), taps: {}, step: 0, level: -1,
        canvases: {}, ghostOn: true, quality: 1 };
      this.s = s;
      const rand = typeof api.random === 'function' ? api.random : seeded(7);
      const day = Math.floor(now(this) / 86400000);
      const base = Math.floor(rand() * 4294967296);
      s.game = createGame({ rand: seeded((base ^ Math.imul(day, 2654435761)) >>> 0), number: Number.isFinite(this.dbg.number) ? this.dbg.number : 0, intro: false });
      const art = api.json && api.atlas ? readArt(api.json) : null;
      s.art = art; s.sheet = art ? recolorAtlas(api.atlas, art) : null;
      if (!s.sheet) s.art = null;
      const cv = s.canvases, mk = (name, w, h, opaque) => { const m = makeCanvas(w, h, opaque); cv[name] = m; return m; };
      mk('casing', W, H); mk('overlay', W, H); mk('lcd', LCD.w, LCD.h, true); mk('ghost', LCD.w, LCD.h, true); mk('hud', LCD.w, 32);
      mk('back', s.game.level.width, LCD.h); mk('front', s.game.level.width, LCD.h);
      const rnd = seeded(0x6b0b);
      if (cv.casing) paintCasing(cv.casing.g, rnd);
      if (cv.overlay) paintOverlay(cv.overlay.g);
      cv.parts = {};
      const part = (name, w, h, paint) => { const m = makeCanvas(w, h); if (m) { paint(m.g); cv.parts[name] = m.canvas; } };
      for (const dir of ['none', 'up', 'down', 'left', 'right']) part('dpad-' + dir, 2 * LAYOUT.dpad.arm + 3, 2 * LAYOUT.dpad.arm + 3, (g) => paintDpad(g, 0, 0, dir === 'none' ? null : dir));
      for (const [name, r] of [['a', LAYOUT.a.r], ['b', LAYOUT.b.r]]) for (const on of [0, 1]) part(name + on, 2 * r + 3, 2 * r + 4, (g) => paintRound(g, 0, 0, r, !!on));
      for (const name of ['select', 'start']) for (const on of [0, 1]) part(name + on, LAYOUT[name].w + 2, LAYOUT[name].h + 8, (g) => paintPill(g, 0, 0, LAYOUT[name].w, LAYOUT[name].h, !!on));
      this.layers(s);
      this.hudRefresh(s, true);
    },
    /** (Re)paint the long pictures of the current level. */
    layers(s) {
      const cv = s.canvases;
      if (!cv.back || !cv.front) return;
      if (cv.back.canvas.width !== s.game.level.width) { cv.back.canvas.width = s.game.level.width; cv.front.canvas.width = s.game.level.width; cv.back.g.imageSmoothingEnabled = false; cv.front.g.imageSmoothingEnabled = false; }
      if (s.art) paintLevel(cv.back.g, cv.front.g, s.sheet, s.art, s.game.level); else paintLevelPlain(cv.back.g, cv.front.g, s.game.level);
      s.level = s.game.level.number;
    },
    hudRefresh(s, force) {
      const t = now(this), date = new Date(t);
      const readings = s.api.readings ? s.api.readings() : null;
      if (readings !== s.readingObj) { s.readingObj = readings; s.readingSeen = Date.now(); }
      const age = this.dbg.noStale ? 0 : Date.now() - s.readingSeen;
      s.model = hudModel(readings, t, age);
      const clock = clockText(date, true), key = s.model.key + '|' + clock;
      if (!force && key === s.hudKey) return;
      s.hudKey = key;
      const m = s.canvases.hud;
      if (m) paintHud(m.g, s.sheet, s.art, s.model, clock);
    },
    step(api, dt) {
      const s = this.s;
      if (!s) return;
      const game = s.game;
      s.step++;
      game.step();
      for (const ev of game.events.splice(0)) {
        if (ev.t === 'level') this.layers(s);
        else if (ev.t === 'cell' && s.canvases.front && !game.bumps.some((b) => b.c === ev.c && b.r === ev.r)) { if (s.art) drawCell(s.canvases.front.g, s.sheet, s.art, game.level, ev.c, ev.r); else drawCellPlain(s.canvases.front.g, game.level, ev.c, ev.r); }
        else if (ev.t === 'cell' && s.canvases.front) s.canvases.front.g.clearRect(ev.c * TILE, ev.r * TILE, TILE, TILE);
      }
      if (s.step % 6 === 0) this.hudRefresh(s, false);
      s.shift = easeShift(s.shift, shiftFor(viewBottom(api)));
      for (const k of Object.keys(s.taps)) if (--s.taps[k] <= 0) delete s.taps[k];
      s.ghostOn = !(api.tier === 'low' || api.tier === 'light');
    },
    draw(api, g) {
      const s = this.s;
      if (!s) return;
      const cv = s.canvases, game = s.game;
      if (!cv.casing || !cv.lcd) { g.fillStyle = '#c7c5bc'; g.fillRect(0, 0, W, H); return; }
      this.drawLcd(s);
      g.save();
      g.translate(0, s.shift);
      g.drawImage(cv.casing.canvas, 0, 0);
      g.drawImage(cv.lcd.canvas, LCD.x, LCD.y);
      if (cv.overlay) g.drawImage(cv.overlay.canvas, 0, 0);
      this.drawControls(s, g, game);
      g.restore();
      if (s.shift < 0) { g.fillStyle = '#9f9d94'; g.fillRect(0, H + s.shift, W, -s.shift); }          // the casing continues below
    },
    drawLcd(s) {
      const cv = s.canvases, g = cv.lcd.g, game = s.game, cam = Math.round(game.cam);
      if (!cv.hud) return;
      g.fillStyle = SHADE_CSS[0]; g.fillRect(0, 0, LCD.w, LCD.h);
      if (game.phase === 'intro') {
        g.fillStyle = SHADE_CSS[0]; g.fillRect(0, 32, LCD.w, LCD.h - 32);
        const text = worldLabel(game.number);
        if (s.art && s.sheet) drawText(g, s.sheet, s.art, text, Math.round((LCD.w - text.length * 8) / 2), 80);
        else drawMini(g, text, Math.round((LCD.w - miniWidth(text, 2)) / 2), 80, SHADE_CSS[3], 2);
      } else if (cv.back && cv.front) {
        g.drawImage(cv.back.canvas, cam, 0, LCD.w, LCD.h, 0, 0, LCD.w, LCD.h);
        g.drawImage(cv.front.canvas, cam, 0, LCD.w, LCD.h, 0, 0, LCD.w, LCD.h);
        drawActors(g, s.sheet, s.art, game);
        if (game.phase === 'fade') { g.globalAlpha = clamp(game.fade, 0, 1); g.fillStyle = SHADE_CSS[3]; g.fillRect(0, 32, LCD.w, LCD.h - 32); g.globalAlpha = 1; }
      }
      g.drawImage(cv.hud.canvas, 0, 0);
      if (s.ghostOn && cv.ghost) {                                              // the previous frame, a little: dark pixels fade slowly on an LCD
        g.globalCompositeOperation = 'darken'; g.globalAlpha = 0.14; g.drawImage(cv.ghost.canvas, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
      }
      if (cv.ghost) cv.ghost.g.drawImage(cv.lcd.canvas, 0, 0);
    },
    drawControls(s, g, game) {
      const L = LAYOUT, parts = s.canvases.parts || {}, p = game.p, running = (game.phase === 'play' || game.phase === 'walk') && !p.dead;
      const tap = (name) => s.taps[name] > 0;
      const down = (name) => (name === 'a' ? game.buttons.a > 0 || (game.phase === 'play' && p.hold > 0 && !p.onGround) || tap('a') : name === 'b' ? game.boost > 0 || tap('b')
        : name === 'start' ? (game.phase === 'intro' && game.t > 20 && game.t < 34) || tap('start') : name === 'select' ? tap('select') : false);
      let dir = 'none';
      for (const d of ['up', 'down', 'left', 'right']) if (tap(d)) dir = d;
      if (dir === 'none' && running) dir = 'right';
      const dp = parts['dpad-' + dir];
      if (dp) g.drawImage(dp, L.dpad.cx - L.dpad.arm - 1, L.dpad.cy - L.dpad.arm - 1);
      for (const [name, b] of [['a', L.a], ['b', L.b]]) { const part = parts[name + (down(name) ? 1 : 0)]; if (part) g.drawImage(part, b.cx - b.r - 1, b.cy - b.r - 1); }
      for (const name of ['select', 'start']) { const part = parts[name + (down(name) ? 1 : 0)]; if (part) g.drawImage(part, L[name].x - 1, L[name].y - 1); }
      const led = L.led;                                                          // the lamp's glow
      g.fillStyle = 'rgba(255,60,80,.16)'; g.fillRect(led.x - 3, led.y - 3, 10, 10); g.fillStyle = 'rgba(255,90,110,.22)'; g.fillRect(led.x - 1, led.y - 1, 6, 6);
    },
    poke(api, x, y) {
      const s = this.s;
      if (!s) return;
      const hit = hitTest(x, y - s.shift);
      if (!hit) return;
      const label = hit === 'dpad' ? null : hit === 'lcd' ? 'a' : hit;
      if (label) s.taps[label] = 8;
      const action = pokeAction(hit);
      if (action) s.game.poke(action);
    },
  };

  const logic = {
    W, H, LCD, TILE, ROWS, GROUND, GROUND_Y, HUD_ROWS, STEP, SHADES, STALE_MS, T, SOLID, PHY, INTRO, FADE, LAYOUT, MINI, REQUIRED_FRAMES, FEATURES,
    seeded, percentText, resetText, heartsModel, hudModel, clockText, segmentFill, worldLabel, buildLevel, solidAt, stepPlayer, stepEnemy, touch, look, runSafe, jumpSafe, plan, createGame,
    hitTest, pokeAction, shiftFor, easeShift, readArt, recolorPixels, playerFrame, walkerFrame, paintHud, drawGauge, drawText, drawMini, miniWidth, blit, drawCell, drawCellPlain, paintLevel, paintLevelPlain,
  };
  if (global.TabletGames && typeof global.TabletGames.define === 'function') global.TabletGames.define('game-boy', scene);
  if (typeof module !== 'undefined' && module.exports) module.exports = Object.assign({ scene }, logic);
}(typeof window !== 'undefined' ? window : globalThis));
