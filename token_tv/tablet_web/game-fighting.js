/* VERSUS for the tablet: a small fighting game that plays itself, in real time (a scene of the game engine, stage-game.js: window.TabletGames).
 *
 * Tony: "more fluid, bigger, more things, full-bleed" and then "the STAGE needs more DETAILS, more cool things and WOW things". The two original fighters are CODEX (a sturdy blue
 * terminal-cloud machine whose prompt is its expression, on the left) and CLAUDE (a springy orange octopus with a starburst on its forehead, on the right), about 78 x 77 art pixels
 * each (the picture is 200 x 320, so x4 on the 800 x 1280 panel). They fight best of three rounds, for real: a match state machine (a name-plate intro, ROUND n, FIGHT! with a screen
 * swipe, the fight, K.O. in slow motion with a white impact frame and a punch-in, the winner's pose and taunt, the next round, the winner of the match with fireworks, the stage changes),
 * a small AI that walks, steps in and out, jabs, throws a heavy punch (Codex lunges, Claude slams a tentacle), cracks a tentacle whip from afar (Claude), guards, throws a special with a
 * screen flash, and takes hits: hit-stop, a screen shake along the blow, sparks, slashes and speed lines, dust, a knock-down with a flight and a slide, getting up. Every move eases in
 * and out through in-between frames (made offline by blending poses), so nothing pops. The life bars at the top are the MATCH'S OWN fictional hit points, not quota: this scene never
 * asks the page for its quota and draws no reading of any kind (Tony's rule: only the isometric city, the Game Boy and Neon City's bridge show quota in the picture). It is
 * decoration, calm: nothing in it is activity or trading.
 *
 * The stages change every match (every two to three minutes), all drawn in code over baked layers that follow the REAL clock (the sky, the sun with its shafts, the moon, stars, clouds
 * with lit rims, lamps, lanterns): a HARBOUR in two arrangements (a lighthouse cove with a ferris wheel, or a container quay with a gantry crane that loads a ship), each with weather
 * (clear, a rainbow, a far thunderstorm, streaks of cirrus), an airship and a banner plane, a ferry that crosses with its wake, a sailor band, dancers, a fisherman, a cat, kids, a gull
 * that steals a fish, balloons, bunting and lamps that sway in a wind, signs, a crowd in two tiers that reacts, puddles that hold the sky, and a quay edge over water in front; a
 * LANTERN MARKET (tiled roofs and a tower, shopfronts, four stalls with cooks and neon signs, strings of paper lanterns, steam, sky lanterns, a parade of lantern carriers); and, when it
 * exists in the private atlas, Tony's own jungle backdrop (a private stage the board already used; it only ever lives in the private atlas, never in Git). The camera follows the two
 * fighters over a stage wider than the screen. A touch makes the nearer fighter taunt (or, away from them, the crowd cheers).
 *
 * Files: the engine is stage-game.js. The art (both fighters in every pose and in-between, sparks, slashes, projectiles, fans, actors, props, boats, the optional jungle) is a private
 * atlas made offline by scripts/prepare_game_fighting.py (with scripts/fighting_stage_art.py); the stages, the life bars and the pixel text are drawn here, in code. The frames the scene
 * asks for are listed in FRAMES, FX_FRAMES and ACTOR_FRAMES (the preparation script's tests read those tables). The pure logic (the layout that follows api.view.bottom, the sun, the
 * pixel font, the moves, the match, the AI, the camera) is exported for the Node tests (tests/test_tablet_game_fighting.mjs) and uses only the engine's seeded random, so the same seed
 * is always the same match.
 */
(function (global) {
  'use strict';

  const NAME = 'fighting';
  const SIZE = [200, 320];
  const W = SIZE[0], H = SIZE[1];
  const STEP = 1 / 30;
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (t) => t * t * (3 - 2 * t);
  const sign = (v) => (v < 0 ? -1 : v > 0 ? 1 : 0);

  /* ---- a repeatable random generator (the engine's own mulberry32, so the pure logic needs no engine) */
  function seeded(seed) {
    let a = (seed >>> 0) || 1;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const pick = (rand, list) => list[Math.floor(rand() * list.length) % list.length];
  const between = (rand, lo, hi) => lo + rand() * (hi - lo);
  /** One of `items` ([[value, weight], ...]) by weight. */
  function weighted(rand, items) {
    let total = 0;
    for (const it of items) total += it[1];
    let r = rand() * total;
    for (const it of items) { r -= it[1]; if (r <= 0) return it[0]; }
    return items[items.length - 1][0];
  }

  /* ---- colours */
  function rgb(hex) { const v = parseInt(hex.slice(1), 16); return [(v >> 16) & 255, (v >> 8) & 255, v & 255]; }
  const mixRgb = (a, b, t) => [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t)];
  const mulRgb = (c, tint) => [Math.round(clamp(c[0] * tint[0], 0, 255)), Math.round(clamp(c[1] * tint[1], 0, 255)), Math.round(clamp(c[2] * tint[2], 0, 255))];
  const css = (c, a) => (a === undefined || a >= 1 ? 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')' : 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')');

  /* ---- the layout: where the fighters stand.
   *
   * The page's glass dock hides the lower part of the picture and its date and clock sit at the left just above it (about 70 art rows above `api.view.bottom`), so the fighters'
   * feet are put at the last row above the clock: `feet`. With the whole picture showing (a tap on the clock) they step down to the lower third, and the anchor eases there over a
   * few steps, so nothing jumps. The life bars, the names and the timer sit at the top (below the page's bar), whatever the dock does. */
  const LAYOUT = { feetDock: 112, feetPicture: 208, dockBelow: 190, pictureFrom: 290, minBottom: 104, hudTop: 11, clockRows: 74, feetLeast: 92 };
  function layoutFor(viewBottom) {
    const vb = clamp(Math.round(finite(viewBottom) ? viewBottom : H), LAYOUT.minBottom, H);
    const dock = 1 - smooth(clamp((vb - LAYOUT.dockBelow) / (LAYOUT.pictureFrom - LAYOUT.dockBelow), 0, 1));
    const docked = clamp(vb - LAYOUT.clockRows, LAYOUT.feetLeast, LAYOUT.feetDock);                    // a taller dock than the tablet's lifts the fighters off the clock
    return { feet: Math.round(lerp(LAYOUT.feetPicture, docked, dock)), dock, vb };
  }
  /** One step of easing toward a new feet row: quick at first, never more than `limit` rows a step, exactly on the target at the end. */
  function easeFeet(current, target, rate = 0.3, limit = 9, least = 2) {
    const d = target - current;
    if (Math.abs(d) <= least) return target;
    return Math.round(current + sign(d) * Math.max(least, Math.min(Math.abs(d) * rate, limit)));
  }

  /* ---- the pixel font: 5 x 7, upper case, digits and a little punctuation (a row is a 5-bit number, the left pixel the highest bit) */
  const FONT = {
    A: [14, 17, 17, 31, 17, 17, 17], B: [30, 17, 17, 30, 17, 17, 30], C: [14, 17, 16, 16, 16, 17, 14], D: [30, 17, 17, 17, 17, 17, 30], E: [31, 16, 16, 30, 16, 16, 31],
    F: [31, 16, 16, 30, 16, 16, 16], G: [14, 17, 16, 23, 17, 17, 15], H: [17, 17, 17, 31, 17, 17, 17], I: [14, 4, 4, 4, 4, 4, 14], J: [7, 2, 2, 2, 2, 18, 12],
    K: [17, 18, 20, 24, 20, 18, 17], L: [16, 16, 16, 16, 16, 16, 31], M: [17, 27, 21, 21, 17, 17, 17], N: [17, 17, 25, 21, 19, 17, 17], O: [14, 17, 17, 17, 17, 17, 14],
    P: [30, 17, 17, 30, 16, 16, 16], Q: [14, 17, 17, 17, 21, 18, 13], R: [30, 17, 17, 30, 20, 18, 17], S: [15, 16, 16, 14, 1, 1, 30], T: [31, 4, 4, 4, 4, 4, 4],
    U: [17, 17, 17, 17, 17, 17, 14], V: [17, 17, 17, 17, 17, 10, 4], W: [17, 17, 17, 21, 21, 21, 10], X: [17, 17, 10, 4, 10, 17, 17], Y: [17, 17, 17, 10, 4, 4, 4],
    Z: [31, 1, 2, 4, 8, 16, 31], 0: [14, 17, 19, 21, 25, 17, 14], 1: [4, 12, 4, 4, 4, 4, 14], 2: [14, 17, 1, 2, 4, 8, 31], 3: [30, 1, 1, 14, 1, 1, 30],
    4: [2, 6, 10, 18, 31, 2, 2], 5: [31, 16, 30, 1, 1, 17, 14], 6: [6, 8, 16, 30, 17, 17, 14], 7: [31, 1, 2, 4, 8, 8, 8], 8: [14, 17, 17, 14, 17, 17, 14],
    9: [14, 17, 17, 15, 1, 2, 12], '!': [4, 4, 4, 4, 4, 0, 4], '.': [0, 0, 0, 0, 0, 12, 12], '-': [0, 0, 0, 31, 0, 0, 0], ' ': [0, 0, 0, 0, 0, 0, 0],
  };
  const GLYPH_W = 5, GLYPH_H = 7, GAP = 1;
  /** The lit pixels of a text at scale 1: {width, height, pixels: [[x, y], ...]}. Unknown characters are skipped. */
  function textPixels(text) {
    const pixels = [];
    let x = 0;
    for (const raw of String(text).toUpperCase()) {
      const rows = FONT[raw];
      if (!rows) continue;
      for (let y = 0; y < GLYPH_H; y++) for (let k = 0; k < GLYPH_W; k++) if (rows[y] & (1 << (GLYPH_W - 1 - k))) pixels.push([x + k, y]);
      x += GLYPH_W + GAP;
    }
    return { width: Math.max(0, x - GAP), height: GLYPH_H, pixels };
  }

  /* ---- the day: the sun at a reference location and what the harbour looks like at that altitude */
  const LAT = 40.4, LON = -3.7, RAD = Math.PI / 180;
  function dayOfYear(date) {
    return Math.round((Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) - Date.UTC(date.getFullYear(), 0, 0)) / 86400000);
  }
  /** The sun's altitude (degrees) and whether it is before solar noon, for a Date in its own time zone. */
  function sunState(date, lat = LAT, lon = LON) {
    const doy = dayOfYear(date);
    const decl = 23.44 * Math.sin(2 * Math.PI * (284 + doy) / 365) * RAD;
    const b = 2 * Math.PI * (doy - 81) / 364;
    const equation = 9.87 * Math.sin(2 * b) - 7.53 * Math.cos(b) - 1.5 * Math.sin(b);
    const clockHours = date.getHours() + date.getMinutes() / 60 + date.getSeconds() / 3600 + date.getMilliseconds() / 3600000;
    const zone = -date.getTimezoneOffset() / 60;
    const solar = clockHours - zone + lon / 15 + equation / 60;
    const sinAlt = Math.sin(lat * RAD) * Math.sin(decl) + Math.cos(lat * RAD) * Math.cos(decl) * Math.cos(15 * (solar - 12) * RAD);
    return { alt: Math.asin(clamp(sinAlt, -1, 1)) / RAD, morning: solar < 12, solar };
  }
  /** Keyframes by sun altitude: six sky bands from the zenith down, the tint that lights everything else, the haze the far things fade into, the sun's colour and size, the stars and the lamps. */
  const KEYS = [
    { alt: -16, sky: ['#02061a', '#040a24', '#07123a', '#0b1c50', '#122a62', '#1a3a72'], tint: [.40, .46, .72], haze: '#1c3a6c', sun: '#ff9a4a', r: 12, stars: 1, lamps: 1 },
    { alt: -9, sky: ['#0a1240', '#141c5a', '#2a2a74', '#4d3382', '#7a3a80', '#b04a78'], tint: [.52, .52, .76], haze: '#8a4a7a', sun: '#ff8a4a', r: 12, stars: .75, lamps: 1 },
    { alt: -4, sky: ['#1a2a78', '#3a3a90', '#7a4690', '#c0507e', '#ee7058', '#ffa05a'], tint: [.84, .66, .72], haze: '#f08a6a', sun: '#ff7a3a', r: 14, stars: .2, lamps: .8 },
    { alt: 0, sky: ['#2c4a9c', '#4d5ca8', '#9a6aa0', '#e8806a', '#ff9a52', '#ffc070'], tint: [1.0, .82, .68], haze: '#ffb078', sun: '#ff8a3a', r: 14, stars: 0, lamps: .5 },
    { alt: 5, sky: ['#2f64b8', '#4d82cc', '#86a6d4', '#e8b88a', '#ffc47e', '#ffdca0'], tint: [1.0, .91, .76], haze: '#ffd8a0', sun: '#ffc860', r: 11, stars: 0, lamps: .1 },
    { alt: 14, sky: ['#1c62c6', '#2c80dc', '#4f9de6', '#7cc0ee', '#a9d9f0', '#d8e8d8'], tint: [1.0, .96, .88], haze: '#d0e4dc', sun: '#fff0a8', r: 8, stars: 0, lamps: 0 },
    { alt: 30, sky: ['#075bd1', '#087de8', '#159cf0', '#53c3f4', '#8fd9f2', '#bedfe3'], tint: [1, 1, 1], haze: '#bedfe3', sun: '#fff6c8', r: 6, stars: 0, lamps: 0 },
  ];
  const KEY_RGB = KEYS.map((k) => ({ alt: k.alt, sky: k.sky.map(rgb), tint: k.tint, haze: rgb(k.haze), sun: rgb(k.sun), r: k.r, stars: k.stars, lamps: k.lamps }));
  function lightAt(alt) {
    const keys = KEY_RGB;
    if (alt <= keys[0].alt) return Object.assign({}, keys[0], { alt });
    if (alt >= keys[keys.length - 1].alt) return Object.assign({}, keys[keys.length - 1], { alt });
    let i = 0;
    while (alt > keys[i + 1].alt) i++;
    const a = keys[i], b = keys[i + 1], t = smooth((alt - a.alt) / (b.alt - a.alt));
    return { alt, sky: a.sky.map((c, k) => mixRgb(c, b.sky[k], t)), tint: a.tint.map((v, k) => lerp(v, b.tint[k], t)), haze: mixRgb(a.haze, b.haze, t), sun: mixRgb(a.sun, b.sun, t),
      r: Math.round(lerp(a.r, b.r, t)), stars: lerp(a.stars, b.stars, t), lamps: lerp(a.lamps, b.lamps, t) };
  }
  function phaseName(alt) { return alt >= 15 ? 'day' : alt >= 4 ? 'golden' : alt >= -2 ? 'dusk' : alt >= -10 ? 'twilight' : 'night'; }
  /** Where the sun is in the sky: it climbs on the right in the morning and sets on the left in the evening, low over the sea at dusk. */
  function sunPlace(alt, morning, horizon) {
    const progress = clamp(1 - Math.max(0, alt) / 60, 0, 1);
    return { x: Math.round(W / 2 + (morning ? 1 : -1) * (30 + 46 * progress * progress)), y: Math.round(horizon - 6 - (1 - progress) * Math.max(10, horizon - 34)) };
  }
  function moonPlace(solar, horizon) {
    const night = solar >= 12 ? solar - 18 : solar + 6, t = clamp(night / 12, 0, 1);
    return { x: Math.round(172 - 140 * t), y: Math.round(Math.max(18, horizon * (0.18 + 0.2 * Math.abs(t - 0.5) * 2))) };
  }

  /* ---- the frames the scene asks of the atlas: how many frames each move of each fighter has (scripts/prepare_game_fighting.py draws exactly these) */
  const FRAMES = {
    codex: { idle: 4, walk: 6, guard: 2, jab: 4, heavy: 5, special: 6, hit: 2, hurt: 2, kd: 5, getup: 3, win: 3, taunt: 3 },
    claude: { idle: 4, blink: 1, walk: 6, guard: 2, jab: 4, heavy: 5, whip: 6, special: 6, hit: 2, hurt: 2, kd: 5, getup: 3, win: 3, taunt: 3 },
  };
  /* the in-between frames (`<who>-tw-<name>`): a move eases in from the idle pose and out to it, a hit and a getting up ease out, a guard and a taunt ease in and out */
  const TWEEN_NAMES = {
    codex: ['jab-in', 'jab-out', 'heavy-in', 'heavy-out', 'special-in', 'special-out', 'guard-in', 'guard-out', 'hit-out', 'getup-out', 'taunt-in', 'win-in'],
    claude: ['jab-in', 'jab-out', 'heavy-in', 'heavy-out', 'whip-in', 'special-in', 'special-out', 'guard-in', 'guard-out', 'hit-out', 'getup-out', 'taunt-in', 'win-in', 'whip-out'],
  };
  const FX_FRAMES = { spark: 4, impact: 5, flash: 6, block: 4, dust: 5, ring: 5, stars: 4, glint: 4, slash: 3, streak: 3, note: 2, steam: 4, splash: 4 };
  /* the stages' little actors and props (`act-<kind>-<k>`) */
  const ACTOR_FRAMES = { drummer: 2, horn: 2, accordion: 2, bandstand: 1, dancers: 4, fisher: 4, fish: 2, cat: 7, kids: 3, 'flag-codex': 2, 'flag-claude': 2, balloon: 3, cont: 4, ferry: 2, tug: 2, blimp: 2, plane: 2, buoy: 2,
    lantern: 8, skylantern: 2, stall: 4, noodle: 3, grill: 2, 'carrier-bot': 4, 'carrier-octo': 4 };
  const CROWD_KINDS = ['bot-teal', 'bot-pink', 'octo-violet', 'octo-green', 'bot-sailor', 'octo-cap', 'bot-hard'];
  const CROWD_POSES = ['idle0', 'idle1', 'cheer0', 'cheer1', 'gasp'];

  /* ---- the moves. Frames are indices into the atlas animations of a fighter (`codex-jab-2`); `steps` is how long each is shown (30 Hz); `hit` is the index of the frame on
   *      which the blow lands (the art's fist is at its farthest there); `reach` is how far the fist or tentacle is from the fighter's middle on that frame (the preparation script
   *      draws exactly that: its tests compare); a fist that gets past the other's body surface (BODY from its middle) connects. */
  const BODY = 27;
  const ARENA = { left: 48, right: 272, width: 320 };
  const MIN_GAP = 54;
  const MAX_GAP = 128;           // two fighters walk no farther apart than this: the camera (200 wide) keeps both in view
  const MOVES = {
    codex: {
      jab: { anim: 'jab', seq: ['tw-jab-in', 0, 1, 2, 3, 'tw-jab-out'], steps: [2, 2, 2, 3, 3, 3], hit: 3, reach: 72, damage: 6, chip: 1, stun: 11, blockStun: 8, push: 9, stop: 3, spark: 'spark' },
      heavy: { anim: 'heavy', seq: ['tw-heavy-in', 0, 1, 2, 3, 4, 'tw-heavy-out'], steps: [2, 3, 4, 3, 4, 5, 3], hit: 4, reach: 87, damage: 14, chip: 2, stun: 17, blockStun: 11, push: 18, stop: 6, spark: 'impact', knock: 0.3, lunge: [0, 0, 0, 3, 2, 0, 0] },
      special: { anim: 'special', seq: ['tw-special-in', 0, 1, 2, 3, 4, 5, 'tw-special-out'], steps: [2, 4, 5, 7, 3, 5, 6, 3], fire: 4, damage: 20, chip: 2, speed: 3.2, y: 44, cost: 100, dim: 3 },
    },
    claude: {
      jab: { anim: 'jab', seq: ['tw-jab-in', 0, 1, 2, 3, 'tw-jab-out'], steps: [2, 2, 2, 3, 2, 1], hit: 3, reach: 83, damage: 5, chip: 1, stun: 11, blockStun: 8, push: 9, stop: 3, spark: 'spark' },
      heavy: { anim: 'heavy', seq: ['tw-heavy-in', 0, 1, 2, 3, 4, 'tw-heavy-out'], steps: [2, 4, 4, 3, 4, 4, 2], hit: 4, reach: 91, damage: 11, chip: 2, stun: 17, blockStun: 11, push: 16, stop: 6, spark: 'impact', knock: 0.3 },
      whip: { anim: 'whip', seq: ['tw-whip-in', 0, 1, 2, 3, 4, 5, 'tw-whip-out'], steps: [2, 3, 3, 3, 3, 3, 8, 2], hit: 4, reach: 128, damage: 8, chip: 1, stun: 14, blockStun: 9, push: 12, stop: 5, spark: 'impact' },
      special: { anim: 'special', seq: ['tw-special-in', 0, 1, 2, 3, 4, 5, 'tw-special-out'], steps: [2, 4, 5, 6, 3, 5, 6, 3], fire: 4, damage: 20, chip: 2, speed: 2.8, y: 40, cost: 100, dim: 3 },
    },
  };
  const STATS = { codex: { speed: 1.0, back: 0.66, armor: 0.85, idleSteps: 5 }, claude: { speed: 1.05, back: 0.74, armor: 1.0, idleSteps: 4 } };
  const IDLE_SEQ = [0, 1, 2, 3, 2, 1];
  const ROUND_SECONDS = 60, WINS_NEEDED = 2;
  const KO_SLOW = 3;
  const FIREWORK_COLOURS = ['#ffd23a', '#ff7a3a', '#7ad0ff', '#ff6ab0', '#a8ff7a'];

  const sum = (list) => list.reduce((a, b) => a + b, 0);
  const moveSteps = (mv) => sum(mv.steps);
  const lungeDistance = (mv) => (mv.lunge ? mv.lunge.reduce((a, v, i) => a + v * mv.steps[i], 0) : 0);
  /** The distance between two middles at which the move's blow lands, counting the lunge that comes before it. */
  const strikeRange = (mv) => mv.reach + BODY + (mv.lunge ? mv.lunge.reduce((a, v, i) => a + (i < mv.hit ? v * mv.steps[i] : 0), 0) : 0);

  /* ---- a fighter */
  function play(f, anim, seq, steps, loop, loopFrom) { f.anim = anim; f.seq = seq; f.steps = steps; f.si = 0; f.st = 0; f.loop = !!loop; f.loopFrom = loopFrom || 0; f.done = false; }
  /** One step of the animation clock. Returns true on the step a sequence that does not loop has run out (it then stays on its last frame). */
  function tickAnim(f) {
    if (f.done) return false;
    f.st++;
    if (f.st >= f.steps[f.si]) {
      f.st = 0;
      f.si++;
      if (f.si >= f.seq.length) {
        if (f.loop) f.si = f.loopFrom || 0; else { f.si = f.seq.length - 1; f.done = true; return true; }
      }
    }
    return false;
  }
  /** The atlas frame a fighter shows: `codex-jab-2`, or, when the sequence names an in-between frame as a string, `codex-tw-jab-in`. */
  const frameName = (f) => { const e = f.seq[f.si]; return f.id + '-' + (typeof e === 'string' ? e : f.anim + '-' + e); };
  const free = (f) => f.state === 'idle' || f.state === 'walk';
  const hittable = (f) => f.state !== 'kd' && f.state !== 'getup' && f.state !== 'win' && f.state !== 'intro' && f.invuln <= 0;

  function createFighter(id, x) {
    const f = { id, dir: id === 'codex' ? 1 : -1, x, vx: 0, hp: 100, ghost: 100, ghostT: 0, meter: 0, wins: 0, state: 'idle', anim: 'idle', seq: [0], steps: [1], si: 0, st: 0, loop: true, done: false,
      move: null, moveName: '', hitDone: false, fired: false, stun: 0, think: 20, walk: 0, walkT: 0, guardT: 0, blinkT: 80, blinking: 0, combo: 0, invuln: 0, ko: false, mood: { aggr: 1, skill: 0.5 }, lastHit: 0, flashT: 0, loopFrom: 0, winTaunt: false };
    toIdle(f);
    return f;
  }
  /** Back to standing; `via` names an in-between frame that eases out of the pose it came from (shown for two steps, then the idle breathing loops without it). */
  function toIdle(f, via) {
    f.state = 'idle'; f.move = null; f.moveName = ''; f.walk = 0; f.stun = 0; f.guardT = 0; f.winTaunt = false;
    const n = STATS[f.id].idleSteps;
    if (via) play(f, 'idle', [via].concat(IDLE_SEQ), [2].concat(IDLE_SEQ.map(() => n)), true, 1);
    else play(f, 'idle', IDLE_SEQ.slice(), IDLE_SEQ.map(() => n), true);
  }
  function toWalk(f, toward, steps) {
    f.state = 'walk'; f.walk = toward; f.walkT = steps;
    if (f.anim !== 'walk') play(f, 'walk', [0, 1, 2, 3, 4, 5], [4, 4, 4, 4, 4, 4], true);
  }
  function toGuard(f, steps) {
    if (f.state === 'guard') { f.guardT = Math.max(f.guardT, steps); return; }
    f.state = 'guard'; f.guardT = steps; f.move = null; f.walk = 0;
    play(f, 'guard', ['tw-guard-in', 0, 1], [2, 3, 9999], false);
  }
  function toAttack(f, name) {
    const mv = MOVES[f.id][name];
    f.state = 'attack'; f.move = mv; f.moveName = name; f.hitDone = false; f.fired = false; f.walk = 0;
    play(f, mv.anim, mv.seq.slice(), mv.steps.slice(), false);
  }
  function toHit(f, stun, heavy) {
    f.state = 'hit'; f.stun = stun; f.move = null; f.walk = 0;
    const first = Math.max(2, Math.ceil(stun * 0.6));
    play(f, heavy ? 'hurt' : 'hit', [0, 1], [first, 9999], false);
  }
  function toKnock(f, ko) {
    f.state = 'kd'; f.move = null; f.walk = 0; f.ko = !!ko;
    play(f, 'kd', [0, 1, 2, 3, 4], [4, 4, 4, 3, ko ? 99999 : 26], false);
  }
  function toGetUp(f) {
    f.state = 'getup'; f.invuln = 22;
    play(f, 'getup', [0, 1, 2], [6, 5, 5], false);
  }
  function toWin(f) {
    f.state = 'win'; f.move = null; f.walk = 0; f.vx = 0;
    play(f, 'win', ['tw-win-in', 0, 1, 2, 1], [3, 8, 6, 8, 6], true, 1);
  }
  function toTaunt(f) {
    f.state = 'taunt'; f.move = null; f.walk = 0;
    play(f, 'taunt', ['tw-taunt-in', 0, 1, 2, 1, 0], [2, 4, 5, 5, 5, 4], false);
  }
  const moveBy = (f, dx) => { f.x = clamp(f.x + dx, ARENA.left, ARENA.right); };

  /* ---- the match: rounds, the fight, the AI, hits, projectiles, effects, the camera. `step()` is one 30 Hz tick; everything is driven by the seeded random. */
  function createMatch(options) {
    const o = Object.assign({ seed: 20261110, random: null, rounds: WINS_NEEDED, roundSeconds: ROUND_SECONDS }, options);
    const rand = typeof o.random === 'function' ? o.random : seeded(o.seed);
    const m = { rand, opts: o, steps: 0, time: 0, phase: 'intro', phaseT: 0, round: 1, clock: o.roundSeconds, clockT: 0, text: null, winner: null, matchWinner: null, hitstop: 0, shake: 0, shakeMax: 1, shakeAmp: 0,
      flash: 0, dim: 0, dimTarget: 0, slow: 1, fade: 0, fadeDir: 0, camX: 60, camKick: 0, camBias: 0, pushV: 0, shakeDir: 1, koAt: -1, hitGlow: null, cues: [], fx: [], sparks: [], proj: [], events: [], crowd: { mood: 'idle', t: 0 }, sinceHit: 0, matches: 1,
      stats: { hits: 0, blocks: 0, knockdowns: 0, rounds: 0, matches: 1, specials: 0, whips: 0, taunts: 0, timeups: 0, kos: 0, wins: { codex: 0, claude: 0 }, roundSteps: [] }, f: [createFighter('codex', 100), createFighter('claude', 220)] };
    const [codex, claude] = m.f;
    const other = (f) => (f === codex ? claude : codex);
    m.other = other;

    function addFx(kind, x, y, extra) {
      const frames = FX_FRAMES[kind] || 1;
      const e = Object.assign({ kind, x, y, t: 0, rate: kind === 'dust' ? 3 : kind === 'stars' ? 4 : 2, frames, vx: 0, vy: 0, loop: false, life: 0 }, extra);
      if (!e.life) e.life = e.loop ? 60 : e.rate * frames;
      if (m.fx.length < 28) m.fx.push(e);
      return e;
    }
    m.addFx = addFx;
    /** A thing that happened, for the scene's stage to react to (the crowd, the sky, the cat): it empties the list, and the match never waits for it. */
    const cue = (type, extra) => { if (m.cues.length < 64) m.cues.push(Object.assign({ type, at: m.steps }, extra)); };
    m.cue = cue;
    const crowdMood = (mood, steps) => { if (mood === 'cheer' || m.crowd.mood !== 'cheer' || m.crowd.t <= 0) { m.crowd.mood = mood; m.crowd.t = steps; } };

    function startRound() {
      m.phase = 'intro'; m.phaseT = 0; m.clock = o.roundSeconds; m.clockT = 0; m.slow = 1; m.winner = null; m.text = { kind: 'round', n: m.round }; m.sinceHit = 0;
      m.proj.length = 0; m.fx.length = 0; m.sparks.length = 0; m.hitstop = 0; m.flash = 0; m.dim = 0; m.dimTarget = 0; m.roundStartStep = m.steps; m.koAt = -1; m.camKick = 0; m.hitGlow = null;
      cue('round', { n: m.round, first: m.round === 1 });
      for (const f of m.f) {
        f.x = f.id === 'codex' ? 100 : 220; f.vx = 0; f.hp = 100; f.ghost = 100; f.ghostT = 0; f.invuln = 0; f.ko = false; f.combo = 0; f.flashT = 0; f.winTaunt = false; f.meter = Math.min(f.meter, 40);
        f.mood = { aggr: between(rand, 0.85, 1.3), skill: between(rand, 0.28, 0.75) };
        f.think = 30 + Math.floor(rand() * 20); f.state = 'idle'; toIdle(f);
      }
      m.crowd.mood = 'idle'; m.crowd.t = 0;
    }
    function newMatch() {
      m.round = 1; m.matches++; m.stats.matches++; m.matchWinner = null;
      for (const f of m.f) { f.wins = 0; f.meter = 0; }
      startRound();
    }

    /* what a blow does: a hit or a block, the damage, the sparks, the hit-stop, the push and the fall */
    function contactPoint(att, def) { return { x: def.x - att.dir * (BODY - 4), y: 44 + Math.floor(rand() * 16) - 6 }; }
    function applyDamage(def, amount) {
      def.hp = Math.max(0, def.hp - amount);
      def.ghostT = 24;
    }
    function land(att, def, mv, kind) {
      const blocked = def.state === 'guard';
      const p = contactPoint(att, def);
      m.sinceHit = 0;
      if (blocked) {
        m.stats.blocks++;
        applyDamage(def, mv.chip * (def.hp > mv.chip ? 1 : 0));
        def.guardT = Math.max(def.guardT, mv.blockStun || 8);
        def.vx = att.dir * 1.2; att.vx = -att.dir * 0.8;
        addFx('block', p.x, p.y);
        m.hitstop = Math.max(m.hitstop, 2); cue('block');
        att.meter = Math.min(100, att.meter + 3); def.meter = Math.min(100, def.meter + 2);
        return;
      }
      m.stats.hits++;
      const heavy = kind === 'heavy' || kind === 'whip' || kind === 'special';
      const amount = Math.max(1, Math.round(mv.damage * STATS[def.id].armor));
      applyDamage(def, amount);
      att.meter = Math.min(100, att.meter + 9 + (heavy ? 4 : 0)); def.meter = Math.min(100, def.meter + 6);
      def.lastHit = m.steps;
      addFx(kind === 'special' ? 'flash' : heavy ? 'impact' : 'spark', p.x, p.y);
      if (heavy) { addFx('ring', def.x - att.dir * 6, 6, { rate: 2 }); addFx('streak', p.x, p.y, { rate: 2 }); }
      if (kind === 'whip' || kind === 'heavy') addFx('slash', att.x + att.dir * (kind === 'whip' ? 44 : 30), p.y, { rate: 2, flip: att.dir < 0 });
      def.flashT = heavy ? 3 : 2; m.hitGlow = { x: p.x, y: p.y, t: heavy ? 3 : 2 }; m.camKick = -att.dir * (heavy ? 3 : 1.5); m.shakeDir = att.dir;
      cue('hit', { heavy, kind, x: def.x });
      m.hitstop = Math.max(m.hitstop, mv.stop || (kind === 'special' ? 10 : 4));
      m.shake = heavy ? 8 : 4; m.shakeMax = m.shake; m.shakeAmp = kind === 'special' ? 3 : heavy ? 2 : 1;
      if (heavy) crowdMood('gasp', 16);
      def.vx = att.dir * ((mv.push || 8) * 0.18);
      def.combo = def.state === 'hit' ? def.combo + 1 : 1;
      if (def.hp <= 0) { knockOut(att, def); return; }
      const knock = kind === 'special' || (mv.knock && rand() < mv.knock) || def.combo >= 3;
      if (knock) { m.stats.knockdowns++; def.vx = att.dir * 3.4; toKnock(def, false); addFx('dust', def.x, 2); crowdMood('gasp', 18); return; }
      toHit(def, mv.stun, heavy);
    }
    function knockOut(att, def) {
      m.stats.knockdowns++;
      def.hp = 0; def.vx = att.dir * 3.6; toKnock(def, true);
      m.stats.kos++;
      m.phase = 'ko'; m.phaseT = 0; m.slow = KO_SLOW; m.winner = att; m.text = { kind: 'ko' }; m.flash = 6; m.shake = 14; m.shakeMax = 14; m.shakeAmp = 3; m.hitstop = Math.max(m.hitstop, 12);
      addFx('flash', def.x - att.dir * 10, 46); addFx('streak', def.x - att.dir * 10, 46, { rate: 3 }); crowdMood('cheer', 90);
      m.koAt = m.steps; def.flashT = 4; m.camKick = -att.dir * 5; m.shakeDir = att.dir; cue('ko', { who: att.id });
      m.proj.length = 0;
    }
    m.land = land;

    /* the AI: what a free fighter does next */
    function decide(f) {
      const o2 = other(f), dist = Math.abs(f.x - o2.x), mv = MOVES[f.id], aggr = f.mood.aggr * (m.sinceHit > 150 ? 1.5 : 1);
      const toward = sign(o2.x - f.x);
      const down = !hittable(o2) && o2.state !== 'attack';
      const options = [];
      const canSpecial = f.meter >= mv.special.cost && !m.proj.some((p) => p.owner === f);
      if (canSpecial && dist > 70 && dist < 200 && !down) options.push(['special', 3.2 * aggr]);
      if (!down) {
        if (dist <= strikeRange(mv.jab) - 8) options.push(['jab', 4.2 * aggr]);
        if (dist <= strikeRange(mv.heavy) - 8 && dist >= 60) options.push(['heavy', 2.8 * aggr]);
        if (mv.whip && dist <= strikeRange(mv.whip) - 10 && dist > strikeRange(mv.jab) - 10) options.push(['whip', 4.6 * aggr]);
      }
      options.push(['guard', down ? 0 : dist < 130 ? 1.5 * (1.2 - f.mood.aggr * 0.4) + 0.3 : 0.2]);
      options.push(['approach', dist > 118 ? 5.5 : dist > 92 ? 2.6 * aggr : 0.9 * aggr]);
      options.push(['retreat', dist < 80 ? 1.8 : dist < 100 ? 0.5 : 0.1]);
      options.push(['wait', 1.1]);
      if (down || m.sinceHit > 200) options.push(['taunt', down ? 0.6 : 0.15]);
      const choice = weighted(rand, options);
      if (choice === 'jab' || choice === 'heavy' || choice === 'whip') toAttack(f, choice);
      else if (choice === 'special') { toAttack(f, 'special'); m.stats.specials++; }
      else if (choice === 'guard') toGuard(f, 14 + Math.floor(rand() * 14));
      else if (choice === 'approach') toWalk(f, toward, 10 + Math.floor(rand() * 22));
      else if (choice === 'retreat') toWalk(f, -toward, 8 + Math.floor(rand() * 14));
      else if (choice === 'taunt') { toTaunt(f); m.stats.taunts++; }
      else f.think = 8 + Math.floor(rand() * 12);
      if (choice === 'whip') m.stats.whips++;
      return choice;
    }
    m.decide = decide;

    /* a free fighter sees a blow coming and may put its guard up */
    function react(f) {
      const o2 = other(f), dist = Math.abs(f.x - o2.x);
      if (o2.state === 'attack' && o2.move && o2.si < o2.move.hit && o2.move.reach && dist <= strikeRange(o2.move) + 6 && rand() < f.mood.skill * 0.14) { toGuard(f, 18 + Math.floor(rand() * 8)); return true; }
      for (const p of m.proj) {
        if (p.owner !== f && Math.abs(p.x - f.x) < 46 && Math.abs(p.x - f.x) > 16 && sign(f.x - p.x) === p.dir && rand() < f.mood.skill * 0.12) { toGuard(f, 22); return true; }
      }
      return false;
    }

    function fighterStep(f) {
      const o2 = other(f);
      if (f.invuln > 0) f.invuln--;
      if (Math.abs(f.vx) > 0.05) { moveBy(f, f.vx); f.vx *= 0.82; } else f.vx = 0;
      if (f.ghostT > 0) f.ghostT--; else if (f.ghost > f.hp) f.ghost = Math.max(f.hp, f.ghost - 0.7);
      const fighting = m.phase === 'fight';
      if (f.id === 'claude') { f.blinkT--; if (f.blinkT <= 0) { f.blinkT = 70 + Math.floor(rand() * 110); f.blinking = 3; } if (f.blinking > 0) f.blinking--; }
      switch (f.state) {
        case 'idle': case 'walk':
          if (!fighting) break;
          if (react(f)) break;
          if (f.state === 'walk') {
            const away = f.walk !== sign(o2.x - f.x);
            if (!away || Math.abs(f.x - o2.x) < MAX_GAP) moveBy(f, f.walk * (away ? STATS[f.id].back : STATS[f.id].speed));
            else f.walkT = 0;
            f.walkT--;
            const stopAt = Math.abs(f.x - o2.x) <= MIN_GAP + 18;
            if (f.walkT <= 0 || (f.walk === sign(o2.x - f.x) && stopAt)) { toIdle(f); f.think = 2 + Math.floor(rand() * 6); }
          } else if (--f.think <= 0) { decide(f); }
          break;
        case 'guard':
          if (f.guardT > 0) f.guardT--; else { toIdle(f, 'tw-guard-out'); f.think = 6 + Math.floor(rand() * 10); }
          break;
        case 'hit':
          if (--f.stun <= 0) { toIdle(f, 'tw-hit-out'); f.think = 5 + Math.floor(rand() * 8); f.combo = 0; }
          break;
        case 'attack': {
          const mv = f.move;
          if (mv.lunge && mv.lunge[f.si]) moveBy(f, f.dir * mv.lunge[f.si]);
          break;
        }
        default: break;
      }
      const ended = tickAnim(f);
      if (f.state === 'kd' && f.si === 3 && f.st === 0) { addFx('dust', f.x - 12, 2); addFx('dust', f.x + 14, 2, { rate: 2 }); addFx('ring', f.x, 5, { rate: 2 }); m.shake = Math.max(m.shake, 4); m.shakeMax = Math.max(m.shakeMax, 4); m.shakeAmp = Math.max(m.shakeAmp, 1); }
      if (f.state === 'attack' && f.moveName === 'special' && f.si <= f.move.dim && f.st % 2 === 0) addFx('glint', f.x + (rand() - 0.5) * 70, 14 + rand() * 70, { rate: 3 });
      if (f.state === 'attack' && f.move) {
        const mv = f.move;
        if (mv.fire !== undefined && f.si === mv.fire && f.st === 0 && !f.fired) { f.fired = true; fire(f, mv); }
        if (mv.hit !== undefined && f.si === mv.hit && f.st === 0 && !f.hitDone) {
          f.hitDone = true;
          if (Math.abs(f.x - o2.x) <= mv.reach + BODY && (hittable(o2) || o2.state === 'hit' && o2.combo < 2) && o2.state !== 'kd') land(f, o2, mv, f.moveName);
        }
        if (ended) { toIdle(f); f.think = Math.floor((8 + rand() * 16) / f.mood.aggr); }
      } else if (ended) {
        if (f.state === 'kd' && !f.ko) toGetUp(f);
        else if (f.state === 'getup') { toIdle(f, 'tw-getup-out'); f.think = 6; }
        else if (f.state === 'taunt') { toIdle(f); f.think = 6 + Math.floor(rand() * 10); }
        else if (f.state === 'win' && f.winTaunt) { f.winTaunt = false; toWin(f); }
      }
    }

    /* projectiles: a burst of prompt chevrons from Codex, a spinning starburst from Claude */
    function fire(f, mv) {
      if (m.proj.some((p) => p.owner === f)) return;
      f.meter = 0;
      m.proj.push({ owner: f, kind: f.id, x: f.x + f.dir * 58, y: mv.y, dir: f.dir, speed: mv.speed, damage: mv.damage, chip: mv.chip, t: 0 });
      m.flash = 4; m.shake = 8; m.shakeMax = 8; m.shakeAmp = 2; m.shakeDir = f.dir; crowdMood('cheer', 30); cue('special', { who: f.id });
      addFx('dust', f.x - f.dir * 14, 2); addFx('glint', f.x + f.dir * 52, mv.y + 8);
    }
    function projectileStep() {
      const dead = new Set();
      for (const p of m.proj.slice()) {
        if (dead.has(p)) continue;
        const o2 = other(p.owner);
        p.x += p.dir * p.speed; p.t++;
        if (p.t % 3 === 0 && m.fx.length < 24) addFx('glint', p.x - p.dir * 10, p.y + (p.t % 2 ? 4 : -4), { rate: 2 });
        let gone = p.x < -20 || p.x > ARENA.width + 20;
        for (const q of m.proj) {
          if (q !== p && !dead.has(q) && q.dir !== p.dir && Math.abs(q.x - p.x) < 12) {              // two bursts meet in the middle and both go out
            addFx('flash', (p.x + q.x) / 2, p.y); m.shake = 6; m.shakeMax = 6; m.shakeAmp = 1; dead.add(q); gone = true;
            break;
          }
        }
        if (!gone && Math.abs(p.x - o2.x) <= BODY + 4 && o2.state !== 'kd' && o2.state !== 'getup' && o2.state !== 'win' && o2.invuln <= 0) {
          land(p.owner, o2, { damage: p.damage, chip: p.chip, push: 24, stop: 10, stun: 22, blockStun: 10, knock: 1 }, 'special');
          gone = true;
        }
        if (gone) dead.add(p);
      }
      if (dead.size) m.proj = m.proj.filter((p) => !dead.has(p));
    }

    function separate() {
      const a = codex, b = claude;
      const standing = (f) => f.state !== 'kd' && f.state !== 'getup';
      if (!standing(a) || !standing(b)) return;
      const gap = b.x - a.x;
      if (gap >= MIN_GAP) return;
      const push = (MIN_GAP - gap) / 2;
      const aRoom = a.x - ARENA.left, bRoom = ARENA.right - b.x;
      const da = Math.min(push + Math.max(0, push - bRoom), Math.max(0, aRoom)), db = Math.min(push + Math.max(0, push - aRoom), Math.max(0, bRoom));
      a.x -= da; b.x += db;
    }

    function endRound() {
      const w = m.winner;
      w.wins++; m.stats.rounds++; m.stats.wins[w.id]++; m.stats.roundSteps.push(m.steps - (m.roundStartStep || 0));
      m.phase = 'win'; m.phaseT = 0; m.slow = 1; m.text = { kind: 'win', who: w.id };
      toWin(w); w.vx = 0; cue('win', { who: w.id });
      const l = other(w);
      if (l.state !== 'kd') { l.state = 'kd'; toKnock(l, true); }
      crowdMood('cheer', 100);
    }
    function phaseStep() {
      m.phaseT++;
      switch (m.phase) {
        case 'intro': if (m.phaseT >= 64) { m.phase = 'ready'; m.phaseT = 0; m.text = { kind: 'fight' }; crowdMood('cheer', 26); cue('fight'); } break;
        case 'ready': if (m.phaseT >= 36) { m.phase = 'fight'; m.phaseT = 0; m.text = null; } break;
        case 'fight':
          m.sinceHit++;
          if (++m.clockT >= 30) { m.clockT = 0; if (--m.clock <= 0) { m.clock = 0; m.phase = 'timeup'; m.phaseT = 0; m.text = { kind: 'timeup' }; m.stats.timeups++; } }
          break;
        case 'timeup':
          if (m.phaseT >= 40) {
            let w = codex.hp > claude.hp ? codex : claude.hp > codex.hp ? claude : (codex.meter !== claude.meter ? (codex.meter > claude.meter ? codex : claude) : (rand() < 0.5 ? codex : claude));
            m.winner = w; endRound();
          }
          break;
        case 'ko': if (m.phaseT >= 22) endRound(); break;
        case 'win':
          if (m.phaseT === 42 && m.winner && m.winner.state === 'win' && !m.winner.winTaunt) { const w = m.winner; w.winTaunt = true; m.stats.taunts++; play(w, 'taunt', ['tw-taunt-in', 0, 1, 2, 1, 0], [2, 4, 5, 5, 5, 4], false); }
          if (m.phaseT >= 90) {
            if (m.winner.wins >= o.rounds) { m.matchWinner = m.winner; m.phase = 'matchend'; m.phaseT = 0; m.text = { kind: 'match', who: m.winner.id }; crowdMood('cheer', 140); cue('matchend', { who: m.winner.id }); }
            else { m.round++; startRound(); }
          }
          break;
        case 'matchend': if (m.phaseT >= 120) { m.phase = 'fadeout'; m.phaseT = 0; m.fadeDir = 1; } break;
        case 'fadeout': if (m.phaseT >= 24) { m.events.push({ type: 'stage', at: m.steps }); newMatch(); m.phase = 'fadein'; m.phaseT = 0; m.fadeDir = -1; m.fade = 1; m.text = { kind: 'round', n: 1 }; } break;
        case 'fadein': if (m.phaseT >= 20) { m.phase = 'intro'; m.phaseT = 30; m.fadeDir = 0; m.fade = 0; } break;
        default: break;
      }
    }

    /** A firework over the harbour when a match is won: a ring of embers that fly out and fall (screen coordinates: the sky is far away). */
    function firework() {
      const x = 30 + Math.floor(rand() * (W - 60)), y = 38 + Math.floor(rand() * 36), hue = Math.floor(rand() * FIREWORK_COLOURS.length), n = 18;
      for (let k = 0; k < n; k++) {
        const a = (k / n) * Math.PI * 2 + rand() * 0.2, v = 1.3 + rand() * 0.7;
        m.sparks.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 0.3, t: 0, life: 34 + Math.floor(rand() * 14), hue });
      }
    }
    function fxStep() {
      for (let i = m.sparks.length - 1; i >= 0; i--) {
        const e = m.sparks[i];
        e.t++; e.x += e.vx; e.y += e.vy; e.vy += 0.04; e.vx *= 0.965; e.vy *= 0.985;
        if (e.t >= e.life) m.sparks.splice(i, 1);
      }
      if (m.phase === 'matchend' && m.steps % 16 === 0 && m.sparks.length < 70) firework();
      for (let i = m.fx.length - 1; i >= 0; i--) {
        const e = m.fx[i];
        e.t++; e.x += e.vx; e.y += e.vy;
        if (e.t >= e.life) m.fx.splice(i, 1);
      }
      if (m.shake > 0) m.shake--;
      if (m.flash > 0) m.flash--;
      for (const f of m.f) if (f.flashT > 0) f.flashT--;
      if (m.hitGlow && --m.hitGlow.t <= 0) m.hitGlow = null;
      m.camKick = Math.abs(m.camKick) < 0.2 ? 0 : m.camKick * 0.72;
      const special = m.f.find((f) => f.state === 'attack' && f.moveName === 'special' && f.si <= f.move.dim);
      m.dimTarget = special ? 0.5 : 0;
      m.dim += (m.dimTarget - m.dim) * 0.4;
      if (Math.abs(m.dim - m.dimTarget) < 0.02) m.dim = m.dimTarget;
      if (m.crowd.t > 0) { m.crowd.t--; if (m.crowd.t === 0) m.crowd.mood = 'idle'; }
      if (m.fadeDir > 0) m.fade = Math.min(1, m.fade + 1 / 22); else if (m.fadeDir < 0) m.fade = Math.max(0, m.fade - 1 / 18);
      // dust under a walking fighter's feet, and under a fast slide
      for (const f of m.f) if (f.state === 'walk' && f.st === 0 && f.si % 3 === 0 && m.steps % 2 === 0) addFx('dust', f.x - f.dir * 16, 2, { rate: 2 });
    }
    /** The camera follows the two fighters' middle; it leans a little toward a special's thrower and toward the one who is knocked out (a push-in; the picture's own zoom is the knock-out's). */
    function cameraStep() {
      let bias = 0, push = 0;
      for (const f of m.f) if (f.state === 'attack' && f.moveName === 'special' && f.move && f.si <= f.move.dim + 1) { bias += f.dir * 6; push = 1; }
      let mid = (codex.x + claude.x) / 2;
      if (m.phase === 'ko' && m.winner) { mid = lerp(mid, other(m.winner).x, 0.4); push = 1; }
      m.camBias += (bias - m.camBias) * 0.12;
      m.pushV += (push - m.pushV) * 0.2;
      const target = clamp(mid - W / 2 + m.camBias, 0, ARENA.width - W);
      m.camX += (target - m.camX) * 0.14;
    }

    m.step = function () {
      m.steps++; m.time += STEP;
      fxStep();
      if (m.hitstop > 0) { m.hitstop--; cameraStep(); return; }
      if (m.slow > 1 && m.steps % m.slow !== 0) { cameraStep(); return; }
      phaseStep();
      for (const f of m.f) fighterStep(f);
      separate();
      projectileStep();
      cameraStep();
    };

    /** Make a free fighter do a move now (for the tests and for a person looking at the picture): 'jab', 'heavy', 'whip', 'special', 'guard', 'taunt'. Returns whether it started. */
    m.start = function (who, name) {
      const f = typeof who === 'number' ? m.f[who] : who;
      if (!f || !free(f) || m.phase !== 'fight') return false;
      if (name === 'guard') toGuard(f, 30);
      else if (name === 'taunt') toTaunt(f);
      else if (MOVES[f.id][name]) toAttack(f, name);
      else return false;
      return true;
    };

    /** A touch at world column `wx` and `above` pixels over the floor: the nearer fighter taunts, or the crowd cheers. */
    m.poke = function (wx, above) {
      const near = Math.abs(wx - codex.x) <= Math.abs(wx - claude.x) ? codex : claude;
      const onFighters = above >= -14 && above <= 96;
      if (onFighters && free(near) && (m.phase === 'fight' || m.phase === 'intro' || m.phase === 'ready')) {
        toTaunt(near); m.stats.taunts++; addFx('glint', near.x + near.dir * 6, 86); addFx('glint', near.x - near.dir * 22, 70, { rate: 3 });
        crowdMood('cheer', 40);
        return 'taunt';
      }
      crowdMood('cheer', 50);
      addFx('glint', wx, Math.max(2, above), { rate: 3 });
      return 'cheer';
    };
    startRound();
    return m;
  }

  /* ---- the atlas: frames by name (anchors say where a fighter's floor is), animations, attachment points, shadows and stages as the preparation script describes them */
  function readAtlas(json) {
    if (!json || typeof json !== 'object' || !json.frames || typeof json.frames !== 'object') return null;
    const cache = new Map();
    const entry = (name) => {
      if (cache.has(name)) return cache.get(name);
      const f = json.frames[name];
      let e = null;
      if (Array.isArray(f) && f.length === 4 && f.every(finite)) {
        const a = json.anchors && Array.isArray(json.anchors[name]) ? json.anchors[name] : [f[2] >> 1, f[3] >> 1];
        e = { name, x: f[0], y: f[1], w: f[2], h: f[3], ax: a[0], ay: a[1] };
      }
      cache.set(name, e);
      return e;
    };
    const points = json.points && typeof json.points === 'object' ? json.points : {};
    const shadows = json.shadows && typeof json.shadows === 'object' ? json.shadows : {};
    const actors = json.anims && json.anims.actors && typeof json.anims.actors === 'object' ? json.anims.actors : {};
    return { entry, anims: json.anims && typeof json.anims === 'object' ? json.anims : {}, stages: json.stages && typeof json.stages === 'object' ? json.stages : {}, count: Object.keys(json.frames).length,
      points: (name) => (Array.isArray(points[name]) ? points[name] : []), shadow: (name) => (Array.isArray(shadows[name]) && shadows[name].length === 3 && shadows[name].every(finite) ? shadows[name] : null),
      actor: (kind, k) => { const list = actors[kind]; return Array.isArray(list) && list.length ? list[((k % list.length) + list.length) % list.length] : null; } };
  }
  const docOf = (api) => (api && api.atlas && api.atlas.ownerDocument) || global.document;
  function makeCanvas(doc, w, h) {
    const c = doc.createElement('canvas');
    c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
    const x = c.getContext('2d');
    if (x) x.imageSmoothingEnabled = false;
    return [c, x];
  }
  /** Draw sprite `e` of `sheet` so its anchor lands on (x, y) (whole pixels, never scaled). Returns false when it is off the picture. */
  function blit(g, sheet, e, x, y) {
    if (!e || !sheet) return false;
    const dx = Math.round(x - e.ax), dy = Math.round(y - e.ay);
    if (dx >= W || dx + e.w <= 0 || dy >= H || dy + e.h <= 0) return false;
    g.drawImage(sheet, e.x, e.y, e.w, e.h, dx, dy, e.w, e.h);
    return true;
  }
  /** The sprite called `name` (tinted by the light) with its anchor at (x, y). */
  const put = (g, s, name, x, y) => (s.lib && name ? blit(g, s.sheetBG || s.atlas, s.lib.entry(name), x, y) : false);
  /** A sprite mirrored left to right, anchor at (x, y). */
  function putFlipped(g, s, name, x, y) {
    const e = s.lib && s.lib.entry(name);
    if (!e) return false;
    const dx = Math.round(x), dy = Math.round(y - e.ay);
    if (dx - e.w >= W || dx + e.w <= 0) return false;
    g.save(); g.translate(dx, 0); g.scale(-1, 1);
    g.drawImage(s.sheetBG || s.atlas, e.x, e.y, e.w, e.h, -e.ax, dy, e.w, e.h);
    g.restore();
    return true;
  }
  /** A whole canvas of the stage, `cam` pixels of it scrolled, drawn at row y. */
  const strip = (g, c, cam, y, h) => { if (c) g.drawImage(c, Math.round(cam), 0, W, h === undefined ? c.height : h, 0, Math.round(y), W, h === undefined ? c.height : h); };
  const bake = (s, w, h, fn) => { const [c, x] = makeCanvas(s.doc, w, h); if (!x) return null; fn(x, c); return c; };
  /** A pixel disc: one rectangle per row, so the edge is stairs, never anti-aliased. */
  function disc(x, cx, cy, r) { for (let y = -r; y <= r; y++) { const half = Math.floor(Math.sqrt(r * r - y * y) + 0.5); x.fillRect(cx - half, cy + y, half * 2 + 1, 1); } }
  /** A ring between radii r0 and r1, the same way (rows only: the arc stays above `cy` when `upper` is true). */
  function ring(x, cx, cy, r0, r1, upper) {
    for (let y = -r1; y <= (upper ? 0 : r1); y++) {
      const o = Math.floor(Math.sqrt(r1 * r1 - y * y) + 0.5), i = Math.abs(y) < r0 ? Math.floor(Math.sqrt(r0 * r0 - y * y) + 0.5) : -1;
      if (i < 0) x.fillRect(cx - o, cy + y, o * 2 + 1, 1); else { x.fillRect(cx - o, cy + y, o - i, 1); x.fillRect(cx + i + 1, cy + y, o - i, 1); }
    }
  }
  /** One layer at a time may be rebuilt in a frame once it exists (a new light changes many layers at once; they follow in turn, never in one hitch). */
  function layer(s, st, name, key, builder) {
    st.L = st.L || {}; st.keys = st.keys || {};
    if (st.L[name] !== undefined && st.keys[name] === key) return st.L[name];
    if (st.L[name] !== undefined && s.builds >= 2) return st.L[name];
    s.builds++;
    st.keys[name] = key;
    let c = null;
    try { c = builder(); } catch (e) { s.errors['layer ' + name] = String(e && e.message || e); }
    st.L[name] = c;
    return c;
  }

  /* ---- pixel text drawn once into a small canvas (an upright block font, an outline and a shadow, a gradient by row) and then copied */
  const TEXT_STYLES = {
    banner: { top: '#fff58a', bottom: '#ff6a1a', outline: '#3b1348', shadow: '#12081c' },
    ko: { top: '#ffffff', bottom: '#ff3b2f', outline: '#3a0a12', shadow: '#12081c' },
    win: { top: '#ffffff', bottom: '#9fd0ff', outline: '#10224a', shadow: '#080f22' },
    name: { top: '#ffffff', bottom: '#dfe6ff', outline: '#10142e', shadow: '#080a1a' },
    digit: { top: '#fff7b0', bottom: '#ffcf3a', outline: '#10142e', shadow: '#080a1a' },
    cloth: { top: '#3a2418', bottom: '#3a2418', outline: null, shadow: null },
    plate: { top: '#ffffff', bottom: '#c8d4ff', outline: '#0a1030', shadow: '#05081a' },
  };
  /** A style by name; 'neon:#rrggbb' makes a glowing sign colour on the fly. */
  function styleOf(name) {
    if (TEXT_STYLES[name]) return TEXT_STYLES[name];
    if (typeof name === 'string' && name.startsWith('neon:')) { const c = name.slice(5); return { top: '#ffffff', bottom: c, outline: c, shadow: null }; }
    return TEXT_STYLES.banner;
  }
  function renderText(doc, text, scale, styleName) {
    const t = textPixels(text), st = styleOf(styleName);
    const o = st.outline ? Math.max(1, scale >> 1) : 0, pad = o + (st.shadow ? scale : 0) + (st.outline ? 0 : 0);
    const w = t.width * scale + pad * 2, h = t.height * scale + pad * 2;
    const [c, x] = makeCanvas(doc, Math.max(2, w), Math.max(2, h));
    if (!x) return null;
    if (st.shadow) { x.fillStyle = st.shadow; for (const [px, py] of t.pixels) x.fillRect(pad + px * scale - o + o, pad + py * scale - o + o + o, scale + 2 * o, scale + 2 * o); }
    if (st.outline) { x.fillStyle = st.outline; for (const [px, py] of t.pixels) x.fillRect(pad + px * scale - o, pad + py * scale - o, scale + 2 * o, scale + 2 * o); }
    const a = rgb(st.top), b = rgb(st.bottom);
    for (const [px, py] of t.pixels) { x.fillStyle = css(mixRgb(a, b, py / (GLYPH_H - 1))); x.fillRect(pad + px * scale, pad + py * scale, scale, scale); }
    return { canvas: c, w, h, pad, textWidth: t.width * scale };
  }
  function textSprite(s, text, scale, style) {
    const key = text + '|' + scale + '|' + style;
    let t = s.texts.get(key);
    if (t === undefined) { t = renderText(s.doc, text, scale, style); s.texts.set(key, t); }
    return t;
  }
  /** Draw a text centred on x (or left/right aligned) with its vertical middle on y. */
  function drawText(g, s, text, x, y, scale, style, align) {
    const t = textSprite(s, text, scale, style);
    if (!t) return;
    const left = align === 'left' ? x - t.pad : align === 'right' ? x - t.textWidth - t.pad : Math.round(x - t.w / 2);
    g.drawImage(t.canvas, Math.round(left), Math.round(y - t.h / 2));
  }

  /* ---- the light: the global tint on the atlas and the baked layers that depend on the sun, rebuilt only when the light has really moved */
  const lightKey = (light) => light.tint.map((v) => Math.round(v * 24)).join(',') + '|' + Math.round(light.lamps * 4) + '|' + Math.round(light.alt / 2);
  function tintSheet(s, tint) {
    const key = tint.map((v) => Math.round(v * 16)).join(',');
    if (key === s.sheetKey) return;
    s.sheetKey = key;
    if (!s.atlas) return;
    if (tint[0] >= 0.97 && tint[1] >= 0.97 && tint[2] >= 0.97) { s.sheetBG = s.atlas; return; }
    if (!s.doc) { s.sheetBG = s.atlas; return; }
    if (!s.tintCanvas) { const [c] = makeCanvas(s.doc, s.atlas.naturalWidth || s.atlas.width, s.atlas.naturalHeight || s.atlas.height); s.tintCanvas = c; }
    const c = s.tintCanvas, x = c.getContext('2d');
    if (!x) { s.sheetBG = s.atlas; return; }
    x.globalCompositeOperation = 'source-over'; x.clearRect(0, 0, c.width, c.height); x.drawImage(s.atlas, 0, 0);
    x.globalCompositeOperation = 'multiply'; x.fillStyle = css(tint.map((v) => Math.round(clamp(v, 0, 1) * 255))); x.fillRect(0, 0, c.width, c.height);
    x.globalCompositeOperation = 'destination-in'; x.drawImage(s.atlas, 0, 0);
    x.globalCompositeOperation = 'source-over';
    s.sheetBG = c;
  }
  /** A soft warm glow (a radial gradient drawn once) that a lantern or a lit window adds to the night. */
  function glowSprite(s, r, colour) {
    const key = r + (colour || '');
    if (s.glows[key] !== undefined) return s.glows[key];
    let c = null;
    const made = s.doc ? makeCanvas(s.doc, 2 * r, 2 * r) : null;
    if (made && made[1] && typeof made[1].createRadialGradient === 'function') {
      const x = made[1], grad = x.createRadialGradient(r, r, 0, r, r, r), cc = colour || '255,190,100';
      grad.addColorStop(0, 'rgba(' + cc + ',0.55)'); grad.addColorStop(0.4, 'rgba(' + cc + ',0.2)'); grad.addColorStop(1, 'rgba(' + cc + ',0)');
      x.fillStyle = grad; x.fillRect(0, 0, 2 * r, 2 * r);
      c = made[0];
    }
    s.glows[key] = c;
    return c;
  }
  /** Add a glow of radius r at (x, y) with 'lighter' compositing, at the given strength. */
  function glowAt(g, s, x, y, r, strength, colour) {
    if (strength <= 0.02) return;
    const glow = glowSprite(s, r, colour);
    if (!glow) return;
    g.globalCompositeOperation = 'lighter'; g.globalAlpha = clamp(strength, 0, 1);
    g.drawImage(glow, Math.round(x - r), Math.round(y - r));
    g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
  }

  /* ---- the sky: six flat bands that follow the clock, stars, the sun with its shafts or the moon, two depths of clouds with lit edges, and whatever passes by (an airship, a banner plane,
   *      fireworks, a far storm or a rainbow). Everything is baked when the light changes and then copied; `hor` is the horizon row. */
  function skyBands(g, light, hor) {
    const cuts = [0, 0.22, 0.42, 0.62, 0.78, 0.9, 1].map((f) => Math.round(f * hor));
    for (let i = 0; i < 6; i++) { g.fillStyle = css(light.sky[i]); g.fillRect(0, cuts[i], W, cuts[i + 1] - cuts[i] + (i === 5 ? 2 : 0)); }
  }
  function celestial(s, kind, light, bandColour) {
    const r = kind === 'sun' ? light.r : 7, pad = kind === 'sun' ? 6 : 3, size = 2 * (r + pad) + 1, [c, x] = makeCanvas(s.doc, size, size);
    if (!x) return null;
    const mid = r + pad;
    if (kind === 'sun') {
      for (let k = 2; k >= 0; k--) {
        const rad = r + (k === 2 ? 6 : k === 1 ? 3 : 0);
        x.fillStyle = css(k === 0 ? light.sun : mixRgb(bandColour, light.sun, k === 1 ? 0.42 : 0.18));
        disc(x, mid, mid, rad);
      }
    } else {                                                                                                  // a full moon with maria and a halo, and a crescent cut on the sky's side
      x.fillStyle = css(mixRgb(light.sky[2], [244, 240, 216], 0.18)); disc(x, mid, mid, r + 3);
      x.fillStyle = css(mixRgb(light.sky[2], [244, 240, 216], 0.4)); disc(x, mid, mid, r + 1);
      x.fillStyle = '#f4f0d8'; disc(x, mid, mid, r);
      x.fillStyle = '#d6d2b8';
      for (const [dx, dy, rr] of [[-2, -2, 2], [2, 1, 2], [0, 3, 1], [-3, 2, 1]]) disc(x, mid + dx, mid + dy, rr);
      x.fillStyle = '#fffdf0'; x.fillRect(mid - 4, mid - 4, 2, 1); x.fillRect(mid - 5, mid - 3, 1, 2);
    }
    return { canvas: c, mid };
  }
  /** Shafts of light fanning out of the sun (drawn once as pale wedges; the scene lets them breathe with a changing alpha). */
  function bakeRays(s, light) {
    const R = 120;
    return bake(s, R * 2, R * 2, (x) => {
      const col = mixRgb(light.sun, [255, 255, 255], 0.4);
      for (let k = 0; k < 9; k++) {
        const a0 = (k / 9) * Math.PI * 2 + 0.17, a1 = a0 + 0.11 + 0.05 * (k % 3), r0 = 14;
        x.fillStyle = css(col, 0.5);
        x.beginPath(); x.moveTo(R + Math.cos(a0) * r0, R + Math.sin(a0) * r0); x.lineTo(R + Math.cos(a0) * R, R + Math.sin(a0) * R); x.lineTo(R + Math.cos(a1) * R, R + Math.sin(a1) * R); x.lineTo(R + Math.cos(a1) * r0, R + Math.sin(a1) * r0); x.closePath(); x.fill();
      }
    });
  }
  /** The stars of the whole sky at fixed rows (a baked canvas) and how many of them are brighter. */
  function bakeStars(s, stars) {
    return bake(s, W, 170, (x) => {
      for (const star of stars) {
        const sy = 3 + Math.floor(star.f * 160);
        x.fillStyle = star.big ? '#f4f6ff' : star.tw ? '#8ca0d2' : '#d4dcff'; x.fillRect(star.x, sy, 1, 1);
        if (star.big) { x.fillStyle = '#8ca0d2'; x.fillRect(star.x + 1, sy, 1, 1); x.fillRect(star.x - 1, sy, 1, 1); x.fillRect(star.x, sy + 1, 1, 1); x.fillRect(star.x, sy - 1, 1, 1); }
      }
    });
  }
  /** Clouds in the sky's own light: the atlas cumulus with a bright rim on the sun's side and a cool shade underneath, per light. */
  function bakeClouds(s, light) {
    const lib = s.lib, names = (lib && lib.anims.clouds && lib.anims.clouds.cumulus) || [];
    const side = light.morning ? 1 : -1, rim = mixRgb(light.sun, [255, 252, 236], 0.5), shade = mixRgb(light.sky[1], [20, 24, 60], 0.35);
    return names.map((name) => {
      const e = lib.entry(name);
      if (!e) return null;
      const cw = e.w + 2, ch = e.h + 2;
      const [c, x] = makeCanvas(s.doc, cw, ch);
      if (!x) return null;
      x.drawImage(s.sheetBG || s.atlas, e.x, e.y, e.w, e.h, 1, 1, e.w, e.h);
      const edge = (dx, dy, colour, alpha) => {
        const [t, tx] = makeCanvas(s.doc, cw, ch);
        if (!tx) return;
        tx.drawImage(c, 0, 0);
        tx.globalCompositeOperation = 'destination-out'; tx.drawImage(c, dx, dy);
        tx.globalCompositeOperation = 'source-in'; tx.fillStyle = css(colour, alpha); tx.fillRect(0, 0, cw, ch);
        x.drawImage(t, 0, 0);
      };
      edge(0, -2, shade, 0.5);
      edge(-2 * side, 2, rim, 0.9);
      return { canvas: c, w: cw, h: ch };
    });
  }

  function makeSky(rand, weather) {
    const sky = { weather, clouds: [], far: [], stars: [], bolt: null, boltIn: 500 + Math.floor(rand() * 500), blimp: { x: 40 + rand() * 120, dir: rand() < 0.5 ? 1 : -1, wait: 0 }, plane: { on: false, wait: 900 + Math.floor(rand() * 900), x: 0, dir: 1, text: '' },
      fireworks: [], shoot: null, shootIn: 400 + Math.floor(rand() * 600), flare: 0 };
    for (let i = 0; i < 5; i++) sky.clouds.push({ x0: Math.floor(rand() * (W + 80)), f: (i + 0.2 + rand() * 0.5) / 5, kind: i % 4 });
    for (let i = 0; i < 4; i++) sky.far.push({ x0: Math.floor(rand() * (W + 120)), y: 10 + rand() * 60, w: 40 + Math.floor(rand() * 70) });
    for (let i = 0; i < 70; i++) sky.stars.push({ x: Math.floor(rand() * W), f: rand(), at: rand(), tw: Math.floor(rand() * 3), big: rand() < 0.1 });
    return sky;
  }
  const PLANE_TEXTS = ['FRESH FISH', 'HARBOUR CUP', 'GO GO GO!', 'SUMMER SALE', 'VERSUS NIGHT'];
  function bannerCloth(s, text, wave) {
    const key = 'cloth|' + text + '|' + wave;
    if (s.texts.has(key)) return s.texts.get(key);
    const t = textPixels(text), w = t.width + 8, h = 11;
    const out = bake(s, w, h + 4, (x) => {
      const [c, cx] = makeCanvas(s.doc, w, h);
      if (!cx) return;
      cx.fillStyle = '#f4ecd0'; cx.fillRect(0, 0, w, h); cx.fillStyle = '#c0402e'; cx.fillRect(0, 0, 2, h); cx.fillRect(w - 2, 0, 2, h); cx.fillStyle = '#d8ccaa'; cx.fillRect(0, h - 1, w, 1);
      cx.fillStyle = '#3a2418'; for (const [px, py] of t.pixels) cx.fillRect(4 + px, 2 + py, 1, 1);
      for (let col = 0; col < w; col++) x.drawImage(c, col, 0, 1, h, col, 2 + Math.round(Math.sin(col * 0.32 + wave * 1.4) * 1.5), 1, h);
    });
    s.texts.set(key, out ? { canvas: out, w, h: h + 4 } : null);
    return s.texts.get(key);
  }

  function stepSky(s, sky, m, rect) {
    const b = sky.blimp;
    if (b.wait > 0) b.wait--; else { b.x += b.dir * 0.14; if (b.x > W + 90 || b.x < -90) { b.dir = -b.dir; b.wait = 700 + Math.floor(m.rand() * 600); } }
    const p = sky.plane;
    if (p.on) { p.x += p.dir * 0.55; if (p.x > W + 120 || p.x < -120) { p.on = false; p.wait = 1500 + Math.floor(rect.rand() * 1500); } }
    else if (--p.wait <= 0) { p.on = true; p.dir = rect.rand() < 0.5 ? 1 : -1; p.x = p.dir > 0 ? -110 : W + 110; p.text = PLANE_TEXTS[Math.floor(rect.rand() * PLANE_TEXTS.length)]; }
    for (let i = sky.fireworks.length - 1; i >= 0; i--) {
      const f = sky.fireworks[i];
      f.t++;
      if (f.mode === 'rise') { f.y = f.y0 + (f.y1 - f.y0) * (1 - (1 - f.t / f.fuse) * (1 - f.t / f.fuse)); f.trail.push([f.x, f.y]); if (f.trail.length > 6) f.trail.shift(); if (f.t >= f.fuse) burst(sky, f); }
      else { for (const e of f.parts) { e.t++; e.x += e.vx; e.y += e.vy; e.vy += f.grav; e.vx *= 0.97; e.vy *= 0.985; } if (f.t > f.fuse + f.life) sky.fireworks.splice(i, 1); }
    }
    if (sky.shoot) { sky.shoot.t++; if (sky.shoot.t > 14) sky.shoot = null; } else if (s.light && s.light.stars > 0.5 && --sky.shootIn <= 0) { sky.shootIn = 500 + Math.floor(rect.rand() * 900); sky.shoot = { x: 40 + rect.rand() * 120, y: 12 + rect.rand() * 40, t: 0 }; }
    if (sky.flare > 0) sky.flare--;
  }
  /** A rocket that climbs and bursts under the horizon `hor`: a ring of embers, a willow that droops or a palm that crackles (a lower sky makes a smaller burst). */
  function launchFirework(sky, rect, hor) {
    if (sky.fireworks.length >= 4) return;
    const kind = ['ring', 'willow', 'palm'][Math.floor(rect.rand() * 3)], room = Math.max(24, hor - 38), y1 = 24 + rect.rand() * clamp(hor - 80, 8, 70), k = clamp((hor - 20) / 90, 0.55, 1.25);
    sky.fireworks.push({ mode: 'rise', x: 28 + rect.rand() * (W - 56), y: hor - 2, y0: hor - 2, y1, k, trail: [], t: 0, fuse: 20 + Math.floor(rect.rand() * 8), kind, hue: Math.floor(rect.rand() * FIREWORK_COLOURS.length), parts: [], grav: (kind === 'willow' ? 0.05 : 0.03) * k, life: 44 });
  }
  function burst(sky, f) {
    f.mode = 'burst'; f.t = f.fuse; f.parts.length = 0; sky.flare = 3;
    const n = f.kind === 'palm' ? 22 : f.kind === 'willow' ? 30 : 36;
    for (let q = 0; q < n; q++) {
      const a = (q / n) * Math.PI * 2 + (q & 1) * 0.1, v = (f.kind === 'palm' ? 1.8 + (q % 2) * 0.8 : f.kind === 'willow' ? 1.4 + (q % 3) * 0.25 : 1.4 + (q % 2) * 0.45) * f.k;
      f.parts.push({ x: f.x, y: f.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - (f.kind === 'willow' ? 0.4 * f.k : 0), t: 0 });
    }
    f.life = f.kind === 'willow' ? 58 : 40;
  }

  const FIREWORK_GLOW = ['255,210,70', '255,130,60', '120,200,255', '255,110,180', '170,255,120'];
  function drawFireworks(g, s, sky, hor) {
    for (const f of sky.fireworks) {
      const colour = FIREWORK_COLOURS[f.hue];
      if (f.mode === 'rise') {
        g.fillStyle = '#fff2c0'; g.fillRect(Math.round(f.x), Math.round(f.y), 2, 2);
        g.fillStyle = 'rgba(255,214,120,0.7)';
        for (let i = 0; i < f.trail.length; i++) g.fillRect(Math.round(f.trail[i][0]), Math.round(f.trail[i][1]) + 2 + (f.trail.length - i), 1, 1);
      } else {
        const age = f.t - f.fuse, left = 1 - age / f.life;
        if (age < 9 && !s.cheap) glowAt(g, s, f.x, f.y, 34, (1 - age / 9) * 0.9, FIREWORK_GLOW[f.hue]);
        if (age < 5) { g.fillStyle = '#ffffff'; const q = 5 - age; g.fillRect(Math.round(f.x) - q, Math.round(f.y), q * 2 + 1, 1); g.fillRect(Math.round(f.x), Math.round(f.y) - q, 1, q * 2 + 1); g.fillRect(Math.round(f.x) - 1, Math.round(f.y) - 1, 3, 3); }
        for (const e of f.parts) {
          if (e.y > hor + 6) continue;
          const sz = left > 0.7 ? 3 : left > 0.35 ? 2 : 1, x = Math.round(e.x) - (sz >> 1), y = Math.round(e.y) - (sz >> 1);
          g.fillStyle = left > 0.85 ? '#ffffff' : colour; g.fillRect(x, y, sz, sz);
          if (left > 0.15) { g.fillStyle = colour; g.globalAlpha = 0.55; g.fillRect(Math.round(e.x - e.vx * 2), Math.round(e.y - e.vy * 2), 1, 1); g.fillRect(Math.round(e.x - e.vx * 4), Math.round(e.y - e.vy * 4), 1, 1); g.globalAlpha = 1; }
          if (f.kind === 'palm' && left > 0.3 && (e.t & 3) === 0) { g.fillStyle = '#ffffff'; g.fillRect(x + 2, y + 2, 1, 1); }
        }
      }
    }
  }

  /** A cached composite of several layers that move together (the sky, the shore, the pier, the street, the HUD's frame): a screen-sized canvas that `build(ctx)` redraws only when `key`
   *  changes, so most frames copy it once. A new light changes many of them at once; they are rebuilt a few per frame, never in one hitch (a first build is never delayed). */
  function compose(s, st, name, key, build) {
    st.C = st.C || {};
    let c = st.C[name];
    if (!c) { const [cv, cx] = makeCanvas(s.doc, W, H); c = st.C[name] = { canvas: cv, ctx: cx, key: null }; }
    if (c.key !== key) {
      if (!c.ctx) return null;
      if (c.key !== null && s.builds >= 4) return c.canvas;
      s.builds++;
      c.ctx.clearRect(0, 0, W, H);
      try { build(c.ctx); } catch (e) { s.errors['compose ' + name] = String(e && e.message || e); }
      c.key = key;
    }
    return c.canvas;
  }

  /** The sky as one composite: bands, stars, the sun or the moon, a rainbow, a storm's bank, high streaks and clouds. The clouds drift one pixel at a time (together, every 16 or 24 steps),
   *  so the composite is rebuilt rarely; what really moves (twinkle, shafts, an airship, a plane, fireworks, lightning) is drawn on top. */
  function drawSkyBase(x, s, st, hor, cn, cf, near16, near24, far) {
    const light = s.light, lib = s.lib, sky = st.sky, key = lightKey(light), cheap = s.cheap;
    if (sky.weather === 'storm') { if (sky.washKey !== key) { sky.washKey = key; sky.wash = light.sky.map((c) => mixRgb(c, [92, 100, 130], 0.34)); } skyBands(x, { sky: sky.wash }, hor); }
    else skyBands(x, light, hor);
    if (light.stars > 0.02) {
      const stars = layer(s, st, 'stars', 'stars', () => bakeStars(s, sky.stars));
      if (stars) { x.globalAlpha = clamp(light.stars, 0, 1); x.drawImage(stars, 0, 0, W, Math.min(170, hor), 0, 0, W, Math.min(170, hor)); x.globalAlpha = 1; }
    }
    if (light.alt > -4) {
      const place = sunPlace(light.alt, light.morning, hor);
      const sun = layer(s, st, 'sun', key + '|' + hor, () => celestial(s, 'sun', light, light.sky[Math.min(5, Math.max(0, Math.floor(place.y / Math.max(1, hor) * 6)))]));
      if (!cheap && light.alt < 40) { const rays = layer(s, st, 'rays', key, () => bakeRays(s, light)); if (rays) { x.globalCompositeOperation = 'lighter'; x.globalAlpha = light.alt < 12 ? 0.2 : 0.12; x.drawImage(rays, place.x - 120, place.y - 120); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over'; } }
      if (sun) x.drawImage(sun.canvas, place.x - sun.mid, place.y - sun.mid);
    }
    if (light.alt < -2) {
      const mp = moonPlace(light.solar, hor);
      const moon = layer(s, st, 'moon', key, () => celestial(s, 'moon', light, null));
      if (moon) x.drawImage(moon.canvas, mp.x - moon.mid, mp.y - moon.mid);
    }
    if (sky.weather === 'rainbow' && light.alt > 2 && light.alt < 45) {
      const rb = layer(s, st, 'rainbow', hor + '|' + Math.round(light.alt / 6), () => bakeRainbow(s, hor, light));
      if (rb) { x.globalAlpha = 0.42 * clamp((light.alt - 2) / 8, 0, 1); x.drawImage(rb, Math.round(-cn * 0.5), 0); x.globalAlpha = 1; }
    }
    if (sky.weather === 'storm') { const bank = layer(s, st, 'storm', key, () => bakeStorm(s, light)); if (bank) x.drawImage(bank, Math.round(100 - cn * 0.8), hor - 52); }
    if (lib && s.atlas) {
      const set = layer(s, st, 'clouds', key, () => bakeClouds(s, light)) || [];
      if (!cheap) for (const c of sky.far) {
        const cx = ((c.x0 + far - cf) % (W + 160) + (W + 160)) % (W + 160) - 80, cy = Math.round(10 + (c.y / 70) * Math.max(10, hor - 40));
        x.fillStyle = css(mixRgb(light.sky[Math.min(5, 1 + (cy * 6 / Math.max(1, hor)) | 0)], [255, 255, 255], 0.28), 0.65); x.fillRect(Math.round(cx), cy, c.w, 2); x.fillRect(Math.round(cx) + 5, cy - 1, c.w - 14, 1);
      }
      for (const [i, c] of sky.clouds.entries()) {
        const e = set[c.kind % Math.max(1, set.length)];
        if (!e) continue;
        const maxH = Math.max(7, hor * 0.34), pick = e.h > maxH && set[0] ? set[0] : e;
        x.drawImage(pick.canvas, ((c.x0 + (i & 1 ? near24 : near16) - cn) % (W + 120) + (W + 120)) % (W + 120) - 60, 8 + Math.round(c.f * Math.max(4, hor - 40 - pick.h)));
      }
    }
  }
  function drawSky(g, s, m, cam, hor, st) {
    const light = s.light, sky = st.sky, key = lightKey(light), cheap = s.cheap, steps = m.steps;
    const n16 = Math.floor(steps / 16), n24 = Math.floor(steps / 24), far = Math.floor(steps / 32), cn = Math.round(cam * 0.12), cf = Math.round(cam * 0.05);
    const c = compose(s, st, 'sky', [key, hor, sky.weather, n16, n24, far, cn, cf, cheap ? 1 : 0].join('|'), (x) => drawSkyBase(x, s, st, hor, cn, cf, n16, n24, far));
    if (c) g.drawImage(c, 0, 0, W, hor + 2, 0, 0, W, hor + 2);
    if (light.stars > 0.02) {
      g.fillStyle = '#ffffff';
      for (let i = 0; i < 3; i++) { const star = sky.stars[i * 11]; if (star.at <= light.stars && ((steps >> 3) + i) % 4 === 0) g.fillRect(star.x, 3 + Math.floor(star.f * 160) % Math.max(4, hor - 10), 1, 1); }
      if (sky.shoot && !cheap) { const t = sky.shoot.t; g.fillStyle = '#ffffff'; g.fillRect(Math.round(sky.shoot.x + t * 3), Math.round(sky.shoot.y + t * 1.2), 2, 1); g.fillStyle = 'rgba(255,255,255,0.5)'; g.fillRect(Math.round(sky.shoot.x + t * 3 - 6), Math.round(sky.shoot.y + t * 1.2 - 2), 5, 1); }
    }
    if (sky.weather === 'storm' && sky.bolt) {
      const flash = sky.bolt.t < 4 ? 1 - sky.bolt.t / 4 : 0, bank = layer(s, st, 'storm', key, () => bakeStorm(s, light)), bx = Math.round(100 - cam * 0.1 * 0.8);
      if (bank && flash) { g.globalCompositeOperation = 'lighter'; g.globalAlpha = 0.45 * flash; g.drawImage(bank, bx, hor - 52); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; }
      if (sky.bolt.t < sky.bolt.dur - 3) { g.fillStyle = '#f4f8ff'; for (const [bx2, by] of sky.bolt.points) { if (by + hor - 48 < hor - 2) g.fillRect(Math.round(bx2 - cam * 0.1), hor - 48 + by, 2, 4); } }
      if (flash) { g.fillStyle = 'rgba(190,210,255,' + (0.16 * flash) + ')'; g.fillRect(0, 0, W, hor); }
    }
    if (sky.weather === 'storm' && !cheap) {
      const rain = layer(s, st, 'rain', key, () => buildHarbourLayers(s, st, light, 'rain'));
      if (rain) for (let k = 0; k < 3; k++) g.drawImage(rain, 0, (steps * 3 + k * 9) % 30, 60, 10, Math.round(110 - cam * 0.1) + k * 40, hor - 12, 60, 10);
    }
    drawSkyActors(g, s, m, cam, hor, st);
    drawFireworks(g, s, sky, hor);
    if (sky.flare > 0 && !cheap) { g.fillStyle = 'rgba(255,240,210,' + (0.06 * sky.flare) + ')'; g.fillRect(0, 0, W, hor); }
  }
  function bakeRainbow(s, hor, light) {
    return bake(s, W + 40, Math.max(40, hor), (x) => {
      const cx = Math.round(W * 0.62), cy = hor + 22, bands = ['#e8453c', '#f08a2a', '#ffd23a', '#68d066', '#3a9ae8', '#4a4ac8', '#8a4fc0'];
      for (let i = 0; i < bands.length; i++) { x.fillStyle = bands[i]; ring(x, cx, cy, 78 - i * 2 - 2, 78 - i * 2, true); }
    });
  }
  function drawSkyActors(g, s, m, cam, hor, st) {
    const sky = st.sky, light = s.light, lib = s.lib;
    if (!lib || !s.atlas) return;
    const yBlimp = Math.min(hor - 4, Math.max(66, hor * 0.55 + 30));
    const b = sky.blimp;
    if (b.wait <= 0 && (b.x > -80 && b.x < W + 80)) {
      const name = lib.actor('blimp', (m.steps >> 2) & 1), bx = Math.round(b.x - cam * 0.08), by = Math.round(yBlimp + Math.sin(m.steps * 0.02) * 1.5);
      if (b.dir > 0) put(g, s, name, bx, by); else putFlipped(g, s, name, bx, by);
      if (light.lamps > 0.3 && !s.cheap) for (const [dx, dy] of lib.points(name)) { g.fillStyle = 'rgba(255,226,140,' + clamp(light.lamps, 0, 1) + ')'; g.fillRect(bx + (b.dir > 0 ? dx : -dx), by + dy, 2, 1); }
    }
    const p = sky.plane;
    if (p.on) {
      const px = Math.round(p.x), py = Math.round(Math.max(40, Math.min(hor - 16, hor * 0.4 + 6)) + Math.sin(m.steps * 0.05) * 2);
      const cloth = bannerCloth(s, p.text, (m.steps >> 3) % 3);
      if (cloth) g.drawImage(cloth.canvas, p.dir > 0 ? px - 6 - cloth.w : px + 6, py - 4);
      if (p.dir > 0) put(g, s, lib.actor('plane', (m.steps >> 1) & 1), px, py); else putFlipped(g, s, lib.actor('plane', (m.steps >> 1) & 1), px, py);
    }
  }

  /* ---- the shore: skyline in two depths (towers, domes, spires, sawtooth roofs, tanks, a stack, a lit sign) that slides at two speeds */
  function makeSkyline(rand) {
    const out = { far: [], near: [] };
    for (const [list, lo, hi, wlo, whi] of [[out.far, 12, 30, 7, 15], [out.near, 8, 20, 9, 19]]) {
      let x = -6;
      while (x < ARENA.width + 10) {
        const w = Math.round(between(rand, wlo, whi)), h = Math.round(between(rand, lo, hi));
        const roof = weighted(rand, [[0, 3], [1, 2], [2, 1], [3, 1], [4, 1], [5, 1], [6, 1]]);
        list.push({ x, w, h, roof, lit: rand(), sign: list === out.near && roof === 0 && rand() < 0.12 ? pick(rand, ['BAR', 'INN', 'CAFE', 'SAIL']) : null });
        x += w + Math.round(between(rand, 0, 3));
      }
    }
    return out;
  }
  function bakeSkyline(s, list, base, depth, withWindows, light, ph) {
    const tint = light.tint, haze = light.haze, body0 = mulRgb(mixRgb(base, haze, depth), tint);
    return bake(s, ARENA.width, ph, (x) => {
      for (const b of list) {
        const top = ph - b.h, body = body0, dark = mixRgb(body, [0, 0, 0], 0.22), hi = mixRgb(body, [255, 255, 255], 0.14);
        x.fillStyle = css(body); x.fillRect(b.x, top, b.w, b.h);
        x.fillStyle = css(hi); x.fillRect(b.x, top, b.w, 1);
        x.fillStyle = css(dark); x.fillRect(b.x + b.w - 1, top, 1, b.h);
        const cx = b.x + (b.w >> 1);
        if (b.roof === 1) { x.fillStyle = css(body); x.fillRect(cx, top - 6, 1, 6); x.fillStyle = css(dark); x.fillRect(cx - 1, top - 2, 3, 1); }                                   // an antenna
        else if (b.roof === 2) { x.fillStyle = css(dark); x.fillRect(b.x + 2, top - 2, Math.max(2, b.w - 4), 2); }
        else if (b.roof === 3) { x.fillStyle = css(body); const r = Math.max(3, (b.w >> 1) - 1); for (let k = 0; k < r; k++) x.fillRect(cx - r + k + 1, top - 1 - Math.floor(Math.sqrt(r * r - (r - k) * (r - k))), (r - k) * 2 - 1 > 0 ? 1 : 1, 1); x.fillStyle = css(hi); x.fillRect(cx - 1, top - r - 1, 2, 1); }  // a dome
        else if (b.roof === 4) { x.fillStyle = css(body); for (let k = 0; k < 8; k++) x.fillRect(cx - (7 - k >> 1), top - 1 - k, Math.max(1, (7 - k >> 1) * 2 + 1 - 2), 1); x.fillStyle = css(hi); x.fillRect(cx, top - 10, 1, 2); }  // a spire
        else if (b.roof === 5) { x.fillStyle = css(dark); for (let k = 0; k < b.w - 2; k += 4) { x.fillRect(b.x + 1 + k, top - 3, 2, 3); x.fillRect(b.x + 3 + k, top - 2, 1, 2); } }                    // sawtooth roofs
        else if (b.roof === 6) { x.fillStyle = css(dark); x.fillRect(cx - 3, top - 6, 7, 5); x.fillStyle = css(body); x.fillRect(cx - 3, top - 6, 7, 1); x.fillRect(cx - 2, top - 1, 1, 1); x.fillRect(cx + 2, top - 1, 1, 1); }   // a water tank
        if (withWindows && light.lamps > 0.12) {
          x.fillStyle = css([255, 211, 106]);
          const rows = Math.floor((b.h - 4) / 4), cols = Math.floor((b.w - 2) / 3);
          for (let r = 0; r < rows; r++) for (let k = 0; k < cols; k++) {
            const h = Math.imul(b.x * 31 + r * 17 + k * 7, 2654435761) >>> 0;
            if ((h % 100) / 100 < b.lit * 0.55 * light.lamps) x.fillRect(b.x + 1 + k * 3, top + 3 + r * 4, 1, 2);
          }
          if (b.sign) { const tw = textPixels(b.sign), neon = [[255, 90, 140], [90, 220, 255], [255, 200, 70]][b.x % 3], sx = Math.max(0, Math.min(ARENA.width - tw.width - 2, b.x + (b.w >> 1) - (tw.width >> 1))), sy = top - 9;
            x.fillStyle = css(mixRgb([20, 24, 44], neon, 0.25 * light.lamps)); x.fillRect(sx - 1, sy - 1, tw.width + 2, 9); x.fillStyle = css(mixRgb(neon, [255, 255, 255], 0.2)); for (const [px, py] of tw.pixels) x.fillRect(sx + px, sy + py, 1, 1); }
        }
      }
    });
  }

  /** A ferris wheel on the shore: eight turns of it, baked (a rim, spokes, gondolas that stay upright, lit rim lamps at night). */
  function bakeWheel(s, light) {
    const R = 21, size = R * 2 + 8, mid = R + 4, tint = light.tint, steel = css(mulRgb([150, 160, 190], tint)), dark = css(mulRgb([54, 62, 92], tint));
    const colours = ['#e8453c', '#ffd23a', '#3a9ae8', '#68d066', '#f08a2a', '#e8509a', '#8a4fc0', '#4ad0c8'].map((c) => css(mulRgb(rgb(c), tint)));
    const frames = [];
    for (let f = 0; f < 8; f++) {
      const c = bake(s, size, size + 18, (x) => {
        x.fillStyle = dark; ring(x, mid, mid, R - 1, R, false); x.fillStyle = steel; ring(x, mid, mid, R - 8, R - 7, false);
        const turn = f * (Math.PI / 4) / 8;
        for (let k = 0; k < 8; k++) {
          const a = turn + k * Math.PI / 4;
          x.fillStyle = steel;
          for (let r = 1; r < R; r++) x.fillRect(Math.round(mid + Math.cos(a) * r), Math.round(mid + Math.sin(a) * r), 1, 1);
          const gx = Math.round(mid + Math.cos(a) * R), gy = Math.round(mid + Math.sin(a) * R);
          x.fillStyle = colours[k]; x.fillRect(gx - 2, gy, 5, 4); x.fillStyle = dark; x.fillRect(gx - 2, gy + 3, 5, 1);
          if (light.lamps > 0.3) { x.fillStyle = 'rgba(255,240,170,' + light.lamps + ')'; x.fillRect(gx, gy - 1, 1, 1); }
        }
        x.fillStyle = dark; x.fillRect(mid - 1, mid - 1, 3, 3);
        x.fillRect(mid - 1, mid + 1, 1, R + 14); x.fillRect(mid + 1, mid + 1, 1, R + 14);
        for (let k = 0; k < 10; k++) { x.fillRect(mid - 2 - k, mid + R + 14 - k * 0, 1, 1); }
        x.fillRect(mid - 7, mid + R + 12, 15, 2);
      });
      frames.push(c);
    }
    return { frames, mid, size };
  }

  /* ---- the harbour: a sky with weather, a shore, the sea with its traffic, the pier with a crowd in two tiers and its little stories, a deck, and in front a quay edge over the water */
  const HARBOUR = { horizon: 52, edge: 34, deck: 18, front: 52 };
  const SEA = { top: '#4fa8d4', mid: '#2f86b8', deep: '#1d5f8c', glint: '#bfe8f4' };
  const WOOD = ['#b08048', '#a2733f'], WOOD_LINE = '#6a4422', WOOD_HI = '#cfa066';
  const BUNTING_COLOURS = ['#e8453c', '#f5c12e', '#f4f4ec', '#2f7fd0'];

  function makeHarbour(rand, variant) {
    const weather = weighted(rand, [['clear', 4], ['rainbow', 2], ['storm', 2], ['streaks', 2]]);
    const st = { kind: 'harbour', variant, sky: makeSky(rand, weather), skyline: makeSkyline(rand), boats: [], crowd: [], gulls: [], steal: null, stealIn: 900 + Math.floor(rand() * 900), ferry: { on: false, wait: 200 + Math.floor(rand() * 300), x: 0, dir: 1 }, smoke: [], notes: [],
      crane: { loaded: 0, cycle: 0, t: Math.floor(rand() * 600) }, splashes: [], rowX: Math.floor(rand() * 300), drop: { phase: 'none', wait: 700 + Math.floor(rand() * 700) }, fish: { phase: 'wait', t: 0, wait: 300 + Math.floor(rand() * 400) }, cat: { x: 54, dir: 1, mode: 'sit', t: 0, wait: 120 }, balloons: { free: false, t: 0 },
      wind: 0, cheer: 0, shock: 0 };
    const boatKinds = ['boat-sail-0', 'boat-sail-1', 'boat-sail-0'];
    for (let i = 0; i < 3; i++) st.boats.push({ x: 30 + i * 110 + between(rand, -20, 20), row: 4 + i * 4, kind: boatKinds[i], speed: between(rand, 0.03, 0.08) * (rand() < 0.5 ? -1 : 1), bob: rand() * 6 });
    if (variant === 1) st.boats.push({ x: 40, row: 3, kind: 'prop-ship', speed: 0, bob: 0 });
    // the crowd: two tiers of fans of the two fighters, with the little stories among them at their own places
    const place = (tier, x0, x1, gap) => { for (let x = x0; x < x1; x += gap + Math.floor(rand() * 10)) st.crowd.push({ type: 'fan', tier, x, kind: CROWD_KINDS[Math.floor(rand() * CROWD_KINDS.length)], ph: Math.floor(rand() * 32), flag: rand() < 0.22 ? (rand() < 0.5 ? 'codex' : 'claude') : null, lag: Math.floor(rand() * 5), hop: rand() < 0.4 }); };
    place(0, 16, ARENA.width - 8, 25);
    place(1, 28, ARENA.width - 20, 25);
    const slots = variant === 0 ? { band: 78, dancers: 196, fisher: 262, kids: 22, cat: 54 } : { band: 236, dancers: 66, fisher: 292, kids: 150, cat: 196 };
    st.slots = slots;
    st.crowd = st.crowd.filter((c) => !(c.tier === 0 && (Math.abs(c.x - slots.band) < 44 || Math.abs(c.x - slots.dancers) < 22 || Math.abs(c.x - slots.fisher) < 18 || Math.abs(c.x - slots.kids) < 22)));
    for (let i = 0; i < 3; i++) st.gulls.push({ x: rand() * W, y: 14 + rand() * 30, dir: i % 2 ? -1 : 1, speed: 0.4 + rand() * 0.3, phase: Math.floor(rand() * 4), bob: rand() * 6 });
    return st;
  }

  function buildHarbourLayers(s, st, light, name) {
    const tint = light.tint, haze = light.haze, F = ARENA.width;
    switch (name) {
      case 'far': return bakeSkyline(s, st.skyline.far, [92, 112, 168], 0.45, false, light, 74);
      case 'near': return bakeSkyline(s, st.skyline.near, [44, 52, 100], 0.2, true, light, 60);
      case 'wheel': return bakeWheel(s, light);
      case 'sea': {
        const sea = [SEA.top, SEA.mid, SEA.deep].map((c) => mulRgb(mixRgb(rgb(c), light.sky[5], 0.22), tint)), seaH = HARBOUR.horizon - HARBOUR.edge + 6;
        return bake(s, F, seaH, (x) => {
          for (let y = 0, k = 0; y < seaH; y += 3, k++) { x.fillStyle = css(sea[Math.min(2, Math.floor((y / seaH) * 3))]); x.fillRect(0, y, F, Math.min(3, seaH - y)); }
          x.fillStyle = css(mixRgb(sea[0], light.haze, 0.5)); x.fillRect(0, 0, F, 1);
          for (let i = 0; i < 46; i++) { const h = Math.imul(i * 7919 + 13, 2654435761) >>> 0, y = 2 + (h % (seaH - 3)); x.fillStyle = css(mixRgb(sea[Math.min(2, Math.floor(y / seaH * 3))], [255, 255, 255], 0.1)); x.fillRect((h >> 8) % F, y, 4 + (h >> 4) % 6, 1); }
        });
      }
      case 'glint': {
        const seaH = HARBOUR.horizon - HARBOUR.edge + 6, col = css(mulRgb(mixRgb(rgb(SEA.glint), light.sun, 0.25), tint));
        return bake(s, F + 40, seaH, (x) => { x.fillStyle = col; for (let y = 2; y < seaH - 2; y += 3) { const h = Math.imul(y * 7919 + 5, 2654435761) >>> 0, h2 = Math.imul(y * 104729 + 9, 2246822519) >>> 0; x.fillRect(h % F, y, 3 + (y >> 3), 1); x.fillRect(h2 % F, y, 2 + (y >> 4), 1); } });
      }
      case 'deck': return bakeDeck(s, st, light);
      case 'edge': return bakeEdge(s, st, light);
      case 'bunting': return buildBunting(s, tint);
      case 'front': return bakeFront(s, st, light);
      case 'wake': return bake(s, 30, 5, (x) => { x.fillStyle = 'rgba(255,255,255,0.85)'; x.fillRect(0, 2, 30, 1); x.fillStyle = 'rgba(255,255,255,0.55)'; x.fillRect(4, 1, 20, 1); x.fillRect(6, 3, 18, 1); x.fillStyle = 'rgba(255,255,255,0.3)'; x.fillRect(10, 0, 12, 1); x.fillRect(12, 4, 10, 1); });
      case 'dinghy': return bakeDinghy(s, light);
      case 'frontglint': { const col = css(mixRgb(light.sun, [255, 255, 255], 0.3)); return bake(s, W + 40, 190, (x) => { x.fillStyle = col; for (let y = 14; y < 190; y += 5) { const h = Math.imul(y * 7919 + 3, 2654435761) >>> 0, h2 = Math.imul(y * 104729 + 7, 2246822519) >>> 0; x.fillRect(h % (W + 20), y, 5 + (y >> 4), 1); x.fillRect(h2 % (W + 20), y + 2, 4 + (y >> 5), 1); } }); }
      case 'lighthouse': return bakeLighthouse(s, light);
      case 'crane': return bakeCrane(s, st, light);
      case 'storm': return bakeStorm(s, light);
      case 'rain': return bake(s, 60, 40, (x) => { x.fillStyle = 'rgba(190,205,230,0.55)'; for (let i = 0; i < 36; i++) { const h = Math.imul(i * 2654435761 + 3, 2246822519) >>> 0; x.fillRect(h % 58, (h >> 8) % 36, 1, 4); x.fillRect((h % 58) - 1, ((h >> 8) % 36) + 4, 1, 1); } });
      default: return null;
    }
  }
  function bakeDeck(s, st, light) {
    const tint = light.tint, F = ARENA.width, dh = HARBOUR.edge + HARBOUR.front + 24;
    const A = mulRgb(rgb(WOOD[0]), tint), B = mulRgb(rgb(WOOD[1]), tint), L = mulRgb(rgb(WOOD_LINE), tint), HI = mulRgb(rgb(WOOD_HI), tint), sky = mixRgb(light.sky[3], [255, 255, 255], 0.2);
    return bake(s, F, dh, (x) => {
      for (let r = 0, y = 0; y < dh; r++, y += 10) {
        const jitter = (Math.imul(r * 7 + 3, 2654435761) >>> 0) % 3;
        x.fillStyle = css(mixRgb(r & 1 ? B : A, jitter === 0 ? [0, 0, 0] : jitter === 1 ? HI : r & 1 ? A : B, 0.07)); x.fillRect(0, y, F, 10);
        x.fillStyle = css(HI); x.fillRect(0, y, F, 1);
        x.fillStyle = css(L); x.fillRect(0, y + 9, F, 1);
        for (let jx = (r * 53) % 71; jx < F; jx += 71) { x.fillStyle = css(L); x.fillRect(jx, y + 1, 1, 8); x.fillStyle = css(HI); x.fillRect(jx + 1, y + 1, 1, 1); }
        for (let k = 0; k < 4; k++) {
          const h = Math.imul(r * 131 + k * 977, 2654435761) >>> 0;
          x.fillStyle = css(mixRgb(A, L, 0.45)); x.fillRect(h % F, y + 2 + (h >> 9) % 5, 2 + (h >> 5) % 3, 1);
          if (k === 0) { x.fillStyle = css(L); x.fillRect((h >> 3) % F, y + 4, 2, 2); x.fillStyle = css(HI); x.fillRect((h >> 3) % F, y + 4, 1, 1); }          // a knot
        }
        for (let nx = 5 + (r * 17) % 23; nx < F; nx += 23) { x.fillStyle = css(mixRgb(L, A, 0.4)); x.fillRect(nx, y + 3, 1, 1); x.fillRect(nx, y + 7, 1, 1); }                                      // nails
      }
      // the stage floor below the fighters' row (28) down to the quay's lip (80): wet patches that hold the sky and the lamps, a coil of rope, a fish net, a chalk line, a drain, stains, scales, a hatch
      const spans = (cx, cy, rx, ry, c) => { x.fillStyle = c; for (let yy = -ry; yy <= ry; yy++) { const h = Math.floor(rx * Math.sqrt(Math.max(0, 1 - (yy / (ry + 0.6)) ** 2)) + 0.5); x.fillRect(cx - h, cy + yy, h * 2 + 1, 1); } };
      const wet = mixRgb(A, [24, 34, 60], 0.42), sky2 = mixRgb(light.sky[3], [255, 255, 255], 0.22), sky3 = mixRgb(light.sky[1], light.sky[3], 0.4);
      for (const [px, py, rx, ry] of [[46, 40, 22, 3], [150, 56, 26, 4], [244, 44, 28, 4], [96, 70, 24, 3], [282, 66, 18, 3], [200, 74, 22, 2]]) {
        spans(px, py, rx + 1, ry + 1, css(wet));
        spans(px, py, rx - 1, ry, css(sky3));
        spans(px, py - 1, rx - 3, Math.max(1, ry - 1), css(sky2));
        x.fillStyle = 'rgba(255,255,255,0.55)'; x.fillRect(px - rx + 5, py - 1, Math.max(3, rx - 4), 1);
        if (light.lamps > 0.3) { x.fillStyle = 'rgba(255,214,140,' + 0.4 * light.lamps + ')'; x.fillRect(px - 5, py, 10, 1); x.fillRect(px - 3, py + 1, 6, 1); }
      }
      const rope = mulRgb([206, 176, 112], tint), ropeDk = mulRgb([130, 100, 62], tint);                                              // a coil of rope
      for (let k = 0; k < 4; k++) { x.fillStyle = css(k & 1 ? rope : ropeDk); spans(126, 56, 12 - k * 2, 4 - (k >> 1), css(k & 1 ? rope : ropeDk)); }
      spans(126, 56, 2, 1, css(mulRgb([40, 34, 28], tint)));
      x.fillStyle = css(rope); x.fillRect(139, 58, 14, 1); x.fillRect(153, 59, 6, 1);
      const net = mulRgb([150, 128, 84], tint), netDk = mulRgb([88, 70, 44], tint);                                                  // a heap of net
      x.fillStyle = css(netDk); x.fillRect(12, 56, 36, 14); x.fillStyle = css(mixRgb(net, netDk, 0.3)); x.fillRect(13, 57, 34, 12);
      x.fillStyle = css(net); for (let yy = 57; yy < 69; yy += 3) for (let xx = 13 + ((yy / 3 | 0) & 1) * 2; xx < 47; xx += 4) { x.fillRect(xx, yy, 1, 3); x.fillRect(xx + 1, yy + 1, 2, 1); }
      x.fillStyle = css(mulRgb([200, 70, 50], tint)); x.fillRect(16, 59, 3, 3); x.fillRect(40, 63, 3, 3);                              // two cork floats
      x.fillStyle = css(mulRgb([232, 214, 150], tint)); x.fillRect(0, 76, F, 1); for (let k = 0; k < F; k += 14) { x.fillStyle = css(mulRgb([232, 214, 150], tint)); x.fillRect(k, 77, 7, 1); }    // the chalk line at the quay's lip
      x.fillStyle = css(mulRgb([68, 60, 54], tint)); x.fillRect(218, 52, 16, 10); x.fillStyle = css(mulRgb([22, 20, 24], tint)); for (let k = 0; k < 5; k++) x.fillRect(220 + k * 3, 53, 1, 8); x.fillStyle = css(mulRgb([110, 104, 98], tint)); x.fillRect(218, 52, 16, 1);   // a drain
      x.fillStyle = css(mulRgb([50, 36, 24], tint), 0.5); for (const [px, py, w] of [[22, 36, 10], [172, 44, 8], [268, 52, 9], [74, 76, 12], [250, 70, 11]]) x.fillRect(px, py, w, 2);        // oil stains
      x.fillStyle = css(mulRgb([196, 206, 224], tint)); for (let k = 0; k < 34; k++) { const h = Math.imul(k * 2654435761 + 17, 2246822519) >>> 0; x.fillRect(h % F, 30 + (h >> 9) % 46, 1, 1); }      // fish scales
      const hatch = mulRgb([100, 70, 40], tint), hatchHi = mulRgb([156, 112, 66], tint);                                             // a hatch with an iron ring
      x.fillStyle = css(mulRgb([40, 28, 18], tint)); x.fillRect(264, 44, 22, 14); x.fillStyle = css(hatch); x.fillRect(265, 45, 20, 12); x.fillStyle = css(hatchHi); x.fillRect(265, 45, 20, 1); x.fillRect(274, 45, 1, 12);
      x.fillStyle = css(mulRgb([40, 44, 58], tint)); spans(279, 51, 2, 2, css(mulRgb([40, 44, 58], tint)));
      for (const [name, wx, row] of [['prop-crate', 58, 68], ['prop-barrel', 80, 72], ['prop-crate', 58, 47], ['prop-bollard', 150, 76], ['prop-barrel', 248, 70], ['prop-crate', 272, 74], ['prop-bollard', 196, 78]]) {
        const e = s.lib && s.lib.entry(name);
        if (e) x.drawImage(s.sheetBG || s.atlas, e.x, e.y, e.w, e.h, Math.round(wx - e.ax), Math.round(row - e.ay), e.w, e.h);
      }
    });
  }
  function bakeEdge(s, st, light) {
    const tint = light.tint, F = ARENA.width;
    return bake(s, F, 30, (x) => {
      const beam = mulRgb([86, 56, 30], tint), beamHi = mulRgb([140, 96, 54], tint), iron = mulRgb([38, 44, 58], tint), rope = mulRgb([208, 180, 120], tint), ropeDk = mulRgb([140, 112, 70], tint);
      x.fillStyle = css(beam); x.fillRect(0, 22, F, 8);
      x.fillStyle = css(beamHi); x.fillRect(0, 22, F, 1);
      for (let px = 6; px < F; px += 24) { x.fillStyle = css(iron); x.fillRect(px, 4, 3, 19); x.fillStyle = css(beamHi); x.fillRect(px, 4, 3, 1); }
      for (let px = 6; px + 24 < F; px += 24) {                                                                                         // a rope slung from post to post
        for (let k = 0; k <= 24; k++) { const sag = Math.round(Math.sin(k / 24 * Math.PI) * 4); x.fillStyle = css(k % 3 ? rope : ropeDk); x.fillRect(px + 3 + k, 8 + sag, 1, 2); }
      }
      for (const px of [78, 190]) { x.fillStyle = css(mulRgb([230, 80, 60], tint)); disc(x, px + 1, 17, 3); x.fillStyle = css(mulRgb([250, 244, 236], tint)); x.fillRect(px - 2, 16, 7, 2); x.fillStyle = css(beam); disc(x, px + 1, 17, 1); } // life rings
      x.fillStyle = css(mixRgb(beam, [220, 200, 150], 0.35));
      for (let px = 0; px < F; px++) x.fillRect(px, 25 + Math.round(Math.sin(px * 0.13) * 1.4), 1, 1);
    });
  }
  function bakeFront(s, st, light) {
    const tint = light.tint, F = ARENA.width + 80, hh = 190;
    const sea = [SEA.top, SEA.mid, SEA.deep].map((c) => mulRgb(mixRgb(rgb(c), light.sky[4], 0.12), tint.map((v, i) => v * [0.8, 0.86, 0.9][i])));
    return bake(s, F, hh, (x) => {
      const beam = mulRgb([90, 58, 28], tint), lip = mulRgb([154, 116, 64], tint), under = mulRgb([34, 22, 12], tint), iron = mulRgb([38, 44, 58], tint);
      x.fillStyle = css(beam); x.fillRect(0, 0, F, 6); x.fillStyle = css(lip); x.fillRect(0, 0, F, 1); x.fillStyle = css(mulRgb([60, 38, 20], tint)); x.fillRect(0, 5, F, 1);
      x.fillStyle = css(under); x.fillRect(0, 6, F, 5);
      for (let px = 10; px < F; px += 36) { x.fillStyle = css(iron); x.fillRect(px, 0, 4, 12); x.fillStyle = css(mulRgb([122, 132, 152], tint)); x.fillRect(px, 0, 1, 12); }
      for (let y = 11, k = 0; y < hh; k++, y += 6) { x.fillStyle = css(sea[Math.min(2, k >> 2)]); x.fillRect(0, y, F, Math.min(6, hh - y)); }
      for (let i = 0; i < 90; i++) { const h = Math.imul(i * 7919 + 21, 2654435761) >>> 0, y = 13 + (h % (hh - 14)); x.fillStyle = css(mixRgb(sea[Math.min(2, (y - 11) / 24 | 0)], [255, 255, 255], 0.14)); x.fillRect((h >> 8) % F, y, 4 + (h >> 4) % 9, 1); }
      x.fillStyle = css(mixRgb(sea[0], [10, 20, 40], 0.5)); for (let px = 10; px < F; px += 36) x.fillRect(px - 1, 12, 6, 3);                       // the posts' shadows on the water
    });
  }
  /** A little rowing boat with a lantern at its bow (the front water's traffic): two bobbing frames. */
  function bakeDinghy(s, light) {
    const tint = light.tint, hull = css(mulRgb([150, 94, 52], tint)), hullHi = css(mulRgb([200, 140, 84], tint)), hullLo = css(mulRgb([84, 50, 28], tint)), stripe = css(mulRgb([240, 236, 224], tint)), red = css(mulRgb([196, 56, 46], tint)), iron = css(mulRgb([40, 44, 58], tint));
    return [0, 1].map((f) => bake(s, 48, 26, (x) => {
      const y0 = 12 + f;
      x.fillStyle = hullLo; for (let k = 0; k < 6; k++) x.fillRect(4 + k + (k > 3 ? 0 : 0), y0 + 5 + k - 3 + 3, 40 - 2 * k - 2, 1);
      x.fillStyle = hull; x.fillRect(2, y0, 44, 5); x.fillRect(4, y0 + 5, 40, 2); x.fillRect(7, y0 + 7, 34, 1);
      x.fillStyle = hullHi; x.fillRect(2, y0, 44, 1); x.fillStyle = stripe; x.fillRect(2, y0 + 1, 44, 1); x.fillStyle = red; x.fillRect(2, y0 + 2, 44, 1);
      x.fillStyle = hullLo; for (let px = 8; px < 44; px += 8) x.fillRect(px, y0 + 3, 1, 4);
      x.fillStyle = hull; x.fillRect(0, y0 - 2, 3, 3); x.fillRect(45, y0 - 2, 3, 3);                         // bow and stern
      x.fillStyle = hullLo; x.fillRect(14, y0 - 1, 20, 2);                                                  // a seat
      x.fillStyle = iron; x.fillRect(2, y0 - 9, 1, 8); x.fillRect(2, y0 - 10, 4, 1); x.fillStyle = css([255, 224, 140]); x.fillRect(4, y0 - 9, 2, 3);        // the lantern on its post
      x.fillStyle = css(mulRgb([120, 84, 52], tint)); x.fillRect(22 + f, y0 - 6, 1, 10); x.fillRect(22 + f, y0 + 3, 7, 1); x.fillRect(29 + f, y0 + 3, 2, 2);  // an oar
    }));
  }
  function bakeLighthouse(s, light) {
    const tint = light.tint;
    return bake(s, 40, 78, (x) => {
      const white = css(mulRgb([238, 232, 222], tint)), red = css(mulRgb([200, 56, 48], tint)), dark = css(mulRgb([44, 52, 76], tint)), rock = css(mulRgb([70, 66, 74], tint)), rockHi = css(mulRgb([104, 98, 106], tint)), cx = 20, base = 74;
      x.fillStyle = rock; x.fillRect(cx - 13, base - 5, 26, 5); x.fillRect(cx - 9, base - 8, 18, 3); x.fillRect(cx - 5, base - 10, 10, 2);
      x.fillStyle = rockHi; x.fillRect(cx - 13, base - 5, 26, 1); x.fillRect(cx - 9, base - 8, 18, 1); x.fillRect(cx - 3, base - 10, 5, 1);
      for (let k = 0; k < 6; k++) { x.fillStyle = k & 1 ? red : white; const w = 11 - (k >> 1); x.fillRect(cx - (w >> 1), base - 18 - k * 6, w, 6); x.fillStyle = css(mulRgb([0, 0, 0], tint), 0.18); x.fillRect(cx + (w >> 1) - 2, base - 18 - k * 6, 2, 6); }
      x.fillStyle = dark; x.fillRect(cx - 6, base - 56, 13, 3); x.fillRect(cx - 5, base - 64, 11, 3); x.fillStyle = css([255, 236, 150]); x.fillRect(cx - 3, base - 61, 7, 5);
      x.fillStyle = dark; for (let k = 0; k < 5; k++) x.fillRect(cx - 4 + k, base - 69 + k * 0, 1, 1); x.fillRect(cx - 4, base - 66, 9, 2); x.fillRect(cx - 2, base - 69, 5, 3); x.fillRect(cx, base - 72, 1, 3);
      x.fillStyle = dark; x.fillRect(cx - 1, base - 26, 3, 4);
    });
  }
  function bakeCrane(s, st, light) {
    const tint = light.tint;
    return bake(s, 130, 100, (x) => {
      const steel = css(mulRgb([62, 74, 98], tint)), hi = css(mulRgb([200, 90, 60], tint)), pale = css(mulRgb([120, 134, 160], tint));
      x.fillStyle = steel; x.fillRect(48, 22, 4, 76); x.fillRect(64, 22, 4, 76); x.fillRect(48, 22, 20, 3); x.fillRect(48, 50, 20, 2); x.fillRect(48, 74, 20, 2);
      for (let y = 26; y < 96; y += 12) { for (let k = 0; k < 12; k++) { x.fillRect(52 + Math.round(k * 12 / 12), y + k, 1, 1); x.fillRect(63 - k, y + k, 1, 1); } }
      x.fillStyle = steel; x.fillRect(6, 18, 118, 4); x.fillRect(6, 22, 118, 1);
      x.fillStyle = hi; x.fillRect(4, 16, 8, 3); x.fillRect(46, 8, 24, 8); x.fillStyle = css(mulRgb([255, 236, 150], tint)); x.fillRect(48, 10, 6, 4);
      x.fillStyle = steel; for (let k = 0; k < 28; k++) { x.fillRect(58 + k * 2, 17 - Math.floor(k * 9 / 28), 2, 1); }
      x.fillRect(10, 14, 1, 4); x.fillRect(110, 14, 1, 4);
      x.fillStyle = pale; x.fillRect(6, 18, 118, 1);
      x.fillStyle = css(mulRgb([30, 36, 56], tint)); x.fillRect(44, 96, 28, 4);
    });
  }
  function bakeStorm(s, light) {
    const tint = light.tint, base = mulRgb([54, 60, 86], tint), mid = mulRgb([84, 94, 126], tint), hi = mixRgb(mulRgb([156, 166, 196], tint), light.sun, 0.2);
    return bake(s, 190, 62, (x) => {
      const puffs = [[28, 44, 11], [50, 38, 15], [76, 32, 17], [102, 26, 19], [128, 31, 16], [152, 38, 13], [172, 44, 10]];
      x.fillStyle = css(base); x.fillRect(8, 44, 176, 12);
      for (const [cx, cy, r] of puffs) disc(x, cx, cy, r);
      x.fillStyle = css(mid); for (const [cx, cy, r] of puffs) disc(x, cx - 2, cy - 3, r - 3);
      x.fillStyle = css(base); x.fillRect(60, 12, 90, 4); x.fillRect(48, 14, 110, 3);                                              // the anvil spreads at the top
      x.fillStyle = css(mid); x.fillRect(56, 9, 94, 3); x.fillStyle = css(hi); x.fillRect(66, 8, 70, 1);
      x.fillStyle = css(hi); for (const [cx, cy, r] of puffs) { disc(x, cx - 4, cy - r + 6, Math.max(2, r - 10)); }
      x.fillStyle = css(base); x.fillRect(8, 52, 176, 10);
      x.fillStyle = css(mixRgb(base, [20, 24, 44], 0.5)); for (let k = 0; k < 9; k++) x.fillRect(16 + k * 19, 50, 8, 8);
    });
  }

  /** Two strings of pennants across the pier, drawn once per sway phase (four of them, the flaps move a pixel) and per light, then copied. */
  function buildBunting(s, tint) {
    const out = [];
    const colours = BUNTING_COLOURS.map((c) => css(mulRgb(rgb(c), tint))), string = css(mulRgb([40, 40, 52], tint));
    for (let sway = 0; sway < 4; sway++) {
      const [c, x] = makeCanvas(s.doc, ARENA.width, 24);
      if (!x) { out.push(null); continue; }
      for (const [from, to] of [[8, 110], [110, 214], [214, ARENA.width - 8]]) {
        for (let px = from + 4; px < to - 2; px += 7) {
          const t = (px - from) / (to - from), sag = Math.round(Math.sin(Math.PI * t) * 9), flap = ((px >> 3) + sway) & 3 ? 0 : 1, lean = sway === 1 || sway === 3 ? 1 : 0;
          x.fillStyle = colours[(px >> 3) & 3]; x.fillRect(px + lean, sag + 1, 4, 4 + flap); x.fillRect(px + 1 + lean, sag + 5 + flap, 2, 1);
          x.fillStyle = string; x.fillRect(px, sag, 4, 1);
        }
      }
      out.push(c);
    }
    return out;
  }

  /* ---- the little stories: a sailor band, a dancing couple, a fisherman who catches a boot or a fish, a cat, kids on a crate, a gull that steals a fish, balloons, a ferry, a crane */
  const BAND = { x: [-24, 0, 24], base: 13 };
  function harbourCue(s, st, cue) {
    const m = s.m;
    if (cue.type === 'ko') { st.fish.phase = 'cheer'; st.fish.t = 0; st.balloons.free = true; st.balloons.t = 0; st.cat.mode = 'run'; st.cat.t = 0; }
    if (cue.type === 'hit' && cue.heavy) { st.cat.mode = st.cat.mode === 'run' ? 'run' : 'arch'; st.cat.t = 0; st.shock = 16; }
    if (cue.type === 'special') st.shock = 24;
  }
  function stepHarbour(s, st) {
    const m = s.m, steps = m.steps, rect = st;
    stepSky(s, st.sky, m, { rand: st.rand });
    st.wind = Math.sin(steps * 0.011) + 0.5 * Math.sin(steps * 0.037 + 1.3);
    if (st.shock > 0) st.shock--;
    for (const g of st.gulls) { g.x += g.dir * g.speed; if ((steps & 3) === 0) g.phase = (g.phase + 1) & 3; if (g.x > W + 20 || g.x < -20) { g.dir = -g.dir; g.y = 14 + (steps * 7 % 30); } }
    for (const b of st.boats) b.x += b.speed;
    const sky = st.sky, light = s.light;
    if (sky.weather === 'storm') {
      if (sky.bolt) { sky.bolt.t++; if (sky.bolt.t >= sky.bolt.dur) sky.bolt = null; }
      else if (--sky.boltIn <= 0) {
        sky.boltIn = 260 + Math.floor(st.rand() * 520);
        const x0 = 80 + Math.floor(st.rand() * 70), pts = [];
        for (let y = 0, x = x0; y < 60; y += 4) { pts.push([x, y]); x += Math.floor(st.rand() * 7) - 3; }
        sky.bolt = { t: 0, dur: 9, points: pts, x0 };
      }
    }
    // the ferry crosses every minute or so
    const f = st.ferry;
    if (f.on) { f.x += f.dir * 0.42; f.t++; if (f.t % 5 === 0 && st.smoke.length < 8) st.smoke.push({ x: f.x - f.dir * 8, y: -17, t: 0 }); if (f.x > W + 140 || f.x < -140) { f.on = false; f.wait = 1500 + Math.floor(st.rand() * 1500); } }
    else if (--f.wait <= 0) { f.on = true; f.t = 0; f.dir = st.rand() < 0.5 ? 1 : -1; f.x = f.dir > 0 ? -90 : W + 90; }
    for (let i = st.smoke.length - 1; i >= 0; i--) { const p = st.smoke[i]; p.t++; p.x += st.wind * 0.1 - f.dir * 0.1; p.y -= 0.12; if (p.t > 50) st.smoke.splice(i, 1); }
    // the band's notes drift up
    const tempo = bandBeat(m);
    if (steps % (tempo * 2) === 0 && st.notes.length < 5) st.notes.push({ x: st.slots.band + BAND.x[1], y: 0, t: 0, k: (steps / tempo | 0) & 1, ph: Math.random ? 0 : 0 });
    for (let i = st.notes.length - 1; i >= 0; i--) { const n = st.notes[i]; n.t++; n.y -= 0.35; if (n.t > 46) st.notes.splice(i, 1); }
    // a gull swoops down for the fisherman's fish
    if (st.steal) { st.steal.t++; if (st.steal.t > 170) st.steal = null; }
    else if (st.variant === 0 && m.phase === 'fight' && --st.stealIn <= 0) { st.stealIn = 1300 + Math.floor(st.rand() * 1400); st.steal = { t: 0, dir: st.rand() < 0.5 ? 1 : -1, y0: 20 + Math.floor(st.rand() * 14) }; }
    // the fisherman: waits, gets a bite, hauls up a fish (or a boot), now and then
    const fi = st.fish;
    fi.t++;
    if (fi.phase === 'wait' && fi.t > fi.wait) { fi.phase = 'bite'; fi.t = 0; }
    else if (fi.phase === 'bite' && fi.t > 26) { fi.phase = 'catch'; fi.t = 0; fi.boot = st.rand() < 0.3; }
    else if (fi.phase === 'catch' && fi.t > 60) { fi.phase = 'wait'; fi.t = 0; fi.wait = 600 + Math.floor(st.rand() * 700); }
    else if (fi.phase === 'cheer' && fi.t > 120) { fi.phase = 'wait'; fi.t = 0; fi.wait = 400; }
    // the cat sits, licks, walks along the rail, arches at a heavy blow and runs from a knock-out
    const c = st.cat;
    c.t++;
    if (c.mode === 'sit' && c.t > c.wait) { c.t = 0; c.mode = st.rand() < 0.4 ? 'lick' : st.rand() < 0.6 ? 'walk' : 'sleep'; c.wait = 60 + Math.floor(st.rand() * 160); if (c.mode === 'walk') c.dir = c.x < 60 ? 1 : st.rand() < 0.5 ? 1 : -1; }
    else if ((c.mode === 'lick' || c.mode === 'sleep') && c.t > c.wait) { c.t = 0; c.mode = 'sit'; c.wait = 90 + Math.floor(st.rand() * 160); }
    else if (c.mode === 'walk') { c.x += c.dir * 0.3; if (c.x > 92) c.dir = -1; if (c.x < 24) c.dir = 1; if (c.t > 150) { c.t = 0; c.mode = 'sit'; c.wait = 80; } }
    else if (c.mode === 'arch' && c.t > 26) { c.t = 0; c.mode = 'sit'; c.wait = 60; }
    else if (c.mode === 'run') { c.x += 1.2; if (c.x > 330 || c.t > 140) { c.x = 54; c.t = 0; c.mode = 'sit'; c.wait = 200; } }
    // the balloons
    if (st.balloons.free) { st.balloons.t++; if (st.balloons.t > 240) { st.balloons.free = false; st.balloons.t = 0; } }
    // the crane
    st.crane.t++;
    const slip = st.variant === 1 && st.crane.cycle % 3 === 1;
    if (slip && st.crane.t === 756 + 15) { st.splashes.push({ t: 0, tx: craneAt(756, true).tx }); m.crowd.mood = 'gasp'; m.crowd.t = 26; st.shock = 10; }
    if (st.crane.t >= 1260) { st.crane.t = 0; st.crane.cycle++; if (!slip) st.crane.loaded = (st.crane.loaded + 1) % 4; }
    for (let i = st.splashes.length - 1; i >= 0; i--) { st.splashes[i].t++; if (st.splashes[i].t > 26) st.splashes.splice(i, 1); }
    // the crane drops a crate in the foreground (harmlessly) and picks it up again: `h` is the crate's height over the spot where it lands
    const d = st.drop;
    if (d.phase === 'none') { if (st.variant === 1 && m.phase === 'fight' && --d.wait <= 0) { const spot = [176, 186].map((cx) => [cx, Math.min(...m.f.map((f) => Math.abs(f.x - m.camX - cx)))]).sort((a, b) => b[1] - a[1])[0];   // the right edge only: the page's date and clock sit at the left
      if (spot[1] < 52) d.wait = 90; else { d.phase = 'down'; d.t = 0; d.x = spot[0]; d.cam = m.camX; d.h = 200; d.vy = 0; d.wait = 1500 + Math.floor(st.rand() * 1500); } } }
    else {
      d.t++;
      if (d.phase === 'down') { d.h = lerp(200, 104, smooth(clamp(d.t / 44, 0, 1))); if (d.t > 44) { d.phase = 'fall'; d.t = 0; d.vy = 0; } }
      else if (d.phase === 'fall') { d.vy += 0.5; d.h -= d.vy; if (d.h <= 0) { d.h = 0; d.phase = 'bounce'; d.t = 0; d.vy = 2.6; const wx = d.x + Math.round(m.camX); m.addFx('dust', wx - 8, -46); m.addFx('dust', wx + 8, -46, { rate: 2 }); st.shock = 14; m.crowd.mood = 'gasp'; m.crowd.t = 24; } }
      else if (d.phase === 'bounce') { d.h += d.vy; d.vy -= 0.45; if (d.h <= 0) { d.h = 0; d.phase = 'rest'; d.t = 0; } }
      else if (d.phase === 'rest' && d.t > 120) { d.phase = 'up'; d.t = 0; }
      else if (d.phase === 'up') { d.h = lerp(0, 230, smooth(clamp(d.t / 70, 0, 1))); if (d.t > 70) d.phase = 'none'; }
    }
  }
  /** A beat of the band in steps: calm, quicker when the crowd cheers, quickest in the last ten seconds of a round. */
  function bandBeat(m) { return m.phase === 'fight' && m.clock <= 10 && m.clock > 0 ? 3 : m.crowd.mood === 'cheer' ? 4 : 6; }
  function bandPose(m, ph) { return Math.floor((m.steps + ph) / bandBeat(m)) & 1; }

  /** The crowd of the harbour: fans in two tiers (baked strips while the crowd is calm, live sprites while it cheers or gasps) and the stories at their places. */
  const fanGroup = (fan) => (((fan.ph || 0) + (fan.lag || 0)) >> 3) & 3;
  /** A calm fan's pose in variant v (v = (steps >> 3) & 3): two bobs, a group of fans offset from the next by eight steps. */
  const idlePoseOf = (fan, v) => (((v + fanGroup(fan)) & 3) >> 1 ? 'idle1' : 'idle0');
  function fanPose(m, fan) {
    const mood = m.crowd.mood;
    if (mood === 'cheer') return ((m.steps + fan.ph) >> 2) & 1 ? 'cheer1' : 'cheer0';
    if (mood === 'gasp') return 'gasp';
    return idlePoseOf(fan, (m.steps >> 3) & 3);
  }
  const HIDE = { halfW: 22, top: 62 };
  /** Whether a sprite whose box is (sx - w/2 .. sx + w/2) x (y - h .. y) lies wholly behind a standing fighter's body (so it need not be drawn). */
  function hiddenBehind(s, m, cam, sx, y, w, h, feet) {
    for (const f of m.f) {
      if (f.state === 'kd' || f.state === 'getup') continue;
      const fx = f.x - cam;
      if (sx - w / 2 > fx - HIDE.halfW && sx + w / 2 < fx + HIDE.halfW && y - h > feet - HIDE.top && y < feet - 4) return true;
    }
    return false;
  }
  function drawFan(g, s, m, cam, fan, y, par) {
    const sx = Math.round(fan.x - cam * par);
    if (sx < -16 || sx > W + 16 || hiddenBehind(s, m, cam, sx, y, 26, 25, s.feet)) return;
    const pose = fanPose(m, fan), e = s.lib.entry('crowd-' + fan.kind + '-' + pose), hop = pose === 'cheer1' && fan.hop ? 2 : 0;
    blit(g, s.sheetBG || s.atlas, e, sx, y - hop);
    if (fan.flag) put(g, s, s.lib.actor('flag-' + fan.flag, m.crowd.mood === 'cheer' ? (m.steps >> 2) & 1 : (m.steps >> 4) & 1), sx + (fan.flag === 'codex' ? -9 : 9), y - 11 - hop);
  }
  /** One tier of the crowd, baked for one phase of the bobbing: 320 wide, the fans' feet on row 36. */
  function bakeCrowd(s, fans, tier, v, light) {
    const lib = s.lib, sheet = s.sheetBG || s.atlas;
    return bake(s, ARENA.width, 44, (x) => {
      for (const fan of fans) {
        if (fan.tier !== tier) continue;
        const e = lib.entry('crowd-' + fan.kind + '-' + idlePoseOf(fan, v));
        if (!e) continue;
        x.drawImage(sheet, e.x, e.y, e.w, e.h, Math.round(fan.x - e.ax), 36 - e.ay, e.w, e.h);
        const fe = fan.flag ? lib.entry(lib.actor('flag-' + fan.flag, v & 1)) : null;
        if (fe) x.drawImage(sheet, fe.x, fe.y, fe.w, fe.h, Math.round(fan.x + (fan.flag === 'codex' ? -9 : 9) - fe.ax), 36 - 11 - fe.ay, fe.w, fe.h);
      }
      if (tier === 1) { x.globalCompositeOperation = 'source-atop'; x.fillStyle = 'rgba(14,20,50,' + (0.18 + 0.08 * light.lamps) + ')'; x.fillRect(0, 0, ARENA.width, 44); x.globalCompositeOperation = 'source-over'; }
    });
  }
  /** The crowd's two tiers: a baked strip each while it is calm, the live fans while it reacts. `rows` are the feet rows of the back and the front tier. */
  function drawCrowd(g, s, m, cam, st, light, y1, y0, tiers) {
    const key = lightKey(light), v = (m.steps >> 3) & 3;
    if (m.crowd.mood === 'idle') {
      for (const [tier, y, par] of tiers) { const c = layer(s, st, 'crowd' + tier + '_' + v, key, () => bakeCrowd(s, st.crowd, tier, v, light)); if (c) g.drawImage(c, Math.round(cam * par), 0, W, 44, 0, y - 36, W, 44); }
    } else {
      for (const [tier, y, par] of tiers) for (const fan of st.crowd) if (fan.tier === tier) drawFan(g, s, m, cam, fan, y, par);
    }
  }
  function drawHarbourCrowd(g, s, m, cam, feet, st, light) {
    const lib = s.lib, y0 = feet - 12, y1 = feet - 24, mood = m.crowd.mood;
    drawCrowd(g, s, m, cam, st, light, y1, y0, [[1, y1, 0.86], [0, y0, 0.9]]);
    const X = (x, par) => Math.round(x - cam * par);
    // the band on its stage
    const bx = X(st.slots.band, 0.9), by = y0;
    if (bx > -60 && bx < W + 60) {
      put(g, s, lib.actor('bandstand', 0), bx, by + 1);
      const sy = by - 11, names = ['drummer', 'horn', 'accordion'];
      for (let i = 0; i < 3; i++) put(g, s, lib.actor(names[i], bandPose(m, i * 2)), bx + BAND.x[i], sy);
      for (const n of st.notes) put(g, s, 'fx-note-' + n.k, bx + BAND.x[1] + Math.sin(n.t * 0.2) * 5, sy - 30 + n.y);
    }
    // the dancers
    const dx = X(st.slots.dancers, 0.9);
    if (dx > -30 && dx < W + 30 && !hiddenBehind(s, m, cam, dx, y0, 34, 30, feet)) {
      const k = mood === 'cheer' || st.shock > 0 ? [2, 3][(m.steps >> 3) & 1] : mood === 'gasp' ? 0 : [0, 1][(m.steps >> 4) & 1];
      put(g, s, lib.actor('dancers', k), dx, y0 + 1 - (st.shock > 0 && ((m.steps >> 2) & 1) ? 1 : 0));
    }
    // kids on a crate
    const kx = X(st.slots.kids, 0.9);
    if (kx > -30 && kx < W + 30 && !hiddenBehind(s, m, cam, kx, y0, 30, 28, feet)) put(g, s, lib.actor('kids', mood === 'cheer' || st.shock > 0 ? 2 : (m.steps >> 4) & 1), kx, y0 + 1);
    // the cat
    const c = st.cat, cx = X(c.x, 0.9);
    if (cx > -20 && cx < W + 20) {
      const poses = { sit: ((m.steps >> 5) & 3) === 3 ? 1 : 0, lick: 4, sleep: 6, arch: 5, walk: 2 + ((m.steps >> 2) & 1), run: 2 + ((m.steps >> 1) & 1) };
      const name = lib.actor('cat', poses[c.mode] || 0), cy = (c.mode === 'walk' || c.mode === 'run') ? y0 - 6 : y0 - 5;
      if (c.mode === 'walk' && c.dir < 0 || c.mode === 'run') putFlipped(g, s, name, cx, cy); else put(g, s, name, cx, cy);
    }
    // the fisherman at the rail, his line over the water
    const fx = X(st.slots.fisher, 0.9), fi = st.fish;
    if (fx > -40 && fx < W + 40) {
      const k = fi.phase === 'bite' ? 2 : fi.phase === 'catch' ? 3 : fi.phase === 'cheer' ? 3 : ((m.steps >> 5) & 3) === 3 ? 1 : 0;
      const name = lib.actor('fisher', k);
      if (!hiddenBehind(s, m, cam, fx, y0, 30, 30, feet)) put(g, s, name, fx, y0 + 1);
      const tip = lib.points(name)[0];
      if (tip && fi.phase !== 'catch' && fi.phase !== 'cheer') {
        const tx = fx + tip[0], ty = y0 + 1 + tip[1], water = feet - HARBOUR.horizon + 10 + (fi.phase === 'bite' ? 2 : 0);
        g.fillStyle = 'rgba(240,240,250,0.8)'; g.fillRect(tx, ty, 1, Math.max(1, water - ty));
        const bob = fi.phase === 'bite' ? ((m.steps >> 1) & 1) * 2 : (m.steps >> 4) & 1;
        g.fillStyle = '#e8453c'; g.fillRect(tx - 1, water - 1 + bob, 3, 2); g.fillStyle = '#ffffff'; g.fillRect(tx - 1, water - 1 + bob, 3, 1);
      }
      if (fi.phase === 'catch') { if (!fi.boot) put(g, s, lib.actor('fish', (m.steps >> 2) & 1), fx + 14, y0 - 28 + Math.min(10, fi.t * 0.3)); else { g.fillStyle = '#4a3a2a'; g.fillRect(fx + 11, y0 - 24, 4, 6); g.fillRect(fx + 14, y0 - 20, 5, 2); } }
    }
    // balloons tied to the kids' crate
    const bl = X(st.slots.kids + 34, 0.9);
    if (bl > -20 && bl < W + 20) {
      for (let i = 0; i < 3; i++) {
        const free = st.balloons.free, rise = free ? st.balloons.t * (0.4 + i * 0.12) : 0, sway = Math.sin(m.steps * 0.05 + i * 2 + st.wind) * (free ? 3 : 2);
        const by2 = y0 - 28 - i * 3 - rise, bx2 = bl + (i - 1) * 6 + sway;
        if (by2 > -20) put(g, s, lib.actor('balloon', i), bx2, by2 + 19);
      }
    }
    // the gull that steals the fisherman's fish
    const sl = st.steal;
    if (sl) {
      const t = sl.t, target = fx + 14, targetY = y0 - 16;
      let gx, gy;
      if (t < 70) { const u = smooth(t / 70); gx = lerp(sl.dir > 0 ? -20 : W + 20, target, u); gy = lerp(sl.y0, targetY, u * u); }
      else if (t < 80) { gx = target; gy = targetY; }
      else { const u = (t - 80) / 90; gx = target + sl.dir * u * 140; gy = targetY - u * u * 110 - u * 20; }
      const gl = lib.anims.gulls && lib.anims.gulls.fly || [], e = gl.length ? lib.entry(gl[[0, 1, 2, 1][(m.steps >> 2) & 3] % gl.length]) : null;
      if (e) { blit(g, s.sheetBG || s.atlas, e, gx, gy + e.h); if (t >= 80) put(g, s, lib.actor('fish', (m.steps >> 2) & 1), gx, gy + 12); }
      if (t >= 76 && t < 96) put(g, s, lib.actor('fisher', 2), fx, y0 + 1);
    }
  }

  /** The shore as one composite: the far and near skyline, the wheel, the landmark's body (a lighthouse, or a crane with the ship it loads), the sea and the skyline's reflection in it. */
  function buildShore(x, s, st, cam, hor, light, get) {
    const lib = s.lib, edge = hor + HARBOUR.horizon - HARBOUR.edge, seaH = edge - hor + 6, cheap = s.cheap;
    strip(x, get('far'), cam * 0.18, hor - 72, 74);
    const wheel = get('wheel');
    if (wheel && st.variant === 0 && !cheap) { const wx = Math.round(186 - cam * 0.36) - wheel.mid; if (wx > -60 && wx < W) x.drawImage(wheel.frames[(s.m.steps / 52 | 0) & 7], wx, hor + 3 - 61); }
    strip(x, get('near'), cam * 0.34, hor - 58, 60);
    if (st.variant === 0) { const lh = get('lighthouse'); if (lh) x.drawImage(lh, Math.round(46 - cam * 0.45) - 20, hor + 3 - 74); }
    strip(x, get('sea'), cam * 0.5, hor, seaH);
    const near = get('near');
    if (!cheap && near) { x.save(); x.translate(0, hor); x.scale(1, -1); x.globalAlpha = 0.2; x.drawImage(near, Math.round(cam * 0.34), 46, W, 14, 0, -14, W, 14); x.restore(); x.globalAlpha = 1; }
    if (st.variant === 1) {
      put(x, s, 'prop-ship', 214 - cam * 0.45, hor + 11);
      const cr = get('crane'), ox = Math.round(150 - cam * 0.45), left = ox - 64, top = hor + 4 - 98;
      if (cr) x.drawImage(cr, left, top);
      for (let i = 0; i < st.crane.loaded; i++) put(x, s, lib.actor('cont', i), left + 94 + (i % 2) * 25, hor + 4 - 3 - 9 * (i >> 1) - 18);
    }
  }
  /** What moves on the shore: the lighthouse's beam, the crane's trolley, cable, hook and the container it carries (or drops into the sea). */
  function drawLandmarkLive(g, s, m, cam, hor, light, st) {
    if (st.variant === 0) {
      if (light.lamps > 0.2 && !s.cheap) {
        const x = Math.round(46 - cam * 0.45), swing = Math.sin(m.steps * 0.025), dir = swing >= 0 ? 1 : -1, reach = Math.round(Math.abs(swing) * 110), ly = hor + 3 - 74 + 13;
        g.save(); g.globalCompositeOperation = 'lighter';
        for (const [k, a] of [[1, 0.13], [0.55, 0.12]]) { g.fillStyle = 'rgba(255,238,170,' + (a * light.lamps) + ')'; g.beginPath(); g.moveTo(x, ly); g.lineTo(x + dir * reach * k, ly - 4 - reach * 0.14 * k); g.lineTo(x + dir * reach * k, ly + 4 + reach * 0.2 * k); g.closePath(); g.fill(); }
        g.fillStyle = 'rgba(255,240,170,' + (0.6 * light.lamps) + ')'; g.fillRect(x - 2, ly - 1, 5, 3);
        g.restore();
        glowAt(g, s, x, ly, 22, 0.8 * light.lamps, '255,240,170');
      }
      return;
    }
    const x = Math.round(150 - cam * 0.45), t = st.crane.t, base = hor + 4, left = x - 64, top = base - 98;
    const slip = st.crane.cycle % 3 === 1, c = craneAt(t, slip), tx = left + c.tx;
    g.fillStyle = css(mulRgb([62, 74, 98], light.tint)); g.fillRect(tx - 3, top + 22, 7, 3); g.fillRect(tx, top + 25, 1, c.len);
    g.fillStyle = css(mulRgb([200, 90, 60], light.tint)); g.fillRect(tx - 2, top + 25 + c.len, 5, 2);
    if (c.attached) put(g, s, s.lib.actor('cont', st.crane.loaded), tx, top + 25 + c.len + 11);
    if (slip && t >= 756 && t < 756 + 16) { const tf = t - 756, fx0 = left + craneAt(756, true).tx; put(g, s, s.lib.actor('cont', st.crane.loaded), fx0, top + 25 + 10 + 11 + 0.17 * tf * tf); }
    for (const sp of st.splashes) put(g, s, 'fx-splash-' + Math.min(3, sp.t / 6 | 0), left + sp.tx, base + 6);
    if (light.lamps > 0.2 && ((m.steps >> 4) & 1)) { g.fillStyle = '#ff4a3a'; g.fillRect(left + 8, top + 14, 2, 2); }
    if (light.lamps > 0.2) { g.fillStyle = 'rgba(255,236,150,' + light.lamps + ')'; g.fillRect(left + 50, top + 11, 4, 2); }
  }
  /** A signboard on the pier's rail (FISH, FERRY, BAIT, CRANE); at night its letters glow. Baked into the pier. */
  const SIGNS = [['FISH', 'FERRY'], ['BAIT', 'CRANE']];
  function St_sign(st, k) { return SIGNS[st.variant % 2][k]; }
  function bakeSigns(x, s, cam, edge, light, list) {
    for (const [text, wx] of list) {
      const sx = Math.round(wx - cam * 0.9), t = textSprite(s, text, 1, 'plate');
      if (!t || sx < -40 || sx > W + 40) continue;
      const w = t.textWidth + 6, x0 = sx - (w >> 1), y0 = edge - 24;
      x.fillStyle = css(mulRgb([54, 34, 20], light.tint)); x.fillRect(x0, y0, w, 11); x.fillStyle = css(mulRgb([150, 104, 60], light.tint)); x.fillRect(x0, y0, w, 1); x.fillStyle = css(mulRgb([18, 20, 36], light.tint)); x.fillRect(x0 + 1, y0 + 1, w - 2, 9);
      x.drawImage(t.canvas, x0 + 2 - t.pad, y0 + 1 - t.pad + 1);
      if (light.lamps > 0.3) { x.save(); x.globalCompositeOperation = 'lighter'; x.fillStyle = 'rgba(160,210,255,' + (0.1 * light.lamps) + ')'; x.fillRect(x0 - 3, y0 - 2, w + 6, 15); x.restore(); }
    }
  }
  /** The pier as one composite: its far edge with the rail and rope, the planks (puddles, rope, net, props), three lamp posts with their glow on the deck, two signboards. */
  function buildPier(x, s, st, cam, feet, light, get) {
    const edge = feet - HARBOUR.edge;
    strip(x, get('edge'), cam * 0.9, edge - 20, 30);
    const deck = get('deck');
    if (deck) strip(x, deck, cam, edge + 6, Math.min(deck.height, H - edge - 6));
    const lamps = light.lamps;
    for (const lx of [30, 160, ARENA.width - 30]) {
      const sx = lx - cam * 0.9;
      if (put(x, s, 'prop-lantern', sx, edge + 18) && lamps > 0.15) {
        glowAt(x, s, sx, edge - 18, 38, lamps);
        x.save(); x.globalCompositeOperation = 'lighter';
        for (let k = 0; k < 4; k++) { x.fillStyle = 'rgba(255,184,96,' + (0.07 * lamps) + ')'; x.fillRect(Math.round(sx - 62 + k * 10), edge + 14 + k * 3, 124 - k * 20, 3); }
        if (lamps > 0.3 && !s.cheap) { x.fillStyle = 'rgba(255,196,110,' + (0.05 * lamps) + ')'; x.fillRect(Math.round(sx) - 44, edge + 22, 88, 20); x.fillRect(Math.round(sx) - 30, edge + 40, 60, 16); }
        x.restore();
      }
    }
    bakeSigns(x, s, cam, edge, light, [[St_sign(st, 0), 120], [St_sign(st, 1), 252]]);
  }

  function drawHarbourBack(g, s, m, cam, feet) {
    const st = s.stage, light = s.light, lib = s.lib, hor = feet - HARBOUR.horizon, edge = feet - HARBOUR.edge, key = lightKey(light), cheap = s.cheap, steps = m.steps;
    const get = (name) => layer(s, st, name, key, () => buildHarbourLayers(s, st, light, name));
    drawSky(g, s, m, cam, hor, st);
    // the shore: one composite, rebuilt only when the camera (at any of its speeds), the light, the wheel's turn or the crane's load change
    const c1 = Math.round(cam * 0.18), c2 = Math.round(cam * 0.34), c3 = Math.round(cam * 0.36), c4 = Math.round(cam * 0.45), c5 = Math.round(cam * 0.5), wheelFrame = st.variant === 0 ? (steps / 52 | 0) & 7 : 0;
    const shore = compose(s, st, 'shore', [key, hor, st.variant, c1, c2, c3, c4, c5, wheelFrame, st.crane.loaded, cheap ? 1 : 0].join('|'), (x) => buildShore(x, s, st, cam, hor, light, get));
    const seaH = edge - hor + 6, top = Math.max(0, hor - 72);
    if (shore) g.drawImage(shore, 0, top, W, hor + seaH - top, 0, top, W, hor + seaH - top);
    drawLandmarkLive(g, s, m, cam, hor, light, st);
    if (!cheap) {                                                                                                  // glints that drift, the sun's glitter
      const gl = get('glint');
      if (gl) g.drawImage(gl, (steps >> 3) % 40, 0, W, seaH - 4, 0, hor + 2, W, seaH - 4);
      if (light.alt > -4 && light.alt < 18) {
        const glit = layer(s, st, 'glitter', key + '|' + hor, () => bakeGlitter(s, light, hor, seaH));
        if (glit) g.drawImage(glit[(steps >> 3) & 1], 0, hor, W, seaH, 0, hor, W, seaH);
      }
    }
    // boats and traffic
    const sheet = s.sheetBG || s.atlas;
    for (const b of st.boats) {
      if (b.kind === 'prop-ship') continue;
      const e = lib && lib.entry(b.kind);
      if (!e) continue;
      const bx = ((b.x - cam * 0.5) % (W + 160) + (W + 160)) % (W + 160) - 80;
      blit(g, sheet, e, bx, hor + 3 + b.row + e.h * 0.5 + Math.round(Math.sin(steps * 0.05 + b.bob) * 0.8));
    }
    drawHarbourTraffic(g, s, m, cam, hor, st, get, light);
    // the pier (one composite), then the crowd, the stories, and the strings of flags
    const pier = compose(s, st, 'pier', [key, feet, Math.round(cam * 0.9), Math.round(cam), st.variant, cheap ? 1 : 0].join('|'), (x) => buildPier(x, s, st, cam, feet, light, get));
    const lipRow = Math.min(H, feet + HARBOUR.front + 2);
    if (pier) g.drawImage(pier, 0, edge - 24, W, lipRow - edge + 24, 0, edge - 24, W, lipRow - edge + 24);
    drawHarbourCrowd(g, s, m, cam, feet, st, light);
    if (!cheap) { const frames = get('bunting'), sway = ((steps >> 3) + Math.round(st.wind * 1.4) + 8) & 3, c = frames && frames[sway]; if (c) g.drawImage(c, Math.round(cam * 0.9), 0, W, 24, 0, edge - 46, W, 24); }
  }
  /** The sun's glitter on the sea, two shimmering versions, baked. */
  function bakeGlitter(s, light, hor, seaH) {
    const sun = sunPlace(light.alt, light.morning, hor), col = css(mixRgb(light.sun, [255, 255, 255], 0.3));
    return [0, 1].map((v) => bake(s, W, H, (x) => { x.fillStyle = col; for (let y = 1; y < seaH - 1; y += 2) { const jitter = ((y * 7 + v * 13 * 3) & 7) - 3; x.fillRect(sun.x + jitter - 1 - (y >> 2), hor + y, 3 + (y >> 1), 1); } }));
  }
  /** Where the crane's trolley and hook are at step t of its 42-second loop: trolley column, cable length, and whether it carries a container. */
  function craneAt(t, slip) {
    const u = t / 1260, A = 24, B = 94;
    const seg = (a, b, from, to) => from + (to - from) * smooth(clamp((u - a) / (b - a), 0, 1));
    let tx = B, len = 8, attached = false;
    if (u < 0.12) { tx = seg(0, 0.12, B, A); len = 8; }
    else if (u < 0.27) { tx = A; len = seg(0.12, 0.27, 8, 52); }
    else if (u < 0.33) { tx = A; len = 52; attached = u > 0.3; }
    else if (u < 0.48) { tx = A; len = seg(0.33, 0.48, 52, 10); attached = true; }
    else if (u < 0.68) { tx = seg(0.48, 0.68, A, B); len = 10; attached = !(slip && u > 0.6); }
    else if (u < 0.8) { tx = B; len = seg(0.68, 0.8, 10, 44); attached = !slip; }
    else if (u < 0.86) { tx = B; len = 44; attached = !slip && u < 0.83; }
    else { tx = B; len = seg(0.86, 0.95, 44, 8); }
    return { tx: Math.round(tx), len: Math.round(len), attached };
  }
  function drawHarbourTraffic(g, s, m, cam, hor, st, get, light) {
    const lib = s.lib, sheet = s.sheetBG || s.atlas, wake = get('wake'), f = st.ferry;
    // the ferry: a white boat with lit windows, a funnel's smoke and a wake
    if (f.on) {
      const fx = Math.round(f.x - cam * 0.55), name = lib.actor('ferry', (m.steps >> 4) & 1), fy = hor + 21 + Math.round(Math.sin(m.steps * 0.06) * 0.6);
      if (fx > -50 && fx < W + 50) {
        if (wake && !s.cheap) { for (let k = 0; k < 2; k++) g.drawImage(wake, fx - f.dir * (38 + k * 10) - 15, fy - 3 - k * 0); }
        if (f.dir > 0) put(g, s, name, fx, fy); else putFlipped(g, s, name, fx, fy);
        if (light.lamps > 0.25 && !s.cheap) { g.fillStyle = 'rgba(255,226,140,' + clamp(light.lamps, 0, 1) + ')'; for (const [dx, dy] of lib.points(name)) g.fillRect(fx + (f.dir > 0 ? dx : -dx) - (f.dir > 0 ? 0 : 2), fy + dy, 3, 3); glowAt(g, s, fx, fy - 12, 38, 0.35 * light.lamps); }
        for (const p of st.smoke) { const e = lib.entry('fx-steam-' + Math.min(3, p.t / 14 | 0)); if (e) { g.globalAlpha = 0.7 * (1 - p.t / 55); blit(g, sheet, e, fx + (p.x - f.x) - (f.dir > 0 ? 6 : -6), fy - 24 + p.y + 17); g.globalAlpha = 1; } }
      }
    }
    // a tug with a barge on the far shore in the container harbour
    if (st.variant === 1) {
      const tx = (((m.steps * 0.18 + 60) % (W + 220)) - 110) , name = lib.actor('tug', (m.steps >> 4) & 1), ty = hor + 16;
      put(g, s, name, tx, ty);
      g.fillStyle = css(mulRgb([40, 40, 60], light.tint)); g.fillRect(Math.round(tx - 52), ty - 4, 52, 1); put(g, s, lib.actor('cont', 1), tx - 64, ty - 1); put(g, s, lib.actor('cont', 0), tx - 90, ty - 1);
      g.fillStyle = css(mulRgb([30, 34, 52], light.tint)); g.fillRect(Math.round(tx - 104), ty - 1, 52, 3);
      if (wake && !s.cheap) g.drawImage(wake, Math.round(tx - 30), ty - 2);
    }
    // a buoy that blinks
    for (const [bxw, row] of [[110, 8], [250, 11]]) { const bx = Math.round(bxw - cam * 0.5); const e = lib.actor('buoy', 0); put(g, s, e, bx, hor + row + 5 + Math.round(Math.sin(m.steps * 0.07 + bxw) * 0.8)); if (light.lamps > 0.3 && ((m.steps >> 4) & 1)) { g.fillStyle = 'rgba(255,220,90,' + light.lamps + ')'; g.fillRect(bx - 1, hor + row - 8, 2, 2); } }
  }

  function drawHarbourFront(g, s, m, cam, feet) {
    const lib = s.lib, light = s.light, st = s.stage, key = lightKey(light);
    if (!lib || !s.atlas) return;
    const get = (name) => layer(s, st, name, key, () => buildHarbourLayers(s, st, light, name));
    const lipY = feet + HARBOUR.front;
    if (light.lamps > 0.6) { g.fillStyle = 'rgba(8,12,40,' + (0.18 * light.lamps) + ')'; g.fillRect(0, Math.min(H, feet + 56), W, H - feet - 56); }
    const d = st.drop;
    if (d && d.phase !== 'none') {                                                                      // the crane's crate: it hangs, falls, bounces, rests, and is lifted away again
      const x = Math.round(d.x - (m.camX - d.cam) * 1.12), y = Math.round(feet + 46 - d.h), hang = d.phase === 'down' || d.phase === 'up';
      if (d.h > 0.5) { g.fillStyle = 'rgba(18,10,30,' + (0.34 * clamp(1 - d.h / 220, 0.2, 1)) + ')'; g.fillRect(x - 11, feet + 44, 22, 3); }
      else { g.fillStyle = 'rgba(18,10,30,0.4)'; g.fillRect(x - 12, feet + 44, 24, 4); }
      put(g, s, 'prop-crate', x, y);
      if (hang) { g.fillStyle = css(mulRgb([40, 44, 58], light.tint)); g.fillRect(x, 0, 1, Math.max(0, y - 30)); g.fillRect(x - 3, y - 30, 7, 3); g.fillRect(x - 9, y - 27, 1, 5); g.fillRect(x + 9, y - 27, 1, 5); for (let k = 0; k < 8; k++) { g.fillRect(x - 8 + Math.round(k * 0.8), y - 27 + k, 1, 1); g.fillRect(x + 8 - Math.round(k * 0.8), y - 27 + k, 1, 1); } }
    }
    // the quay's front edge, and the water below it with a rowing boat, buoys and its glitter
    const front = get('front');
    if (front) {
      const hh = Math.max(1, Math.min(front.height, H - lipY));
      g.drawImage(front, Math.round(cam * 1.1), 0, W, hh, 0, lipY, W, hh);
      const fg = !s.cheap && get('frontglint'), gh = Math.min(hh, Math.max(0, s.vb + 36 - lipY), 70);
      if (fg && gh > 4) g.drawImage(fg, (m.steps >> 3) % 40, 0, W, gh, 0, lipY, W, gh);
    }
    const dinghy = get('dinghy');
    if (dinghy && !s.cheap && lipY + 22 < s.vb + 40) {
      const bx = (((st.rowX + m.steps * 0.11) % 380) + 380) % 380 - 90 - Math.round(cam * 1.1), by = lipY + 22 + Math.round(Math.sin(m.steps * 0.06) * 1.2), pic = dinghy[(m.steps >> 5) & 1];
      if (bx > -50 && bx < W + 4 && by < H) {
        g.save(); g.translate(0, 2 * (by + 21)); g.scale(1, -1); g.globalAlpha = 0.22; g.drawImage(pic, 0, 0, 48, 22, bx, by - 1, 48, 22); g.restore(); g.globalAlpha = 1;
        g.drawImage(pic, bx, by);
        if (light.lamps > 0.3) { g.fillStyle = 'rgba(255,214,120,' + 0.5 * light.lamps + ')'; g.fillRect(bx + 4, by + 22, 2, 8); g.fillRect(bx + 3, by + 30, 4, 2); glowAt(g, s, bx + 5, by + 5, 22, 0.8 * light.lamps); }
      }
      for (const [bxw, dy] of [[36, 36], [256, 30]]) { const bxx = bxw - cam * 1.1; put(g, s, lib.actor('buoy', 0), bxx, lipY + dy + Math.round(Math.sin(m.steps * 0.07 + bxw) * 1)); if (light.lamps > 0.3 && ((m.steps >> 4) & 1)) { g.fillStyle = 'rgba(255,220,90,' + light.lamps + ')'; g.fillRect(Math.round(bxx - 1), lipY + dy - 13, 2, 2); } }
    }
  }

  /* ---- the lantern market: an old street at dusk with tiled roofs and a tower, shopfronts, four stalls with cooks behind their counters, strings of paper lanterns that sway, a lit crowd,
   *      steam, sky lanterns that rise, and now and then a parade of lantern carriers behind the fighters. By day it is a bright, busy alley; at night it glows. */
  const MARKET = { wall: 76, ground: 24, front: 52 };
  const STALL_SIGNS = ['RAMEN', 'FRUIT', 'GRILL', 'TOYS'];
  const LANTERN_GLOW = ['255,110,80', '255,170,70', '255,215,90', '255,120,180'];

  function makeMarket(s, rand) {
    const st = { kind: 'market', variant: 0, sky: makeSky(rand, rand() < 0.5 ? 'clear' : 'streaks'), roofs: { far: [], near: [] }, facades: [], crowd: [], stalls: [], notes: [], steam: [], skyLanterns: [], parade: { on: false, wait: 260 + Math.floor(rand() * 200), x: 0, dir: 1, t: 0 },
      wind: 0, shock: 0, cat: { mode: 'sleep', t: 0 }, vendor: [0, 0, 0, 0], release: 0 };
    st.sky.blimp.wait = 1e9; st.sky.plane.wait = 1e9;
    for (const [list, lo, hi, wlo, whi] of [[st.roofs.far, 16, 40, 16, 34], [st.roofs.near, 20, 36, 22, 40]]) {
      let x = -10;
      while (x < ARENA.width + 20) { const w = Math.round(between(rand, wlo, whi)), h = Math.round(between(rand, lo, hi)); list.push({ x, w, h, lit: rand(), kind: rand() < 0.3 ? 1 : 0 }); x += w + Math.round(between(rand, 0, 4)); }
    }
    let fx = 0;
    while (fx < ARENA.width + 10) { const w = Math.round(between(rand, 34, 48)); st.facades.push({ x: fx, w, tone: Math.floor(rand() * 5), shop: Math.floor(rand() * 3), win: 1 + Math.floor(rand() * 2), flag: rand() < 0.45 }); fx += w; }
    const stallX = [44, 124, 204, 284];
    for (let i = 0; i < 4; i++) st.stalls.push({ x: stallX[i] + Math.round(between(rand, -6, 6)), kind: i, ph: Math.floor(rand() * 20) });
    for (let x = 16; x < ARENA.width - 6; x += 26 + Math.floor(rand() * 10)) st.crowd.push({ type: 'fan', tier: 0, x, kind: CROWD_KINDS[Math.floor(rand() * CROWD_KINDS.length)], ph: Math.floor(rand() * 32), flag: rand() < 0.18 ? (rand() < 0.5 ? 'codex' : 'claude') : null, lag: Math.floor(rand() * 5), hop: rand() < 0.4 });
    st.slots = { band: 164, dancers: 26, kids: 262 };
    st.crowd = st.crowd.filter((c) => !(Math.abs(c.x - st.slots.band) < 44 || Math.abs(c.x - st.slots.dancers) < 22 || Math.abs(c.x - st.slots.kids) < 22));
    for (let i = 0; i < 9; i++) st.skyLanterns.push({ x: rand() * W, y: 40 + rand() * 90, v: 0.1 + rand() * 0.12, ph: rand() * 6, k: Math.floor(rand() * 2) });
    return st;
  }
  function marketCue(s, st, cue) {
    if (cue.type === 'ko') { st.release = 150; for (const l of st.skyLanterns) l.y = Math.max(l.y, 120); st.cat.mode = 'wake'; st.cat.t = 0; }
    if (cue.type === 'hit' && cue.heavy) st.shock = 16;
    if (cue.type === 'special') st.shock = 24;
  }
  function stepMarket(s, st) {
    const m = s.m, steps = m.steps;
    stepSky(s, st.sky, m, { rand: st.rand });
    st.wind = Math.sin(steps * 0.013) + 0.4 * Math.sin(steps * 0.041);
    if (st.shock > 0) st.shock--;
    const tempo = bandBeat(m);
    if (steps % (tempo * 2) === 0 && st.notes.length < 5) st.notes.push({ x: st.slots.band, y: 0, t: 0, k: (steps / tempo | 0) & 1 });
    for (let i = st.notes.length - 1; i >= 0; i--) { const n = st.notes[i]; n.t++; n.y -= 0.35; if (n.t > 46) st.notes.splice(i, 1); }
    // steam from the pot and the grill
    if (steps % 6 === 0 && st.steam.length < 10) { const k = (steps / 6 | 0) % 2 ? 0 : 2; st.steam.push({ stall: k, t: 0, dx: (st.rand() - 0.5) * 4 }); }
    for (let i = st.steam.length - 1; i >= 0; i--) { st.steam[i].t++; if (st.steam[i].t > 56) st.steam.splice(i, 1); }
    // sky lanterns drift up and wrap; after a knock-out many more are let go
    for (const l of st.skyLanterns) { l.y -= l.v * (st.release > 0 ? 2.4 : 1); l.x += st.wind * 0.04; if (l.y < -12) { l.y = 150 + st.rand() * 40; l.x = st.rand() * W; } }
    if (st.release > 0) st.release--;
    // the parade crosses the street behind the crowd
    const p = st.parade;
    if (p.on) { p.t++; p.x += p.dir * 0.5; if (p.x < -190 || p.x > ARENA.width + 190) { p.on = false; p.wait = 1300 + Math.floor(st.rand() * 1300); } }
    else if (m.phase === 'fight' && --p.wait <= 0) { p.on = true; p.t = 0; p.dir = st.rand() < 0.5 ? 1 : -1; p.x = p.dir > 0 ? -160 : ARENA.width + 160; }
    // the cat on the awning sleeps; a knock-out wakes it
    const c = st.cat;
    c.t++;
    if (c.mode === 'wake' && c.t > 70) { c.mode = 'sleep'; c.t = 0; }
  }
  function bakeRoofs(s, list, light, ph, depth, tower) {
    const tint = light.tint, haze = light.haze, body = mulRgb(mixRgb(depth ? [88, 66, 78] : [60, 46, 62], haze, depth ? 0.36 : 0.12), tint), tile = mulRgb(mixRgb(depth ? [126, 62, 56] : [96, 48, 52], haze, depth ? 0.3 : 0.1), tint);
    return bake(s, ARENA.width, ph, (x) => {
      for (const b of list) {
        const top = ph - b.h;
        x.fillStyle = css(body); x.fillRect(b.x, top + 8, b.w, b.h - 8);
        const half = (b.w >> 1) + 3;
        x.fillStyle = css(tile);
        for (let r = 0; r < 9; r++) { const w = Math.round(half * (1 - r / 10)); x.fillRect(b.x + (b.w >> 1) - w, top + 8 - r - 1, w * 2, 1); }
        x.fillStyle = css(mixRgb(tile, [255, 220, 200], 0.18)); x.fillRect(b.x + (b.w >> 1) - half + 1, top + 7, 2, 1); x.fillRect(b.x + (b.w >> 1) + half - 3, top + 7, 2, 1);
        x.fillStyle = css(mixRgb(body, [0, 0, 0], 0.3)); x.fillRect(b.x, top + 8, b.w, 1);
        if (b.kind) { x.fillStyle = css(body); x.fillRect(b.x + 3, top - 4, 2, 6); x.fillRect(b.x + b.w - 7, top - 2, 3, 4); }
        if (light.lamps > 0.12 && depth) {
          x.fillStyle = css([255, 200, 110]);
          for (let r = 0; r < Math.floor((b.h - 12) / 6); r++) for (let k = 0; k < Math.floor((b.w - 4) / 7); k++) { const h = Math.imul(b.x * 31 + r * 17 + k * 7, 2654435761) >>> 0; if ((h % 100) / 100 < b.lit * 0.7 * light.lamps) x.fillRect(b.x + 3 + k * 7, top + 12 + r * 6, 3, 3); }
        }
      }
      if (tower) {                                                                                       // a tower of three tiled roofs with a spire, lit windows and a hanging lantern
        const cx = tower.x, rows = [[24, 16], [20, 14], [16, 12]];
        let y = ph - 4;
        for (let i = 2; i >= 0; i--) {
          const [w, hh] = rows[i];
          x.fillStyle = css(body); x.fillRect(cx - (w >> 1) + 3, y - hh + 6, w - 6, hh - 6);
          if (light.lamps > 0.1) { x.fillStyle = css([255, 200, 110]); x.fillRect(cx - 2, y - hh + 9, 4, 4); }
          x.fillStyle = css(tile);
          for (let r = 0; r < 8; r++) { const ww = Math.round((w >> 1) * (1 - r / 10)); x.fillRect(cx - ww, y - hh + 6 - r - 1, ww * 2 + 1, 1); }
          x.fillRect(cx - (w >> 1) - 2, y - hh + 6, w + 5, 2); x.fillRect(cx - (w >> 1) - 3, y - hh + 5, 2, 1); x.fillRect(cx + (w >> 1) + 2, y - hh + 5, 2, 1);
          y -= hh;
        }
        x.fillStyle = css(mixRgb(tile, [255, 210, 120], 0.3)); x.fillRect(cx, y - 8, 1, 10); x.fillRect(cx - 1, y - 3, 3, 1);
      }
    });
  }
  function bakeWall(s, st, light) {
    const tint = light.tint, F = ARENA.width, h = MARKET.wall;
    const tones = [[154, 104, 84], [136, 92, 96], [158, 124, 84], [112, 100, 122], [150, 86, 70]];
    return bake(s, F, h, (x) => {
      for (const f of st.facades) {
        const base = mulRgb(tones[f.tone], tint), dark = mixRgb(base, [0, 0, 0], 0.3), hi = mixRgb(base, [255, 255, 255], 0.12), warm = mixRgb([60, 40, 40], [255, 196, 108], clamp(0.25 + light.lamps * 0.75, 0, 1));
        x.fillStyle = css(base); x.fillRect(f.x, 8, f.w, h - 8);
        x.fillStyle = css(hi); x.fillRect(f.x, 8, f.w, 1);
        x.fillStyle = css(dark); x.fillRect(f.x, 8, 1, h - 8);
        x.fillStyle = css(mulRgb([110, 52, 50], tint)); x.fillRect(f.x - 2, 4, f.w + 4, 6);                                           // the tiled eave
        x.fillStyle = css(mulRgb([150, 76, 66], tint)); for (let k = 0; k < f.w + 4; k += 3) x.fillRect(f.x - 2 + k, 9, 2, 2);
        x.fillStyle = css(mulRgb([74, 34, 36], tint)); x.fillRect(f.x - 2, 4, f.w + 4, 1);
        const cols = f.win === 1 ? [f.w >> 1] : [f.w / 3 | 0, 2 * f.w / 3 | 0];
        for (const cx of cols) {                                                                                                      // upstairs windows with shutters
          const wx = f.x + cx - 4;
          x.fillStyle = css(dark); x.fillRect(wx - 1, 17, 11, 15); x.fillStyle = css(warm); x.fillRect(wx, 18, 9, 13);
          x.fillStyle = css(dark); x.fillRect(wx + 4, 18, 1, 13); x.fillRect(wx, 24, 9, 1);
          x.fillStyle = css(mulRgb([70, 110, 100], tint)); x.fillRect(wx - 3, 18, 2, 13); x.fillRect(wx + 10, 18, 2, 13);
          x.fillStyle = css(mulRgb([120, 76, 40], tint)); x.fillRect(wx - 2, 31, 14, 2);
        }
        x.fillStyle = css(mulRgb([70, 46, 34], tint)); x.fillRect(f.x, 38, f.w, 3);                                                        // a beam between the floors
        x.fillStyle = css(mixRgb(dark, [0, 0, 0], 0.2)); x.fillRect(f.x + 3, 44, f.w - 6, h - 44);                                      // the shop opening
        x.fillStyle = css(warm); x.fillRect(f.x + 4, 45, f.w - 8, 4);
        if (f.flag) { x.fillStyle = css(mulRgb([196, 48, 44], tint)); x.fillRect(f.x + f.w - 8, 14, 5, 22); x.fillStyle = css(mulRgb([255, 210, 80], tint)); x.fillRect(f.x + f.w - 8, 14, 5, 1); x.fillRect(f.x + f.w - 8, 35, 5, 1); x.fillRect(f.x + f.w - 6, 22, 1, 6); }
        x.fillStyle = css(mulRgb([120, 84, 54], tint)); x.fillRect(f.x, 38, 2, h - 38); x.fillRect(f.x + f.w - 2, 38, 2, h - 38);
      }
    });
  }
  function bakeCobbles(s, light) {
    const tint = light.tint, F = ARENA.width + 80, hh = 250, base = mulRgb([122, 108, 104], tint), mortar = mulRgb([46, 38, 48], tint);
    return bake(s, F, hh, (x) => {
      x.fillStyle = css(mortar); x.fillRect(0, 0, F, hh);
      // cobbles: rows of stones of varied size with rounded corners, a highlight at the top left and a dark lower edge
      for (let y = 0, r = 0; y < hh; r++) {
        const rowH = 6 + ((Math.imul(r * 97 + 5, 2654435761) >>> 0) % 3);
        for (let cx = -((Math.imul(r * 31 + 3, 2654435761) >>> 0) % 9); cx < F;) {
          const h = Math.imul(cx * 31 + r * 977 + 7, 2654435761) >>> 0, w = 6 + (h % 6), tone = (h >> 6) % 5, jy = (h >> 12) % 3 === 0 ? 1 : 0;
          const c = tone === 0 ? mixRgb(base, [24, 20, 44], 0.26) : tone === 1 ? mixRgb(base, [255, 226, 190], 0.14) : tone === 2 ? mixRgb(base, [70, 56, 96], 0.2) : base;
          x.fillStyle = css(c); x.fillRect(cx + 1, y + 1 + jy, w - 2, rowH - 2 - jy); x.fillRect(cx, y + 2 + jy, w, rowH - 4 - jy);
          x.fillStyle = css(mixRgb(c, [255, 255, 255], 0.13)); x.fillRect(cx + 2, y + 1 + jy, w - 4, 1); x.fillRect(cx + 1, y + 2 + jy, 1, rowH - 5 - jy);
          x.fillStyle = css(mixRgb(c, [0, 0, 0], 0.28)); x.fillRect(cx + 2, y + rowH - 2, w - 3, 1); x.fillRect(cx + w - 2, y + 3 + jy, 1, rowH - 5 - jy);
          cx += w + 1;
        }
        y += rowH;
      }
      // wet patches: they hold the lantern light and the sky
      const wet = mixRgb(base, [16, 22, 46], 0.55), glass = mixRgb(mixRgb(light.sky[2], [255, 255, 255], 0.2), [255, 190, 120], clamp(light.lamps * 0.4, 0, 0.5));
      for (const [px, py, rx, ry] of [[40, 54, 24, 4], [118, 74, 26, 4], [204, 60, 22, 3], [276, 80, 28, 4], [88, 110, 22, 3], [232, 128, 24, 4], [20, 160, 22, 3], [150, 184, 28, 4]]) {
        x.fillStyle = css(wet); for (let yy = -ry - 1; yy <= ry + 1; yy++) { const hw = Math.floor(rx * Math.sqrt(Math.max(0, 1 - (yy / (ry + 1)) ** 2)) + 0.5); x.fillRect(px - hw, py + yy, hw * 2 + 1, 1); }
        x.fillStyle = css(glass); for (let yy = -ry; yy <= ry; yy++) { const hw = Math.floor((rx - 2) * Math.sqrt(Math.max(0, 1 - (yy / (ry + 0.5)) ** 2)) + 0.5); x.fillRect(px - hw, py + yy, hw * 2 + 1, 1); }
        x.fillStyle = css(mixRgb(glass, [255, 255, 255], 0.5)); x.fillRect(px - rx + 6, py - 1, rx - 4, 1);
      }
      x.fillStyle = css(mulRgb([44, 120, 64], tint)); for (let k = 0; k < 22; k++) { const h = Math.imul(k * 2654435761 + 5, 2246822519) >>> 0; x.fillRect(h % F, (h >> 9) % hh, 1, 2); }          // moss between stones
      for (const [name, wx, row] of [['prop-crate', 36, 64], ['prop-barrel', 60, 70], ['prop-barrel', 262, 68], ['prop-crate', 286, 74], ['prop-crate', 160, 80]]) {
        const e = s.lib && s.lib.entry(name);
        if (e) x.drawImage(s.sheetBG || s.atlas, e.x, e.y, e.w, e.h, Math.round(wx - e.ax), Math.round(row - e.ay), e.w, e.h);
      }
    });
  }
  /** The overhead strings of paper lanterns: two spans, four sway phases, the lanterns drawn from the untinted atlas (they are lit, so the night does not darken them). */
  function bakeLanternStrings(s, light) {
    const lib = s.lib, out = [], F = ARENA.width;
    for (let sway = 0; sway < 4; sway++) {
      out.push(bake(s, F, 46, (x) => {
        for (const [y0, sag, gap, from] of [[6, 9, 17, 4], [20, 6, 14, 12]]) {
          x.fillStyle = css(mulRgb([40, 28, 24], light.tint));
          for (let px = 0; px < F; px++) x.fillRect(px, y0 + Math.round(Math.sin(((px % 80) / 80) * Math.PI) * sag), 1, 1);
          for (let px = from, i = 0; px < F - 4; px += gap, i++) {
            const e = lib.entry('act-lantern-' + ((i + y0) % 4 + (i % 3 === 0 ? 4 : 0))), yy = y0 + Math.round(Math.sin(((px % 80) / 80) * Math.PI) * sag) + 1;
            if (e) { const off = (sway === 1 || sway === 3 ? 1 : 0) * (i & 1 ? 1 : -1); x.drawImage(s.atlas, e.x, e.y, e.w, e.h, px - e.ax + off, yy, e.w, e.h); if (light.lamps > 0.1) glowAt(x, s, px + off, yy + 8, 15, 0.7 * light.lamps, LANTERN_GLOW[i % 4]); }
          }
        }
      }));
    }
    return out;
  }
  function bakePools(s, light) {
    return bake(s, ARENA.width + 80, 80, (x) => {
      for (let px = 30; px < ARENA.width + 80; px += 72) { const hue = ['255,170,90', '255,150,80', '255,200,110'][(px / 72 | 0) % 3]; for (let k = 2; k >= 0; k--) { x.fillStyle = 'rgba(' + hue + ',' + (0.06 + 0.03 * (2 - k)) + ')'; const rx = 16 + k * 6, ry = 3 + k * 2; for (let yy = -ry; yy <= ry; yy++) { const hw = Math.floor(rx * Math.sqrt(1 - (yy / (ry + 0.5)) ** 2) + 0.5); x.fillRect(px - hw, 40 + yy, hw * 2 + 1, 1); } } }
    });
  }
  function buildMarketLayers(s, st, light, name) {
    switch (name) {
      case 'rooffar': return bakeRoofs(s, st.roofs.far, light, 90, 1, null);
      case 'roofnear': return bakeRoofs(s, st.roofs.near, light, 80, 0, { x: 214 });
      case 'wall': return bakeWall(s, st, light);
      case 'cobbles': return bakeCobbles(s, light);
      case 'strings': return bakeLanternStrings(s, light);
      case 'pools': return bakePools(s, light);
      default: return null;
    }
  }
  /** The stalls' fixed parts (the lit window, the front with its awning and counter, the neon sign), drawn into the street's composite. */
  function buildStalls(x, s, st, cam, base, light) {
    const lib = s.lib;
    for (const stall of st.stalls) {
      const sx = Math.round(stall.x - cam * 0.9);
      if (sx < -34 || sx > W + 34) continue;
      const name = lib.actor('stall', stall.kind), pts = lib.points(name);
      if (pts.length >= 4) {
        const wx = sx + pts[0][0], wy = base + pts[0][1], ww = pts[1][0] - pts[0][0], wh = pts[1][1] - pts[0][1];
        x.fillStyle = css(mixRgb([30, 22, 24], [255, 190, 100], clamp(0.22 + light.lamps * 0.7, 0, 0.95))); x.fillRect(wx, wy, ww + 1, wh + 1);
        x.fillStyle = css(mixRgb([60, 40, 34], [255, 224, 150], clamp(0.2 + light.lamps * 0.6, 0, 0.9))); x.fillRect(wx, wy + wh - 6, ww + 1, 6);
      }
      put(x, s, name, sx, base);
      if (pts.length >= 4) {
        const text = STALL_SIGNS[stall.kind], t = textSprite(s, text, 1, 'neon:' + ['#ff5a7a', '#a8ff6a', '#ffb23a', '#8ad0ff'][stall.kind]), sgx = sx + pts[2][0], sgy = base + pts[2][1];
        if (t) { x.globalAlpha = clamp(0.55 + light.lamps * 0.45, 0, 1); x.drawImage(t.canvas, sgx + ((pts[3][0] - pts[2][0] - t.textWidth) >> 1) - t.pad, sgy + 1 - t.pad + 1); x.globalAlpha = 1; if (light.lamps > 0.3 && !s.cheap) glowAt(x, s, sgx + 15, sgy + 4, 20, 0.45 * light.lamps, ['255,90,120', '160,255,100', '255,180,60', '130,200,255'][stall.kind]); }
      }
    }
  }
  /** The street as one composite: the shopfronts, the cobbles (with their props), the pools of lantern light and the stalls in front of the wall. */
  function buildStreet(x, s, st, cam, feet, light, get) {
    const wallY = feet - MARKET.ground - MARKET.wall, top = feet - MARKET.ground;
    strip(x, get('wall'), cam * 0.9, wallY, MARKET.wall);
    const cob = get('cobbles');
    if (cob) strip(x, cob, cam, top, Math.min(cob.height, H - top));
    if (!s.cheap && light.lamps > 0.1) { const pools = get('pools'); if (pools) { x.globalCompositeOperation = 'lighter'; x.globalAlpha = clamp(light.lamps * 1.2, 0, 1); x.drawImage(pools, Math.round(cam), 0, W, 80, 0, top + 4, W, 80); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over'; } }
    buildStalls(x, s, st, cam, feet - MARKET.ground + 12, light);
  }
  function drawMarketBack(g, s, m, cam, feet) {
    const st = s.stage, light = s.light, lib = s.lib, hor = feet - MARKET.wall - 12, key = lightKey(light), cheap = s.cheap, steps = m.steps;
    const get = (name) => layer(s, st, name, key, () => buildMarketLayers(s, st, light, name));
    drawSky(g, s, m, cam, hor + 10, st);
    // sky lanterns rising over the roofs
    for (const [li, l] of st.skyLanterns.entries()) {
      if (li > 5 || (light.lamps < 0.12 && li % 3)) continue;
      const ly = Math.round(l.y * (hor / 100)), lx = Math.round(l.x - cam * 0.1 + Math.sin(steps * 0.03 + l.ph) * 3);
      if (ly > -10 && ly < hor + 4) { const e = lib.entry('act-skylantern-' + (((steps >> 3) + l.k) & 1)); if (e) blit(g, s.atlas, e, lx, ly + 6); if (light.lamps > 0.15 && !cheap && li < 3) glowAt(g, s, lx, ly, 12, 0.7 * light.lamps); }
    }
    // the roofs and the tower (one composite), the street (another)
    const roofs = compose(s, st, 'roofs', [key, hor, Math.round(cam * 0.2), Math.round(cam * 0.4)].join('|'), (x) => {
      strip(x, get('rooffar'), cam * 0.2, hor - 82, 90);
      strip(x, get('roofnear'), cam * 0.4, hor - 64, 80);
      if (light.lamps > 0.15 && !cheap) glowAt(x, s, 214 - cam * 0.4, hor - 40, 28, 0.55 * light.lamps);
    });
    if (roofs) g.drawImage(roofs, 0, Math.max(0, hor - 82), W, Math.min(H, hor + 2) - Math.max(0, hor - 82), 0, Math.max(0, hor - 82), W, Math.min(H, hor + 2) - Math.max(0, hor - 82));
    const wallY = feet - MARKET.ground - MARKET.wall;
    const street = compose(s, st, 'street', [key, feet, Math.round(cam * 0.9), Math.round(cam), cheap ? 1 : 0].join('|'), (x) => buildStreet(x, s, st, cam, feet, light, get));
    if (street) g.drawImage(street, 0, wallY, W, H - wallY, 0, wallY, W, H - wallY);
    drawMarketLive(g, s, m, cam, feet, st, light);
    drawMarketCrowd(g, s, m, cam, feet, st, light);
    // two strings of paper lanterns across the street (their glow baked in); at night they light what is under them
    const strings = get('strings'), frame = ((steps >> 3) + Math.round(st.wind * 1.2) + 8) & 3;
    if (strings && strings[frame]) g.drawImage(strings[frame], Math.round(cam * 0.9), 0, W, 46, 0, Math.max(feet - 112, 40), W, 46);
  }
  /** What moves at the stalls: the cooks behind their counters (a bust that ends at the counter's top), steam, and the cat asleep on an awning. */
  function drawMarketLive(g, s, m, cam, feet, st, light) {
    const lib = s.lib, base = feet - MARKET.ground + 12;
    for (const stall of st.stalls) {
      const sx = Math.round(stall.x - cam * 0.9);
      if (sx < -34 || sx > W + 34) continue;
      const vk = stall.kind === 0 ? lib.actor('noodle', mood3(m, stall.ph)) : stall.kind === 2 ? lib.actor('grill', (m.steps + stall.ph >> 3) & 1) : null;
      if (vk) put(g, s, vk, sx, base - 17);
      if (stall.kind === 1) put(g, s, lib.actor('cat', st.cat.mode === 'wake' ? 0 : 6), sx - 8, base - 50);
    }
    for (const p of st.steam) {
      const stall = st.stalls[p.stall], sx = Math.round(stall.x - cam * 0.9), e = lib.entry('fx-steam-' + Math.min(3, p.t / 14 | 0));
      if (e) { g.globalAlpha = 0.75 * (1 - p.t / 60); blit(g, s.atlas, e, sx + 4 + p.dx + st.wind * p.t * 0.05, base - 36 - p.t * 0.5); g.globalAlpha = 1; }
    }
  }
  const mood3 = (m, ph) => (m.crowd.mood === 'cheer' ? (m.steps >> 2) % 3 : ((m.steps + ph) >> 4) % 3);
  function drawMarketCrowd(g, s, m, cam, feet, st, light) {
    const lib = s.lib, y0 = feet - 10, mood = m.crowd.mood, X = (x, par) => Math.round(x - cam * par);
    // the lantern parade behind the crowd
    const p = st.parade;
    if (p.on) {
      for (let i = 0; i < 6; i++) {
        const px = X(p.x - p.dir * i * 28, 0.8), name = lib.actor(i % 2 ? 'carrier-octo' : 'carrier-bot', ((p.t >> 3) + i) & 3);
        if (px > -30 && px < W + 30) { if (p.dir > 0) put(g, s, name, px, y0 - 14); else putFlipped(g, s, name, px, y0 - 14); if (light.lamps > 0.15 && !s.cheap && i < 3) glowAt(g, s, px + (p.dir > 0 ? 11 : -11), y0 - 15 - 52, 26, 0.8 * light.lamps, '255,110,80'); }
      }
    }
    drawCrowd(g, s, m, cam, st, light, y0, y0, [[0, y0, 0.9]]);
    const bx = X(st.slots.band, 0.9);
    if (bx > -60 && bx < W + 60) {
      put(g, s, lib.actor('bandstand', 0), bx, y0 + 1);
      const sy = y0 - 11, names = ['drummer', 'horn', 'accordion'];
      for (let i = 0; i < 3; i++) put(g, s, lib.actor(names[i], bandPose(m, i * 2)), bx + BAND.x[i], sy);
      for (const n of st.notes) put(g, s, 'fx-note-' + n.k, bx + Math.sin(n.t * 0.2) * 5, sy - 30 + n.y);
    }
    const dx = X(st.slots.dancers, 0.9);
    if (dx > -30 && dx < W + 30 && !hiddenBehind(s, m, cam, dx, y0, 34, 30, feet)) put(g, s, lib.actor('dancers', mood === 'cheer' ? [2, 3][(m.steps >> 3) & 1] : mood === 'gasp' ? 0 : [0, 1][(m.steps >> 4) & 1]), dx, y0 + 1);
    const kx = X(st.slots.kids, 0.9);
    if (kx > -30 && kx < W + 30 && !hiddenBehind(s, m, cam, kx, y0, 30, 28, feet)) put(g, s, lib.actor('kids', mood === 'cheer' ? 2 : (m.steps >> 4) & 1), kx, y0 + 1);
  }
  function drawMarketFront(g, s, m, cam, feet) {
    const light = s.light;
    if (light.lamps > 0.6) { g.fillStyle = 'rgba(8,10,34,' + (0.16 * light.lamps) + ')'; g.fillRect(0, Math.min(H, feet + 58), W, H - feet - 58); }
  }

  /* ---- Tony's jungle stage (private art in the atlas): the board's backdrop, panned with the camera, its two ambient pieces, and the deck carried on downward */
  function makeJungle(s, rand) {
    const info = s.lib && s.lib.stages && s.lib.stages.jungle;
    if (!info || !s.lib.entry(info.frame)) return null;
    const stage = { kind: 'jungle', info, key: '', tinted: null, fans: [] };
    for (let x = 150; x < 300; x += 38 + Math.floor(rand() * 10)) stage.fans.push({ x, kind: CROWD_KINDS[Math.floor(rand() * CROWD_KINDS.length)], ph: Math.floor(rand() * 32), lag: Math.floor(rand() * 5), hop: rand() < 0.4, flag: null });
    return stage;
  }
  function drawJungleBack(g, s, m, cam, feet) {
    const st = s.stage, info = st.info, lib = s.lib, e = lib.entry(info.frame), light = s.light;
    const tint = light.tint.map((v) => lerp(1, v, 0.75));
    const key = tint.map((v) => Math.round(v * 16)).join(',');
    let sheet = s.atlas;
    if (key !== '16,16,16' && s.doc) {
      if (st.key !== key) {
        st.key = key;
        if (!st.tinted) { const [c] = makeCanvas(s.doc, e.w, e.h); st.tinted = c; }
        const x = st.tinted.getContext('2d');
        if (x) { x.globalCompositeOperation = 'source-over'; x.clearRect(0, 0, e.w, e.h); x.drawImage(s.atlas, e.x, e.y, e.w, e.h, 0, 0, e.w, e.h); x.globalCompositeOperation = 'multiply'; x.fillStyle = css(tint.map((v) => Math.round(clamp(v, 0, 1) * 255))); x.fillRect(0, 0, e.w, e.h); x.globalCompositeOperation = 'source-over'; }
      }
      sheet = st.tinted || s.atlas;
    }
    const direct = sheet === s.atlas, sx = direct ? e.x : 0, sy = direct ? e.y : 0;
    const y0 = feet - info.floor, cx = Math.round(clamp(cam, 0, e.w - W));
    g.fillStyle = '#1b2234'; g.fillRect(0, 0, W, H);
    g.drawImage(sheet, sx + cx, sy, W, e.h, 0, y0, W, e.h);
    if (y0 > 0) {                                                                                     // above the picture: its top rows mirrored and darkened
      for (let done = 0; done < y0; done += e.h) {
        const n = Math.min(e.h, y0 - done), flipped = (done / e.h) % 2 === 0;
        g.save(); g.translate(0, y0 - done); g.scale(1, -1);
        g.drawImage(sheet, sx + cx, sy + (flipped ? 0 : e.h - n), W, n, 0, 0, W, n);
        g.restore();
      }
      for (let k = 0; k < 8; k++) { g.fillStyle = 'rgba(8,12,24,' + (0.07 * (8 - k)) + ')'; g.fillRect(0, Math.round(y0 * k / 8), W, Math.ceil(y0 / 8)); }
    }
    const end = y0 + e.h;
    if (end < H) {                                                                                    // below the picture the deck ends in a front beam, and under it the river, dark
      const beam = mulRgb([90, 58, 28], tint), lip = mulRgb([154, 116, 64], tint), under = mulRgb([34, 22, 12], tint), river = mulRgb([26, 52, 56], tint), ripple = mulRgb([60, 108, 112], tint);
      g.fillStyle = css(beam); g.fillRect(0, end, W, 5);
      g.fillStyle = css(lip); g.fillRect(0, end, W, 1);
      g.fillStyle = css(under); g.fillRect(0, end + 5, W, 3);
      const top = end + 8;
      for (let k = 0, y = top; y < H; k++, y += 8) { g.fillStyle = css(mixRgb(river, [4, 10, 14], Math.min(0.85, y / H * 0.5 + k * 0.05))); g.fillRect(0, y, W, Math.min(8, H - y)); }
      if (!s.cheap) {
        g.fillStyle = css(ripple);
        for (let y = top + 3, k = 0; y < H; y += 6, k++) { const h = Math.imul(k * 7919 + (m.steps >> 4) * 31, 2654435761) >>> 0, h2 = Math.imul(k * 104729 + (m.steps >> 4) * 17, 2246822519) >>> 0; g.fillRect(h % W, y, 6 + (k & 7), 1); g.fillRect(h2 % W, y + 2, 4 + (k & 3), 1); }
      }
    }
    const pieces = info.ambient || [];
    for (const a of pieces) {
      const frame = a.frames[a.script[Math.floor(m.steps / Math.max(1, Math.round(a.ms / 33))) % a.script.length]], fe = frame && lib.entry(frame);
      if (fe) { g.drawImage(s.atlas, fe.x, fe.y, fe.w, fe.h, Math.round(a.at[0] - cx), Math.round(y0 + a.at[1]), fe.w, fe.h); }
    }
    for (const fan of st.fans) drawFan(g, s, m, cam, fan, y0 + 160, 0.9);
  }

  /* ---- the stages in turn: harbour, the market, the jungle when the atlas has it, the other harbour */
  function stageOrder(lib) { return lib && lib.stages && lib.stages.jungle ? ['harbour0', 'jungle', 'market', 'harbour1', 'jungle', 'market'] : ['harbour0', 'market', 'harbour1']; }
  const STAGES = {
    harbour: { step: stepHarbour, back: drawHarbourBack, front: drawHarbourFront, cue: harbourCue, hor: (feet) => feet - HARBOUR.horizon },
    market: { step: stepMarket, back: drawMarketBack, front: drawMarketFront, cue: marketCue, hor: (feet) => feet - MARKET.wall - 2 },
    jungle: { step: null, back: drawJungleBack, front: null, cue: null, hor: (feet) => feet - 60 },
  };
  function buildStage(s, name) {
    const rand = seeded(0x51a9 + s.stageCount * 131 + name.length * 977);
    let st = null;
    if (name === 'jungle') st = makeJungle(s, rand);
    else if (name === 'market') st = makeMarket(s, rand);
    if (!st) st = makeHarbour(rand, name === 'harbour1' ? 1 : 0);
    st.rand = seeded(0x2c3d + s.stageCount * 977 + name.length * 31);
    st.def = STAGES[st.kind];
    return st;
  }

  /* ---- the HUD: the match's own life bars (never quota), the timer, the names and the rounds won, and the banners */
  const BAR = { y: 12, h: 8, left: [6, 86], right: [114, 194] };
  /** The fixed parts of a life bar: its frame, the meter's trough, the name and the rounds won (the HUD's composite holds them; it is rebuilt when a round is won). */
  function drawBarFrame(x, s, f, side) {
    const [x0, x1] = side < 0 ? BAR.left : BAR.right, w = x1 - x0, y = BAR.y, h = BAR.h;
    x.fillStyle = '#0e1224'; x.fillRect(x0 - 2, y - 2, w + 4, h + 4);
    x.fillStyle = '#4a5488'; x.fillRect(x0 - 2, y - 2, w + 4, 1); x.fillRect(x0 - 2, y - 2, 1, h + 4);
    x.fillStyle = '#3a0f1a'; x.fillRect(x0, y, w, h);
    x.fillStyle = '#0e1224'; x.fillRect(x0 - 2, y + h + 2, w + 4, 4);
    x.fillStyle = '#243a78'; x.fillRect(x0, y + h + 3, w, 2);
    const name = f.id.toUpperCase(), t = textSprite(s, name, 1, 'name');
    if (t) {
      const ty = y + h + 12;
      drawText(x, s, name, side < 0 ? x0 : x1, ty, 1, 'name', side < 0 ? 'left' : 'right');
      for (let i = 0; i < WINS_NEEDED; i++) {
        const px = side < 0 ? x0 + t.textWidth + 5 + i * 7 : x1 - t.textWidth - 9 - i * 7;
        x.fillStyle = '#0e1224'; x.fillRect(px - 1, ty - 3, 6, 6);
        x.fillStyle = i < f.wins ? '#ffcf3a' : '#3a4270'; x.fillRect(px, ty - 2, 4, 4);
        if (i < f.wins) { x.fillStyle = '#fff29a'; x.fillRect(px, ty - 2, 2, 1); }
      }
    }
  }
  /** What changes every step on a life bar: the red trail of lost hit points, the yellow bar (it flashes when low), its bright end, the middle mark, the special meter. */
  function drawBar(g, s, f, side) {
    const [x0, x1] = side < 0 ? BAR.left : BAR.right, w = x1 - x0, y = BAR.y, h = BAR.h, m = s.m;
    const ghost = Math.round(w * clamp(f.ghost, 0, 100) / 100), fill = Math.round(w * clamp(f.hp, 0, 100) / 100);
    if (ghost > fill) { g.fillStyle = '#e2402a'; g.fillRect(side < 0 ? x1 - ghost : x0, y, ghost, h); }
    if (fill > 0) {
      const fx = side < 0 ? x1 - fill : x0, low = f.hp < 26 && ((m.steps >> 2) & 1);
      g.fillStyle = low ? '#ff8a2b' : '#f5a712'; g.fillRect(fx, y, fill, h);
      g.fillStyle = low ? '#ffb45a' : '#ffcf3a'; g.fillRect(fx, y, fill, 5);
      g.fillStyle = '#fff29a'; g.fillRect(fx, y, fill, 2);
      g.fillStyle = 'rgba(255,255,255,0.55)'; g.fillRect(side < 0 ? fx : x1 - 1, y, 1, h);
    }
    g.fillStyle = '#0e1224'; g.fillRect(x0 + ((w * 0.5) | 0), y, 1, h);
    const meter = Math.round(w * clamp(f.meter, 0, 100) / 100);
    if (meter > 0) { g.fillStyle = f.meter >= 100 && ((m.steps >> 3) & 1) ? '#ffffff' : '#57a2ff'; g.fillRect(side < 0 ? x1 - meter : x0, y + h + 3, meter, 2); }
  }
  function drawTimer(g, s, m) {
    const urgent = m.phase === 'fight' && m.clock <= 10 && ((m.steps >> 3) & 1) && m.clockT < 15;
    if (urgent) { g.fillStyle = '#e2402a'; g.fillRect(88, BAR.y - 2, 24, 1); }
    drawText(g, s, String(Math.max(0, m.clock)).padStart(2, '0'), 100, BAR.y + 9, 2, 'digit', 'center');
  }

  const easeOut = (t) => 1 - (1 - t) * (1 - t);
  const easeBack = (t) => { const c = 1.7; t = t - 1; return 1 + (c + 1) * t * t * t + c * t * t; };
  /** The big announcements: where the text is, how large, how opaque (a pure function of the match, tested). Lines are [text, scale, style, dy]. */
  function bannerFor(m, feet) {
    const t = m.text;
    if (!t) return null;
    const y = clamp(feet - 50, 48, 170), tt = m.phaseT;
    switch (t.kind) {
      case 'round': return { lines: [[(t.n === 3 && m.f[0].wins === 1 && m.f[1].wins === 1 ? 'FINAL ROUND' : 'ROUND ' + t.n), t.n === 3 && m.f[0].wins === 1 && m.f[1].wins === 1 ? 2 : 3, 'banner', 0]], x: 100 + Math.max(0, 12 - tt) * 14, y, alpha: clamp((64 - tt) / 10, 0, 1) };
      case 'fight': return { lines: [['FIGHT!', tt < 3 ? 6 : tt < 6 ? 5 : 4, 'banner', 0]], x: 100, y, alpha: clamp((36 - tt) / 8, 0, 1) };
      case 'ko': return { lines: [['K.O.', tt < 3 ? 6 : 5, 'ko', 0]], x: 100 + (m.steps & 1 ? 1 : -1) * (m.shake > 0 ? 1 : 0), y: y - 14, alpha: 1 };
      case 'timeup': return { lines: [['TIME UP', 3, 'banner', 0]], x: 100, y, alpha: 1 };
      case 'win': return { lines: [[t.who.toUpperCase() + ' WINS', 2, 'win', 0]], x: 100, y: clamp(feet - 92, 46, 124), alpha: clamp(tt / 6, 0, 1) * clamp((72 - tt) / 14, 0, 1), ribbon: true };
      case 'match': return { lines: [[t.who.toUpperCase(), 3, 'banner', -4], ['WINS THE MATCH', 1, 'win', 14]], x: 100, y: clamp(feet - 88, 52, 124), alpha: clamp(tt / 8, 0, 1), ribbon: true };
      default: return null;
    }
  }
  function drawBanner(g, s, m, feet) {
    const b = bannerFor(m, feet);
    if (!b || b.alpha <= 0) return;
    g.save();
    g.globalAlpha = b.alpha;
    if (b.ribbon) {                                                                                  // a dark ribbon slides in behind the winner's name
      const slide = easeOut(clamp(m.phaseT / 10, 0, 1)), h = b.lines.length > 1 ? 34 : 20;
      g.fillStyle = 'rgba(10,14,40,0.8)'; g.fillRect(Math.round(-W + slide * W), Math.round(b.y - h / 2), W, h);
      g.fillStyle = '#ffcf3a'; g.fillRect(Math.round(-W + slide * W), Math.round(b.y - h / 2), W, 1); g.fillRect(Math.round(-W + slide * W), Math.round(b.y + h / 2 - 1), W, 1);
    }
    for (const [text, scale, style, dy] of b.lines) drawText(g, s, text, b.x, b.y + dy, scale, style, 'center');
    g.restore();
  }
  /** The round's opening: two name plates slide in from the sides with a VS between them, and slide out again (the first round of a match), then ROUND n. */
  function drawPlates(g, s, m, feet) {
    if (m.phase !== 'intro' || !m.text || m.text.kind !== 'round' || m.round !== 1 || m.phaseT > 62) return;
    const tt = m.phaseT, y = clamp(feet - 98, 46, 118);
    const inK = easeOut(clamp(tt / 14, 0, 1)), outK = easeOut(clamp((tt - 46) / 14, 0, 1)), k = inK - outK;
    if (k <= 0.01) return;
    for (const [who, side, colour] of [['CODEX', -1, '#57a2ff'], ['CLAUDE', 1, '#ff8a2b']]) {
      const t = textSprite(s, who, 2, 'plate');
      if (!t) continue;
      const w = t.textWidth + 10, x0 = side < 0 ? Math.round(lerp(-w - 4, 4, k)) : Math.round(lerp(W + 4, W - 4 - w, k));
      g.fillStyle = 'rgba(10,14,40,0.86)'; g.fillRect(x0, y - 9, w, 18);
      g.fillStyle = colour; g.fillRect(x0, y - 9, w, 1); g.fillRect(x0, y + 8, w, 1); g.fillRect(side < 0 ? x0 + w - 2 : x0, y - 9, 2, 18);
      g.drawImage(t.canvas, x0 + 5 - t.pad, Math.round(y - t.h / 2));
    }
    const vk = clamp((tt - 8) / 8, 0, 1) * (1 - outK);
    if (vk > 0) { g.globalAlpha = vk; drawText(g, s, 'VS', 100, y, vk < 1 ? 3 : 2, 'banner', 'center'); g.globalAlpha = 1; }
  }
  /** A bright diagonal band that sweeps over the picture (FIGHT! and the knock-out's flash). t in 0..1. */
  function drawSwipe(g, t, colour) {
    if (t <= 0 || t >= 1) return;
    const x = lerp(-70, W + 70, t);
    g.save();
    g.fillStyle = colour || 'rgba(255,255,255,0.5)';
    g.beginPath(); g.moveTo(x - 20, 0); g.lineTo(x + 26, 0); g.lineTo(x - 22, H); g.lineTo(x - 68, H); g.closePath(); g.fill();
    g.fillStyle = 'rgba(255,255,255,0.35)';
    g.beginPath(); g.moveTo(x + 30, 0); g.lineTo(x + 38, 0); g.lineTo(x - 10, H); g.lineTo(x - 18, H); g.closePath(); g.fill();
    g.restore();
  }
  function drawHud(g, s, m) {
    const frame = compose(s, s, 'hud', m.f[0].wins + '|' + m.f[1].wins, (x) => {
      drawBarFrame(x, s, m.f[0], -1); drawBarFrame(x, s, m.f[1], 1);
      x.fillStyle = '#0e1224'; x.fillRect(88, BAR.y - 2, 24, 22); x.fillStyle = '#4a5488'; x.fillRect(88, BAR.y - 2, 24, 1); x.fillStyle = '#1a2148'; x.fillRect(89, BAR.y - 1, 22, 20);
    });
    if (frame) g.drawImage(frame, 0, 0, W, 40, 0, 0, W, 40);
    drawBar(g, s, m.f[0], -1);
    drawBar(g, s, m.f[1], 1);
    drawTimer(g, s, m);
  }

  /* ---- fighters: shadows that follow the light, tweened frames, white impact frames, afterimages; effects */
  const REFLECT = [[0, 14, 0.19], [14, 36, 0.07]];
  function shadowSprite(s, half) {
    const key = 'sh' + half;
    if (s.glows[key] !== undefined) return s.glows[key];
    const c = bake(s, half * 2 + 10, 11, (x) => {
      for (const [grow, a] of [[4, 0.12], [2, 0.2], [0, 0.34]]) {
        x.fillStyle = 'rgba(18,10,30,' + a + ')';
        const rx = half + grow, ry = 3.2 + grow * 0.6;
        for (let y = -Math.ceil(ry); y <= Math.ceil(ry); y++) { const hw = Math.floor(rx * Math.sqrt(Math.max(0, 1 - (y / (ry + 0.4)) ** 2)) + 0.5); x.fillRect(half + 5 - hw, 5 + y, hw * 2 + 1, 1); }
      }
    });
    s.glows[key] = c;
    return c;
  }
  /** The shadow under a fighter: wider and offset away from a low sun, short at noon, soft and small under lamps. */
  function drawShadow(g, s, f, cam, feet) {
    const lib = s.lib, light = s.light, e = fighterEntry(s, f), sh = (e && lib.shadow(e.name)) || [0, 26, 1];
    if (!e) return;
    const sunUp = light.alt > 2, low = sunUp ? clamp(1 - light.alt / 40, 0, 1) : 0.3, sunX = sunUp ? sunPlace(light.alt, light.morning, 100).x : W / 2, fx = f.x - cam;
    const away = sign(fx - sunX) || 1, half = Math.max(8, Math.round(sh[1] * (1 + 0.7 * low) / 2) * 2 / 2), off = Math.round(sh[0] + away * low * 12);
    const spr = shadowSprite(s, Math.round(half / 2) * 2);
    if (!spr) return;
    g.globalAlpha = clamp(sh[2] * (sunUp ? 0.9 : 0.6 + 0.2 * light.lamps), 0, 1);
    g.drawImage(spr, Math.round(fx + off - spr.width / 2), feet - 5);
    g.globalAlpha = 1;
  }
  function silhouette(s, e) {
    s.sil = s.sil || new Map();
    let c = s.sil.get(e.name);
    if (c === undefined) {
      const made = makeCanvas(s.doc, e.w, e.h);
      c = null;
      if (made[1]) { const x = made[1]; x.drawImage(s.atlas, e.x, e.y, e.w, e.h, 0, 0, e.w, e.h); x.globalCompositeOperation = 'source-in'; x.fillStyle = '#ffffff'; x.fillRect(0, 0, e.w, e.h); c = made[0]; }
      if (s.sil.size > 24) s.sil.clear();
      s.sil.set(e.name, c);
    }
    return c;
  }
  const nameOf = (f) => { const n = frameName(f); return f.id === 'claude' && f.blinking > 0 && f.state === 'idle' ? 'claude-blink-0' : n; };
  /** The atlas entry a fighter shows now. An in-between frame the atlas lacks (an atlas made before they existed) falls back to the nearest drawn pose of the same move, never to nothing. */
  function fighterEntry(s, f) {
    const lib = s.lib;
    let e = lib.entry(nameOf(f));
    if (e || typeof f.seq[f.si] !== 'string') return e;
    for (let k = f.si + 1; k < f.seq.length && !e; k++) if (typeof f.seq[k] === 'number') e = lib.entry(f.id + '-' + f.anim + '-' + f.seq[k]);
    for (let k = f.si - 1; k >= 0 && !e; k--) if (typeof f.seq[k] === 'number') e = lib.entry(f.id + '-' + f.anim + '-' + f.seq[k]);
    return e || lib.entry(f.id + '-idle-0');
  }
  function drawFighter(g, s, f, cam, feet) {
    const lib = s.lib;
    if (!lib || !s.atlas) return;
    const e = fighterEntry(s, f), m = s.m;
    if (!e) return;
    const tremble = m.hitstop > 0 && f.si === 0 && (f.state === 'hit' || f.state === 'kd') ? ((m.steps & 1) ? 1 : -1) : 0;
    const x = f.x - cam + tremble, tr = s.trail[f.id];
    if (tr && tr.length) for (let i = 0; i < tr.length; i++) { const t = tr[i], e2 = lib.entry(t.name); if (e2) { g.globalAlpha = 0.1 + 0.08 * i; blit(g, s.atlas, e2, t.x - cam, feet); } g.globalAlpha = 1; }
    blit(g, s.atlas, e, x, feet);
    if (f.flashT > 0) { const sil = silhouette(s, e); if (sil) { g.globalAlpha = 0.85; g.drawImage(sil, Math.round(x - e.ax), Math.round(feet - e.ay)); g.globalAlpha = 1; } }
  }
  /** The fighters mirrored in the wet deck: the same frame flipped about the floor line, in three slices that fade with the distance from it. */
  function drawReflections(g, s, m, cam, feet) {
    const lib = s.lib;
    if (!lib || !s.atlas || s.cheap) return;
    g.save();
    g.translate(0, 2 * feet + 2);
    g.scale(1, -1);
    for (const f of m.f) {
      const e = fighterEntry(s, f);
      if (!e) continue;
      const dx = Math.round(f.x - cam - e.ax);
      if (dx >= W || dx + e.w <= 0) continue;
      for (const [d0, d1, a] of REFLECT) {
        const sy0 = Math.max(0, e.ay - d1), sy1 = Math.min(e.h, e.ay - d0);
        if (sy1 <= sy0) continue;
        g.globalAlpha = a;
        g.drawImage(s.atlas, e.x, e.y + sy0, e.w, sy1 - sy0, dx, Math.round(feet - e.ay + sy0), e.w, sy1 - sy0);
      }
    }
    g.restore();
  }
  function drawFx(g, s, m, cam, feet) {
    const lib = s.lib;
    if (!lib || !s.atlas) return;
    for (const e of m.fx) {
      const idx = Math.min(e.frames - 1, Math.floor(e.t / e.rate)), name = 'fx-' + e.kind + '-' + idx, ent = lib.entry(name);
      if (!ent) continue;
      if (e.flip) putFlippedAt(g, s.atlas, ent, e.x - cam, feet - e.y); else blit(g, s.atlas, ent, e.x - cam, feet - e.y);
    }
  }
  function putFlippedAt(g, sheet, e, x, y) {
    const dx = Math.round(x), dy = Math.round(y - e.ay);
    if (dx - e.w >= W || dx + e.w <= 0) return;
    g.save(); g.translate(dx, 0); g.scale(-1, 1); g.drawImage(sheet, e.x, e.y, e.w, e.h, -e.ax, dy, e.w, e.h); g.restore();
  }
  /** Fireworks of the match end (two-pixel embers that fade by shrinking) and the dizzy stars over a fighter who is down. */
  function drawSparks(g, s, m, cam, feet) {
    for (const e of m.sparks) {
      const left = 1 - e.t / e.life, size = left > 0.55 ? 2 : 1;
      g.fillStyle = left > 0.8 ? '#ffffff' : FIREWORK_COLOURS[e.hue];
      g.fillRect(Math.round(e.x), Math.round(e.y), size, size);
    }
    const lib = s.lib;
    if (!lib || !s.atlas) return;
    for (const f of m.f) {
      if (f.state === 'kd' && f.si >= 3) blit(g, s.atlas, lib.entry('fx-stars-' + ((m.steps >> 2) & 3)), f.x - cam - f.dir * 14, feet - 36);
      else if (f.state === 'hit' && f.combo >= 2) blit(g, s.atlas, lib.entry('fx-stars-' + ((m.steps >> 2) & 3)), f.x - cam, feet - 84);
    }
  }
  function drawProjectiles(g, s, m, cam, feet) {
    const lib = s.lib;
    if (!lib || !s.atlas) return;
    for (const p of m.proj) {
      blit(g, s.atlas, lib.entry('proj-' + p.kind + '-' + ((p.t >> 1) & 3)), p.x - cam, feet - p.y);
      if (!s.cheap) glowAt(g, s, p.x - cam, feet - p.y, 26, 0.55, p.kind === 'codex' ? '90,160,255' : '255,160,60');
    }
  }
  /** Fast lines that rush in toward the middle (the knock-out and the special's charge). `k` 0..1. */
  function drawSpeedLines(g, cx, cy, k) {
    if (k <= 0.02) return;
    g.fillStyle = 'rgba(255,255,255,' + (0.5 * k) + ')';
    for (let i = 0; i < 16; i++) {
      const a = i * Math.PI / 8 + 0.2, r0 = 48 + (i % 3) * 14, r1 = r0 + 22 + (i % 2) * 10;
      for (let r = r0; r < r1; r += 3) g.fillRect(Math.round(cx + Math.cos(a) * r), Math.round(cy + Math.sin(a) * r), 2, 1);
    }
  }

  /* ---- the scene */
  const now = () => (typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now());
  const viewBottom = (api) => (api && api.view && finite(api.view.bottom) ? api.view.bottom : H);
  const qaOptions = () => (global.__fightingQA && typeof global.__fightingQA === 'object' ? global.__fightingQA : {});

  function createScene() {
    const scene = {
      size: SIZE, needsAtlas: true, s: null,
      init(api) {
        const qa = qaOptions();
        const base = Math.floor(api.random() * 4294967296);
        const seed = finite(qa.seed) ? qa.seed >>> 0 : (base ^ ((Date.now() / 60000) | 0)) >>> 0;
        const lib = api.json && api.atlas ? readAtlas(api.json) : null;
        const layout = layoutFor(viewBottom(api));
        const s = { api, doc: docOf(api), atlas: api.atlas || null, sheetBG: api.atlas || null, sheetKey: '', lib, texts: new Map(), glows: {}, match: null, m: null, feet: layout.feet, stage: null, stageCount: 0, order: stageOrder(lib), orderAt: 0,
          light: null, lightAt: -1000, clock: finite(qa.hour) ? () => { const d = new Date(2026, 10, 9, Math.floor(qa.hour), Math.round((qa.hour % 1) * 60), 0); return d; } : () => new Date(), cheap: false, stepAt: 0, errors: {}, qa, builds: 0, vb: viewBottom(api), trail: { codex: [], claude: [] },
          queue: [], zoomCanvas: null, lastKo: -1 };
        s.match = s.m = createMatch({ seed });
        if (qa.stage && s.order.indexOf(qa.stage) >= 0) s.orderAt = s.order.indexOf(qa.stage);
        this.s = s;
        this.updateLight(true);
        s.stage = buildStage(s, s.order[s.orderAt]);
        if (finite(qa.skip)) for (let i = 0; i < qa.skip; i++) s.m.step();
        if (qa.phase === 'fight') { for (let i = 0; i < 200 && s.m.phase !== 'fight'; i++) s.m.step(); }
        global.__fighting = { skip: (n) => { for (let i = 0; i < n; i++) this.step(api, STEP); }, scene: this };
      },
      updateLight(force) {
        const s = this.s;
        if (!s) return;
        if (!force && s.m.steps - s.lightAt < 90) return;
        const sun = sunState(s.clock()), light = lightAt(sun.alt);
        light.morning = sun.morning; light.solar = sun.solar; light.phase = phaseName(sun.alt);
        s.light = light; s.lightAt = s.m.steps;
        tintSheet(s, light.tint);
      },
      step(api, dt) {
        const s = this.s;
        if (!s) return;
        s.cheap = api.tier === 'low' || api.tier === 'light';
        s.builds = 0;
        s.vb = viewBottom(api);
        const m = s.m;
        m.step();
        s.stepAt = now();
        s.feet = easeFeet(s.feet, layoutFor(viewBottom(api)).feet);
        this.updateLight(false);
        const st = s.stage;
        // afterimages behind a lunging, flying or whipping fighter
        for (const f of m.f) {
          const tr = s.trail[f.id], fast = Math.abs(f.vx) > 1.6 || (f.state === 'attack' && f.move && (f.move.lunge || f.moveName === 'whip') && f.si >= 1 && f.si <= 4) || (f.state === 'kd' && f.si < 3 && m.phase === 'ko');
          if (m.steps % 2 === 0) { if (fast) { tr.push({ name: nameOf(f), x: f.x }); if (tr.length > 3) tr.shift(); } else if (tr.length) tr.shift(); }
        }
        for (const cue of m.cues.splice(0)) {
          try { if (st && st.def && st.def.cue) st.def.cue(s, st, cue); } catch (e) { s.errors.cue = String(e && e.message || e); }
          if (cue.type === 'ko') { s.lastKo = m.steps; for (let k = 0; k < 3; k++) s.queue.push({ at: m.steps + 40 + k * 17, kind: 'firework' }); }
          if (cue.type === 'round' && cue.n === 1 && cue.first && ((m.steps * 7 + s.stageCount) % 3 === 0)) s.queue.push({ at: m.steps + 30, kind: 'firework' });
          if (cue.type === 'matchend') for (let k = 0; k < 5; k++) s.queue.push({ at: m.steps + 10 + k * 22, kind: 'firework' });
        }
        if (st && st.sky) {
          for (let i = s.queue.length - 1; i >= 0; i--) if (s.queue[i].at <= m.steps) { launchFirework(st.sky, st, st.def.hor(s.feet)); s.queue.splice(i, 1); }
        } else s.queue.length = 0;
        if (st && st.def && st.def.step) {
          try { st.def.step(s, st); } catch (e) { if (!s.errors.stageStep) s.errors.stageStep = String(e && e.message || e); }
        }
        for (const ev of m.events.splice(0)) {
          if (ev.type === 'stage') { s.stageCount++; s.orderAt = (s.orderAt + 1) % s.order.length; s.stage = buildStage(s, s.order[s.orderAt]); s.queue.length = 0; }
        }
      },
      draw(api, g) {
        const s = this.s;
        if (!s) return;
        const m = s.m, target = layoutFor(viewBottom(api)).feet;
        if (now() - s.stepAt > 250 && s.feet !== target) s.feet = target;                          // nothing is running (the first picture, a still): no sliding
        const feet = s.feet, cam = Math.round(m.camX + m.camKick);
        if (!s.lib || !s.atlas) { g.fillStyle = '#12182c'; g.fillRect(0, 0, W, H); return; }
        const sd = m.shakeDir || 1;
        const shake = m.shake > 0 ? Math.round(((m.steps & 1) ? sd : -sd * 0.5) * m.shakeAmp * (m.shake / m.shakeMax)) : 0, lift = m.shake > 0 && m.shakeAmp > 1 ? Math.round(((m.steps >> 1) & 1 ? 1 : -1) * 0.5 * m.shakeAmp * (m.shake / m.shakeMax)) : 0;
        const safe = (name, fn) => { try { fn(); } catch (e) { if (!s.errors[name]) { s.errors[name] = String(e && e.message || e); } } };
        const st = s.stage;
        g.save();
        g.translate(shake, lift);
        safe('stage', () => st.def.back(g, s, m, cam, feet));
        if (m.dim > 0.02) { g.fillStyle = 'rgba(8,10,34,' + (0.55 * m.dim * 2) + ')'; g.fillRect(-4, -4, W + 8, H + 8); }
        safe('reflections', () => drawReflections(g, s, m, cam, feet));
        safe('shadows', () => { for (const f of m.f) drawShadow(g, s, f, cam, feet); });
        const order = m.f.slice().sort((a, b) => (a.state === 'attack') - (b.state === 'attack') || (b.state === 'kd') - (a.state === 'kd'));
        safe('fighters', () => { for (const f of order) drawFighter(g, s, f, cam, feet); });
        safe('projectiles', () => drawProjectiles(g, s, m, cam, feet));
        safe('fx', () => { drawFx(g, s, m, cam, feet); drawSparks(g, s, m, cam, feet); });
        safe('stage-front', () => { if (st.def.front) st.def.front(g, s, m, cam, feet); });
        if (m.hitGlow && m.hitGlow.t > 0 && !s.cheap) glowAt(g, s, m.hitGlow.x - cam, feet - m.hitGlow.y, 34, 0.9 * m.hitGlow.t / 3, '255,255,255');
        g.restore();
        const kt = m.koAt >= 0 ? m.steps - m.koAt : -1, zoom = m.phase === 'ko' && kt >= 3 && kt < 22 && !s.cheap;
        if (zoom) safe('zoom', () => zoomIn(g, s, m, cam, feet, kt));
        if (m.pushV > 0.02) safe('push', () => { g.fillStyle = 'rgba(6,8,26,' + (0.22 * m.pushV) + ')'; g.fillRect(0, 0, W, 14); g.fillRect(0, H - 14, W, 14); drawSpeedLines(g, 100, feet - 40, m.pushV * 0.7); });
        if (m.flash > 0) { g.fillStyle = 'rgba(255,255,255,' + (0.8 * m.flash / 6) + ')'; g.fillRect(0, 0, W, H); }
        if (m.phase === 'ready' && m.phaseT < 12) safe('swipe', () => drawSwipe(g, m.phaseT / 12, 'rgba(255,214,90,0.55)'));
        if (m.phase === 'ko' && kt >= 0 && kt < 10) safe('swipe2', () => drawSwipe(g, kt / 10, 'rgba(255,255,255,0.28)'));
        safe('hud', () => { drawHud(g, s, m); drawPlates(g, s, m, feet); drawBanner(g, s, m, feet); });
        if (m.fade > 0.01) { g.fillStyle = 'rgba(0,0,0,' + m.fade + ')'; g.fillRect(0, 0, W, H); }
      },
      poke(api, x, y) {
        const s = this.s;
        if (!s) return;
        s.m.poke(x + Math.round(s.m.camX), s.feet - y);
      },
    };
    return scene;
  }
  /** The knock-out's punch-in: the picture so far, copied once and shown at twice the size around the fallen fighter (whole pixels doubled, never a fractional scale), with lines racing in. */
  function zoomIn(g, s, m, cam, feet, kt) {
    if (!s.zoomCanvas) { const made = makeCanvas(s.doc, W, H); s.zoomCanvas = made[1] ? made[0] : null; }
    const z = s.zoomCanvas, loser = m.winner ? m.other(m.winner) : m.f[0];
    if (!z || !g.canvas) return;
    z.getContext('2d').drawImage(g.canvas, 0, 0);
    const fx = clamp(Math.round(loser.x - cam), 30, W - 30), sx = clamp(fx - 50, 0, W / 2), sy = clamp(feet - 100, 0, H / 2 - 8);
    g.drawImage(z, sx, sy, W / 2, H / 2, 0, 0, W, H);
    drawSpeedLines(g, (fx - sx) * 2, (feet - 40 - sy) * 2, 1 - kt / 22);
  }
  const scene = createScene();

  const logic = {
    NAME, SIZE, W, H, STEP, LAYOUT, FONT, FRAMES, FX_FRAMES, ACTOR_FRAMES, TWEEN_NAMES, CROWD_KINDS, CROWD_POSES, MOVES, STATS, BODY, ARENA, MIN_GAP, MAX_GAP, IDLE_SEQ, ROUND_SECONDS, WINS_NEEDED, KO_SLOW, FIREWORK_COLOURS,
    seeded, weighted, layoutFor, easeFeet, textPixels, sunState, lightAt, phaseName, sunPlace, moonPlace,
    createMatch, createFighter, play, tickAnim, frameName, free, hittable, strikeRange, moveSteps, lungeDistance,
    HARBOUR, MARKET, BAR, TEXT_STYLES, readAtlas, createScene, makeHarbour, makeMarket, buildStage, stageOrder, bannerFor, fanPose, lightKey, blit, renderText, craneAt, bandBeat, STALL_SIGNS, PLANE_TEXTS,
  };
  if (global.TabletGames && typeof global.TabletGames.define === 'function') global.TabletGames.define(NAME, scene);
  if (typeof module !== 'undefined' && module.exports) module.exports = Object.assign({ scene }, logic);
}(typeof window !== 'undefined' ? window : globalThis));
