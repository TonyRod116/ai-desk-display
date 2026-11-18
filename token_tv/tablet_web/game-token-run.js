/* TOKEN RUN for the tablet: a real-time, Out Run style coastal racer drawn with the classic scanline road (segments with curves and hills), 200 x 320 art pixels, 30 Hz.
 *
 * Decorative and calm, never activity or trading: a red open-top sports car steers gently between slower rivals and overtakes them (the whole layout follows api.view.bottom,
 * the rows above the page's glass dock: the horizon a third of the way down them, the car just above the clock, the road running on below); palms, signs,
 * houses, rocks, billboards and now and then an overpass scale with distance; the sea with sailboats is on the left, mountains scroll in parallax, and the sky, the sun
 * (big at dusk), the stars, the lights and the colours follow the REAL clock. A touch makes the car honk-hop or a gull take off. NO quota, number or ring is drawn here
 * (Tony's rule: only the isometric city, the Game Boy and Neon City's bridge show quota in the picture).
 *
 * Files: the engine is stage-game.js (window.TabletGames). The sprites come from a private atlas made offline by scripts/prepare_game_token_run.py (every roadside
 * sprite is drawn at a ladder of heights, so nothing is ever resampled by a fraction; the frames and their ground anchors are in the atlas JSON). The road, the ground,
 * the sea, the sky and the mountains are composed in a typed array and put on the canvas once per frame; everything else is a few dozen drawImage calls. Without the
 * atlas the scene still draws the road, sea, sky and mountains and a plain car, calmly.
 *
 * The file is also a Node module: the road geometry, the projection, the traffic, the scenery and the day schedule are pure and have tests
 * (tests/test_tablet_game_token_run.mjs).
 */
(function (global) {
  'use strict';

  /* ---- constants */
  const W = 200, H = 320, HORIZON = 92, CX = 100;
  const SEG = 100;                       // world units per road segment
  const ROAD = 1000;                     // half the road's width: three lanes of 667
  const LANE = (ROAD * 2) / 3;
  const CAM_H = 1000;                    // camera height over the road
  const FX = 50, FY = 122;               // lateral and vertical focal lengths of the plain layout (the picture is tall: the ground is foreshortened more than the sprites)
  const ZP = 600;                        // the player's car is this far in front of the camera: its tyres touch the car's row
  const CAR_ROW = Math.round(HORIZON + CAM_H * FY / ZP);        // 295: the plain layout, which the pure tests and the default projection use (the scene itself follows the visible rows)
  const DRAW = 300;                      // segments drawn ahead
  const TRACK = 3000;                    // segments before the track repeats
  const BAND = 64;                       // world length of one stripe (kerbs, grass, sea, asphalt)
  const HILL_GAIN = 2.2;                 // hills are drawn this much taller than they drive: gentle slopes, but swells you can see from the sofa
  const STEP = 1 / 30;
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (t) => t * t * (3 - 2 * t);

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

  /* ---- colours: '#rrggbb' <-> [r, g, b], packed little-endian for a Uint32 view of an ImageData */
  function rgb(hex) {
    const v = parseInt(hex.slice(1), 16);
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  }
  const pack = (c) => (0xff000000 | (c[2] << 16) | (c[1] << 8) | c[0]) >>> 0;
  const mixRgb = (a, b, t) => [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t)];
  const mulRgb = (c, tint) => [Math.round(clamp(c[0] * tint[0], 0, 255)), Math.round(clamp(c[1] * tint[1], 0, 255)), Math.round(clamp(c[2] * tint[2], 0, 255))];
  const css = (c) => 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')';

  /* ---- the layout: where the horizon and the car sit.
   *
   * The page's glass dock hides the lower part of the picture. `api.view.bottom` is the last art row that stays visible above it (about 186 of 320 on the tablet, the
   * whole 320 in picture mode), so the layout follows it: the horizon a third of the way down the visible rows, the car above the clock and quota lines, and the road
   * keeps going below the car, seen through the dock and in picture
   * mode. The vertical focal length follows from the two rows (the car's tyres touch their row at depth ZP), so the road always looks right, and the anchors ease a few
   * steps toward new targets: a tap on the clock slides the picture instead of jumping. */
  const ANCHOR = { horizonShare: 1 / 3, carGap: 84, dockGap: 65, dockBelow: 190, pictureFrom: 280, minBottom: 104 };
  /** The horizon row and the car's row (art pixels) for a visible bottom row. */
  function anchorsFor(viewBottom) {
    const vb = clamp(Math.round(finite(viewBottom) ? viewBottom : H), ANCHOR.minBottom, H);
    const dock = 1 - smooth(clamp((vb - ANCHOR.dockBelow) / (ANCHOR.pictureFrom - ANCHOR.dockBelow), 0, 1));       // 1 with the dock up, 0 with the whole picture showing
    const horizon = Math.round(vb * ANCHOR.horizonShare);
    return { horizon, carRow: Math.max(horizon + 24, Math.round(vb - ANCHOR.carGap - (ANCHOR.dockGap - ANCHOR.carGap) * dock)) };
  }
  /** What the projection needs for a horizon row and a car row. `contrast` rescales rows below the horizon so the haze and the stripes fade at the same distance
   *  whatever the layout; `zCut` is the depth nearer than which a thing is below the picture. */
  function geometry(horizon, carRow) {
    const hz = Math.round(horizon), car = Math.max(hz + 24, Math.round(carRow)), fy = (car - hz) * ZP / CAM_H;
    return { horizon: hz, carRow: car, fy, contrast: Math.sqrt(FY / fy), zCut: CAM_H * fy / (H + 8 - hz) };
  }
  const DEFAULT_GEO = geometry(HORIZON, CAR_ROW);
  /** One step of easing toward a new target: quick at first, never more than `limit` rows a step, and exactly on the target at the end. */
  function easeAnchors(current, target, rate = 0.35, limit = 18, least = 2) {
    const move = (a, b) => {
      const d = b - a;
      if (Math.abs(d) <= least) return b;
      return Math.round(a + Math.sign(d) * Math.max(least, Math.min(Math.abs(d) * rate, limit)));
    };
    return { horizon: move(current.horizon, target.horizon), carRow: move(current.carRow, target.carRow) };
  }

  /* ---- the day: where the sun is and how the scene is lit.
   *
   * The tablet knows no location, so the sun is computed for a reference location from the date and the clock's own time zone: the standard declination and
   * equation-of-time formulas, then the altitude. Everything the scene shows of the time of day is a function of that altitude (and whether it is the morning), so
   * dusk is a real dusk: the sun grows and reddens as it sets over the sea on the left, stars come out when it is well below the horizon. */
  const LAT = 40.4, LON = -3.7;
  const RAD = Math.PI / 180;

  function dayOfYear(date) {
    return Math.round((Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) - Date.UTC(date.getFullYear(), 0, 0)) / 86400000);
  }
  /** The sun's altitude (degrees above the horizon) and whether it is still before solar noon, for a Date in its own time zone. */
  function sunState(date, lat = LAT, lon = LON) {
    const doy = dayOfYear(date);
    const decl = 23.44 * Math.sin(2 * Math.PI * (284 + doy) / 365) * RAD;
    const b = 2 * Math.PI * (doy - 81) / 364;
    const equation = 9.87 * Math.sin(2 * b) - 7.53 * Math.cos(b) - 1.5 * Math.sin(b);                    // minutes
    const clockHours = date.getHours() + date.getMinutes() / 60 + date.getSeconds() / 3600 + date.getMilliseconds() / 3600000;
    const zone = -date.getTimezoneOffset() / 60;                                                          // hours east of Greenwich
    const solar = clockHours - zone + lon / 15 + equation / 60;
    const hourAngle = 15 * (solar - 12) * RAD;
    const sinAlt = Math.sin(lat * RAD) * Math.sin(decl) + Math.cos(lat * RAD) * Math.cos(decl) * Math.cos(hourAngle);
    return { alt: Math.asin(clamp(sinAlt, -1, 1)) / RAD, morning: solar < 12, solar, decl: decl / RAD };
  }

  /** What the picture looks like at a sun altitude (keyframes, linear between): six sky bands from the zenith to the horizon, the tint that lights the ground
   *  and the sprites, the haze the distance fades into, the sun's colour and size, and how many stars and lamps are lit. */
  const KEYS = [
    { alt: -16, sky: ['#02061a', '#040a24', '#07123a', '#0b1c50', '#122a62', '#1a3a72'], tint: [.36, .44, .70], haze: '#1c3a6c', sun: '#ff9a4a', r: 26, stars: 1, lamps: 1 },
    { alt: -9, sky: ['#0a1240', '#141c5a', '#2a2a74', '#4d3382', '#7a3a80', '#b04a78'], tint: [.50, .50, .74], haze: '#8a4a7a', sun: '#ff8a4a', r: 26, stars: .75, lamps: 1 },
    { alt: -4, sky: ['#1a2a78', '#3a3a90', '#7a4690', '#c0507e', '#ee7058', '#ffa05a'], tint: [.82, .64, .70], haze: '#f08a6a', sun: '#ff7a3a', r: 26, stars: .2, lamps: .8 },
    { alt: 0, sky: ['#2c4a9c', '#4d5ca8', '#9a6aa0', '#e8806a', '#ff9a52', '#ffc070'], tint: [1.0, .80, .66], haze: '#ffb078', sun: '#ff8a3a', r: 25, stars: 0, lamps: .5 },
    { alt: 5, sky: ['#2f64b8', '#4d82cc', '#86a6d4', '#e8b88a', '#ffc47e', '#ffdca0'], tint: [1.0, .90, .74], haze: '#ffd8a0', sun: '#ffc860', r: 18, stars: 0, lamps: .1 },
    { alt: 14, sky: ['#1c62c6', '#2c80dc', '#4f9de6', '#7cc0ee', '#a9d9f0', '#d8e8d8'], tint: [1.0, .96, .86], haze: '#d0e4dc', sun: '#fff0a8', r: 11, stars: 0, lamps: 0 },
    { alt: 30, sky: ['#075bd1', '#087de8', '#159cf0', '#53c3f4', '#8fd9f2', '#bedfe3'], tint: [1, 1, 1], haze: '#bedfe3', sun: '#fff6c8', r: 8, stars: 0, lamps: 0 },
  ];
  const KEY_RGB = KEYS.map((k) => ({ alt: k.alt, sky: k.sky.map(rgb), tint: k.tint, haze: rgb(k.haze), sun: rgb(k.sun), r: k.r, stars: k.stars, lamps: k.lamps }));

  function lightAt(alt) {
    const keys = KEY_RGB;
    if (alt <= keys[0].alt) return Object.assign({}, keys[0], { alt });
    if (alt >= keys[keys.length - 1].alt) return Object.assign({}, keys[keys.length - 1], { alt });
    let i = 0;
    while (alt > keys[i + 1].alt) i++;
    const a = keys[i], b = keys[i + 1], t = smooth((alt - a.alt) / (b.alt - a.alt));
    return {
      alt,
      sky: a.sky.map((c, k) => mixRgb(c, b.sky[k], t)),
      tint: a.tint.map((v, k) => lerp(v, b.tint[k], t)),
      haze: mixRgb(a.haze, b.haze, t), sun: mixRgb(a.sun, b.sun, t),
      r: Math.round(lerp(a.r, b.r, t)), stars: lerp(a.stars, b.stars, t), lamps: lerp(a.lamps, b.lamps, t),
    };
  }
  /** A name for the moment, for the notes and the tests: day, golden, dusk (a big low sun), twilight, night. */
  function phaseName(alt) {
    return alt >= 15 ? 'day' : alt >= 4 ? 'golden' : alt >= -2 ? 'dusk' : alt >= -10 ? 'twilight' : 'night';
  }
  /** Where the sun is in the sky (art pixels): it crosses from the right in the morning to the left in the evening, over the sea. */
  function sunPlace(alt, morning, horizon = HORIZON) {
    const progress = clamp(1 - Math.max(0, alt) / 60, 0, 1);                       // 0 at the zenith of the day, 1 on the horizon
    const side = morning ? 1 : -1;
    return { x: Math.round(CX + side * (18 + 48 * progress * progress)), y: Math.round(horizon - 4 - (1 - progress) * (horizon - 30)) };
  }
  /** The moon crosses during the night from right to left. `solar` is the solar hour (0-24). */
  function moonPlace(solar, horizon = HORIZON) {
    const night = solar >= 12 ? solar - 18 : solar + 6;                             // hours after about 18:00 solar
    const t = clamp(night / 12, 0, 1);
    return { x: Math.round(176 - 150 * t), y: Math.round((34 + 18 * Math.abs(t - .5) * 2 * .6) * horizon / HORIZON) };
  }

  /* ---- the track: curves, hills and the scenery along it. Everything here is built once from the seeded random, so a given seed is always the same road. */
  const SHORE_RUMBLE = 0.10;                                   // a kerb is this fraction of the road's half width (at least one pixel)

  /** The beach is this wide (world units) at segment i: it breathes along the coast so the sea bends in and out. */
  function beachAt(i) {
    return Math.max(420, 760 + 360 * Math.sin(i * 0.011 + 1.3) + 220 * Math.sin(i * 0.037 + 0.4));
  }

  /** Optional private turn samples are adapted from a user's original road.
   * Invalid or missing data keeps the self-contained procedural drive. */
  function validRoute(samples) {
    return Array.isArray(samples) && samples.length >= 64 && samples.length <= 2048 &&
      samples.every((v) => Number.isInteger(v) && v >= -127 && v <= 127);
  }
  /** Curves and hills close smoothly at the end of the perpetual drive. */
  function buildTrack(rand, count = TRACK, route = null) {
    const sourced = validRoute(route);
    if (sourced) count = route.length * 14;
    const curve = new Float32Array(count), height = new Float32Array(count + 1);
    if (sourced) {
      for (let k = 0; k < count; k++) {
        const sample = k / 14, i = Math.floor(sample), t = sample - i;
        curve[k] = lerp(route[i], route[(i + 1) % route.length], t) / 127;
      }
    } else {
      let i = 0;
      while (i < count) {
        const len = Math.min(count - i, 50 + Math.floor(rand() * 110));
        const first = i < 80 || i + len >= count - 80;                              // the start and the end of the loop are straight
        const strength = first || rand() < 0.28 ? 0 : (0.25 + rand() * 0.6) * (rand() < 0.5 ? -1 : 1);
        for (let k = 0; k < len; k++) {
          const t = k / len;
          curve[i + k] = strength * smooth(Math.min(1, t / 0.3)) * smooth(Math.min(1, (1 - t) / 0.3));
        }
        i += len;
      }
    }
    const waves = [[7, 300 + rand() * 80, rand() * 6.28], [19, 60 + rand() * 40, rand() * 6.28], [3, 200 + rand() * 80, rand() * 6.28]];
    for (let k = 0; k <= count; k++) {
      let y = 0;
      for (const [n, a, phase] of waves) y += a * Math.sin(2 * Math.PI * n * k / count + phase);
      height[k] = y;
    }
    return { count, curve, height, length: count * SEG, sourced };
  }

  /** How big each kind of roadside thing really is (world units tall); the atlas draws it at a ladder of pixel heights and the scene picks the nearest. */
  const KINDS = {
    palm0: 1500, palm1: 1000, pine: 1300, bush: 380, rock0: 520, rock1: 420, post: 480, sign0: 1000, sign1: 1000, billboard: 1700, house0: 1050, house1: 950,
    block: 2200, lamp: 1500, parasol: 450, boat: 800, windsurf: 900, bridge: 1260,
    windmill: 1850, billboard1: 1700, icecream: 1000, crowd: 560, forksign: 1150,
  };

  function buildScenery(rand, track) {
    const n = track.count, list = new Array(n);
    const add = (seg, kind, off, more) => { seg = ((seg % n) + n) % n; (list[seg] || (list[seg] = [])).push(Object.assign({ kind, off }, more)); };
    const between = (a, b) => a + rand() * (b - a);
    for (let i = 3; i < n; i += 6) { add(i, 'post', -(ROAD + 240)); add(i + 3, 'post', ROAD + 240); }              // reflector posts: they show the speed
    for (let i = 10; i < n; i += 30 + Math.floor(rand() * 20)) add(i, 'lamp', ROAD + 330);                          // lamp posts: lit at night
    let i = 12;
    while (i < n - 30) {
      const len = 100 + Math.floor(rand() * 160), pick = rand(), end = Math.min(n - 20, i + len);
      const theme = pick < 0.36 ? 'avenue' : pick < 0.60 ? 'resort' : pick < 0.76 ? 'wild' : pick < 0.90 ? 'signs' : 'open';
      for (let k = i, flip = 0; k < end; flip ^= 1) {
        const beach = beachAt(k);
        if (theme === 'avenue') {
          add(k, flip ? 'palm1' : 'palm0', -(ROAD + 330 + beach * 0.3 + rand() * 120));
          if (rand() < 0.5) add(k + 2, rand() < 0.5 ? 'pine' : 'bush', ROAD + between(700, 2400));
          k += 5;
        } else if (theme === 'resort') {
          const kind = ['house0', 'house1', 'block', 'house0'][Math.floor(rand() * 4)];
          add(k, kind, ROAD + between(800, 1900));
          if (rand() < 0.6) add(k + 3, rand() < 0.5 ? 'palm0' : 'palm1', -(ROAD + 330 + beach * 0.4));
          if (rand() < 0.4) add(k + 5, 'parasol', -(ROAD + beach * 0.8));
          k += 12 + Math.floor(rand() * 10);
        } else if (theme === 'wild') {
          add(k, rand() < 0.5 ? 'rock0' : 'rock1', (rand() < 0.5 ? -1 : 1) * (ROAD + between(500, 1600)) * (1));
          if (rand() < 0.7) add(k + 3, 'bush', ROAD + between(500, 2800));
          if (rand() < 0.4) add(k + 6, 'pine', ROAD + between(1400, 3600));
          k += 7 + Math.floor(rand() * 8);
        } else if (theme === 'signs') {
          add(k, flip ? 'sign0' : 'sign1', (flip ? 1 : -1) * (ROAD + 420));
          if (flip && rand() < 0.5) add(k + 4, 'billboard', ROAD + between(1100, 1700));
          k += 18 + Math.floor(rand() * 12);
        } else {
          if (rand() < 0.5) add(k, 'bush', (rand() < 0.5 ? -1 : 1) * (ROAD + between(500, 2000)));
          k += 14 + Math.floor(rand() * 12);
        }
      }
      i = end;
    }
    for (let k = 5; k < n; k += 5 + Math.floor(rand() * 5)) add(k, rand() < 0.6 ? 'bush' : 'pine', ROAD + between(1300, 5500));        // the land side is never bare
    // Layers beyond the verge make the land feel inhabited without placing
    // anything on the road or in front of the car.
    for (let k = 18; k < n; k += 16 + Math.floor(rand() * 9)) {
      add(k, rand() < 0.5 ? 'palm0' : 'palm1', ROAD + between(750, 1650));
      add(k + 4, rand() < 0.55 ? 'bush' : 'rock1', ROAD + between(1900, 3800));
      if (rand() < 0.42) add(k + 8, rand() < 0.5 ? 'house0' : 'house1', ROAD + between(2500, 4300));
    }
    for (let k = 70, flip = 0; k < n; k += 70 + Math.floor(rand() * 50), flip ^= 1) add(k, flip ? 'sign0' : 'sign1', (flip ? 1 : -1) * (ROAD + 420));       // a sign every 15 s or so
    for (let k = 90; k < n; k += 140 + Math.floor(rand() * 120)) add(k, 'billboard', ROAD + between(1100, 1900));                                        // and a billboard: a sunset over the sea
    for (let k = 180; k < n - 30; k += 320 + Math.floor(rand() * 180)) {
      // A few distinctive original-game sights, interspersed rather than
      // arranged as a repeating strip of identical billboards.
      const kind = ['windmill', 'icecream', 'billboard1', 'forksign'][Math.floor(rand() * 4)];
      add(k, kind, ROAD + between(1400, 2600));
      if (kind === 'icecream' || kind === 'forksign') add(k + 5, 'crowd', ROAD + between(1100, 1700));
    }
    for (let k = 260; k < n - 40; k += 520 + Math.floor(rand() * 380)) add(k, 'bridge', 0);                        // an overpass now and then
    for (let k = 20; k < n - 20; k += 22 + Math.floor(rand() * 26)) {                                               // sailboats in the sea on the left
      add(k, rand() < 0.7 ? 'boat' : 'windsurf', -(ROAD + beachAt(k) + between(1500, 8500)), { drift: (rand() < 0.5 ? -1 : 1) * between(0, 40) });
    }
    return list;
  }

  /* ---- the projection: the classic scanline road. For each segment ahead, its near and far edge go to rows and x positions, hills hide what is behind a crest. */
  function makeProjection() {
    const f = (n, T = Float32Array) => new T(n);
    return { y1: f(DRAW), y2: f(DRAW), xn: f(DRAW), xf: f(DRAW), hn: f(DRAW), hf: f(DRAW), zn: f(DRAW), zf: f(DRAW), top: f(DRAW, Int16Array), bot: f(DRAW, Int16Array),
      clip: f(DRAW, Int16Array), idx: f(DRAW, Int32Array), top0: H, camZ: 0, base: 0, percent: 0, geo: DEFAULT_GEO };
  }
  /** Fill `out` for a camera at (camZ along the track, camX across it, camY above the ground) and a layout `geo` (the horizon row and the vertical focal length).
   *  Returns `out`; `out.top0` is the highest row the road reaches. */
  function projectRoad(track, camZ, camX, camY, out, geo = DEFAULT_GEO) {
    const n = track.count, total = track.length, hz = geo.horizon, fy = geo.fy;
    const z0 = ((camZ % total) + total) % total;
    const base = Math.floor(z0 / SEG), percent = (z0 - base * SEG) / SEG;
    let x = 0, dx = -track.curve[base] * percent, clip = H;
    out.geo = geo;
    for (let k = 0; k < DRAW; k++) {
      const idx = (base + k) % n;
      const z1 = Math.max(60, k * SEG - percent * SEG), z2 = Math.max(61, (k + 1) * SEG - percent * SEG);
      const y1 = hz + (camY - HILL_GAIN * track.height[idx]) * fy / z1, y2 = hz + (camY - HILL_GAIN * track.height[idx + 1]) * fy / z2;
      out.idx[k] = idx; out.zn[k] = z1; out.zf[k] = z2; out.y1[k] = y1; out.y2[k] = y2;
      out.xn[k] = CX + (x - camX) * FX / z1; out.xf[k] = CX + (x + dx - camX) * FX / z2;
      out.hn[k] = ROAD * FX / z1; out.hf[k] = ROAD * FX / z2;
      out.clip[k] = clip;
      let top = 0, bot = 0;
      if (y2 < y1 && y2 < clip && z2 > 60) {
        top = Math.max(0, Math.round(y2)); bot = Math.min(Math.round(y1), clip);
        if (bot > top) clip = top; else { top = 0; bot = 0; }
      }
      out.top[k] = top; out.bot[k] = bot;
      x += dx; dx += track.curve[idx];
    }
    out.top0 = clip; out.camZ = camZ; out.base = base; out.percent = percent;
    return out;
  }
  /** The road at a depth `z` (relative to the camera) inside the drawn segments: its screen row, centre x and half width (null beyond the drawing distance). */
  function sampleRoad(out, z) {
    const k = Math.floor((z + out.percent * SEG) / SEG);
    if (k < 0 || k >= DRAW) return null;
    const near = out.zn[k], far = out.zf[k], s = clamp((1 / near - 1 / Math.max(z, 1)) / (1 / near - 1 / far), 0, 1);
    return { k, y: lerp(out.y1[k], out.y2[k], s), x: lerp(out.xn[k], out.xf[k], s), half: ROAD * FX / Math.max(z, 1), hidden: lerp(out.y1[k], out.y2[k], s) > out.clip[k] + 1 };
  }

  /* ---- the world: the camera, the player's car and its autopilot, the rivals, the clouds and gulls. All logic, no drawing; `step()` is one 30 Hz tick. */
  const CRUISE = 6750;                                         // faster arcade drive, without changing the animation frame rate
  const LANE_SPEED = [0.78, 0.72, 0.68];                     // visibly slower traffic, varied from lane to lane
  const RIVAL_WIDTH = 480, RIVAL_COLOURS = 8;
  const HOP = [0, -2, -4, -5, -6, -6, -5, -4, -2, 0, 0, -1, -3, -4, -4, -3, -1, 0];       // a honk-hop: two bounces, whole pixels

  const FOLLOW_WIDTH = 520;                                    // a car this close sideways is in our way
  /** The speed to hold behind a leader `gap` units ahead: the leader's own speed at about a car and a half, a little more when far, a little less when too close. */
  const followSpeed = (leader, gap) => Math.max(120, leader + clamp((gap - 1100) * 0.6, -150, 300));
  const wrapZ = (z, total) => { const m = ((z % total) + total) % total; return m > total / 2 ? m - total : m; };
  const laneX = (lane) => (lane - 1) * LANE;
  function heightAt(track, z) {
    const total = track.length, m = ((z % total) + total) % total, i = Math.floor(m / SEG), t = (m - i * SEG) / SEG;
    return lerp(track.height[i], track.height[i + 1], t);
  }

  function createWorld(options) {
    const o = Object.assign({ seed: 20261109, clock: () => new Date(), random: null }, options);
    const rand = typeof o.random === 'function' ? o.random : seeded(o.seed);
    const track = buildTrack(rand, TRACK, o.route), scenery = buildScenery(rand, track);
    const world = {
      track, scenery, rand, steps: 0, time: 0, camZ: 0, camX: 0, camY: CAM_H, speed: CRUISE, light: null, sun: null, clockAt: -1, solar: 12,
      player: { x: 0, vx: 0, lane: 1, cooldown: 45, lean: 0, leanHold: 0, hop: 0, honk: 0, changes: 0 },
      rivals: [], clouds: [], gulls: [], scroll: { far: 0, near: 0, farAcc: 0, nearAcc: 0 }, stars: [], wave: 0,
    };
    const total = track.length;
    // rivals: ten cars, four in the slow lane, three in the middle, three in the fast one (two of them behind us), spread along the road
    const place = (lane, z) => ({ z, lane, x: laneX(lane) + Math.round((rand() - .5) * 120), speed: CRUISE * LANE_SPEED[lane], v: CRUISE * LANE_SPEED[lane], colour: Math.floor(rand() * RIVAL_COLOURS), kind: Math.floor(rand() * 3) });
    for (const [lane, offsets] of [[2, [3000, 8500, 14500, 21500]], [1, [5500, 12500, 19500]], [0, [-6500, -14000, 4000]]]) {
      for (const base of offsets) world.rivals.push(place(lane, base + Math.round(rand() * 2000)));
    }
    // four clouds on their own bands of sky, so two never pile up into one white block
    for (let i = 0; i < 4; i++) world.clouds.push({ x: Math.round(rand() * W), f: (i + 0.15 + rand() * 0.6) / 4, kind: [4, 2, 5, 3][i], speed: 0.04 + rand() * 0.07, acc: 0 });
    for (let i = 0; i < 2; i++) world.gulls.push(makeGull(rand, i));
    for (let i = 0; i < 90; i++) world.stars.push({ x: Math.floor(rand() * W), f: rand(), at: rand(), tw: Math.floor(rand() * 3), big: rand() < 0.12 });

    function makeGull(r, i) {
      const dir = i % 2 ? -1 : 1;
      return { x: dir > 0 ? -20 - Math.round(r() * 120) : W + 20 + Math.round(r() * 120), y: 22 + Math.round(r() * 34), dir, small: r() < 0.5, phase: Math.floor(r() * 4), bob: r() * 6, speed: 0.6 + r() * 0.4, acc: 0, poked: false };
    }
    /** Will a car of this lane come within `margin` units of ours in the next `horizon` seconds, if everybody keeps their speed? */
    const threatened = (lane, horizon, margin) => world.rivals.some((r) => {
      if (r.lane !== lane) return false;
      const d = wrapZ(r.z - (world.camZ + ZP), total), closing = r.v - world.speed;
      for (let s = 0; s <= horizon; s += 0.25) if (Math.abs(d + closing * s) < margin) return true;
      return false;
    });

    world.updateLight = function () {
      const date = o.clock(), s = sunState(date);
      world.sun = s; world.solar = s.solar; world.light = lightAt(s.alt); world.light.morning = s.morning; world.light.phase = phaseName(s.alt);
      world.clockAt = world.steps;
    };
    world.updateLight();

    world.step = function () {
      world.steps++; world.time += STEP;
      const p = world.player, t = world.time;
      if (world.steps - world.clockAt >= 90) world.updateLight();                                             // the sun moves slowly: look at the clock every 3 s
      // speed: a gentle cruise that eases on hills, and never faster than a car just ahead of us (the car follows a slower one, it does not ram it)
      const slope = (heightAt(track, world.camZ + ZP + 400) - heightAt(track, world.camZ + ZP)) / 400;
      let target = CRUISE * (1 + 0.05 * Math.sin(t * 0.21) + 0.03 * Math.sin(t * 0.53)) * (1 - clamp(slope * 2.2, -0.12, 0.18));
      for (const r of world.rivals) {
        const d = wrapZ(r.z - (world.camZ + ZP), total);
        if (d > 0 && d < 2400 && Math.abs(r.x - p.x) < FOLLOW_WIDTH) target = Math.min(target, followSpeed(r.v, d));
      }
      world.speed += (target - world.speed) * (target < world.speed ? 0.09 : 0.04);
      // At high speed reserve a real gap, including the next simulation step.
      // This also covers the brief instant while a lane change is beginning.
      for (const r of world.rivals) {
        const d = wrapZ(r.z - (world.camZ + ZP), total);
        if (d > 0 && Math.abs(r.x - p.x) < FOLLOW_WIDTH) {
          const nextRivalSpeed = Math.min(r.v, world.speed * 0.98);
          world.speed = Math.min(world.speed, Math.max(0, nextRivalSpeed + (d - 650) / STEP));
        }
      }
      world.camZ += world.speed * STEP;
      // the autopilot: when a car will be near us in this lane within a few seconds, move to a lane that stays free for longer; now and then just weave
      p.cooldown = Math.max(0, p.cooldown - 1);
      if (Math.abs(p.x - laneX(p.lane)) < 90 && p.cooldown === 0) {
        const crowded = threatened(p.lane, 5, 1500);
        const free = [p.lane - 1, p.lane + 1].filter((l) => l >= 0 && l <= 2 && !threatened(l, 4.5, 1300));
        if (free.length && (crowded || rand() < 1 / 1100)) { p.lane = free[Math.floor(rand() * free.length)]; p.cooldown = crowded ? 100 : 240; p.changes++; }
      }
      const ax = 10 * (laneX(p.lane) - p.x) - 6.4 * p.vx;
      p.vx += ax * STEP; p.x += p.vx * STEP;
      // the camera follows the car with a little lag, so the car swings on the screen when it changes lane
      world.camX += (p.x - world.camX) * 0.1;
      world.camY = CAM_H + HILL_GAIN * heightAt(track, world.camZ + ZP);
      // the lean of the car: its sideways speed and the bend ahead, held for a few steps so the sprite never flickers
      const bend = track.curve[(Math.floor(world.camZ / SEG) + 6) % track.count];
      const want = clamp(Math.round(p.vx / 260 + bend * 1.6), -2, 2);
      if (want === p.lean) p.leanHold = 0; else if (++p.leanHold >= 5) { p.lean = want; p.leanHold = 0; }
      if (p.hop > 0) p.hop--;
      if (p.honk > 0) p.honk--;
      // the rivals drive on at their own speed, slowing behind a car (or ours) in their lane; one that is far behind (or far ahead) comes back on the other side of the picture
      for (const r of world.rivals) {
        let cap = r.speed;
        const behindUs = wrapZ(world.camZ + ZP - r.z, total);
        if (behindUs > 0 && behindUs < 2400 && Math.abs(p.x - r.x) < FOLLOW_WIDTH) cap = Math.min(cap, followSpeed(world.speed, behindUs));
        for (const q of world.rivals) {
          const gap = q === r || q.lane !== r.lane ? -1 : wrapZ(q.z - r.z, total);
          if (gap > 0 && gap < 2400) cap = Math.min(cap, followSpeed(q.v, gap));
        }
        r.v += (cap - r.v) * (cap < r.v ? 0.12 : 0.05);
        // A car behind must fall back, not match our speed indefinitely: a
        // neighbour alongside can otherwise block the lane needed to overtake.
        // Cars ahead keep their own speed so traffic does not gradually stop.
        if (behindUs > 0) r.v = Math.min(r.v, world.speed * .85);
        r.z += r.v * STEP;
        const d = wrapZ(r.z - (world.camZ + ZP), total);
        if (d < -9000 || d > DRAW * SEG + 8500) {
          for (let tries = 0; tries < 8; tries++) {
            const z = world.camZ + ZP + DRAW * SEG + rand() * 5000;
            const clash = world.rivals.some((q) => q !== r && q.lane === r.lane && Math.abs(wrapZ(q.z - z, total)) < 5200);
            if (!clash || tries === 7) { r.z = z; r.v = r.speed; r.colour = Math.floor(rand() * RIVAL_COLOURS); r.kind = Math.floor(rand() * 3); r.x = laneX(r.lane) + Math.round((rand() - .5) * 120); break; }
          }
        }
      }
      // clouds drift a whole pixel at a time; gulls flap and cross; the mountains slide as the road bends
      for (const c of world.clouds) { c.acc += c.speed; while (c.acc >= 1) { c.acc -= 1; c.x += 1; } if (c.x > W + 60) { c.x = -70 - Math.round(rand() * 60); c.kind = 2 + Math.floor(rand() * 4); } }
      for (const g of world.gulls) {
        g.acc += g.speed; while (g.acc >= 1) { g.acc -= 1; g.x += g.dir; }
        if (world.steps % 4 === 0) g.phase = (g.phase + 1) % 4;
        if ((g.dir > 0 && g.x > W + 24) || (g.dir < 0 && g.x < -24)) {
          if (g.poked) g.dead = true; else { g.dir = -g.dir; g.y = 20 + Math.round(rand() * 36); g.small = rand() < 0.5; g.x = g.dir > 0 ? -16 - Math.round(rand() * 160) : W + 16 + Math.round(rand() * 160); }
        }
      }
      world.gulls = world.gulls.filter((g) => !g.dead);
      const near = track.curve[(Math.floor(world.camZ / SEG) + 12) % track.count] * (world.speed / CRUISE);
      world.scroll.farAcc += near * 0.35; world.scroll.nearAcc += near * 0.8;
      while (world.scroll.farAcc >= 1) { world.scroll.farAcc -= 1; world.scroll.far++; } while (world.scroll.farAcc <= -1) { world.scroll.farAcc += 1; world.scroll.far--; }
      while (world.scroll.nearAcc >= 1) { world.scroll.nearAcc -= 1; world.scroll.near++; } while (world.scroll.nearAcc <= -1) { world.scroll.nearAcc += 1; world.scroll.near--; }
      world.wave += 1;
    };

    /** A touch: below the horizon the car honks and hops, above it a gull takes off from the finger. */
    world.poke = function (x, y, horizon = HORIZON) {
      if (y > horizon - 6) { if (world.player.hop === 0) { world.player.hop = HOP.length; world.player.honk = 24; } return 'honk'; }
      if (world.gulls.length < 7) world.gulls.push({ x: Math.round(x), y: Math.round(y), dir: x > CX ? 1 : -1, small: false, phase: 0, bob: 0, speed: 1.6, acc: 0, poked: true });
      return 'gull';
    };
    return world;
  }

  /* ---- the palette: every flat colour of the picture for the current light, in tables by distance level (0 = near and crisp, 11 = far, flat and hazy) */
  const LEVELS = 12;
  const BASE = {
    grass: ['#66bf43', '#59af39'], sand: ['#f5db91', '#ecce80'], sea: ['#35d4cc', '#2bc3c4'], kerb: ['#fff3d8', '#ef3939'], road: ['#687184', '#555d6d'],
    lane: ['#fff7e4', '#fff7e4'], edge: ['#f4f4ec', '#f4f4ec'], foam: ['#e5fff1', '#e5fff1'], wet: ['#d9bc76', '#d9bc76'], glint: ['#9af2e4', '#baf9ee'],
  };
  function buildPalette(light) {
    const tint = light.tint, haze = light.haze, pal = { sky: new Uint32Array(6), skyRgb: light.sky.slice() };
    for (let i = 0; i < 6; i++) pal.sky[i] = pack(light.sky[i]);
    for (const [name, [a, b]] of Object.entries(BASE)) {
      const table = new Uint32Array(LEVELS * 2), ca = mulRgb(rgb(a), tint), cb = mulRgb(rgb(b), tint), avg = mixRgb(ca, cb, 0.5);
      for (let l = 0; l < LEVELS; l++) {
        const flat = Math.min(1, l / 7), mist = Math.min(1, l / (LEVELS - 1)) * 0.6;
        table[l * 2] = pack(mixRgb(mixRgb(ca, avg, flat), haze, mist));
        table[l * 2 + 1] = pack(mixRgb(mixRgb(cb, avg, flat), haze, mist));
      }
      pal[name] = table;
    }
    pal.mountainFar = mulRgb(mixRgb(rgb('#7f98c8'), light.haze, 0.35), tint); pal.mountainNear = mulRgb(mixRgb(rgb('#4f7da0'), light.haze, 0.2), tint);
    pal.hill = mulRgb(mixRgb(rgb('#3d8f58'), light.haze, 0.12), tint);
    pal.glitter = mixRgb(light.sun, mulRgb(rgb('#35d4cc'), tint), 0.35);
    return pal;
  }

  /* ---- the backdrop and the ground, written straight into a typed array (one putImageData per frame) */
  const SKY_FRACTIONS = [0.22, 0.42, 0.62, 0.78, 0.9];         // the bands end at these shares of the sky's height
  /** A static map of which sky band each pixel belongs to, with gently undulating edges (flat bands, like hand-painted sky; no dithering). */
  const SKY_ROWS = 100;                                        // the map is drawn for this many rows and stretched to the horizon of the moment
  function makeSkyMap() {
    const map = new Uint8Array(W * SKY_ROWS);
    for (let x = 0; x < W; x++) {
      const edges = SKY_FRACTIONS.map((f, i) => Math.round(f * SKY_ROWS + 1.4 * Math.sin(x * (0.05 + i * 0.013) + i * 1.9)));
      for (let y = 0; y < SKY_ROWS; y++) { let b = 0; while (b < 5 && y >= edges[b]) b++; map[y * W + x] = b; }
    }
    return map;
  }
  /** A periodic ridge line: smooth noise that repeats every `period` columns, so a scrolling mountain never shows a seam. */
  function makeRidge(rand, period, low, high, bumps) {
    const out = new Int16Array(period), phase = [], amp = [];
    for (let i = 0; i < bumps; i++) { phase.push(rand() * 6.283); amp.push(0.4 + rand()); }
    let lo = 1e9, hi = -1e9; const raw = new Float32Array(period);
    for (let x = 0; x < period; x++) {
      let v = 0;
      for (let i = 0; i < bumps; i++) v += amp[i] * Math.sin(2 * Math.PI * (i + 2) * x / period + phase[i]) / (1 + i * 0.5);
      raw[x] = v; lo = Math.min(lo, v); hi = Math.max(hi, v);
    }
    for (let x = 0; x < period; x++) out[x] = Math.round(low + (high - low) * (raw[x] - lo) / (hi - lo));
    return out;
  }
  function fillSpan(buf, y, x0, x1, colour) {
    if (x0 < 0) x0 = 0; if (x1 > W) x1 = W;
    if (x1 > x0 && y >= 0 && y < H) buf.fill(colour, y * W + x0, y * W + x1);
  }
  /** The sky down to the horizon row `hz`: bands, stars, the sun or the moon, the far and near mountains and the green headlands. */
  function paintSky(buf, view, pal, world, light, hz) {
    const t = pal.sky, map = view.skyMap, scale = hz / HORIZON;
    for (let y = 0; y < hz; y++) {
      const row = Math.min(SKY_ROWS - 1, Math.floor(y * SKY_ROWS / hz)) * W, o = y * W;
      for (let x = 0; x < W; x++) buf[o + x] = t[map[row + x]];
    }
    const bandAt = (y) => { let b = 0; while (b < 5 && y >= SKY_FRACTIONS[b] * hz) b++; return b; };
    if (light.stars > 0.02) {
      const on = light.stars, white = pack([225, 232, 255]), dim = pack([140, 160, 210]);
      for (const s of world.stars) {
        if (s.at > on) continue;
        const twinkle = ((world.steps >> 4) + s.tw) % 4 === 0, y = 3 + Math.floor(s.f * (hz - 24));
        buf[y * W + s.x] = twinkle ? dim : white;
        if (s.big && !twinkle) { buf[y * W + s.x + 1] = dim; buf[(y + 1) * W + s.x] = dim; }
      }
    }
    const sunAbove = light.alt > -4;                                                    // the disc is drawn until it has set behind the sea
    if (sunAbove) {
      const place = sunPlace(light.alt, light.morning, hz), r = light.r;
      for (let ring = 2; ring >= 0; ring--) {
        const rad = r + (ring === 2 ? 7 : ring === 1 ? 3 : 0);
        for (let y = Math.max(0, place.y - rad); y <= Math.min(hz - 1, place.y + rad); y++) {
          const dy = y - place.y, half = Math.floor(Math.sqrt(rad * rad - dy * dy + 0.25));
          const sky = pal.skyRgb[bandAt(y)];
          const colour = ring === 0 ? light.sun : mixRgb(sky, light.sun, ring === 1 ? 0.42 : 0.18);
          fillSpan(buf, y, place.x - half, place.x + half + 1, pack(colour));
        }
      }
      if (r >= 14) {                                                                    // a big low sun has a brighter heart
        const heart = pack(mixRgb(light.sun, [255, 255, 255], 0.32)), rad = Math.round(r * 0.58);
        for (let y = Math.max(0, place.y - rad); y <= Math.min(hz - 1, place.y + rad); y++) {
          const dy = y - place.y, half = Math.floor(Math.sqrt(rad * rad - dy * dy + 0.25));
          fillSpan(buf, y, place.x - half, place.x + half + 1, heart);
        }
      }
      world.sunScreen = place;
    } else world.sunScreen = null;
    if (light.alt < -2) {                                                              // the moon: a pale disc with a crescent bitten out of it
      const m = moonPlace(world.solar, hz), moon = pack([244, 240, 216]);
      for (let y = m.y - 6; y <= m.y + 6; y++) {
        const dy = y - m.y, half = Math.floor(Math.sqrt(36 - dy * dy + 0.25));
        fillSpan(buf, y, m.x - half, m.x + half + 1, moon);
        const dy2 = y - (m.y - 1), cut = 25 - dy2 * dy2;
        if (cut > 0) { const h2 = Math.floor(Math.sqrt(cut)); fillSpan(buf, y, m.x - 3 - h2, m.x - 3 + h2 + 1, t[bandAt(y)]); }
      }
    }
    for (const [ridge, scroll, colour, low] of [[view.ridgeFar, world.scroll.far, pal.mountainFar, 0.3], [view.ridgeNear, world.scroll.near, pal.mountainNear, 0.12]]) {
      const period = ridge.length, packed = pack(colour), crest = pack(mixRgb(colour, [255, 255, 255], 0.18)), foot = pack(mixRgb(colour, light.haze, 0.45));
      for (let x = 0; x < W; x++) {
        const lift = (low + (1 - low) * smooth(x / W)) * scale;                          // the sea side is low and open (the sun sets there); the mountains stand on the land side
        const top = hz - Math.round(ridge[(((x + scroll) % period) + period) % period] * lift);
        if (top >= hz) continue;
        const o = top * W + x;
        buf[o] = crest;
        for (let y = top + 1; y < hz; y++) buf[y * W + x] = y >= hz - 2 ? foot : packed;
      }
    }
    const hill = pack(pal.hill), hillCrest = pack(mixRgb(pal.hill, [255, 255, 255], 0.2)), period = view.ridgeHill.length;       // green headlands on the land side, none over the sea
    for (let x = 60; x < W; x++) {
      const ramp = clamp((x - 60) / 70, 0, 1) * scale, top = hz - Math.round(view.ridgeHill[(((x + world.scroll.near) % period) + period) % period] * ramp);
      if (top >= hz) continue;
      buf[top * W + x] = hillCrest;
      for (let y = top + 1; y < hz; y++) buf[y * W + x] = hill;
    }
  }

  /** The player's sprite and its light use the same screen position. */
  const playerScreenX = (world) => CX + Math.round((world.player.x - world.camX) * FX / ZP);

  /** Two short arcade beams that reach the shoulders and stop at the waterline. */
  function headlightRow(buf, y, left, right, centre, carRow, amount, sandStart = 0) {
    const distance = carRow - 23 - y;
    if (amount <= 0.2 || distance < 0 || distance >= 34) return;
    const separation = 16 + Math.floor(distance * 0.58), radius = 13 + Math.floor(distance * 0.75);
    const strength = 0.72 * amount * (1 - smooth(distance / 34));
    const shoulderReach = 34;
    const from = Math.max(0, sandStart, left - shoulderReach, Math.floor(centre - separation - radius));
    const to = Math.min(W, right + shoulderReach, Math.ceil(centre + separation + radius));
    for (let x = from; x < to; x++) {
      const d = Math.min(Math.abs(x - centre - separation), Math.abs(x - centre + separation));
      if (d >= radius) continue;
      const band = d < radius * 0.45 ? 1 : d < radius * 0.75 ? 0.65 : 0.35;
      const shoulderDistance = Math.max(0, left - x, x - right + 1);
      const a = strength * band * (1 - smooth(shoulderDistance / shoulderReach));
      const index = y * W + x, pixel = buf[index];
      const r = pixel & 255, green = (pixel >>> 8) & 255, b = (pixel >>> 16) & 255;
      buf[index] = (0xff000000 | (Math.round(b + (220 - b) * a) << 16) | (Math.round(green + (240 - green) * a) << 8) | Math.round(r + (255 - r) * a)) >>> 0;
    }
  }

  /** The ground: sea on the left, beach, kerbs, the road and grass on the right, row by row from the segments the projection found. */
  function paintGround(buf, proj, pal, world, light) {
    const camZ = proj.camZ, wave = world.wave, glit = world.sunScreen && light.alt < 24 ? world.sunScreen : null, hz = proj.geo.horizon, kc = proj.geo.contrast;
    const carX = playerScreenX(world), carRow = proj.geo.carRow + (world.player.hop > 0 ? HOP[HOP.length - world.player.hop] : 0);
    let lastX = CX, lastTop = H, prevCell = -1;
    for (let k = 0; k < DRAW; k++) {
      const top = proj.top[k], bot = proj.bot[k];
      if (bot <= top) continue;
      const y1 = proj.y1[k], y2 = proj.y2[k], span = y1 - y2, xn = proj.xn[k], xf = proj.xf[k], hn = proj.hn[k], hf = proj.hf[k];
      const invN = 1 / proj.zn[k], invF = 1 / proj.zf[k], beach = beachAt(proj.idx[k]);
      for (let y = top; y < bot; y++) {
        const t = clamp((y + 0.5 - y2) / span, 0, 1);
        const xc = xf + (xn - xf) * t, half = hf + (hn - hf) * t, inv = invF + (invN - invF) * t;
        const wz = camZ + 1 / inv, band = Math.floor(wz / BAND), p = band & 1, r = (y - hz) * kc;       // r: the row's distance below the horizon, as it would be in the plain layout
        const level = r >= 72 ? 0 : r <= 6 ? LEVELS - 1 : ((72 - r) / 6) | 0, li = level * 2;
        const rw = Math.max(1, Math.round(half * SHORE_RUMBLE)), eL = Math.round(xc - half), eR = Math.round(xc + half);
        const shore = eL - rw - Math.round(beach * inv * FX), foam = r > 40 ? 2 : 1;
        fillSpan(buf, y, 0, shore, pal.sea[li + (Math.floor((wz - wave * 1.6) / (BAND * 2)) & 1)]);
        const cell = Math.floor(wz / (BAND * 1.5));
        if (cell !== prevCell) {                                                          // short lighter strokes fixed in the water: they come toward us with the world
          prevCell = cell;
          const h = Math.imul(cell, 2654435761) >>> 0;
          if (r > 6 && shore > 6 && ((h >>> 5) + (wave >> 3)) % 5 !== 0) {
            const len = Math.max(2, Math.round(2 + r / 7)), x1 = Math.round(((h >>> 8) % 1000) / 1000 * (shore - len)), x2 = Math.round(((h >>> 18) % 1000) / 1000 * (shore - len));
            fillSpan(buf, y, x1, x1 + len, pal.glint[li + (h & 1)]);
            if (h & 2) fillSpan(buf, y, x2, x2 + Math.max(2, len - 1), pal.glint[li]);
          }
        }
        if (glit && r < 60 && shore > 0) {
          // A broken trail of short, independent glints reads as light on
          // ripples, rather than a filled polygon painted over the water.
          const h = Math.imul(y * 73 + (wave >> 3) * 19, 2654435761) >>> 0;
          const spread = 2 + (r >> 2), gx = glit.x + Math.round(((h & 255) / 127.5 - 1) * spread);
          const len = 1 + ((h >>> 9) % Math.max(2, Math.round(1 + r / 14)));
          if ((h >>> 20) % 5 < 3) fillSpan(buf, y, gx, Math.min(gx + len, shore), pack(pal.glitter));
        }
        fillSpan(buf, y, shore, shore + foam, pal.foam[li]);
        fillSpan(buf, y, shore + foam, eL - rw, pal.sand[li + p]);
        if (r > 12) fillSpan(buf, y, shore + foam, shore + foam + 2, pal.wet[li]);
        fillSpan(buf, y, eL - rw, eL, pal.kerb[li + p]);
        fillSpan(buf, y, eL, eR, pal.road[li + p]);
        fillSpan(buf, y, eR, eR + rw, pal.kerb[li + p]);
        fillSpan(buf, y, eR + rw, W, pal.grass[li + p]);
        if (half >= 9 && level < 6) { fillSpan(buf, y, eL, eL + 1, pal.edge[li]); fillSpan(buf, y, eR - 1, eR, pal.edge[li]); }
        if (r >= 30 && (Math.floor(wz / (BAND * 3)) & 1) === 0) {
          const dw = Math.max(1, Math.round(half * 0.035)), third = half / 3;
          fillSpan(buf, y, Math.round(xc - third - dw / 2), Math.round(xc - third - dw / 2) + dw, pal.lane[li]);
          fillSpan(buf, y, Math.round(xc + third - dw / 2), Math.round(xc + third - dw / 2) + dw, pal.lane[li]);
        }
        if (light.lamps > 0.2) headlightRow(buf, y, eL, eR, carX, carRow, light.lamps, shore + foam);
        lastX = xc;
      }
      lastTop = Math.min(lastTop, top);
    }
    const far = LEVELS - 1, edge = Math.round(lastX - 14);                              // behind a crest or past the drawing distance: far sea and grass
    for (let y = Math.max(hz - 1, 0); y < lastTop; y++) { fillSpan(buf, y, 0, edge, pal.sea[far * 2]); fillSpan(buf, y, edge, W, pal.grass[far * 2]); }
  }

  /* ---- the atlas: ladders of sprites by kind, the nearest rung for a size, and tinted copies of the sheet for dusk and night */
  function readAtlas(json) {
    if (!json || typeof json !== 'object' || !json.frames || typeof json.frames !== 'object') return null;
    const entry = (name) => {
      const f = json.frames[name];
      if (!Array.isArray(f) || f.length !== 4 || !f.every(finite)) return null;
      const a = json.anchors && Array.isArray(json.anchors[name]) ? json.anchors[name] : [f[2] >> 1, f[3] - 1];
      const nominal = /-(\d+)$/.exec(name);
      return { name, x: f[0], y: f[1], w: f[2], h: f[3], ax: a[0], ay: a[1], nominal: nominal ? Number(nominal[1]) : f[3] };
    };
    const ladders = {};
    for (const [kind, names] of Object.entries(json.ladders || {})) {
      const list = (Array.isArray(names) ? names : []).map(entry).filter(Boolean).sort((a, b) => a.h - b.h || a.nominal - b.nominal);
      if (list.length) ladders[kind] = list;
    }
    return { ladders, frame: entry, count: Object.keys(json.frames).length };
  }
  /** The rung of a ladder nearest (in ratio) to a wanted size; null when the thing is too small to draw. `by` is 'h' (pixel height) or 'nominal' (the width a car or a bridge was drawn for). */
  function pickRung(list, wanted, by = 'h') {
    if (!list || !list.length || !(wanted > 0)) return null;
    if (wanted < list[0][by] * 0.7) return null;
    let best = list[0], error = Infinity;
    for (const e of list) { const d = Math.abs(Math.log(wanted / e[by])); if (d < error) { error = d; best = e; } }
    return best;
  }
  function tintAtlas(s, tint) {
    const key = tint.map((v) => Math.round(v * 16)).join(',');
    if (key === s.tintKey) return;
    s.tintKey = key;
    if (tint[0] >= 0.97 && tint[1] >= 0.97 && tint[2] >= 0.97) { s.sheet = s.atlas; return; }
    if (typeof document === 'undefined') { s.sheet = s.atlas; return; }
    if (!s.tintCanvas) { s.tintCanvas = document.createElement('canvas'); s.tintCanvas.width = s.atlas.naturalWidth || s.atlas.width; s.tintCanvas.height = s.atlas.naturalHeight || s.atlas.height; }
    const c = s.tintCanvas, x = c.getContext('2d');
    x.globalCompositeOperation = 'source-over'; x.clearRect(0, 0, c.width, c.height); x.drawImage(s.atlas, 0, 0);
    x.globalCompositeOperation = 'multiply'; x.fillStyle = css(tint.map((v) => Math.round(clamp(v, 0, 1) * 255))); x.fillRect(0, 0, c.width, c.height);
    x.globalCompositeOperation = 'destination-in'; x.drawImage(s.atlas, 0, 0);
    x.globalCompositeOperation = 'source-over';
    s.sheet = c;
  }

  /* ---- drawing the sprites: every roadside thing, rival and the car, far to near; a hill hides the foot of what is behind it */
  const CAR_PHASE_STEPS = 3, GULL_POSE = [0, 1, 2, 1];
  function blit(g, s, e, sx, sy, clip) {
    const dx = Math.round(sx - e.ax), dy = Math.round(sy - e.ay);
    if (dx >= W || dx + e.w <= 0 || dy >= H) return null;
    let h = e.h;
    if (dy + h > clip) h = clip - dy;
    if (h <= 0) return null;
    g.drawImage(s.sheet, e.x, e.y, e.w, h, dx, dy, e.w, h);
    return { x: dx, y: dy, w: e.w, h: e.h };
  }
  /** How tall an overpass must be for the car to drive under it in this layout: its deck has to clear the camera in the stretched ground view, or it would sink onto the car. */
  const bridgeHeight = (geo) => Math.max(KINDS.bridge, 1.4 * CAM_H * geo.fy / FX);
  /** An overpass: the atlas's sprite hung from the row where the structure's top really is (so its deck rises out of the picture over the car instead of coming down on it,
   *  whatever the layout and even when the biggest rung is smaller than the real thing), on pillars drawn as plain rectangles down to the road. */
  function drawOverpass(g, s, e, x, foot, zn, geo, tint) {
    const top = foot - bridgeHeight(geo) * FX / zn, box = blit(g, s, { x: e.x, y: e.y, w: e.w, h: e.h, ax: e.ax, ay: 0 }, x, top, H);
    if (!box) return;
    const from = Math.round(top + e.h), to = Math.round(foot), pillar = Math.max(2, Math.round(e.nominal * 0.075)), shade = Math.max(1, pillar / 3 | 0);
    if (to <= from) return;
    for (const left of [box.x, box.x + e.w - pillar]) {
      g.fillStyle = css(mulRgb([201, 194, 182], tint)); g.fillRect(left, from, pillar, to - from);
      g.fillStyle = css(mulRgb([143, 138, 128], tint)); g.fillRect(left + pillar - shade, from, shade, to - from);
    }
  }
  function drawSprites(g, s, world, proj, light) {
    const atlas = s.lib, total = world.track.length, list = s.list, geo = proj.geo;
    let n = 0;
    const push = (kind, z, a, b) => { const it = list[n] || (list[n] = {}); it.kind = kind; it.z = z; it.a = a; it.b = b; n++; };
    for (let k = DRAW - 1; k >= 0; k--) {
      const objects = world.scenery[proj.idx[k]];
      if (!objects || proj.zn[k] < 100) continue;
      for (const obj of objects) if (proj.zn[k] >= geo.zCut || obj.kind === 'bridge') push(0, proj.zn[k], obj, k);        // an overpass is still overhead when its foot is below the picture
    }
    for (const r of world.rivals) {
      const z = wrapZ(r.z - (world.camZ + ZP), total) + ZP;
      if (z >= geo.zCut && z < DRAW * SEG - 300) push(1, z, r, 0);
    }
    push(2, ZP, null, 0);
    list.length = n;
    list.sort((p, q) => q.z - p.z);
    const lamps = light.lamps > 0.2 ? s.glow : null;
    if (lamps) lamps.length = 0;
    for (const it of list) {
      if (it.kind === 0) {
        const obj = it.a, k = it.b, zn = proj.zn[k], e = obj.kind === 'bridge' ? pickRung(atlas.ladders.bridge, 2900 * FX / zn, 'nominal') : pickRung(atlas.ladders[obj.kind], KINDS[obj.kind] * FX / zn);
        if (e && obj.kind === 'bridge') drawOverpass(g, s, e, proj.xn[k], proj.y1[k], zn, geo, light.tint);
        else if (e) blit(g, s, e, proj.xn[k] + obj.off * FX / zn, proj.y1[k], proj.clip[k]);
        if (lamps && obj.kind === 'lamp' && e) lamps.push([Math.round(proj.xn[k] + obj.off * FX / zn - e.ax + e.w - 1 - Math.max(0, e.h / 14)), Math.round(proj.y1[k] - e.h + 1), Math.max(2, e.h >> 3), 0]);
      } else if (it.kind === 1) {
        const r = it.a, road = sampleRoad(proj, it.z);
        if (!road) continue;
        const e = pickRung(atlas.ladders['rival-' + RIVAL_NAMES[r.colour]], RIVAL_WIDTH * FX / it.z, 'nominal');
        if (!e) continue;
        const box = blit(g, s, e, road.x + r.x * FX / it.z, road.y, proj.clip[road.k]);
        if (box && lamps) rivalLights(g, box, e, proj.clip[road.k], light.lamps);
      } else {
        const p = world.player, hop = p.hop > 0 ? HOP[HOP.length - p.hop] : 0;
        const phase = ((world.steps / CAR_PHASE_STEPS) | 0) & 3, name = 'car-' + (p.lean + 2) + '-' + phase, e = atlas.frame(name);
        const carX = playerScreenX(world);
        if (e) {
          const box = blit(g, s, e, carX, geo.carRow + hop, H);
          if (box && light.lamps > 0.2) rearLights(g, box, e, phase, light.lamps);
          if (box && p.honk > 0 && ((p.honk >> 2) & 1) === 0) honkMarks(g, box);
        }
      }
    }
  }
  /** Small horizontal tail lamps, on the vehicle and behind any nearer sprites. */
  function rivalLights(g, box, sprite, clip, amount) {
    const y = box.y + Math.max(0, Math.round(sprite.ay - sprite.w * 0.25));
    const height = Math.min(Math.max(1, Math.round(sprite.h * 0.045)), clip - y);
    if (height <= 0) return;
    const width = Math.max(1, Math.round(sprite.w * 0.12)), inset = Math.max(0, Math.round(sprite.w * 0.10));
    g.save(); g.globalCompositeOperation = 'lighter';
    g.fillStyle = 'rgba(255,60,40,' + (0.8 * clamp(amount, 0, 1)) + ')';
    g.fillRect(box.x + inset, y, width, height);
    g.fillRect(box.x + box.w - inset - width, y, width, height);
    g.restore();
  }
  function rearLights(g, box, sprite, phase, amount) {
    const centre = box.x + sprite.ax, y = box.y + sprite.ay - 7 - (phase === 1 || phase === 2 ? 1 : 0);
    g.save();
    g.globalCompositeOperation = 'lighter';
    g.fillStyle = 'rgba(255,50,35,' + (0.55 * clamp(amount, 0, 1)) + ')';
    for (const dx of [-16, -11, 11, 16]) g.fillRect(centre + dx - 1, y, 2, 2);
    g.restore();
  }
  function honkMarks(g, box) {                                                            // sound waves on each side of the car (the horn), in whole pixels
    g.fillStyle = '#fff3a8';
    const y = box.y + 4;
    for (const side of [-1, 1]) {
      const x = side < 0 ? box.x - 2 : box.x + box.w + 1;
      for (let k = 0; k < 3; k++) { const len = 3 + k * 2; g.fillRect(x + side * k * 3, y + 3 - (len >> 1), 1, len); }
    }
  }
  /** The sky's moving things: clouds (tinted with the sheet; smaller and fewer when the sky is short) and gulls, in whole pixels. */
  function drawAir(g, s, world, hz) {
    const atlas = s.lib, clouds = atlas.ladders.cloud;
    if (clouds) {
      const limit = hz * 0.34, shown = hz < 80 ? 3 : world.clouds.length;
      for (let i = 0; i < shown; i++) {
        const c = world.clouds[i];
        let at = c.kind % clouds.length;
        while (at > 0 && clouds[at].h > limit) at--;
        const e = clouds[at];
        blit(g, s, e, c.x - e.w / 2, 12 + Math.round(c.f * Math.max(4, hz - 22 - e.h)), H);
      }
    }
    for (const gull of world.gulls) {
      const list = atlas.ladders[gull.small ? 'gull-s' : 'gull-m'];
      if (!list) continue;
      const e = list[GULL_POSE[gull.phase & 3] % list.length], bob = Math.round(Math.sin(world.time * 2.4 + gull.bob) * 1.4);
      blit(g, s, e, gull.x, Math.min(gull.y + bob, hz - 8), H);
    }
  }
  const RIVAL_NAMES = ['blue', 'yellow', 'white', 'teal', 'orange', 'violet', 'green', 'black'];

  /** After dark the rival tail lights and lamp posts glow. The car's lights are drawn with the road and the car. */
  function drawLights(g, s, light) {
    const amount = clamp(light.lamps, 0, 1);
    if (amount < 0.2) return;
    g.save(); g.globalCompositeOperation = 'lighter';
    for (const [x, y, size, red] of s.glow) { g.fillStyle = red ? 'rgba(255,60,40,' + (0.55 * amount) + ')' : 'rgba(255,226,140,' + (0.7 * amount) + ')'; g.fillRect(x - 1, y - 1, size + 2, size + 2); }
    g.restore();
  }

  /* ---- the plain stand-in when the atlas is missing: the road, sea, sky and mountains still draw; the car is a simple red box */
  function drawPlainCar(g, world, geo) {
    const x = playerScreenX(world) - 22, y = geo.carRow - 24;
    g.fillStyle = '#252e40'; g.fillRect(x - 1, y + 20, 46, 4);
    g.fillStyle = '#701d36'; g.fillRect(x, y + 6, 44, 18); g.fillStyle = '#ef343d'; g.fillRect(x + 2, y + 8, 40, 10); g.fillStyle = '#261f32'; g.fillRect(x + 3, y + 18, 38, 5);
    g.fillStyle = '#85c9d4'; g.fillRect(x + 10, y, 24, 7);
  }

  /* ---- the scene */
  const now = () => (typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now());
  const viewBottom = (api) => (api && api.view && finite(api.view.bottom) ? api.view.bottom : H);
  const scene = {
    size: [W, H],
    init(api) {
      const route = api.json && api.json.route && api.json.route.turns;
      const world = createWorld({ random: typeof api.random === 'function' ? api.random : null, route });
      const lib = api.json && api.atlas ? readAtlas(api.json) : null;
      const anchor = anchorsFor(viewBottom(api));
      const s = { world, lib, atlas: api.atlas || null, sheet: api.atlas || null, list: [], glow: [], proj: makeProjection(), palKey: '', pal: null, tintKey: '',
        anchor, geo: geometry(anchor.horizon, anchor.carRow), stepAt: 0 };
      s.img = typeof ImageData === 'function' ? new ImageData(W, H) : null;
      s.buf = s.img ? new Uint32Array(s.img.data.buffer) : null;
      s.skyMap = makeSkyMap();
      const ridgeRand = seeded(0x7a11);
      s.ridgeFar = makeRidge(ridgeRand, 360, 8, 26, 5); s.ridgeNear = makeRidge(ridgeRand, 280, 3, 15, 6); s.ridgeHill = makeRidge(ridgeRand, 200, 0, 9, 4);
      this.s = s;
    },
    step(api, dt) {
      const s = this.s;
      if (!s) return;
      s.world.step(dt);
      s.stepAt = now();
      s.anchor = easeAnchors(s.anchor, anchorsFor(viewBottom(api)));                       // a tap on the clock changes the visible rows: slide to the new layout over a few steps
    },
    draw(api, g) {
      const s = this.s;
      if (!s || !s.buf) return;
      const target = anchorsFor(viewBottom(api));
      if (now() - s.stepAt > 250 && (s.anchor.horizon !== target.horizon || s.anchor.carRow !== target.carRow)) s.anchor = target;      // nothing is running (the first picture, a still): no sliding
      const geo = s.geo = geometry(s.anchor.horizon, s.anchor.carRow);
      const world = s.world, light = world.light, key = light.tint.map((v) => Math.round(v * 40)).join(',') + '|' + Math.round(light.alt * 3);
      if (key !== s.palKey) { s.palKey = key; s.pal = buildPalette(light); if (s.lib) tintAtlas(s, light.tint); }
      projectRoad(world.track, world.camZ, world.camX, world.camY, s.proj, geo);
      const view = { skyMap: s.skyMap, ridgeFar: s.ridgeFar, ridgeNear: s.ridgeNear, ridgeHill: s.ridgeHill };
      paintSky(s.buf, view, s.pal, world, light, geo.horizon);
      paintGround(s.buf, s.proj, s.pal, world, light);
      g.putImageData(s.img, 0, 0);
      if (s.lib) { drawAir(g, s, world, geo.horizon); drawSprites(g, s, world, s.proj, light); drawLights(g, s, light); } else drawPlainCar(g, world, geo);
    },
    poke(api, x, y) { if (this.s) this.s.world.poke(x, y, this.s.geo.horizon); },
  };

  const logic = {
    W, H, HORIZON, CX, SEG, ROAD, LANE, CAM_H, FX, FY, ZP, CAR_ROW, DRAW, TRACK, BAND, HILL_GAIN, STEP, CRUISE, LANE_SPEED, KINDS, HOP, KEYS, LEVELS, ANCHOR, DEFAULT_GEO, SKY_ROWS,
    anchorsFor, geometry, easeAnchors,
    seeded, rgb, pack, mixRgb, sunState, lightAt, phaseName, sunPlace, moonPlace, beachAt, validRoute, buildTrack, buildScenery, makeProjection, projectRoad, sampleRoad, wrapZ, laneX, heightAt,
    createWorld, buildPalette, makeSkyMap, makeRidge, readAtlas, pickRung, playerScreenX, headlightRow,
  };
  if (global.TabletGames && typeof global.TabletGames.define === 'function') global.TabletGames.define('token-run', scene);
  if (typeof module !== 'undefined' && module.exports) module.exports = Object.assign({ scene }, logic);
}(typeof window !== 'undefined' ? window : globalThis));
