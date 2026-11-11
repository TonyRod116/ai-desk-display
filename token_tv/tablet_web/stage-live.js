/*
 * Live effects for the scene stage (window.SceneStageLive): real-time life for the photo look and touch for every look. WebGL 1 only.
 *
 * What lives here
 *   - the scene's optional `live` block (private manifest, checked by token_tv/tablet_live.py and once more by normalizeLive below):
 *     water (rippling refraction and moving glints), clouds (a slow sway and drifting light), lights (windows, lamps and stars that
 *     breathe and go out for a while), mist, light rain, a few craft or gulls crossing the sky and, the one effect that carries data, lamps (rows of small
 *     lamp modules that light with a provider's weekly quota left, from the readings the page hands the stage). Positions are fractions of the
 *     PICTURE and sizes fractions of its HEIGHT, so one preset suits every screen.
 *   - the touch bank: stage.poke(x, y) makes a ring on water, sparkles and a glow elsewhere, and a bump with sparks on the pixel looks.
 *   - pure helpers (region masks, craft paths, poke life, sparkles) that the tests run in Node, and the GLSL the looks compile.
 *
 * How the photo look uses it (stage-photo.js), built for a weak GPU (the tablet reports a Mali-T860): NOT a per-pixel effect shader. A still picture is baked ONCE (grade,
 * bloom, vignette) into a render target the size of the canvas, and a frame is: the baked picture, one read per pixel (a film is read directly and graded in the same
 * pass); two coarse meshes over the water and the sky, whose vertices only change where the picture is read (one more read per pixel of their own area, no mask texture:
 * the region weights are vertex data); then small things drawn over it: point sprites for the twinkling lights (each redraws its few pixels, a light that goes out becomes
 * the wall around it) and the glints, soft blobs for mist, lines for rain, small quads for the craft. No loop anywhere in a fragment shader, nothing blurred per frame,
 * nothing below the picture slot (a scissor). The tier sets only counts and the frame rate (BUDGET): high and medium 30 fps with everything, light 24 fps with coarser,
 * sparser effects, low 20 fps with a few lights and craft (or a slow drift of the baked picture, one read), css draws no live effect at all.
 *
 * No network, no eval, no inline markup; shaders are strings. Times are wrapped at 1000 s and every frequency is a whole number of
 * thousandths of a hertz, so the wrap is seamless.
 */
(function (global) {
  'use strict';

  const TAU = Math.PI * 2;
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const smooth = (t) => t * t * (3 - 2 * t);
  const fract1 = (v) => v - Math.floor(v);

  /* ------------------------------------------------------------------------------------------------ the schema */

  const VERSION = 1;
  const MAX_REGIONS = 8, MAX_POINTS = 24, MAX_CRAFT = 4, MAX_SIDE = 512;
  // name -> [low, high, default]; the same numbers as token_tv/tablet_live.py (SPECS)
  const LIMITS = {
    water: { amount: [0, 2, 1], speed: [0.25, 3, 1], scale: [0.5, 3, 1], glints: [0, 2, 1], glint_size: [0.1, 2, 1], glint_density: [0, 1, 1], feather: [0.002, 0.08, 0.02] },
    clouds: { amount: [0, 2, 1], speed: [0.25, 3, 1], direction: [-180, 180, 0], breath: [0, 2, 1], feather: [0.002, 0.1, 0.03] },
    lights: { amount: [0, 2, 1], speed: [0.25, 3, 1], out: [0, 0.5, 0.25], cell: [3, 60, 9] },
    mist: { amount: [0, 1, 0.5], speed: [0.25, 3, 1], scale: [0.5, 3, 1], feather: [0.002, 0.15, 0.04] },
    rain: { amount: [0, 1, 0.5], speed: [0.25, 3, 1], angle: [-45, 45, 10] },
  };
  const NEEDS_REGIONS = { water: true, clouds: true, mist: true, lights: false, rain: false };
  const TINT = { water: null, mist: [0.70, 0.76, 0.90], rain: [0.70, 0.80, 1.0] };
  const CRAFT = {
    kinds: ['ship', 'drone', 'gull', 'swallow'],
    size: { ship: 0.03, drone: 0.012, gull: 0.028, swallow: 0.013 },
    count: { ship: [1, 1], drone: [1, 1], gull: [1, 6], swallow: [1, 2] },
    colour: { ship: [0.35, 0.80, 1.0], drone: [1.0, 0.30, 0.25], gull: [0.96, 0.97, 1.0], swallow: [0.25, 0.31, 0.34] },
    seconds: [8, 300, 60], sizeRange: [0.008, 0.12], bob: [0, 0.05, 0.006], flap: [0.3, 2.5, 1.1], delay: [0, 900, 0],
  };
  // lamps: rows of small lamp modules that light with a provider's weekly quota left (the same numbers as token_tv/tablet_live.py)
  const LAMPS = {
    providers: ['codex', 'claude'], maxRows: 4, count: [2, 64], height: [0.004, 0.05, 0.0125], amount: [0, 2, 1], anchors: ['start', 'end'], defaultCount: 26,
    colour: { codex: [1.0, 0.725, 0.27], claude: [0.318, 0.863, 1.0] },
    staleMs: 45000,            // the page asks every few seconds; a reading not renewed for this long is not shown (unknown, never an old number)
    minLit: 0.4,               // modules: any quota left shows at least a little light
  };
  // how far an effect moves the picture, in picture heights, for amount = 1 (the rest of the shader works in the same units)
  const AMP = { water: 0.0045, clouds: 0.0160 };
  const EFFECTS = ['water', 'clouds', 'lights', 'mist', 'rain'];

  const isObject = (v) => v && typeof v === 'object' && !Array.isArray(v);
  const num = (v, range) => (finite(v) ? clamp(v, range[0], range[1]) : range[2]);
  const r4 = (v) => Math.round(v * 10000) / 10000;

  function normalizeRegion(value) {
    if (!Array.isArray(value) || !value.length) return null;
    if (value.every(finite)) {
      if (value.length !== 4) return null;
      const [x0, y0, x1, y1] = value.map((v) => r4(clamp(v, 0, 1)));
      return x0 < x1 && y0 < y1 ? [x0, y0, x1, y1] : null;
    }
    if (value.length < 3 || value.length > MAX_POINTS) return null;
    const pts = [];
    for (const p of value) {
      if (!Array.isArray(p) || p.length !== 2 || !p.every(finite)) return null;
      pts.push([r4(clamp(p[0], 0, 1)), r4(clamp(p[1], 0, 1))]);
    }
    let area = 0;
    for (let i = 0; i < pts.length; i++) { const a = pts[i], b = pts[(i + 1) % pts.length]; area += a[0] * b[1] - b[0] * a[1]; }
    return Math.abs(area) / 2 >= 1e-5 ? pts : null;
  }

  function regionsTop(regions) {
    let top = 1;
    for (const r of regions) top = Math.min(top, typeof r[0] === 'number' ? r[1] : Math.min(...r.map((p) => p[1])));
    return top;
  }

  function normalizeTint(value, fallback) {
    return Array.isArray(value) && value.length === 3 && value.every(finite) ? value.map((v) => r4(clamp(v, 0, 1))) : fallback ? fallback.slice() : null;
  }

  function normalizeEffect(name, raw) {
    if (!isObject(raw)) return null;
    const out = {};
    if (Array.isArray(raw.regions)) {
      const regions = raw.regions.slice(0, MAX_REGIONS).map(normalizeRegion);
      if (!regions.length || regions.some((r) => !r)) return null;
      out.regions = regions;
    } else if (NEEDS_REGIONS[name]) return null;
    for (const key of Object.keys(LIMITS[name])) out[key] = r4(num(raw[key], LIMITS[name][key]));
    if (name === 'water') out.horizon = finite(raw.horizon) ? r4(clamp(raw.horizon, 0, 1)) : r4(regionsTop(out.regions));
    const tint = normalizeTint(raw.tint, TINT[name]);
    if (tint) out.tint = tint;
    return out;
  }

  function normalizeCraft(raw) {
    if (!isObject(raw) || !CRAFT.kinds.includes(raw.kind)) return null;
    const point = (p) => (Array.isArray(p) && p.length === 2 && p.every(finite) ? [r4(clamp(p[0], -0.3, 1.3)), r4(clamp(p[1], -0.3, 1.3))] : null);
    const from = point(raw.from), to = point(raw.to);
    if (!from || !to || (from[0] === to[0] && from[1] === to[1])) return null;
    const kind = raw.kind, seconds = r4(num(raw.seconds, CRAFT.seconds));
    const [cLo, cHi] = CRAFT.count[kind];
    const count = finite(raw.count) ? clamp(Math.round(raw.count), cLo, cHi) : Math.min(3, cHi);
    return {
      kind, from, to, seconds, count,
      size: finite(raw.size) ? r4(clamp(raw.size, CRAFT.sizeRange[0], CRAFT.sizeRange[1])) : CRAFT.size[kind],
      every: finite(raw.every) ? r4(clamp(raw.every, seconds, 900)) : r4(seconds * 1.7),
      delay: r4(num(raw.delay, CRAFT.delay)), bob: r4(num(raw.bob, CRAFT.bob)), flap: r4(num(raw.flap, CRAFT.flap)),
      colour: normalizeTint(raw.colour, CRAFT.colour[kind]),
    };
  }

  function normalizeLampRow(raw) {
    if (!isObject(raw) || !LAMPS.providers.includes(raw.provider)) return null;
    if (!Array.isArray(raw.x) || raw.x.length !== 2 || !raw.x.every((v) => finite(v) && v >= 0 && v <= 1)) return null;
    const left = r4(raw.x[0]), right = r4(raw.x[1]);
    if (right - left < 0.02 || !finite(raw.y) || raw.y < 0 || raw.y > 1) return null;
    const count = raw.count === undefined ? LAMPS.defaultCount : raw.count;
    if (!Number.isInteger(count) || count < LAMPS.count[0] || count > LAMPS.count[1]) return null;
    const anchor = raw.anchor === undefined ? (raw.provider === 'codex' ? 'start' : 'end') : raw.anchor;
    if (!LAMPS.anchors.includes(anchor)) return null;
    return { provider: raw.provider, x: [left, right], y: r4(raw.y), count, height: r4(num(raw.height, LAMPS.height)), anchor, colour: normalizeTint(raw.colour, LAMPS.colour[raw.provider]) };
  }

  /** Rows of lamps for the weekly quota: one bad row drops the whole effect (half a circuit would read as a half-empty quota). */
  function normalizeLamps(raw) {
    if (!isObject(raw) || !Array.isArray(raw.rows) || raw.rows.length < 1 || raw.rows.length > LAMPS.maxRows) return null;
    const rows = raw.rows.map(normalizeLampRow);
    if (rows.some((r) => !r)) return null;
    return { amount: r4(num(raw.amount, LAMPS.amount)), rows };
  }

  /** The page's own second check of a scene's `live` block: clamps numbers, drops what cannot be understood, null when nothing is left. */
  function normalizeLive(raw) {
    if (!isObject(raw)) return null;
    const out = { version: VERSION };
    let any = false;
    for (const name of EFFECTS) {
      const effect = normalizeEffect(name, raw[name]);
      if (effect) { out[name] = effect; any = true; }
    }
    if (Array.isArray(raw.craft)) {
      const craft = raw.craft.slice(0, MAX_CRAFT).map(normalizeCraft).filter(Boolean);
      if (craft.length) { out.craft = craft; any = true; }
    }
    if (raw.lamps !== undefined) {
      const lamps = normalizeLamps(raw.lamps);
      if (lamps) { out.lamps = lamps; any = true; }
    }
    return any ? out : null;
  }

  /** The names of the effects a block switches on, in a fixed order (for the status line and the tests). */
  function effectNames(cfg) {
    if (!cfg) return [];
    const names = EFFECTS.filter((n) => cfg[n]);
    if (cfg.craft && cfg.craft.length) names.push('craft');
    if (cfg.lamps) names.push('lamps');
    return names;
  }

  /* ------------------------------------------------------------------------------------------------ lamps: the quota as light */

  /** The week left (a percentage) each provider's lamps may show: from a reading the page renewed within the last 45 s whose week has not rolled over, else null (unknown is never zero).
   *  `readings` is the page's latest `/api/status`; `ageMs` how long ago the page handed it over (omitted: fresh). */
  function lampReadings(readings, nowMs, ageMs) {
    const out = { codex: null, claude: null };
    if (!readings || typeof readings !== 'object' || (finite(ageMs) && ageMs > LAMPS.staleMs)) return out;
    const providers = readings.providers;
    if (!providers || typeof providers !== 'object') return out;
    for (const name of LAMPS.providers) {
      const week = providers[name] && providers[name].weekly;
      if (week && typeof week === 'object' && finite(week.remaining) && week.remaining >= 0 && week.remaining <= 100 && finite(week.resets_at) && week.resets_at * 1000 > nowMs) out[name] = week.remaining;
    }
    return out;
  }

  /** How many modules of a row are lit, counted from its outer (anchored) end and fractional (the lit length follows the quota even inside a lamp): 0 for nothing left, at least a
   *  little while anything is, all of them at 100, and null for an unknown reading. */
  function lampLit(count, remaining) {
    if (!finite(remaining) || remaining < 0 || remaining > 100) return null;
    if (remaining <= 0) return 0;
    return clamp(Math.max(count * remaining / 100, LAMPS.minLit), 0, count);
  }

  /** What each row of a lamps block shows now: its geometry and colour plus `lit` (modules from the anchor, null = unknown). */
  function lampPlan(lamps, readings, nowMs, ageMs) {
    if (!lamps || !Array.isArray(lamps.rows)) return [];
    const week = lampReadings(readings, nowMs, ageMs);
    return lamps.rows.map((row) => ({ provider: row.provider, x: row.x, y: row.y, count: row.count, height: row.height, anchor: row.anchor, colour: row.colour, lit: lampLit(row.count, week[row.provider]) }));
  }

  /* ------------------------------------------------------------------------------------------------ region masks */

  function fillPolygon(mask, w, h, points) {
    const n = points.length, xs = [];
    for (let y = 0; y < h; y++) {
      const sy = (y + 0.5) / h;
      xs.length = 0;
      for (let i = 0; i < n; i++) {
        const a = points[i], b = points[(i + 1) % n];
        if ((a[1] <= sy) === (b[1] <= sy)) continue;
        xs.push(a[0] + (sy - a[1]) / (b[1] - a[1]) * (b[0] - a[0]));
      }
      xs.sort((p, q) => p - q);
      for (let k = 0; k + 1 < xs.length; k += 2) {
        const x0 = clamp(Math.round(xs[k] * w - 0.5), 0, w), x1 = clamp(Math.round(xs[k + 1] * w - 0.5), 0, w);
        for (let x = x0; x < x1; x++) mask[y * w + x] = 1;
      }
    }
  }

  function fillRegions(mask, w, h, regions) {
    for (const r of regions) {
      if (typeof r[0] === 'number') fillPolygon(mask, w, h, [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]);
      else fillPolygon(mask, w, h, r);
    }
  }

  /** One running-sum box blur along rows then columns; outside the picture counts as its edge, so a region that reaches the border keeps full weight there. */
  function boxBlur(data, w, h, radius) {
    const r = Math.max(0, Math.floor(radius));
    if (r < 1) return data;
    const tmp = new Float32Array(data.length), span = 2 * r + 1;
    for (let y = 0; y < h; y++) {
      const row = y * w;
      let sum = data[row] * (r + 1);
      for (let x = 1; x <= r; x++) sum += data[row + Math.min(x, w - 1)];
      for (let x = 0; x < w; x++) {
        tmp[row + x] = sum / span;
        sum += data[row + Math.min(x + r + 1, w - 1)] - data[row + Math.max(x - r, 0)];
      }
    }
    for (let x = 0; x < w; x++) {
      let sum = tmp[x] * (r + 1);
      for (let y = 1; y <= r; y++) sum += tmp[Math.min(y, h - 1) * w + x];
      for (let y = 0; y < h; y++) {
        data[y * w + x] = sum / span;
        sum += tmp[Math.min(y + r + 1, h - 1) * w + x] - tmp[Math.max(y - r, 0) * w + x];
      }
    }
    return data;
  }

  /** The feather an effect really gets: never less than the farthest it moves the picture, so a pixel never fetches across its region's edge. */
  function effectiveFeather(name, effect) {
    const amp = (AMP[name] || 0) * (effect.amount || 0);
    return Math.max(effect.feather || 0.02, amp * 1.6);
  }

  /** RGBA region masks for a picture of this aspect (width / height): R water, G clouds, B mist, A where the lights may twinkle. Row 0 is the top. */
  function rasterRegions(cfg, aspect, maxSide) {
    const side = maxSide || MAX_SIDE;
    const w = aspect >= 1 ? side : Math.max(16, Math.round(side * aspect));
    const h = aspect >= 1 ? Math.max(16, Math.round(side / aspect)) : side;
    const data = new Uint8Array(w * h * 4);
    const channel = (index, name) => {
      const effect = cfg && cfg[name];
      if (!effect || !effect.regions) return;
      const m = new Float32Array(w * h);
      fillRegions(m, w, h, effect.regions);
      const radius = effectiveFeather(name, effect) * h;
      boxBlur(m, w, h, radius * 0.55); boxBlur(m, w, h, radius * 0.55);
      for (let i = 0; i < m.length; i++) { const t = clamp((m[i] - 0.5) * 2, 0, 1); data[i * 4 + index] = Math.round(255 * smooth(t)); }
    };
    channel(0, 'water'); channel(1, 'clouds'); channel(2, 'mist');
    const lights = cfg && cfg.lights;
    if (lights && lights.regions) {
      const m = new Float32Array(w * h);
      fillRegions(m, w, h, lights.regions);
      boxBlur(m, w, h, 0.012 * h * 0.55); boxBlur(m, w, h, 0.012 * h * 0.55);
      for (let i = 0; i < m.length; i++) data[i * 4 + 3] = Math.round(255 * smooth(clamp((m[i] - 0.5) * 2, 0, 1)));
    } else for (let i = 0; i < w * h; i++) data[i * 4 + 3] = 255;
    return { w, h, data };
  }

  /** The weight (0..1) of one channel (0 water, 1 clouds, 2 mist, 3 lights) of a raster at a picture position (u, v in 0..1). */
  function regionWeightAt(raster, index, u, v) {
    if (!raster || !finite(u) || !finite(v)) return 0;
    const x = clamp(Math.floor(u * raster.w), 0, raster.w - 1), y = clamp(Math.floor(v * raster.h), 0, raster.h - 1);
    return raster.data[(y * raster.w + x) * 4 + index] / 255;
  }

  /* ------------------------------------------------------------------------------------------------ craft and gulls */

  const hash1 = (n) => { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };

  /** Where each craft is at `seconds`: a straight, calm crossing from `from` to `to` in `seconds`, then a quiet spell until `every` has passed.
   *  Positions are picture fractions; `heading` is in picture-height units (x is stretched by the aspect), `alpha` fades the ends. */
  function craftState(craft, seconds, aspect) {
    const out = [];
    if (!craft) return out;
    for (let i = 0; i < craft.length && out.length < MAX_CRAFT; i++) {
      const c = craft[i];
      const cycle = seconds - c.delay;
      if (cycle < 0) continue;
      const u = (cycle % c.every) / c.seconds;
      if (u > 1) continue;
      const dx = (c.to[0] - c.from[0]) * aspect, dy = c.to[1] - c.from[1];
      const bob = c.bob * Math.sin(TAU * (seconds * 0.071 + hash1(i + 1)));
      out.push({
        kind: c.kind, index: i, u,
        x: c.from[0] + (c.to[0] - c.from[0]) * u, y: c.from[1] + (c.to[1] - c.from[1]) * u + bob,
        heading: Math.atan2(dy, dx), size: c.size, count: c.count, flap: c.flap,
        alpha: smooth(clamp(u / 0.04, 0, 1)) * smooth(clamp((1 - u) / 0.04, 0, 1)),
        phase: hash1(i * 7.7 + 2) * TAU, colour: c.colour,
      });
    }
    return out;
  }

  /* ------------------------------------------------------------------------------------------------ touch */

  const POKE = { max: 3, ripple: 2.8, glow: 1.5, bump: 1.3, minGap: 0.10, minDistance: 10, sparkles: 8, sparks: 10 };

  /** The few touches that are alive. Pure: times are seconds on any clock the caller keeps; ages come from the same clock. */
  class PokeBank {
    constructor(max) { this.max = max || POKE.max; this.items = []; this.seed = 1; }
    life(kind) { return kind === 'ripple' ? POKE.ripple : kind === 'bump' ? POKE.bump : POKE.glow; }
    /** Add a touch at (x, y) CSS px; false when it is ignored (too soon after the last one, in nearly the same place). */
    add(x, y, now, kind) {
      if (!finite(x) || !finite(y) || !finite(now)) return false;
      const last = this.items[this.items.length - 1];
      if (last && now - last.t0 < POKE.minGap && Math.hypot(x - last.x, y - last.y) < POKE.minDistance) return false;
      this.prune(now);
      if (this.items.length >= this.max) this.items.shift();
      this.items.push({ x, y, t0: now, kind: kind || 'glow', seed: this.seed++ });
      return true;
    }
    prune(now) { this.items = this.items.filter((p) => now - p.t0 < this.life(p.kind) && now >= p.t0 - 0.5); }
    alive(now) { return this.items.some((p) => now - p.t0 < this.life(p.kind) && now >= p.t0 - 0.5); }
    /** The live touches with their ages, oldest first. */
    list(now) { this.prune(now); return this.items.map((p) => ({ x: p.x, y: p.y, age: Math.max(0, now - p.t0), kind: p.kind, seed: p.seed })); }
    clear() { this.items = []; }
  }

  /** Soft sparkles around a touch: up to 8 of (x, y, size, alpha), CSS px, each born a little after the last, rising slowly and fading. */
  function sparkles(poke, age, out) {
    const list = out || [];
    list.length = 0;
    for (let i = 0; i < POKE.sparkles; i++) {
      const delay = i * 0.07, life = 0.95, a = (age - delay) / life;
      if (a <= 0 || a >= 1) continue;
      const angle = hash1(poke.seed * 13.1 + i * 3.7) * TAU, radius = 18 + hash1(poke.seed * 7.3 + i * 5.1) * 74;
      list.push({ x: poke.x + Math.cos(angle) * radius, y: poke.y + Math.sin(angle) * radius - 14 * a, size: 3 + 4 * hash1(poke.seed + i * 9.9),
        alpha: Math.pow(Math.sin(Math.PI * a), 1.4) });
    }
    return list;
  }

  /** Pixel sparks for the CRT and LCD looks: up to 10 of (x, y, size, alpha, heat), CSS px; they fly out, fall a little and cool. */
  function sparks(poke, age, out) {
    const list = out || [];
    list.length = 0;
    for (let i = 0; i < POKE.sparks; i++) {
      const life = 0.55 + 0.35 * hash1(poke.seed * 3.3 + i * 1.9), a = age / life;
      if (a >= 1) continue;
      const angle = (i / POKE.sparks) * TAU + hash1(poke.seed + i * 4.4) * 0.6, speed = 70 + 90 * hash1(poke.seed * 5.5 + i * 2.2);
      list.push({ x: poke.x + Math.cos(angle) * speed * age, y: poke.y + Math.sin(angle) * speed * age + 160 * age * age, size: 1, alpha: 1 - a * a, heat: 1 - a });
    }
    return list;
  }

  /* ------------------------------------------------------------------------------------------------ what each tier pays for */

  // scene-stage.js LEVELS: 0 high, 1 medium, 2 light, 3 low. The numbers are COUNTS OF SMALL THINGS, never per-pixel work: the cell size (device px) of the
  // two meshes (0: none), the most light sprites, glint sprites, mist blobs, rain streaks and craft, and the frame rate the loop aims at.
  const BUDGET = [
    { cell: 8, lights: 3000, glints: 170, mist: 6, rain: 420, craft: 4, fps: 30 },
    { cell: 8, lights: 3000, glints: 170, mist: 6, rain: 420, craft: 4, fps: 30 },
    { cell: 12, lights: 1000, glints: 70, mist: 3, rain: 180, craft: 2, fps: 24 },
    { cell: 0, lights: 300, glints: 0, mist: 0, rain: 0, craft: 2, fps: 20 },
  ];
  const budgetFor = (level) => BUDGET[clamp(Math.round(finite(level) ? level : 0), 0, BUDGET.length - 1)];
  const intervalFor = (level) => 1000 / budgetFor(level).fps;

  /* ------------------------------------------------------------------------------------------------ geometry (pure)
   * The effects are not a per-pixel shader. A still picture is baked once; each frame is the baked picture (one read per pixel), then two coarse meshes
   * over the water and the sky whose vertices only shift where the picture is read (one read per pixel of their own area), then small sprites: the
   * twinkling lights, the glints, the mist blobs, the rain streaks and the craft. */

  function rng(seed) {
    let a = (seed >>> 0) || 1;
    return () => { a = (a + 0x6D2B79F5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }

  /** Bilinear weight (0..1) of one raster channel at a picture position, so a vertex between two texels gets a smooth value. */
  function weightBilinear(raster, index, u, v) {
    if (!raster || !finite(u) || !finite(v)) return 0;
    const x = clamp(u * raster.w - 0.5, 0, raster.w - 1), y = clamp(v * raster.h - 0.5, 0, raster.h - 1);
    const x0 = Math.floor(x), y0 = Math.floor(y), x1 = Math.min(raster.w - 1, x0 + 1), y1 = Math.min(raster.h - 1, y0 + 1), fx = x - x0, fy = y - y0;
    const at = (xx, yy) => raster.data[(yy * raster.w + xx) * 4 + index];
    return ((at(x0, y0) * (1 - fx) + at(x1, y0) * fx) * (1 - fy) + (at(x0, y1) * (1 - fx) + at(x1, y1) * fx) * fy) / 255;
  }

  /** The canvas rectangle (device px) the regions of an effect cover, cut to the canvas and to `bottom` (nothing below the picture slot is worth drawing). Null when too small. */
  function effectRect(regions, pic, width, bottom) {
    if (!regions || !regions.length) return null;
    let u0 = 1, v0 = 1, u1 = 0, v1 = 0;
    for (const r of regions) {
      const pts = typeof r[0] === 'number' ? [[r[0], r[1]], [r[2], r[3]]] : r;
      for (const p of pts) { u0 = Math.min(u0, p[0]); u1 = Math.max(u1, p[0]); v0 = Math.min(v0, p[1]); v1 = Math.max(v1, p[1]); }
    }
    const x0 = Math.max(0, pic.x + u0 * pic.w), y0 = Math.max(0, pic.y + v0 * pic.h), x1 = Math.min(width, pic.x + u1 * pic.w), y1 = Math.min(bottom, pic.y + v1 * pic.h);
    return x1 - x0 >= 8 && y1 - y0 >= 8 ? { x0, y0, x1, y1 } : null;
  }

  /** A regular grid of vertices over `rect` with cells of about `cell` px: Float32Array of [x, y, a, b] (canvas px and two numbers from `at(x, y)`), Uint16Array triangles. */
  function buildGrid(rect, cell, at, maxX, maxY) {
    const w = rect.x1 - rect.x0, h = rect.y1 - rect.y0;
    const nx = clamp(Math.ceil(w / cell), 1, maxX || 120), ny = clamp(Math.ceil(h / cell), 1, maxY || 64);
    const verts = new Float32Array((nx + 1) * (ny + 1) * 4), idx = new Uint16Array(nx * ny * 6);
    for (let iy = 0; iy <= ny; iy++) {
      for (let ix = 0; ix <= nx; ix++) {
        const x = rect.x0 + w * ix / nx, y = rect.y0 + h * iy / ny, ab = at(x, y), k = (iy * (nx + 1) + ix) * 4;
        verts[k] = x; verts[k + 1] = y; verts[k + 2] = ab[0]; verts[k + 3] = ab[1];
      }
    }
    let n = 0;
    for (let iy = 0; iy < ny; iy++) {
      for (let ix = 0; ix < nx; ix++) {
        const a = iy * (nx + 1) + ix, b = a + 1, c = a + nx + 1, d = c + 1;
        idx[n++] = a; idx[n++] = b; idx[n++] = c; idx[n++] = b; idx[n++] = d; idx[n++] = c;
      }
    }
    return { verts, idx, nx, ny, vertices: (nx + 1) * (ny + 1), count: n, area: w * h };
  }

  /** The small lights of a picture, from the detection pass read back once: local maxima of the R channel (small bright spots), strongest first, kept only where the
   *  lights may twinkle and not under the water or the sky mesh (a sprite there would draw the picture un-shifted). Float32Array of [u, v, size (picture heights), seed]. */
  function extractLights(buf, w, h, options) {
    const o = options || {}, floor = o.threshold || 46, found = [];
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const i = (y * w + x) * 4, v = buf[i];
        if (v < floor) continue;
        // a local maximum, ties broken towards the earlier texel so a flat top gives one light, not four
        let top = true, sum = 0, cx = 0, cy = 0, big = 0;
        for (let dy = -1; dy <= 1 && top; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            if (!dx && !dy) continue;
            const n = buf[((y + dy) * w + x + dx) * 4];
            if (n > v || (n === v && (dy < 0 || (dy === 0 && dx < 0)))) { top = false; break; }
          }
        }
        if (!top) continue;
        for (let dy = -2; dy <= 2; dy++) {
          for (let dx = -2; dx <= 2; dx++) {
            const xx = x + dx, yy = y + dy;
            if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue;
            const n = buf[(yy * w + xx) * 4];
            if (n >= v * 0.5) { big++; if (Math.abs(dx) <= 1 && Math.abs(dy) <= 1) { sum += n; cx += n * dx; cy += n * dy; } }
          }
        }
        const u = (x + 0.5 + (sum ? cx / sum : 0)) / w, vv = (y + 0.5 + (sum ? cy / sum : 0)) / h;
        if (o.raster) {
          if (regionWeightAt(o.raster, 3, u, vv) < 0.5 || regionWeightAt(o.raster, 0, u, vv) > 0.15 || regionWeightAt(o.raster, 1, u, vv) > 0.15) continue;
        }
        found.push([v, u, vv, (Math.sqrt(big) + 2.4) / h]);
      }
    }
    found.sort((a, b) => b[0] - a[0]);
    const n = Math.min(found.length, o.max || 3000), out = new Float32Array(n * 4);
    for (let i = 0; i < n; i++) { out[i * 4] = found[i][1]; out[i * 4 + 1] = found[i][2]; out[i * 4 + 2] = found[i][3]; out[i * 4 + 3] = hash1(i + 0.5); }
    return out;
  }

  /** Glints: small points scattered over the water, each with its own seed; Float32Array of [u, v, size (picture heights), seed]. Deterministic. */
  function placeGlints(raster, count, seed) {
    const out = new Float32Array(Math.max(0, count) * 4), next = rng(seed);
    let n = 0;
    for (let tries = 0; n < count && tries < count * 40; tries++) {
      const u = next(), v = next();
      if (weightBilinear(raster, 0, u, v) < 0.6) continue;
      out[n * 4] = u; out[n * 4 + 1] = v; out[n * 4 + 2] = 0.0045 + 0.007 * next(); out[n * 4 + 3] = next(); n++;
    }
    return out.subarray(0, n * 4);
  }

  /** Rain: `count` drops, two vertices each (head, tail): [x (0..1 of the canvas), start (0..1), speed (CSS px per second), length (CSS px), end (0 head, 1 tail)]. */
  function placeRain(count, seed) {
    const out = new Float32Array(Math.max(0, count) * 10), next = rng(seed);
    for (let i = 0; i < count; i++) {
      const near = next() < 0.55, x = next(), start = next(), speed = near ? 820 + 260 * next() : 380 + 160 * next(), len = near ? 26 + 22 * next() : 14 + 10 * next();
      for (let e = 0; e < 2; e++) { const k = (i * 2 + e) * 5; out[k] = x; out[k + 1] = start; out[k + 2] = speed; out[k + 3] = len; out[k + 4] = e; }
    }
    return out;
  }

  /** Mist: soft blobs inside the mist region, four corners each: [corner x, corner y, u, v, radius (picture heights), seed]. Deterministic. */
  function placeMist(raster, count, seed) {
    const next = rng(seed), blobs = [];
    for (let tries = 0; blobs.length < count && tries < count * 60; tries++) {
      const u = next(), v = next();
      if (weightBilinear(raster, 2, u, v) < 0.5) continue;
      blobs.push([u, v, 0.07 + 0.08 * next(), next()]);
    }
    const out = new Float32Array(blobs.length * 4 * 6);
    blobs.forEach((b, i) => { [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach((c, k) => out.set([c[0], c[1], b[0], b[1], b[2], b[3]], (i * 4 + k) * 6)); });
    return { data: out, count: blobs.length };
  }

  /** What one frame reads: the baked picture once per pixel, plus once per pixel of each mesh, plus the sprites' own few pixels. Numbers for reasoning, not a speed. */
  function estimateCost(parts) {
    const p = parts, pixels = p.pixels || 0;
    const sprites = (p.lightsPx || 0) + (p.glintsPx || 0) + (p.craftPx || 0);
    const reads = pixels + (p.waterPx || 0) + (p.cloudsPx || 0) + sprites;
    return { pixels, reads: Math.round(reads), readsPerPixel: pixels ? Math.round(reads / pixels * 100) / 100 : 0, meshPixels: Math.round((p.waterPx || 0) + (p.cloudsPx || 0)), spritePixels: Math.round(sprites),
      blendedPixels: Math.round((p.mistPx || 0) + (p.rainPx || 0) + (p.glintsPx || 0)), draws: p.draws || 0, vertices: p.vertices || 0 };
  }

  /* ------------------------------------------------------------------------------------------------ GLSL */

  const HASH_GLSL = 'float h11(float n) { return fract(sin(n * 127.1 + 311.7) * 43758.5453); }\n';

  // the per-picture detection of small lights and larger lit things (run once, read back once)
  const DETECT_FS = function (lib, taps) {
    const fetch = taps
      ? ['  float l0 = luma(texture2D(uTex, tuv).rgb);',
        '  vec2 a = 1.6 * uTexel, b = 4.0 * uTexel, c = 9.0 * uTexel;',
        '  float la = 0.25 * (luma(texture2D(uTex, tuv + a).rgb) + luma(texture2D(uTex, tuv - a).rgb) + luma(texture2D(uTex, tuv + vec2(a.x, -a.y)).rgb) + luma(texture2D(uTex, tuv + vec2(-a.x, a.y)).rgb));',
        '  float lb = 0.25 * (luma(texture2D(uTex, tuv + b).rgb) + luma(texture2D(uTex, tuv - b).rgb) + luma(texture2D(uTex, tuv + vec2(b.x, -b.y)).rgb) + luma(texture2D(uTex, tuv + vec2(-b.x, b.y)).rgb));',
        '  float lc = 0.25 * (luma(texture2D(uTex, tuv + c).rgb) + luma(texture2D(uTex, tuv - c).rgb) + luma(texture2D(uTex, tuv + vec2(c.x, -c.y)).rgb) + luma(texture2D(uTex, tuv + vec2(-c.x, c.y)).rgb));']
      : ['  float l0 = luma(texture2D(uTex, tuv).rgb);',
        '  float la = luma(texture2D(uTex, tuv, 1.5).rgb);',
        '  float lb = luma(texture2D(uTex, tuv, 3.0).rgb);',
        '  float lc = luma(texture2D(uTex, tuv, 5.0).rgb);'];
    return [
      'uniform sampler2D uTex; uniform vec2 uOut; uniform vec2 uUvScale; uniform vec2 uTexel;',
      lib,
      'void main() {',
      '  vec2 uv = gl_FragCoord.xy / uOut;',
      '  vec2 tuv = uv * uUvScale;',
      ...fetch,
      '  float small = smoothstep(0.10, 0.28, l0 - la) * smoothstep(0.20, 0.46, l0);',
      '  float big = smoothstep(0.10, 0.30, lb - lc) * smoothstep(0.28, 0.52, lb) * (1.0 - small);',
      '  gl_FragColor = vec4(small, big, 0.0, 1.0);',
      '}',
    ].join('\n');
  };

  // ---- the picture itself: the baked still (canvas space) or the film (picture space, graded here)
  const BASE_VS = [
    'attribute vec2 aPos; uniform vec4 uXf; uniform vec2 uCtr; varying vec2 vUv;',
    'void main() { gl_Position = vec4(aPos, 0.0, 1.0); vec2 uv = aPos * 0.5 + 0.5; vUv = uCtr + (uv - uCtr) / uXf.x + uXf.yz; }',
  ].join('\n');
  const BASE_FS = 'uniform sampler2D uBase; varying vec2 vUv;\nvoid main() { gl_FragColor = vec4(texture2D(uBase, vUv).rgb, 1.0); }\n';

  /** The film's picture: a graded read (the contrast, saturation and tints of the photo look) and its finish (vignette, fade at the picture's end). */
  function videoGlsl(grade) {
    return [
      'uniform vec2 uUvScale; uniform vec4 uGrade; uniform vec3 uShadow; uniform vec3 uHighlight; uniform vec3 uBaseColour; uniform vec4 uVig; uniform vec4 uArea; uniform vec4 uPic;',
      'vec3 fetchVideo(vec2 q) {',
      // past the film's edge it goes on as its own reflection (the finish below fades it into the page's colour): never the last row dragged downwards
      '  vec3 c = texture2D(uBase, (vec2(1.0) - abs(vec2(1.0) - mod(q, vec2(2.0)))) * uUvScale).rgb;',
      grade ? [
        '  float lum = luma(c);',
        '  c = mix(c, c * c * (3.0 - 2.0 * c), uGrade.x);',
        '  c = mix(vec3(lum), c, 1.0 + uGrade.y);',
        '  c += uShadow * ((1.0 - lum) * (1.0 - lum)) + uHighlight * (lum * lum);'].join('\n') : '',
      '  return min(c, vec3(1.0));',
      '}',
      'vec3 finishVideo(vec3 c, vec2 p) {',
      '  vec2 a2 = (p - (uArea.xy + 0.5 * uArea.zw)) / (0.5 * uArea.zw);',
      '  c *= 1.0 - uVig.x * smoothstep(0.55, 1.45, min(length(a2), 1.6));',
      '  vec2 out2 = max(max(uPic.xy - p, p - (uPic.xy + uPic.zw)), vec2(0.0));',
      '  return mix(c, uBaseColour, smoothstep(0.0, uVig.y, length(out2)));',
      '}',
    ].join('\n');
  }

  const baseVideoVS = [
    'attribute vec2 aPos; uniform vec2 uRes; uniform vec4 uPic; varying vec2 vUv; varying vec2 vP;',
    'void main() { gl_Position = vec4(aPos, 0.0, 1.0); vec2 uv = aPos * 0.5 + 0.5; vec2 p = vec2(uv.x, 1.0 - uv.y) * uRes; vP = p; vUv = (p - uPic.xy) / uPic.zw; }',
  ].join('\n');
  const baseVideoFS = (lib, grade) => ['uniform sampler2D uBase; varying vec2 vUv; varying vec2 vP;', lib, videoGlsl(grade),
    'void main() { gl_FragColor = vec4(finishVideo(fetchVideo(vUv), vP), 1.0); }'].join('\n');

  // ---- the water and the sky: a mesh whose vertices say where the picture is read. Frequencies are whole numbers of thousandths of a hertz, so the clock can wrap.
  const RING_GLSL = [
    'float ringFade(float age) { return exp(-age * 0.85) * smoothstep(0.0, 0.06, age); }',
    // the signed profile of a touch's wave: the picture is pulled one way ahead of the crest and the other way behind it, a lens that travels outward
    'float ringPush(float r, float age, float s) {',
    '  float R = age * 150.0 * s, wd = 13.0 * s;',
    '  float a = (r - R) / wd, b = (r - R * 0.6) / (wd * 1.2);',
    '  return (-a * exp(-a * a) - 0.55 * b * exp(-b * b)) * 2.0 * ringFade(age);',
    '}',
    'vec2 pushOf(vec4 P, vec2 p, float s) {',
    '  if (P.w < 0.5 || P.w > 1.5) return vec2(0.0);',
    '  vec2 dd = p - P.xy; float r = length(dd);',
    '  return (dd / max(r, 1.0)) * (ringPush(r, P.z, s) * 9.0 * s);',
    '}',
  ].join('\n');

  /** The vertex shader of a mesh. `kind` 'water' or 'clouds'; `video`: the film is read in picture space, a still in the baked canvas. */
  function meshVS(kind, video) {
    const head = ['attribute vec2 aPos; attribute vec2 aWD; uniform vec2 uRes; uniform vec4 uPic; uniform vec2 uSize; uniform float uT; uniform vec4 uP[3];',
      kind === 'water' ? 'uniform vec4 uW; uniform vec2 uW2;' : 'uniform vec4 uC;',
      'varying vec2 vUv; varying vec2 vP; varying float vL;', RING_GLSL];
    const common = ['void main() {',
      '  vec2 p = aPos;',
      '  vec2 puv = (p - uPic.xy) / uPic.zw;',
      '  float asp = uSize.x, xh = puv.x * asp, yh = puv.y;'];
    const tail = [
      '  vec2 q = puv + d * vec2(1.0 / asp, 1.0);',
      video ? '  vUv = q;' : '  vec2 s = uPic.xy + q * uPic.zw; vUv = vec2(s.x, uRes.y - s.y) / uRes;',
      '  vP = p;',
      '  gl_Position = vec4(p.x / uRes.x * 2.0 - 1.0, 1.0 - p.y / uRes.y * 2.0, 0.0, 1.0);',
      '}'];
    const body = kind === 'water' ? [
      '  float depth = aWD.y, persp = 0.30 + 0.70 * depth;',
      '  float y0 = yh - uW.w, k = (1.0 + 0.8 * (1.0 - depth)) / uW.y, t = uT;',
      '  float a1 = fract(y0 * 13.0 * k + t * 0.043 + 0.35 * sin(6.2832 * fract(xh * 3.1 / uW.y + t * 0.011)));',
      '  float a2 = fract(y0 * 21.0 * k - t * 0.031 + xh * 5.3 / uW.y);',
      '  float a3 = fract(xh * 7.1 / uW.y + y0 * 9.0 * k + t * 0.023);',
      '  vec2 d = vec2(sin(6.2832 * a1) + 0.6 * sin(6.2832 * a2), 0.45 * sin(6.2832 * a3)) * (uW.x * persp * aWD.x);',
      '  vec2 dpx = pushOf(uP[0], p, uSize.y) + pushOf(uP[1], p, uSize.y) + pushOf(uP[2], p, uSize.y);',
      '  d += dpx / uPic.w * aWD.x;',
      '  vL = 1.0;'] : [
      '  float t = uT;',
      '  float n1 = 0.5 + 0.5 * sin(6.2832 * fract(xh * 0.55 + yh * 0.35 + 0.2 * sin(6.2832 * fract(yh * 0.9 + t * 0.003))));',
      '  float n2 = 0.5 + 0.5 * sin(6.2832 * fract(xh * 0.30 - yh * 0.50 + 0.37 - t * 0.002));',
      '  float s1 = sin(6.2832 * fract(t * 0.016 + n1 * 0.7)), s2 = sin(6.2832 * fract(t * 0.016 + n2 * 0.7 + 0.25));',
      '  vec2 dir = uC.zw;',
      '  vec2 d = (dir * s1 + vec2(-dir.y, dir.x) * s2 * 0.4) * (uC.x * aWD.x);',
      '  float br = 0.5 + 0.5 * sin(6.2832 * fract(t * 0.01 + xh * 0.4 - yh * 0.2 + n2 * 0.5));',
      '  vL = 1.0 + uC.y * aWD.x * (br - 0.5) * 0.9;'];
    return [...head, ...common, ...body, ...tail].join('\n');
  }

  const meshFS = (lib, video, grade) => video
    ? ['uniform sampler2D uBase; varying vec2 vUv; varying vec2 vP; varying float vL;', lib, videoGlsl(grade),
      'void main() { gl_FragColor = vec4(finishVideo(fetchVideo(vUv), vP) * vL, 1.0); }'].join('\n')
    : 'uniform sampler2D uBase; varying vec2 vUv; varying float vL;\nvoid main() { gl_FragColor = vec4(texture2D(uBase, vUv).rgb * vL, 1.0); }\n';

  // ---- the twinkling lights: one point sprite each, redrawing its own few pixels of the picture a little darker for a while
  function lightsVS(video) {
    return ['attribute vec4 aPos; uniform vec2 uRes; uniform vec4 uPic; uniform vec4 uL; uniform vec4 uL2; uniform float uT;',
      'varying vec2 vC; varying vec2 vS; varying float vF; varying vec2 vP;',
      'void main() {',
      '  vec2 p = uPic.xy + aPos.xy * uPic.zw;',
      '  gl_Position = vec4(p.x / uRes.x * 2.0 - 1.0, 1.0 - p.y / uRes.y * 2.0, 0.0, 1.0);',
      '  float sd = aPos.w;',
      '  float f1 = floor(140.0 + 360.0 * fract(sd * 37.17)) * 0.001, f2 = floor(14.0 + 62.0 * fract(sd * 91.31)) * 0.001;',
      '  float br = 0.5 + 0.5 * sin(6.2832 * fract(uT * f1 + sd * 13.7));',
      '  float of = smoothstep(uL2.x, uL2.y, 0.5 + 0.5 * sin(6.2832 * fract(uT * f2 + sd * 71.3)));',
      '  vF = mix(1.0, (1.0 - uL.y * br) * (1.0 - (1.0 - uL.z) * of), uL.x);',
      '  float px = max(5.0, aPos.z * uPic.w);',
      '  gl_PointSize = px;',
      '  vP = p;',
      video ? '  vC = aPos.xy; vS = vec2(px / uPic.z, px / uPic.w);' : '  vC = vec2(p.x, uRes.y - p.y) / uRes; vS = vec2(px / uRes.x, px / uRes.y);',
      '}'].join('\n');
  }
  // A light that goes out does not turn black: it turns into what is around it (the darker of the pixels a little to either side), so a window becomes a plain wall.
  const lightsFS = (lib, video, grade) => [
    'uniform sampler2D uBase; varying vec2 vC; varying vec2 vS; varying float vF; varying vec2 vP;',
    video ? lib + '\n' + videoGlsl(grade) : '',
    video ? 'vec3 grab(vec2 uv) { return fetchVideo(uv); }' : 'vec3 grab(vec2 uv) { return texture2D(uBase, uv).rgb; }',
    'void main() {',
    '  vec2 pc = gl_PointCoord - 0.5;',
    video ? '  vec2 uv = vC + pc * vS;' : '  vec2 uv = vC + vec2(pc.x * vS.x, -pc.y * vS.y);',
    '  float a = 1.0 - smoothstep(0.30, 0.50, length(pc));',
    '  vec3 c = grab(uv);',
    '  vec2 k = vec2(0.55 * vS.x, 0.0);',
    '  vec3 wall = min(c, min(grab(uv + k), grab(uv - k)));',
    '  vec3 col = mix(c, mix(wall, c, vF), a);',
    video ? '  gl_FragColor = vec4(finishVideo(col, vP), 1.0);' : '  gl_FragColor = vec4(col, 1.0);',
    '}'].join('\n');

  // ---- glints on the water: additive points that swell and fade, tinted by the picture under them
  function glintsVS(video) {
    return ['attribute vec4 aPos; uniform vec2 uRes; uniform vec4 uPic; uniform vec4 uG; uniform float uT;',
      'varying vec2 vC; varying float vA; varying vec2 vP;',
      'void main() {',
      '  float sd = aPos.w;',
      '  float rate = floor(250.0 + 750.0 * fract(sd * 53.7)) * 0.001;',
      '  float tw = 0.5 + 0.5 * sin(6.2832 * fract(uT * rate + sd * 29.3));',
      '  tw = tw * tw * tw;',
      '  vec2 uv = aPos.xy + vec2(0.0035 * sin(6.2832 * fract(uT * 0.021 + sd * 7.1)), 0.0012 * sin(6.2832 * fract(uT * 0.017 + sd * 3.3)));',
      '  vec2 p = uPic.xy + uv * uPic.zw;',
      '  gl_Position = vec4(p.x / uRes.x * 2.0 - 1.0, 1.0 - p.y / uRes.y * 2.0, 0.0, 1.0);',
      '  float depth = clamp((uv.y - uG.y) * uG.z, 0.0, 1.0);',
      '  vA = tw * uG.x * (0.25 + 0.75 * depth);',
      '  gl_PointSize = uG.w * max(4.0, aPos.z * uPic.w * (0.5 + 0.9 * tw) * (0.6 + 0.8 * depth));',
      '  vP = p;',
      video ? '  vC = uv;' : '  vC = vec2(p.x, uRes.y - p.y) / uRes;',
      '}'].join('\n');
  }
  const glintsFS = (lib, video, grade) => [
    'uniform sampler2D uBase; uniform vec3 uGT; varying vec2 vC; varying float vA; varying vec2 vP;',
    video ? lib + '\n' + videoGlsl(grade) : '',
    'void main() {',
    '  vec2 pc = gl_PointCoord - 0.5;',
    '  float r2 = dot(pc, pc) * 4.0;',
    '  float core = max(0.0, 1.0 - r2); core *= core;',
    '  float star = max(0.0, 1.0 - abs(pc.x) * 9.0) * max(0.0, 1.0 - abs(pc.y) * 2.2) + max(0.0, 1.0 - abs(pc.y) * 9.0) * max(0.0, 1.0 - abs(pc.x) * 2.2);',
    video ? '  vec3 b = finishVideo(fetchVideo(vC), vP);' : '  vec3 b = texture2D(uBase, vC).rgb;',
    '  vec3 col = uGT.x >= 0.0 ? uGT : mix(vec3(1.0), min(b * 1.8, vec3(1.0)), 0.5);',
    '  gl_FragColor = vec4(col * (core * 0.55 + star * 0.22) * vA, 0.0);',
    '}'].join('\n');

  // ---- mist: a few big soft blobs that drift slowly, drawn over the picture with alpha
  const MIST_VS = ['attribute vec4 aPos; attribute vec2 aB; uniform vec2 uRes; uniform vec4 uPic; uniform vec3 uM; uniform float uT; varying vec2 vK; varying float vA;',
    'void main() {',
    '  float sd = aB.y;',
    '  vec2 c = vec2(aPos.z + 0.07 * sin(6.2832 * fract(uT * 0.006 + sd * 17.1)), aPos.w + 0.012 * sin(6.2832 * fract(uT * 0.009 + sd * 5.3)));',
    '  float rad = aB.x * (0.85 + 0.25 * sin(6.2832 * fract(uT * 0.004 + sd * 9.1)));',
    '  vec2 p = uPic.xy + c * uPic.zw + aPos.xy * vec2(rad * uPic.w * 1.9, rad * uPic.w * 0.75);',
    '  gl_Position = vec4(p.x / uRes.x * 2.0 - 1.0, 1.0 - p.y / uRes.y * 2.0, 0.0, 1.0);',
    '  vK = aPos.xy;',
    '  vA = uM.x * (0.55 + 0.45 * sin(6.2832 * fract(uT * 0.005 + sd * 3.7)));',
    '}'].join('\n');
  const MIST_FS = 'uniform vec3 uMT; varying vec2 vK; varying float vA;\nvoid main() { float a = 1.0 - smoothstep(0.0, 1.0, length(vK)); a = a * a * vA * 0.55; gl_FragColor = vec4(uMT * a, a); }\n';

  // ---- rain: thin streaks (lines), a bright head and a transparent tail, falling on the slant
  const RAIN_VS = ['attribute vec4 aPos; attribute float aEnd; uniform vec2 uRes; uniform vec4 uR; uniform float uS; varying float vA;',
    'void main() {',
    '  float y = fract(aPos.y + uR.z * aPos.z * uS / uRes.y);',
    '  vec2 p = vec2(aPos.x * (uRes.x + 0.5 * uRes.y * uR.y) - 0.25 * uRes.y * uR.y, (-0.08 + 1.16 * y) * uRes.y);',
    '  p.x += uR.y * p.y;',
    '  p -= aEnd * aPos.w * uS * vec2(uR.y, 1.0);',
    '  gl_Position = vec4(p.x / uRes.x * 2.0 - 1.0, 1.0 - p.y / uRes.y * 2.0, 0.0, 1.0);',
    '  vA = (1.0 - aEnd) * (0.30 + 0.70 * uR.x) * (0.35 + 0.65 * smoothstep(0.0, 1.0, aPos.z / 1000.0));',
    '}'].join('\n');
  const RAIN_FS = 'uniform vec3 uRT; varying float vA;\nvoid main() { gl_FragColor = vec4(uRT * vA * 0.5, 0.0); }\n';

  // ---- touch: a soft glow, a ring and sparkle or spark points, all additive, all small
  const QUAD_VS = 'attribute vec2 aPos;\nuniform vec4 uBox;\nvarying vec2 vK;\nvoid main() { vK = aPos; gl_Position = vec4(uBox.xy + aPos * uBox.zw, 0.0, 1.0); }\n';
  const GLOW_FS = 'uniform vec4 uGC; varying vec2 vK;\nvoid main() { float a = exp(-dot(vK, vK) * 3.2) * uGC.w; gl_FragColor = vec4(uGC.rgb * a, 0.0); }\n';
  const RING_VS = ['attribute vec3 aPos; uniform vec2 uRes; uniform vec4 uC; varying float vS;',
    'void main() { vec2 p = uC.xy + aPos.xy * (uC.z + aPos.z * uC.w); vS = aPos.z; gl_Position = vec4(p.x / uRes.x * 2.0 - 1.0, 1.0 - p.y / uRes.y * 2.0, 0.0, 1.0); }'].join('\n');
  const RING_FS = 'uniform vec4 uRC; varying float vS;\nvoid main() { float a = 1.0 - vS * vS; a *= a * uRC.w; gl_FragColor = vec4(uRC.rgb * a, 0.0); }\n';
  const POINT_VS = ['attribute vec4 aPos; attribute vec3 aCol; uniform vec2 uRes; varying vec3 vCol; varying float vA;',
    'void main() { gl_Position = vec4(aPos.x / uRes.x * 2.0 - 1.0, 1.0 - aPos.y / uRes.y * 2.0, 0.0, 1.0); gl_PointSize = aPos.z; vCol = aCol; vA = aPos.w; }'].join('\n');
  const POINT_FS = ['uniform float uSquare; varying vec3 vCol; varying float vA;',
    'void main() {',
    '  vec2 pc = gl_PointCoord - 0.5;',
    '  float core = max(0.0, 1.0 - dot(pc, pc) * 4.0); core *= core;',
    '  float star = max(0.0, 1.0 - abs(pc.x) * 9.0) * max(0.0, 1.0 - abs(pc.y) * 1.8) + max(0.0, 1.0 - abs(pc.y) * 9.0) * max(0.0, 1.0 - abs(pc.x) * 1.8);',
    '  float a = mix(core * 0.9 + star * 0.55, 1.0, uSquare);',
    '  gl_FragColor = vec4(vCol * a * vA, 0.0);',
    '}'].join('\n');
  const BLIT_FS = 'uniform sampler2D uTex; varying vec2 vUv;\nvoid main() { gl_FragColor = texture2D(uTex, vUv); }\n';
  const BLIT_VS = 'attribute vec2 aPos; varying vec2 vUv;\nvoid main() { vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }\n';

  /* ---- craft: each one a small quad drawn over the picture, so only the pixels around a craft pay for it, whatever the GPU does with branches */

  const CRAFT_VS = 'attribute vec2 aPos;\nuniform vec4 uBox;\nvoid main() { gl_Position = vec4(uBox.xy + aPos * uBox.zw, 0.0, 1.0); }\n';

  /** The fragment shader of one craft kind. Output is premultiplied: the dark body as colour with its alpha, light as colour with no alpha (added). */
  function craftFragment(kind, lib) {
    const head = [
      'uniform vec2 uRes; uniform vec4 uPic; uniform vec2 uSize; uniform float uTime;',
      'uniform vec4 uA; uniform vec4 uB; uniform vec4 uC;',        // x, y, heading, size | kind, alpha, phase, count | r, g, b, wingbeat or blink
      lib, HASH_GLSL,
      'vec2 rot2(vec2 v, float a) { float c = cos(a), s = sin(a); return vec2(c * v.x - s * v.y, s * v.x + c * v.y); }',
    ];
    const prologue = [
      'void main() {',
      '  vec2 p = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);',
      '  vec2 puv = (p - uPic.xy) / uPic.zw;',
      '  float unit = uPic.w;',
      '  vec2 d = (puv - uA.xy) * vec2(uSize.x, 1.0);',
      '  float s = uA.w;',
    ];
    let body;
    if (kind === 'ship') {
      // a small dark wedge with a glowing engine and a long faint trail
      body = [
        'vec4 shipLayer(vec2 d, float s, vec3 glowCol, float px) {',
        '  float x = d.x / s, y = abs(d.y) / s;',
        '  float hw = 0.46 * (1.0 - x) / 1.9 - 0.10 * smoothstep(-0.55, -0.95, x);',
        '  float body = smoothstep(0.0, px / s * 1.4, hw - y) * step(-0.95, x) * step(x, 1.0);',
        '  float rim = smoothstep(0.0, px / s * 3.0, hw - y) * (1.0 - smoothstep(0.0, px / s * 5.0, hw - y)) * body;',
        '  vec2 g = vec2(x + 1.05, d.y / s * 1.4);',
        '  float glow = exp(-dot(g, g) / 0.16);',
        '  float trail = exp(-y * y / 0.012) * exp((x + 1.0) / 5.5) * step(x, -1.0) * smoothstep(-14.0, -1.0, x);',
        '  return vec4(glowCol * (glow * 1.4 + trail * 0.55 + rim * 0.9), body);',
        '}',
        ...prologue,
        '  vec4 sh = shipLayer(rot2(d, -uA.z), s, uC.rgb, 1.2 / unit);',
        '  float a = sh.a * uB.y * 0.95;',
        '  gl_FragColor = vec4(vec3(0.045, 0.04, 0.10) * a + sh.rgb * uB.y, a);',
        '}',
      ];
    } else if (kind === 'gull') {
      // Distant gulls: tapered asymmetric wings, a small body and a beak facing their direction of travel.
      // Six guarded blocks keep the shader bounded; the wing glides and each bird beats at its own phase.
      body = [
        'vec2 gullShape(vec2 d, float s, float flap, float px, float face) {',
        '  vec2 q = d / s;',
        '  float aa = max(0.02, px / s);',
        '  float x = abs(q.x) / (q.x < 0.0 ? 1.0 : 0.82);',
        '  float bend = -(0.18 + 0.35 * flap) * x + 0.12 * x * x;',
        '  bend += q.x > 0.0 ? 0.045 * x : 0.0;',
        '  float thick = 0.018 + 0.10 * (1.0 - clamp(x, 0.0, 1.0));',
        '  float wing = (1.0 - smoothstep(thick, thick + aa, abs(q.y - bend))) * (1.0 - smoothstep(0.94, 1.0 + aa, x));',
        '  float body = 1.0 - smoothstep(1.0 - aa, 1.0 + aa, length((q - vec2(0.0, 0.025)) / vec2(0.16, 0.12)));',
        '  float head = 1.0 - smoothstep(1.0 - aa, 1.0 + aa, length((q - vec2(0.12 * face, -0.035)) / vec2(0.10, 0.075)));',
        '  float beak = (1.0 - smoothstep(0.015, 0.015 + aa * 0.5, abs(q.y + 0.035))) * step(0.19, q.x * face) * step(q.x * face, 0.27);',
        '  float mask = max(wing, max(body, head));',
        '  float dark = max(wing * smoothstep(0.72, 1.0, x), beak);',
        '  return vec2(max(mask, beak), dark);',
        '}',
        ...prologue,
        '  float gi = 0.0, gdark = 0.0;',
        ...[0, 1, 2, 3, 4, 5].flatMap((k) => {
          const row = Math.floor((k + 1) / 2), side = (k % 2) * 2 - 1;
          return [
            '  if (uB.w > ' + k + '.5) {',
            '    vec2 slot = vec2(' + (-1.9 * row).toFixed(2) + ', ' + (side * row).toFixed(1) + ') * s * (1.0 + 0.25 * h11(' + k + '.0 + uB.z));',
            '    slot += vec2(0.30, 0.45) * s * vec2(sin(uTime * 0.2 + ' + (k * 2.1).toFixed(1) + ' + uB.z), cos(uTime * 0.17 + ' + (k * 1.3).toFixed(1) + '));',
            '    float fl = sin(uC.w + ' + (k * 1.3).toFixed(1) + ' + uB.z);',
            '    float sz = s * (0.85 + 0.25 * h11(' + (k * 3) + '.0 + uB.z));',
            '    vec2 gd = d - rot2(slot, uA.z);',
            '    vec2 bird = gullShape(gd, sz, fl, 1.0 / unit, cos(uA.z) < 0.0 ? -1.0 : 1.0);',
            '    gi = max(gi, bird.x); gdark = max(gdark, bird.y);',
            '  }',
          ];
        }),
        '  float a = gi * uB.y * 0.9;',
        '  vec3 colour = mix(uC.rgb * 0.92, vec3(0.22, 0.25, 0.27), clamp(gdark, 0.0, 1.0));',
        '  gl_FragColor = vec4(colour * a, a);',
        '}',
      ];
    } else if (kind === 'swallow') {
      // A distant swallow: narrow swept wings, a slim body and the forked tail, with independent wingbeats.
      body = [
        'float tapered(vec2 p, vec2 a, vec2 b, float wide, float thin, float aa) {',
        '  vec2 ab = b - a; float t = clamp(dot(p - a, ab) / dot(ab, ab), 0.0, 1.0);',
        '  return 1.0 - smoothstep(mix(wide, thin, t), mix(wide, thin, t) + aa, length(p - mix(a, b, t)));',
        '}',
        'float swallow(vec2 p, float flap, float aa) {',
        '  float body = tapered(p, vec2(-0.29, 0.0), vec2(0.39, -0.015), 0.075, 0.045, aa);',
        '  float upJoint = -0.34 - flap * 0.06, upTip = -0.70 - flap * 0.16;',
        '  float downJoint = 0.31 + flap * 0.06, downTip = 0.65 + flap * 0.15;',
        '  float upper = max(tapered(p, vec2(0.02, -0.02), vec2(-0.06, upJoint), 0.105, 0.045, aa), tapered(p, vec2(-0.06, upJoint), vec2(-0.30, upTip), 0.055, 0.006, aa));',
        '  float lower = max(tapered(p, vec2(0.01, 0.02), vec2(-0.07, downJoint), 0.10, 0.045, aa), tapered(p, vec2(-0.07, downJoint), vec2(-0.29, downTip), 0.05, 0.006, aa));',
        '  float tail1 = tapered(p, vec2(-0.25, 0.0), vec2(-0.63, -0.14), 0.04, 0.006, aa);',
        '  float tail2 = tapered(p, vec2(-0.25, 0.0), vec2(-0.63, 0.14), 0.04, 0.006, aa);',
        '  return max(max(body, max(upper, lower)), max(tail1, tail2));',
        '}',
        ...prologue,
        '  vec2 q = rot2(d, -uA.z) / s; float aa = clamp(1.0 / (unit * s), 0.025, 0.25);',
        '  float mask = swallow(q, sin(uC.w + uB.z), aa);',
        '  if (uB.w > 1.5) mask = max(mask, swallow(q - vec2(-3.1, 1.0), sin(uC.w + uB.z + 1.7), aa));',
        '  float a = mask * uB.y * 0.9;',
        '  gl_FragColor = vec4(uC.rgb * a, a);',
        '}',
      ];
    } else {
      // a distant drone: a tiny dark body, a slowly blinking light with a halo and a faint trail behind it
      body = [
        ...prologue,
        '  float ph = uC.w;',
        '  float blink = smoothstep(0.45, 0.55, ph) * (1.0 - smoothstep(0.88, 0.98, ph));',
        '  float r2 = dot(d, d);',
        '  float core = exp(-r2 / (s * s * 0.45));',
        '  float halo = exp(-r2 / (s * s * 12.0));',
        '  vec2 r = rot2(d, -uA.z);',
        '  float trail = exp(-r.y * r.y / (s * s * 0.05)) * exp(r.x / (s * 9.0)) * step(r.x, 0.0);',
        '  float a = smoothstep(s * 0.8, s * 0.3, sqrt(r2)) * uB.y * 0.85;',
        '  gl_FragColor = vec4(vec3(0.03) * a + uC.rgb * ((core * 1.3 + halo * 0.45) * (0.20 + 0.80 * blink) + trail * 0.10) * uB.y, a);',
        '}',
      ];
    }
    return [...head, ...body].join('\n');
  }

  /* ---- lamps: one small premultiplied quad per row, over the finished frame. The fragment shader finds its module with a floor, never a loop: dark housings
     (colour with their alpha) with the light on top (colour with no alpha, added). `lit` counts modules from the row's outer end and is fractional, so the lit
     length follows the quota even inside a lamp; below zero it is unknown: a few dim neutral lamps, never a full or an empty row. */

  function lampsFragment() {
    return [
      'uniform vec2 uRes; uniform vec4 uPic; uniform vec2 uSize; uniform float uTime;',
      'uniform vec4 uRow;',            // left, right (fractions of the picture's width), y (of its height), the face's height (picture heights)
      'uniform vec4 uRow2;',           // modules, lit modules from the anchored end (below zero: unknown), anchor (+1 left end, -1 right end), amount
      'uniform vec3 uCol;',
      'void main() {',
      '  vec2 p = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);',
      '  vec2 puv = (p - uPic.xy) / uPic.zw;',
      '  float aa = 1.0 / uPic.w;',                                      // one device pixel, in picture heights
      '  float pitch = (uRow.y - uRow.x) * uSize.x / uRow2.x;',           // one module and its gap, in picture heights
      '  float t = (puv.x - uRow.x) / (uRow.y - uRow.x) * uRow2.x;',      // modules from the left end
      '  float s = uRow2.z > 0.0 ? t : uRow2.x - t;',                     // modules from the anchored (outer) end
      '  float k = floor(s);',
      '  float fx = fract(s) - 0.5;',                                     // -0.5 .. 0.5 across one pitch
      '  float dy = (puv.y - uRow.z) / uRow.w;',                          // -0.5 .. 0.5 over the face
      '  float aax = aa / pitch;',
      '  float aay = aa / uRow.w;',
      '  float inside = step(0.0, s) * step(s, uRow2.x);',                // on the row, not in the margin around it
      // Individually mounted round bridge lamps, instead of a rectangular LED bar.
      '  float radius = length(vec2(fx / 0.27, dy / 0.39));',
      '  float face = (1.0 - smoothstep(0.72, 1.0, radius)) * inside;',
      '  float house = face * 0.58;',
      '  float known = step(0.0, uRow2.y);',
      '  float breath = 0.95 + 0.05 * sin(uTime * 0.2513274 + k * 1.7);',  // a slow breath, 40 whole cycles in the 1000 s the clock wraps at
      // the light of a lit module: coloured glass with a nearly white core, only on the module's face so the seams between modules stay dark
      '  float run = (1.0 - smoothstep(uRow2.y - aax, uRow2.y + aax, s)) * known;',
      '  float core = 1.0 - smoothstep(0.08, 0.65, radius);',
      '  vec3 lamp = mix(uCol, vec3(1.0), core * 0.55) * face * run;',
      // unknown: every fourth module shows one small dim neutral light
      '  float every = (1.0 - known) * (1.0 - step(0.5, mod(k, 4.0)));',
      '  float dot4 = smoothstep(-0.24 - aax, -0.24 + aax, fx) * (1.0 - smoothstep(0.21 - aax, 0.21 + aax, fx)) * smoothstep(-0.17 - aay, -0.17 + aay, dy) * (1.0 - smoothstep(0.17 - aay, 0.17 + aay, dy));',
      '  vec3 neutral = vec3(0.357, 0.404, 0.439) * dot4 * every * inside;',
      // a tight halo around what is lit: beyond the lit run's end (or the row's anchored end) it is the distance to that end, inside the run only the distance to the module's own
      // face, so the seams between lit modules keep some dark; measured in units of 0.003 picture heights so no number is tiny
      '  float lit = max(uRow2.y, 0.0);',
      '  float beyond = max(max(s - lit, 0.0), max(-s, 0.0));',
      '  float gap = max(abs(fx) - 0.22, 0.0);',
      '  vec2 q = vec2(beyond > 0.0 ? beyond * pitch : gap * pitch, max(abs(dy) - 0.22, 0.0) * uRow.w) / 0.003;',
      '  float d2 = dot(q, q);',
      '  float halo = (exp(-d2) * 0.22 + exp(-d2 / 16.0) * 0.055) * known * step(0.0001, uRow2.y);',
      '  vec3 rgb = vec3(0.035, 0.067, 0.094) * house;',
      '  rgb += vec3(0.18, 0.22, 0.26) * face * (1.0 - smoothstep(-0.25, 0.0, dy)) * 0.3;',
      '  rgb += (lamp + neutral + uCol * halo) * breath * uRow2.w;',
      '  gl_FragColor = vec4(rgb, house);',
      '}',
    ].join('\n');
  }

  /* ------------------------------------------------------------------------------------------------ the touch kit (photo and pixel looks share it) */

  /** Small additive sprites for a touch: a glow quad, a ring, points (sparkles, sparks) and a blit of a cached picture. The caller sets BLEND/SCISSOR. */
  function createTouchKit(kit, gl) {
    const shared = kit.initContext(gl), made = {};
    const get = (key, make) => made[key] || (made[key] = make());
    const ringBuffer = get('ringBuf', () => {
      const data = new Float32Array(66 * 2 * 3), b = gl.createBuffer();
      for (let i = 0; i <= 65; i++) { const a = i / 65 * TAU, c = Math.cos(a), s = Math.sin(a); data.set([c, s, -1, c, s, 1], i * 6); }
      gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      return b;
    });
    const pointBuffer = get('pointBuf', () => gl.createBuffer());
    const packed = new Float32Array(24 * 7);
    let maxLoc = 0;
    const attrib = (buffer, loc, size, stride, offset) => { gl.bindBuffer(gl.ARRAY_BUFFER, buffer); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride, offset); maxLoc = Math.max(maxLoc, loc); };
    const api = {
      shared,
      attrib,
      /** Restore the shared quad on attribute 0 and switch the others off: the looks that draw after this expect that. */
      restore() {
        gl.bindBuffer(gl.ARRAY_BUFFER, shared.buffer); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
        for (let l = 1; l <= maxLoc; l++) gl.disableVertexAttribArray(l);
        maxLoc = 0;
      },
      /** A soft round glow (canvas px centre and radius), colour r, g, b and strength. */
      glow(width, height, cx, cy, radius, color, strength) {
        const prog = get('glow', () => kit.program(gl, GLOW_FS, QUAD_VS)).use();
        prog.f4('uBox', cx / width * 2 - 1, 1 - cy / height * 2, radius / width * 2, radius / height * 2).f4('uGC', color[0], color[1], color[2], strength);
        attrib(shared.buffer, 0, 2, 0, 0);
        kit.draw(gl);
      },
      /** A ring of light: centre, radius and half width in canvas px, colour and strength. */
      ring(width, height, cx, cy, radius, halfWidth, color, strength) {
        const prog = get('ring', () => kit.program(gl, RING_FS, RING_VS)).use();
        prog.f2('uRes', width, height).f4('uC', cx, cy, radius, halfWidth).f4('uRC', color[0], color[1], color[2], strength);
        attrib(ringBuffer, 0, 3, 0, 0);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 132);
      },
      /** Points, each {x, y, size, alpha, r, g, b} in canvas px; `square` makes them hard-edged cells instead of soft stars. */
      points(width, height, list, square) {
        const n = Math.min(list.length, 24);
        if (!n) return;
        for (let i = 0; i < n; i++) { const p = list[i]; packed.set([p.x, p.y, p.size, p.alpha, p.r, p.g, p.b], i * 7); }
        const prog = get('points', () => kit.program(gl, POINT_FS, POINT_VS, ['aCol'])).use();
        prog.f2('uRes', width, height).f1('uSquare', square ? 1 : 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, pointBuffer); gl.bufferData(gl.ARRAY_BUFFER, packed.subarray(0, n * 7), gl.DYNAMIC_DRAW);
        attrib(pointBuffer, 0, 4, 28, 0); attrib(pointBuffer, 1, 3, 28, 16);
        gl.drawArrays(gl.POINTS, 0, n);
      },
      /** Copy a picture (RGBA, canvas sized) to the canvas as it is. */
      blit(texture) {
        const prog = get('blit', () => kit.program(gl, BLIT_FS, BLIT_VS)).use();
        kit.bindTexture(gl, 0, texture); prog.i1('uTex', 0);
        attrib(shared.buffer, 0, 2, 0, 0);
        kit.draw(gl);
      },
      dispose() {
        for (const k of Object.keys(made)) { const m = made[k]; if (m && typeof m.dispose === 'function') m.dispose(); else if (m) { try { gl.deleteBuffer(m); } catch (_) { /* gone */ } } }
      },
    };
    return api;
  }

  /** What a touch adds over a pixel look (the CRT or the LCD): the cached picture is copied to the canvas, then a soft glow, a ring and a few sparks (each exactly one
   *  source pixel) are added where the picture is. It works from the layout's own generic parts (`picture`: where the source pixels are drawn, `canvas`, `area`: what the
   *  page gave the stage), never from a monitor's frame or bezel, so it survives a look without one. `palette`: {glow, ring, spark: [hot, cool]} colours. */
  function compositeTouch(touch, gl, kit, f, L, cacheTexture, columns, palette) {
    const s = f.scale, W = f.width, H = f.height, pokes = f.live.pokes || [];
    const canvas = L.canvas, pic = L.picture || L.screen || { x: canvas.x, y: canvas.y, w: canvas.w, h: canvas.h }, area = L.area || { left: -1e9, top: -1e9, width: 2e9, height: 2e9 };
    kit.toCanvas(gl, f);
    gl.disable(gl.BLEND); gl.disable(gl.SCISSOR_TEST);
    touch.blit(cacheTexture);
    // where light may be added: the picture's rectangle, inside the canvas and the area
    const left = Math.max(pic.x, canvas.x, area.left), top = Math.max(pic.y, canvas.y, area.top);
    const right = Math.min(pic.x + pic.w, canvas.x + canvas.w, area.left + area.width), bottom = Math.min(pic.y + pic.h, canvas.y + canvas.h, area.top + area.height);
    const cols = columns || (L.grid && L.grid.cols) || Math.max(1, Math.round(pic.w / 3)), cell = pic.w * s / cols;
    const ox = (pic.x - canvas.x) * s, oy = (pic.y - canvas.y) * s;                                   // the source pixels' grid starts here (canvas px)
    gl.enable(gl.SCISSOR_TEST);
    gl.scissor(Math.max(0, Math.round((left - canvas.x) * s)), Math.max(0, Math.round(H - (bottom - canvas.y) * s)), Math.max(0, Math.round((right - left) * s)), Math.max(0, Math.round((bottom - top) * s)));
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);
    const dots = [], tmp = [];
    for (let i = 0; i < pokes.length && i < 3; i++) {
      const p = pokes[i], x = (p.x - canvas.x) * s, y = (p.y - canvas.y) * s;
      const fade = Math.exp(-p.age * 2.4) * smooth(clamp(p.age / 0.04, 0, 1)), R = (22 + p.age * 150) * s;
      touch.glow(W, H, x, y, R * 1.6, palette.glow, 0.55 * fade);
      touch.ring(W, H, x, y, R, 9 * s, palette.ring, 0.55 * fade);
    }
    for (let i = pokes.length - 1; i >= 0 && dots.length < 24; i--) {
      for (const k of sparks(pokes[i], pokes[i].age, tmp)) {
        if (dots.length >= 24) break;
        const gx = (k.x - canvas.x) * s, gy = (k.y - canvas.y) * s;
        const cx = ox + (Math.floor((gx - ox) / cell) + 0.5) * cell, cy = oy + (Math.floor((gy - oy) / cell) + 0.5) * cell;
        const hot = palette.spark[0], cool = palette.spark[1];
        dots.push({ x: cx, y: cy, size: Math.max(2, cell * 0.94), alpha: k.alpha, r: hot[0] + (cool[0] - hot[0]) * k.heat, g: hot[1] + (cool[1] - hot[1]) * k.heat, b: hot[2] + (cool[2] - hot[2]) * k.heat });
      }
    }
    touch.points(W, H, dots, true);
    gl.disable(gl.BLEND); gl.disable(gl.SCISSOR_TEST);
    touch.restore();
  }

  /* ------------------------------------------------------------------------------------------------ the renderer */

  /** The live drawing of one photo scene. `view` (from stage-photo.js): {src: {tex, id, mipmapped, uvScale, texW, texH}, base: the baked still or null, pic, grade, cfg}. */
  function createLiveRenderer(kit, gl) {
    const touch = createTouchKit(kit, gl), shared = touch.shared;
    const programs = {};
    const program = (key, make) => programs[key] || (programs[key] = make());
    const buffers = {};
    const buffer = (key) => buffers[key] || (buffers[key] = gl.createBuffer());
    const upload = (key, data, target) => { const b = buffer(key); gl.bindBuffer(target || gl.ARRAY_BUFFER, b); gl.bufferData(target || gl.ARRAY_BUFFER, data, gl.STATIC_DRAW); return b; };
    const attrib = touch.attrib;
    let detect = null, detectTaps = null;
    let raster = null, rasterFor = '', lightList = null, lightsFor = '', geo = null, geoKey = '', lastCost = null;
    const uP = new Float32Array(12);
    const craftPrograms = {};
    const craftProgram = (kind) => craftPrograms[kind] || (craftPrograms[kind] = kit.program(gl, craftFragment(kind, kit.glsl.lib), CRAFT_VS));
    let lampsProgram = null;

    function disposeDerived() {
      raster = null; rasterFor = ''; lightList = null; lightsFor = ''; geo = null; geoKey = '';
      for (const k of Object.keys(buffers)) { try { gl.deleteBuffer(buffers[k]); } catch (_) { /* gone */ } delete buffers[k]; }
    }

    /** The region masks of this picture and block (CPU only: they become vertex weights, sprite positions and the answer to a touch). */
    function ensureRaster(f, src, cfg) {
      const id = (src.id || 0) + '|' + JSON.stringify(cfg) + '|' + f.mediaW + 'x' + f.mediaH;
      if (rasterFor === id && raster) return;
      raster = rasterRegions(cfg, f.mediaW / f.mediaH); rasterFor = id; lightList = null; lightsFor = ''; geo = null; geoKey = '';
    }

    /** Detect the small lights once per picture (a GPU pass, read back) and keep them as a list, strongest first. */
    function ensureLights(f, src, cfg) {
      if (!cfg.lights) { lightList = null; return; }
      const id = rasterFor;
      if (lightsFor === id && lightList) return;
      const side = Math.max(f.mediaW, f.mediaH), k = Math.min(1, 1024 / side), w = Math.max(16, Math.round(f.mediaW * k)), h = Math.max(16, Math.round(f.mediaH * k));
      const taps = !src.mipmapped;
      const prog = taps ? (detectTaps = detectTaps || kit.program(gl, DETECT_FS(kit.glsl.lib, true))) : (detect = detect || kit.program(gl, DETECT_FS(kit.glsl.lib, false)));
      const target = kit.target(gl, w, h);
      try {
        kit.bindTexture(gl, 0, src.tex);
        target.bind();
        attrib(shared.buffer, 0, 2, 0, 0);
        prog.use().i1('uTex', 0).f2('uOut', w, h).f2('uUvScale', src.uvScale[0], src.uvScale[1]).f2('uTexel', 1 / src.texW, 1 / src.texH);
        kit.draw(gl);
        const bytes = new Uint8Array(w * h * 4);
        gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, bytes);
        lightList = extractLights(bytes, w, h, { raster, max: BUDGET[0].lights });
      } finally { gl.bindFramebuffer(gl.FRAMEBUFFER, null); target.dispose(); }
      lightsFor = id; geoKey = '';
    }

    /** The meshes and sprite lists for this canvas, layout and tier; rebuilt only when one of them changes. */
    function ensureGeometry(f, view, cfg, B, fxBottom) {
      const pic = view.pic, s = f.scale;
      const key = [f.width, f.height, pic.x, pic.y, pic.w, pic.h, s, B.cell, B.glints, cfg.water ? cfg.water.glint_density : '', B.mist, B.rain, fxBottom, rasterFor, lightList ? lightList.length : 0].join('|');
      if (geo && geoKey === key) return;
      const dev = { x: pic.x * s, y: pic.y * s, w: pic.w * s, h: pic.h * s };
      const g = { water: null, clouds: null, glints: null, mist: null, rain: null, lights: null };
      const grid = (name, withDepth) => {
        const effect = cfg[name];
        if (!effect || !B.cell || (name === 'water' && effect.amount === 0)) return null;
        const rect = effectRect(effect.regions, dev, f.width, fxBottom);
        if (!rect) return null;
        const bottom = effect.regions.reduce((m, r) => Math.max(m, typeof r[0] === 'number' ? r[3] : Math.max(...r.map((p) => p[1]))), 0), span = Math.max(0.05, bottom - (effect.horizon || 0));
        const mesh = buildGrid(rect, B.cell, (x, y) => {
          const u = (x - dev.x) / dev.w, v = (y - dev.y) / dev.h;
          return [weightBilinear(raster, name === 'water' ? 0 : 1, u, v), withDepth ? clamp((v - effect.horizon) / span, 0, 1) : 0];
        });
        mesh.vbo = upload(name + 'V', mesh.verts); mesh.ibo = upload(name + 'I', mesh.idx, gl.ELEMENT_ARRAY_BUFFER);
        mesh.span = span;
        return mesh;
      };
      g.water = grid('water', true);
      g.clouds = grid('clouds', false);
      if (cfg.water && B.glints) {
        const list = placeGlints(raster, Math.round(B.glints * cfg.water.glint_density), 7001 + hashSeed(rasterFor));
        if (list.length) g.glints = { count: list.length / 4, vbo: upload('glints', list), pixels: 0 };
      }
      if (cfg.mist && B.mist) {
        const mist = placeMist(raster, B.mist, 9001 + hashSeed(rasterFor));
        if (mist.count) {
          const idx = new Uint16Array(mist.count * 6);
          for (let i = 0; i < mist.count; i++) { const a = i * 4; idx.set([a, a + 1, a + 2, a + 1, a + 3, a + 2], i * 6); }
          g.mist = { count: mist.count, vbo: upload('mist', mist.data), ibo: upload('mistI', idx, gl.ELEMENT_ARRAY_BUFFER) };
        }
      }
      if (cfg.rain && B.rain) g.rain = { count: B.rain * 2, vbo: upload('rain', placeRain(B.rain, 5003 + hashSeed(rasterFor))) };
      if (lightList && lightList.length && B.lights) g.lights = { count: Math.min(B.lights, lightList.length / 4), vbo: upload('lights', lightList) };
      geo = g; geoKey = key;
    }

    const hashSeed = (text) => { let h = 2166136261 >>> 0; for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; } return h % 100000; };

    function common(prog, f, view) {
      const s = f.scale, aspect = f.mediaW / f.mediaH, pic = view.pic;
      prog.f2('uRes', f.width, f.height).f4('uPic', pic.x * s, pic.y * s, pic.w * s, pic.h * s).f2('uSize', aspect, s);
    }

    function videoUniforms(prog, f, view) {
      const g = view.grade, b = f.base, area = f.layout.area, s = f.scale;
      prog.f2('uUvScale', f.uvScale[0], f.uvScale[1]).f4('uGrade', g.contrast * g.amount, g.saturation * g.amount, 0, 0)
        .f3('uShadow', g.shadow[0] * g.amount, g.shadow[1] * g.amount, g.shadow[2] * g.amount).f3('uHighlight', g.highlight[0] * g.amount, g.highlight[1] * g.amount, g.highlight[2] * g.amount)
        .f3('uBaseColour', b[0] / 255, b[1] / 255, b[2] / 255).f4('uVig', g.vignette, g.fade * s, 0, 0).f4('uArea', area.left * s, area.top * s, area.width * s, area.height * s);
    }

    /** The picture: a still's baked canvas (a slow zoom when nothing else is alive), a film graded here. */
    function drawBase(f, view, B, drift) {
      const video = f.isVideo, grade = video && f.level <= 1 && view.grade.amount > 0;
      const prog = video ? program('baseV' + (grade ? 'g' : ''), () => kit.program(gl, baseVideoFS(kit.glsl.lib, grade), baseVideoVS)) : program('base', () => kit.program(gl, BASE_FS, BASE_VS));
      prog.use();
      kit.bindTexture(gl, 0, video ? f.tex : view.base);
      prog.i1('uBase', 0);
      if (video) { common(prog, f, view); videoUniforms(prog, f, view); } else {
        if (drift) { const d = view.drift; prog.f4('uXf', d.zoom, d.pan[0] / f.width, d.pan[1] / f.height, 0).f2('uCtr', d.cx, d.cy); } else prog.f4('uXf', 1, 0, 0, 0).f2('uCtr', 0.5, 0.5);
      }
      attrib(shared.buffer, 0, 2, 0, 0);
      kit.draw(gl);
    }

    function drawMesh(kind, mesh, f, view, cfg, clockOf) {
      const video = f.isVideo, grade = video && f.level <= 1 && view.grade.amount > 0, key = 'mesh' + kind + (video ? 'V' : 'S') + (grade ? 'g' : '');
      const prog = program(key, () => kit.program(gl, meshFS(kit.glsl.lib, video, grade), meshVS(kind, video), ['aWD'])).use();
      kit.bindTexture(gl, 0, video ? f.tex : view.base);
      prog.i1('uBase', 0);
      common(prog, f, view);
      if (video) videoUniforms(prog, f, view);
      prog.f1('uT', clockOf(cfg[kind].speed)).fv4('uP', uP);
      if (kind === 'water') { const w = cfg.water; prog.f4('uW', w.amount * AMP.water, w.scale, w.glints, w.horizon).f2('uW2', 1 / mesh.span, 0); }
      else { const c = cfg.clouds, a = c.direction * Math.PI / 180; prog.f4('uC', c.amount * AMP.clouds, c.breath * 0.16, Math.cos(a), Math.sin(a)); }
      attrib(mesh.vbo, 0, 2, 16, 0); attrib(mesh.vbo, 1, 2, 16, 8);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.ibo);
      gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_SHORT, 0);
    }

    function drawLights(f, view, cfg, g, clockOf) {
      const video = f.isVideo, grade = video && f.level <= 1 && view.grade.amount > 0, l = cfg.lights, from = 0.5 + 0.5 * Math.cos(Math.PI * l.out);
      const prog = program('lights' + (video ? 'V' : 'S') + (grade ? 'g' : ''), () => kit.program(gl, lightsFS(kit.glsl.lib, video, grade), lightsVS(video))).use();
      kit.bindTexture(gl, 0, video ? f.tex : view.base);
      prog.i1('uBase', 0);
      common(prog, f, view);
      if (video) videoUniforms(prog, f, view);
      prog.f4('uL', l.amount, 0.26, 0.16, 0).f4('uL2', from, Math.min(1, from + 0.12), 0, 0).f1('uT', clockOf(l.speed));
      attrib(g.lights.vbo, 0, 4, 16, 0);
      gl.drawArrays(gl.POINTS, 0, g.lights.count);
    }

    function drawGlints(f, view, cfg, g, clockOf) {
      const video = f.isVideo, grade = video && f.level <= 1 && view.grade.amount > 0, w = cfg.water;
      const prog = program('glints' + (video ? 'V' : 'S') + (grade ? 'g' : ''), () => kit.program(gl, glintsFS(kit.glsl.lib, video, grade), glintsVS(video))).use();
      kit.bindTexture(gl, 0, video ? f.tex : view.base);
      prog.i1('uBase', 0);
      common(prog, f, view);
      if (video) videoUniforms(prog, f, view);
      const tint = w.tint || [-1, -1, -1], span = geo.water ? geo.water.span : 0.3;
      prog.f4('uG', w.glints, w.horizon, 1 / span, w.glint_size).f3('uGT', tint[0], tint[1], tint[2]).f1('uT', clockOf(w.speed));
      attrib(g.glints.vbo, 0, 4, 16, 0);
      gl.drawArrays(gl.POINTS, 0, g.glints.count);
    }

    function drawMist(f, view, cfg, g, clockOf) {
      const m = cfg.mist, prog = program('mist', () => kit.program(gl, MIST_FS, MIST_VS, ['aB'])).use(), t = m.tint;
      common(prog, f, view);
      prog.f3('uM', m.amount, 0, 0).f3('uMT', t[0], t[1], t[2]).f1('uT', clockOf(m.speed));
      attrib(g.mist.vbo, 0, 4, 24, 0); attrib(g.mist.vbo, 1, 2, 24, 16);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, g.mist.ibo);
      gl.drawElements(gl.TRIANGLES, g.mist.count * 6, gl.UNSIGNED_SHORT, 0);
    }

    function drawRain(f, cfg, g) {
      const r = cfg.rain, t = r.tint, prog = program('rain', () => kit.program(gl, RAIN_FS, RAIN_VS, ['aEnd'])).use();
      prog.f2('uRes', f.width, f.height).f4('uR', r.amount, Math.tan(r.angle * Math.PI / 180), (f.time * r.speed) % 1000, 0).f1('uS', f.scale).f3('uRT', t[0], t[1], t[2]);
      attrib(g.rain.vbo, 0, 4, 20, 0); attrib(g.rain.vbo, 1, 1, 20, 16);
      gl.drawArrays(gl.LINES, 0, g.rain.count);
    }

    /** The craft on screen now, each a small premultiplied quad over the finished frame. Nothing is drawn while none is crossing. */
    function drawCraft(f, view, cfg, B) {
      if (!cfg.craft || !cfg.craft.length) return 0;
      const aspect = f.mediaW / f.mediaH, state = craftState(cfg.craft.slice(0, B.craft), f.time, aspect);
      let drawn = 0;
      const s = f.scale, pic = view.pic, px = pic.x * s, py = pic.y * s, pw = pic.w * s, ph = pic.h * s;
      for (const c of state) {
        const cx = px + c.x * pw, cy = py + c.y * ph, rows = Math.ceil(c.count / 2);
        const bird = c.kind === 'gull' || c.kind === 'swallow';
        const r = c.size * ph * (c.kind === 'ship' ? 16 : bird ? 2.4 * rows + 2.4 : 14);
        if (cx + r < 0 || cx - r > f.width || cy + r < 0 || cy - r > f.height) continue;
        const code = c.kind === 'ship' ? 1 : bird ? 2 : 3;
        const extra = bird ? TAU * fract1(f.time * c.flap) : c.kind === 'drone' ? fract1(f.time * 0.8 + c.phase) : 0;
        craftProgram(c.kind).use().f2('uRes', f.width, f.height).f4('uPic', px, py, pw, ph).f2('uSize', aspect, s).f1('uTime', f.time % 1000)
          .f4('uA', c.x, c.y, c.heading, c.size).f4('uB', code, c.alpha, c.phase, c.count).f4('uC', c.colour[0], c.colour[1], c.colour[2], extra)
          .f4('uBox', cx / f.width * 2 - 1, 1 - cy / f.height * 2, r / f.width * 2, r / f.height * 2);
        attrib(shared.buffer, 0, 2, 0, 0);
        kit.draw(gl);
        drawn++;
      }
      return drawn;
    }

    /** The lamp rows (the quota as light), each a small premultiplied quad over the finished frame; the readings come from the page through the stage. Returns how many were drawn. */
    function drawLamps(f, view, cfg) {
      const lamps = cfg.lamps;
      if (!lamps) return 0;
      const live = f.live || {}, plan = lampPlan(lamps, live.readings, Date.now(), live.readingsAge);
      const aspect = f.mediaW / f.mediaH, s = f.scale, pic = view.pic, px = pic.x * s, py = pic.y * s, pw = pic.w * s, ph = pic.h * s, pad = 0.03 * ph;
      let drawn = 0;
      for (const row of plan) {
        const left = px + row.x[0] * pw - pad, right = px + row.x[1] * pw + pad, top = py + (row.y - row.height / 2) * ph - pad, bottom = py + (row.y + row.height / 2) * ph + pad;
        if (right < 0 || left > f.width || bottom < 0 || top > f.height) continue;
        if (!lampsProgram) lampsProgram = kit.program(gl, lampsFragment(), CRAFT_VS);
        lampsProgram.use().f2('uRes', f.width, f.height).f4('uPic', px, py, pw, ph).f2('uSize', aspect, s).f1('uTime', f.time % 1000)
          .f4('uRow', row.x[0], row.x[1], row.y, row.height).f4('uRow2', row.count, row.lit === null ? -1 : row.lit, row.anchor === 'start' ? 1 : -1, lamps.amount).f3('uCol', row.colour[0], row.colour[1], row.colour[2])
          .f4('uBox', (left + right) / 2 / f.width * 2 - 1, 1 - (top + bottom) / 2 / f.height * 2, (right - left) / 2 / f.width * 2, (bottom - top) / 2 / f.height * 2);
        attrib(shared.buffer, 0, 2, 0, 0);
        kit.draw(gl);
        drawn++;
      }
      return drawn;
    }

    /** What a touch adds on top: the ring's crest on water (its push on the picture is in the water mesh), a glow and sparkles elsewhere. */
    function drawPokes(f, view) {
      const pokes = f.live.pokes, s = f.scale, L = f.layout;
      if (!pokes || !pokes.length) return;
      for (let i = 0; i < pokes.length && i < 3; i++) {
        const p = pokes[i], x = (p.x - L.canvas.x) * s, y = (p.y - L.canvas.y) * s;
        if (p.kind === 'ripple') {
          const R = p.age * 150 * s, fade = Math.exp(-p.age * 0.85) * smooth(clamp(p.age / 0.06, 0, 1));
          touch.ring(f.width, f.height, x, y, R, 13 * s, [0.85, 0.95, 1.0], 0.30 * fade);
          touch.ring(f.width, f.height, x, y, R * 0.6, 15 * s, [0.85, 0.95, 1.0], 0.16 * fade);
        } else {
          const fade = Math.exp(-p.age * 1.7) * smooth(clamp(p.age / 0.05, 0, 1)), R = (34 + p.age * 46) * s;
          touch.glow(f.width, f.height, x, y, R * 1.7, [0.9, 0.95, 1.0], 0.34 * fade);
          const list = sparkles(p, p.age, []).map((k) => ({ x: (k.x - L.canvas.x) * s, y: (k.y - L.canvas.y) * s, size: k.size * s * 3, alpha: k.alpha, r: 1, g: 0.97, b: 0.9 }));
          touch.points(f.width, f.height, list, false);
        }
      }
    }

    function packPokes(f) {
      uP.fill(0);
      const pokes = f.live.pokes, s = f.scale, L = f.layout;
      if (!pokes) return;
      for (let i = 0; i < pokes.length && i < 3; i++) { const p = pokes[i]; uP.set([(p.x - L.canvas.x) * s, (p.y - L.canvas.y) * s, p.age, p.kind === 'ripple' ? 1 : 2], i * 4); }
    }

    // testing only (stage options {tuning: {off: ['water', ...]}}): the block without the named effects, so each one's cost and look can be judged alone
    let filteredFrom = null, filteredKey = '', filtered = null;
    function effectiveCfg(f) {
      const base = f.info.live, off = (f.tuning && f.tuning.off) || [];
      if (!base || !off.length) return base;
      const key = off.join(',');
      if (filteredFrom === base && filteredKey === key) return filtered;
      const out = {};
      for (const k of Object.keys(base)) if (off.indexOf(k) < 0) out[k] = base[k];
      if (out.craft) { out.craft = out.craft.filter((c) => off.indexOf(c.kind) < 0); if (!out.craft.length) delete out.craft; }      // 'ship', 'drone', 'gull' switch one kind off
      filteredFrom = base; filteredKey = key; filtered = out;
      return out;
    }

    return {
      available: true,
      invalidate() { disposeDerived(); },
      /** Draw one live frame. False when there is nothing to draw (the caller then draws the classic pass). */
      draw(f, view) {
        const cfg = view.empty ? {} : effectiveCfg(f);          // `empty`: only the picture (and its slow drift at the lowest tier)
        if (!cfg) return false;
        view.cfg = cfg;
        const B = budgetFor(f.level), s = f.scale, pic = view.pic, clockOf = (speed) => (f.time * speed) % 1000;
        const fxBottom = Math.min(f.height, (f.layout.area.top + f.layout.area.height + 0.05 * pic.h) * s);
        ensureRaster(f, view.src, cfg);
        ensureLights(f, view.src, cfg);
        ensureGeometry(f, view, cfg, B, fxBottom);
        packPokes(f);
        kit.toCanvas(gl, f);
        gl.disable(gl.BLEND); gl.disable(gl.SCISSOR_TEST);
        const sprites = !!(geo.lights || geo.glints || cfg.craft);
        drawBase(f, view, B, !sprites && !geo.water && !geo.clouds && view.drift);
        if (geo.water) drawMesh('water', geo.water, f, view, cfg, clockOf);
        if (geo.clouds) drawMesh('clouds', geo.clouds, f, view, cfg, clockOf);
        gl.enable(gl.SCISSOR_TEST); gl.scissor(0, Math.max(0, f.height - Math.round(fxBottom)), f.width, Math.round(fxBottom));
        if (geo.lights) drawLights(f, view, cfg, geo, clockOf);
        gl.enable(gl.BLEND);
        if (geo.mist) { gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); drawMist(f, view, cfg, geo, clockOf); }
        gl.blendFunc(gl.ONE, gl.ONE);
        if (geo.glints) drawGlints(f, view, cfg, geo, clockOf);
        if (geo.rain) drawRain(f, cfg, geo);
        gl.disable(gl.SCISSOR_TEST);
        gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        const lampRows = drawLamps(f, view, cfg);
        const craft = drawCraft(f, view, cfg, B);
        gl.blendFunc(gl.ONE, gl.ONE);
        drawPokes(f, view);
        gl.disable(gl.BLEND);
        touch.restore();
        // what this frame read, for the status line and the docs
        lastCost = estimateCost({
          pixels: f.width * f.height, waterPx: geo.water ? geo.water.area : 0, cloudsPx: geo.clouds ? geo.clouds.area : 0,
          lightsPx: geo.lights ? geo.lights.count * 49 : 0, glintsPx: geo.glints ? geo.glints.count * 36 : 0, craftPx: craft * 2500 + lampRows * 24000,
          mistPx: geo.mist ? geo.mist.count * (3.8 * 0.11) * (1.5 * 0.11) * Math.pow(pic.h * s, 2) * 0.5 : 0, rainPx: geo.rain ? geo.rain.count / 2 * 34 : 0,
          draws: 1 + (geo.water ? 1 : 0) + (geo.clouds ? 1 : 0) + (geo.lights ? 1 : 0) + (geo.mist ? 1 : 0) + (geo.glints ? 1 : 0) + (geo.rain ? 1 : 0) + craft + lampRows,
          vertices: (geo.water ? geo.water.vertices : 0) + (geo.clouds ? geo.clouds.vertices : 0) + (geo.lights ? geo.lights.count : 0) + (geo.glints ? geo.glints.count : 0),
        });
        return true;
      },
      dispose() {
        disposeDerived();
        touch.dispose();
        for (const k of Object.keys(programs)) programs[k].dispose();
        for (const k of Object.keys(craftPrograms)) craftPrograms[k].dispose();
        if (lampsProgram) { lampsProgram.dispose(); lampsProgram = null; }
        if (detect) detect.dispose();
        if (detectTaps) detectTaps.dispose();
      },
      /** Is a touch at picture position (u, v) on water? */
      onWater(cfg, u, v) { return !!(raster && cfg && cfg.water && regionWeightAt(raster, 0, u, v) > 0.3); },
      raster() { return raster; },
      cost() { return lastCost; },
      lightCount() { return lightList ? lightList.length / 4 : 0; },
    };
  }

  const SceneStageLive = {
    version: VERSION, LIMITS, AMP, POKE, BUDGET, MAX_REGIONS, MAX_POINTS, MAX_CRAFT, MAX_SIDE, LAMPS,
    normalizeLive, normalizeRegion, normalizeLamps, lampReadings, lampLit, lampPlan, lampsFragment, CRAFT_VS, effectNames, rasterRegions, regionWeightAt, weightBilinear, effectiveFeather, boxBlur, craftState, PokeBank, sparkles, sparks,
    budgetFor, intervalFor, effectRect, buildGrid, extractLights, placeGlints, placeRain, placeMist, estimateCost, rng,
    meshVS, meshFS, lightsVS, lightsFS, glintsVS, glintsFS, MIST_VS, MIST_FS, RAIN_VS, RAIN_FS, QUAD_VS, GLOW_FS, RING_VS, RING_FS, POINT_VS, POINT_FS, BASE_VS, BASE_FS, baseVideoVS, baseVideoFS,
    craftFragment, DETECT_FS, createTouchKit, compositeTouch, createLiveRenderer, hash1,
  };
  global.SceneStageLive = SceneStageLive;
  if (typeof module !== 'undefined' && module.exports) module.exports = SceneStageLive;
})(typeof window !== 'undefined' ? window : globalThis);
