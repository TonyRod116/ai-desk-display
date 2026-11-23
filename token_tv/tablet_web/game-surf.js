/* TIDAL RUSH for the tablet: a huge curling wave at the golden hour, a surfer carving it, drawn in real time (200 x 320 art pixels, 30 Hz).
 *
 * The sunset is FIXED (Tony, 2026-11-10: always that golden/violet dusk; the page's own night mode dims the whole screen). Decorative and calm, never activity or trading: a tall wave
 * curls over a round tube mouth that frames the sun and the sky; a surfer, who faces mostly toward the camera and slightly left, drops in, bottom-turns, pumps, snaps off the lip, hangs ten, jumps
 * straight up with a grab, crouches in the tube while the lip throws a curtain of water, is swallowed by the foam and spat out, and now and then loses his balance, falls, swims,
 * paddles and pops up; every 60 s a swell builds in the tube's window and everything closes out in foam. A palm grows on a sand island at the left, sailboats, a llaut, a windsurfer and a far
 * ferry cross the sea, a dolphin leaps, gulls fly over the left sky and disappear behind the wave. A touch makes the surfer hop and grab his board, or splashes the water, or sends
 * a gull up. NO quota, number or text is drawn here (Tony's rule: only the isometric city, the Game Boy and Neon City's bridge show quota in the picture).
 *
 * How it is drawn: a BACKDROP picture (the sky, the sun, the sea, the wave: 200 x 320 pixels in a small palette, plus a class for every pixel: still, sky, sea, water) comes
 * from the private atlas (scripts/prepare_game_surf.py makes it from Tony's own Gemini plates, never in Git) or, without it, from a calmer built-in one drawn by `makeBackdrop`.
 * The backdrop is copied into one typed array. The distant sea ripples and the water accelerates up the wave face and around the barrel.
 * The crest then falls into a spreading whitewash. The living things are drawn by tiny software rasterisers (stars, gulls, craft, the surfer with a dark outline, spray, foam, the lip's
 * curtain, mist) and one `putImageData` puts the picture on the canvas. Everything is whole pixels.
 *
 * The file is also a Node module: the geometry, the warp, the surfer's kinematics, the ride, the world and the drawing path are pure and have tests
 * (tests/test_tablet_game_surf.mjs).
 */
(function (global) {
  'use strict';

  /* ---- constants */
  const W = 200, H = 320;                         // the picture, in art pixels (x3 on this tablet's CSS pixels, x4 on its panel)
  const STEP = 1 / 30, WAKE_LIFE = 72, WAKE_MAX = 72;
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (t) => { t = t < 0 ? 0 : t > 1 ? 1 : t; return t * t * (3 - 2 * t); };
  const RAD = Math.PI / 180;
  // what the page puts over the scene at the left while the dock is up (docs/tablet-games.md): nothing that acts may enter it
  const CLEAR = { x: 110, y0: 116, y1: 186 };

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
  function rgb(hex) { const v = parseInt(hex.slice(1), 16); return [(v >> 16) & 255, (v >> 8) & 255, v & 255]; }
  const pack = (c) => (0xff000000 | (c[2] << 16) | (c[1] << 8) | c[0]) >>> 0;
  const unpack = (p) => [p & 255, (p >> 8) & 255, (p >> 16) & 255];
  const mixRgb = (a, b, t) => [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t)];
  const hexPack = (hex) => pack(rgb(hex));
  /** Blend packed pixel `c` over packed pixel `d`; a is 0..256. */
  function mixPx(d, c, a) {
    const ia = 256 - a;
    return (0xff000000 | (((((d >> 16) & 255) * ia + ((c >> 16) & 255) * a) >> 8) << 16) | (((((d >> 8) & 255) * ia + ((c >> 8) & 255) * a) >> 8) << 8) | ((((d & 255) * ia + (c & 255) * a) >> 8))) >>> 0;
  }
  /** Multiply a packed pixel by k (0..1+), per channel, clamped. */
  function shadePx(d, k) {
    const r = Math.min(255, ((d & 255) * k) | 0), g = Math.min(255, (((d >> 8) & 255) * k) | 0), b = Math.min(255, (((d >> 16) & 255) * k) | 0);
    return (0xff000000 | (b << 16) | (g << 8) | r) >>> 0;
  }

  /* ---- smooth value noise on a 64 x 64 lattice from the seeded random; `noise.fbm` adds octaves */
  function makeNoise(rand) {
    const grid = new Float32Array(4096);
    for (let i = 0; i < grid.length; i++) grid[i] = rand();
    const at = (xi, yi) => grid[((yi & 63) << 6) + (xi & 63)];
    function noise(x, y) {
      const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
      return lerp(lerp(at(xi, yi), at(xi + 1, yi), u), lerp(at(xi, yi + 1), at(xi + 1, yi + 1), u), v);
    }
    noise.fbm = (x, y, octaves = 3) => { let s = 0, a = 0.5, f = 1, n = 0; for (let i = 0; i < octaves; i++) { s += a * noise(x * f, y * f); n += a; a *= 0.5; f *= 2.03; } return s / n; };
    return noise;
  }

  /* ---- splines and polygons (used once, in init) */
  function spline(pts, per = 16) {
    const out = [], n = pts.length, P = (i) => pts[Math.max(0, Math.min(n - 1, i))];
    for (let i = 0; i < n - 1; i++) {
      const p0 = P(i - 1), p1 = P(i), p2 = P(i + 1), p3 = P(i + 2);
      for (let k = 0; k < per; k++) {
        const t = k / per, t2 = t * t, t3 = t2 * t, c = (a) => 0.5 * ((2 * p1[a]) + (-p0[a] + p2[a]) * t + (2 * p0[a] - 5 * p1[a] + 4 * p2[a] - p3[a]) * t2 + (-p0[a] + 3 * p1[a] - 3 * p2[a] + p3[a]) * t3);
        out.push([c(0), c(1)]);
      }
    }
    out.push([pts[n - 1][0], pts[n - 1][1]]);
    return out;
  }
  /** A polyline measured by length: `at(s)` gives the point at distance s along it, `tangent(s)` the unit direction, `length` the total. */
  function makePath(points) {
    const n = points.length, len = new Float32Array(n);
    for (let i = 1; i < n; i++) len[i] = len[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    const total = len[n - 1] || 1;
    const seg = (s) => { s = clamp(s, 0, total); let lo = 0, hi = n - 1; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (len[m] <= s) lo = m; else hi = m; } return lo; };
    return {
      length: total, points,
      at(s) { const i = seg(s), span = len[i + 1] - len[i] || 1, t = clamp((s - len[i]) / span, 0, 1); return [lerp(points[i][0], points[i + 1][0], t), lerp(points[i][1], points[i + 1][1], t)]; },
      tangent(s) { const i = seg(s), dx = points[i + 1][0] - points[i][0], dy = points[i + 1][1] - points[i][1], m = Math.hypot(dx, dy) || 1; return [dx / m, dy / m]; },
    };
  }

  /* ---- software drawing: tiny rasterisers into a frame buffer (a Uint32Array W x H, ABGR); all in whole pixels. `lim` is the last row the frame needs (the dock hides the rest). */
  let LIM = H;
  const put = (fb, x, y, c) => { if (x >= 0 && x < W && y >= 0 && y < LIM) fb[y * W + x] = c; };
  const putA = (fb, x, y, c, a) => { if (a > 0 && x >= 0 && x < W && y >= 0 && y < LIM) { const i = y * W + x; fb[i] = a >= 256 ? c : mixPx(fb[i], c, a); } };
  function fillSpan(buf, y, x0, x1, colour) {
    if (x0 < 0) x0 = 0; if (x1 > W) x1 = W;
    if (x1 > x0 && y >= 0 && y < LIM) buf.fill(colour, y * W + x0, y * W + x1);
  }
  function fillDisc(buf, cx, cy, r, colour) {
    for (let y = Math.max(0, cy - r); y <= Math.min(LIM - 1, cy + r); y++) {
      const dy = y - cy, half = Math.floor(Math.sqrt(Math.max(0, r * r - dy * dy) + 0.25));
      fillSpan(buf, y, cx - half, cx + half + 1, colour);
    }
  }
  /** A line of whole pixels; `w` 2 stamps 2 x 2 squares, 3 a plus-shaped brush. */
  function line(fb, x0, y0, x1, y1, c, w = 1) {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy, x = x0, y = y0;
    for (let guard = 0; guard < 500; guard++) {
      put(fb, x, y, c);
      if (w > 1) { put(fb, x + 1, y, c); put(fb, x, y + 1, c); put(fb, x + 1, y + 1, c); }
      if (w > 2) { put(fb, x - 1, y, c); put(fb, x, y - 1, c); }
      if (x === x1 && y === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x += sx; }
      if (e2 <= dx) { err += dx; y += sy; }
    }
  }
  /** Fill a polygon (even-odd) calling fn(x, y) for every pixel centre inside it that lies on the picture. */
  function fillPolygon(poly, fn, bw = W, bh = H) {
    let lo = Infinity, hi = -Infinity;
    for (const p of poly) { if (p[1] < lo) lo = p[1]; if (p[1] > hi) hi = p[1]; }
    const n = poly.length, xs = [];
    for (let y = Math.max(0, Math.ceil(lo - 0.5)); y <= Math.min(bh - 1, Math.floor(hi - 0.5)); y++) {
      const yc = y + 0.5;
      xs.length = 0;
      for (let i = 0, j = n - 1; i < n; j = i++) {
        const a = poly[j], b = poly[i];
        if ((a[1] <= yc && b[1] > yc) || (b[1] <= yc && a[1] > yc)) xs.push(a[0] + (yc - a[1]) / (b[1] - a[1]) * (b[0] - a[0]));
      }
      xs.sort((p, q) => p - q);
      for (let k = 0; k + 1 < xs.length; k += 2) {
        const x0 = Math.max(0, Math.ceil(xs[k] - 0.5)), x1 = Math.min(bw - 1, Math.ceil(xs[k + 1] - 0.5) - 1);
        for (let x = x0; x <= x1; x++) fn(x, y);
      }
    }
  }
  /** A tiny raster of palette indices (a sprite is drawn into one, outlined and blitted): put, line (1-3 px brush), disc, polygon. */
  function makeRaster(w, h) {
    const buf = new Uint8Array(w * h);
    const r = { w, h, buf, minX: w, maxX: -1, minY: h, maxY: -1 };                                      // the box of what was drawn: blitting never scans the empty rest
    const put = (x, y, c) => { if (x >= 0 && x < w && y >= 0 && y < h) { buf[y * w + x] = c; if (x < r.minX) r.minX = x; if (x > r.maxX) r.maxX = x; if (y < r.minY) r.minY = y; if (y > r.maxY) r.maxY = y; } };
    r.put = put; r.clear = () => { buf.fill(0); r.minX = w; r.maxX = -1; r.minY = h; r.maxY = -1; };
    r.line = (x0, y0, x1, y1, c, wd = 1) => {
      x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
      const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
      let err = dx + dy, x = x0, y = y0;
      for (let guard = 0; guard < 300; guard++) {
        put(x, y, c);
        if (wd > 1) { put(x + 1, y, c); put(x, y + 1, c); put(x + 1, y + 1, c); }
        if (wd > 2) { put(x - 1, y, c); put(x, y - 1, c); }
        if (x === x1 && y === y1) break;
        const e2 = 2 * err;
        if (e2 >= dy) { err += dy; x += sx; }
        if (e2 <= dx) { err += dx; y += sy; }
      }
    };
    r.disc = (cx, cy, rad, c) => { for (let y = cy - rad; y <= cy + rad; y++) { const dy = y - cy, half = Math.floor(Math.sqrt(Math.max(0, rad * rad - dy * dy) + 0.25)); for (let x = cx - half; x <= cx + half; x++) put(x, y, c); } };
    r.poly = (pts, c) => fillPolygon(pts, (x, y) => { buf[y * w + x] = c; if (x < r.minX) r.minX = x; if (x > r.maxX) r.maxX = x; if (y < r.minY) r.minY = y; if (y > r.maxY) r.maxY = y; }, w, h);
    return r;
  }
  const BYTE = (v) => (v < 0 ? 0 : v > 255 ? 255 : v | 0);

  /* ---- the backdrop: what the picture looks like before anything moves.
   *
   * A backdrop is { rgb: Uint32Array(W*H) the picture, cls: Uint8Array(W*H) the class of every pixel, geom: the geometry the living things need }.
   * Classes: STILL (kept as it is), SKY (clouds, stars and gulls may be drawn here), SEA (its rows slither), WATER (the wave: its rings flow).
   * Geometry: horizon (row), sun {x, y, r}, centre [x, y] (the tube's), hole [cx, cy, rx, ry] (the open mouth), line [[x, y]...] (the wave's surface the surfer rides, from low to
   * high, the air on its upper left), lip [[x, y]...] (the lip's crest), tip [x, y] (where it ends), foot [[x, y]...] (the foam at the wave's foot), path [x0, x1] (the sun's
   * glitter at the horizon), rocks and beach are decoration.
   * The built-in one below is calm and decent; the private atlas replaces it with the real art. */
  const CLS = { STILL: 0, SKY: 1, SEA: 2, WATER: 3, FORE: 4 };                       // FORE (the island at the left) is set by code only; WATER and FORE hide whatever is far away
  const DEFAULT_GEOM = {
    horizon: 122, sun: { x: 46, y: 114, r: 21 }, centre: [124, 100], hole: [124, 100, 33, 34], tip: [92, 121], path: [20, 80],
    lip: [[150, 62], [138, 54], [124, 52], [110, 57], [100, 67], [94, 80], [91, 94], [91, 108], [92, 120]],
    line: [[126, 138], [138, 129], [147, 118], [153, 106], [156, 94], [154, 82], [148, 72], [140, 64], [130, 59]],
    foot: [[20, 205], [60, 192], [100, 172], [140, 152], [180, 144], [200, 140]],
  };
  const SKY_BANDS = ['#3b2a8f', '#5a34a8', '#7a3cb4', '#9a40b4', '#c04aa8', '#e8508e', '#ff5e80', '#ff7662', '#ff9a54', '#ffb84e', '#ffd25a', '#ffe27a'];
  const SKY_EDGES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.78, 0.86, 0.92, 0.97];
  const RING = ['#082a64', '#0a4088', '#0a5aa0', '#0b78b0', '#0f9cbc', '#12b8c2', '#48d2c4', '#86e6cc', '#c4f4de'];

  function makeBackdrop(rand) {
    const noise = makeNoise(rand), g = JSON.parse(JSON.stringify(DEFAULT_GEOM)), hz = g.horizon, [cx, cy] = g.centre, R0 = g.hole[2];
    const rgbBuf = new Uint32Array(W * H), cls = new Uint8Array(W * H);
    const bands = SKY_BANDS.map(hexPack), ring = RING.map(hexPack);
    const ramp = spline([[-8, 214], [24, 206], [56, 194], [88, 174], [112, 154], [136, 134], [156, 114]], 12);
    const rampY = (x) => { let best = ramp[0]; for (const p of ramp) if (Math.abs(p[0] - x) < Math.abs(best[0] - x)) best = p; return x < ramp[0][0] ? ramp[0][1] : best[1]; };
    const rampTable = new Float32Array(W); for (let x = 0; x < W; x++) rampTable[x] = x > 156 ? 114 - (x - 156) * 0.9 : rampY(x);
    const thick = (a) => { const T = [[20, 96], [45, 36], [75, 20], [110, 13], [150, 8], [185, 4], [205, 1.5]]; if (a <= T[0][0]) return T[0][1]; for (let i = 1; i < T.length; i++) if (a <= T[i][0]) return lerp(T[i - 1][1], T[i][1], (a - T[i - 1][0]) / (T[i][0] - T[i - 1][0])); return 0; };
    const sun = g.sun;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = y * W + x, dx = x - cx, dy = cy - y, r = Math.hypot(dx, dy);
        let a = Math.atan2(dy, dx) / RAD; if (a < -100) a += 360;
        let water = false, s = 0, T = 0;
        if (y > rampTable[x]) { water = true; s = y - rampTable[x]; }
        else if (r >= R0) {
          if (a >= 20 && a <= 205) { T = thick(a); water = r - R0 <= T; s = r - R0; }
          else if (a < 20 && a >= -100) { water = true; s = r - R0; }
        }
        if (water) {
          cls[i] = CLS.WATER;
          let t;
          if (y > rampTable[x] && !(r < R0 + 1 && a < 20)) {                                // the foreground water below the ramp: gold-lit at the top, deep below, foam streaks
            const dd = y - rampTable[x], streak = noise.fbm(x * 0.045 + dd * 0.02, y * 0.2 - x * 0.02, 3);
            t = 6.2 - 4.6 * smooth(dd / 130) + (streak - 0.5) * 3.4 + 0.7 * Math.sin(dd * 0.33 + x * 0.02);
            const foam = noise.fbm(x * 0.03 - y * 0.012, y * 0.16 + x * 0.05, 3);
            if (foam > 0.64 && dd > 12) { rgbBuf[i] = foam > 0.7 ? hexPack('#f0fcff') : hexPack('#9fe6d8'); continue; }
            if (dd < 3) { rgbBuf[i] = hexPack('#ffd98a'); continue; }
            if (dd < 6) { rgbBuf[i] = hexPack('#7ae0c8'); continue; }
          } else if (a >= 20 && a <= 205 && T < 80) {                                       // the lip: gold inside, aqua, a white foamy rim outside
            const u = s / Math.max(1, T);
            if (u > 0.82 && noise.fbm(x * 0.35, y * 0.35, 2) > 0.34) { rgbBuf[i] = hexPack(u > 0.93 ? '#ffffff' : '#ffe2b4'); continue; }
            if (u < 0.1) { rgbBuf[i] = hexPack('#ffd98a'); continue; }
            t = 7.4 - 3.2 * u + 0.9 * Math.sin(u * 9 + a * 0.12) + (noise(x * 0.2, y * 0.2) - 0.5) * 1.2;
          } else {                                                                          // the body right of the tube: concentric rings that wind a little
            t = 7.6 - 7.2 * smooth(s / 120) + 0.95 * Math.sin(s * 0.5 + a * 0.012 * s * 0.05) + (noise.fbm(x * 0.05, y * 0.05, 2) - 0.5) * 0.9;
            if (s < 2.5) { rgbBuf[i] = hexPack('#ffd98a'); continue; }
          }
          rgbBuf[i] = ring[clamp(Math.round(t), 0, ring.length - 1)];
          continue;
        }
        if (y < hz) {                                                                        // the sky: bands that arch up toward the sun, then the sun and its halo
          cls[i] = CLS.SKY;
          const glow = Math.exp(-Math.pow((x - sun.x) / 80, 2)) * 10, f = (y + glow * (y / hz)) / hz;
          let b = 0; while (b < SKY_EDGES.length && f >= SKY_EDGES[b] + 0.012 * Math.sin(x * 0.07 + b * 2)) b++;
          let c = bands[b];
          const d = Math.hypot(x - sun.x, (y - sun.y) * 1.0);
          if (d < sun.r) c = hexPack(d < sun.r * 0.55 ? '#ffa81e' : '#ff9a14');
          else if (d < sun.r + 6) c = hexPack('#ff7c3c');
          else if (d < sun.r + 15) c = hexPack('#ff8a4a');
          rgbBuf[i] = c;
        } else {                                                                             // the sea: a purple gradient with the sun's gold path
          cls[i] = CLS.SEA;
          const dd = y - hz, wide = 6 + dd * 0.45, off = Math.abs(x - sun.x), inside = off < wide;
          let t = 0.55 - 0.3 * smooth(dd / 80) + (noise.fbm(x * 0.05, y * 0.35, 2) - 0.5) * 0.22;
          let c = mixRgb(rgb('#5a3790'), rgb('#2a1a5c'), clamp(1 - t, 0, 1));
          if (inside) {
            const dash = noise.fbm(x * 0.09, y * 0.9 + 3, 2);
            if (dash > 0.52 - 0.12 * (1 - off / wide)) c = dash > 0.66 ? rgb('#fff0b0') : dash > 0.58 ? rgb('#ffd25a') : rgb('#ff9a3a');
          } else if (noise.fbm(x * 0.07, y * 0.8 + 9, 2) > 0.68) c = mixRgb(c, rgb('#b06aa6'), 0.5);
          rgbBuf[i] = pack(c);
        }
      }
    }
    // the horizon: a thin dark line under the sky, so the sea sits on it
    for (let x = 0; x < W; x++) { const i = hz * W + x; if (cls[i] === CLS.SEA) rgbBuf[i] = hexPack('#2a1658'); }
    return { rgb: rgbBuf, cls, geom: g, builtin: true };
  }

  /* ---- reading a backdrop from the private atlas: frame `plate` (the colours, W x H) and frame `maps` (W x H: red = the class of every pixel); geometry in json.geometry */
  const okFrame = (f) => Array.isArray(f) && f.length === 4 && f.every(finite) && f[0] >= 0 && f[1] >= 0 && f[2] > 0 && f[3] > 0;
  const okPoint = (p) => Array.isArray(p) && p.length === 2 && finite(p[0]) && finite(p[1]) && p[0] > -60 && p[0] < W + 60 && p[1] > -60 && p[1] < H + 60;
  const okPoints = (list, min = 2) => Array.isArray(list) && list.length >= min && list.length <= 400 && list.every(okPoint);
  /** The geometry of a backdrop: the built-in defaults with every valid key of `given` laid over them (an invalid key is ignored). */
  function mergeGeometry(given) {
    const g = JSON.parse(JSON.stringify(DEFAULT_GEOM));
    if (!given || typeof given !== 'object') return g;
    if (finite(given.horizon) && given.horizon > 30 && given.horizon < H - 40) g.horizon = Math.round(given.horizon);
    if (given.sun && finite(given.sun.x) && finite(given.sun.y) && finite(given.sun.r) && given.sun.r > 2 && given.sun.r < 60) g.sun = { x: given.sun.x, y: given.sun.y, r: given.sun.r };
    if (okPoint(given.centre)) g.centre = [given.centre[0], given.centre[1]];
    if (Array.isArray(given.hole) && given.hole.length === 4 && given.hole.every(finite) && given.hole[2] > 4 && given.hole[3] > 4) g.hole = given.hole.slice();
    if (okPoint(given.tip)) g.tip = [given.tip[0], given.tip[1]];
    if (Array.isArray(given.path) && given.path.length === 2 && given.path.every(finite)) g.path = given.path.slice();
    for (const key of ['lip', 'line', 'foot', 'current']) if (okPoints(given[key], key === 'line' || key === 'current' ? 4 : 2)) g[key] = given[key].map((p) => [p[0], p[1]]);
    if (given.palm && finite(given.palm.x) && finite(given.palm.y) && Math.abs(given.palm.x) < 100 && Math.abs(given.palm.y) < 200) g.palm = { x: Math.round(given.palm.x), y: Math.round(given.palm.y) };
    return g;
  }
  /** The backdrop of an atlas (json + the atlas's pixels as ImageData-like {width, data}), or null when anything is wrong. */
  function readPlate(json, pixels) {
    try {
      if (!json || !json.frames || !pixels || !pixels.data || !(pixels.width > 0)) return null;
      const fp = json.frames.plate, fm = json.frames.maps;
      if (!okFrame(fp) || !okFrame(fm) || fp[2] !== W || fp[3] !== H || fm[2] !== W || fm[3] !== H) return null;
      if (fp[0] + W > pixels.width || fm[0] + W > pixels.width || (fp[1] + H) * pixels.width * 4 > pixels.data.length || (fm[1] + H) * pixels.width * 4 > pixels.data.length) return null;
      const d = pixels.data, stride = pixels.width * 4, rgbBuf = new Uint32Array(W * H), cls = new Uint8Array(W * H);
      const behind = json.frames.background;
      const hasBackground = okFrame(behind) && behind[2] === W && behind[3] === H &&
        behind[0] + W <= pixels.width && (behind[1] + H) * stride <= d.length;
      const background = hasBackground ? new Uint32Array(W * H) : null;
      for (let y = 0; y < H; y++) {
        let p = (fp[1] + y) * stride + fp[0] * 4, m = (fm[1] + y) * stride + fm[0] * 4;
        for (let x = 0; x < W; x++, p += 4, m += 4) { rgbBuf[y * W + x] = (0xff000000 | (d[p + 2] << 16) | (d[p + 1] << 8) | d[p]) >>> 0; cls[y * W + x] = Math.min(3, d[m]); }
        if (background) {
          let at = (behind[1] + y) * stride + behind[0] * 4;
          for (let x = 0; x < W; x++, at += 4) background[y * W + x] = (0xff000000 | (d[at + 2] << 16) | (d[at + 1] << 8) | d[at]) >>> 0;
        }
      }
      return { rgb: rgbBuf, cls, geom: mergeGeometry(json.geometry), builtin: false, background };
    } catch (e) { return null; }
  }

  // The foreground and the surfer's line have a fixed right-hand anchor.
  // A moving shoulder rises above that line while a separate pulse pushes
  // the lip forward. The backing picture is revealed by the changing mask.
  const WAVE_ANCHOR = 171;
  function makeWaveMotion(plate) {
    if (!plate.background) return null;
    const { geom, cls } = plate;
    const bottom = clamp(Math.round(geom.tip[1] + 58), 1, H);
    const leftEdge = new Uint16Array(bottom);
    for (let y = 0; y < bottom; y++) {
      let left = W;
      for (let row = Math.max(0, y - 20); row <= Math.min(H - 1, y + 20); row++) {
        const start = row * W;
        for (let x = 0; x < left; x++) if (cls[start + x] === CLS.WATER) { left = x; break; }
      }
      leftEdge[y] = Math.max(0, left - 28);
    }
    const shoulderEnd = Math.min(130, geom.tip[1] - 18);
    const shoulder = Float32Array.from({length: H}, (_, y) => smooth((shoulderEnd - y) / 56));
    return {
      bottom, leftEdge, shoulder, rgb: new Uint32Array(W * H),
      stretch: new Float32Array(H).fill(1), inverse: new Float32Array(H).fill(1), rise: new Float32Array(W),
      visibleGain: new Uint8Array(W * H),
      wash: 0,
    };
  }
  function breakPulse(step, period) {
    const age = ((step % period) + period) % period;
    return smooth(age / 28) * smooth((82 - age) / 47);
  }
  function poseWave(wave, geom, world) {
    const step = world.steps, advance = .57 * Math.sin(step * .047) + .43 * Math.sin(step * .026 + 1.2);
    for (let y = 0; y < wave.bottom; y++) {
      const arrive = step - y * .29;
      const peel = .73 * breakPulse(arrive, 157) + .37 * breakPulse(arrive + 48, 211);
      const envelope = smooth(y / 47) * smooth((wave.bottom - y) / 62);
      wave.stretch[y] = 1 + envelope * (.061 * advance + .163 * peel + .035 * Math.sin(step * .054 - y * .064));
      wave.inverse[y] = 1 / wave.stretch[y];
    }
    for (let x = 0; x < W; x++) {
      const gather = .68 * breakPulse(step - (W - x) * .29, 157) + .29 * breakPulse(step + x * .32 + 41, 211);
      wave.rise[x] = smooth((x - geom.tip[0]) / 64) *
        (-6.4 * advance - 8.7 * gather + 2.1 * Math.sin(step * .072 + x * .047));
    }
    wave.wash = clamp(.65 * breakPulse(step - 62, 157) + .45 * breakPulse(step - 13, 211), 0, 1);
  }
  function wavePoint(wave, x, y) {
    const row = clamp(Math.round(y), 0, H - 1);
    const at = x < WAVE_ANCHOR ? WAVE_ANCHOR + (x - WAVE_ANCHOR) * wave.stretch[row] : x;
    const lift = wave.rise[clamp(Math.round(at), 0, W - 1)] * wave.shoulder[row];
    return [at, y + lift];
  }
  function drawMovingWave(s, plate) {
    const { fb, back, wave, world, currents } = s;
    const rest = plate.cls, live = back.cls, h = Math.min(LIM, wave.bottom);
    poseWave(wave, plate.geom, world);
    live.set(rest);
    const gain = wave.visibleGain;
    gain.set(currents.gain);
    wave.rgb.set(fb.subarray(0, Math.min(H, h + 20) * W));
    for (let y = 0; y < h; y++) {
      const row = y * W, shoulder = wave.shoulder[y];
      for (let x = wave.leftEdge[y]; x < W; x++) {
        const at = row + x;
        const sy = shoulder > 0 ? Math.max(0, (y - wave.rise[x] * shoulder + .5) | 0) : y;
        const sx = x < WAVE_ANCHOR
          ? (WAVE_ANCHOR + (x - WAVE_ANCHOR) * wave.inverse[sy] + .5) | 0 : x;
        const sample = sy * W + sx;
        if (sx >= 0 && rest[sample] === CLS.WATER) {
          fb[at] = wave.rgb[sample];
          live[at] = CLS.WATER;
          gain[at] = currents.gain[sample];
        } else if (rest[at] === CLS.WATER) {
          fb[at] = plate.background[at];
          live[at] = y < plate.geom.horizon ? CLS.SKY : CLS.SEA;
          gain[at] = 0;
        }
      }
    }
  }

  /* ---- the warp: the sea's rows slither, the wave's rings pulse and flow, the glow pulses through the lip. For each animated pixel a table keeps where it is, how far it may move in x
   *      and y (units of 1/128 of the swing) and its phase; a frame looks each one up in a sine table and takes the colour of the pixel that far away IF that pixel is of the same class
   *      (so the sea never borrows the wave's colours). On top of that the wave's two colour families are RAMPS: the teal rings (dark navy to pale aqua) and the sunlit peach and
   *      cream of the lip and the foam; a pixel may take the next tone up or down its ramp, with a phase that travels outward from the tube for the rings (they breathe and flow) and
   *      diagonally for the sunlit tones (the glow slides along the lip and the face). All colours stay the plate's own. */
  const SIN = new Int8Array(256);
  for (let i = 0; i < 256; i++) SIN[i] = Math.round(127 * Math.sin(i / 256 * 2 * Math.PI));
  const RAMP_AMP = [0, 1.9, 2.3];
  /** The two ramps of the backdrop's water, found from its own colours: family 1 teal (hue 150-225 degrees), family 2 sunlit peach, cream and gold; each sorted by luminance. */
  function buildRamps(back, skip) {
    const { rgb: pix, cls } = back, count = new Map();
    for (let i = 0; i < pix.length; i++) if (cls[i] === CLS.WATER) count.set(pix[i], (count.get(pix[i]) || 0) + 1);
    const fams = [null, [], []];
    for (const [c, n] of count) {
      if (n < 20) continue;
      const [r, g, b] = unpack(c), mx = Math.max(r, g, b), mn = Math.min(r, g, b), sat = mx ? (mx - mn) / mx : 0, lum = 0.3 * r + 0.59 * g + 0.11 * b;
      let hue = 0;
      if (mx !== mn) hue = mx === r ? 60 * (((g - b) / (mx - mn)) % 6) : mx === g ? 60 * ((b - r) / (mx - mn) + 2) : 60 * ((r - g) / (mx - mn) + 4);
      if (hue < 0) hue += 360;
      if (hue >= 150 && hue <= 225 && (sat > 0.5 || (sat > 0.28 && lum > 190))) fams[1].push([lum, c]);                  // saturated teals and the pale aqua, never the plate's few greys
      else if (r >= 200 && g >= 150 && b >= 100 && r - b >= 25 && r >= g) fams[2].push([lum, c]);
    }
    const tables = [null], rankOf = [null];
    for (const f of [1, 2]) {
      fams[f].sort((p, q) => p[0] - q[0]);
      if (fams[f].length < 2) return null;
      tables.push(Uint32Array.from(fams[f].map((p) => p[1]))); rankOf.push(new Map(fams[f].map((p, k) => [p[1], k])));
    }
    const fam = new Uint8Array(pix.length), rank = new Uint8Array(pix.length);
    for (let i = 0; i < pix.length; i++) {
      if (cls[i] !== CLS.WATER) continue;
      if (skip && skip(i % W, (i / W) | 0)) continue;
      for (const f of [1, 2]) { const k = rankOf[f].get(pix[i]); if (k !== undefined) { fam[i] = f; rank[i] = k; break; } }
    }
    return { fam, rank, tables, len: [0, tables[1].length, tables[2].length] };
  }
  function buildWarp(cls, geom, rgbBuf) {
    const [cx, cy] = geom.centre, hz = geom.horizon;
    const ramp = rgbBuf ? buildRamps({ rgb: rgbBuf, cls }, (x, y) => x < 100 && y >= 118 && y < 186) : null;           // not behind the clock, where the scrim has darkened the colours
    const sea = { idx: [], ax: [], ph: [] }, water = { idx: [], ax: [], ay: [], ph: [] };
    const edge = (x, y, c) => { for (let dy = -3; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) { const nx = x + dx, ny = y + dy; if (nx >= 0 && nx < W && ny >= 0 && ny < H && cls[ny * W + nx] !== c) return true; } return false; };
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = y * W + x, c = cls[i];
        if ((c === CLS.SEA || c === CLS.WATER) && (x < 4 || x >= W - 4 || y < 4 || y >= H - 4 || edge(x, y, c))) continue;   // the pixels near another class (or the screen's edge) stay still: silhouettes never tear
        if (c === CLS.SEA) {
          const dd = y - hz, amp = dd < 6 ? 1 : dd < 28 ? 2 : 3;
          sea.idx.push(i); sea.ax.push(amp); sea.ph.push(((y * 9 + (x >> 2)) & 255));
        } else if (c === CLS.WATER) {
          const dx = x - cx, dy = y - cy, r = Math.hypot(dx, dy) || 1, ux = dx / r, uy = dy / r, f = ramp ? ramp.fam[i] : 0;
          if (f === 2) {                                                                      // sunlit tones slide along the flow, counter-clockwise around the tube: up the face, over the lip
            water.idx.push(i); water.ax.push(Math.round(uy * 3)); water.ay.push(Math.round(-ux * 3)); water.ph.push(Math.round(x * 3 + y * 2) & 255);
          } else {                                                                            // rings: mostly radial, a little spiral
            const k = 0.5, tx = -uy, ty = ux, vx = ux * Math.cos(k) + tx * Math.sin(k), vy = uy * Math.cos(k) + ty * Math.sin(k);
            water.idx.push(i); water.ax.push(Math.round(vx * 4)); water.ay.push(Math.round(vy * 4)); water.ph.push(Math.round(r * 5) & 255);
          }
        }
      }
    }
    const pack32 = (o) => { const r = {}; for (const k of Object.keys(o)) r[k] = k === 'idx' ? Int32Array.from(o[k]) : k === 'ph' ? Uint8Array.from(o[k]) : Int8Array.from(o[k]); return r; };
    return { sea: pack32(sea), water: pack32(water), ramp };
  }
  /** Copy the backdrop into `dst` and warp the animated pixels; `t` is the time in steps. Only rows above `lim` are touched. */
  function applyWarp(dst, back, warp, t, lim, srcRgb) {
    const src = srcRgb || back.rgb, cls = back.cls, end = lim * W;
    dst.set(end >= W * H ? src : src.subarray(0, end));
    const ts = (t * 1.6) | 0, tw = (t * 2.4) | 0, S = warp.sea, Wt = warp.water, R = warp.ramp;
    for (let k = 0, n = S.idx.length; k < n; k++) {
      const i = S.idx[k];
      if (i >= end) break;
      const ox = ((SIN[(S.ph[k] + ts) & 255] * S.ax[k]) / 128) | 0;
      if (ox === 0) continue;
      if (cls[i + ox] === CLS.SEA) dst[i] = src[i + ox];
    }
    for (let k = 0, n = Wt.idx.length; k < n; k++) {
      const i = Wt.idx[k];
      if (i >= end) break;
      const s = SIN[(Wt.ph[k] + tw) & 255], ox = ((s * Wt.ax[k]) / 128) | 0, oy = ((s * Wt.ay[k]) / 128) | 0;
      let j = i;
      if (ox !== 0 || oy !== 0) { const jj = i + oy * W + ox; if (cls[jj] === CLS.WATER) j = jj; }
      let c = src[j];
      if (R) { const f = R.fam[j]; if (f) { const sh = ((s * RAMP_AMP[f]) / 128) | 0; if (sh) { const nr = R.rank[j] + sh; c = R.tables[f][nr < 0 ? 0 : nr >= R.len[f] ? R.len[f] - 1 : nr]; } } }
      if (c !== dst[i]) dst[i] = c;
    }
  }

  /* ---- the surfer, the hero: riding toward the viewer and slightly left, about 54 px with the board. A pose is a handful of numbers (hip, lean, head, hands, rail, where the feet stand); legs and arms follow by
   *      two-bone inverse kinematics; the board's pitch follows the way he moves; poses blend into each other, so he crouches, carves, hangs ten, tucks, flies and stands up without
   *      any jump. There is no rotation: he keeps his stance throughout. Paddling and swimming have their own figures.
   *      Every limb is a tapered capsule shaded in three tones (light on the side of the sun, shade opposite), the head is a small hand-pixelled picture, the board has a graphic,
   *      and the whole figure is outlined in dark violet and rim-lit with the sunset on its sunny edge. He is drawn into a raster and blitted. */
  const SC = 1.25, K = 1.12 * SC, FS = 1.3 * SC;
  const THIGH = 8.8 * K, SHIN = 8.8 * K, TORSO = 12.2 * K, UPPER = 5.7 * K, FORE = 5.7 * K, FOOT_F = -8.2 * K, FOOT_B = 8.2 * K, DECK = -2.3 * K, BOARD_HALF = 24, NECK = 4.8 * K;
  const BACK_THIGH = THIGH * 0.88, BACK_SHIN = SHIN * 1.12;   // the far leg is seen at an angle: its thigh is foreshortened
  const POSE_KEYS = ['hx', 'hy', 'lean', 'head', 'fx', 'fy', 'bx', 'by', 'rail', 'ffx', 'bfx'];
  const P = (hx, hy, lean, head, fx, fy, bx, by, rail, ffx = -8.2, bfx = 8.2) => ({ hx: hx * FS, hy: hy * FS, lean, head, fx: fx * FS, fy: fy * FS, bx: bx * FS, by: by * FS, rail, ffx: ffx * K, bfx: bfx * K });
  const POSES = {                                                                   // hip (x, y above the deck: negative is up), torso lean (deg, forward = left), head tilt, front hand and back hand (from the shoulder), rail, front and back foot
    trim: P(-1.5, -12.6, 16, -12, -8.8, 1.8, 8.6, 2.2, 0.05),
    pumpDown: P(-2.4, -9.2, 32, -24, -8.4, 4.6, 8.2, 4.2, 0.28),
    pumpUp: P(0.4, -14.6, 6, 0, -8.6, -2.8, 8.4, -1.4, 0.05),
    bottom: P(-2.6, -8.4, 44, -34, -7.8, 5.8, 8.2, -4.2, 0.90, -8, 8.5),
    top: P(1.8, -11.4, -12, 10, -8.8, -3.4, 8.4, 4.6, 1.0),
    tuck: P(1, -7.8, 52, -42, -7.4, 7.2, 7.2, 6.4, 0.4, -6.2, 6),
    cheer: P(0, -14.8, -3, 10, -7.2, -7.6, 7.2, -7.6, 0),
    air: P(0, -11.4, 12, -2, -8.8, -3.2, 8.6, -2.6, 0),
    grab: P(-2.0, -9.2, 34, -24, -6.4, 9.0, 8.2, -5.6, 0),
    fall: P(0, -13, 35, 14, -8.6, -7.4, 8.6, -6.8, 0),
    crouch: P(-0.8, -9.6, 34, -26, -8.6, 3.6, 8.4, 2.8, 0.32, -7.6, 7.6),
    hangTen: P(-9.2, -14.4, 8, -4, -9.0, -0.8, 8.8, -0.6, 0, -16, -5),
    cutback: P(2.4, -10.8, -16, 14, -8.6, -1.6, 8.6, 5.4, 1.0),
    anticipate: P(-2, -9.2, 36, -28, -7.0, 6.2, 8.4, 3.0, 0.12),                     // the coil before a pop: low, the arms back
    pop: P(1.0, -16.2, -2, 5, -8.4, -4.6, 8.2, -3.8, 0),                             // full extension, straight up
    airTuck: P(-1.8, -8.8, 34, -12, -6.4, 8.0, 8.2, -3.4, 0),                        // the knees drawn up, the front hand reaching for the rail
    extend: P(0, -15.2, 2, 4, -9.0, -3.0, 9.0, -2.6, 0),                             // let go of the rail, arms wide
    land: P(-2.0, -9.2, 38, -28, -8.4, 4.4, 8.4, 3.8, 0.25, -7.8, 7.8),              // absorbing the landing with the knees
    floater: P(0.4, -11.6, 10, -4, -8.8, 0.8, 8.6, -1.4, 0.35),                      // gliding on the white water at the top
    barrel: P(0.5, -10.0, 28, -22, -9.0, 0.6, 8.6, 4.8, 0.5, -8, 8),                 // soft knees, leading arm toward the exit and trailing hand near the face
    barrelSet: P(1.1, -10.3, 33, -28, -8.6, 1.6, 8.8, 5.6, 0.55, -8, 8),
    barrelDeep: P(1.3, -9.4, 40, -32, -8.8, 4.0, 9.0, 6.8, 0.58, -8, 8),
    stall: P(3.2, -10.2, 34, -34, -8.8, -1.2, 9.2, 6.4, 0.72, -8, 8),                // weight over the tail, rear hand toward the wall
    drag: P(0.6, -9.6, 32, -26, -9.8, -1.0, 8.6, 8.8, 0.62, -8, 8),                  // lower one hand and counterbalance with the other
    duck: P(1.0, -9.3, 50, -45, -8.6, 3.6, 8.8, 5.8, 0.42, -8, 8),                   // compress under the breaking lip
    barrelUp: P(0, -11.8, 26, -22, -8.8, 0.0, 8.6, 4.2, 0.22, -8, 8),                // recover more slowly into an open crouch
    exitTall: P(0, -15.0, -3, 7, -9.2, -2.2, 9.2, -2.2, 0, -8.2, 8.2),               // standing up tall with the arms spread as the foam spits him out
    fall1: P(3, -12.8, -18, -6, -8.8, -6.6, 6.8, 6.4, 0),                            // losing balance: leaning back, the front arm up, the back arm down
    fall2: P(3, -12.8, -18, -6, -7.2, 5.8, 8.6, -6.6, 0),                            // and the other way (the arms windmill)
    fallDrop: P(4, -11.0, -10, 6, -8.4, -7.2, 8.4, -7.0, 0),                         // off the board, the arms up
  };
  const blendPose = (a, b, t) => { const o = {}; for (const k of POSE_KEYS) o[k] = a[k] + (b[k] - a[k]) * t; return o; };
  /** Two-bone inverse kinematics: the joint between a root and a tip; `side` +1 puts it on the left of the root-to-tip direction on screen (a knee that points forward when the tip is below the root), -1 on the right. */
  function bend(rx, ry, tx, ty, l1, l2, side) {
    const dx = tx - rx, dy = ty - ry, m = Math.hypot(dx, dy) || 0.001, d = Math.max(0.001, Math.min(m, l1 + l2 - 0.01));
    const a = (l1 * l1 - l2 * l2 + d * d) / (2 * d), h = Math.sqrt(Math.max(0, l1 * l1 - a * a)), ux = dx / m, uy = dy / m;
    return [rx + ux * a - uy * side * h, ry + uy * a + ux * side * h];
  }
  /** Every joint of the surfer for a pose and a board pitch (degrees, nose up positive), relative to the middle of the board's deck; x grows to the right, y down. */
  function figure(pose, pitch) {
    const p = pitch * RAD, cp = Math.cos(p), sp = Math.sin(p), rot = (x, y) => [x * cp - y * sp, x * sp + y * cp];
    const b = 0.55 * p, cb = Math.cos(b), sb = Math.sin(b), rotBody = (x, y) => [x * cb - y * sb, x * sb + y * cb];
    const footF = rot(pose.ffx === undefined ? FOOT_F : pose.ffx, DECK), footB = rot(pose.bfx === undefined ? FOOT_B : pose.bfx, DECK), hip = rotBody(pose.hx, pose.hy), mid = [(footF[0] + footB[0]) / 2, (footF[1] + footB[1]) / 2], reach = (THIGH + SHIN) * 0.985;
    for (let i = 0; i < 16 && (Math.hypot(hip[0] - footF[0], hip[1] - footF[1]) > reach || Math.hypot(hip[0] - footB[0], hip[1] - footB[1]) > reach); i++) { hip[0] += (mid[0] - hip[0]) * 0.07; hip[1] += (mid[1] - hip[1]) * 0.07; }
    // Keep the back knee visibly clear of the deck. A bent leg that rests
    // on the board looks like kneeling, rather than an athlete surfing.
    // Adjust in board coordinates and keep both feet within leg reach.
    const normal = [-sp, cp];
    let kneeB = bend(hip[0], hip[1], footB[0], footB[1], BACK_THIGH, BACK_SHIN, 1);
    for (let i = 0; i < 20 && (kneeB[0] - footB[0]) * normal[0] + (kneeB[1] - footB[1]) * normal[1] > -1.5; i++) {
      const next = [hip[0] - normal[0] * 0.4, hip[1] - normal[1] * 0.4];
      if (Math.hypot(next[0] - footF[0], next[1] - footF[1]) > reach || Math.hypot(next[0] - footB[0], next[1] - footB[1]) > reach) break;
      hip[0] = next[0]; hip[1] = next[1];
      kneeB = bend(hip[0], hip[1], footB[0], footB[1], BACK_THIGH, BACK_SHIN, 1);
    }
    const kneeF = bend(hip[0], hip[1], footF[0], footF[1], THIGH, SHIN, 1);          // both knees point forward
    const lean = pose.lean * RAD, shoulder = [hip[0] - TORSO * Math.sin(lean + b), hip[1] - TORSO * Math.cos(lean + b)];
    const neckA = (pose.lean * 0.55 + (pose.lean + pose.head) * 0.45) * RAD + b, head = [shoulder[0] - NECK * Math.sin(neckA), shoulder[1] - NECK * Math.cos(neckA)];
    const sF = [shoulder[0] - 0.5, shoulder[1] + 0.5], armReach = (UPPER + FORE) * 0.97;
    const within = (dx, dy) => { const m = Math.hypot(dx, dy); return m > armReach ? [dx * armReach / m, dy * armReach / m] : [dx, dy]; };         // an arm cannot reach farther than it is long
    const sB = [shoulder[0] + 0.5, shoulder[1]], oF = within(pose.fx, pose.fy), oB = within(pose.bx, pose.by), handF = [sF[0] + oF[0], sF[1] + oF[1]], handB = [sB[0] + oB[0], sB[1] + oB[1]];
    const elbowF = bend(sF[0], sF[1], handF[0], handF[1], UPPER, FORE, -1), elbowB = bend(sB[0], sB[1], handB[0], handB[1], UPPER, FORE, 1);           // natural downward-hanging elbows on both arms
    return { hip, shoulder, head, kneeF, kneeB, footF, footB, elbowF, elbowB, handF, handB, sF, sB };
  }
  /** The colours of the surfer, as indices into one packed palette (0 is empty); each body colour has a light and a dark tone next to it. */
  const S = { skin: 1, skinShade: 2, skinLight: 3, hair: 4, hairLight: 5, shirt: 6, shirtShade: 7, shirtLight: 8, trunks: 9, trunksLight: 10, trunksDark: 11, stripe: 12, eye: 13, mouth: 14,
    board: 15, boardLight: 16, boardDark: 17, cream: 18, fin: 19, cap: 20, white: 21, belly: 22 };
  const TONES = { skin: [S.skin, S.skinLight, S.skinShade], shirt: [S.shirt, S.shirtLight, S.shirtShade], trunks: [S.trunks, S.trunksLight, S.trunksDark], board: [S.board, S.boardLight, S.boardDark] };
  function surferPalette() {
    const c = hexPack, p = new Uint32Array(23);
    p[S.skin] = c('#db9b7c'); p[S.skinLight] = c('#f7caa0'); p[S.skinShade] = c('#9e625d'); p[S.hair] = c('#1e1834'); p[S.hairLight] = c('#8c5446');
    p[S.shirt] = c('#d2dce8'); p[S.shirtLight] = c('#f0eee4'); p[S.shirtShade] = c('#62789a'); p[S.trunks] = c('#d6404e'); p[S.trunksLight] = c('#ff7a68'); p[S.trunksDark] = c('#7a1c34');
    p[S.stripe] = c('#ef5b48'); p[S.eye] = c('#1e2034'); p[S.mouth] = c('#a4635c'); p[S.board] = c('#f0c276'); p[S.boardLight] = c('#fff2c8'); p[S.boardDark] = c('#274858');
    p[S.cream] = c('#fff0c4'); p[S.fin] = c('#253941'); p[S.cap] = c('#ff5e4d'); p[S.white] = c('#eef6f0'); p[S.belly] = c('#8b5e5d');
    return p;
  }
  /** The warm rim of the sunset on the sunny edge of every part: the palette index -> a brighter, warmer packed colour. */
  function rimPalette(pal) {
    const out = new Uint32Array(pal.length), warm = rgb('#ffea9e');
    for (let i = 1; i < pal.length; i++) out[i] = pack(mixRgb(unpack(pal[i]), warm, i === S.eye || i === S.mouth ? 0.15 : 0.56));
    return out;
  }
  const OUTLINE = hexPack('#1c0f3a');
  const LIGHT = [-0.8, -0.6];                                                                                                   // the sun is on the left, a little above
  /** A tapered limb from a to b (widths wa, wb in px): a capsule in the base tone, a one-pixel highlight along its sunny edge and a one-pixel shade along the other. */
  function limb(r, a, b, wa, wb, tone) {
    const dx = b[0] - a[0], dy = b[1] - a[1], m = Math.hypot(dx, dy) || 1;
    let sx = -dy / m, sy = dx / m; if (sx * LIGHT[0] + sy * LIGHT[1] < 0) { sx = -sx; sy = -sy; }                                // (sx, sy) points to the light
    r.poly([[a[0] + sx * wa / 2, a[1] + sy * wa / 2], [b[0] + sx * wb / 2, b[1] + sy * wb / 2], [b[0] - sx * wb / 2, b[1] - sy * wb / 2], [a[0] - sx * wa / 2, a[1] - sy * wa / 2]], tone[0]);
    r.disc(Math.round(a[0]), Math.round(a[1]), Math.round(wa / 2 - 0.2), tone[0]); r.disc(Math.round(b[0]), Math.round(b[1]), Math.round(wb / 2 - 0.2), tone[0]);
    if (wa > 2.6 && wb > 2.6) {
      r.line(a[0] + sx * (wa / 2 - 0.9), a[1] + sy * (wa / 2 - 0.9), b[0] + sx * (wb / 2 - 0.9), b[1] + sy * (wb / 2 - 0.9), tone[1], 1);
      r.line(a[0] - sx * (wa / 2 - 0.7), a[1] - sy * (wa / 2 - 0.7), b[0] - sx * (wb / 2 - 0.7), b[1] - sy * (wb / 2 - 0.7), tone[2], 1);
    }
  }
  /** Compact three-quarter portrait with the eyes just under the brow. */
  const HEAD_UP = ['..hhh....', '.hllhhh..', 'hhdshhhd.', 'hdsaaaas.', 'hdsaaeaas', '.dsaaassd', '.ddsaasda', '..ddsmd..', '...ddd...', '.........'];
  const HEAD_DOWN = ['..hhh....', '.hllhhh..', 'hhhhhhhs.', 'hdhsaaas.', '.dsaaeaas', '.ddsaasdd', '..ddssda.', '...dmd...', '...dd....', '.........'];
  const HEAD_KEY = { h: S.hair, l: S.hairLight, s: S.skin, a: S.skinLight, d: S.skinShade, e: S.eye, b: S.hair, m: S.mouth, o: S.skinShade };
  function drawHead(r, cx, cy, face, down) {
    const rows = down ? HEAD_DOWN : HEAD_UP;
    for (let y = 0; y < 10; y++) for (let x = 0; x < 9; x++) {
      const ch = rows[y][x];
      if (ch === '.') continue;
      r.put(face > 0 ? cx - 4 + x : cx + 4 - x, cy - 5 + y, HEAD_KEY[ch]);
    }
  }
  // Perspective: the nose comes toward the lower left of the viewer, while
  // the tail recedes to the upper right. The same projection is used for the
  // deck and for the rider's feet, so neither floats as the board pitches.
  const DECK_X = .63, DECK_DEPTH = .50, RIDER_OX = 64, RIDER_OY = 84;
  const projectDeck = (x, y) => [DECK_X * x, y - DECK_DEPTH * x];
  // A point on the foreshortened board, in scene coordinates. Keep wake and
  // spray anchored to the same perspective and pitch as the drawn deck.
  function boardPoint(s, along, across = 0) {
    const p = s.pitchQ * RAD, cp = Math.cos(p), sp = Math.sin(p);
    const q = projectDeck(along * cp - across * sp, along * sp + across * cp);
    return [s.x + q[0], s.y + q[1]];
  }
  const boardHalfWidth = (along) => {
    const t = (along + BOARD_HALF) / (2 * BOARD_HALF);
    return Math.sin(Math.PI * t) * (4.6 + 1.8 * (1 - t));
  };
  const deckPitch = (pitch) => {
    const p = pitch * RAD;
    return Math.atan2(Math.sin(p) - DECK_DEPTH * Math.cos(p), DECK_X * Math.cos(p));
  };
  /** A foreshortened board: broad near nose, tapered tail and visible deck. */
  function drawBoard(r, ox, oy, angle, squeeze, rail) {
    const cp = Math.cos(angle), sp = Math.sin(angle), half = BOARD_HALF, sq = Math.max(.22, Math.abs(squeeze));
    const at = (s, t = 0, dy = 0) => {
      const x = s * sq * cp - t * sp, y = s * sq * sp + t * cp;
      const p = projectDeck(x, y);
      return [ox + p[0], oy + p[1] + dy];
    };
    const edge = (scale, offset = 0) => {
      const top = [], bottom = [];
      for (let s = -half; s <= half; s += 2) {
        const width = boardHalfWidth(s) * scale;
        top.push(at(s, -width, offset)); bottom.unshift(at(s, width, offset));
      }
      return top.concat(bottom);
    };
    r.poly(edge(1, 2 + (rail > .5 ? 1 : 0)), S.boardDark);
    r.poly(edge(1), S.board);
    r.poly(edge(.65, -.4), S.boardLight);
    const a = at(-half + 3), b = at(half - 3);
    r.line(a[0], a[1], b[0], b[1], S.cream, 1);
    const glint = at(-half*.69, -boardHalfWidth(-half*.69)*.82);
    const glintEnd = at(half*.38, -boardHalfWidth(half*.38)*.82);
    r.line(glint[0], glint[1], glintEnd[0], glintEnd[1], S.cream, 1);
    const tip = at(-half + 1), end = at(-half + 5);
    r.line(tip[0], tip[1], end[0], end[1], S.cap, 2);
  }
  /** A leg: a thigh that tapers to the knee, a calf that swells a little behind the shin and tapers to the ankle, a lighter knee cap. `bendSide` is the way the knee points (the calf bulges the other way). */
  function leg(r, hip, knee, ankle, tone, w0, kneeCap) {
    const scale = w0 / 6.4;
    limb(r, hip, knee, w0, 4.9 * scale, tone);
    const dx = ankle[0] - knee[0], dy = ankle[1] - knee[1], m = Math.hypot(dx, dy) || 1, nx = -dy / m, ny = dx / m, side = nx > 0 ? 1 : -1;       // the normal on the side of the heel (the right, toward the tail)
    const calf = [knee[0] + dx * 0.36 + nx * side * 0.7, knee[1] + dy * 0.36 + ny * side * 0.7];
    limb(r, knee, ankle, 5.0 * scale, 3.3 * scale, tone); r.disc(Math.round(calf[0]), Math.round(calf[1]), Math.round(2 * scale), tone[0]);
    if (kneeCap) r.put(Math.round(knee[0] - 1.6 * scale), Math.round(knee[1]), tone[1]);
  }
  /** A foot aligned with the deck; prone toes point toward the tail. */
  function foot(r, ankle, pitchRad, len, tone, scale = 1, direction = -1) {
    const cp = Math.cos(pitchRad), sp = Math.sin(pitchRad), x = ankle[0], y = ankle[1] + 0.6;
    limb(r, [x + 0.6, y], [x + direction * len * cp, y + direction * len * sp + 0.6], 3 * scale, 2.2 * scale, [tone[0], tone[1], tone[2]]);
    r.line(x + 0.6, y + 1.6, x + direction * len * cp, y + direction * len * sp + 1.9, tone[2], 1);
  }
  function standingJoints(ox, oy, pose, pitch) {
    const f = figure(pose, pitch), J = {};
    const front = projectDeck(...f.footF), back = projectDeck(...f.footB), hip = f.hip.slice();
    // Keep both legs able to reach the newly projected deck, then re-solve
    // the knees. Move the upper body as one instead of stretching the limbs.
    for (let i = 0; i < 24; i++) for (const target of [front, back]) {
      const dx = target[0] - hip[0], dy = target[1] - hip[1], d = Math.hypot(dx, dy), max = (THIGH + SHIN) * .985;
      if (d > max) { hip[0] += dx * (d - max) / d; hip[1] += dy * (d - max) / d; }
    }
    const shift = [hip[0] - f.hip[0], hip[1] - f.hip[1]];
    for (const k of Object.keys(f)) J[k] = [ox + f[k][0] + shift[0], oy + f[k][1] + shift[1]];
    J.hip = [ox + hip[0], oy + hip[1]];
    J.footF = [ox + front[0], oy + front[1]]; J.footB = [ox + back[0], oy + back[1]];
    J.kneeF = bend(...J.hip, ...J.footF, THIGH, SHIN, 1);
    J.kneeB = bend(...J.hip, ...J.footB, BACK_THIGH, BACK_SHIN, 1);
    // A three-quarter frontal torso: preserve the pose's height and motion,
    // but foreshorten the sideways lean rather than showing the rider's back.
    const chestShift = -.50 * (J.shoulder[0] - J.hip[0]);
    for (const key of ['shoulder', 'head', 'sF', 'sB', 'elbowF', 'elbowB', 'handF', 'handB']) J[key][0] += chestShift;
    for (const key of ['sB', 'elbowB', 'handB']) J[key][0] += 1.4;
    return J;
  }
  function drawBody(r, J, pitch, down, wide = 1.12, legScale = 1, toeDirection = -1) {
    const face = -1, pr = deckPitch(pitch), shade = [S.skinShade, S.skin, S.skinShade];
    const hipsNear = [J.hip[0] - 1.3, J.hip[1] + 1], hipsFar = [J.hip[0] + 1.7, J.hip[1] - 1];
    // Layer the far arm and both legs behind the clothing. In particular the
    // near thigh must not paint over the shorts when the rider compresses.
    leg(r, hipsFar, J.kneeB, J.footB, shade, 6.0 * legScale, false); foot(r, J.footB, pr, 3.4 * legScale, shade, legScale, toeDirection);
    limb(r, J.sB, J.elbowB, 4, 3.4, [S.shirtShade, S.shirt, S.shirtShade]); limb(r, J.elbowB, J.handB, 3.4, 2.8, shade); r.disc(Math.round(J.handB[0]), Math.round(J.handB[1]), 2, S.skinShade);
    leg(r, hipsNear, J.kneeF, J.footF, TONES.skin, 6.4 * legScale, true); foot(r, J.footF, pr, 5 * legScale, TONES.skin, legScale, toeDirection);
    limb(r, J.hip, J.shoulder, 8.7 * wide, 10.6 * wide, TONES.shirt);
    limb(r, J.hip, [J.hip[0] + (J.kneeB[0] - J.hip[0]) * 0.63, J.hip[1] + (J.kneeB[1] - J.hip[1]) * 0.63], 9.0 * wide, 6.8, TONES.trunks);
    limb(r, J.hip, [J.hip[0] + (J.kneeF[0] - J.hip[0]) * 0.63, J.hip[1] + (J.kneeF[1] - J.hip[1]) * 0.63], 9.0 * wide, 6.8, TONES.trunks);
    r.line(J.hip[0] - 3, J.hip[1] - 1, J.hip[0] + 3, J.hip[1] - 1, S.stripe, 1);
    const neck = blendPoint(J.shoulder, J.head, .62);
    limb(r, J.shoulder, neck, 4.5, 3.3, TONES.skin);
    // An exposed collar and angled seam separate the neck and torso.
    r.line(J.shoulder[0] - 2, J.shoulder[1] + 1, J.shoulder[0] + 1, J.shoulder[1] + 2, S.skinShade, 1);
    r.line(J.shoulder[0] - 2, J.shoulder[1] + 5, J.hip[0] - 2, J.hip[1] - 3, S.shirtLight, 1);
    r.line(J.shoulder[0] - 4, J.shoulder[1] + 3, J.shoulder[0] + 2, J.shoulder[1] + 6, S.stripe, 1);
    limb(r, J.sF, J.elbowF, 4.2, 3.6, TONES.shirt); limb(r, J.elbowF, J.handF, 3.6, 2.8, TONES.skin); r.disc(Math.round(J.handF[0]), Math.round(J.handF[1]), 2, S.skin);
    drawHead(r, Math.round(J.head[0]), Math.round(J.head[1]), face, down);                                                                         // the head last: no arm covers his face
  }
  /** Draw the standing figure with both feet attached to the board. */
  function drawStanding(r, ox, oy, st) {
    const J = standingJoints(ox, oy, st.pose, st.pitch);
    if (st.board !== false) drawBoard(r, Math.round(ox), Math.round(oy), st.pitch * RAD, 1, st.pose.rail);
    drawBody(r, J, st.pitch, st.pose.lean + st.pose.head > 28);
    return J;
  }

  const distanceBetween = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
  const blendPoint = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t)];
  const withLift = (p, lift) => [p[0], p[1] - lift];
  function reachableJoint(root, tip, reach) {
    const distance = distanceBetween(root, tip);
    return distance > reach ? blendPoint(root, tip, reach / distance) : tip;
  }

  /** A prone rider with an arched chest and alternating freestyle strokes:
   *  each arm pulls down in the water from nose to tail, then lifts in a high-
   *  elbow arc over the water back to the nose. `plant` brings both hands to
   *  the deck as the wave is caught. */
  function paddlingJoints(ox, oy, pitch, phase, plant) {
    const p = pitch * RAD, cp = Math.cos(p), sp = Math.sin(p), settle = smooth(clamp(plant || 0, 0, 1)), active = 1 - settle;
    const at = (x, y, lift = 0) => {
      const q = projectDeck(x * cp - y * sp, x * sp + y * cp);
      return [ox + q[0], oy + q[1] - lift];
    };
    const c = Math.cos(phase), v = Math.sin(phase), kick = Math.sin(phase * 2) * active;
    const roll = c * active, bob = Math.sin(phase * 2 + 0.6) * active;
    const hip = at(5, 0, 3.6 + 0.35 * bob), shoulder = at(-10, 0, 9.4 + 0.6 * bob), head = at(-15.2, 0, 16.0 + 0.7 * bob);
    head[1] = Math.min(head[1], hip[1] - 5);
    // Each shoulder sits on its own side of the chest and rolls naturally with
    // each reaching stroke before squaring onto the rails at plant = 1.
    const normal = projectDeck(-sp, cp), length = Math.hypot(...normal) || 1;
    const nx = normal[0] / length, ny = normal[1] / length;
    const sF = [shoulder[0] + 2.5 * nx - 0.6 * roll, shoulder[1] + 2.5 * ny + 0.8 * roll];
    const sB = [shoulder[0] - 1.2 * nx + 0.6 * roll, shoulder[1] - 1.2 * ny - 0.8 * roll];
    const reach = (UPPER + FORE) * 1.2 * 0.985;
    // Front arm: aF moves nose (-13.2) -> tail (-0.8) when v > 0 (power pull in
    // the water) and tail -> nose when v < 0 (high-elbow air recovery).
    // Back arm: opposite phase — pulls when v < 0 and recovers when v > 0.
    const aF = -6.8 - 6.6 * c, aB = -6.8 + 6.6 * c;
    const pullF = Math.max(0, v), recF = Math.max(0, -v);
    const pullB = Math.max(0, -v), recB = Math.max(0, v);
    const strokeF = at(aF, boardHalfWidth(aF) + 7.2 + 2.0 * recF, 5.4 * recF - 3.6 * pullF);
    const strokeB = at(aB, -boardHalfWidth(aB) - 6.8 - 1.4 * pullB, 5.2 * recB - 2.6 * pullB);
    const handF = reachableJoint(sF, blendPoint(strokeF, at(-9, 3.3, 1.5), settle), reach);
    const handB = reachableJoint(sB, blendPoint(strokeB, at(-6.2, -3.6, 1.5), settle), reach);
    // Natural elbow bend: arched high over the water on recovery, tucked beside
    // the rail during the pull, converging smoothly to the push-up press.
    const elbowF = bend(...sF, ...handF, UPPER * 1.2, FORE * 1.2, -1);
    const eBDown = bend(...sB, ...handB, UPPER * 1.2, FORE * 1.2, 1);
    const eBUp = bend(...sB, ...handB, UPPER * 1.2, FORE * 1.2, -1);
    const elbowB = blendPoint(eBUp, eBDown, pullB * 0.72 * active);
    return { hip, shoulder, head, sF, sB, elbowF, elbowB, handF, handB,
      kneeF: at(14, 2.2, 3.4 + 0.5 * kick), kneeB: at(13, -1.8, 4.2 - 0.5 * kick),
      footF: at(22, 1.8, 1.6 + 1.4 * kick), footB: at(20.8, -1.8, 2.0 - 1.4 * kick) };
  }
  /** The palms take the weight until the feet swing underneath and the
   *  leading foot lands. Hands, hips and feet each have their own timing. */
  function takeoffJoints(ox, oy, pose, pitch, t, phase) {
    const start = paddlingJoints(ox, oy, pitch, phase, 1);
    if (t === 0) return start;
    const target = standingJoints(ox, oy, pose, pitch);
    if (t === 1) return target;

    const push = smooth(t / .42), hipPush = smooth((t - .05) / .39), stand = smooth((t - .44) / .56);
    const knees = smooth((t - .20) / .54);
    const release = smooth((t - .45) / .53);
    const rear = smooth((t - .18) / .45), front = smooth((t - .19) / .55);
    const J = {
      hip: blendPoint(withLift(start.hip, 10.6 * hipPush), target.hip, stand),
      shoulder: blendPoint(withLift(start.shoulder, 9.6 * push), target.shoulder, stand),
      head: blendPoint(withLift(start.head, 8.8 * push), target.head, stand),
      footF: withLift(blendPoint(start.footF, target.footF, front), lerp(4.2, 7.0, smooth((pitch + 30) / 30)) * Math.sin(Math.PI * front)),
      footB: withLift(blendPoint(start.footB, target.footB, rear), 3.4 * Math.sin(Math.PI * rear)),
    };
    for (const side of ['F', 'B']) {
      const shoulder = 's' + side, hand = 'hand' + side;
      J[shoulder] = blendPoint(withLift(start[shoulder], 9.6 * push), target[shoulder], stand);
      J[hand] = release > 0 ? withLift(blendPoint(start[hand], target[hand], release), 2.2 * Math.sin(Math.PI * release)) : start[hand].slice();
      const knee = 'knee' + side, foot = 'foot' + side;
      const thigh = lerp(distanceBetween(start.hip, start[knee]), side === 'F' ? THIGH : BACK_THIGH, knees);
      const shin = lerp(distanceBetween(start[knee], start[foot]), side === 'F' ? SHIN : BACK_SHIN, knees);
      const flexed = bend(...J.hip, ...J[foot], thigh, shin, 1);
      // Guide the knee smoothly under the chest without bunching into the face.
      const guided = withLift(blendPoint(start[knee], target[knee], knees), 2.6 * Math.sin(Math.PI * knees));
      J[knee] = blendPoint(guided, flexed, .42 * Math.sin(Math.PI * knees));
    }
    const armScale = lerp(1.2, 1, smooth(t)), upper = UPPER * armScale, fore = FORE * armScale;
    // Respect the arm span by moving the upper body while supported. Free
    // wrists then open smoothly into balanced surf arms as the torso rises.
    const reach = (upper + fore) * .985;
    for (const side of ['F', 'B']) {
      const shoulder = J['s' + side], palm = J['hand' + side];
      const fit = reachableJoint(palm, shoulder, reach);
      const dx = (fit[0] - shoulder[0]) * (1 - release);
      const dy = (fit[1] - shoulder[1]) * (1 - release);
      for (const key of ['shoulder', 'head', 'sF', 'sB']) J[key] = [J[key][0] + dx, J[key][1] + dy];
    }
    for (const side of ['F', 'B']) {
      const shoulder = J['s' + side], hand = 'hand' + side;
      if (release > 0) J[hand] = reachableJoint(shoulder, J[hand], reach);
      if (side === 'F') J.elbowF = bend(...shoulder, ...J[hand], upper, fore, -1);
      else J.elbowB = blendPoint(bend(...shoulder, ...J[hand], upper, fore, -1), bend(...shoulder, ...J[hand], upper, fore, 1), release);
    }
    return J;
  }
  function drawPopUp(r, ox, oy, pose, pitch, amount, phase = 0) {
    const t = clamp(amount, 0, 1);
    const J = takeoffJoints(ox, oy, pose, pitch, t, phase);
    drawBoard(r, ox, oy, pitch * RAD, 1, pose.rail * smooth(t));
    drawBody(r, J, pitch, false, lerp(.88, 1.12, smooth(t)), lerp(.80, 1, smooth(t)), lerp(1, -1, smooth((t - .30) / .38)));
    return J;
  }
  /** Paddling and the pop-up share the same articulated body and board. */
  function drawPaddler(r, ox, oy, phase, plant, pitch = 0) {
    const J = paddlingJoints(ox, oy, pitch, phase, plant);
    drawBoard(r, ox, oy, pitch * RAD, 1, 0);
    drawBody(r, J, pitch, false, .88, .80, 1);
    return J;
  }
  /** Only the head and one waving arm above the water (a swimmer after a wipeout). */
  function drawSwimmer(r, ox, oy, phase) {
    drawHead(r, ox, oy - 4, -1, false);
    const w = Math.sin(phase);
    limb(r, [ox + 5, oy + 1], [ox + 9 + 2 * w, oy - 5], 4.4, 3.8, TONES.shirt); limb(r, [ox + 9 + 2 * w, oy - 5], [ox + 11 + 4 * w, oy - 12], 3.8, 3, TONES.skin); r.disc(Math.round(ox + 11 + 4 * w), Math.round(oy - 12), 2, S.skin);
    limb(r, [ox - 7, oy + 2], [ox + 6, oy + 2], 5, 5, TONES.shirt);
  }
  /** Blit a raster into the frame buffer: its pixel (0, 0) lands at (x0, y0); empty pixels next to a drawn one become the outline, and body pixels with nothing on their left catch the sunset's rim light. */
  function blitRaster(fb, r, x0, y0, palette, outline, rim) {
    const { w, h, buf } = r, ya = Math.max(0, r.minY - 1), yb = Math.min(h - 1, r.maxY + 1), xa = Math.max(0, r.minX - 1), xb = Math.min(w - 1, r.maxX + 1);
    for (let y = ya; y <= yb; y++) {
      const py = y0 + y;
      if (py < 0 || py >= LIM) continue;
      for (let x = xa; x <= xb; x++) {
        const px = x0 + x;
        if (px < 0 || px >= W) continue;
        const v = buf[y * w + x];
        if (v) fb[py * W + px] = rim && v <= S.shirtLight + 3 && (x === 0 || buf[y * w + x - 1] === 0) ? rim[v] : palette[v];
        else if (outline !== 0 && ((x > 0 && buf[y * w + x - 1]) || (x < w - 1 && buf[y * w + x + 1]) || (y > 0 && buf[(y - 1) * w + x]) || (y < h - 1 && buf[(y + 1) * w + x]))) fb[py * W + px] = outline;
      }
    }
  }

  /* ---- the ride: a loop of moves along the wave's face. There is NO rotation anywhere: he keeps the same stance (the camera follows him and the water streams past him), a turn is a
   *      curve of the path and a change of pose (low crouch with the rails in, hips leading and shoulders following), a jump goes straight up. A waypoint is {u, d} (along the
   *      surface line, how far into the water) or {dx, dy} (relative to where the move starts). Each move starts exactly where the last one ended, eases through its waypoints on a
   *      spline and gives the world a TARGET pose built from keyframes; the world lets the real pose follow that target joint by joint with a lag (hips first, then the torso, the
   *      head and the hands last), which is the overlap and follow-through. Every ride ends the way a real one does: swallowed by the foam of the tube and spat out, or a wipeout. */
  const PI = Math.PI;
  /** Keep the outstretched front hand and the board on screen without a hard stop in the path. */
  const BOARD_MIN_X = 151;                                                                           // 125 (the clock's right edge) + the board's half length (24) + its outline
  const keepInside = (x) => (x > 157 ? 157 + 7 * (1 - Math.exp(-(x - 157) / 7)) : x);
  function makeSurface(geom) {
    const path = makePath(spline(geom.line, 10)), L = path.length;
    return {
      path, L,
      /** The point at u along the line and d into the water (the normal to the line, pointing to the water, is (-ty, tx)). */
      at(u, d) { const s = clamp(u, -0.2, 1.2) * L, p = path.at(s), t = path.tangent(s); return [keepInside(p[0] - t[1] * d), p[1] + t[0] * d]; },
      slope(u) { const t = path.tangent(clamp(u, 0, 1) * L); return Math.atan2(-t[1], t[0]); },        // the line's angle above the horizontal (radians, up to the right)
    };
  }
  const M = (name, dur, wps, o) => Object.assign({ name, dur, wps }, o || {});
  const U = (u, d) => ({ u, d });
  const START = U(0.55, 14);                                                                         // where every ride starts and ends: high on the face, standing
  const MOVES = {
    drop: () => M('drop', 30, [U(0.5, 22), U(0.45, 29)], { pose: [[0, 'trim'], [0.2, 'anticipate'], [0.5, 'crouch'], [1, 'bottom']], ease: 0.6, snap: 1.5 }),
    bottom: () => M('bottom', 24, [U(0.4, 33), U(0.385, 31), U(0.42, 27)], { pose: [[0, 'bottom'], [0.58, 'bottom'], [1, 'pumpUp']], events: [[3, 'spray'], [10, 'spray']], snap: 1.3 }),
    pump: () => M('pump', 48, [U(0.45, 25), U(0.48, 21), U(0.51, 17)], { pose: [[0, 'pumpUp'], [0.14, 'pumpDown'], [0.34, 'pumpUp'], [0.54, 'pumpDown'], [0.76, 'pumpUp'], [1, 'trim']], events: [[15, 'spray'], [31, 'spray']], snap: 1.25 }),
    snap: () => M('snap', 20, [U(0.58, 13), U(0.61, 10), U(0.57, 15)], { pose: [[0, 'trim'], [0.28, 'top'], [0.55, 'top'], [1, 'bottom']], events: [[7, 'bigspray']], snap: 1.5 }),
    floater: () => M('floater', 28, [U(0.61, 11), U(0.58, 13)], { pose: [[0, 'top'], [0.25, 'floater'], [0.8, 'floater'], [1, 'trim']], events: [[4, 'spray'], [15, 'spray']] }),
    hang: () => M('hang', 66, [U(0.47, 24), U(0.43, 22)], { pose: [[0, 'trim'], [0.22, 'hangTen'], [0.8, 'hangTen'], [1, 'trim']], events: [[16, 'spray']] }),
    carve: () => M('carve', 30, [U(0.52, 20), U(0.56, 15), U(0.51, 21), U(0.45, 26)], { pose: [[0, 'trim'], [0.2, 'cutback'], [0.52, 'cutback'], [0.78, 'bottom'], [1, 'pumpUp']], events: [[6, 'spray'], [15, 'bigspray'], [23, 'spray']], snap: 1.35 }),
    airUp: () => M('airUp', 60, [{ dx: -1, dy: -4 }, { dx: -2, dy: -15 }, { dx: -3, dy: -20 }, { dx: -4, dy: -14 }, { dx: -5, dy: 0 }], { micro: 0.15, pose: [[0, 'anticipate'], [0.1, 'pop'], [0.3, 'airTuck'], [0.5, 'grab'], [0.68, 'extend'], [0.88, 'land'], [1, 'land']], events: [[1, 'spray'], [56, 'landing']], ease: 0.0, hang: 0.55, air: true, snap: 1.6 }),
    tubeIn: () => M('tubeIn', 42, [U(0.53, 15), U(0.57, 13), U(0.60, 12)], { pose: [[0, 'trim'], [0.3, 'crouch'], [0.75, 'barrelSet'], [1, 'barrel']], events: [[4, 'veil']], micro: 0.8, ease: 0.7 }),
    stall: () => M('stall', 54, [U(0.60, 12), U(0.62, 13), U(0.61, 12)], { pose: [[0, 'barrel'], [0.24, 'stall'], [0.48, 'barrelSet'], [0.72, 'stall'], [1, 'barrel']], hang: 0.8, micro: 0.65, events: [[22, 'spray']] }),
    drag: () => M('drag', 42, [U(0.60, 12), U(0.55, 14), U(0.5, 19), U(0.42, 24)], { pose: [[0, 'barrel'], [0.15, 'barrelSet'], [0.35, 'drag'], [0.68, 'drag'], [0.87, 'barrelDeep'], [1, 'barrel']], tm: 'accel', ease: 0, micro: 0.75, events: [[9, 'spray'], [24, 'spray']] }),
    pumpLow: () => M('pumpLow', 32, [U(0.42, 14), U(0.47, 12), U(0.53, 10), U(0.57, 10)], { pose: [[0, 'barrel'], [0.20, 'barrelUp'], [0.44, 'barrelDeep'], [0.68, 'barrelUp'], [0.88, 'barrelDeep'], [1, 'barrel']], micro: 0.55, events: [[7, 'spray'], [18, 'spray']] }),
    duck: () => M('duck', 40, [U(0.57, 10), U(0.58, 9), U(0.57, 10)], { pose: [[0, 'barrel'], [0.35, 'barrelDeep'], [0.65, 'duck'], [1, 'duck']], micro: 0.65, events: [[14, 'crash']] }),
    engulf: () => M('engulf', 30, [U(0.55, 14)], { kind: 'engulf', pose: [[0, 'exitTall']], events: [[1, 'engulf']] }),
    spit: () => M('spit', 18, [U(0.55, 14)], { pose: [[0, 'exitTall'], [0.55, 'exitTall'], [1, 'trim']], events: [[1, 'spit']] }),
    sunRun: () => M('sunRun', 42, [U(0.49, 23), U(0.41, 28), U(0.47, 23), START], {
      pose: [[0, 'bottom'], [.32, 'pumpUp'], [.52, 'exitTall'], [.78, 'trim'], [1, 'trim']],
      events: [[6, 'spray'], [18, 'bigspray']], ease: 0.26, micro: .18
    }),
    wobble: () => M('wobble', 26, [{ dx: -2, dy: -3 }, { dx: -3, dy: -1 }], { pose: [[0, 'top'], [0.2, 'fall1'], [0.4, 'fall2'], [0.6, 'fall1'], [0.8, 'fall2'], [1, 'fall1']], events: [[1, 'oops']], snap: 1.3 }),
    fall: () => M('fall', 36, [{ dx: 4, dy: -5 }, { dx: 8, dy: 4 }, { dx: 10, dy: 20 }], { kind: 'fall', pose: [[0, 'fall1'], [0.3, 'fall2'], [0.6, 'fallDrop'], [1, 'fallDrop']], ease: 0.0, snap: 1.2 }),
    under: () => M('under', 30, [{ dx: 1, dy: 2 }], { kind: 'under', events: [[1, 'splash']] }),
    swim: () => M('swim', 70, [{ dx: -4, dy: 0 }, { dx: -8, dy: 0 }], { kind: 'swim' }),
    paddle: () => M('paddle', 74, [U(0.45, 26), U(0.5, 20), U(0.55, 14)], { kind: 'paddle' }),
    popup: () => M('popup', 38, [U(.55, 14), U(.53, 17)], {
      kind: 'popup', pose: [[0, 'crouch'], [.76, 'crouch'], [1, 'trim']], events: [[28, 'takeoff']]
    }),
    settle: () => M('settle', 28, [U(0.50, 20), U(0.45, 26)], {
      kind: 'popup', pose: [[0, 'trim'], [.50, 'crouch'], [1, 'crouch']], ease: .7
    }),
  };
  const SEQUENCES = {
    tube: ['settle', 'paddle', 'popup', 'drop', 'bottom', 'pump', 'tubeIn', 'stall', 'drag', 'pumpLow', 'duck', 'engulf', 'spit', 'sunRun'],
    air: ['drop', 'bottom', 'pump', 'airUp', 'bottom', 'hang', 'floater', 'engulf', 'spit'],
    carve: ['drop', 'bottom', 'snap', 'floater', 'bottom', 'carve', 'pump', 'snap', 'engulf', 'spit'],
    wipeout: ['drop', 'bottom', 'pump', 'wobble', 'fall', 'under', 'swim', 'paddle', 'popup'],
  };
  const SEGMENTS = Object.fromEntries(Object.keys(SEQUENCES).map((k) => [k, SEQUENCES[k].map((n) => MOVES[n]())]));
  const VARIANTS = ['tube', 'air', 'carve', 'wipeout'];
  const TUBE_SHARE = 0.9;                                                                           // after any other ride the barrel comes next nine times in ten: about every second ride is a tube ride
  function posePick(frames, t) {
    if (frames.length === 1) return POSES[frames[0][1]];
    let i = 0;
    while (i < frames.length - 2 && t >= frames[i + 1][0]) i++;
    const a = frames[i], b = frames[i + 1], k = smooth((t - a[0]) / Math.max(1e-6, b[0] - a[0]));
    return blendPose(POSES[a[1]], POSES[b[1]], t <= a[0] ? 0 : t >= b[0] ? 1 : k);
  }
  function createRide(surface, rand, first) {
    const at0 = surface.at(START.u, START.d);
    const ride = { variant: first || 'tube', i: 0, t: 0, loops: 0, x: at0[0], y: at0[1], pose: Object.assign({}, POSES.trim), mode: 'stand', name: 'drop', snap: 1,
      board: { x: at0[0], y: at0[1], ang: 0, mode: 'attached', vx: 0, vy: 0, t: 0 }, from: null, path: null, hidden: false, last: null };
    ride.seg = () => SEGMENTS[ride.variant][ride.i];
    const resolve = (wp, from) => (wp.u !== undefined ? surface.at(wp.u, wp.d) : [keepInside(from[0] + wp.dx), from[1] + wp.dy]);
    function begin() {
      const seg = ride.seg(), from = [ride.x, ride.y], pts = [from];
      for (const wp of seg.wps) pts.push(resolve(wp, from));
      ride.mode = seg.kind || 'stand'; ride.name = seg.name; ride.snap = seg.snap || 1; ride.t = 0; ride.from = from;
      ride.hidden = seg.kind === 'under' || seg.kind === 'engulf';
      if (seg.kind === 'swim') { const b = ride.board; pts.length = 1; pts.push([(from[0] + b.x) / 2, (from[1] + b.y) / 2 + 1], [b.x + 2, b.y + 2]); }
      if (seg.kind === 'paddle') ride.board.mode = 'attached';
      if (seg.kind === 'popup') ride.board.mode = 'attached';
      if (seg.name === 'fall') { const b = ride.board; b.mode = 'flying'; b.x = from[0]; b.y = from[1] + 2; b.vx = -1.1; b.vy = -0.5; b.ang = 0; b.t = 0; }
      ride.path = makePath(spline(pts, 12));
    }
    begin();
    /** Advance one step; returns the surfer's target and the events of the step. */
    ride.step = function () {
      const seg = ride.seg(), events = [];
      ride.t++;
      for (const [at, name] of seg.events || []) if (ride.t === at) events.push(name);
      const u = clamp(ride.t / seg.dur, 0, 1), ease = seg.ease === undefined ? 0.5 : seg.ease;
      let p = ease > 0 ? lerp(u, smooth(u), ease) : u;
      if (seg.tm === 'accel') p = Math.pow(u, 1.7); else if (seg.tm === 'decel') p = 1 - Math.pow(1 - u, 1.7);
      if (seg.hang) p = u + seg.hang * Math.sin(2 * PI * u) / (2 * PI);                                  // a hold at the top of a jump: slow in the middle, quick at both ends
      const pos = ride.path.at(p * ride.path.length);
      if (seg.pose) ride.pose = posePick(seg.pose, u);
      ride.x = pos[0]; ride.y = pos[1];
      const b = ride.board;
      if (b.mode === 'flying') {
        b.t++; b.x += b.vx; b.y += b.vy; b.vy += 0.15; b.vx *= 0.985; b.ang += (-0.35 - b.ang) * 0.05;
        if (b.x < BOARD_MIN_X) { b.x = BOARD_MIN_X; b.vx = Math.max(0, b.vx); }                          // a board never drifts under the page's date and clock
        if (b.t > 12 && b.y >= ride.surfaceY(b.x)) { b.mode = 'float'; b.t = 0; events.push('boardsplash'); }
      } else if (b.mode === 'float') {
        b.t++; b.ang += (0.12 - b.ang) * 0.1; b.y += Math.sin(b.t * 0.12) * 0.12; b.x += 0.05;
      } else { b.x = ride.x; b.y = ride.y; }
      let ended = false, uOut = u;
      if (ride.t >= seg.dur) {
        uOut = 0;                                                                                          // the next move starts: its name, its mode and its progress agree on the same step
        ride.i++;
        if (ride.i >= SEGMENTS[ride.variant].length) {
          ride.i = 0; ride.loops++;
          const others = VARIANTS.filter((v) => v !== 'tube' && v !== ride.variant);                                                       // never the same ride twice (so never two wipeouts in a row either)
          ride.last = ride.variant; ride.variant = ride.variant !== 'tube' && rand() < TUBE_SHARE ? 'tube' : others[Math.floor(rand() * others.length) % others.length]; ended = true;
        }
        begin();
      }
      return { x: ride.x, y: ride.y, pose: ride.pose, mode: ride.mode, name: ride.name, events, hidden: ride.hidden, board: ride.board, ended, air: !!ride.seg().air, snap: ride.snap, u: uOut, micro: ride.seg().micro === undefined ? 0.6 : ride.seg().micro };
    };
    ride.surfaceY = (x) => { const p = surface.path.points; let best = p[0][1]; for (const q of p) if (q[0] >= x) { best = q[1]; break; } return best + 5; };
    return ride;
  }
  /** The board's pitch (degrees, nose up) for a velocity (art pixels per step): up is nose up, down is nose down; `limit` keeps it from standing on its end. */
  const pitchFor = (vx, vy, limit = 38) => clamp(Math.atan2(-vy, Math.max(0.12, Math.abs(vx))) / RAD, -limit, limit);
  /** Quantise an angle to steps of 5 degrees with hysteresis, so the board never flickers between two pixel patterns. */
  const quantise = (angle, current) => (Math.abs(angle - current) > 3.8 ? Math.round(angle / 5) * 5 : current);
  /** How fast each joint of the pose follows its target (the share of the gap closed in a step): the hips first, the torso, then the head, the hands last. */
  const FOLLOW = { hx: 0.34, hy: 0.32, lean: 0.24, head: 0.15, fx: 0.18, fy: 0.17, bx: 0.13, by: 0.13, rail: 0.26, ffx: 0.42, bfx: 0.42 };
  function followPose(current, target, boost) {
    for (const k of POSE_KEYS) current[k] += (target[k] - current[k]) * Math.min(0.7, FOLLOW[k] * boost);
    return current;
  }

  /* ---- foam brushes: ragged, streaky blobs of tone and alpha made from noise (never round bubbles); drawn in the foam colours. The atlas may bring its own (scripts/prepare_game_surf.py). */
  function makeBrush(noise, w, h, style, seed) {
    const tone = new Uint8Array(w * h), alpha = new Uint8Array(w * h);
    const sx = style === 'streak' ? 0.07 : style === 'sheet' ? 0.09 : 0.2, sy = style === 'streak' ? 0.55 : style === 'sheet' ? 0.5 : 0.26;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const nx = (x + 0.5) / w * 2 - 1, ny = (y + 0.5) / h * 2 - 1;
        const env = style === 'streak' ? 1 - (Math.abs(nx) ** 2.2 * 0.8 + ny * ny * 1.1) : style === 'sheet' ? 1 - (nx * nx * 0.7 + Math.abs(ny) ** 1.6 * 1.3) : 1 - (nx * nx * 0.95 + ny * ny * 1.25);
        const v = noise.fbm(x * sx + seed * 7.3, y * sy + seed * 3.1, 3), tail = style === 'streak' ? 0.18 * (nx + 1) * 0.5 : 0;     // streaks fade out toward their tail (the right)
        const m = env * 1.0 + (v - 0.5) * 1.4 - tail;
        if (m <= 0.08) continue;
        const edge = clamp(1 - m * 2.1, 0, 1), lace = noise.fbm(x * 0.55 + seed * 2.3, y * 0.75 + seed * 1.7, 2);       // the rim is eaten into lace, the core stays whole
        if (lace < 0.22 + 0.46 * edge) continue;
        alpha[y * w + x] = m > 0.55 ? 255 : m > 0.3 ? 200 : 120;
        tone[y * w + x] = BYTE(110 + 160 * clamp((m - 0.08) / 0.7, 0, 1) - (ny > 0.4 ? 30 : 0) - (lace < 0.4 ? 34 : 0) + (noise(x * 0.5, y * 0.5 + seed) - 0.5) * 30);
      }
    }
    return { w, h, tone, alpha };
  }
  function makeBrushes(noise) {
    const set = (style, sizes) => sizes.map(([w, h], i) => makeBrush(noise, w, h, style, i + style.length));
    return { puff: set('puff', [[9, 7], [14, 10], [21, 13], [30, 17]]), streak: set('streak', [[13, 4], [20, 5], [32, 6], [48, 7]]), sheet: set('sheet', [[18, 6], [28, 8], [40, 10]]) };
  }
  /** Brushes from the optional atlas (foam-puff-N, foam-streak-N, foam-sheet-N: tone in red, alpha in alpha), or null. `pixels` is the atlas as {width, data}. */
  function readAtlasBrushes(json, pixels) {
    try {
      if (!json || !json.frames || typeof json.frames !== 'object' || !pixels || !pixels.data) return null;
      const out = { puff: [], streak: [], sheet: [] };
      for (const style of Object.keys(out)) {
        for (let i = 0; i < 12; i++) {
          const f = json.frames[`foam-${style}-${i}`];
          if (!f) break;
          if (!okFrame(f) || f[2] > 64 || f[3] > 64 || f[0] + f[2] > pixels.width || (f[1] + f[3]) * pixels.width * 4 > pixels.data.length) return null;
          const [x, y, w, h] = f, tone = new Uint8Array(w * h), alpha = new Uint8Array(w * h);
          for (let yy = 0; yy < h; yy++) for (let xx = 0; xx < w; xx++) { const p = ((y + yy) * pixels.width + x + xx) * 4; tone[yy * w + xx] = pixels.data[p]; alpha[yy * w + xx] = pixels.data[p + 3]; }
          out[style].push({ w, h, tone, alpha });
        }
      }
      return out.puff.length && out.streak.length && out.sheet.length ? out : null;
    } catch (e) { return null; }
  }
  /** The foam colours for a brush tone (0-255): 32 steps from translucent aqua to white. */
  function buildFoamLut() {
    const lut = new Uint32Array(32), stops = [[0, rgb('#187ca8')], [0.45, rgb('#68dcf0')], [0.8, rgb('#dffbff')], [1, rgb('#fffbf0')]];
    for (let i = 0; i < 32; i++) {
      const t = i / 31; let k = 1; while (k < stops.length - 1 && t > stops[k][0]) k++;
      lut[i] = pack(mixRgb(stops[k - 1][1], stops[k][1], clamp((t - stops[k - 1][0]) / (stops[k][0] - stops[k - 1][0]), 0, 1)));
    }
    return lut;
  }
  /** Draw a brush with its top left corner at (x, y); `a` is how opaque the whole brush is (0-256); `flip` mirrors it left to right. */
  function drawBrush(fb, b, x, y, a, foamLut, flip, height = b.h) {
    const plume = height > b.h, middle = (b.w - 1) / 2;
    for (let yy = 0; yy < height; yy++) {
      const sourceRow = Math.floor(yy * b.h / height);
      const depth = yy / height;
      const reach = plume ? middle * (.32 + .69 * depth + .12 * Math.sin(yy * .74 + x * .37)) : middle;
      const lift = plume ? Math.round(3 * (1 - depth) + Math.sin(yy * .5)) : 0;
      const density = plume ? a * smooth(depth / .25) : a;
      for (let xx = 0; xx < b.w; xx++) {
        const j = sourceRow * b.w + (flip ? b.w - 1 - xx : xx), al = b.alpha[j];
        if (al === 0) continue;
        const edge = plume ? clamp((reach - Math.abs(xx - middle) + 1) / 3, 0, 1) : 1;
        putA(fb, x + xx + lift, y + yy, foamLut[b.tone[j] >> 3], (al * density * edge) >> 8);
      }
    }
  }

  /* ---- gulls: a body, a head and beak, and two wings that are each an upper wing and a hand; the hand lags the upper wing, so a stroke runs along the wing like a real flap.
   *      They flap for a few strokes, then glide with the wings in a soft M; they cross the sky slowly. Against the sunset they are silhouettes with a warm rim. */
  const GULL_LANES = [{ y: 46, span: 17, speed: 0.34 }, { y: 62, span: 14, speed: 0.28 }, { y: 84, span: 10, speed: 0.22 }];
  const GULL_MAX_Y = 112, GULL_TURN = 150;
  function makeGull(rand, i) {
    const lane = GULL_LANES[i % GULL_LANES.length], dir = i % 2 ? -1 : 1;
    return { x: dir > 0 ? -16 - Math.round(rand() * 120) : W + 16 + Math.round(rand() * 120), base: lane.y + Math.round(rand() * 3), y: lane.y, dir, span: lane.span, speed: lane.speed * (0.9 + rand() * 0.2), acc: 0,
      phase: rand() * 6.28, mode: rand() < 0.5 ? 'flap' : 'glide', timer: 30 + Math.floor(rand() * 60), amp: 0.5, bob: rand() * 6.28, poked: false, lane: i % GULL_LANES.length };
  }
  /** The wing angles (radians above the horizontal) for a flap phase and amplitude (1 flapping, about 0.1 gliding): the upper wing, the hand that follows it a little later, and the far wing. */
  function wingAngles(phase, amp) {
    const flapIn = 0.06 + 0.78 * Math.sin(phase), flapOut = 0.98 * Math.sin(phase - 1.0), flapFar = 0.06 + 0.74 * Math.sin(phase - 0.2);
    const glideIn = 0.3, glideOut = -0.14, glideFar = 0.28;                                                          // gliding: a soft M
    return { inner: lerp(glideIn, flapIn, amp), outer: lerp(glideOut, flapOut, amp), far: lerp(glideFar, flapFar, amp), farOuter: lerp(glideOut + 0.05, 0.9 * Math.sin(phase - 1.1), amp) };
  }
  const GULL_YAW = 0.95;                                                                                              // radians: seen from the side but turned a little toward us, so both wings show
  /** The points of a gull (screen pixels, not rounded): the body (tail, head, beak) and two wings as [shoulder, elbow, tip]. */
  function gullShape(g) {
    const d = g.dir, L = g.span * 0.62, a = wingAngles(g.phase, g.amp), x = g.x, y = g.y, sy = Math.sin(GULL_YAW), cy = Math.cos(GULL_YAW), body = g.span * 0.42 * cy;
    const wing = (shoulder, side, ai, ao, k) => {
      const seg = (from, theta, len) => [from[0] - d * side * sy * Math.cos(theta) * len, from[1] - Math.sin(theta) * len];
      const e = seg(shoulder, ai, 0.46 * L * k);
      return [shoulder, e, seg(e, ao, 0.54 * L * k)];
    };
    const sh = [x + d * body * 0.1, y - 0.6];
    return { tail: [x - d * body * 0.5, y + 0.4], rump: [x - d * body * 0.2, y], head: [x + d * body * 0.5, y - 0.5], beak: [x + d * (body * 0.5 + 2), y - 0.2],
      near: wing(sh, 1, a.inner, a.outer, 1), far: wing([sh[0] + d * 0.5, sh[1] - 0.4], -1, a.far, a.farOuter, 0.9) };
  }
  function stepGull(g, time) {
    g.acc += g.speed; while (g.acc >= 1) { g.acc -= 1; g.x += g.dir; }
    if (--g.timer <= 0) { g.mode = g.mode === 'flap' ? 'glide' : 'flap'; g.timer = g.mode === 'flap' ? 55 + Math.floor((g.span * 7) % 50) : 40 + Math.floor((g.span * 11) % 45); }
    g.amp += ((g.mode === 'flap' ? 1 : 0.12) - g.amp) * 0.07;
    g.phase += 0.2 + 0.3 * g.amp;                                                                                          // 0.5 rad a step flapping (about 2.4 beats a second), slow while gliding
    g.y = Math.min(GULL_MAX_Y, g.base + 1.9 * Math.sin(time * 0.8 + g.bob) - 0.9 * g.amp * Math.cos(g.phase));
  }

  /* ---- the world: everything that moves, in logic only (no pixels) */
  /** For the columns of the open tube mouth: the lowest row of the lip above it (the veil hangs from there) and the first row of the wave's face below it (the veil lands there). */
  function computeColumns(back) {
    const { cls, geom } = back, [hx, , rx] = geom.hole, x0 = Math.max(0, Math.floor(hx - rx)), x1 = Math.min(W - 1, Math.ceil(hx + rx)), arch = new Int16Array(W).fill(-1), floor = new Int16Array(W).fill(-1);
    for (let x = x0; x <= x1; x++) {
      let y = 0;
      while (y < H && cls[y * W + x] !== CLS.WATER) y++;
      if (y >= H) continue;
      while (y < H && cls[y * W + x] === CLS.WATER) y++;
      arch[x] = y;                                                                      // the first row below the lip
      let f = y; while (f < H && cls[f * W + x] !== CLS.WATER) f++;
      floor[x] = f < H ? f : -1;
    }
    return { arch, floor, x0, x1 };
  }

  /** What a body does on top of the pose it is aiming for: it breathes, the knees take the chop (more when he is fast), the arms counter-balance the sway of the torso and the head stays
   *  level while the torso moves; and the line asks something of him: at the bottom of a turn (the speed along the face changes sign) he is pressed into the board and compresses, while the
   *  line falls away he is a little lighter. `amp` is the move's share of all this, `flow` how fast he goes (0 to 1), `comp` the line's pressure (-1 to 1). Returns a new pose. */
  function dress(t, tt, amp, flow, comp) {
    const o = Object.assign({}, t), breath = Math.sin(tt * 0.075), sway = Math.sin(tt * 0.047 + 1.3), chop = Math.sin(tt * 0.40) * Math.sin(tt * 0.17 + 0.7), fast = 0.6 + 1.0 * flow;
    const balance = Math.sin(tt * .22 - 1.7) * Math.sin(tt * .073);
    const lean = amp * (1.8 * sway + .8 * breath + 1.8 * chop) + 5.2 * comp;
    o.hy += FS * (amp * (0.3 * breath + 2.55 * fast * (0.5 + 0.5 * chop)) + 0.65 * comp);
    o.hx += FS * amp * (.65 * sway + .38 * balance) - .95 * comp;
    o.lean += lean; o.head -= lean * 0.78;
    o.fx += FS * amp * (.92 * sway + .52 * balance) - .35 * comp;
    o.fy += FS * amp * (.72 * breath - .62 * balance) + .55 * comp;
    o.bx -= FS * amp * (.96 * sway + .34 * balance) - .45 * comp;
    o.by += FS * amp * (.82 * chop + .68 * balance) - .55 * comp;
    return o;
  }
  function createWorld(options) {
    const o = Object.assign({ seed: 20261110, random: null, back: null, current: null, first: 'tube', goldList: [] }, options);
    const rand = typeof o.random === 'function' ? o.random : seeded(o.seed);
    const back = o.back || makeBackdrop(rand), geom = back.geom, surface = makeSurface(geom);
    const world = {
      rand, back, geom, surface, steps: 0, time: 0, columns: computeColumns(back), ride: createRide(surface, rand, o.first),
      surfer: { x: 0, y: 0, pose: Object.assign({}, POSES.trim), pitch: 0, pitchQ: 0, vx: 0, vy: 0, mode: 'stand', name: 'drop', hidden: false, hop: 0, u: 0, ax: 0, ay: 0 },
      veil: { state: 'idle', t: 0 }, particles: [], foamItems: [], wake: [], wakeTouch: false, wakeGroup: 0, ripples: [], gulls: [], birds: [], clouds: [], stars: [], sparkles: [], glints: [], boat: null, bubbles: [], events: [], paddle: 0, gold: [], twinkles: [], surge: 0, phase: 0, flow: 0, mist: [], shake: null, dolphin: { cur: null, next: 900 }, star: { t: -1, next: 520, x: 0, y: 0, vx: 0, vy: 0 }, flock: { on: false, next: 760, x: 0, y: 80, dir: 1, speed: 0.25, near: false },
    };
    world.surfer.x = world.ride.x; world.surfer.y = world.ride.y;
    // the sky: stars where the sky is dark, clouds that drift over the sky only, gulls, tiny far birds, a sailboat on the horizon
    const skyDark = [];
    for (let y = 4; y < Math.min(70, geom.horizon - 30); y++) for (let x = 2; x < W - 2; x++) { const i = y * W + x, v = back.rgb[i]; if (back.cls[i] === CLS.SKY && (v & 255) + ((v >> 8) & 255) + ((v >> 16) & 255) < 330 && (y + x) % 3 === 0) skyDark.push(i); }
    for (let k = 0; k < 44 && skyDark.length; k++) {
      const i = skyDark[Math.floor(rand() * skyDark.length)];
      world.stars.push({ x: i % W, y: (i / W) | 0, big: rand() < 0.2, period: 40 + Math.floor(rand() * 70), phase: Math.floor(rand() * 90), tw: rand() < 0.35 });
    }
    for (let i = 0; i < 3; i++) { const g = makeGull(rand, i); g.x = [20, 64, 104][i]; world.gulls.push(g); }                    // the first three are already in the sky when the scene opens
    for (let i = 0; i < 3; i++) world.birds.push({ x: 20 + Math.round(rand() * 80), y: 70 + Math.round(rand() * 30), dir: i % 2 ? -1 : 1, speed: 0.12 + rand() * 0.1, acc: 0, phase: rand() * 6.28 });
    for (let i = 0; i < 7; i++) world.clouds.push(i < 3 ? { x: Math.round(rand() * W), y: 12 + Math.round(i * 14 + rand() * 6), kind: 3 + (i % 2), speed: 0.09 + rand() * 0.06, acc: 0 } : { x: Math.round(rand() * W), y: 52 + Math.round((i - 3) * 13 + rand() * 6), kind: i % 3, speed: 0.03 + rand() * 0.04, acc: 0 });
    world.craft = makeCraft(geom); world.gold = o.goldList;

    const spray = (x, y, n, power, up = 1, dir = 0) => {
      for (let k = 0; k < n && world.particles.length < 240; k++) world.particles.push({ x, y, vx: (rand() - 0.5) * power + dir * 0.6 * power * rand(), vy: -(0.4 + rand() * 1.5) * up * (0.6 + power * 0.4), g: 0.075, life: 16 + Math.floor(rand() * 16), age: 0, big: rand() < 0.22, warm: rand() < 0.45 });
    };
    const puff = (style, x, y, vx, vy, life, layer, gain, cap) => { if (world.foamItems.length < 90) world.foamItems.push({ style, x, y, vx, vy, age: 0, life, layer, flip: rand() < 0.5, gain: gain || 0.94, cap: cap === undefined ? 9 : cap }); };
    world.spray = spray; world.puff = puff;
    const veilEvent = (name) => {
      const v = world.veil;
      if (name === 'veil') { v.state = 'throw'; v.t = 0; }
      if (name === 'crash') {
        v.state = 'crash'; v.t = 0;
        const s = world.surfer, c = world.columns;
        for (let k = 0; k < 14; k++) { const x = lerp(c.x0 + 10, c.x1 - 6, rand()), y = c.floor[Math.round(x)] > 0 ? c.floor[Math.round(x)] : 160; puff(k % 4 === 0 ? 'sheet' : 'puff', x, y - 4 + (rand() - 0.5) * 8, (rand() - 0.5) * 0.4, -0.1 - rand() * 0.2, 46 + Math.floor(rand() * 30), k % 2 ? 'front' : 'back'); }
        spray(s.x - 6, s.y - 8, 30, 2.2);
      }
    };
    const handle = (name) => {
      const s = world.surfer, face = -1;                                                                               // the tail is behind him, on the right
      const [tx, tailY] = boardPoint(s, 15, boardHalfWidth(15) + 0.5), ty = tailY + 2;
      if (name === 'spray') spray(tx, ty, 14, 1.75, 1.15, -face);
      else if (name === 'takeoff') spray(tx, ty, 13, 1.75, .65, -face);
      else if (name === 'bigspray') { spray(tx, ty - 2, 38, 2.75, 1.35, -face); puff('puff', tx, ty - 2, -face * 0.24, -0.14, 26, 'front', 0.72, 1); puff('puff', tx - face * 7, ty, -face * 0.28, -0.06, 24, 'front', 0.62, 0); }
      else if (name === 'landing') { world.shake = { t: 0, amp: 1.1 }; spray(s.x + 2, s.y + 5, 24, 2.05, 1.15, 0.35); puff('puff', s.x, s.y + 8, 0, -0.08, 26, 'front'); world.ripples.push({ x: Math.round(s.x), y: Math.round(s.y + 10), age: 0 }); }
      else if (name === 'splash') {
        world.shake = { t: 0, amp: 1.6 };
        spray(s.x, s.y + 4, 46, 2.8); puff('puff', s.x - 6, s.y + 4, -0.1, -0.12, 34, 'front'); puff('puff', s.x + 8, s.y + 5, 0.1, -0.1, 34, 'front'); puff('sheet', s.x, s.y + 8, 0, -0.05, 44, 'front');
        for (let k = 0; k < 3; k++) world.ripples.push({ x: Math.round(s.x), y: Math.round(s.y + 8), age: -k * 5 });
        world.bubbles.length = 0; for (let k = 0; k < 8; k++) world.bubbles.push({ x: s.x + (rand() - 0.5) * 14, y: s.y + 8 + rand() * 6, vy: -0.18 - rand() * 0.2, age: 0, life: 24 + Math.floor(rand() * 20) });
      } else if (name === 'boardsplash') { const b = world.ride.board; spray(b.x, b.y + 2, 18, 1.8); world.ripples.push({ x: Math.round(b.x), y: Math.round(b.y + 4), age: 0 }); puff('puff', b.x, b.y + 4, 0, -0.08, 24, 'front'); }
      else if (name === 'veil' || name === 'crash') veilEvent(name);
      else if (name === 'engulf') {                                                                                 // the tube swallows him: a cloud of foam and mist hides him
        for (let k = 0; k < 9; k++) puff(k % 3 === 0 ? 'sheet' : 'puff', s.x + (rand() - 0.5) * 30, s.y - 6 + (rand() - 0.5) * 24, (rand() - 0.5) * 0.3, -0.06 - rand() * 0.1, 56 + Math.floor(rand() * 24), 'front', 0.95, 3);
        spray(s.x, s.y - 4, 26, 2.2); world.shake = { t: 0, amp: 1.2 };
      } else if (name === 'spit') {                                                                                 // the broken foam opens onto his exit
        for (const q of world.foamItems) if (q.layer === 'front' && q.style !== 'streak' && Math.hypot(q.x-s.x,q.y-s.y)<26) {
          q.layer = 'back';
          q.life = Math.min(q.life, q.age + 13);
        }
        for (let k = 0; k < 6; k++) puff(k % 3 === 0 ? 'sheet' : 'puff', s.x + (rand() - 0.5) * 18,
          s.y + 6 + (rand() - 0.5) * 8, (rand() - 0.5) * 0.29, -0.06 - rand() * 0.1, 22 + Math.floor(rand() * 16), 'back', 0.62, 2);
        spray(s.x, s.y, 23, 2.2, 1.05, 1);
      }
    };
    world.step = function () {
      world.steps++; world.time += STEP;
      const t = world.time, st = world.steps, s = world.surfer;
      world.phase += 1 + 1.3 * world.surge + 0.8 * world.flow;                                                      // the water runs faster when he is fast: he travels along the wave
      // the surfer's pose follows the ride's target with a lag (the overlap); a touch adds a little hop with a grab
      const r = world.ride.step(), px = s.x, py = s.y;
      s.x = r.x; s.y = r.y; s.mode = r.mode; s.name = r.name; s.hidden = r.hidden; s.u = r.u; s.air = !!r.air;
      let target = r.pose, boost = r.snap;
      if (s.hop > 0) { s.hop--; const k = 1 - s.hop / HOP.length; target = k < 0.2 ? POSES.anticipate : k < 0.35 ? POSES.pop : k < 0.8 ? POSES.grab : POSES.land; boost = 1.8; }
      if (!s.hidden && s.mode === 'stand' && r.micro > 0 && s.hop === 0) target = dress(target, st, r.micro, world.flow, clamp(-s.ay * 14, -1, 1));
      followPose(s.pose, target, boost);
      if (s.hidden) Object.assign(s.pose, r.pose);                                                                  // out of sight he is already in the pose he will come out in
      if (r.mode === 'popup' && r.name !== 'settle' && r.u < 0.36) Object.assign(s.pose, POSES.crouch);
      const ovy = s.vy;
      s.vx += ((s.x - px) - s.vx) * 0.25; s.vy += ((s.y - py) - s.vy) * 0.25;
      s.ay += ((s.vy - ovy) - s.ay) * 0.25;
      world.flow += ((s.hidden ? 0.3 : clamp(Math.hypot(s.vx, s.vy) / 1.3, 0, 1)) - world.flow) * 0.06;
      if (s.mode === 'paddle' || s.mode === 'popup') {
        const targetPitch = s.mode === 'paddle' ? 0 : pitchFor(s.vx, s.vy, 12) * smooth(r.u);
        s.pitch += (targetPitch - s.pitch) * 0.14; s.pitchQ = quantise(s.pitch, s.pitchQ);
      } else if (s.mode === 'stand') { s.pitch += (pitchFor(s.vx, s.vy, r.air || s.hop > 0 ? 16 : 30) - s.pitch) * 0.14; s.pitchQ = quantise(s.pitch, s.pitchQ); }
      else if (s.mode === 'fall') { s.pitch += (0 - s.pitch) * 0.1; s.pitchQ = quantise(s.pitch, s.pitchQ); }
      for (const e of r.events) handle(e);
      if (s.mode === 'paddle') {
        const prevV = Math.sin(world.paddle);
        world.paddle += 0.36;
        const currV = Math.sin(world.paddle);
        // Each hand slices into the wave near the nose as it starts its power pull.
        if (!s.hidden && s.u > 0.10 && s.u < 0.72) {
          if (prevV <= 0 && currV > 0) {
            const [hx, hy] = boardPoint(s, -11, boardHalfWidth(-11) + 5.5);
            spray(hx, hy + 1, 4, 1.05, 0.75, 0.65);
          } else if (prevV >= 0 && currV < 0) {
            const [hx, hy] = boardPoint(s, -11, -boardHalfWidth(-11) - 5.5);
            spray(hx, hy + 1, 4, 1.05, 0.75, 0.65);
          }
        }
      }
      // A new contact starts a new trail; jumps must not connect two separate wakes.
      const touching = !s.hidden && ['stand', 'paddle', 'popup'].includes(s.mode) && !boardAirborne(s);
      if ((s.mode === 'stand' || s.mode === 'popup') && !s.hidden) {
        const [tx, tailY] = boardPoint(s, 17, boardHalfWidth(17) + 0.5), ty = tailY + 2, rail = s.pose.rail, rate = 0.42 + rail * 0.55 + Math.abs(s.vy) * 0.48;
        if (s.mode === 'stand' && rand() < rate && touching) {
          const count = 2 + (rail > 0.4 ? 1 : 0) + (rail > 0.7 ? 2 : 0);
          spray(tx, ty, count, 1.35 + rail * 1.15, 1.30, 1.35);
        }
      }
      if (touching) {
        if (!world.wakeTouch) world.wakeGroup++;
        // A sample each frame keeps the fast-moving water connected on turns.
        const [x, y] = boardPoint(s, 17, boardHalfWidth(17) + 0.5);
        const strength = s.mode === 'paddle' ? .15 : s.mode === 'popup' ? .38 : Math.min(1, .50 + .29 * s.pose.rail + .24 * world.flow);
        world.wake.push({ x, y: y + 4, age: 0, group: world.wakeGroup, id: st, strength });
        if (world.wake.length > WAKE_MAX) world.wake.shift();
      }
      world.wakeTouch = touching;
      // It first leaves the tail, then rides the wave's counter-clockwise flow.
      const [wakeCx, wakeCy] = geom.centre, wakeSpeed = 2.75 + 0.25 * world.flow + 0.15 * world.surge;
      for (const w of world.wake) {
        w.age++;
        const dx = w.x - wakeCx, dy = w.y - wakeCy, radius = Math.hypot(dx, dy) || 1;
        const launch = 1 - smooth((w.age - 3) / 6);
        const x = Math.round(w.x), y = Math.round(w.y), index = y * W + x;
        const local = o.current && x >= 0 && x < W && y >= 0 && y < H && (o.current.x[index] || o.current.y[index]);
        const vx = local ? o.current.x[index] / 127 : dy / radius;
        const vy = local ? o.current.y[index] / 127 : -dx / radius;
        w.x += .85 * launch + wakeSpeed * vx * (1 - launch);
        w.y += -.35 * launch + wakeSpeed * vy * (1 - launch);
      }
      world.wake = world.wake.filter((w) => w.age < WAKE_LIFE);
      const v = world.veil, c = world.columns;
      v.t++;
      if (v.state === 'throw') {
        if (v.t > 70) { v.state = 'idle'; v.t = 0; }
      } else if (v.state === 'crash') { if (v.t > 50) { v.state = 'idle'; v.t = 0; } if (v.t < 30 && st % 3 === 0) { const x = lerp(c.x0 + 12, c.x1 - 8, rand()); puff('streak', x, (c.floor[Math.round(x)] > 0 ? c.floor[Math.round(x)] : 160) - 3, -(0.2 + rand() * 0.2), 0.12, 50, 'back', 0.8); } }
      // Wind whips fine golden-lit spray off the top of the curling crest.
      const lip = geom.lip;
      if (rand() < 0.42 + 0.52 * world.surge) {
        const p = lip[Math.floor(rand() * lip.length * .76)];
        const offshore = p[1] < 92 && rand() < 0.62;
        world.particles.push({
          x: p[0] + (rand() - 0.5) * 4, y: p[1] + (rand() - 0.5) * 3,
          vx: offshore ? 0.36 + rand() * 0.58 : -0.52 - rand() * 0.46,
          vy: offshore ? -0.38 - rand() * 0.34 : -0.26 + rand() * 0.20,
          g: offshore ? 0.016 : 0.014, life: 18 + Math.floor(rand() * 18), age: 0,
          big: rand() < 0.24, warm: offshore || rand() < 0.65,
        });
      }
      if (st % 3 === 0 && world.gold.length && world.twinkles.length < 10) { const i = o.goldList[Math.floor(rand() * o.goldList.length)]; if (i !== undefined) world.twinkles.push({ x: i % W, y: (i / W) | 0, age: 0, life: 14 }); }
      for (const q of world.twinkles) q.age++;
      world.twinkles = world.twinkles.filter((q) => q.age < q.life);
      for (const q of world.particles) {
        q.age++;
        q.x += q.vx;
        q.y += q.vy;
        q.vy += q.g;
      }
      world.particles = world.particles.filter((q) => q.age < q.life && q.y < H);
      const drift = 1 + .7 * world.flow;
      for (const q of world.foamItems) {
        q.age++;
        q.x += q.vx * drift;
        q.y += q.vy * drift;
      }
      world.foamItems = world.foamItems.filter((q) => q.age < q.life);
      for (const rp of world.ripples) rp.age++;
      world.ripples = world.ripples.filter((rp) => rp.age < 28);
      for (const b of world.bubbles) { b.age++; b.y += b.vy; }
      world.bubbles = world.bubbles.filter((b) => b.age < b.life);
      // sparkles on the sea's path and the lip: a few at a time
      if (st % 5 === 0 && world.sparkles.length < 16) {
        const sun = geom.sun, y = geom.horizon + 2 + Math.floor(rand() * 40), spread = 4 + (y - geom.horizon) * 0.5;
        world.sparkles.push({ x: Math.round(sun.x + (rand() * 2 - 1) * spread), y, age: 0, life: 7 + Math.floor(rand() * 8), big: rand() < 0.3, lip: false });
      }
      if (st % 24 === 0 && world.glints.length < 5) { const p = lip[Math.floor(rand() * lip.length)]; world.glints.push({ x: Math.round(p[0] + (rand() - 0.5) * 6), y: Math.round(p[1] + (rand() - 0.5) * 4), age: 0, life: 12 }); }
      for (const q of world.sparkles) q.age++;
      world.sparkles = world.sparkles.filter((q) => q.age < q.life);
      for (const q of world.glints) q.age++;
      world.glints = world.glints.filter((q) => q.age < q.life);
      // the sky
      for (const g of world.gulls) {
        stepGull(g, t);
        if (g.poked) { if ((g.dir > 0 && g.x > W + 18) || (g.dir < 0 && g.x < -18)) g.dead = true; }
        else if ((g.dir > 0 && g.x > GULL_TURN) || (g.dir < 0 && g.x < -18)) { g.dir = -g.dir; g.base = GULL_LANES[g.lane].y + Math.round(rand() * 3); g.mode = rand() < 0.5 ? 'flap' : 'glide'; }       // they fly over the left sky and turn round out of sight behind the wave
      }
      world.gulls = world.gulls.filter((g) => !g.dead);
      for (const b of world.birds) { b.acc += b.speed; b.phase += 0.16; while (b.acc >= 1) { b.acc -= 1; b.x += b.dir; } if (b.x < -8) b.dir = 1; if (b.x > GULL_TURN) b.dir = -1; }
      for (const cl of world.clouds) { cl.acc += cl.speed; while (cl.acc >= 1) { cl.acc -= 1; cl.x += 1; } if (cl.x > W + 40) { cl.x = -60 - Math.round(rand() * 40); cl.kind = cl.y < 50 ? 3 + Math.floor(rand() * 2) : Math.floor(rand() * 3); } }
      stepExtras(world, rand, handle);
    };
    world.seek = function (steps) { for (let i = 0; i < steps; i++) world.step(); };
    /** A touch at picture coordinates: the surfer hops and grabs his board, the water splashes, or a gull takes off from the sky. */
    world.poke = function (x, y) {
      const s = world.surfer;
      if (!s.hidden && Math.hypot(x - s.x, y - (s.y - 12)) < 26) { if (s.hop === 0 && s.mode === 'stand') { s.hop = HOP.length; spray(s.x, s.y + 2, 16, 1.6); puff('puff', s.x + 8, s.y + 4, 0.2, -0.1, 24, 'front'); } return 'surfer'; }
      if (y >= geom.horizon - 3 && back.cls[clamp(Math.round(y), 0, H - 1) * W + clamp(Math.round(x), 0, W - 1)] !== CLS.SKY) {
        if (world.ripples.length < 6) world.ripples.push({ x: Math.round(x), y: Math.round(y), age: 0 });
        spray(x, y, 14, 1.3); puff('puff', x - 4, y - 3, 0, -0.1, 24, 'front');
        return 'splash';
      }
      if (world.gulls.filter((g) => g.poked).length < 2) world.gulls.push({ x: Math.round(x), base: clamp(Math.round(y), 30, GULL_MAX_Y), y, dir: x > W / 2 ? 1 : -1, span: 13, speed: 0.9, acc: 0, phase: 0, mode: 'flap', timer: 1e6, amp: 1, bob: 0, poked: true, lane: 0 });
      return 'gull';
    };
    return world;
  }
  const HOP = [0, -3, -6, -8, -9, -8, -6, -3, -1, 0, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];                // a hop (with a grab) when he is touched
  function boardAirborne(rider) {
    if (rider.air) return true;
    if (!rider.hop) return false;
    return !Number.isInteger(rider.hop) || rider.hop < 0 || rider.hop > HOP.length || HOP[HOP.length - rider.hop] < 0;
  }

  /* ---- things in the sky and on the far sea (software, whole pixels). They are drawn only where the backdrop is sky or sea: the wave hides what is behind it. */
  function makeCloud(noise, w, h, seed) {
    const tone = new Uint8Array(w * h), alpha = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const nx = (x + 0.5) / w * 2 - 1, ny = (y + 0.5) / h * 2 - 1;
        const env = 1 - (Math.abs(nx) ** 2.1 * 0.9 + (ny < 0 ? ny * ny * 1.15 : ny * ny * 1.9));
        const m = env * 1.25 + (noise.fbm(x * 0.1 + seed * 5, y * 0.26 + seed * 2, 3) - 0.5) * 1.0;
        if (m <= 0.12) continue;
        alpha[y * w + x] = 1;
        tone[y * w + x] = BYTE(40 + 215 * clamp((ny + 0.55) / 1.25, 0, 1) + (noise(x * 0.4, y * 0.6 + seed) - 0.5) * 50 + (nx < -0.55 ? 55 : 0));
      }
    }
    return { w, h, tone, alpha };
  }
  /** A cloud takes the colour of the sky behind it: deep twilight violet on top, sunset rose-gold underneath. */
  const CLOUD_SHADOW_PX = hexPack('#2c164c'), CLOUD_LIT_PX = hexPack('#ffbe7c'), CLOUD_HIGH_LIT_PX = hexPack('#b8688c');
  function drawCloud(fb, back, b, x0, y0) {
    for (let yy = 0; yy < b.h; yy++) {
      const py = y0 + yy;
      if (py < 0 || py >= LIM) continue;
      const litCol = py < 44 ? CLOUD_HIGH_LIT_PX : CLOUD_LIT_PX;
      const litGain = py < 44 ? 135 : 175;
      for (let xx = 0; xx < b.w; xx++) {
        const px = x0 + xx;
        if (px < 0 || px >= W || !b.alpha[yy * b.w + xx]) continue;
        const i = py * W + px;
        if (back.cls[i] !== CLS.SKY) continue;
        const k = Math.floor(b.tone[yy * b.w + xx] / 64) / 3;
        fb[i] = mixPx(mixPx(back.rgb[i], CLOUD_SHADOW_PX, Math.round(150 * (1 - k))), litCol, Math.round(litGain * k));
      }
    }
  }
  const SIL = hexPack('#2a1450'), SIL_DARK = hexPack('#1a0c38'), RIM = hexPack('#ff9c5a');
  /** Put a silhouette pixel only where the backdrop is not the wave (things far away are hidden by it). */
  function putFar(fb, back, x, y, c) { if (x >= 0 && x < W && y >= 0 && y < LIM && back.cls[y * W + x] < CLS.WATER) fb[y * W + x] = c; }
  /** A line drawn only where the backdrop is not the wave (a gull behind the lip is hidden by it). */
  function lineFar(fb, back, x0, y0, x1, y1, c, wd = 1) {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy, x = x0, y = y0;
    for (let guard = 0; guard < 400; guard++) {
      putFar(fb, back, x, y, c);
      if (wd > 1) { putFar(fb, back, x + 1, y, c); putFar(fb, back, x, y + 1, c); putFar(fb, back, x + 1, y + 1, c); }
      if (x === x1 && y === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x += sx; }
      if (e2 <= dx) { err += dx; y += sy; }
    }
  }
  /** A gull: two wing lines (thick near the body, thin toward the tip) from a slim body with a head and a short tail; dark against the sunset. */
  function drawGull(fb, back, g) {
    const sh = gullShape(g), big = g.span > 11;
    const wingLine = (pts, thick) => { lineFar(fb, back, pts[0][0], pts[0][1], pts[1][0], pts[1][1], SIL, thick); lineFar(fb, back, pts[1][0], pts[1][1], pts[2][0], pts[2][1], SIL, 1); };
    wingLine(sh.far, 1);
    lineFar(fb, back, sh.tail[0], sh.tail[1], sh.head[0], sh.head[1], SIL, 1);
    if (big) lineFar(fb, back, sh.rump[0], sh.rump[1] + 1, sh.head[0] - g.dir, sh.head[1] + 1, SIL, 1);
    putFar(fb, back, Math.round(sh.head[0]), Math.round(sh.head[1]), SIL); putFar(fb, back, Math.round(sh.beak[0]), Math.round(sh.beak[1]), hexPack('#ffb84a'));
    wingLine(sh.near, big ? 2 : 1);
  }
  function drawBird(fb, back, b) {
    const x = Math.round(b.x), y = Math.round(b.y), up = Math.sin(b.phase) > 0;
    putFar(fb, back, x, y, SIL); putFar(fb, back, x - 1, y + (up ? -1 : 1), SIL); putFar(fb, back, x + 1, y + (up ? -1 : 1), SIL); putFar(fb, back, x - 2, y + (up ? -2 : 1), SIL); putFar(fb, back, x + 2, y + (up ? -2 : 1), SIL);
  }
  /** A palm on the far islet: a leaning trunk and a crown of fronds that sway, drawn as solid tapering arcs so that the silhouette stays a clean feathery fan. */
  function drawPalm(fb, back, bx, by, h, lean, t, ph) {
    const sway = Math.sin(t * 0.8 + ph), topX = bx + lean * h + sway * 0.6, topY = by - h, steps = Math.round(h * 1.6);
    for (let k = 0; k <= steps; k++) {                                                                                  // the trunk: a quadratic curve, two pixels wide below, one above
      const u = k / steps, v = 1 - u, x = v * v * bx + 2 * v * u * (bx + lean * h * 0.15) + u * u * topX, y = v * v * by + 2 * v * u * (by - h * 0.55) + u * u * topY;
      putFar(fb, back, Math.round(x), Math.round(y), SIL_DARK); if (u < 0.55) putFar(fb, back, Math.round(x) + 1, Math.round(y), SIL_DARK);
    }
    const angles = [-0.35, 0.3, 0.85, 1.45, 2.05, 2.65, 3.3];
    for (let f = 0; f < angles.length; f++) {
      const len = h * (0.66 + 0.1 * Math.sin(f * 1.9)), a = angles[f] + Math.sin(t * 1.0 + ph + f * 0.9) * 0.06;
      for (let s = 0; s <= len; s += 0.5) {
        const u = s / len, x = topX + Math.cos(a) * s, y = topY - Math.sin(a) * s * 0.78 + u * u * len * 0.62, r = Math.round(1.7 * (1 - u * u));
        if (r >= 1) fillDiscFar(fb, back, Math.round(x), Math.round(y), r, f % 2 ? SIL : SIL_DARK); else putFar(fb, back, Math.round(x), Math.round(y), SIL_DARK);
        if (u > 0.3 && u < 0.95 && ((s * 2) | 0) % 3 === 0) putFar(fb, back, Math.round(x), Math.round(y) + r + 1, SIL_DARK);                // the fringe of leaflets under the spine
      }
    }
    fillDiscFar(fb, back, Math.round(topX), Math.round(topY), 1, SIL_DARK);
  }
  function fillDiscFar(fb, back, cx, cy, r, c) { for (let y = cy - r; y <= cy + r; y++) for (let x = cx - r; x <= cx + r; x++) if ((x - cx) * (x - cx) + (y - cy) * (y - cy) <= r * r + 0.5) putFar(fb, back, x, y, c); }
  /** Swells: rows of dashes on the sea that slide toward the shore, short and slow at the horizon, long and quicker near us; lighter (or gold in the sun's path) on a crest, darker in a trough. */
  function makeSwells(rand, geom) {
    const rows = [], hz = geom.horizon;
    for (let k = 0; k <= 30; k++) {
      const u = k / 30, y = hz + 3 + Math.round((H - hz - 5) * u ** 1.54);
      if (rows.length && rows[rows.length - 1].y === y) continue;
      rows.push({
        y, period: 29 + Math.round(u * 51 + rand() * 19), len: 8 + Math.round(u * 22 + rand() * 6),
        speed: .19 + u * .51, phase: Math.round(rand() * 217), crest: rand() < .66,
        bend: .49 + u * .96,
      });
    }
    return rows;
  }
  function drawSwells(s, world) {
    const { fb, back, swells, currents } = s, sun = back.geom.sun, hz = back.geom.horizon;
    const gain = s.wave?.visibleGain || currents.gain;
    const light = hexPack('#97b2ba'), gold = hexPack('#f0bc86'), dark = hexPack('#1d3047');
    const drift = Math.floor(world.steps * 1.25);
    const perspective = 63 / Math.log1p((H - hz) / 9);
    // Broad reflections travel over the whole visible surface. The same
    // ripple continues into the wave until its faster current takes over.
    for (let y = hz + 1; y < LIM; y++) {
      const depth = y - hz, row = y * W;
      const tile = (Math.floor(perspective * Math.log1p(depth / 9)) << 8);
      const ahead = Math.floor(depth * .34) + drift;
      const envelope = .56 * smooth(depth / 21);
      const sunWidth = 7 + depth * .34;
      for (let x = 0; x < W; x++) {
        const i = row + x, kind = back.cls[i];
        if (kind !== CLS.SEA && kind !== CLS.WATER) continue;
        const ripple = currents.flow[tile | ((2 * x + ahead) & 255)];
        if (ripple > -13 && ripple < 13) continue;
        const strength = (1 - .88 * gain[i] / 255) * envelope;
        const alpha = Math.round((Math.abs(ripple) - 10) * strength);
        const shade = ripple < 0 ? dark : Math.abs(x - sun.x) < sunWidth ? gold : light;
        if (alpha > 0) fb[i] = mixPx(fb[i], shade, alpha);
      }
    }

    for (const row of swells) {
      if (row.y - 2 >= LIM) break;
      const off = row.phase - world.steps * row.speed, per = row.period;
      for (let x0 = ((off % per) + per) % per - per; x0 < W; x0 += per) {
        const end = Math.min(W - 1, Math.floor(x0 + row.len));
        for (let x = Math.max(0, Math.ceil(x0)); x <= end; x++) {
          const y = row.y + Math.round(row.bend * SIN[(x * 6 + row.phase - drift) & 255] / 127);
          if (y >= LIM) continue;
          const i = y * W + x, kind = back.cls[i];
          if (kind !== CLS.SEA && kind !== CLS.WATER) continue;
          const span = 2 * (x - x0) / row.len - 1;
          const taper = (1 - span * span) * (1 - .83 * gain[i] / 255);
          const inSun = Math.abs(x - sun.x) < 7 + (row.y - hz) * .34;
          const color = row.crest ? (inSun ? gold : light) : dark;
          const alpha = Math.round(taper * (row.crest ? (inSun ? 102 : 90) : 77));
          if (alpha > 0) fb[i] = mixPx(fb[i], color, alpha);
        }
      }
    }
  }
  const CURRENT_LIGHT = hexPack('#2ad0ec'), CURRENT_VEIN = hexPack('#e4fdff'), CURRENT_SUN = hexPack('#ffe49e'), CURRENT_DEPTH = hexPack('#041236');
  function currentSegments(points) {
    if (!points) return [];
    const samples = spline(points, 3), segments = [];
    let distance = 0;
    for (let i = 1; i < samples.length; i++) {
      const [x, y] = samples[i - 1], [endX, endY] = samples[i];
      const dx = endX - x, dy = endY - y, length = Math.hypot(dx, dy);
      if (!length) continue;
      segments.push({x, y, length, ux: dx / length, uy: dy / length, distance});
      distance += length;
    }
    return segments;
  }
  function onCurrent(path, x, y) {
    let closest = Infinity, best = null, along = 0, across = 0;
    for (const segment of path) {
      const dx = x - segment.x, dy = y - segment.y;
      const u = clamp(dx * segment.ux + dy * segment.uy, 0, segment.length);
      const a = dx - u * segment.ux, b = dy - u * segment.uy;
      const d = a * a + b * b;
      if (d >= closest) continue;
      closest = d;
      best = segment;
      along = segment.distance + u;
      across = b * segment.ux - a * segment.uy;
    }
    return best ? {along, across, ux: best.ux, uy: best.uy} : null;
  }
  /** Distance from open water gives the quicker current a feathered edge.
   *  The foreground ripples run across both surfaces at that shared edge. */
  function currentGain(cls) {
    const reach = 34, distance = new Uint8Array(W * H).fill(reach);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const i = y * W + x;
      distance[i] = cls[i] === CLS.SEA ? 0 : Math.min(reach,
        x > 0 ? distance[i - 1] + 1 : reach,
        y > 0 ? distance[i - W] + 1 : reach);
    }
    const gain = new Uint8Array(W * H);
    for (let y = H - 1; y >= 0; y--) for (let x = W - 1; x >= 0; x--) {
      const i = y * W + x;
      distance[i] = Math.min(distance[i],
        x < W - 1 ? distance[i + 1] + 1 : reach,
        y < H - 1 ? distance[i + W] + 1 : reach);
      if (cls[i] === CLS.WATER) gain[i] = Math.round(255 * smooth(distance[i] / reach));
    }
    return gain;
  }
  /** Lay bands of reflective water along the open curve of the barrel.
   *  Texture coordinates and the wake's heading come from the same path. */
  function buildCurrents(back) {
    const [cx, cy] = back.geom.centre, flow = new Int8Array(64 * 256);
    const gain = currentGain(back.cls);
    const path = currentSegments(back.geom.current);
    const heading = path.length ? {x: new Int8Array(W * H), y: new Int8Array(W * H)} : null;
    const noise = makeNoise(seeded(0x453CE8));
    for (let r = 0; r < 64; r++) for (let u = 0; u < 256; u++) {
      // Sleek stretched flow ribbons along the barrel curl (long along u, crisp
      // across r) with fine aerated foam filaments on the sharpest ridges.
      const broad = lerp(noise(u / 16, r * .46), noise((u - 256) / 16, r * .46), smooth(u / 256));
      const ribbon = lerp(noise(u / 8 + 11, r * .92), noise((u - 256) / 8 + 11, r * .92), smooth(u / 256));
      const thread = noise(u / 4 + 27, r * 1.35);
      const lift = 128 * (broad - .50) + 92 * (ribbon - .51) + 56 * (thread - .53);
      flow[r * 256 + u] = Math.round(clamp(lift, -96, 118));
    }
    const texels = [];
    for (let i = 0; i < back.cls.length; i++) {
      if (back.cls[i] !== CLS.WATER) continue;
      const x = i % W, y = Math.floor(i / W);
      const local = heading ? onCurrent(path, x, y) : null;
      let lane, along;
      if (local) {
        lane = clamp(Math.round(31 + .52 * local.across + 1.6 * Math.sin(local.along * .046)), 0, 63);
        along = -Math.round(local.along * 1.27) & 255;
        heading.x[i] = Math.round(local.ux * 127);
        heading.y[i] = Math.round(local.uy * 127);
        gain[i] = Math.round(gain[i] * (1 - .74 * smooth((Math.abs(local.across) - 36) / 76)));
      } else {
        const shoulder = Math.max(0, cy - y);
        const across = x - .26 * (y - cy) + .0015 * shoulder * shoulder;
        lane = clamp(Math.round(.25 * across + 4), 0, 63);
        along = Math.round(y * 1.16 + x * .21) & 255;
      }
      // The 200 × 320 picture fits in the low 16 bits. The upper bits address the tile.
      texels.push((lane << 24) | (along << 16) | i);
    }
    return { flow, texels: Uint32Array.from(texels), gain, heading };
  }
  function drawCurrents(s, world) {
    const { fb, currents } = s;
    const phase = Math.floor(world.phase * 3.4);
    const end = LIM * W;
    const { flow, texels, gain } = currents;
    for (let k = 0; k < texels.length; k++) {
      const texel = texels[k];
      const i = texel & 65535;
      if (i >= end) break;
      const address = texel >>> 16;
      const crest = flow[(address & 0xff00) | ((address + phase) & 255)];
      if (crest > 16) {
        const color = fb[i];
        // The thin pale rim belongs to the breaker, even as water moves below it.
        if (((color >>> 8) & 255) < 204) {
          const g = gain[i];
          if (crest > 74) {
            const sunCatch = i < 96 * W && (i % W) < 146 && crest > 88;
            fb[i] = mixPx(color, sunCatch ? CURRENT_SUN : CURRENT_VEIN, ((crest - 36) * g + 127) >> 8);
          } else {
            fb[i] = mixPx(color, CURRENT_LIGHT, ((crest - 10) * g + 127) >> 8);
          }
        }
      } else if (crest < -14) {
        if (((fb[i] >>> 8) & 255) < 196) fb[i] = mixPx(fb[i], CURRENT_DEPTH, ((-crest - 5) * gain[i] + 127) >> 8);
      }
    }
  }
  /** The sunlit foam on the wave (gold and cream pixels of the backdrop) twinkles: a few at a time flash into a little star. */
  function findGold(back) {
    const list = [];
    for (let y = 100; y < H - 40; y++) for (let x = 0; x < W; x++) { const i = y * W + x; if (back.cls[i] !== CLS.WATER) continue; const v = back.rgb[i], r = v & 255, g = (v >> 8) & 255, b = (v >> 16) & 255; if (((r > 225 && g > 170 && b > 110 && b < 235 && r - b > 20) || (r > 238 && g > 238 && b > 228)) && (x + y) % 2 === 0) list.push(i); }
    return list;
  }
  /** The surfer: drawn into a raster with his outline and blitted; the board is a second raster when it is not under his feet (thrown, floating). With `dry` nothing is drawn
   *  and the boxes (x0, y0, x1, y1 in picture pixels, outline included) of what would be are returned (the tests keep them out of the page's clock). */
  function drawSurferFrame(s, world, dry) {
    const sf = world.surfer, r = s.raster, OX = RIDER_OX, OY = RIDER_OY, hop = sf.hop > 0 ? HOP[HOP.length - sf.hop] : 0, board = world.ride.board, boxes = [];
    const emit = (x0, y0) => {
      if (dry) { let lo = r.w, hi = -1, top = r.h, bottom = -1; for (let y = 0; y < r.h; y++) for (let x = 0; x < r.w; x++) if (r.buf[y * r.w + x]) { if (x < lo) lo = x; if (x > hi) hi = x; if (y < top) top = y; if (y > bottom) bottom = y; } if (hi >= 0) boxes.push([x0 + lo - 1, y0 + top - 1, x0 + hi + 1, y0 + bottom + 1]); }
      else blitRaster(s.fb, r, x0, y0, s.spal, OUTLINE, s.rim);
    };
    const separate = (sf.mode === 'fall' || sf.mode === 'under' || sf.mode === 'swim') && board.mode !== 'attached';
    if (separate) { r.clear(); drawBoard(r, OX, OY, board.ang, 1, 0); emit(Math.round(board.x) - OX, Math.round(board.y) - OY); }
    if (sf.hidden) return boxes;
    r.clear();
    if (sf.mode === 'swim') drawSwimmer(r, OX, OY, world.time * 4);
    else if (sf.mode === 'paddle') {
      const plant = sf.u < 0.14 ? 1 - sf.u / 0.14 : clamp((sf.u - 0.7) / 0.3, 0, 1);
      s.joints = drawPaddler(r, OX, OY, world.paddle, plant, sf.pitchQ);
    }
    else if (sf.mode === 'popup') s.joints = drawPopUp(r, OX, OY, sf.pose, sf.pitchQ, sf.name === 'settle' ? 1 - sf.u : sf.u, world.paddle);
    else if (sf.mode === 'fall') drawStanding(r, OX, OY, { pose: sf.pose, pitch: sf.pitchQ, board: false });
    else s.joints = drawStanding(r, OX, OY, { pose: sf.pose, pitch: sf.pitchQ, board: true });
    emit(Math.round(sf.x) - OX, Math.round(sf.y) + hop - OY);
    return boxes;
  }

  function drawBoardShade(s, world) {
    const rider = world.surfer;
    if (rider.hidden || boardAirborne(rider) || !['stand','paddle','popup'].includes(rider.mode)) return;
    for (let step = -15; step <= 17; step++) {
      const [tx,ty] = boardPoint(rider,step,2.1);
      const x = Math.round(tx), y = Math.round(ty+4);
      if (x < 0 || x >= W || y < 0 || y+2 >= LIM) continue;
      for (let dy = 0; dy < 3; dy++) {
        const index = (y+dy)*W+x;
        if (s.back.cls[index] === CLS.WATER) s.fb[index] = shadePx(s.fb[index], 1 - (.22-.046*dy)*(1-Math.abs(step)/22));
      }
    }
  }

  /** The lip grows while it throws and thins while the foam boils up. */
  function veilStrength(v) { return v.state === 'throw' ? Math.min(1, v.t / 14) : v.state === 'crash' ? Math.max(0, 1 - v.t / 40) : 0; }
  const FOAM_CREST = hexPack('#fffaf0'), FOAM_SUN = hexPack('#ffdc96'), FOAM_COOL = hexPack('#7ae4f0'), FOAM_CLEAR = hexPack('#2aa4c8'), FOAM_SHADE = hexPack('#12507c');
  const AQUA_GLASS = hexPack('#1cd6ee'), AQUA_BRIGHT = hexPack('#8af8ff'), AQUA_GLOW = hexPack('#68fce8'), DEEP_WATER = hexPack('#0d5898'), SUN_RIM = hexPack('#ffd074');
  const SPLASH_SPIKES = [
    { vx: -3.45, vy: 3.45, g: 0.34, w: 2.5, sun: true },
    { vx: -1.85, vy: 4.95, g: 0.38, w: 3.0, sun: true },
    { vx: 0.35, vy: 5.55, g: 0.41, w: 3.2, sun: false },
    { vx: 2.25, vy: 4.55, g: 0.37, w: 2.8, sun: false },
    { vx: 3.85, vy: 3.15, g: 0.33, w: 2.3, sun: false },
  ];
  const CARVE_RIBS = [
    { vx: 1.05, vy: 0.92, g: 0.052, len: 10 },
    { vx: 1.32, vy: 0.62, g: 0.044, len: 13 },
    { vx: 1.52, vy: 0.28, g: 0.036, len: 15 },
    { vx: 1.18, vy: -0.15, g: 0.025, len: 11 },
  ];
  const CARVE_SUN = hexPack('#ffe49a'), CARVE_PEARL = hexPack('#fffcf6'), CARVE_AQUA = hexPack('#5aeef8'), CARVE_DEEP = hexPack('#12689c');

  function heightAtFoot(points, x) {
    for (let i = 1; i < points.length; i++) {
      const [x0, y0] = points[i - 1], [x1, y1] = points[i];
      if (x0 !== x1 && x >= Math.min(x0, x1) && x <= Math.max(x0, x1)) return lerp(y0, y1, (x - x0) / (x1 - x0));
    }
    return points[0][1];
  }
  function makeBreaker(back) {
    const { geom, cls } = back;
    const path = makePath(spline(geom.lip, 7)), crest = [];
    for (let d = 0; d < path.length; d += 2) crest.push(path.at(d));

    const [tipX, tipY] = geom.tip, hitX = tipX - 12;
    const hitY = Math.max(tipY + 27, heightAtFoot(geom.foot, hitX) - 8);
    const falls = [15, 17, 14, 16, 15, 18, 16].map((duration, i) => ({
      x: tipX + i * 1.9 - 2, y: tipY - 1 - i * 1.25,
      hitX: hitX + i * 1.5 - 3, hitY: hitY - i * .40,
      duration, offset: i * 9, period: duration + 13 + (i % 3) * 3,
      splashHeight: [26, 0, 22, 0, 28, 0, 23][i]
    }));

    // On impact the foam spreads sideways over the water. The flattened
    // wedge follows the foot and fades into the wash at its irregular edge.
    const noise = makeNoise(seeded(0x54bb0a)), texture = new Uint8Array(32 * 128);
    for (let v = 0; v < 32; v++) for (let u = 0; u < 128; u++) {
      const span = u / 4, radius = v * .39 + .38 * Math.sin(u * PI / 64);
      const lumps = lerp(noise(span, radius), noise(span - 32, radius), smooth(u / 128));
      const bubbles = noise(u / 2 + 19, v * .86 + 14);
      texture[v * 128 + u] = Math.round(255 * (.71 * lumps + .29 * bubbles));
    }
    const pixels = [], addresses = [], coverage = [];
    for (let y = Math.max(0, Math.floor(hitY - 28)); y < Math.min(H, hitY + 28); y++) {
      for (let x = Math.max(0, Math.floor(hitX - 60)); x < Math.min(W, hitX + 69); x++) {
        const i = y * W + x;
        if (cls[i] !== CLS.SEA && cls[i] !== CLS.WATER) continue;
        const dx = x - hitX, dy = y - hitY + dx * .14;
        const reach = dx > 0 ? 67 : 57;
        const lift = 8 * smooth(1 - Math.abs(dx) / 29);
        const depth = dy > 0 ? 20 : 10 + lift;
        const edge = noise(x * .12, y * .25) - .5;
        const spread = clamp(1 - Math.hypot(dx / reach, dy / depth) + .17 * edge, 0, 1);
        if (spread < .045) continue;
        const row = Math.round(15 + dy * .83) & 31, u = Math.round(x * 1.3 + dy * .67) & 127;
        pixels.push(i);
        addresses.push(row * 128 + u);
        coverage.push(Math.round(255 * spread ** .66));
      }
    }
    return { crest, falls, tipX, tipY, foot: geom.foot, texture, pixels: Uint16Array.from(pixels),
      addresses: Uint16Array.from(addresses), coverage: Uint8Array.from(coverage) };
  }

  /** Airborne drops accelerate along the curve toward the trough. */
  function fallingWater(fall, age, dx = 0, dy = 0) {
    const t = clamp(age / fall.duration, 0, 1), distance = t * (.12 + .88 * t);
    return [lerp(fall.x + dx, fall.hitX, distance), lerp(fall.y + dy, fall.hitY, distance)];
  }
  function impactRun(fall, age, foot) {
    const x = fall.hitX + age * (4.42 - .083 * age);
    const slope = heightAtFoot(foot, x) - heightAtFoot(foot, fall.hitX);
    return [x, fall.hitY + .86 * slope];
  }

  function drawWhitewater(s, world) {
    const { fb, breaker, wave } = s, st = world.steps;
    const wash = wave?.wash ?? .5;
    const power = .82 + .16 * veilStrength(world.veil) + .14 * wash + .08 * world.surge;
    const [tipX, tipY] = wave ? wavePoint(wave, breaker.tipX, breaker.tipY) : [breaker.tipX, breaker.tipY];
    const dx = tipX - breaker.tipX, dy = tipY - breaker.tipY;
    // Fast cel-shaded 90s-arcade pixel-art foam puff (hoisted constants, integer loops).
    const foamBillow = (cx, cy, r, a, sunTint) => {
      if (a < 28 || r < 1.3) return;
      const rr = Math.ceil(r), r2 = r * r, rimCut = r2 * 0.74, invR = 1 / r;
      const y0 = Math.max(0, cy - rr), y1 = Math.min(LIM - 1, cy + rr);
      const x0 = Math.max(0, cx - rr), x1 = Math.min(W - 1, cx + rr);
      const topCol = sunTint ? FOAM_SUN : FOAM_CREST;
      for (let py = y0; py <= y1; py++) {
        const dy = py - cy, dy2 = dy * dy, row = py * W, dyS = dy * 0.78;
        for (let px = x0; px <= x1; px++) {
          const dx = px - cx, d2 = dx * dx + dy2;
          if (d2 > r2) continue;
          if (d2 > rimCut && (((px + py) & 1) === 1)) continue;
          const shade = (dyS + dx * 0.42) * invR;
          const col = shade < -0.18 ? topCol : shade < 0.24 ? FOAM_CREST : shade < 0.58 ? FOAM_COOL : FOAM_SHADE;
          if (a >= 242 && d2 <= rimCut) fb[row + px] = col;
          else fb[row + px] = mixPx(fb[row + px], col, d2 > rimCut ? (a * 210) >> 8 : a);
        }
      }
    };

    // Fast connected, tapering 90s-arcade splash plume (thick cel-shaded base
    // curving into a sharp jagged white/gold foam spike).
    const splashSpike = (x0, y0, vx, vy, g, ageT, baseWidth, a, sunTint) => {
      if (a < 28 || ageT <= 0.15) return;
      const steps = 7, topCol = sunTint ? FOAM_SUN : FOAM_CREST;
      for (let sIdx = 0; sIdx <= steps; sIdx++) {
        const frac = sIdx / steps, t = ageT * frac;
        const px = Math.round(x0 + vx * t);
        const py = Math.round(y0 - (vy * t - 0.5 * g * t * t));
        if (py > y0 + 4 || py < 0 || py >= LIM) continue;
        const w = Math.max(0, Math.round(baseWidth * (1 - frac * 0.84)));
        const sa = Math.min(255, Math.round(a * (1 - frac * 0.28)));
        if (w === 0) {
          putA(fb, px, py, topCol, sa);
        } else {
          const invW = 1 / (w + 0.5);
          for (let ox = -w; ox <= w; ox++) {
            const edge = ox * invW;
            const col = edge < -0.35 ? topCol : (edge < 0.25 || frac > 0.7) ? FOAM_CREST : edge < 0.65 ? FOAM_COOL : FOAM_SHADE;
            putA(fb, px + ox, py, col, (ox === -w || ox === w) ? (sa * 196) >> 8 : sa);
          }
          if (frac < 0.50) putA(fb, px, py + 1, FOAM_COOL, (sa * 164) >> 8);
        }
      }
    };

    // 1. Dynamic 90s-arcade crest animation: sculpted rolling whitewater
    // breakers peeling down the arch + shimmering backlit emerald-aqua pulses
    // inside the lip + lush arching offshore spindrift streamers!
    const beat = Math.floor(world.phase * 8.4);
    const windBeat = Math.floor(world.phase * 5.2);
    const crestLen = breaker.crest.length;
    for (let k = 0; k < crestLen; k++) {
      const wave1 = SIN[(k * 8 - beat) & 255];
      const wave2 = SIN[(k * 20 - (beat >> 1) + 41) & 255];
      const froth = wave1 + .56 * wave2;
      const point = wave ? wavePoint(wave, ...breaker.crest[k]) : breaker.crest[k];
      const x = Math.round(point[0]), y = Math.round(point[1]);
      const sunSide = x < 168;
      if (y < 130 && froth > 44 && (k & 1) === 0) {
        const shimmerA = Math.min(180, Math.round((froth - 30) * 0.9 * power));
        putA(fb, x + 4, y + 4, AQUA_GLOW, shimmerA);
        putA(fb, x + 5, y + 3, AQUA_BRIGHT, shimmerA >> 1);
      }
      if (froth > 4) {
        const a = Math.min(254, Math.round((108 + 1.12 * froth) * power));
        if (froth > 92 && (k % 3 === 0)) {
          foamBillow(x, y, froth > 134 ? 3.1 : 2.3, a, sunSide);
        } else {
          putA(fb, x + 2, y + 2, FOAM_SHADE, a >> 1);
          putA(fb, x + 1, y + 1, FOAM_COOL, (a * 224) >> 8);
          putA(fb, x, y, FOAM_CREST, a);
          if (froth > 44) {
            putA(fb, x - 1, y - 1, sunSide ? FOAM_SUN : FOAM_CREST, (a * 240) >> 8);
            putA(fb, x, y - 1, FOAM_CREST, (a * 208) >> 8);
          }
        }
      }
      if (y < 86 && (k % 3 === 0)) {
        const gust = SIN[(k * 14 - windBeat) & 255] + 0.58 * SIN[(k * 31 + (windBeat >> 1)) & 255];
        if (gust > 46) {
          const feather = Math.min(9, Math.round(4 + (gust - 46) * 0.055 + 2.2 * world.surge));
          const dirX = x > 114 ? 1.2 : -1.0;
          for (let f = 1; f <= feather; f++) {
            const ft = f / feather;
            const archY = (SIN[Math.round(ft * 108) & 255] / 127) * 1.8;
            const fx = Math.round(x + dirX * f * 1.15);
            const fy = Math.round(y - f * 0.28 - archY);
            const fa = Math.min(244, Math.round((1 - ft * 0.72) * (192 + 56 * world.surge) * power));
            if (fa < 24) continue;
            const col = f <= 3 ? FOAM_CREST : ft < 0.65 ? FOAM_SUN : FOAM_COOL;
            putA(fb, fx, fy, col, fa);
            if (f <= 3) putA(fb, fx, fy + 1, f <= 2 ? FOAM_CREST : FOAM_COOL, (fa * 192) >> 8);
            if (f === feather && gust > 90) {
              putA(fb, fx + (dirX > 0 ? 2 : -2), fy, FOAM_SUN, (fa * 220) >> 8);
              putA(fb, fx + (dirX > 0 ? 4 : -4), fy + 1, FOAM_COOL, fa >> 1);
            }
          }
        }
      }
    }

    // 2. Sculpted 4-tone 90s-arcade boiling cauldron + expanding lacy trough wash:
    const { pixels, addresses, texture, coverage } = breaker;
    const offsetFast = Math.floor(world.phase * 6.0);
    const offsetSlow = Math.floor(world.phase * 2.5);
    const end = LIM * W;
    const edge = 12 + 46 * (1 - wash);
    const hitX = breaker.tipX - 12, hitY = breaker.falls[3].hitY;
    for (let n = 0; n < pixels.length; n++) {
      const i = pixels[n], address = addresses[n];
      if (i >= end) break;
      const rowBits = address & 0xf80;
      const b1 = texture[rowBits | ((address - offsetFast) & 127)];
      const b2 = texture[(((address >> 7) + 11) & 31) * 128 + ((address + offsetSlow * 2) & 127)];
      const boil = (b1 * 0.64 + b2 * 0.36);
      const gain = clamp((boil - 8) * .0105, .24, 1.54) * power;
      const a = Math.min(255, Math.round(Math.max(0, coverage[n] - edge) * gain * 1.34));
      if (a > 24) {
        const px = i % W, py = (i / W) | 0;
        const sunSide = px < hitX + 24 && py < hitY + 6;
        const upperLobe = py < hitY + 4 - (px - hitX) * 0.12;
        const lit = boil + (upperLobe ? 28 : -22);
        const tone = lit > 164 ? (sunSide && lit > 182 ? FOAM_SUN : FOAM_CREST) : lit > 122 ? FOAM_COOL : lit > 86 ? FOAM_CLEAR : FOAM_SHADE;
        fb[i] = mixPx(fb[i], tone, a > 160 ? 248 : a > 88 ? 202 : 136);
      }
    }
    // Expanding lacy turquoise-white wash ripples radiating into the foreground trough!
    const ringPhase = (world.phase * 0.085) % 1;
    for (let ring = 0; ring < 2; ring++) {
      const ru = (ringPhase + ring * 0.5) % 1;
      const rx = 26 + ru * 42, ry = 7 + ru * 13;
      const ra = Math.round((1 - ru) * 140 * power);
      if (ra < 20) continue;
      for (let ang = 0; ang < 22; ang++) {
        if (((ang + Math.floor(ru * 12)) & 3) === 0) continue;
        const idx = Math.round((ang / 22) * 128);
        const px = Math.round(hitX + 4 + (SIN[(idx + 64) & 255] / 127) * rx);
        const py = Math.round(hitY + 10 + (SIN[idx & 255] / 127) * ry);
        putA(fb, px, py, (ang & 1) ? FOAM_COOL : FOAM_CREST, ra);
        putA(fb, px, py + 1, FOAM_SHADE, ra >> 1);
      }
    }
    // Heavy rolling cel-shaded whitewater cushions tumbling along the cauldron rim!
    const billowPhase = world.phase * 0.15;
    for (let b = 0; b < 8; b++) {
      const u = ((b / 8) + billowPhase * 0.085) % 1;
      const arcS = SIN[Math.round(u * 128) & 255] / 127;
      const bx = Math.round(hitX - 38 + u * 92);
      const by = Math.round(heightAtFoot(breaker.foot, bx) - 6 - 3.6 * arcS + 1.6 * (SIN[Math.round(billowPhase * 96 + b * 68) & 255] / 127));
      const br = (2.8 + 3.1 * arcS) * (0.88 + 0.20 * (SIN[Math.round(billowPhase * 76 + b * 92) & 255] / 127));
      foamBillow(bx, by, br, Math.round(238 * Math.sqrt(Math.max(0, arcS)) * power), bx < hitX + 14);
    }

    // 3. Heavy, high-contrast 90s-arcade cascading lip waterfall: visible
    // translucent cobalt/aquamarine ocean water channels torn apart by fast
    // plunging white & sunset-gold foam tongues!
    const middle = breaker.falls[3], startY = tipY - 11, depth = Math.round(middle.hitY - startY + 4);
    const rushFast = Math.floor(world.phase * 19.5);
    const rushMed = Math.floor(world.phase * 11.5);
    for (let row = 0; row < depth; row++) {
      const t = row / Math.max(1, depth);
      const fallPhase = Math.round(320 * Math.sqrt(t) - rushFast);
      const sway = SIN[(fallPhase + row * 4) & 255] / 127;
      const flare = t > 0.65 ? ((t - 0.65) / 0.35) ** 1.3 * 7.2 : 0;
      const arcS = SIN[Math.round(t * 128) & 255] / 127;
      const fan = Math.round(5.0 + 5.6 * t + 2.3 * arcS + (1.8 + 3.6 * wash) * t + flare + sway * 1.2);
      const cx = Math.round(lerp(tipX + 2, middle.hitX + 2, t * (.22 + .78 * t)) - arcS * 5.0 + sway);
      const y = Math.round(startY + row);
      if (y < 0 || y >= LIM) continue;
      const rowOff1 = (row * 5 - (rushFast >> 1)) & 127;
      const rowOff2 = (row * 3 - (rushMed >> 1) + 47) & 127;
      const invFan = 1 / Math.max(3, fan);
      const topJoin = row < 7 ? smooth(row / 7) : 1;
      const shred = 0.24 + 0.30 * t;
      const rowIdx = y * W;
      for (let w = -fan; w <= fan; w++) {
        const px = cx + w;
        if (px < 0 || px >= W) continue;
        const tex1 = texture[((row + (w & 3) * 3) & 31) * 128 + ((w * 6 + rowOff1) & 127)] * 0.00392;
        const tex2 = texture[(((row << 1) + ((w + 2) & 3) * 5) & 31) * 128 + ((w * 9 + rowOff2) & 127)] * 0.00392;
        const normW = w * invFan;
        const finger = 0.5 + 0.5 * SIN[(Math.round(normW * 128 + row * 3.2 - rushMed * 1.1)) & 255] / 127;
        const density = tex1 * 0.46 + tex2 * 0.24 + finger * shred + (1 - Math.abs(normW)) * 0.58 + 0.14 * (1 - t);
        if (density < 0.58 || (row < 5 && w > 3)) continue;
        const a = Math.min(255, Math.round((density > 1.08 ? 255 : density > 0.86 ? 232 : 184) * (0.55 + 0.45 * topJoin) * power));
        let col;
        if (w <= -fan + 2 && t < 0.92 && density > 0.68) col = density > 0.96 ? FOAM_SUN : SUN_RIM;
        else if (w >= fan - 2 && density < 1.08) col = FOAM_SHADE;
        else if (density > 1.14) col = FOAM_CREST;
        else if (density > 0.94) col = finger > 0.58 ? AQUA_BRIGHT : FOAM_COOL;
        else if (density > 0.76) col = AQUA_GLASS;
        else col = DEEP_WATER;
        fb[rowIdx + px] = a >= 250 ? col : mixPx(fb[rowIdx + px], col, a);
      }
      if (t > 0.18 && t < 0.94 && ((row + (rushFast >> 2)) & 3) === 0) {
        const side = ((row + rushMed) & 1) ? -1 : 1;
        const off = fan + 2 + ((row * 3 + rushFast) % 6);
        putA(fb, cx + side * off, y, side < 0 ? FOAM_SUN : AQUA_BRIGHT, Math.round(220 * power));
      }
    }

    // 4. Heavy plunging water masses + EXPLOSIVE 90s-arcade tapering splash
    // crowns (5 connected curving foam spikes + unified boiling crash base +
    // 14 ballistic backlit droplets + heavy rolling foam bore)!
    for (const fall of breaker.falls) {
      const age = (st + fall.offset) % fall.period;
      if (age < fall.duration) {
        const [tx, ty] = fallingWater(fall, age - 5.0, dx, dy), [hx, hy] = fallingWater(fall, age, dx, dy);
        const span = Math.max(1, Math.round(hy - ty));
        const fade = power * smooth(age / 3.5);
        for (let j = 0; j <= span; j++) {
          const t = j / span, taper = .38 + .62 * t;
          const x = Math.round(lerp(tx, hx, t)), y = Math.round(lerp(ty, hy, t));
          const lace = SIN[(j * 53 + age * 13 + fall.offset * 3) & 255] > -20;
          putA(fb, x + 2, y, FOAM_SHADE, Math.round(140 * fade * taper));
          putA(fb, x + 1, y, lace ? AQUA_BRIGHT : FOAM_COOL, Math.round((lace ? 232 : 162) * fade * taper));
          putA(fb, x, y, t > 0.72 ? FOAM_CREST : lace ? FOAM_CREST : FOAM_SUN, Math.round((lace ? 252 : 192) * fade * taper));
          if (lace && t > .34) putA(fb, x - 1, y + 1, SUN_RIM, Math.round(186 * fade));
        }
        foamBillow(Math.round(hx), Math.round(hy), 2.1, Math.min(248, Math.round(236 * fade)), true);
      } else {
        const after = age - fall.duration, fade = 1 - smooth(after / 16);
        if (fade === 0) continue;
        const [floorX, floorY] = impactRun(fall, after, breaker.foot);
        const x = Math.round(floorX), floor = Math.round(floorY);
        const a = Math.min(255, Math.round(254 * power * fade));
        if (fall.splashHeight > 0 && after < 15) {
          const impactX = Math.round(fall.hitX + after * 0.55);
          const impactY = Math.round(fall.hitY);
          const burst = smooth(after / 1.5) * (1 - smooth((after - 5) / 10));
          const strength = Math.min(255, Math.round(255 * power * burst));
          if (after < 6) {
            const collarR = 3.8 + after * 0.45;
            foamBillow(impactX - 4, impactY - 1, collarR * 0.85, strength, true);
            foamBillow(impactX + 3, impactY - 2, collarR, strength, false);
          }
          const pTime = Math.min(10.5, after + 0.9);
          for (let sIdx = 0; sIdx < SPLASH_SPIKES.length; sIdx++) {
            const sp = SPLASH_SPIKES[sIdx];
            const jitter = ((fall.offset + sIdx * 7) % 5 - 2) * 0.14;
            splashSpike(impactX, impactY, sp.vx + jitter, sp.vy, sp.g, pTime, sp.w, strength, sp.sun);
          }
          for (let drop = 0; drop < 14; drop++) {
            const h = (fall.offset * 13 + drop * 29) % 31;
            const dvx = (h - 15) * 0.31;
            const dvy = 2.8 + (drop % 7) * 0.66 + (fall.splashHeight - 22) * 0.12;
            const dt = after * 0.98 + (drop & 1) * 0.45;
            const px = Math.round(impactX + dvx * dt);
            const py = Math.round(impactY - (dvy * dt - 0.21 * dt * dt));
            if (py > impactY + 4) continue;
            const da = Math.min(255, Math.round((255 - after * 14) * power));
            if (da < 24) continue;
            const col = dvx < -0.5 ? FOAM_SUN : (drop % 3 === 0 ? AQUA_BRIGHT : FOAM_CREST);
            putA(fb, px, py, col, da);
            if (drop < 6 && after < 9) putA(fb, px, py + 1, FOAM_COOL, (da * 185) >> 8);
          }
        }
        if (after > 1 && after < 14 && (after % 3 === 0)) {
          foamBillow(x, floor - 1, 2.5 + 1.3 * fade, (a * 238) >> 8, x < hitX + 20);
        }
        putA(fb, x - 2, floor - 2, FOAM_SUN, (a * 220) >> 8);
        putA(fb, x, floor - 2, FOAM_CREST, a);
        putA(fb, x + 2, floor - 1, FOAM_CREST, (a * 240) >> 8);
        putA(fb, x + 5, floor, FOAM_COOL, (a * 220) >> 8);
        putA(fb, x + 8, floor - 1, FOAM_CREST, (a * 190) >> 8);
        putA(fb, x + 2, floor + 1, AQUA_GLASS, (a * 208) >> 8);
        putA(fb, x + 4, floor + 2, FOAM_SHADE, (a * 180) >> 8);
      }
    }
  }
  function drawParticles(s, world) {
    const { fb } = s, foam = s.foamLut[31], aqua = s.foamLut[24], mist = s.foamLut[16], cream = hexPack('#ffdf92'), gold = hexPack('#fff8d8');
    for (const q of world.particles) {
      const a = Math.min(255, Math.round(256 * (1 - q.age / q.life)));
      if (a < 18) continue;
      const x = Math.round(q.x), y = Math.round(q.y);
      putA(fb, x, y, q.big ? gold : q.warm ? cream : foam, a);
      if (q.big) {
        // Chunky gleaming 90s-arcade water bead + directional speed streak!
        const tx = Math.round(q.x - clamp(q.vx * 1.25, -2.0, 2.0));
        const ty = Math.round(q.y - clamp(q.vy * 1.25, -2.0, 2.0));
        putA(fb, x + 1, y, q.warm ? cream : foam, Math.round(a * 0.84));
        putA(fb, tx, ty, q.warm ? cream : aqua, Math.round(a * 0.76));
        putA(fb, x, y + 1, aqua, Math.round(a * 0.56));
        putA(fb, tx, ty + 1, mist, Math.round(a * 0.36));
      }
    }
    for (const rp of world.ripples) {
      if (rp.age < 0) continue;
      const r = 2 + rp.age * 0.6, a = Math.round(256 * (1 - rp.age / 28) * 0.75);
      for (let k = 0; k < 22; k++) { const ang = k / 22 * 6.2832, x = Math.round(rp.x + Math.cos(ang) * r), y = Math.round(rp.y + Math.sin(ang) * r * 0.4); if (x >= 0 && x < W && y >= 0 && y < H && s.back.cls[y * W + x] !== CLS.SKY) putA(fb, x, y, s.foamLut[28], a); }
    }
    for (const b of world.bubbles) putA(fb, Math.round(b.x), Math.round(b.y), s.foamLut[26], Math.round(256 * (1 - b.age / b.life) * 0.85));
  }
  function drawSparkles(s, world) {
    const { fb, back } = s, cream = hexPack('#fff6d0'), gold = hexPack('#ffd27a');
    for (const q of world.sparkles) {
      const x = q.x, y = q.y; if (x < 0 || x >= W || y < 0 || y >= LIM || back.cls[y * W + x] !== CLS.SEA) continue;
      const on = q.age < q.life * 0.7;
      if (!on) continue;
      put(fb, x, y, cream); put(fb, x + 1, y, gold); if (q.big) { put(fb, x - 1, y, gold); put(fb, x + 2, y, gold); if (back.cls[(y - 1) * W + x] === CLS.SEA) put(fb, x, y - 1, gold); }
    }
    for (const q of world.glints) {
      const k = q.age < 6 ? q.age / 5 : (12 - q.age) / 6, arm = k > 0.7 ? 2 : 1, c = k > 0.5 ? cream : gold;
      if (k <= 0.1) continue;
      put(fb, q.x, q.y, hexPack('#ffffff')); for (let a = 1; a <= arm; a++) { put(fb, q.x - a, q.y, c); put(fb, q.x + a, q.y, c); put(fb, q.x, q.y - a, c); put(fb, q.x, q.y + a, c); }
    }
  }
  /** The glow around the sun breathes: thin golden rings fade in and out, and a coastal beacon pulses softly on the headland. */
  function drawSunGlow(s, world) {
    const { fb, back } = s, sun = back.geom.sun, glow = hexPack('#ffda88'), outer = hexPack('#ff9c68'), k = 0.5 + 0.5 * Math.sin(world.time * 0.9);
    for (const [rad, a0, col] of [[sun.r + 3, 62, glow], [sun.r + 8, 40, glow], [sun.r + 15, 24, outer]]) {
      const a = Math.round(a0 * (rad > sun.r + 10 ? 1 - k : k));
      for (let q = 0; q < 140; q++) { const ang = q / 140 * 6.2832, x = Math.round(sun.x + Math.cos(ang) * rad), y = Math.round(sun.y + Math.sin(ang) * rad); if (x >= 0 && x < W && y >= 0 && y < LIM && back.cls[y * W + x] === CLS.SKY) putA(fb, x, y, col, a); }
    }
    if (!back.builtin && LIM > 134) {
      const pulse = Math.max(0, Math.sin(world.time * 1.45) ** 4);
      const bx = 9, by = 124;
      if (pulse > 0.08 && back.cls[(by + 2) * W + bx] === CLS.STILL) {
        putA(fb, bx, by, hexPack('#fff6cc'), Math.round(230 * pulse));
        putA(fb, bx - 1, by, hexPack('#ffb864'), Math.round(135 * pulse));
        putA(fb, bx + 1, by, hexPack('#ffb864'), Math.round(135 * pulse));
        putA(fb, bx, by - 1, hexPack('#ffb864'), Math.round(120 * pulse));
      }
    }
  }
  /** A soft darkening behind the page's date and clock (the dock's `eased` 0-1): the sun's path would drown the white digits. */
  const SCRIM = { x0: 0, y0: 122, w: 96, h: 60 };
  function makeScrim() {
    const m = new Uint8Array(SCRIM.w * SCRIM.h);
    for (let y = 0; y < SCRIM.h; y++) for (let x = 0; x < SCRIM.w; x++) m[y * SCRIM.w + x] = Math.round(255 * smooth(Math.min(x + 4, SCRIM.w - x) / 22) * smooth(Math.min(y + 2, SCRIM.h - y) / 12));
    return m;
  }
  function applyScrim(fb, mask, eased) {
    if (eased <= 0.01) return;
    for (let y = 0; y < SCRIM.h; y++) {
      const py = SCRIM.y0 + y;
      if (py >= LIM) break;
      for (let x = 0; x < SCRIM.w; x++) { const m = mask[y * SCRIM.w + x]; if (m) { const i = py * W + SCRIM.x0 + x; fb[i] = shadePx(fb[i], 1 - 0.36 * eased * m / 255); } }
    }
  }
  /** The palm sprite from the atlas (frame `palm`, RGBA with alpha 0 or 255), or null. */
  function readPalm(json, pixels) {
    try {
      const f = json && json.frames && json.frames.palm;
      if (!okFrame(f) || !pixels || !pixels.data || f[2] > 140 || f[3] > 200 || f[0] + f[2] > pixels.width || (f[1] + f[3]) * pixels.width * 4 > pixels.data.length) return null;
      const [x, y, w, h] = f, rgbBuf = new Uint32Array(w * h), mask = new Uint8Array(w * h);
      let n = 0;
      for (let yy = 0; yy < h; yy++) for (let xx = 0; xx < w; xx++) { const p = ((y + yy) * pixels.width + x + xx) * 4; if (pixels.data[p + 3] > 127) { mask[yy * w + xx] = 1; n++; rgbBuf[yy * w + xx] = (0xff000000 | (pixels.data[p + 2] << 16) | (pixels.data[p + 1] << 8) | pixels.data[p]) >>> 0; } }
      return n > 50 ? { w, h, rgb: rgbBuf, mask } : null;
    } catch (e) { return null; }
  }
  /** The crown stays in place while the trunk bends out through the left edge; its base is off camera. */
  const palmOffset = (y, h) => { const shift = Math.round(65 * smooth(clamp((y / h - 0.38) / 0.43, 0, 1))); return shift ? -shift : 0; };
  function drawPalmSprite(fb, palm, at, t) {
    const { w, h, rgb: src, mask } = palm;
    const height = Math.round(h * 1.10), width = Math.round(w * 1.14);
    for (let dy = 0; dy < height; dy++) {
      const y = Math.min(h - 1, Math.floor(dy * h / height)), py = at.y - 4 + dy;
      if (py < 0 || py >= LIM) continue;
      const k = y < h * 0.72 ? smooth((h * 0.72 - y) / (h * 0.72)) : 0, dx = Math.round(k * (1.7 * Math.sin(t * 0.8 + y * 0.05) + 0.9 * Math.sin(t * 0.45 + 1.3)));      // the crown sways, the trunk's foot never
      for (let xx = 0; xx < width; xx++) {
        const x = Math.min(w - 1, Math.floor(xx * w / width)), index = y * w + x;
        if (!mask[index]) continue;
        const px = at.x + xx - 4 + dx + palmOffset(y, h);
        if (px < 0 || px >= W) continue;
        const color = src[index], red = color & 255, green = color >>> 8 & 255;
        const coconut = x >= 41 && x <= 49 && y >= 29 && y <= 42 && red > green + 19;
        fb[py * W + px] = coconut ? mixPx(color, hexPack('#ffd391'), y < 36 && x > 44 ? 88 : 33) : color;
      }
    }
  }
  /** Sun rays: wide pale wedges that fan out of the sun over the sky, fading with distance; baked once into the backdrop's sky pixels (the wave and the sea are untouched). */
  function bakeRays(back) {
    const sun = back.geom.sun, ray = rgb('#ffdc96'), N = 12, R = 112;
    for (let y = Math.max(0, Math.floor(sun.y - R)); y < Math.min(H, sun.y + R); y++) {
      for (let x = Math.max(0, Math.floor(sun.x - R)); x < Math.min(W, sun.x + R); x++) {
        const i = y * W + x;
        if (back.cls[i] !== CLS.SKY) continue;
        const dx = x - sun.x, dy = y - sun.y, d = Math.hypot(dx, dy);
        if (d < sun.r + 4 || d > R) continue;
        const wedge = Math.floor((Math.atan2(dy, dx) + PI) / (2 * PI) * N * 2 + 0.5) & 1;
        if (wedge) continue;
        const k = 0.20 * smooth(1 - (d - sun.r) / (R - sun.r)) * smooth((d - sun.r - 4) / 10);
        back.rgb[i] = pack(mixRgb(unpack(back.rgb[i]), ray, k));
      }
    }
  }
  /* ---- the rhythm of the sea: a set of 60 seconds, a dolphin, a shooting star, a far flock, mist and the camera's shake.
   *
   * The set: a swell builds in the tube's window (it rises out of the horizon, stands up, its lip begins to throw); the big wave's curtain falls over the mouth; then both close out
   * in a burst of foam with mist and a little shake, and the sea is calm for a while before the next swell starts to build. */
  const SET_LEN = 1800;
  const SET_BURST = 1350;                                                           // the step of the set at which everything closes out
  const smoothStep = (c, a, b) => smooth((c - a) / (b - a));
  /** How high the far swell stands (px) at a step of the set, how far its lip has begun to throw (0-1) and the surge (0-1) that makes the water run faster. */
  function setState(step) {
    const c = ((step % SET_LEN) + SET_LEN) % SET_LEN, k = Math.floor(step / SET_LEN);
    const hs = (n) => { let t = (Math.imul(k + 7, 2654435761) + Math.imul(n + 3, 40503)) >>> 0; t = (t ^ (t >>> 15)) >>> 0; t = Math.imul(t, 2246822519) >>> 0; t = (t ^ (t >>> 13)) >>> 0; return (t % 1000) / 1000; };      // a different swell each cycle, always the same for the same cycle
    const hMax = k === 0 ? 15 : 10 + 8 * hs(1), wide = k === 0 ? 1 : 0.8 + 0.55 * hs(2), at = k === 0 ? 0 : (hs(3) - 0.5) * 36;
    const h = c < 200 ? 0 : c < SET_BURST ? hMax * Math.pow(smoothStep(c, 200, 1250), 1.15) : hMax * (1 - smoothStep(c, SET_BURST, SET_BURST + 90));
    const lip = c < 1000 ? 0 : c < SET_BURST ? smoothStep(c, 1000, 1300) : 1 - smoothStep(c, SET_BURST, SET_BURST + 60);
    const surge = c < 600 ? 0 : c < 1100 ? smoothStep(c, 600, 1100) : c < 1500 ? 1 : c < 1700 ? 1 - smoothStep(c, 1500, 1700) : 0;
    return { c, k, h, hMax, wide, at, lip, surge };
  }
  /** The far swell: a wave that stands on the horizon inside the tube's window: a steep face toward the shore (left), a long back, a pale peach crest and white foam when it is high. */
  function drawSwell(s, world) {
    const st = setState(world.steps), h = st.h;
    if (h < 1.2) return;
    // Grow the visible width with the swell's height. At one pixel high a
    // full-width white crest reads as a hard horizontal line across the sea.
    const { fb, back } = s, hz = back.geom.horizon, cx = Math.round(130 + st.at - st.c * 0.014), base = hz + 3, wf = st.wide * smooth(Math.min(1, h / 8));
    const face = ['#cffff0', '#ffd8a0', '#34d0c0', '#1aa4b0', '#128a9e', '#0c6c8c', '#0a4e78'].map(hexPack), foam = hexPack('#ffffff');
    for (let dx = Math.round(-13 * wf); dx <= Math.round(38 * wf); dx++) {
      const t = dx < 0 ? Math.cos(Math.PI / 2 * (-dx / (13 * wf))) : Math.cos(Math.PI / 2 * (dx / (38 * wf))), top = Math.round(h * Math.pow(Math.max(0, t), 1.5));
      if (top < 1) continue;
      const x = cx + dx;
      for (let k = 0; k <= top; k++) {
        const y = base - top + k, depth = k;
        let c = depth === 0 ? (h > 8 && dx < 8 ? foam : face[0]) : depth === 1 ? face[1] : depth < 4 ? face[2] : depth < 7 ? face[3] : depth < 10 ? face[4] : depth < 13 ? face[5] : face[6];
        if (depth === 0 && st.lip > 0.3 && dx < 0 && dx > -10) c = foam;
        putFar(fb, back, x, y, c);
      }
    }
    if (st.lip > 0.25) for (let k = 0; k < Math.round(st.lip * 8); k++) { putFar(fb, back, cx - 13 - (k >> 1), base - Math.round(h * 0.5) + k, foam); if (k > 2) putFar(fb, back, cx - 12 - (k >> 1), base - Math.round(h * 0.5) + k + 1, face[1]); }
  }
  /* ---- the Mediterranean seascape: a few craft in the band between the horizon and the date, each its own kind and speed: a far ferry, a classic sloop with a mainsail and a jib, a
   *      traditional Catalan llaut with its lateen sail, a small cruiser and a windsurfer with a wake. They are hidden by the wave where they pass behind it. */
  function makeCraft(geom) {
    const hz = geom.horizon;
    return [
      { type: 'ferry', x: 105, y: hz - 1, dir: 1, speed: 0.014, acc: 0, size: 20 },
      { type: 'sloop', x: 23, y: hz + 5, dir: 1, speed: 0.05, acc: 0, size: 15 },
      { type: 'llaut', x: 139, y: hz + 7, dir: -1, speed: 0.04, acc: 0, size: 14 },
      { type: 'cruiser', x: -22, y: hz + 8, dir: 1, speed: 0.1, acc: 0, size: 13 },
      { type: 'windsurf', x: -12, y: hz + 10, dir: 1, speed: 0.28, acc: 0, size: 13 },
    ];
  }
  function stepCraft(world) {
    for (const c of world.craft) { c.acc += c.speed; while (c.acc >= 1) { c.acc -= 1; c.x += c.dir; } if (c.x > 175) c.dir = -1; if (c.x < -28) c.dir = 1; }
  }
  const CRAFT_COLOURS = Object.fromEntries(Object.entries({ cream: '#fff4dc', lit: '#ffd9a8', jib: '#ffe8c8', edge: '#ffc690', white: '#f6f0f0', cabin: '#e4dcea', glass: '#6aa8e0', pink: '#ff4f7a', yellow: '#ffd24a', board: '#ffcf3a', wake: '#c8d8f0', hullRed: '#a8402c', wood: '#7a4a2c', window: '#ffd88a', funnel: '#5a2c58', deck: '#3a2c60' }).map(([k, v]) => [k, hexPack(v)]));
  /** A craft's pixels, relative to its waterline point: drawn once into a list (a polygon fill and a few lines per sail are too much to repeat 30 times a second for something that moves a pixel
   *  every few seconds), then `drawCraft` only puts the list down where the wave does not hide it. */
  function craftPixels(c) {
    const K = CRAFT_COLOURS, d = c.dir, X0 = 100, Y0 = 100, x = X0, y = Y0, n = c.size, out = [], fb = null, back = null;
    const P = (px, py, col) => { out.push(px - X0, py - Y0, col); };
    const tri = (a, b, cc, col) => fillPolygon([a, b, cc], (px, py) => P(px, py, col));
    const lineFar = (fb0, back0, x0, y0, x1, y1, col) => {
      x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
      const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
      let err = dx + dy, px = x0, py = y0;
      for (let guard = 0; guard < 400; guard++) {
        P(px, py, col);
        if (px === x1 && py === y1) break;
        const e2 = 2 * err;
        if (e2 >= dy) { err += dy; px += sx; }
        if (e2 <= dx) { err += dx; py += sy; }
      }
    };
    if (c.type === 'sloop') {
      const L = Math.round(n * 0.9);
      for (let k = 1; k <= n; k++) P(x, y - k, SIL);                                                                                      // the mast
      tri([x - d, y - 1], [x - d, y - n + 1], [x - d * Math.round(n * 0.55), y - 1], K.cream);                                            // the mainsail, aft of the mast
      lineFar(fb, back, x - d, y - n + 1, x - d * Math.round(n * 0.55), y - 1, K.edge, 1);
      tri([x + d, y - 1], [x + d, y - n + 3], [x + d * Math.round(n * 0.5), y - 1], K.jib);                                               // the jib, forward
      for (let k = -(L >> 1); k <= (L >> 1); k++) { P(x + k, y, SIL); P(x + k, y + 1, SIL_DARK); }
      P(x + d * ((L >> 1) + 1), y - 1, SIL); P(x - d * (L >> 1), y - 1, K.hullRed);
    } else if (c.type === 'llaut') {
      const L = Math.round(n * 1.15), bow = d * (L >> 1);
      for (let k = -(L >> 1); k <= (L >> 1); k++) { P(x + k, y, K.wood); P(x + k, y + 1, SIL_DARK); }
      for (let k = 1; k <= 2; k++) P(x + bow + d * (k >> 1), y - k, K.wood); P(x - bow, y - 1, K.wood);                                    // the raised bow and stern
      const tack = [x + d * Math.round(n * 0.42), y - 2], peak = [x - d * Math.round(n * 0.12), y - n - 1], clew = [x - d * Math.round(n * 0.5), y - 2];
      tri(tack, peak, clew, K.cream); lineFar(fb, back, tack[0], tack[1], peak[0], peak[1], K.edge, 1); lineFar(fb, back, peak[0] + d, peak[1] + 1, clew[0], clew[1], K.lit, 1);   // the lateen sail, its long yard rising forward
    } else if (c.type === 'cruiser') {
      const L = Math.round(n * 1.1);
      for (let k = -(L >> 1); k <= (L >> 1); k++) { P(x + k, y - 1, K.white); P(x + k, y, K.white); P(x + k, y + 1, SIL_DARK); }
      P(x + d * ((L >> 1) + 1), y, K.white);
      for (let k = -(L >> 2) - 1; k <= (L >> 2); k++) for (let j = 2; j <= 4; j++) P(x - d * 1 + k, y - j, j === 3 ? K.glass : K.cabin);                    // the cabin and its windows
      P(x - d * 2, y - 5, SIL); P(x - d * 2, y - 6, SIL);
      for (let k = 1; k <= 5; k++) if (k % 2) P(x - d * ((L >> 1) + k), y + 1, K.wake);                                                      // a short wake
    } else if (c.type === 'windsurf') {
      const lean = 2, top = [x - d * lean, y - n], foot = [x, y - 2], clew = [x - d * Math.round(n * 0.6), y - 3];
      for (let k = -3; k <= 3; k++) P(x + k, y - 1, K.board);
      tri(top, foot, clew, K.pink); lineFar(fb, back, top[0], top[1] + 3, Math.round((foot[0] + clew[0]) / 2), Math.round((foot[1] + clew[1]) / 2) - 1, K.yellow, 1);                  // a pink sail with a yellow stripe, leaning back
      lineFar(fb, back, x, y - 2, top[0], top[1], SIL, 1);
      P(x - d * 4, y - 5, SIL_DARK); P(x - d * 4, y - 6, K.edge); lineFar(fb, back, x - d * 4, y - 4, x - d * 2, y - 2, SIL_DARK, 1); lineFar(fb, back, x - d * 3, y - 4, x - d * 5, y - 1, SIL_DARK, 1);   // the rider hangs off the boom in his harness
      for (let k = 1; k <= 5; k++) P(x - d * (3 + k), y, k % 2 ? K.white : K.wake);                                                              // the wake
    } else {                                                                                                                                  // the far ferry: a long dark hull, two decks with lit windows, a funnel
      const half = n >> 1;
      for (let k = -half; k <= half; k++) { P(x + k, y - 1, SIL_DARK); P(x + k, y, SIL_DARK); }
      for (let k = -half + 3; k <= half - 4; k++) { P(x + k, y - 2, K.deck); P(x + k, y - 3, K.deck); if (k % 2 === 0) P(x + k, y - 2, K.window); }
      for (let k = -half + 6; k <= half - 8; k++) P(x + k, y - 4, K.deck);
      P(x - d * (half - 4), y - 4, K.funnel); P(x - d * (half - 4), y - 5, K.funnel); P(x - d * (half - 5), y - 5, K.funnel);
      P(x + d * (half + 1), y - 1, SIL_DARK);
    }
    return out;
  }
  function drawCraft(s, c) {
    if (!c.px || c.pxDir !== c.dir) { c.px = craftPixels(c); c.pxDir = c.dir; }
    const { fb, back } = s, px = c.px, x = Math.round(c.x), y = c.y;
    for (let k = 0; k < px.length; k += 3) putFar(fb, back, x + px[k], y + px[k + 1], px[k + 2]);
  }
  /** A dolphin that leaps out of the sea in front of the sun's path. */
  function makeDolphin(rand, geom) {
    const dir = rand() < 0.5 ? 1 : -1, x0 = 14 + Math.floor(rand() * 18), span = 50 + Math.floor(rand() * 14), y = geom.horizon + 8 + Math.floor(rand() * 6);
    return { dir, xa: dir > 0 ? x0 : x0 + span, xb: dir > 0 ? x0 + span : x0, y, apex: 17 + Math.floor(rand() * 7), t: 0, dur: 64 };
  }
  const DOLPHIN_PROFILE = [0.7, 1.3, 2.0, 2.8, 3.4, 3.6, 3.2, 2.5, 1.7, 1.1, 0.8];
  const dolphinAt = (d, u) => ({ x: lerp(d.xa, d.xb, u), y: d.y - 4 * d.apex * u * (1 - u), base: d.y });
  /** The body is a chain of discs along the arc (arched, slender, a thin beak), drawn in a deep blue with a pale belly along its underside and a warm rim along its back; a dorsal fin,
   *  a pectoral fin and two tail flukes. */
  function drawDolphin(s, d) {
    const { fb, back } = s, N = 24, pts = [];
    let uu = d.t / d.dur, prev = dolphinAt(d, uu);
    pts.push(prev);
    for (let k = 1; k < N; k++) { let run = 0; while (run < 1.4 && uu > -0.95) { uu -= 0.004; const q = dolphinAt(d, uu); run += Math.hypot(q.x - prev.x, q.y - prev.y); prev = q; } pts.push(prev); }
    pts.reverse();                                                                  // k = 0 is the tail, N - 1 the nose
    const prof = (k) => { const f = k / (N - 1) * (DOLPHIN_PROFILE.length - 1), i = Math.min(DOLPHIN_PROFILE.length - 2, Math.floor(f)); return lerp(DOLPHIN_PROFILE[i], DOLPHIN_PROFILE[i + 1], f - i); };
    const back2 = hexPack('#243566'), belly = hexPack('#b8c8e4'), bellyShade = hexPack('#7a8ab8'), rim = hexPack('#ff9c5a');
    for (let k = 0; k < N; k++) {
      const pt = pts[k];
      if (pt.y > pt.base + 0.4) continue;
      const a = pts[Math.max(0, k - 1)], b = pts[Math.min(N - 1, k + 1)];
      let tx = b.x - a.x, ty = b.y - a.y; const m = Math.hypot(tx, ty) || 1; tx /= m; ty /= m;
      let nx = -ty, ny = tx; if (ny < 0) { nx = -nx; ny = -ny; }                    // the normal that points down: the belly side
      const r = prof(k), x = Math.round(pt.x), y = Math.round(pt.y);
      fillDiscFar(fb, back, x, y, Math.max(1, Math.round(r)), back2);
      if (r >= 1.6) { putFar(fb, back, Math.round(pt.x + nx * (r - 0.4)), Math.round(pt.y + ny * (r - 0.4)), belly); putFar(fb, back, Math.round(pt.x + nx * (r + 0.4)), Math.round(pt.y + ny * (r + 0.4)), bellyShade); putFar(fb, back, Math.round(pt.x - nx * (r - 0.2)), Math.round(pt.y - ny * (r - 0.2)), rim); }
    }
    const fin = pts[10], tail = pts[0], nose = pts[N - 1], flip = pts[14];
    if (fin.y <= fin.base) { const fx = Math.round(fin.x), fy = Math.round(fin.y); for (let k = 1; k <= 6; k++) for (let w = 0; w < Math.max(1, 3 - (k >> 1)); w++) putFar(fb, back, fx - d.dir * ((k >> 1) + w), fy - 3 - k, back2); putFar(fb, back, fx + d.dir, fy - 4, rim); }
    if (flip.y <= flip.base) { const fx = Math.round(flip.x), fy = Math.round(flip.y); for (let k = 1; k <= 3; k++) putFar(fb, back, fx + d.dir * (k >> 1), fy + 3 + k, back2); }
    if (tail.y <= tail.base - 2) { const tx = Math.round(tail.x), ty = Math.round(tail.y); for (const sg of [-1, 1]) for (let k = 1; k <= 5; k++) { putFar(fb, back, tx - d.dir * k, ty + sg * k, back2); putFar(fb, back, tx - d.dir * k, ty + sg * k + (sg > 0 ? -1 : 1), back2); } }
    if (nose.y <= nose.base) { const nx = Math.round(nose.x), ny = Math.round(nose.y); for (let k = 1; k <= 4; k++) putFar(fb, back, nx + d.dir * k, ny + (k > 2 ? 1 : 0), back2); putFar(fb, back, nx + d.dir * 3, ny + 2, belly); }
  }
  /** A shooting star across the top of the sky: a bright head and a tail that fades through cream, rose and violet, drawn only over the sky. */
  function drawShootingStar(s, star) {
    const { fb, back } = s, tail = ['#ffffff', '#fff2c8', '#ffd0b0', '#e89ac0', '#b070c0', '#7a50b0'].map(hexPack);
    for (let k = 0; k < 12; k++) {
      const x = Math.round(star.x - star.vx * k * 0.9), y = Math.round(star.y - star.vy * k * 0.9), fade = star.t > 12 ? (16 - star.t) / 4 : 1;
      if (fade <= 0 || x < 0 || x >= W || y < 0 || y >= LIM || back.cls[y * W + x] !== CLS.SKY) continue;
      fb[y * W + x] = fade > 0.5 ? tail[Math.min(5, k >> 1)] : mixPx(fb[y * W + x], tail[Math.min(5, k >> 1)], 128);
    }
  }
  /** A far flock: seven tiny birds in a loose V crossing the sky above the horizon, all beating at their own pace. */
  const FLOCK = [[0, 0], [-5, 3], [-5, -3], [-10, 6], [-10, -6], [-15, 9], [-15, -9]];
  function drawFlock(s, flock, time) {
    for (let k = 0; k < FLOCK.length; k++) {
      const x = Math.round(flock.x + FLOCK[k][0] * flock.dir), y = Math.round(flock.y + FLOCK[k][1] + Math.sin(time * 0.7 + k) * 0.8), up = Math.sin(time * 5.5 + k * 1.7) > 0;
      if (x < -3 || x >= W + 3 || y < 0 || y >= LIM) continue;
      putFar(s.fb, s.back, x, y, SIL); putFar(s.fb, s.back, x - 1, y + (up ? -1 : 1), SIL); putFar(s.fb, s.back, x + 1, y + (up ? -1 : 1), SIL); if (flock.near) { putFar(s.fb, s.back, x - 2, y + (up ? -2 : 1), SIL); putFar(s.fb, s.back, x + 2, y + (up ? -2 : 1), SIL); }
    }
  }
  /** Delicate sunset-tinted sea-spray wisps blowing off the crest & close-outs. */
  function drawMist(s, world) {
    const { fb } = s, white = hexPack('#ffe8d6'), warm = hexPack('#ffbe88'), dusk = hexPack('#b878a8');
    for (const q of world.mist) {
      if (q.age < 0) continue;
      const lifeU = q.age / q.life;
      const a = Math.round(40 * Math.sin(Math.PI * lifeU) ** 0.85);
      if (a < 6) continue;
      const r = q.r * (0.55 + 0.42 * lifeU), cx = Math.round(q.x), cy = Math.round(q.y);
      const rx = Math.max(2, Math.ceil(r * 1.25)), ry = Math.max(1, Math.ceil(r * 0.62));
      for (let dy = -ry; dy <= ry; dy++) {
        for (let dx = -rx; dx <= rx; dx++) {
          const px = cx + dx, py = cy + dy;
          if (px < 0 || px >= W || py < 0 || py >= LIM) continue;
          const d2 = (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry);
          if (d2 > 1) continue;
          if (d2 > 0.35 && (((px + py) & 1) === 1)) continue;
          const col = dx < 0 ? warm : py < 45 ? dusk : white;
          putA(fb, px, py, col, Math.round(a * (1.0 - d2 * 0.88)));
        }
      }
    }
  }
  /** The camera's shake: after a close-out the whole picture is moved a pixel or two for a few steps (a copy of the rows, only while it lasts). */
  function shiftFrame(fb, tmp, dx, dy, lim) {
    if (dx === 0 && dy === 0) return;
    tmp.set(fb.subarray(0, lim * W));
    for (let y = 0; y < lim; y++) {
      const sy = y - dy;
      if (sy < 0 || sy >= lim) continue;
      const row = y * W, src = sy * W;
      if (dx === 0) fb.set(tmp.subarray(src, src + W), row);
      else if (dx > 0) { fb.set(tmp.subarray(src, src + W - dx), row + dx); }
      else { fb.set(tmp.subarray(src - dx, src + W), row); }
    }
  }
  /** Everything of the rhythm that is logic: the set, the dolphin's leaps, the shooting star, the flock, the mist, the shake. Called at the end of every world step. */
  function stepExtras(world, rand, handle) {
    const st = world.steps, set = setState(st);
    world.surge = set.surge;
    if (set.c === 1000) handle('veil');
    if (set.c === SET_BURST - 40) handle('veil');
    if (set.c === SET_BURST) {
      handle('crash');
      world.shake = { t: 0, amp: 2.4 };
      for (let k = 0; k < 44; k++) world.mist.push({ x: 120 + rand() * 66, y: 128 + rand() * 40, vx: -(0.1 + rand() * 0.35), vy: -(0.12 + rand() * 0.4), r: 2 + rand() * 3, age: -Math.floor(rand() * 20), life: 70 + Math.floor(rand() * 50) });
      for (let k = 0; k < 20; k++) world.puff(k % 3 === 0 ? 'sheet' : 'puff', 116 + rand() * 70, 134 + rand() * 34, -(0.15 + rand() * 0.4), -0.05 - rand() * 0.15, 60 + Math.floor(rand() * 40), 'front', 0.9, k % 3 === 0 ? 2 : 3);
      world.spray(150, 150, 50, 2.6);
    }
    if (set.c === SET_BURST + 20) for (let k = 0; k < 10; k++) world.puff('streak', 96 + rand() * 40, 128 + rand() * 6, -(0.25 + rand() * 0.2), 0.02, 60, 'back', 0.8, 3);
    if (world.mist.length < 52 && rand() < .26 + .25 * set.surge) {
      const lip = world.geom.lip, point = lip[Math.floor(rand() * lip.length * .72)];
      // Offshore wind pulls the finer spray upward over the shoulder.
      world.mist.push({ x: point[0] + rand() * 3, y: point[1] - 2, vx: .29 + rand() * .61,
        vy: -.25 - rand() * .52, r: 2.3 + rand() * 3.8, age: 0, life: 28 + Math.floor(rand() * 29) });
    }
    for (const m of world.mist) { m.age++; m.x += m.vx; m.y += m.vy; m.vy *= 0.995; }
    world.mist = world.mist.filter((m) => m.age < m.life);
    if (world.shake) { world.shake.t++; if (world.shake.t > 26) world.shake = null; }
    // the dolphin
    const d = world.dolphin;
    if (d.cur) {
      d.cur.t++;
      const u0 = (d.cur.t - 1) / d.cur.dur, u1 = d.cur.t / d.cur.dur;
      for (const edge of [0, 1]) if ((u0 < edge && u1 >= edge) || (edge === 1 && d.cur.t === d.cur.dur)) { const pt = dolphinAt(d.cur, edge); world.spray(pt.x, pt.base, 14, 1.2); world.puff('puff', pt.x, pt.base - 2, 0, -0.1, 26, 'front', 0.8, 1); world.ripples.push({ x: Math.round(pt.x), y: Math.round(pt.base + 2), age: 0 }); }
      if (d.cur.t >= d.cur.dur + 10) { d.cur = null; d.next = st + 600 + Math.floor(rand() * 600); }
    } else if (st >= d.next) d.cur = makeDolphin(rand, world.geom);
    stepCraft(world);
    // the shooting star and the flock
    const sh = world.star;
    if (sh.t >= 0) { sh.t++; sh.x += sh.vx; sh.y += sh.vy; if (sh.t > 16) { sh.t = -1; sh.next = st + 700 + Math.floor(rand() * 900); } }
    else if (st >= sh.next) { sh.t = 0; sh.x = 20 + rand() * 90; sh.y = 8 + rand() * 30; sh.vx = 3.2 + rand() * 1.4; sh.vy = 1.0 + rand() * 0.9; }
    const fl = world.flock;
    if (fl.on) { fl.x += fl.dir * fl.speed; if ((fl.dir > 0 && fl.x > GULL_TURN + 24) || (fl.dir < 0 && fl.x < -24)) { fl.on = false; fl.next = st + 900 + Math.floor(rand() * 900); } }
    else if (st >= fl.next) { fl.on = true; fl.dir = rand() < 0.5 ? 1 : -1; fl.x = fl.dir > 0 ? -20 : GULL_TURN + 20; fl.y = 70 + rand() * 24; fl.speed = 0.22 + rand() * 0.12; fl.near = rand() < 0.5; }
  }

  /* ---- the beach in the lower right corner (picture mode shows it; the dock hides it; the page's clock sits at the bottom left then, so the props stand clear of it): sand with wet shine,
   *      a foam wash that runs up and back, two surfboards stuck upright, a tiki torch, a towel. Drawn once into a layer; only the wash and the torch's flame move. Coordinates are
   *      local, measured from the right edge. */
  const beachLocal = (lx) => 262 + 0.46 * lx + 0.0016 * lx * lx;
  const beachEdge = (x) => beachLocal(W - 1 - x);
  function makeBeach(rand) {
    const w = 112, x0 = W - w, y0 = 252, h = H - y0, rgbBuf = new Uint32Array(w * h), mask = new Uint8Array(w * h), pmask = new Uint8Array(w * h), noise = makeNoise(rand);
    const sand = ['#f6d49a', '#e8b878', '#d49c64', '#b87c52', '#8a5a4c', '#5e3c4a'].map(hexPack), wet = ['#a8707a', '#7c5470'].map(hexPack);
    const set = (lx, y, c) => { const x = w - 1 - lx; if (x >= 0 && x < w && y >= 0 && y < h) { rgbBuf[y * w + x] = c; mask[y * w + x] = 1; } };
    const setP = (lx, y, c) => { set(lx, y, c); const x = w - 1 - lx; if (x >= 0 && x < w && y >= 0 && y < h) pmask[y * w + x] = 1; };                       // a prop: opaque, in front of everything
    for (let y = 0; y < h; y++) for (let lx = 0; lx < w; lx++) {
      const dd = y + y0 - beachLocal(lx);
      if (dd < 0) continue;
      const speck = noise(lx * 0.9, y * 0.9) > 0.72, depth = clamp((y + y0 - 282) / 38, 0, 1);
      let c;
      if (dd < 3) c = wet[1]; else if (dd < 6) c = wet[0]; else if (dd < 10) c = sand[2];
      else c = depth < 0.25 ? sand[0] : depth < 0.5 ? sand[1] : depth < 0.75 ? sand[2] : depth < 0.9 ? sand[3] : sand[4];
      if (speck && dd > 8) c = depth < 0.5 ? sand[2] : sand[4];
      const td = Math.hypot((lx - 48) * 0.85, (y + y0 - 296) * 1.1);
      if (dd >= 6 && td < 26) c = mixPx(c, hexPack('#ffb44e'), Math.round(92 * (1 - td / 26) ** 1.5));
      set(lx, y, c);
    }
    const board = (cx, top, bottom, body, light, dark, cream) => {                                       // a surfboard stuck upright in the sand: a long oval with a stripe, lit on its left edge
      for (let y = top; y <= bottom; y++) {
        const t = (y - top) / (bottom - top), half = Math.round(4.2 * Math.sqrt(Math.max(0, Math.sin(Math.PI * Math.min(1, t * 0.92 + 0.04))))) + 1;
        for (let x = -half; x <= half; x++) setP(cx - x, y - y0, x === -half ? light : x === half ? dark : (x === 0 || (x === 1 && t > 0.2)) ? cream : body);
      }
    };
    board(15, 258, 304, hexPack('#ff6a5a'), hexPack('#ffb090'), hexPack('#b4303c'), hexPack('#fff0c4'));
    board(26, 266, 304, hexPack('#20c0b4'), hexPack('#90f0e0'), hexPack('#107080'), hexPack('#fff0c4'));
    for (let y = 270; y <= 306; y++) { setP(48, y - y0, hexPack('#5a2a18')); setP(49, y - y0, hexPack('#8a4a28')); if (y > 270 && y < 275) { setP(47, y - y0, hexPack('#5a2a18')); setP(50, y - y0, hexPack('#8a4a28')); } }   // the torch's pole and bowl
    for (let y = 308; y < 314; y++) for (let x = 48; x < 68; x++) { const skew = Math.floor((y - 308) * 1.4); setP(x + skew, y - y0, ((x - 48) >> 2) % 2 ? hexPack('#fff0c4') : hexPack('#ff7a6a')); }   // a striped towel
    const edge = hexPack('#2a1430'), grow = [];                                                                       // a dark outline round every prop, so that it stands out of the water and the sand it is stuck in
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (!pmask[y * w + x] && ((x > 0 && pmask[y * w + x - 1]) || (x < w - 1 && pmask[y * w + x + 1]) || (y > 0 && pmask[(y - 1) * w + x]) || (y < h - 1 && pmask[(y + 1) * w + x]))) grow.push(y * w + x);
    for (const i of grow) { rgbBuf[i] = edge; mask[i] = 1; pmask[i] = 1; }
    const list = (pred) => { const idx = [], col = []; for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const k = y * w + x; if (pred(k)) { idx.push((y0 + y) * W + x0 + x); col.push(rgbBuf[k]); } } return { idx: Int32Array.from(idx), col: Uint32Array.from(col) }; };
    return { w, h, x0, y0, rgb: rgbBuf, mask, pmask, sandL: list((k) => mask[k] && !pmask[k]), propL: list((k) => pmask[k]) };                // the pixels to put down, as lists: nothing is scanned in a frame
  }
  function drawBeach(s, world) {
    const b = s.beach, { fb } = s;
    if (!b || LIM < b.y0 + 12) return;
    const lim = LIM * W;
    for (let n = 0, L = b.sandL; n < L.idx.length && L.idx[n] < lim; n++) fb[L.idx[n]] = L.col[n];                                                  // the sand
    const t = world.steps, foam = s.foamLut, run = Math.sin(t * 0.045) * 3.4 + Math.sin(t * 0.11) * 0.8;                 // the wash runs up the sand and back
    const fx = W - 1 - 48, pulse = 0.82 + 0.18 * Math.sin(t * 0.34) + 0.10 * Math.sin(t * 0.71);
    const fire = hexPack('#ffad48');
    for (let lx = 0; lx < b.w; lx++) {
      const yy = Math.round(beachLocal(lx) + run - 1), broken = ((lx * 7 + (t >> 2)) % 11) < 2, px = W - 1 - lx;
      if (broken) continue;
      putA(fb, px, yy, foam[28], 230); putA(fb, px, yy - 1, foam[22], 150); if (run > 1) putA(fb, px, yy + 1, foam[16], 110);
      if (lx % 6 === ((t >> 3) % 6)) putA(fb, px, yy - 1, hexPack('#ffe4a8'), 120);
    }
    for (let r = 4; r <= 10; r += 2) {
      const ha = Math.round((r === 4 ? 58 : r === 6 ? 36 : r === 8 ? 22 : 12) * pulse);
      for (let q = 0; q < 28; q++) {
        const ang = q / 28 * 6.2832, gx = Math.round(fx + Math.cos(ang) * r), gy = Math.round(265 + Math.sin(ang) * r);
        const lx = gx - b.x0, ly = gy - b.y0;
        if (lx >= 0 && lx < b.w && ly >= 0 && ly < b.h && b.mask[ly * b.w + lx]) continue;
        putA(fb, gx, gy, fire, ha);
      }
    }
    for (let n = 0, L = b.propL; n < L.idx.length && L.idx[n] < lim; n++) fb[L.idx[n]] = L.col[n];                                                  // the props over the wash: nothing shows through them
    const flick = (t >> 1) % 3, flame = ['#fff6a8', '#ffa834', '#ff6420'].map(hexPack);                                   // the torch's flame + rising ember
    for (let k = 0; k < 7; k++) { const half = k < 2 ? 2 : k < 5 ? 1 : 0, sway = flick === 0 ? 0 : flick === 1 ? 1 : -1; for (let dx = -half; dx <= half; dx++) put(fb, fx + dx + (k > 3 ? sway : 0), 268 - k, k < 2 ? flame[2] : k < 5 ? flame[1] : flame[0]); }
    const ember = t % 28;
    if (ember < 14) putA(fb, fx + ((ember >> 2) % 2 ? 1 : -1), 261 - ember, flame[0], Math.round(210 * (1 - ember / 14)));
  }

  /* ---- one frame */
  function drawFoamItems(s, world, layer) {
    const brushes = s.brushes, flut = s.foamLut;
    for (const q of world.foamItems) {
      if (q.layer !== layer) continue;
      const list = brushes[q.style], idx = Math.min(list.length - 1, q.cap, Math.floor(q.age / q.life * list.length * 1.4)), b = list[idx];
      const a = Math.round(256 * Math.min(1, q.age / 4) * Math.pow(Math.max(0, 1 - q.age / q.life), 0.8) * q.gain);
      if (a > 0 && q.y - b.h < LIM) drawBrush(s.fb, b, Math.round(q.x - b.w / 2), Math.round(q.y - b.h / 2), a, flut, q.flip);
    }
  }
  /** A broken fan of churned water opens behind the board. Its foamy threads
   *  follow the same curved flow, with scattered water between the V edges. */
  function drawWake(s, wake) {
    if (wake.length < 2) return;
    const { fb, back, foamLut } = s, centre = back.geom && back.geom.centre || DEFAULT_GEOM.centre;
    // A wave-class pixel may still be an orange sunset reflection: use the
    // current warped plate so the wake stays only on genuinely blue water.
    const plate = s.base || back.rgb;
    const wet = (x, y, tone, alpha) => {
      if (x < 0 || x >= W || y < 0 || y >= LIM) return;
      const i = y * W + x;
      if (back.cls[i] !== CLS.WATER) return;
      if (plate) {
        const p = plate[i], r = p & 255, g = (p >>> 8) & 255, b = (p >>> 16) & 255;
        if (g <= r + 4 || b <= r + 2) return;
      }
      putA(fb, x, y, foamLut[tone], alpha);
    };
    const offset = (point) => {
      const dx = point.x - centre[0], dy = point.y - centre[1], radius = Math.hypot(dx, dy) || 1;
      const spread = Math.min(15, Math.max(0, point.age - 3) * 0.24) * (1 + 0.06 * Math.sin(point.age * 0.13));
      return [spread * dx / radius, spread * dy / radius];
    };
    let previous = offset(wake[0]);
    for (let i = 1; i < wake.length; i++) {
      const a = wake[i - 1], b = wake[i], next = offset(b);
      if (a.group === b.group) {
        const trailFade = b.age < 42 ? 1 - 0.18 * b.age / 42 : 0.82 * smooth((WAKE_LIFE - b.age) / 30);
        const atCrest = smooth((b.y - centre[1] + 51) / 27);
        const fade = trailFade * lerp(1, atCrest, smooth((b.age - 7) / 24));
        const strength = ((a.strength ?? 1) + (b.strength ?? 1)) / 2;
        const alpha = Math.round(250 * strength * Math.max(0, fade));
        const dx = b.x - a.x, dy = b.y - a.y;
        const n = Math.ceil(Math.max(Math.abs(dx), Math.abs(dy)));
        if (n <= 9 && alpha > 0) {
          const steps = Math.max(1, n);
          for (let k = 0; k <= steps; k++) {
            const t = k / steps, x = a.x + dx * t, y = a.y + dy * t;
            const ox = lerp(previous[0], next[0], t), oy = lerp(previous[1], next[1], t);
            const spread = Math.hypot(ox, oy), nx = spread > 0.01 ? ox / spread : 0, ny = spread > 0.01 ? oy / spread : 1;
            // Crisp 3-tone arcade froth fragments inside the V (lacy aerated
            // turquoise + bright pearl clusters, never a flat solid triangle).
            const seed = (a.id === undefined ? i : a.id) * 17 + k * 11 + Math.floor(b.age / 5) * 3;
            const width = Math.max(1, spread * 0.86);
            for (let across = -width; across <= width; across += 1.5) {
              const q = Math.round(across * 2), grain = ((seed + q * 13) % 19 + 19) % 19;
              if (grain > 11) continue;
              const edge = Math.abs(across) / (width + 1), gain = 0.62 + 0.36 * (1 - edge);
              const px = Math.round(x + across * nx), py = Math.round(y + across * ny);
              wet(px, py, grain < 4 ? 31 : grain < 8 ? 26 : 18, Math.round(alpha * gain));
              if (grain < 3) wet(Math.round(px + dx / steps), Math.round(py + dy / steps), 29, Math.round(alpha * 0.62));
            }
            // Punchy churned whitewater ribbon down the centre with crisp eddies.
            const centreFleck = ((seed * 7 + 3) % 13 + 13) % 13;
            if (centreFleck < 10) {
              wet(Math.round(x), Math.round(y), 31, Math.min(255, Math.round(alpha * (centreFleck < 6 ? 1.0 : 0.82))));
              if (centreFleck < 7) wet(Math.round(x + nx), Math.round(y + ny), 28, Math.round(alpha * 0.72));
            }
            // Twin gleaming arcade V-crests: pearl highlight backed by vivid
            // electric-cyan aeration along both outer edges.
            for (let side = -1; side <= 1; side += 2) {
              const px = Math.round(x + side * ox), py = Math.round(y + side * oy);
              const fleck = ((seed + side * 7) % 11 + 11) % 11;
              if (fleck < 9) wet(px, py, fleck < 5 ? 31 : 29, Math.min(255, Math.round(alpha * (fleck < 5 ? 1.0 : 0.84))));
              if (fleck < 8) wet(Math.round(px - side * nx), Math.round(py - side * ny), 24, Math.round(alpha * 0.76));
            }
          }
        }
      }
      previous = next;
    }
  }

  /** A narrow, broken waterline over the immersed rail, with a tapered wake
   *  behind the tail. Never paint the rider or foam over the sky and sea. */
  function drawBoardContact(s, world) {
    const rider = world.surfer;
    if (rider.hidden || boardAirborne(rider) || !['stand', 'paddle', 'popup'].includes(rider.mode)) return;
    const {fb, back, foamLut, raster} = s, tm = world.steps;
    const ox = Math.round(rider.x) - RIDER_OX, oy = Math.round(rider.y) - RIDER_OY;
    const rail = rider.mode === 'paddle' ? 0 : clamp(rider.pose && finite(rider.pose.rail) ? rider.pose.rail : 0, 0, 1);
    // Only the back part of the board is immersed; pressure and the water vary it smoothly.
    const immersed = clamp(0.2 + 0.10 * rail + 0.035 * Math.sin(tm * 0.12), 0.15, 0.45);
    const start = BOARD_HALF - 2 * BOARD_HALF * immersed;
    const wet = (x, y, tone, alpha, boardOnly = false) => {
      if (x < 0 || x >= W || y < 0 || y >= LIM || back.cls[y * W + x] !== CLS.WATER) return;
      let v = 0;
      if (raster) {
        const rx = x - ox, ry = y - oy;
        v = rx >= 0 && rx < raster.w && ry >= 0 && ry < raster.h ? raster.buf[ry * raster.w + rx] : 0;
      }
      const boardPixel = v === S.board || v === S.boardLight || v === S.boardDark || v === S.cream || v === S.cap;
      if ((v && !boardPixel) || (boardOnly && !boardPixel)) return;
      putA(fb, x, y, foamLut[tone], alpha);
    };
    if (rider.name === 'drag' && s.joints?.handB) {
      const x = ox + Math.round(s.joints.handB[0]), y = oy + Math.round(s.joints.handB[1]);
      const flick = tm % 9;
      for (let i = 1; i < 8; i++) {
        const a = Math.round((8 - i) * (15 + 5 * Math.sin(tm * .9 - i)));
        wet(x + i, y + 1 - Math.round((i + flick) / 4), 20 + (i % 3) * 4, a);
      }
    }
    for (let along = start; along <= BOARD_HALF - 1; along += 0.8) {
      const width = boardHalfWidth(along), depth = (along - start) / (BOARD_HALF - start);
      // Translucent cyan wash wraps neatly over the wet immersed tail edge.
      for (let across = width * 0.48; across < width * 0.95; across += 1.4) {
        const [bx, by] = boardPoint(rider, along, across);
        wet(Math.round(bx), Math.round(by + 1), 16, Math.round((105 + 48 * rail) * depth), true);
      }
      const [px, py] = boardPoint(rider, along, width + 0.35);
      const x = Math.round(px), y = Math.round(py + 1.5 + (rail > 0.5 ? 0.7 : 0));
      const flow = Math.sin(along * 0.48 - tm * 0.82) + 0.45 * Math.sin(along * 0.92 + tm * 0.66);
      if (flow > -0.82) {
        // Crisp 3-tone arcade carving cut: gleaming white lip, electric cyan
        // spray sheet, and deep aerated shadow tucked beneath the rail.
        wet(x, y, 31, Math.min(255, 236 + Math.round(18 * Math.max(0, flow))));
        wet(x, y + 1, 27, Math.min(245, 205 + Math.round(28 * rail)));
        wet(x, y + 2, 20, 152 + Math.round(28 * rail));
        wet(x, y + 3, 12, 102 + Math.round(22 * rail));
        if (flow > 0.32) wet(x, y - 1, 31, 228);
      }
    }
    // Sculpted 90s-arcade rooster-tail fan slicing off the carving tail:
    // curving water arcs, bright pearl spray tips, and turquoise mid-fan!
    const fanReach = 12 + Math.round(3 * rail);
    for (let d = 1; d <= fanReach; d += 1.1) {
      const fade = 1 - d / (fanReach + 4), spread = 2.2 + d * (0.46 + 0.14 * rail);
      for (let q = 0; q <= spread; q += 1.1) {
        const flow = Math.sin(d * 0.78 + q * 1.65 - tm * 0.92);
        if (flow < -0.52) continue;
        // Slight upward rooster-tail curl as the water arcs off the tail edge.
        const curl = -Math.sin((d / fanReach) * PI) * (1.2 + 2.2 * rail) * (q / (spread + 1));
        const [px, py] = boardPoint(rider, 21 + d, boardHalfWidth(21) + 0.7 + q + 0.4 * flow);
        const x = Math.round(px), y = Math.round(py + 2 + curl);
        if (Math.hypot(x - rider.x, y - rider.y) >= 37) continue;
        const alpha = Math.min(255, Math.round((238 + rail * 18) * fade * (1 - q / (spread + 1.6))));
        const tone = (q < 1.3 || flow > 0.42) ? 31 : flow > 0.0 ? 26 : 19;
        wet(x, y, tone, alpha);
      }
    }
  }

  /** Dramatic 90s-arcade carving rooster-tail fan & glowing spray arcs slicing
   *  off the tail and rear rail (strictly over water, never painting the surfer). */
  function drawCarveSpray(s, world) {
    const rider = world.surfer;
    if (rider.hidden || boardAirborne(rider) || !['stand', 'popup'].includes(rider.mode)) return;
    const { fb, back, raster } = s, tm = world.steps;
    const ox = Math.round(rider.x) - RIDER_OX, oy = Math.round(rider.y) - RIDER_OY;
    const rail = clamp(rider.pose && finite(rider.pose.rail) ? rider.pose.rail : 0, 0, 1);
    const carve = clamp(0.45 + 0.70 * rail + 0.35 * world.flow + Math.abs(rider.vy) * 0.35, 0.35, 1.35);
    const [tx, ty] = boardPoint(rider, 19, boardHalfWidth(19) + 0.6);
    const safePut = (x, y, col, a) => {
      if (a < 20 || x < 0 || x >= W || y < 0 || y >= LIM) return;
      if (back.cls[y * W + x] !== CLS.WATER) return;
      if (raster) {
        const rx = x - ox, ry = y - oy;
        if (rx >= 0 && rx < raster.w && ry >= 0 && ry < raster.h && raster.buf[ry * raster.w + rx]) return;
      }
      putA(fb, x, y, col, a);
    };
    // 4 sculpted, animated curved spray ribs fanning up-and-back off the tail!
    for (let rIdx = 0; rIdx < CARVE_RIBS.length; rIdx++) {
      const rb = CARVE_RIBS[rIdx];
      const pulse = 0.72 + 0.28 * SIN[(tm * 13 + rIdx * 61) & 255] / 127;
      const maxT = rb.len * carve * pulse;
      for (let t = 1; t <= maxT; t += 1.25) {
        const u = t / Math.max(1, maxT);
        const flutter = 0.55 * SIN[(Math.round(t * 28) - tm * 19 + rIdx * 47) & 255] / 127;
        const px = Math.round(tx + rb.vx * t);
        const py = Math.round(ty + 1.5 - (rb.vy * t - rb.g * t * t) + flutter);
        const a = Math.min(252, Math.round((245 - u * 155) * Math.min(1.15, carve)));
        const col = u > 0.70 ? CARVE_SUN : (rIdx === 0 || u < 0.35) ? CARVE_PEARL : CARVE_AQUA;
        safePut(px, py, col, a);
        if (u < 0.65) safePut(px, py + 1, u < 0.28 ? CARVE_PEARL : CARVE_AQUA, (a * 194) >> 8);
        if (u < 0.42) safePut(px + 1, py + 2, CARVE_DEEP, a >> 1);
      }
      if (pulse > 0.62) {
        const dt = maxT + 1.8;
        const dx = Math.round(tx + rb.vx * dt);
        const dy = Math.round(ty + 1 - (rb.vy * dt - rb.g * dt * dt));
        safePut(dx, dy, rIdx < 2 ? CARVE_SUN : CARVE_PEARL, Math.round(215 * Math.min(1, carve)));
      }
    }
  }

  function renderFrame(s) {
    const { world, fb, back } = s, plate = s.plate || back, geom = back.geom, st = world.steps;
    LIM = s.lim;
    const wp = Math.floor(world.phase), dockKey = Math.round(s.dock * 40);
    if (s.warpStep !== Math.floor(wp / 4) || s.baseLim < LIM || s.baseDock !== dockKey) {
      const stable = s.wave || dockKey <= 0 ? plate.rgb : dockKey >= 40 ? s.rgbDock : null;
      applyWarp(s.base, plate, s.warp, wp, LIM, stable);
      if (!stable) applyScrim(s.base, s.scrim, s.dock);
      if (!s.wave) for (const c of world.clouds) { const b = s.cloudSprites[c.kind % s.cloudSprites.length]; drawCloud(s.base, back, b, c.x - (b.w >> 1), c.y); }
      s.warpStep = Math.floor(wp / 4); s.baseLim = LIM; s.baseDock = dockKey;
    }          // the warp is slow: refreshed every second step
    fb.set(LIM >= H ? s.base : s.base.subarray(0, LIM * W));
    drawCurrents(s, world);
    if (s.wave) {
      drawMovingWave(s, plate);
      for (const c of world.clouds) {
        const b = s.cloudSprites[c.kind % s.cloudSprites.length];
        drawCloud(fb, back, b, c.x - (b.w >> 1), c.y);
      }
      applyScrim(fb, s.scrim, s.dock);
    }
    drawSunGlow(s, world);
    // the sky: stars (dim, a few twinkle), clouds that drift over it, the far islet with its palms, the boat, tiny birds
    const star = hexPack('#d6c6f2'), bright = hexPack('#ffffff');
    for (const q of world.stars) {
      const ph = (st + q.phase) % q.period, i = q.y * W + q.x;
      if (i >= LIM * W || back.cls[i] !== CLS.SKY) continue;
      if (q.tw && ph < 8) { fb[i] = bright; if (q.big && ph > 1 && ph < 6) { put(fb, q.x - 1, q.y, star); put(fb, q.x + 1, q.y, star); put(fb, q.x, q.y - 1, star); put(fb, q.x, q.y + 1, star); } }
      else if (ph < q.period * 0.8 || !q.tw) fb[i] = q.big ? star : mixPx(fb[i], star, 150);
    }
    drawSwells(s, world);
    drawSwell(s, world);
    for (const c of world.craft) drawCraft(s, c);
    if (world.dolphin.cur) drawDolphin(s, world.dolphin.cur);
    if (world.star.t >= 0) drawShootingStar(s, world.star);
    if (world.flock.on) drawFlock(s, world.flock, world.time);
    for (const b of world.birds) drawBird(fb, back, b);
    // the water's life: foam that drifts, the wake, then the surfer, the curtain, the foam in front, spray
    drawFoamItems(s, world, 'back');
    drawWake(s, world.wake);
    drawWhitewater(s, world);                                                                                    // the lip and wash are behind the surfer
    drawBoardShade(s, world);
    drawSurferFrame(s, world);
    drawBoardContact(s, world);
    drawCarveSpray(s, world);
    drawFoamItems(s, world, 'front');
    drawParticles(s, world);
    drawMist(s, world);
    drawSparkles(s, world);
    for (const q of world.twinkles) { const k = q.age < 7 ? q.age / 6 : (14 - q.age) / 7; if (k > 0.2 && q.y < LIM) { put(fb, q.x, q.y, hexPack('#ffffff')); if (k > 0.55) { put(fb, q.x - 1, q.y, hexPack('#fff2c0')); put(fb, q.x + 1, q.y, hexPack('#fff2c0')); put(fb, q.x, q.y - 1, hexPack('#fff2c0')); put(fb, q.x, q.y + 1, hexPack('#fff2c0')); } } }
    drawBeach(s, world);
    for (const g of world.gulls) drawGull(fb, back, g);
    if (s.palm) drawPalmSprite(fb, s.palm, geom.palm || { x: 0, y: 0 }, world.time); else drawPalm(fb, back, -36, 122, 68, 0.91, world.time, 0.4);
    if (world.shake) { const k = world.shake, amp = k.amp * (1 - k.t / 26); shiftFrame(fb, s.tmp, Math.round(amp * Math.sin(k.t * 2.3)), Math.round(amp * 0.7 * Math.cos(k.t * 3.1)), LIM); }
  }

  /* ---- the scene */
  const now = () => (typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now());
  const viewBottom = (api) => (api && api.view && finite(api.view.bottom) ? api.view.bottom : H);
  /** The atlas's pixels: an ImageData-like object (tests) or an Image drawn on a canvas (the engine). */
  function atlasPixels(api) {
    try {
      if (!api.atlas) return null;
      if (api.atlas.data && api.atlas.width) return api.atlas;
      if (typeof document === 'undefined') return null;
      const w = api.atlas.naturalWidth || api.atlas.width, h = api.atlas.naturalHeight || api.atlas.height;
      if (!(w > 0 && h > 0 && w <= 4096 && h <= 4096)) return null;
      const c = document.createElement('canvas'); c.width = w; c.height = h;
      const x = c.getContext('2d'); x.drawImage(api.atlas, 0, 0);
      return x.getImageData(0, 0, w, h);
    } catch (e) { return null; }
  }
  /** How many rows a frame needs (the dock hides the rest) and how far the dock is up (0 = the whole picture is visible, 1 = the dock is up). */
  const rowsFor = (bottom) => clamp(Math.round(bottom) + 36, 150, H);
  const dockFor = (bottom) => smooth((262 - bottom) / 60);

  const scene = {
    size: [W, H],
    init(api) {
      const rand = typeof api.random === 'function' ? api.random : seeded(1);
      LIM = H;
      const pixels = atlasPixels(api), plate = readPlate(api.json, pixels) || makeBackdrop(rand), noise = makeNoise(rand);
      const wave = makeWaveMotion(plate);
      const back = wave ? {...plate, rgb: plate.background, cls: plate.cls.slice()} : plate;
      const currents = buildCurrents(plate);
      const world = createWorld({ random: rand, back: plate, current: currents.heading, goldList: findGold(plate) });
      const s = { back, plate, wave, world, warp: buildWarp(plate.cls, plate.geom, plate.rgb), currents, breaker: makeBreaker(plate),
        brushes: readAtlasBrushes(api.json, pixels) || makeBrushes(noise), foamLut: buildFoamLut(), spal: surferPalette(), rim: null, raster: makeRaster(128, 112),
        cloudSprites: [makeCloud(noise, 62, 12, 1), makeCloud(noise, 44, 9, 2), makeCloud(noise, 76, 13, 3), makeCloud(noise, 100, 15, 4), makeCloud(noise, 72, 11, 5)], tmp: new Uint32Array(W * H), scrim: makeScrim(), swells: makeSwells(rand, back.geom), dock: dockFor(viewBottom(api)), lim: H, stepAt: 0, joints: null, base: new Uint32Array(W * H), warpStep: -1, baseLim: 0 };
      s.img = typeof ImageData === 'function' ? new ImageData(W, H) : null;
      s.fb = s.img ? new Uint32Array(s.img.data.buffer) : new Uint32Array(W * H);
      s.rim = rimPalette(s.spal);
      bakeRays(plate);
      if (wave) {
        // Give newly revealed sky the same sun rays as the rest picture.
        for (let i = 0; i < back.cls.length; i++) {
          if (back.cls[i] === CLS.WATER) back.cls[i] = i < plate.geom.horizon * W ? CLS.SKY : CLS.SEA;
        }
        bakeRays(back);
      } else {
        s.rgbDock = back.rgb.slice();
        applyScrim(s.rgbDock, s.scrim, 1);
      }
      s.beach = makeBeach(rand);
      s.palm = readPalm(api.json, pixels);
      world.seek(2);
      this.s = s;
      if (s.img) { s.lim = H; renderFrame(s); }                                    // one whole picture, so the rows under the dock are never empty
    },
    step(api, dt) {
      const s = this.s;
      if (!s) return;
      s.world.step();
      s.stepAt = now();
      const target = dockFor(viewBottom(api));
      s.dock += clamp(target - s.dock, -0.06, 0.06);                               // the darkening behind the clock eases in and out with the dock
    },
    draw(api, g) {
      const s = this.s;
      if (!s || !s.img) return;
      const bottom = viewBottom(api);
      if (now() - s.stepAt > 250) s.dock = dockFor(bottom);                        // nothing is running (the first picture, a still): no easing
      s.lim = rowsFor(bottom);
      renderFrame(s);
      g.putImageData(s.img, 0, 0);
    },
    poke(api, x, y) { if (this.s) this.s.world.poke(x, y); },
  };

  const logic = {
    W, H, STEP, CLS, CLEAR, DEFAULT_GEOM, POSES, POSE_KEYS, SEGMENTS, VARIANTS, HOP, GULL_LANES, GULL_MAX_Y, THIGH, SHIN, BACK_THIGH, BACK_SHIN, UPPER, FORE, TORSO, BOARD_HALF, S,
    seeded, rgb, pack, unpack, mixRgb, mixPx, spline, makePath, makeNoise, makeBackdrop, readPlate, mergeGeometry, buildRamps, buildWarp, applyWarp, computeColumns, makeSurface, createRide,
    createWorld, renderFrame, drawWake, drawBoardContact, boardPoint, drawSwell, drawSurferFrame, blendPose, bend, figure, followPose, FOLLOW, MOVES, SEQUENCES, START, projectDeck, deckPitch, drawStanding, standingJoints, drawPopUp, drawPaddler, drawSwimmer, drawBoard, surferPalette, rimPalette, makeRaster, blitRaster, pitchFor, quantise, fallingWater, impactRun,
    makeBrush, makeBrushes, readAtlasBrushes, buildFoamLut, makeGull, gullShape, wingAngles, stepGull, makeCloud, makeScrim, makeCraft, GULL_TURN, applyScrim, readPalm, palmOffset, dress, drawHead, makeBeach, beachEdge, setState, SET_LEN, SET_BURST, shiftFrame, makeDolphin, dolphinAt, rowsFor, dockFor, atlasPixels,
  };
  if (global.TabletGames && typeof global.TabletGames.define === 'function') global.TabletGames.define('surf', scene);
  if (typeof module !== 'undefined' && module.exports) module.exports = Object.assign({ scene }, logic);
}(typeof window !== 'undefined' ? window : globalThis));
