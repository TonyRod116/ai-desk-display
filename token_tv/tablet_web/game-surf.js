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
 * Every frame the backdrop is copied into one typed array; the sea and the wave are WARPED a pixel or two and their colours pulse along the plate's own ramps (the rings breathe, the
 * glow slides along the lip), then the living things are drawn over it by tiny software rasterisers (stars, gulls, craft, the surfer with a dark outline, spray, foam, the lip's
 * curtain, mist) and one `putImageData` puts the picture on the canvas. Everything is whole pixels.
 *
 * The file is also a Node module: the geometry, the warp, the surfer's kinematics, the ride, the world and the drawing path are pure and have tests
 * (tests/test_tablet_game_surf.mjs).
 */
(function (global) {
  'use strict';

  /* ---- constants */
  const W = 200, H = 320;                         // the picture, in art pixels (x3 on this tablet's CSS pixels, x4 on its panel)
  const STEP = 1 / 30;
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
    for (const key of ['lip', 'line', 'foot']) if (okPoints(given[key], key === 'line' ? 4 : 2)) g[key] = given[key].map((p) => [p[0], p[1]]);
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
      for (let y = 0; y < H; y++) {
        let p = (fp[1] + y) * stride + fp[0] * 4, m = (fm[1] + y) * stride + fm[0] * 4;
        for (let x = 0; x < W; x++, p += 4, m += 4) { rgbBuf[y * W + x] = (0xff000000 | (d[p + 2] << 16) | (d[p + 1] << 8) | d[p]) >>> 0; cls[y * W + x] = Math.min(3, d[m]); }
      }
      return { rgb: rgbBuf, cls, geom: mergeGeometry(json.geometry), builtin: false };
    } catch (e) { return null; }
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
    trim: P(-1, -14.2, 9, 0, -8, 4.5, 6, 6, 0),
    pumpDown: P(-3, -10, 26, -6, -6, 7, 3, 9, 0.2),
    pumpUp: P(0, -15, 2, 4, -10, -1, 8, 1, 0),
    bottom: P(-3, -8.6, 42, -30, -10, 7, 10, -3, 0.85, -8, 8.5),
    top: P(2, -12.5, -10, 8, -10, -6, 9, -5, 1),
    tuck: P(1, -7.4, 56, -46, -7, 9, 5, 9, 0.4, -6.2, 6),
    cheer: P(0, -15, -3, 10, -6, -11, 6, -11, 0),
    air: P(0, -11.5, 10, 2, -11, -5, 11, -4, 0),
    grab: P(-2, -9.8, 32, -22, -8, 12, 9, -7, 0),
    fall: P(0, -13, 35, 14, -11, -11, 11, -10, 0),
    crouch: P(-1, -9, 44, -34, -9, 8, 5, 8, 0.3, -7.5, 7.5),
    hangTen: P(-9, -15, 6, 0, -9, -3.5, 8, -4, 0, -16, -5),
    cutback: P(2, -11.5, -14, 10, -12, -7, 10, -1, 1),
    anticipate: P(-2, -9.5, 36, -28, -5, 8, 8, 4, 0.1),                              // the coil before a pop: low, the arms back
    pop: P(1, -16.5, 0, 4, -9, -4, 9, -3, 0),                                       // full extension, straight up
    airTuck: P(-2, -9, 34, -6, -6, 11, 8, -2, 0),                                   // the knees drawn up, the front hand reaching for the rail
    extend: P(0, -15.5, 2, 4, -12, -4, 12, -4, 0),                                  // let go of the rail, arms wide
    land: P(-2, -9.5, 36, -26, -9, 6, 9, 6, 0.2, -7.8, 7.8),                                    // absorbing the landing with the knees
    floater: P(0, -12.5, 6, 2, -11, 3, 9, 3, 0.3),                                  // gliding on the white water at the top
    barrel: P(1, -10.7, 38, -36, -10, 1.5, 13, 7, 0.5, -8, 8),                // compact front-side stance: looking to the exit, elbows soft
    barrelSet: P(0.8, -11.1, 35, -33, -10.5, 0, 13.5, 7, 0.55, -8, 8),        // settle into the pocket with the rear hand trailing
    barrelDeep: P(0.8, -10.2, 47, -45, -11, 3, 14, 9, 0.58, -8, 8),         // compress at the knees, keeping space between the arms
    stall: P(3.5, -10.7, 35, -37, -12, -1, 14, 8, 0.7, -8, 8),             // weight over the tail, rear hand toward the wall
    drag: P(0, -10.3, 44, -42, -12.5, 2, 14, 11, 0.6, -8, 8),                  // lower one hand and counterbalance with the other
    duck: P(1, -9.8, 52, -49, -10, 4, 14, 9, 0.4, -8, 8),                   // compress under the breaking lip
    barrelUp: P(0, -12.2, 27, -25, -10, 0, 12, 7, 0.2, -8, 8),                // recover more slowly into an open crouch
    exitTall: P(0, -15.2, -2, 6, -13, -3, 13, -3, 0, -8.2, 8.2),                // standing up tall with the arms spread as the foam spits him out
    fall1: P(3, -13, -18, -6, -12, -12, 6, 8, 0),                                   // losing balance: leaning back, the front arm up, the back arm down
    fall2: P(3, -13, -18, -6, -8, 6, 12, -12, 0),                                   // and the other way (the arms windmill)
    fallDrop: P(4, -11, -10, 6, -11, -11, 11, -11, 0),                              // off the board, the arms up
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
    const elbowF = bend(sF[0], sF[1], handF[0], handF[1], UPPER, FORE, -1), elbowB = bend(sB[0], sB[1], handB[0], handB[1], UPPER, FORE, -1);          // the elbows point back and down
    return { hip, shoulder, head, kneeF, kneeB, footF, footB, elbowF, elbowB, handF, handB, sF, sB };
  }
  /** The colours of the surfer, as indices into one packed palette (0 is empty); each body colour has a light and a dark tone next to it. */
  const S = { skin: 1, skinShade: 2, skinLight: 3, hair: 4, hairLight: 5, shirt: 6, shirtShade: 7, shirtLight: 8, trunks: 9, trunksLight: 10, trunksDark: 11, stripe: 12, eye: 13, mouth: 14,
    board: 15, boardLight: 16, boardDark: 17, cream: 18, fin: 19, cap: 20, white: 21, belly: 22 };
  const TONES = { skin: [S.skin, S.skinLight, S.skinShade], shirt: [S.shirt, S.shirtLight, S.shirtShade], trunks: [S.trunks, S.trunksLight, S.trunksDark], board: [S.board, S.boardLight, S.boardDark] };
  function surferPalette() {
    const c = hexPack, p = new Uint32Array(23);
    p[S.skin] = c('#e9a56f'); p[S.skinLight] = c('#f8c690'); p[S.skinShade] = c('#b4704a'); p[S.hair] = c('#2e1a12'); p[S.hairLight] = c('#7a4a2c');
    p[S.shirt] = c('#ff5a4a'); p[S.shirtLight] = c('#ff9a7c'); p[S.shirtShade] = c('#b4303c'); p[S.trunks] = c('#1f3a96'); p[S.trunksLight] = c('#4a70d0'); p[S.trunksDark] = c('#122060');
    p[S.stripe] = c('#fff0c4'); p[S.eye] = c('#1a1018'); p[S.mouth] = c('#a04030'); p[S.board] = c('#ff9a2a'); p[S.boardLight] = c('#ffd070'); p[S.boardDark] = c('#b8501a');
    p[S.cream] = c('#fff2cc'); p[S.fin] = c('#5a2a14'); p[S.cap] = c('#20c0b4'); p[S.white] = c('#ffffff'); p[S.belly] = c('#7a3a1c');
    return p;
  }
  /** The warm rim of the sunset on the sunny edge of every part: the palette index -> a brighter, warmer packed colour. */
  function rimPalette(pal) {
    const out = new Uint32Array(pal.length), warm = rgb('#ffd890');
    for (let i = 1; i < pal.length; i++) out[i] = pack(mixRgb(unpack(pal[i]), warm, i === S.eye || i === S.mouth ? 0.15 : 0.52));
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
  /** Eleven by twelve pixels: an adult face seen from the front and side,
   * with hair behind it and two small eyes, rather than the back of a head. */
  const HEAD_UP = ['...hhhhh...', '..hllhhhh..', '.hhaaaahhh.', '.haaaaaaah.', '.haaaaaaah.', '.haeaaeaah.', '.haasssaah.', '..assmsaah.', '..dsssssd..', '...ddddd...', '...........', '...........'];
  const HEAD_DOWN = ['...hhhhh...', '..hllhhhh..', '.hhhhhhhhh.', '.haaaaaaah.', '.haaaaaaah.', '.haeaaeaah.', '.haasssaah.', '..assmsaah.', '..dsssssd..', '...ddddd...', '...........', '...........'];
  const HEAD_KEY = { h: S.hair, l: S.hairLight, s: S.skin, a: S.skinLight, d: S.skinShade, e: S.eye, b: S.hair, m: S.mouth, o: S.skinShade };
  function drawHead(r, cx, cy, face, down) {
    const rows = down ? HEAD_DOWN : HEAD_UP;
    for (let y = 0; y < 12; y++) for (let x = 0; x < 11; x++) {
      const ch = rows[y][x];
      if (ch === '.') continue;
      r.put(face > 0 ? cx - 5 + x : cx + 5 - x, cy - 6 + y, HEAD_KEY[ch]);
    }
  }
  // Perspective: the nose comes toward the lower left of the viewer, while
  // the tail recedes to the upper right. The same projection is used for the
  // deck and for the rider's feet, so neither floats as the board pitches.
  const DECK_X = .63, DECK_DEPTH = .50;
  const projectDeck = (x, y) => [DECK_X * x, y - DECK_DEPTH * x];
  // A point on the foreshortened board, in scene coordinates. Keep wake and
  // spray anchored to the same perspective and pitch as the drawn deck.
  function boardPoint(s, along, across = 0) {
    const p = s.pitchQ * RAD, cp = Math.cos(p), sp = Math.sin(p);
    const q = projectDeck(along * cp - across * sp, along * sp + across * cp);
    return [s.x + q[0], s.y + q[1]];
  }
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
        const t = (s + half) / (2 * half), width = Math.sin(Math.PI * t) * (4.6 + 1.8 * (1 - t)) * scale;
        top.push(at(s, -width, offset)); bottom.unshift(at(s, width, offset));
      }
      return top.concat(bottom);
    };
    r.poly(edge(1, 2 + (rail > .5 ? 1 : 0)), S.boardDark);
    r.poly(edge(1), S.board);
    r.poly(edge(.65, -.4), S.boardLight);
    const a = at(-half + 3), b = at(half - 3);
    r.line(a[0], a[1], b[0], b[1], S.cream, 1);
    const tip = at(-half + 1), end = at(-half + 5);
    r.line(tip[0], tip[1], end[0], end[1], S.cap, 2);
  }
  /** A leg: a thigh that tapers to the knee, a calf that swells a little behind the shin and tapers to the ankle, a lighter knee cap. `bendSide` is the way the knee points (the calf bulges the other way). */
  function leg(r, hip, knee, ankle, tone, w0, kneeCap) {
    limb(r, hip, knee, w0, 4.9, tone);
    const dx = ankle[0] - knee[0], dy = ankle[1] - knee[1], m = Math.hypot(dx, dy) || 1, nx = -dy / m, ny = dx / m, side = nx > 0 ? 1 : -1;       // the normal on the side of the heel (the right, toward the tail)
    const calf = [knee[0] + dx * 0.36 + nx * side * 0.7, knee[1] + dy * 0.36 + ny * side * 0.7];
    limb(r, knee, ankle, 5.0, 3.3, tone); r.disc(Math.round(calf[0]), Math.round(calf[1]), 2, tone[0]);                          // the calf is a swelling on the shin
    if (kneeCap) r.put(Math.round(knee[0] - 1.6), Math.round(knee[1]), tone[1]);
  }
  /** A foot on the deck: a wedge from the heel to the toes along the board's pitch, `len` long (a foot turned across the board is short in this view), with a darker sole. */
  function foot(r, ankle, pitchRad, len, tone) {
    const cp = Math.cos(pitchRad), sp = Math.sin(pitchRad), x = ankle[0], y = ankle[1] + 0.6;
    limb(r, [x + 0.6, y], [x - len * cp, y - len * sp + 0.6], 3, 2.2, [tone[0], tone[1], tone[2]]);
    r.line(x + 0.6, y + 1.6, x - len * cp, y - len * sp + 1.9, tone[2], 1);
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
  function drawBody(r, J, pitch, down) {
    const wide = 1.12, face = -1, pr = deckPitch(pitch), shade = [S.skinShade, S.skin, S.skinShade];
    // Layer the far arm and both legs behind the clothing. In particular the
    // near thigh must not paint over the shorts when the rider compresses.
    leg(r, J.hip, J.kneeB, J.footB, shade, 6.4, false); foot(r, J.footB, pr, 3.4, shade);
    limb(r, J.sB, J.elbowB, 4, 3.4, [S.shirtShade, S.shirt, S.shirtShade]); limb(r, J.elbowB, J.handB, 3.4, 2.8, shade); r.disc(Math.round(J.handB[0]), Math.round(J.handB[1]), 2, S.skinShade);
    leg(r, J.hip, J.kneeF, J.footF, TONES.skin, 6.4, true); foot(r, J.footF, pr, 5, TONES.skin);
    limb(r, J.hip, J.shoulder, 9.4 * wide, 11.8 * wide, TONES.shirt);
    limb(r, J.hip, [J.hip[0] + (J.kneeB[0] - J.hip[0]) * 0.63, J.hip[1] + (J.kneeB[1] - J.hip[1]) * 0.63], 9.0 * wide, 6.8, TONES.trunks);
    limb(r, J.hip, [J.hip[0] + (J.kneeF[0] - J.hip[0]) * 0.63, J.hip[1] + (J.kneeF[1] - J.hip[1]) * 0.63], 9.0 * wide, 6.8, TONES.trunks);
    r.line(J.hip[0] - 3, J.hip[1] - 1, J.hip[0] + 3, J.hip[1] - 1, S.stripe, 1);
    // A small neckline and front seam make the torso read as facing us.
    r.line(J.shoulder[0] - 2, J.shoulder[1] + 2, J.shoulder[0] + 1, J.shoulder[1] + 3, S.skinShade, 1);
    r.line(J.shoulder[0] - 2, J.shoulder[1] + 5, J.hip[0] - 2, J.hip[1] - 3, S.shirtLight, 1);
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
  /** Plant the hands, draw the knees underneath, then rise into the stance.
   * All joints interpolate together; no prone-to-standing silhouette swap. */
  function drawPopUp(r, ox, oy, pose, pitch, amount) {
    const t = smooth(clamp(amount, 0, 1)), target = standingJoints(ox, oy, pose, pitch);
    const start = {
      hip: [10, -8], shoulder: [-8, -12], head: [-15, -19],
      kneeF: [13, -5], kneeB: [16, -4], footF: [19, -2], footB: [23, -2],
      sF: [-8, -11], sB: [-7, -12], elbowF: [-4, -5], elbowB: [-6, -6],
      handF: [-3, -2], handB: [-1, -2],
    };
    const J = {};
    for (const key of Object.keys(target)) {
      const begin = projectDeck(...start[key]);
      J[key] = [ox + begin[0] * (1 - t) + (target[key][0] - ox) * t, oy + begin[1] * (1 - t) + (target[key][1] - oy) * t];
    }
    drawBoard(r, ox, oy, pitch * RAD, 1, pose.rail);
    drawBody(r, J, pitch, false);
    return J;
  }
  /** Lying on the board and paddling (`phase` runs the arms' stroke); `rise` 0-1 lifts the chest for the pop-up: the hands plant on the deck and push. */
  function drawPaddler(r, ox, oy, phase, rise) {
    const k = SC, up = clamp(rise || 0, 0, 1);
    drawBoard(r, ox, oy, -0.05, 1, 0);
    const point = (x, y) => { const p = projectDeck(x * k, y * k); return [ox + p[0], oy + p[1]]; };
    const s = Math.sin(phase), c = Math.cos(phase), sh = point(-6, -8 - 7 * up);
    limb(r, point(17, -5), point(8, -6), 4, 4.4, [S.skinShade, S.skin, S.skinShade]);
    limb(r, point(8, -7), sh, 8, 9 - 2 * up, TONES.shirt);
    limb(r, point(8, -6), point(13, -6), 7, 6, TONES.trunks);
    limb(r, sh, point(-9, -12 - 9 * up), 3.6, 3.4, TONES.skin);
    const head = point(-11.5, -15 - 10 * up);
    drawHead(r, Math.round(head[0]), Math.round(head[1]), -1, false);
    if (up > 0.3) { const hand = point(-3, -2), elbow = point(-1, -7); limb(r, sh, elbow, 4, 3.6, TONES.shirt); limb(r, elbow, hand, 3.6, 3, TONES.skin); }
    else { const hand = point(-6 - 7 * c + 4, -4 + 4 * s), elbow = point(-6 - 3 * c, -8 + 3 * s - 1); limb(r, sh, elbow, 4, 3.6, TONES.shirt); limb(r, elbow, hand, 3.6, 3, TONES.skin); }
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
    drop: () => M('drop', 36, [U(0.5, 22), U(0.45, 29)], { pose: [[0, 'trim'], [0.2, 'anticipate'], [0.5, 'crouch'], [1, 'bottom']], ease: 0.6, snap: 1.5 }),
    bottom: () => M('bottom', 34, [U(0.4, 33), U(0.385, 31), U(0.42, 27)], { pose: [[0, 'bottom'], [0.55, 'bottom'], [1, 'pumpUp']], events: [[4, 'spray'], [14, 'spray']] }),
    pump: () => M('pump', 64, [U(0.45, 25), U(0.48, 21), U(0.51, 17)], { pose: [[0, 'pumpUp'], [0.14, 'pumpDown'], [0.34, 'pumpUp'], [0.54, 'pumpDown'], [0.76, 'pumpUp'], [1, 'trim']], events: [[20, 'spray'], [42, 'spray']] }),
    snap: () => M('snap', 32, [U(0.58, 13), U(0.61, 10), U(0.57, 15)], { pose: [[0, 'trim'], [0.28, 'top'], [0.55, 'top'], [1, 'bottom']], events: [[11, 'bigspray']], snap: 1.5 }),
    floater: () => M('floater', 38, [U(0.61, 11), U(0.58, 13)], { pose: [[0, 'top'], [0.25, 'floater'], [0.8, 'floater'], [1, 'trim']], events: [[6, 'spray'], [20, 'spray']] }),
    hang: () => M('hang', 66, [U(0.47, 24), U(0.43, 22)], { pose: [[0, 'trim'], [0.22, 'hangTen'], [0.8, 'hangTen'], [1, 'trim']], events: [[16, 'spray']] }),
    carve: () => M('carve', 48, [U(0.52, 20), U(0.56, 15), U(0.51, 21), U(0.45, 26)], { pose: [[0, 'trim'], [0.2, 'cutback'], [0.5, 'cutback'], [0.78, 'bottom'], [1, 'pumpUp']], events: [[10, 'spray'], [24, 'bigspray'], [36, 'spray']] }),
    airUp: () => M('airUp', 60, [{ dx: -1, dy: -6 }, { dx: -2, dy: -24 }, { dx: -3, dy: -31 }, { dx: -4, dy: -22 }, { dx: -5, dy: 0 }], { micro: 0.15, pose: [[0, 'anticipate'], [0.1, 'pop'], [0.3, 'airTuck'], [0.5, 'grab'], [0.68, 'extend'], [0.88, 'land'], [1, 'land']], events: [[1, 'spray'], [56, 'landing']], ease: 0.0, hang: 0.55, air: true, snap: 1.6 }),
    tubeIn: () => M('tubeIn', 42, [U(0.55, 15), U(0.67, 12), U(0.74, 10)], { pose: [[0, 'trim'], [0.3, 'crouch'], [0.75, 'barrelSet'], [1, 'barrel']], events: [[4, 'veil']], micro: 0.8, ease: 0.7 }),
    stall: () => M('stall', 54, [U(0.74, 10), U(0.77, 11), U(0.76, 10)], { pose: [[0, 'barrel'], [0.24, 'stall'], [0.48, 'barrelSet'], [0.72, 'stall'], [1, 'barrel']], hang: 0.8, micro: 0.65, events: [[22, 'spray']] }),
    drag: () => M('drag', 56, [U(0.74, 10), U(0.62, 11), U(0.5, 12), U(0.42, 14)], { pose: [[0, 'barrel'], [0.15, 'barrelSet'], [0.35, 'drag'], [0.68, 'drag'], [0.87, 'barrelDeep'], [1, 'barrel']], tm: 'accel', ease: 0, micro: 0.75, events: [[12, 'spray'], [32, 'spray']] }),
    pumpLow: () => M('pumpLow', 46, [U(0.42, 14), U(0.47, 12), U(0.53, 10), U(0.57, 10)], { pose: [[0, 'barrel'], [0.20, 'barrelUp'], [0.44, 'barrelDeep'], [0.68, 'barrelUp'], [0.88, 'barrelDeep'], [1, 'barrel']], micro: 0.55, events: [[10, 'spray'], [26, 'spray']] }),
    duck: () => M('duck', 40, [U(0.57, 10), U(0.58, 9), U(0.57, 10)], { pose: [[0, 'barrel'], [0.35, 'barrelDeep'], [0.65, 'duck'], [1, 'duck']], micro: 0.65, events: [[14, 'crash']] }),
    engulf: () => M('engulf', 30, [U(0.55, 14)], { kind: 'engulf', pose: [[0, 'exitTall']], events: [[1, 'engulf']] }),
    spit: () => M('spit', 18, [U(0.55, 14)], { pose: [[0, 'exitTall'], [0.55, 'exitTall'], [1, 'trim']], events: [[1, 'spit']] }),
    wobble: () => M('wobble', 26, [{ dx: -2, dy: -3 }, { dx: -3, dy: -1 }], { pose: [[0, 'top'], [0.2, 'fall1'], [0.4, 'fall2'], [0.6, 'fall1'], [0.8, 'fall2'], [1, 'fall1']], events: [[1, 'oops']], snap: 1.3 }),
    fall: () => M('fall', 36, [{ dx: 4, dy: -5 }, { dx: 8, dy: 4 }, { dx: 10, dy: 20 }], { kind: 'fall', pose: [[0, 'fall1'], [0.3, 'fall2'], [0.6, 'fallDrop'], [1, 'fallDrop']], ease: 0.0, snap: 1.2 }),
    under: () => M('under', 30, [{ dx: 1, dy: 2 }], { kind: 'under', events: [[1, 'splash']] }),
    swim: () => M('swim', 70, [{ dx: -4, dy: 0 }, { dx: -8, dy: 0 }], { kind: 'swim' }),
    paddle: () => M('paddle', 74, [U(0.45, 26), U(0.5, 20), U(0.55, 14)], { kind: 'paddle' }),
    popup: () => M('popup', 22, [U(0.55, 14)], { kind: 'popup', pose: [[0, 'crouch'], [0.6, 'crouch'], [1, 'trim']] }),
  };
  const SEQUENCES = {
    tube: ['drop', 'bottom', 'pump', 'tubeIn', 'stall', 'drag', 'pumpLow', 'duck', 'engulf', 'spit'],
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
  const FOLLOW = { hx: 0.3, hy: 0.28, lean: 0.2, head: 0.13, fx: 0.15, fy: 0.15, bx: 0.12, by: 0.12, rail: 0.22, ffx: 0.4, bfx: 0.4 };
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
    const lut = new Uint32Array(32), stops = [[0, rgb('#5ad0c8')], [0.45, rgb('#a8ece0')], [0.8, rgb('#e4fbf4')], [1, rgb('#ffffff')]];
    for (let i = 0; i < 32; i++) {
      const t = i / 31; let k = 1; while (k < stops.length - 1 && t > stops[k][0]) k++;
      lut[i] = pack(mixRgb(stops[k - 1][1], stops[k][1], clamp((t - stops[k - 1][0]) / (stops[k][0] - stops[k - 1][0]), 0, 1)));
    }
    return lut;
  }
  /** Draw a brush with its top left corner at (x, y); `a` is how opaque the whole brush is (0-256); `flip` mirrors it left to right. */
  function drawBrush(fb, b, x, y, a, foamLut, flip, clip, slant) {
    for (let yy = 0; yy < b.h; yy++) {
      for (let xx = 0; xx < b.w; xx++) {
        const j = yy * b.w + (flip ? b.w - 1 - xx : xx), al = b.alpha[j];
        if (al === 0) continue;
        const px = x + xx, py = y + yy + (slant ? Math.round(slant * (xx - (b.w >> 1))) : 0);
        if (py < 0 || py >= LIM || px < 0 || px >= W || (clip && clip[py * W + px] !== CLS.WATER)) continue;
        putA(fb, px, py, foamLut[b.tone[j] >> 3], (al * a) >> 8);
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
  const FOAM_COLUMN = { from: 0.22, to: 0.84 };                                        // the veil covers this part of the hole's width
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
    const o = Object.assign({}, t), breath = Math.sin(tt * 0.075), sway = Math.sin(tt * 0.047 + 1.3), chop = Math.sin(tt * 0.29) * Math.sin(tt * 0.113 + 0.7), fast = 0.5 + 0.9 * flow;
    const lean = amp * (1.5 * sway + 0.8 * breath) + 4 * comp;
    o.hy += FS * (amp * (0.3 * breath + 0.4 * fast * chop) + 0.5 * comp);
    o.hx += FS * amp * 0.5 * sway;
    o.lean += lean; o.head -= lean * 0.75;
    o.fx += FS * amp * 0.8 * sway; o.fy += FS * amp * 0.6 * breath;
    o.bx -= FS * amp * 0.8 * sway; o.by += FS * amp * 0.6 * chop;
    return o;
  }
  function createWorld(options) {
    const o = Object.assign({ seed: 20261110, random: null, back: null, first: 'tube', goldList: [] }, options);
    const rand = typeof o.random === 'function' ? o.random : seeded(o.seed);
    const back = o.back || makeBackdrop(rand), geom = back.geom, surface = makeSurface(geom);
    const world = {
      rand, back, geom, surface, steps: 0, time: 0, columns: computeColumns(back), ride: createRide(surface, rand, o.first),
      surfer: { x: 0, y: 0, pose: Object.assign({}, POSES.trim), pitch: 0, pitchQ: 0, vx: 0, vy: 0, mode: 'stand', name: 'drop', hidden: false, hop: 0, u: 0, ax: 0, ay: 0 },
      veil: { state: 'idle', t: 0 }, particles: [], foamItems: [], wake: [], ripples: [], gulls: [], birds: [], clouds: [], stars: [], sparkles: [], glints: [], boat: null, bubbles: [], events: [], paddle: 0, gold: [], twinkles: [], surge: 0, phase: 0, flow: 0, mist: [], shake: null, dolphin: { cur: null, next: 900 }, star: { t: -1, next: 520, x: 0, y: 0, vx: 0, vy: 0 }, flock: { on: false, next: 760, x: 0, y: 80, dir: 1, speed: 0.25, near: false },
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
      for (let k = 0; k < n && world.particles.length < 240; k++) world.particles.push({ kind: 0, x, y, vx: (rand() - 0.5) * power + dir * 0.6 * power * rand(), vy: -(0.4 + rand() * 1.5) * up * (0.6 + power * 0.4), g: 0.075, life: 16 + Math.floor(rand() * 16), age: 0, big: rand() < 0.22, warm: rand() < 0.45 });
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
      const [tx, tailY] = boardPoint(s, 15, 1), ty = tailY + 1;
      if (name === 'spray') spray(tx, ty, 10, 1.5, 1, -face);
      else if (name === 'bigspray') { spray(tx, ty - 2, 34, 2.5, 1.2, -face); puff('puff', tx, ty - 2, -face * 0.2, -0.1, 26, 'front', 0.7, 1); puff('puff', tx - face * 7, ty, -face * 0.25, -0.05, 24, 'front', 0.6, 0); }
      else if (name === 'landing') { world.shake = { t: 0, amp: 1.1 }; spray(s.x, s.y + 6, 18, 1.7); puff('puff', s.x, s.y + 8, 0, -0.08, 26, 'front'); world.ripples.push({ x: Math.round(s.x), y: Math.round(s.y + 10), age: 0 }); }
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
      } else if (name === 'spit') {                                                                                 // and spits him out at the top of the face
        for (let k = 0; k < 7; k++) puff(k % 3 === 0 ? 'sheet' : 'puff', s.x + (rand() - 0.5) * 26, s.y - 4 + (rand() - 0.5) * 20, (rand() - 0.5) * 0.3, -0.06 - rand() * 0.1, 40 + Math.floor(rand() * 20), 'front', 0.95, 3);
        spray(s.x, s.y, 30, 2.4, 1.2, 1);
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
      if (r.mode === 'popup' && r.u < 0.36) Object.assign(s.pose, POSES.crouch);
      const ovy = s.vy;
      s.vx += ((s.x - px) - s.vx) * 0.25; s.vy += ((s.y - py) - s.vy) * 0.25;
      s.ay += ((s.vy - ovy) - s.ay) * 0.25;
      world.flow += ((s.hidden ? 0.3 : clamp(Math.hypot(s.vx, s.vy) / 1.3, 0, 1)) - world.flow) * 0.06;
      if (s.mode === 'stand' || s.mode === 'popup') { s.pitch += (pitchFor(s.vx, s.vy, r.air || s.hop > 0 ? 16 : 30) - s.pitch) * 0.14; s.pitchQ = quantise(s.pitch, s.pitchQ); }
      else if (s.mode === 'fall') { s.pitch += (0 - s.pitch) * 0.1; s.pitchQ = quantise(s.pitch, s.pitchQ); }
      for (const e of r.events) handle(e);
      if (s.mode === 'paddle') world.paddle += 0.34;
      // spray off the tail while he carves, a foam trail on the water behind him
      if (s.mode === 'stand' && !s.hidden) {
        const [tx, tailY] = boardPoint(s, 17, 1), ty = tailY + 2, rail = s.pose.rail, rate = rail * 0.7 + Math.abs(s.vy) * 0.4;
        if (rand() < rate && !r.air && !s.hop) spray(tx, ty, 1 + (rail > 0.6 ? 1 : 0), 0.8 + rail * 0.8, 1, 1);
        if (!r.air && !s.hop) { world.wake.push({ x: tx, y: ty + 2, age: 0 }); if (world.wake.length > 76) world.wake.shift(); }
      }
      if (s.mode === 'paddle') { world.wake.push({ x: s.x + 16, y: s.y + 5, age: 0 }); if (world.wake.length > 76) world.wake.shift(); }
      // With the surfer facing left, the disturbed water trails to the right.
      for (const w of world.wake) { w.age++; w.x += 0.18; w.y += 0.13; }
      world.wake = world.wake.filter((w) => w.age < 76);
      // A few short droplets peel off the breaking lip. The old long vertical
      // streaks crossed the entire opening and looked like a rain shower.
      const v = world.veil, c = world.columns;
      v.t++;
      if (v.state === 'throw') {
        if (rand() < 0.18 && world.particles.filter((p) => p.kind === 1).length < 3) {
          const x = Math.round(lerp(c.x0 + (c.x1 - c.x0) * FOAM_COLUMN.from, c.x0 + (c.x1 - c.x0) * FOAM_COLUMN.to, rand())), top = c.arch[x];
          if (top > 0 && c.floor[x] > top + 4) world.particles.push({ kind: 1, x, y: top + 1, vx: -0.35 - rand() * 0.35, vy: 0.5 + rand() * 0.25, len: 1 + Math.floor(rand() * 3), life: 14, age: 0, floor: Math.min(c.floor[x] - 1, top + 6 + rand() * 4) });
        }
        if (v.t > 70) { v.state = 'idle'; v.t = 0; }
      } else if (v.state === 'crash') { if (v.t > 50) { v.state = 'idle'; v.t = 0; } if (v.t < 30 && st % 3 === 0) { const x = lerp(c.x0 + 12, c.x1 - 8, rand()); puff('streak', x, (c.floor[Math.round(x)] > 0 ? c.floor[Math.round(x)] : 160) - 3, -(0.2 + rand() * 0.2), 0.12, 50, 'back', 0.8); } }
      // spindrift off the lip, a little foam at its tip, foam that leaves the wave's foot and drifts down and left
      const lip = geom.lip;
      if (rand() < 0.28 + 0.5 * world.surge) { const p = lip[Math.floor(rand() * lip.length)]; world.particles.push({ kind: 0, x: p[0] + (rand() - 0.5) * 4, y: p[1] + (rand() - 0.5) * 3, vx: -0.28 - rand() * 0.3, vy: -0.05 + rand() * 0.2, g: 0.01, life: 20 + Math.floor(rand() * 16), age: 0, big: false }); }
      if (st % 40 === 7) puff('puff', geom.tip[0] + (rand() - 0.5) * 8, geom.tip[1] + 1, -0.1 - rand() * 0.1, -0.02, 36, 'front', 0.7);
      if (st % 7 === 0 && world.foamItems.length < 54) {                                           // foam streaks ride the flow up the face, counter-clockwise around the tube, over the lip
        const [cx, cy] = geom.centre;
        for (let tries = 0; tries < 6; tries++) {
          const x = 70 + rand() * 130, y = 30 + rand() * 270;
          if (back.cls[Math.round(y) * W + Math.round(x)] !== CLS.WATER) continue;
          const dx = x - cx, dy = y - cy, r = Math.hypot(dx, dy) || 1, sp = 0.3 + rand() * 0.3, vx = dy / r * sp, vy = -dx / r * sp;
          world.foamItems.push({ style: Math.abs(vx) < 0.12 ? 'puff' : rand() < 0.3 ? 'sheet' : 'streak', x, y, vx, vy, age: 0, life: 70 + Math.floor(rand() * 50), layer: 'back', flip: rand() < 0.5, gain: 0.5, cap: Math.abs(vx) < 0.12 ? 1 : 9, clip: true, slant: Math.abs(vx) < 0.12 ? 0 : clamp(vy / vx, -1.6, 1.6) });
          break;
        }
      }
      if (st % 3 === 0 && world.gold.length && world.twinkles.length < 10) { const i = o.goldList[Math.floor(rand() * o.goldList.length)]; if (i !== undefined) world.twinkles.push({ x: i % W, y: (i / W) | 0, age: 0, life: 14 }); }
      for (const q of world.twinkles) q.age++;
      world.twinkles = world.twinkles.filter((q) => q.age < q.life);
      for (const q of world.particles) {
        q.age++;
        if (q.kind === 0) { q.x += q.vx; q.y += q.vy; q.vy += q.g; }
        else { q.x += q.vx; q.y += q.vy; q.vy += 0.035; if (q.y >= q.floor) q.age = q.life; }
      }
      world.particles = world.particles.filter((q) => q.age < q.life && q.y < H);
      for (const q of world.foamItems) { q.age++; q.x += q.vx * (1 + 0.7 * world.flow); q.y += q.vy * (1 + 0.7 * world.flow); }
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
  /** A cloud takes the colour of the sky behind it: violet and shadowed on top, lit warm underneath (four flat steps). */
  const CLOUD_SHADOW_PX = hexPack('#402278'), CLOUD_LIT_PX = hexPack('#ffdea8');
  function drawCloud(fb, back, b, x0, y0) {
    for (let yy = 0; yy < b.h; yy++) {
      const py = y0 + yy;
      if (py < 0 || py >= LIM) continue;
      for (let xx = 0; xx < b.w; xx++) {
        const px = x0 + xx;
        if (px < 0 || px >= W || !b.alpha[yy * b.w + xx]) continue;
        const i = py * W + px;
        if (back.cls[i] !== CLS.SKY) continue;
        const k = Math.floor(b.tone[yy * b.w + xx] / 64) / 3;
        fb[i] = mixPx(mixPx(back.rgb[i], CLOUD_SHADOW_PX, Math.round(200 * (1 - k))), CLOUD_LIT_PX, Math.round(205 * k));
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
    for (let k = 0; k < 17; k++) {
      const u = k / 16, y = hz + 3 + Math.round(60 * Math.pow(u, 1.5));
      if (rows.length && rows[rows.length - 1].y === y) continue;
      rows.push({ y, period: 26 + Math.floor(u * 44 + rand() * 14), len: 3 + Math.round(u * 11 + rand() * 3), speed: 0.03 + u * 0.16, phase: Math.floor(rand() * 200), crest: rand() < 0.6 });
    }
    return rows;
  }
  function drawSwells(s, world) {
    const { fb, back, swells } = s, sun = back.geom.sun, t = world.steps, hz = back.geom.horizon, lightC = hexPack('#9a60c0'), gold = hexPack('#ffb858'), dark = hexPack('#180a3a');
    for (const row of swells) {
      if (row.y >= LIM) break;
      const off = Math.floor(row.phase - t * row.speed), per = row.period;
      for (let x0 = ((off % per) + per) % per - per; x0 < W; x0 += per) {
        for (let dx = 0; dx < row.len; dx++) {
          const x = x0 + dx;
          if (x < 0 || x >= W) continue;
          const i = row.y * W + x;
          if (back.cls[i] !== CLS.SEA) continue;
          const inPath = Math.abs(x - sun.x) < 6 + (row.y - hz) * 0.5;
          fb[i] = row.crest ? (inPath ? mixPx(fb[i], gold, 120) : mixPx(fb[i], lightC, 96)) : mixPx(fb[i], dark, 96);
        }
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
    const sf = world.surfer, r = s.raster, OX = 64, OY = 84, hop = sf.hop > 0 ? HOP[HOP.length - sf.hop] : 0, board = world.ride.board, boxes = [];
    const emit = (x0, y0) => {
      if (dry) { let lo = r.w, hi = -1, top = r.h, bottom = -1; for (let y = 0; y < r.h; y++) for (let x = 0; x < r.w; x++) if (r.buf[y * r.w + x]) { if (x < lo) lo = x; if (x > hi) hi = x; if (y < top) top = y; if (y > bottom) bottom = y; } if (hi >= 0) boxes.push([x0 + lo - 1, y0 + top - 1, x0 + hi + 1, y0 + bottom + 1]); }
      else blitRaster(s.fb, r, x0, y0, s.spal, OUTLINE, s.rim);
    };
    const separate = (sf.mode === 'fall' || sf.mode === 'under' || sf.mode === 'swim') && board.mode !== 'attached';
    if (separate) { r.clear(); drawBoard(r, OX, OY, board.ang, 1, 0); emit(Math.round(board.x) - OX, Math.round(board.y) - OY); }
    if (sf.hidden) return boxes;
    r.clear();
    if (sf.mode === 'swim') drawSwimmer(r, OX, OY, world.time * 4);
    else if (sf.mode === 'paddle') drawPaddler(r, OX, OY, world.paddle, 0);
    else if (sf.mode === 'popup') s.joints = drawPopUp(r, OX, OY, sf.pose, sf.pitchQ, sf.u);
    else if (sf.mode === 'fall') drawStanding(r, OX, OY, { pose: sf.pose, pitch: sf.pitchQ, board: false });
    else s.joints = drawStanding(r, OX, OY, { pose: sf.pose, pitch: sf.pitchQ, board: true });
    emit(Math.round(sf.x) - OX, Math.round(sf.y) + hop - OY);
    return boxes;
  }
  /** The lip grows while it throws and thins while the foam boils up. */
  function veilStrength(v) { return v.state === 'throw' ? Math.min(1, v.t / 14) : v.state === 'crash' ? Math.max(0, 1 - v.t / 40) : 0; }
  function drawVeil(s, world) {
    const v = veilStrength(world.veil);
    if (v <= 0.02) return;
    const { fb } = s, c = world.columns, sheet = hexPack('#bff6ee'), tm = world.steps;
    for (let x = c.x0 + 4; x <= c.x1 - 2; x++) {
      const top = c.arch[x], bottom = c.floor[x];
      if (top < 0 || bottom <= top + 2) continue;
      const k = (x - c.x0) / (c.x1 - c.x0), edge = smooth((k - FOAM_COLUMN.from + 0.05) / 0.12) * smooth((FOAM_COLUMN.to + 0.06 - k) / 0.12);
      // Short irregular scallops hug the curved crest; there is no sheet
      // spanning the open barrel. Two slow phases keep neighbouring patches
      // from appearing or disappearing together.
      const ripple = Math.sin(x * 0.36 + tm * 0.07) + 0.55 * Math.sin(x * 0.17 - tm * 0.043);
      const depth = Math.max(0, Math.min(bottom - top - 1, Math.round((2.6 + ripple * 1.8) * edge * v)));
      for (let dy = 0; dy < depth; dy++) {
        const a = Math.round(v * edge * (1 - dy / Math.max(1, depth)) * (45 + 16 * Math.max(0, ripple)));
        if (a > 6) putA(fb, x - Math.round(dy * 0.3), top + dy, sheet, a);
      }
    }
  }
  function drawParticles(s, world, only) {
    const { fb } = s, foam = s.foamLut[30], mist = s.foamLut[18], cream = hexPack('#ffe9c4');
    for (const q of world.particles) {
      if (only !== undefined && q.kind !== only) continue;
      const a = Math.round(256 * (1 - q.age / q.life));
      if (q.kind === 0) { const x = Math.round(q.x), y = Math.round(q.y); putA(fb, x, y, q.big || q.warm ? cream : foam, a); if (q.big) putA(fb, x + 1, y, mist, a >> 1); }
      else { const x = Math.round(q.x), y = Math.round(q.y); for (let k = 0; k < q.len; k++) putA(fb, x + Math.round(k * 0.35), y - k, k < 2 ? foam : mist, Math.min(170, 45 + 135 * (1 - k / q.len))); }
    }
    for (const rp of world.ripples) {
      if (rp.age < 0) continue;
      const r = 2 + rp.age * 0.6, a = Math.round(256 * (1 - rp.age / 28) * 0.7);
      for (let k = 0; k < 22; k++) { const ang = k / 22 * 6.2832, x = Math.round(rp.x + Math.cos(ang) * r), y = Math.round(rp.y + Math.sin(ang) * r * 0.4); if (x >= 0 && x < W && y >= 0 && y < H && s.back.cls[y * W + x] !== CLS.SKY) putA(fb, x, y, s.foamLut[26], a); }
    }
    for (const b of world.bubbles) putA(fb, Math.round(b.x), Math.round(b.y), s.foamLut[24], Math.round(256 * (1 - b.age / b.life) * 0.8));
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
  /** The glow around the sun breathes: a thin lighter ring a few pixels outside its disc fades in and out. */
  function drawSunGlow(s, world) {
    const { fb, back } = s, sun = back.geom.sun, glow = hexPack('#ffd890'), k = 0.5 + 0.5 * Math.sin(world.time * 0.9);
    for (const [rad, a0] of [[sun.r + 5, 46], [sun.r + 11, 28]]) {
      const a = Math.round(a0 * (rad > sun.r + 8 ? 1 - k : k));
      for (let q = 0; q < 140; q++) { const ang = q / 140 * 6.2832, x = Math.round(sun.x + Math.cos(ang) * rad), y = Math.round(sun.y + Math.sin(ang) * rad); if (x >= 0 && x < W && y >= 0 && y < LIM && back.cls[y * W + x] === CLS.SKY) putA(fb, x, y, glow, a); }
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
      for (let xx = 0; xx < width; xx++) { const x = Math.min(w - 1, Math.floor(xx * w / width)); if (!mask[y * w + x]) continue; const px = at.x + xx - 4 + dx + palmOffset(y, h); if (px >= 0 && px < W) fb[py * W + px] = src[y * w + x]; }
    }
  }
  /** Sun rays: wide pale wedges that fan out of the sun over the sky, fading with distance; baked once into the backdrop's sky pixels (the wave and the sea are untouched). */
  function bakeRays(back) {
    const sun = back.geom.sun, ray = rgb('#ffe2a8'), N = 12, R = 105;
    for (let y = Math.max(0, Math.floor(sun.y - R)); y < Math.min(H, sun.y + R); y++) {
      for (let x = Math.max(0, Math.floor(sun.x - R)); x < Math.min(W, sun.x + R); x++) {
        const i = y * W + x;
        if (back.cls[i] !== CLS.SKY) continue;
        const dx = x - sun.x, dy = y - sun.y, d = Math.hypot(dx, dy);
        if (d < sun.r + 4 || d > R) continue;
        const wedge = Math.floor((Math.atan2(dy, dx) + PI) / (2 * PI) * N * 2 + 0.5) & 1;
        if (wedge) continue;
        const k = 0.17 * smooth(1 - (d - sun.r) / (R - sun.r)) * smooth((d - sun.r - 4) / 10);
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
      { type: 'ferry', x: 84, y: hz - 1, dir: 1, speed: 0.014, acc: 0, size: 24 },
      { type: 'sloop', x: 14, y: hz + 4, dir: 1, speed: 0.05, acc: 0, size: 15 },
      { type: 'llaut', x: 120, y: hz + 7, dir: -1, speed: 0.04, acc: 0, size: 14 },
      { type: 'cruiser', x: 60, y: hz + 9, dir: 1, speed: 0.1, acc: 0, size: 13 },
      { type: 'windsurf', x: 40, y: hz + 9, dir: 1, speed: 0.28, acc: 0, size: 13 },
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
  /** Soft translucent puffs of mist that rise and drift after a close-out. */
  function drawMist(s, world) {
    const { fb } = s, white = hexPack('#ffffff'), warm = hexPack('#ffe8d0');
    for (const q of world.mist) {
      const a = Math.round(52 * Math.sin(Math.PI * q.age / q.life) ** 0.8), r = q.r * (0.7 + 0.5 * q.age / q.life), cx = Math.round(q.x), cy = Math.round(q.y);
      if (a < 4) continue;
      for (let y = cy - Math.ceil(r); y <= cy + Math.ceil(r); y++) for (let x = cx - Math.ceil(r); x <= cx + Math.ceil(r); x++) { const d2 = ((x - cx) * (x - cx) + (y - cy) * (y - cy)) / (r * r); if (d2 <= 1) putA(fb, x, y, x < cx ? warm : white, Math.round(a * (1.15 - d2))); }
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
    if (world.mist.length < 52 && rand() < 0.08 + 0.25 * set.surge) world.mist.push({ x: 120 + rand() * 80, y: 10 + rand() * 18, vx: -(0.15 + rand() * 0.3), vy: -0.03 - rand() * 0.1, r: 2 + rand() * 2.4, age: 0, life: 50 + Math.floor(rand() * 40) });      // spindrift and mist blow off the crest
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
    for (let lx = 0; lx < b.w; lx++) {
      const yy = Math.round(beachLocal(lx) + run - 1), broken = ((lx * 7 + (t >> 2)) % 11) < 2, px = W - 1 - lx;
      if (broken) continue;
      putA(fb, px, yy, foam[28], 230); putA(fb, px, yy - 1, foam[22], 150); if (run > 1) putA(fb, px, yy + 1, foam[16], 110);
    }
    for (let n = 0, L = b.propL; n < L.idx.length && L.idx[n] < lim; n++) fb[L.idx[n]] = L.col[n];                                                  // the props over the wash: nothing shows through them
    const flick = (t >> 1) % 3, flame = ['#ffe070', '#ffa030', '#ff6a20'].map(hexPack), fx = W - 1 - 48;                  // the torch's flame
    for (let k = 0; k < 7; k++) { const half = k < 2 ? 2 : k < 5 ? 1 : 0, sway = flick === 0 ? 0 : flick === 1 ? 1 : -1; for (let dx = -half; dx <= half; dx++) put(fb, fx + dx + (k > 3 ? sway : 0), 268 - k, k < 2 ? flame[2] : k < 5 ? flame[1] : flame[0]); }
  }

  /* ---- one frame */
  function drawFoamItems(s, world, layer) {
    const brushes = s.brushes, flut = s.foamLut;
    for (const q of world.foamItems) {
      if (q.layer !== layer) continue;
      const list = brushes[q.style], idx = Math.min(list.length - 1, q.cap, Math.floor(q.age / q.life * list.length * 1.4)), b = list[idx];
      const a = Math.round(256 * Math.min(1, q.age / 4) * Math.pow(Math.max(0, 1 - q.age / q.life), 0.8) * q.gain);
      if (a > 0 && q.y - b.h < LIM) drawBrush(s.fb, b, Math.round(q.x - b.w / 2), Math.round(q.y - b.h / 2), a, flut, q.flip, q.clip ? s.back.cls : null, q.slant || 0);
    }
  }
  /** A short, fading trail behind the board; it belongs to the wave, not the sky or distant sea. */
  function drawWake(s, wake) {
    const { fb, back, foamLut } = s;
    for (let i = 1; i < wake.length; i++) {
      const a0 = wake[i - 1], b0 = wake[i], dx = b0.x - a0.x, dy = b0.y - a0.y, n = Math.ceil(Math.max(Math.abs(dx), Math.abs(dy)));
      if (n > 9 || n < 1) continue;
      const a = Math.round(256 * Math.max(0, 1 - b0.age / 76) * 0.8);
      for (let k = 0; k <= n; k++) {
        const x = Math.round(a0.x + dx * k / n), y = Math.round(a0.y + dy * k / n);
        if (x < 0 || x >= W || y < 0 || y >= LIM) continue;
        if (back.cls[y * W + x] === CLS.WATER) putA(fb, x, y, foamLut[28], a);
        if (y + 1 < LIM && back.cls[(y + 1) * W + x] === CLS.WATER) putA(fb, x, y + 1, foamLut[20], a >> 1);
      }
    }
  }

  /** Broken, moving water along the near rail, only while the board touches
   *  the wave. It is painted before the rider so the board stays legible. */
  function drawBoardContact(s, world) {
    const rider = world.surfer;
    if (rider.hidden || rider.air || rider.hop || !['stand', 'popup'].includes(rider.mode)) return;
    const {fb, back, foamLut} = s, tm = world.steps;
    for (let along = -BOARD_HALF + 2; along <= BOARD_HALF - 2; along += 1.3) {
      const u = (along + BOARD_HALF) / (2 * BOARD_HALF);
      const width = Math.sin(Math.PI * u) * (4.6 + 1.8 * (1 - u));
      const [px, py] = boardPoint(rider, along, width + 1.4);
      const x = Math.round(px), y = Math.round(py + 1.5);
      const flicker = Math.sin(along * .6 - tm * .19) + Math.sin(along * .23 + tm * .11);
      if (flicker < -.55 || x < 0 || x >= W || y < 0 || y >= LIM || back.cls[y * W + x] !== CLS.WATER) continue;
      putA(fb, x, y, foamLut[27], 145 + Math.round(35 * Math.max(0, flicker)));
      if (flicker > 1 && y + 1 < LIM && back.cls[(y + 1) * W + x] === CLS.WATER) putA(fb, x, y + 1, foamLut[21], 85);
    }
  }

  function renderFrame(s) {
    const world = s.world, fb = s.fb, back = s.back, geom = back.geom, st = world.steps;
    LIM = s.lim;
    const wp = Math.floor(world.phase), dockKey = Math.round(s.dock * 40);
    if (s.warpStep !== Math.floor(wp / 4) || s.baseLim < LIM || s.baseDock !== dockKey) {
      const stable = dockKey >= 40 ? s.rgbDock : dockKey <= 0 ? back.rgb : null;                                   // the steady states use a backdrop baked with or without the scrim; only the easing darkens on the fly
      applyWarp(s.base, back, s.warp, wp, LIM, stable);
      if (!stable) applyScrim(s.base, s.scrim, s.dock);
      for (const c of world.clouds) { const b = s.cloudSprites[c.kind % s.cloudSprites.length]; drawCloud(s.base, back, b, c.x - (b.w >> 1), c.y); }                      // clouds are part of the cached layer: they move a pixel every several steps
      s.warpStep = Math.floor(wp / 4); s.baseLim = LIM; s.baseDock = dockKey;
    }          // the warp is slow: refreshed every second step
    fb.set(LIM >= H ? s.base : s.base.subarray(0, LIM * W));
    drawSunGlow(s, world);
    // the sky: stars (dim, a few twinkle), clouds that drift over it, the far islet with its palms, the boat, tiny birds
    const star = hexPack('#d6c6f2'), bright = hexPack('#ffffff');
    for (const q of world.stars) {
      const ph = (st + q.phase) % q.period, i = q.y * W + q.x;
      if (i >= LIM * W) continue;
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
    drawVeil(s, world);                                                                                          // the curtain falls behind him: his face is never behind a streak
    drawParticles(s, world, 1);                                                                                  // the curtain's streaks fall behind him
    drawBoardContact(s, world);
    drawSurferFrame(s, world);
    drawFoamItems(s, world, 'front');
    drawParticles(s, world, 0);
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
      const pixels = atlasPixels(api), back = readPlate(api.json, pixels) || makeBackdrop(rand), noise = makeNoise(rand);
      const world = createWorld({ random: rand, back, goldList: findGold(back) });
      const s = { back, world, warp: buildWarp(back.cls, back.geom, back.rgb), brushes: readAtlasBrushes(api.json, pixels) || makeBrushes(noise), foamLut: buildFoamLut(), spal: surferPalette(), rim: null, raster: makeRaster(128, 112),
        cloudSprites: [makeCloud(noise, 62, 12, 1), makeCloud(noise, 44, 9, 2), makeCloud(noise, 76, 13, 3), makeCloud(noise, 100, 15, 4), makeCloud(noise, 72, 11, 5)], tmp: new Uint32Array(W * H), scrim: makeScrim(), swells: makeSwells(rand, back.geom), dock: dockFor(viewBottom(api)), lim: H, stepAt: 0, joints: null, base: new Uint32Array(W * H), warpStep: -1, baseLim: 0 };
      s.img = typeof ImageData === 'function' ? new ImageData(W, H) : null;
      s.fb = s.img ? new Uint32Array(s.img.data.buffer) : new Uint32Array(W * H);
      s.rim = rimPalette(s.spal);
      bakeRays(back);
      s.rgbDock = back.rgb.slice(); applyScrim(s.rgbDock, s.scrim, 1);
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
    createWorld, renderFrame, drawWake, drawBoardContact, boardPoint, drawSwell, drawSurferFrame, blendPose, bend, figure, followPose, FOLLOW, MOVES, SEQUENCES, START, projectDeck, deckPitch, drawStanding, standingJoints, drawPopUp, drawPaddler, drawSwimmer, drawBoard, surferPalette, rimPalette, makeRaster, blitRaster, pitchFor, quantise,
    makeBrush, makeBrushes, readAtlasBrushes, buildFoamLut, makeGull, gullShape, wingAngles, stepGull, makeCloud, makeScrim, makeCraft, GULL_TURN, applyScrim, readPalm, palmOffset, dress, drawHead, makeBeach, beachEdge, setState, SET_LEN, SET_BURST, shiftFrame, makeDolphin, dolphinAt, rowsFor, dockFor, atlasPixels,
  };
  if (global.TabletGames && typeof global.TabletGames.define === 'function') global.TabletGames.define('surf', scene);
  if (typeof module !== 'undefined' && module.exports) module.exports = Object.assign({ scene }, logic);
}(typeof window !== 'undefined' ? window : globalThis));
