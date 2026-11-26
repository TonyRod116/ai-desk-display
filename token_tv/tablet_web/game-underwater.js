/* DEEP BLUE (underwater pixel art) for the tablet: a 267 x 427 portrait pixel-art dive world (x3 = 801 x 1281), 30 Hz.
 *
 * Designed for smooth 30 fps even on modest tablet GPUs (Mali-T860 / Android WebView):
 *  - Static ocean gradient, baked Bayer-dithered ruins/shipwreck/corals (`bg` + `fg` plates) and precomputed perspective lookup
 *    tables eliminate per-pixel trigonometry and keep draw calls under ~450 per frame (down from 20,000+).
 *  - The animated organic Snell's-window ocean surface and golden seabed caustic web render directly into compact offscreen
 *    ImageData buffers (`Uint32Array`) and composite in ONE drawImage each.
 *  - Volumetric sunbeams draw as 14 crisp translucent light shafts on the native pixel canvas.
 *
 * Fun living dive world: articulated scuba diver (flutter-kicking fins, yellow tank, dive torch, exhale bubbles, rising BUBBLE RINGS,
 * underwater camera flashes), erupting sunken treasure chest, glowing giant pearl clam, cheeky orange reef octopus (puffs ink when
 * startled or tapped), patrolling reef shark parting a shimmering silver bait-ball, playful dolphin, sea turtle, whale/manta
 * silhouettes, bioluminescent jellyfish, anemone clownfish and swaying kelp.
 */
(function (global) {
  'use strict';

  const W = 267, H = 427, STEP = 1 / 30;
  const SURFACE_H = 80;
  const SAND_Y = 346;
  const CHEST = { x: 146, y: 364 };
  const CLAM = { x: 108, y: 198 };
  const ANEMONE = { x: 86, y: 356 };
  const COIN_FADE = 0.42; // <= 0.5s smooth alpha fade-out for treasure coins!
  const ROOMS = {
    left: {
      id: 'left',
      hit: [0, 210, 101, 136],
      litPlate: 'room_left_lit', litPos: [0, 212],
      occPlate: 'occ_left', occPos: [0, 194],
      approach: [130, 262], door: [100, 264], spot: [80, 266],
      depthX: 124, face: -1, relic: [68, 276],
    },
    right: {
      id: 'right',
      hit: [222, 248, 45, 96],
      litPlate: 'room_right_lit', litPos: [222, 244],
      occPlate: 'occ_right', occPos: [208, 230],
      approach: [190, 282], door: [222, 284], spot: [236, 284],
      depthX: 196, face: 1, relic: [251, 288],
    },
  };
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);

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

  function hexToRgba(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 255];
  }
  function packU32(r, g, b, a) {
    return ((a & 255) << 24) | ((b & 255) << 16) | ((g & 255) << 8) | (r & 255);
  }

  /* ---- pure tropical turquoise-to-moonlight water palettes (ZERO pink or muddy tones!) */
  function phaseFromClock(date) {
    if (!date) return 'day';
    const h = date.getHours() + date.getMinutes() / 60;
    if (h >= 6 && h < 8) return 'dawn';
    if (h >= 8 && h < 18.5) return 'day';
    if (h >= 18.5 && h < 20.5) return 'dusk';
    return 'night';
  }

  const PALETTES = {
    day: {
      // Tuned directly to reference.jpg: crisp white Snell's sky lenses -> seafoam jade -> calm lagoon turquoise -> deep teal
      surf: ['#f7fffd', '#9ef2e6', '#4ebdb4', '#2e909b', '#1c6b82', '#135572'],
      water: [[19, 98, 126], [15, 82, 114], [11, 66, 98], [9, 50, 82], [17, 80, 108], [30, 114, 134]],
      rayOuter: 'rgba(118, 236, 228, ',
      rayInner: 'rgba(218, 255, 248, ',
      rayGain: 1.0,
      caustic: '#ffffff',
      causticMid: '#f6fbff',
      causticSoft: '#eef6fc',
      causticScale: 1.0,
      moteBright: '#eefffa',
      moteDim: '#4eb2c6',
      veilTop: null,
      veilMid: null,
      veilBot: null,
      torchGain: 0.22,
      bioGlow: 0.28,
      bioCoral: false,
      bioRipple: false,
    },
    dawn: {
      // Warm golden-amber sunrise breaking through cool dawn seafoam-blue water
      surf: ['#fff7d4', '#ffc870', '#6fd0c4', '#28869d', '#145a7c', '#0b3a5c'],
      water: [[30, 86, 114], [20, 68, 104], [13, 50, 88], [9, 34, 70], [16, 62, 94], [28, 92, 114]],
      rayOuter: 'rgba(255, 196, 98, ',
      rayInner: 'rgba(255, 244, 192, ',
      rayGain: 0.92,
      caustic: '#fff8e8',
      causticMid: '#f8eed8',
      causticSoft: '#ece2cc',
      causticScale: 0.78,
      moteBright: '#fff2be',
      moteDim: '#62a0b4',
      veilTop: 'rgba(255, 158, 62, 0.22)',
      veilMid: 'rgba(20, 36, 70, 0.16)',
      veilBot: 'rgba(8, 20, 50, 0.30)',
      torchGain: 0.42,
      bioGlow: 0.45,
      bioCoral: false,
      bioRipple: false,
    },
    dusk: {
      // Dramatic deep twilight indigo with warm sunset rim overhead, darkening reef & awakening bioluminescence
      surf: ['#ffcf9c', '#d48688', '#426e9e', '#1a3f72', '#0e2854', '#081838'],
      water: [[14, 48, 86], [10, 36, 74], [8, 26, 60], [6, 18, 46], [10, 32, 64], [14, 44, 78]],
      rayOuter: 'rgba(255, 156, 96, ',
      rayInner: 'rgba(255, 214, 158, ',
      rayGain: 0.64,
      caustic: '#f2f6ff',
      causticMid: '#d6e4f8',
      causticSoft: '#b8cce8',
      causticScale: 0.46,
      moteBright: '#98fff8',
      moteDim: '#3488c2',
      veilTop: 'rgba(30, 22, 64, 0.28)',
      veilMid: 'rgba(9, 18, 54, 0.44)',
      veilBot: 'rgba(4, 11, 36, 0.56)',
      torchGain: 0.84,
      bioGlow: 0.82,
      bioCoral: true,
      bioRipple: true,
    },
    night: {
      // Deep midnight abyss night dive: silver moonbeams overhead, rich darkness over reef, vivid headlamp & bioluminescence
      surf: ['#d2ebff', '#5286be', '#1c4276', '#0d224c', '#061230', '#03091a'],
      water: [[5, 22, 52], [4, 16, 42], [3, 12, 34], [2, 8, 26], [4, 15, 38], [6, 22, 48]],
      rayOuter: 'rgba(116, 180, 255, ',
      rayInner: 'rgba(212, 238, 255, ',
      rayGain: 0.46,
      caustic: '#cce4ff',
      causticMid: '#a8d0f8',
      causticSoft: '#88b4e4',
      causticScale: 0.26,
      moteBright: '#72ffff',
      moteDim: '#2296dc',
      veilTop: 'rgba(3, 10, 28, 0.54)',
      veilMid: 'rgba(2, 7, 24, 0.68)',
      veilBot: 'rgba(1, 5, 18, 0.76)',
      torchGain: 1.0,
      bioGlow: 1.0,
      bioCoral: true,
      bioRipple: true,
    },
  };

  for (const p of Object.values(PALETTES)) {
    p.surfRgb = p.surf.map((hex) => hexToRgba(hex));
    p.surfU32 = p.surfRgb.map(([r, g, b]) => packU32(r, g, b, 255));
    p.causticDeepRgb = hexToRgba(p.causticSoft);
    p.causticMidRgb = hexToRgba(p.causticMid);
    p.causticPeakRgb = hexToRgba(p.caustic);
    p.causticSandRgb = p.causticMidRgb;
    p.causticWallRgb = p.causticDeepRgb;
    p.causticAlphaMax = Math.round(204 * (p.causticScale || 1.0));
  }

  /* ---- natural underwater ceiling swell + Snell's-window lookup tables (full 267 x 114 1px sharpness, ZERO trig/exp in loop!) */
  const SIN_N = 1024, SIN_MASK = SIN_N - 1, RAD_TO_LUT = SIN_N / (Math.PI * 2);
  const SIN_LUT = new Float32Array(SIN_N);
  for (let i = 0; i < SIN_N; i++) SIN_LUT[i] = Math.sin((i / SIN_N) * Math.PI * 2);

  const NSIZE = 64, NMASK = NSIZE - 1;
  const NOISE = new Float32Array(NSIZE * NSIZE);
  (function initNoise() {
    const r = seeded(918273);
    for (let i = 0; i < NOISE.length; i++) NOISE[i] = r();
  }());

  function sampleNoise(x, y) {
    const xi = Math.floor(x), yi = Math.floor(y);
    const fx = x - xi, fy = y - yi;
    const ux = fx * fx * (3 - 2 * fx), uy = fy * fy * (3 - 2 * fy);
    const x0 = xi & NMASK, x1 = (xi + 1) & NMASK;
    const y0 = (yi & NMASK) * NSIZE, y1 = ((yi + 1) & NMASK) * NSIZE;
    const a = NOISE[y0 + x0], b = NOISE[y0 + x1], c = NOISE[y1 + x0], d = NOISE[y1 + x1];
    return (a + (b - a) * ux) * (1 - uy) + (c + (d - c) * ux) * uy;
  }

  // Compact native-width surface (267 x 80): dissolves MUCH higher with real alpha transparency & irregular wave packets (ZERO "moqueta"!)
  const SW = W, SH = SURFACE_H;
  const SURF_X = new Float32Array(SW * SH);
  const SURF_Z = new Float32Array(SH);
  const SURF_SNELL = new Float32Array(SW * SH);
  const SURF_FADE = new Float32Array(SH);
  const SURF_ALPHA = new Float32Array(SH);
  const SURF_CEIL = new Float32Array(SW * SH);
  (function initSurfaceLUT() {
    for (let y = 0; y < SH; y++) {
      const d = y / SH;
      // Realistic scuba ceiling perspective compressing smoothly across y = 0..80 (NOT dragging down to y=114!)
      const xScale = 0.140 + d * 0.095;
      SURF_Z[y] = 32.0 * d + 24.0 * d * d;
      // Smooth height rolloff starting early at y = 26 -> dissolves completely into deep ocean water by y = 78!
      const fd = d < 0.30 ? 1.0 : 1.0 - ((d - 0.30) / 0.70);
      SURF_FADE[y] = fd * fd * (3.0 - 2.0 * fd);
      // Real gradual opacity dissolve (255 overhead -> translucent wispy ribbons mid -> 0 at bottom!)
      const af = d < 0.28 ? 1.0 : 1.0 - ((d - 0.28) / 0.72);
      SURF_ALPHA[y] = af * af * (3.0 - 2.0 * af);
      const row = y * SW;
      for (let x = 0; x < SW; x++) {
        SURF_X[row + x] = (x - 184) * xScale;
        // Focused Snell's sky window on center-right (y = 0..32) — crisp white lenses overhead, calm seafoam flanks!
        const dx = (x - 188) / (112 + d * 16);
        const dy = (y + 2) / 31.0;
        const snell = Math.exp(-(dx * dx * 0.92 + dy * dy * 1.65));
        SURF_SNELL[row + x] = snell;
        const ceil = Math.exp(-Math.pow(y / 28.0, 1.55)) * (0.30 + snell * 0.70);
        SURF_CEIL[row + x] = ceil;
      }
    }
  }());

  function surfaceCrest(X, Z, t) {
    // Natural ocean wave-groups ("sets"): macro packet modulation creates calm glassy patches beside bright wave clusters (ZERO carpet!)
    const pkt = sampleNoise(X * 0.048 + t * 0.07 + 4.2, Z * 0.032 + t * 0.09 + 11.8);
    const calmMod = 0.44 + pkt * 0.88; // ranges ~0.44 in calm glassy patches up to ~1.32 in active wave sets!
    const nLo = sampleNoise(X * 0.12 + t * 0.14, Z * 0.065 + t * 0.16);
    const nHi = sampleNoise(X * 0.28 - t * 0.19 + 17.3, Z * 0.14 + t * 0.22 + 9.1);
    const warp = (nLo - 0.5) * 4.0 + (nHi - 0.5) * 1.5;
    const w1 = SIN_LUT[(((X * 0.41 + Z * 0.88 + t * 1.12 + warp) * RAD_TO_LUT) + 65536) & SIN_MASK];
    const w2 = SIN_LUT[((((-X * 0.63) + Z * 1.24 + t * 0.94 - warp * 0.68 + 2.1) * RAD_TO_LUT) + 65536) & SIN_MASK];
    const w3 = SIN_LUT[(((X * 1.14 + Z * 1.86 + t * 1.48 + warp * 0.52 + 3.7) * RAD_TO_LUT) + 65536) & SIN_MASK];
    const w4 = SIN_LUT[((((-X * 0.91) + Z * 2.52 + t * 1.24 + 0.9) * RAD_TO_LUT) + 65536) & SIN_MASK];
    return clamp((0.46 + w1 * 0.26 + w2 * 0.22 + w3 * 0.15 + w4 * 0.09) * calmMod, 0, 1);
  }

  function surfaceWave(x, y, t) {
    const iy = clamp(Math.round(y), 0, SH - 1);
    const ix = clamp(Math.round(x), 0, SW - 1);
    const idx = iy * SW + ix;
    const crest = surfaceCrest(SURF_X[idx], SURF_Z[iy], t);
    return (crest * (0.50 + SURF_SNELL[idx] * 0.64) + SURF_CEIL[idx] * 0.16) * SURF_FADE[iy];
  }

  /* ---- 7 luminous volumetric sunbeams pouring gracefully from center-right / right across the reef */
  const RAYS = [
    { topX: 142, width: 15, slope: -0.26, len: 296, phase: 0.3, speed: 0.68, strength: 0.68 },
    { topX: 168, width: 22, slope: -0.20, len: 344, phase: 1.4, speed: 0.55, strength: 0.90 },
    { topX: 194, width: 30, slope: -0.14, len: 368, phase: 2.3, speed: 0.61, strength: 1.00 },
    { topX: 218, width: 28, slope: -0.08, len: 362, phase: 3.7, speed: 0.50, strength: 0.96 },
    { topX: 238, width: 24, slope: -0.02, len: 336, phase: 4.9, speed: 0.64, strength: 0.86 },
    { topX: 254, width: 18, slope:  0.04, len: 292, phase: 0.9, speed: 0.58, strength: 0.74 },
    { topX: 266, width: 14, slope:  0.09, len: 246, phase: 2.8, speed: 0.72, strength: 0.58 },
  ];

  function rayAt(ray, t) {
    const sway = Math.sin(t * ray.speed + ray.phase) * 6.5 + Math.cos(t * ray.speed * 0.51 + ray.phase * 1.6) * 2.8;
    const pulse = 0.65 + 0.35 * Math.sin(t * (ray.speed * 1.18) + ray.phase * 1.3);
    const width = ray.width * (0.88 + 0.22 * Math.sin(t * 0.42 + ray.phase * 2.1));
    return { topX: ray.topX + sway, width, slope: ray.slope, len: ray.len, alpha: ray.strength * pulse };
  }

  function inSunbeam(x, y, t) {
    if (y > 356) return 0;
    let best = 0;
    for (let i = 0; i < RAYS.length; i++) {
      const r = rayAt(RAYS[i], t);
      if (y > r.len) continue;
      const cx = r.topX + y * r.slope;
      const hw = (r.width + y * 0.14) * 0.5;
      const d = Math.abs(x - cx) / hw;
      if (d < 1) {
        const v = (1 - d) * r.alpha * (1 - y / r.len);
        if (v > best) best = v;
      }
    }
    return best;
  }

  /* ---- ultra-fast offscreen buffer helpers (zero allocation per frame) */
  function makeCanvas(w, h, opaque) {
    if (typeof document === 'undefined') return null;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d', opaque ? { alpha: false } : undefined);
    if (g) g.imageSmoothingEnabled = false;
    return { canvas: c, g };
  }

  function makeBackdropCache() {
    const out = {};
    for (const [name, pal] of Object.entries(PALETTES)) {
      const m = makeCanvas(W, H, true);
      if (!m) return null;
      const stops = pal.water;
      for (let y = 0; y < H; y += 2) {
        const f = Math.min(1, y / (SAND_Y + 6));
        const pos = f * (stops.length - 1);
        const i = Math.min(stops.length - 2, Math.floor(pos));
        const t = pos - i;
        m.g.fillStyle = 'rgb(' + Math.round(lerp(stops[i][0], stops[i + 1][0], t)) + ',' + Math.round(lerp(stops[i][1], stops[i + 1][1], t)) + ',' + Math.round(lerp(stops[i][2], stops[i + 1][2], t)) + ')';
        m.g.fillRect(0, y, W, 2);
      }
      out[name] = m.canvas;
    }
    return out;
  }

  /* ---- ultra-fast surface update into native 267 x 114 ImageData (1 drawImage, ZERO Math.sin/exp/sqrt in loop!) */
  function classifySurface(crest, snell, ceil, fade) {
    // 1. Inside Snell's window (y = 0..32): crisp organic pure-white sky lenses separated by glassy seafoam troughs!
    const sky = crest * (0.42 + snell * 0.96);
    if (snell > 0.20 && sky > 0.78) return 0;
    if (snell > 0.14 && sky > 0.67) return 1;
    // 2. Spaced broken turquoise wave crests with calm glassy gaps (ZERO carpet/moqueta!), fading smoothly by y = 78!
    const rib = (crest * 0.82 + ceil * 0.26) * fade;
    if (rib > 0.64) return 2;
    if (rib > 0.48) return 3;
    if (rib > 0.34) return 4;
    return -1;
  }

  function updateSurfaceBuffer(buf, pal, t) {
    const u32 = buf.u32;
    const rgbs = pal.surfRgb;
    const ptx = t * 0.07 + 4.2, ptz = t * 0.09 + 11.8;
    const tx1 = t * 0.14, tz1 = t * 0.16, tx2 = -t * 0.19 + 17.3, tz2 = t * 0.22 + 9.1;
    const wt1 = t * 1.12, wt2 = t * 0.94 + 2.1, wt3 = t * 1.48 + 3.7, wt4 = t * 1.24 + 0.9;
    for (let y = 0; y < SH; y++) {
      const Z = SURF_Z[y];
      const fade = SURF_FADE[y];
      const rowAlpha = Math.round(SURF_ALPHA[y] * 255);
      if (rowAlpha < 8) { u32.fill(0, y * SW, (y + 1) * SW); continue; }
      const pnz = Z * 0.032 + ptz;
      const nz1 = Z * 0.065 + tz1, nz2 = Z * 0.14 + tz2;
      const z1 = Z * 0.88 + wt1, z2 = Z * 1.24 + wt2, z3 = Z * 1.86 + wt3, z4 = Z * 2.52 + wt4;
      const row = y * SW;
      for (let x = 0; x < SW; x++) {
        const idx = row + x;
        const X = SURF_X[idx];
        const pkt = sampleNoise(X * 0.048 + ptx, pnz);
        const nLo = sampleNoise(X * 0.12 + tx1, nz1);
        const nHi = sampleNoise(X * 0.28 + tx2, nz2);
        const warp = (nLo - 0.5) * 4.0 + (nHi - 0.5) * 1.5;
        const w1 = SIN_LUT[(((X * 0.41 + z1 + warp) * RAD_TO_LUT) + 65536) & SIN_MASK];
        const w2 = SIN_LUT[((((-X * 0.63) + z2 - warp * 0.68) * RAD_TO_LUT) + 65536) & SIN_MASK];
        const w3 = SIN_LUT[(((X * 1.14 + z3 + warp * 0.52) * RAD_TO_LUT) + 65536) & SIN_MASK];
        const w4 = SIN_LUT[((((-X * 0.91) + z4) * RAD_TO_LUT) + 65536) & SIN_MASK];
        let crest = (0.46 + w1 * 0.26 + w2 * 0.22 + w3 * 0.15 + w4 * 0.09) * (0.44 + pkt * 0.88);
        if (crest < 0) crest = 0; else if (crest > 1) crest = 1;
        const c = classifySurface(crest, SURF_SNELL[idx], SURF_CEIL[idx], fade);
        if (c < 0) { u32[idx] = 0; continue; }
        const rgb = rgbs[c];
        // Bright Snell's lenses stay crisp opaque; lower ribbons smoothly fade out via real alpha dissolve!
        const a = c <= 1 ? 255 : rowAlpha;
        u32[idx] = (a << 24) | (rgb[2] << 16) | (rgb[1] << 8) | rgb[0];
      }
    }
    buf.g.putImageData(buf.img, 0, 0);
  }

  function drawSurfaceFallback(g, pal, t) {
    // Headless Node fallback with exact alpha fade matching updateSurfaceBuffer!
    const rgbs = pal.surfRgb;
    for (let y = 0; y < SH; y++) {
      const Z = SURF_Z[y], fade = SURF_FADE[y], af = SURF_ALPHA[y], row = y * SW;
      if (af < 0.04) continue;
      let runCol = -1, runX = 0;
      for (let x = 0; x <= SW; x++) {
        let idx = -1;
        if (x < SW) {
          const pos = row + x;
          idx = classifySurface(surfaceCrest(SURF_X[pos], Z, t), SURF_SNELL[pos], SURF_CEIL[pos], fade);
        }
        if (idx !== runCol) {
          if (runCol >= 0) {
            const rgb = rgbs[runCol];
            const a = runCol <= 1 ? 1.0 : af;
            g.fillStyle = a >= 0.98 ? pal.surf[runCol] : ('rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',' + a.toFixed(2) + ')');
            g.fillRect(runX, y, x - runX, 1);
          }
          runCol = idx; runX = x;
        }
      }
    }
  }

  /* ---- ultra-fast volumetric sunbeams: 14 clean diagonal quads (0.15ms instead of 1,800 fillRects!) */
  function drawSunbeams(g, pal, t) {
    const hasPath = typeof g.beginPath === 'function' && typeof g.fill === 'function';
    for (let i = 0; i < RAYS.length; i++) {
      const r = rayAt(RAYS[i], t);
      const a = r.alpha * pal.rayGain;
      if (a < 0.06) continue;
      if (hasPath) {
        const x0 = r.topX, x1 = r.topX + r.len * r.slope;
        const hw0 = r.width * 0.5, hw1 = (r.width + r.len * 0.16) * 0.5;
        // Single seamless full-length outer shaft (no mid-water seam, 14 total quads!)
        g.fillStyle = pal.rayOuter + (a * 0.115).toFixed(3) + ')';
        g.beginPath();
        g.moveTo(x0 - hw0, 10); g.lineTo(x0 + hw0, 10);
        g.lineTo(x1 + hw1, r.len); g.lineTo(x1 - hw1, r.len);
        g.closePath(); g.fill();
        // Luminous inner mint core fading cleanly at 72% depth
        const cy = 10 + (r.len - 10) * 0.72;
        const xc = r.topX + cy * r.slope, hwc = (r.width + cy * 0.16) * 0.22;
        g.fillStyle = pal.rayInner + (a * 0.135).toFixed(3) + ')';
        g.beginPath();
        g.moveTo(x0 - hw0 * 0.44, 10); g.lineTo(x0 + hw0 * 0.44, 10);
        g.lineTo(xc + hwc, cy); g.lineTo(xc - hwc, cy);
        g.closePath(); g.fill();
      } else {
        // Fallback for simple fillRect-only mock canvases
        for (let y = 10; y < r.len; y += 6) {
          const fade = 1 - y / r.len;
          const cx = Math.round(r.topX + y * r.slope), w = Math.round(r.width + y * 0.16);
          g.fillStyle = pal.rayOuter + (a * fade * 0.17).toFixed(3) + ')';
          g.fillRect(cx - (w >> 1), y, w, 6);
          const cw = Math.max(2, Math.round(w * 0.44));
          g.fillStyle = pal.rayInner + (a * fade * 0.15).toFixed(3) + ')';
          g.fillRect(cx - (cw >> 1), y, cw, 6);
        }
      }
    }
  }

  /* ---- TRUE PHYSICAL RAY-REFRACTION WATER CAUSTICS (Snell's-law photon splatting through crossing ocean wave trains!) */
  // Real underwater caustics are NOT a scrolling net: crossing surface wave trains act as shifting water lenses that
  // continuously focus sunlight into razor-narrow bright white filaments, then widen, blur & fade semi-transparent as
  // waves pass, merge, split, and refocus elsewhere!
  // We trace 112 x 112 (12,544) refracted sun rays through 6 crossing periodic wave trains into a seamless 128 x 128
  // photon-accumulation tile (~0.9ms!), then sample 1:1 onto the full native 267 x 427 scene canvas!
  const MW = 134, MH = 214;
  const CW = W, CH = H;
  const CT_SIZE = 128, CT_MASK = 127, RAY_N = 112;
  const CT_ACC = new Float32Array(CT_SIZE * CT_SIZE);
  const CT_ALPHA = new Uint8Array(CT_SIZE * CT_SIZE);
  // 6 crossing periodic ocean wave trains: finer wave-vectors (3..4 cycles/tile) so caustic holes are delicate,
  // natural reef-scale, and continuously merge, split, widen/defocus soft & snap back into bright white filaments!
  const CAUSTIC_WAVES = [
    { kx:  3, ky:  1, amp: 1.04, spd:  1.18, ph: 0.3 },
    { kx: -1, ky:  3, amp: 1.00, spd:  0.98, ph: 1.7 },
    { kx:  3, ky: -2, amp: 0.72, spd: -1.32, ph: 2.9 },
    { kx: -4, ky: -1, amp: 0.62, spd:  1.46, ph: 4.1 },
    { kx:  2, ky:  4, amp: 0.54, spd: -1.22, ph: 5.2 },
    { kx: -3, ky: -4, amp: 0.44, spd:  1.62, ph: 0.9 },
  ];
  // Precomputed LUT index step per ray for each wave (ZERO trig in the 12,544-ray inner loop!)
  const TWO_PI_LUT = SIN_N; // 1024 entries = 2*pi

  const CAUSTIC_UI = new Int16Array(CW * CH);
  const CAUSTIC_VI = new Int16Array(CW * CH);
  const CAUSTIC_SUN = new Float32Array(CW * CH);
  const DEFAULT_CAUSTIC_MASK = new Uint8Array(MW * MH);
  (function initCausticLUT() {
    // 1. Default 134 x 214 fallback exposure mask (used only when atlas lacks baked caustic_mask)
    for (let j = 0; j < MH; j++) {
      const y = j * 2, row = j * MW;
      if (y < SAND_Y) {
        for (let i = 0; i < MW; i++) {
          const x = i * 2;
          DEFAULT_CAUSTIC_MASK[row + i] = (x < 96 || x > 210) ? 140 : 0;
        }
      } else {
        const horiz = clamp((y - SAND_Y) / 10.0, 0.30, 1.0);
        for (let i = 0; i < MW; i++) {
          const x = i * 2;
          const ctr = 0.70 + 0.30 * Math.exp(-Math.pow((x - 146) / 96, 2));
          DEFAULT_CAUSTIC_MASK[row + i] = Math.round(clamp(horiz * ctr * 245, 0, 255));
        }
      }
    }
    // 2. Full-native 267 x 427 perspective UV + sunlight LUT (finer realistic reef scale, zero scrolling!)
    for (let y = 0; y < CH; y++) {
      const row = y * CW;
      if (y < SAND_Y) {
        // Vertical & sloped ruins/columns/shipwreck/archway: delicate refracted sun ripples draping over 3D stone & timber!
        const depthSun = clamp(1.0 - y / 320, 0.30, 1.0);
        const vy = y * 1.48;
        for (let x = 0; x < CW; x++) {
          const warp = Math.sin(y * 0.055 + x * 0.032) * 3.0;
          CAUSTIC_UI[row + x] = Math.round((x - 186 + y * 0.18) * 1.54 + warp);
          CAUSTIC_VI[row + x] = Math.round(vy - warp * 0.6);
          const beamX = 186 - y * 0.16;
          const beam = Math.exp(-Math.pow((x - beamX) / 102, 2));
          CAUSTIC_SUN[row + x] = clamp(depthSun * 0.50 + beam * 0.50, 0.32, 1.0);
        }
      } else {
        // Horizontal golden sandy seabed: finer foreshortened perspective (compact natural underwater cells!)
        const vf = (y - SAND_Y) / (CH - SAND_Y);
        const persp = 1.0 / (0.28 + vf * 0.72);
        const vv = 128.0 + persp * 126.0;
        for (let x = 0; x < CW; x++) {
          const warp = Math.sin(x * 0.06 + vf * 4.4) * 2.2;
          CAUSTIC_UI[row + x] = Math.round((x - 146) * 1.18 * persp + warp);
          CAUSTIC_VI[row + x] = Math.round(vv + Math.cos(x * 0.048) * 1.8);
          CAUSTIC_SUN[row + x] = clamp(Math.exp(-Math.pow((x - 148) / 86, 2)) * (0.64 + vf * 0.36), 0.38, 1.0);
        }
      }
    }
  }());

  function extractCausticMask(atlas, frames) {
    const f = frames && frames.caustic_mask;
    if (!atlas || !f) return DEFAULT_CAUSTIC_MASK;
    const m = makeCanvas(MW, MH, false);
    if (!m || typeof m.g.getImageData !== 'function') return DEFAULT_CAUSTIC_MASK;
    try {
      m.g.drawImage(atlas, f[0], f[1], f[2], f[3], 0, 0, MW, MH);
      const data = m.g.getImageData(0, 0, MW, MH).data;
      const out = new Uint8Array(MW * MH);
      for (let k = 0; k < out.length; k++) out[k] = data[k * 4];
      return out;
    } catch (_) {
      return DEFAULT_CAUSTIC_MASK;
    }
  }

  function buildRefractionCausticTile(t) {
    CT_ACC.fill(0);
    // Unrolled 6 crossing wave phases in SIN_LUT index space (0..1023)
    const w0 = CAUSTIC_WAVES[0], w1 = CAUSTIC_WAVES[1], w2 = CAUSTIC_WAVES[2];
    const w3 = CAUSTIC_WAVES[3], w4 = CAUSTIC_WAVES[4], w5 = CAUSTIC_WAVES[5];
    const p0 = ((t * w0.spd + w0.ph) * RAD_TO_LUT) | 0;
    const p1 = ((t * w1.spd + w1.ph) * RAD_TO_LUT) | 0;
    const p2 = ((t * w2.spd + w2.ph) * RAD_TO_LUT) | 0;
    const p3 = ((t * w3.spd + w3.ph) * RAD_TO_LUT) | 0;
    const p4 = ((t * w4.spd + w4.ph) * RAD_TO_LUT) | 0;
    const p5 = ((t * w5.spd + w5.ph) * RAD_TO_LUT) | 0;
    // Gentle breathing focal-depth modulation so lines naturally bloom wide/soft and snap razor-sharp!
    const focusBreath = 1.0 + 0.14 * SIN_LUT[((t * 0.65 * RAD_TO_LUT) + 65536) & SIN_MASK];
    const a0x = w0.amp * w0.kx * focusBreath, a0y = w0.amp * w0.ky * focusBreath;
    const a1x = w1.amp * w1.kx * focusBreath, a1y = w1.amp * w1.ky * focusBreath;
    const a2x = w2.amp * w2.kx * focusBreath, a2y = w2.amp * w2.ky * focusBreath;
    const a3x = w3.amp * w3.kx * focusBreath, a3y = w3.amp * w3.ky * focusBreath;
    const a4x = w4.amp * w4.kx * focusBreath, a4y = w4.amp * w4.ky * focusBreath;
    const a5x = w5.amp * w5.kx * focusBreath, a5y = w5.amp * w5.ky * focusBreath;

    const rayStep = CT_SIZE / RAY_N;
    const lutStep = TWO_PI_LUT / RAY_N;
    // Forward Snell's-law ray splatting: each ray bends by the local wave surface gradient (dh/du, dh/dv)
    // and deposits its light bilinearly onto the seabed! Where rays pile up -> sharp bright white caustic;
    // where waves flatten -> wide, soft, semi-transparent defocused band; where waves diverge -> crystal clear!
    for (let ry = 0; ry < RAY_N; ry++) {
      const ly = ry * lutStep;
      const by0 = (ly * w0.ky + p0 + 65536) | 0;
      const by1 = (ly * w1.ky + p1 + 65536) | 0;
      const by2 = (ly * w2.ky + p2 + 65536) | 0;
      const by3 = (ly * w3.ky + p3 + 65536) | 0;
      const by4 = (ly * w4.ky + p4 + 65536) | 0;
      const by5 = (ly * w5.ky + p5 + 65536) | 0;
      const syBase = ry * rayStep;
      for (let rx = 0; rx < RAY_N; rx++) {
        const lx = rx * lutStep;
        const c0 = SIN_LUT[(by0 + ((lx * w0.kx) | 0)) & SIN_MASK];
        const c1 = SIN_LUT[(by1 + ((lx * w1.kx) | 0)) & SIN_MASK];
        const c2 = SIN_LUT[(by2 + ((lx * w2.kx) | 0)) & SIN_MASK];
        const c3 = SIN_LUT[(by3 + ((lx * w3.kx) | 0)) & SIN_MASK];
        const c4 = SIN_LUT[(by4 + ((lx * w4.kx) | 0)) & SIN_MASK];
        const c5 = SIN_LUT[(by5 + ((lx * w5.kx) | 0)) & SIN_MASK];

        const hitX = rx * rayStep + c0 * a0x + c1 * a1x + c2 * a2x + c3 * a3x + c4 * a4x + c5 * a5x;
        const hitY = syBase       + c0 * a0y + c1 * a1y + c2 * a2y + c3 * a3y + c4 * a4y + c5 * a5y;

        const ix = Math.floor(hitX);
        const iy = Math.floor(hitY);
        const fx = hitX - ix;
        const fy = hitY - iy;
        const x0 = ix & CT_MASK, x1 = (ix + 1) & CT_MASK;
        const r0 = (iy & CT_MASK) << 7, r1 = ((iy + 1) & CT_MASK) << 7;
        const omx = 1.0 - fx, omy = 1.0 - fy;
        CT_ACC[r0 | x0] += omx * omy;
        CT_ACC[r0 | x1] += fx  * omy;
        CT_ACC[r1 | x0] += omx * fy;
        CT_ACC[r1 | x1] += fx  * fy;
      }
    }

    // Convert accumulated photon density -> lively, unmistakable pure-white optical opacity (0..255):
    // Below 1.08x average: 0 (crystal-clear open sand/stone!).
    // 1.08x .. 2.0x: clearly visible soft wide defocused translucent bands (alpha ~ 20-50%)!
    // 2.0x .. 4.5x+: crisp narrow focused pure-white filaments & bright cusp crossings (alpha ~ 58-89%)!
    const avg = (RAY_N * RAY_N) / (CT_SIZE * CT_SIZE);
    const invAvg = 1.0 / avg;
    for (let k = 0; k < CT_ACC.length; k++) {
      const ratio = CT_ACC[k] * invAvg;
      if (ratio <= 1.08) { CT_ALPHA[k] = 0; continue; }
      const ex = ratio - 1.08;
      const tone = ex / (ex + 1.12);
      const cusp = ratio > 2.25 ? Math.min(0.32, (ratio - 2.25) * 0.11) : 0;
      const v = Math.min(1.0, tone * 0.92 + cusp);
      CT_ALPHA[k] = (v * 255) | 0;
    }
  }

  let _cachedMaskRef = null, _activeIdx = null, _activeMask = null;
  function getActiveCausticPixels(mArr) {
    if (mArr === _cachedMaskRef && _activeIdx) return;
    _cachedMaskRef = mArr;
    let count = 0;
    for (let y = 0; y < CH; y++) {
      const mRow = (y >> 1) * MW;
      for (let x = 0; x < CW; x++) if (mArr[mRow + (x >> 1)] >= 12) count++;
    }
    const idxs = new Int32Array(count);
    const vals = new Uint8Array(count);
    let k = 0;
    for (let y = 0; y < CH; y++) {
      const row = y * CW, mRow = (y >> 1) * MW;
      for (let x = 0; x < CW; x++) {
        const mb = mArr[mRow + (x >> 1)];
        if (mb >= 12) { idxs[k] = row + x; vals[k] = mb; k++; }
      }
    }
    _activeIdx = idxs;
    _activeMask = vals;
  }

  function updateCausticBuffer(buf, pal, t, mask) {
    const u32 = buf.u32;
    const mArr = mask || DEFAULT_CAUSTIC_MASK;
    getActiveCausticPixels(mArr);
    const idxs = _activeIdx, vals = _activeMask;
    const [wr, wg, wb] = pal.causticPeakRgb;
    const aMax = pal.causticAlphaMax;
    const sandStart = SAND_Y * CW;
    const rgbPacked = (wb << 16) | (wg << 8) | wr;

    // 1. Trace real refracted sun rays through the animated crossing ocean waves (ZERO scrolling net!)
    buildRefractionCausticTile(t);

    // 2. Composite pure translucent white onto active sunlit sand & ruins pixels (full 1px native sharpness!)
    for (let k = 0; k < idxs.length; k++) {
      const idx = idxs[k];
      const tIdx = ((CAUSTIC_VI[idx] & CT_MASK) << 7) | (CAUSTIC_UI[idx] & CT_MASK);
      const cByte = CT_ALPHA[tIdx];
      if (cByte < 8) { u32[idx] = 0; continue; }

      const isSand = idx >= sandStart;
      const cVal = cByte * 0.00392157;
      const sun = CAUSTIC_SUN[idx];
      const mNorm = 0.42 + (vals[k] * 0.00392157) * 0.58;
      const layerGain = isSand ? (1.02 + sun * 0.40) : (0.94 + sun * 0.42);

      // Pure white with clearly visible physical opacity range:
      // wide defocused bands glow soft & semi-transparent (~20-50%); focused sharp filaments & crossings shine bright white (~68-89%)!
      const alpha = Math.round(cVal * mNorm * layerGain * aMax);
      if (alpha < 10) { u32[idx] = 0; continue; }
      u32[idx] = ((alpha > 228 ? 228 : alpha) << 24) | rgbPacked;
    }
    buf.g.putImageData(buf.img, 0, 0);
  }

  function drawCausticsFallback(g, pal, t, mask) {
    // Lightweight translucent fallback for fillRect-only headless tests
    const mArr = mask || DEFAULT_CAUSTIC_MASK;
    const [sr, sg, sb] = pal.causticMidRgb;
    for (let y = SAND_Y; y < CH; y += 4) {
      const mRow = (y >> 1) * MW;
      for (let x = 0; x < CW; x += 4) {
        const mByte = mArr[mRow + (x >> 1)];
        if (mByte < 24) continue;
        const a1 = SIN_LUT[(((x * 0.08 + y * 0.06 + t * 0.92) * RAD_TO_LUT) + 65536) & SIN_MASK];
        const b1 = SIN_LUT[((((-x * 0.04) + y * 0.11 + t * 0.74) * RAD_TO_LUT) + 65536) & SIN_MASK];
        const f1 = 1.0 - Math.abs(a1 + b1) * 1.85;
        if (f1 > 0.42) {
          g.fillStyle = 'rgba(' + sr + ',' + sg + ',' + sb + ',' + (f1 * f1 * 0.42).toFixed(2) + ')';
          g.fillRect(x, y, 3, 2);
        }
      }
    }
  }

  /* ---- interactive reef props: Treasure Chest, Giant Glowing Pearl Clam, Swaying Anemone, Cheeky Reef Octopus */
  function drawTreasureChest(g, ch, t) {
    const x = CHEST.x, y = CHEST.y, open = ch.open;
    if (open > 0.08) {
      const a = (open * (0.22 + 0.06 * Math.sin(t * 6))).toFixed(3);
      g.fillStyle = 'rgba(255, 224, 96, ' + a + ')';
      g.fillRect(x - 10, y - 22, 20, 16);
      g.fillStyle = 'rgba(255, 232, 130, ' + (open * 0.11).toFixed(3) + ')';
      g.fillRect(x - 15, y - 34, 30, 14);
    }
    g.fillStyle = 'rgba(12, 32, 42, 0.45)'; g.fillRect(x - 14, y + 7, 28, 3);
    g.fillStyle = '#3b2112'; g.fillRect(x - 12, y - 2, 24, 10);
    g.fillStyle = '#6e3d1e'; g.fillRect(x - 11, y - 1, 22, 8);
    g.fillStyle = '#92562a'; g.fillRect(x - 11, y, 22, 2);
    g.fillStyle = '#e8b62c';
    g.fillRect(x - 12, y - 2, 2, 10); g.fillRect(x + 10, y - 2, 2, 10);
    g.fillRect(x - 12, y + 6, 24, 2); g.fillRect(x - 2, y - 2, 5, 5);
    g.fillStyle = '#fff098'; g.fillRect(x - 1, y - 1, 3, 2);
    g.fillStyle = '#22140a'; g.fillRect(x, y + 1, 1, 2);
    if (open > 0.1) {
      const gh = Math.round(open * 5);
      g.fillStyle = '#f2be2c'; g.fillRect(x - 10, y - 2 - gh, 20, gh + 1);
      g.fillStyle = '#fff49c'; g.fillRect(x - 8, y - 2 - gh, 16, 2);
      g.fillStyle = '#36f0a8'; g.fillRect(x - 5, y - 1 - gh, 3, 2);
      g.fillStyle = '#ff4898'; g.fillRect(x + 3, y - 1 - gh, 3, 2);
    }
    const lift = Math.round(open * 7);
    g.fillStyle = '#3b2112'; g.fillRect(x - 13, y - 7 - lift, 26, 6);
    g.fillStyle = '#7e4824'; g.fillRect(x - 12, y - 6 - lift, 24, 4);
    g.fillStyle = '#aa6834'; g.fillRect(x - 11, y - 6 - lift, 22, 2);
    g.fillStyle = '#e8b62c'; g.fillRect(x - 13, y - 7 - lift, 2, 6); g.fillRect(x + 11, y - 7 - lift, 2, 6);
    g.fillStyle = '#fff098'; g.fillRect(x - 12, y - 7 - lift, 24, 1);
  }

  function drawGiantClam(g, cl, pal, t) {
    const x = CLAM.x, y = CLAM.y, gap = Math.round(cl.open * 7);
    if (cl.open > 0.18) {
      g.fillStyle = 'rgba(210, 255, 252, ' + ((0.18 + pal.bioGlow * 0.22) * cl.open).toFixed(3) + ')';
      g.fillRect(x - 8, y - 6 - gap, 16, 12);
      g.fillStyle = '#28d8d4'; g.fillRect(x - 8, y - 1, 16, 2);
      g.fillStyle = '#d4f4ff'; g.fillRect(x - 3, y - 5 - (gap >> 1), 6, 6);
      g.fillStyle = '#ffffff'; g.fillRect(x - 2, y - 4 - (gap >> 1), 3, 3);
      if (Math.sin(t * 7) > 0.35) {
        g.fillStyle = '#ffffff';
        g.fillRect(x, y - 7 - (gap >> 1), 1, 5);
        g.fillRect(x - 2, y - 5 - (gap >> 1), 5, 1);
      }
    }
    g.fillStyle = '#3b2452'; g.fillRect(x - 10, y, 20, 5);
    g.fillStyle = '#784894'; g.fillRect(x - 9, y, 18, 3);
    g.fillStyle = '#be82d8'; g.fillRect(x - 7, y + 1, 3, 2); g.fillRect(x - 1, y + 1, 3, 2); g.fillRect(x + 5, y + 1, 3, 2);
    g.fillStyle = '#3b2452'; g.fillRect(x - 10, y - 4 - gap, 20, 5);
    g.fillStyle = '#8e58ab'; g.fillRect(x - 9, y - 4 - gap, 18, 4);
    g.fillStyle = '#d6a4ee'; g.fillRect(x - 8, y - 4 - gap, 16, 1);
  }

  function drawAnemone(g, t) {
    const x = ANEMONE.x, y = ANEMONE.y;
    g.fillStyle = '#681a44'; g.fillRect(x - 7, y - 2, 14, 4);
    for (let i = -6; i <= 6; i += 3) {
      const len = 9 + (6 - Math.abs(i));
      for (let k = 0; k < len; k += 3) {
        const sway = Math.sin(t * 2.8 - k * 0.3 + i * 0.5) * (0.6 + k * 0.22);
        g.fillStyle = k > len - 4 ? '#ff9ee0' : k > len * 0.4 ? '#eb4c96' : '#a82264';
        g.fillRect(Math.round(x + i + sway), y - 3 - k, 2, 3);
      }
    }
  }

  function drawOctopus(g, oc, t) {
    const x = Math.round(oc.x), y = Math.round(oc.y);
    for (const ic of oc.inks) {
      const a = clamp(1 - ic.age / 2.6, 0, 1) * 0.72, r = Math.round(4 + ic.age * 9);
      g.fillStyle = 'rgba(18, 12, 46, ' + a.toFixed(2) + ')';
      g.fillRect(Math.round(ic.x - r), Math.round(ic.y - r * 0.7), r * 2, Math.round(r * 1.4));
      g.fillStyle = 'rgba(42, 24, 86, ' + (a * 0.7).toFixed(2) + ')';
      g.fillRect(Math.round(ic.x - r * 0.6), Math.round(ic.y - r * 0.9), Math.round(r * 1.2), Math.round(r * 1.8));
    }
    for (let k = 0; k < 6; k++) {
      const side = (k - 2.5) * 3.4, len = oc.jet > 0 ? 14 : 10 + (k % 2) * 3;
      for (let i = 0; i < len; i += 3) {
        const wave = Math.sin(t * (oc.jet > 0 ? 9 : 3.2) - i * 0.4 + k * 1.1) * (1.2 + i * 0.22);
        g.fillStyle = i < len * 0.6 ? '#e04c2c' : '#a62c1c';
        g.fillRect(Math.round(x + side * (0.55 + i * 0.08) + wave), y + 2 + i, i < 6 ? 2 : 1, 3);
      }
    }
    const bob = Math.round(Math.sin(t * 2.5) * 1.2);
    g.fillStyle = '#b4301e';
    g.fillRect(x - 4, y - 11 + bob, 8, 2); g.fillRect(x - 6, y - 9 + bob, 12, 7); g.fillRect(x - 5, y - 2 + bob, 10, 4);
    g.fillStyle = '#f25c34';
    g.fillRect(x - 3, y - 10 + bob, 6, 2); g.fillRect(x - 5, y - 8 + bob, 10, 6); g.fillRect(x - 4, y - 2 + bob, 8, 3);
    g.fillStyle = '#ff9856'; g.fillRect(x - 3, y - 9 + bob, 5, 3);
    g.fillStyle = '#ffd29e'; g.fillRect(x - 2, y - 9 + bob, 3, 2);
    g.fillStyle = '#fff29c'; g.fillRect(x - 4, y - 3 + bob, 3, 3); g.fillRect(x + 1, y - 3 + bob, 3, 3);
    g.fillStyle = '#121624'; g.fillRect(x - 3, y - 2 + bob, 2, 2); g.fillRect(x + 1, y - 2 + bob, 2, 2);
  }

  /* ---- deep pelagic silhouettes: Humpback Whale, Giant Manta Ray & Patrolling Reef Shark */
  function drawWhale(g, m, t) {
    // Coords below draw head on the LEFT (-dx) and tail on the RIGHT (+dx), so flip when moving RIGHT!
    const flip = m.vx > 0, x0 = Math.round(m.x), y0 = Math.round(m.y);
    const body = '#093452', belly = '#06243b', hi = '#1f6c90', ty = Math.round(Math.sin(t * 1.8) * 4.2);
    const put = (dx, dy, w, h, c) => { g.fillStyle = c; g.fillRect(flip ? x0 - dx - w : x0 + dx, y0 + dy, w, h); };
    put(-36, -4, 19, 9, body); put(-34, -5, 16, 2, hi);
    put(-17, -7, 25, 15, body); put(-17, -9, 22, 3, hi);
    put(-25, 3, 33, 5, belly);
    put(8, -4, 17, 9, body); put(10, -5, 12, 2, hi);
    put(3, -10, 5, 3, body); put(-13, 5, 10, 4, body); put(-7, 8, 12, 4, belly);
    put(24, -1 + (ty >> 1), 8, 5, body);
    put(31, -7 + ty, 5, 5, body); put(35, -10 + ty, 4, 4, hi);
    put(31, 2 + ty, 6, 5, belly); put(35, 6 + ty, 4, 3, belly);
  }

  function drawManta(g, m, t) {
    // Coords below draw head on the LEFT (-dx) and whip tail on the RIGHT (+dx), so flip when moving RIGHT!
    const flip = m.vx > 0, x0 = Math.round(m.x), y0 = Math.round(m.y);
    const body = '#0c4062', dark = '#072a44', hi = '#267da0', wy = Math.round(Math.sin(t * 2.2) * 5.8);
    const put = (dx, dy, w, h, c) => { g.fillStyle = c; g.fillRect(flip ? x0 - dx - w : x0 + dx, y0 + dy, w, h); };
    put(-18, -2, 5, 2, hi); put(-14, -4, 22, 8, body); put(-12, -5, 16, 2, hi); put(-10, 3, 16, 3, dark);
    put(-5, -9 + (wy >> 1), 12, 5, body); put(-1, -13 + wy, 8, 4, hi);
    put(-5, 4 - (wy >> 1), 11, 4, dark); put(-1, 7 - wy, 7, 3, dark);
    for (let i = 0; i < 18; i += 3) put(8 + i, Math.round(Math.sin(t * 3 - i * 0.3) * 1.8), 3, 1, i < 9 ? body : dark);
  }

  function drawShark(g, sh, t) {
    // Coords below draw snout on the LEFT (-dx) and tail on the RIGHT (+dx), so flip when moving RIGHT!
    const flip = sh.vx > 0, x0 = Math.round(sh.x), y0 = Math.round(sh.y), wag = Math.round(Math.sin(t * 5.2) * 2.5);
    const back = '#1a4f6e', mid = '#2e7294', belly = '#72b6c8', fin = '#113a54';
    const put = (dx, dy, w, h, c) => { g.fillStyle = c; g.fillRect(flip ? x0 - dx - w : x0 + dx, y0 + dy, w, h); };
    put(-20, -2, 8, 4, mid); put(-18, -3, 6, 1, back);
    put(-12, -4, 18, 8, mid); put(-11, -5, 16, 2, back); put(-13, 2, 17, 3, belly);
    put(-16, 0, 1, 1, '#081824'); put(-9, -1, 1, 3, fin); put(-7, -1, 1, 3, fin);
    put(-2, -10, 6, 5, back); put(0, -12, 4, 3, fin);
    put(-6, 4, 7, 3, fin); put(6, -2, 10, 5, mid);
    put(15, -1 + (wag >> 1), 5, 3, back);
    put(19, -7 + wag, 4, 7, back); put(21, -9 + wag, 3, 4, fin);
    put(19, 1 + wag, 4, 4, mid);
  }

  function drawDolphin(g, dl, t) {
    const flip = dl.vx < 0, x0 = Math.round(dl.x), y0 = Math.round(dl.y);
    const pitch = clamp(dl.vy / (Math.abs(dl.vx) + 0.5) * 0.45, -0.4, 0.4);
    const cP = Math.cos(pitch), sP = Math.sin(pitch), wag = Math.sin(t * 6.5) * 3.0;
    const put = (lx, ly, w, h, c) => {
      const rx = lx * cP - ly * sP, ry = lx * sP + ly * cP;
      g.fillStyle = c; g.fillRect(flip ? x0 - Math.round(rx) - w : x0 + Math.round(rx), y0 + Math.round(ry), w, h);
    };
    const top = '#3d7fa8', mid = '#64a8cc', belly = '#c4eef6', hi = '#9ae0f4';
    put(14, 0, 5, 2, mid); put(9, -3, 6, 5, mid); put(10, -4, 4, 2, hi); put(12, -1, 1, 1, '#091824');
    put(-6, -4, 16, 7, mid); put(-5, -5, 14, 2, top); put(-4, 2, 14, 2, belly);
    put(-2, -9, 5, 4, top); put(3, 3, 5, 3, top);
    put(-13, -2 + wag * 0.4, 8, 4, mid); put(-19, -4 + wag, 6, 3, top); put(-19, 0 + wag, 5, 3, top);
  }

  function drawTurtle(g, tu, t) {
    const flip = tu.vx < 0, x0 = Math.round(tu.x), y0 = Math.round(tu.y), stroke = Math.sin(t * 2.8 + tu.ph);
    const put = (dx, dy, w, h, c) => { g.fillStyle = c; g.fillRect(flip ? x0 - dx - w : x0 + dx, y0 + dy, w, h); };
    put(-12, 1 + Math.round(-stroke * 2), 6, 3, '#3c6648');
    put(-8, -5, 16, 3, '#a4c462'); put(-9, -2, 18, 5, '#588248'); put(-8, 3, 16, 2, '#d8c474');
    put(-6, -4, 4, 3, '#d4bc68'); put(0, -4, 4, 3, '#d4bc68');
    put(-7, -1, 4, 3, '#365836'); put(-1, -1, 4, 3, '#365836'); put(5, -1, 3, 3, '#365836');
    put(9, -3, 7, 5, '#82aa5c'); put(10, -4, 5, 1, '#b6d87e'); put(13, -1, 1, 1, '#091622');
    const fy = Math.round(stroke * 4.8);
    put(3, 1 + (fy >> 1), 6, 4, '#709854'); put(0, 4 + fy, 7, 3, '#a8cc74'); put(-3, 5 + fy, 4, 2, '#4a7244');
  }

  function drawJellyfish(g, jf, pal, t) {
    const x = Math.round(jf.x), y = Math.round(jf.y), pulse = Math.sin(t * jf.speed + jf.ph);
    const bw = Math.max(8, Math.round(jf.r * 2 - pulse * 2.0));
    const bh = Math.max(5, Math.round(jf.r * 1.15 + pulse * 1.3));
    const hw = bw >> 1;
    const c = jf.pink
      ? { glow: 'rgba(255,142,226,', rim: '#ffe4fa', body: '#e678d0', core: '#963896', tent: '#f8b2ee' }
      : { glow: 'rgba(84,248,255,', rim: '#e0ffff', body: '#4adce8', core: '#1b86a8', tent: '#94f8ff' };
    g.fillStyle = c.glow + (0.09 + pal.bioGlow * 0.14).toFixed(2) + ')';
    g.fillRect(x - hw - 2, y - bh, bw + 4, bh + 1);
    g.fillRect(x - hw, y - bh - 2, bw, 2);
    g.fillStyle = c.rim; g.fillRect(x - hw + 2, y - bh, bw - 4, 2);
    g.fillStyle = c.body; g.fillRect(x - hw, y - bh + 2, bw, bh - 3);
    g.fillStyle = c.rim; g.fillRect(x - hw + 1, y - bh + 2, Math.max(2, bw >> 2), 2);
    g.fillStyle = c.core; g.fillRect(x - hw, y - 1, bw, 1);
    const tents = 3;
    for (let k = 0; k < tents; k++) {
      const tx0 = x - hw + 2 + Math.round((k / (tents - 1)) * Math.max(1, bw - 4));
      const len = Math.round(jf.r * 2.8 + (k === 1 ? 5 : 1));
      for (let i = 0; i < len; i += 3) {
        const wave = Math.sin(t * 3.2 - i * 0.32 + jf.ph + k * 1.1) * (1.1 + i * 0.11);
        g.fillStyle = i < len * 0.6 ? c.tent : c.core;
        g.fillRect(Math.round(tx0 + wave), y + i, 1, 3);
      }
    }
  }

  function drawFish(g, f, t) {
    const flip = f.vx < 0, x = Math.round(f.x), y = Math.round(f.y), wag = Math.sin(t * 11 + f.ph) > 0 ? 1 : 0;
    const put = (dx, dy, w, h, c) => { g.fillStyle = c; g.fillRect(flip ? x - dx - w : x + dx, y + dy, w, h); };
    if (f.kind === 'teal') {
      put(-6, -2 + wag, 2, 5, '#ff8828'); put(-7, -3 + wag, 1, 7, '#ffc854');
      put(-4, -3, 8, 7, '#28bec6'); put(-3, -4, 6, 2, '#82f4ee');
      put(-1, -5, 5, 1, '#ffa03a'); put(0, 0, 3, 2, '#ff8828');
      put(4, -2, 3, 5, '#5ce6e0'); put(5, -1, 1, 1, '#081622');
    } else if (f.kind === 'crimson') {
      put(-5, -1 + wag, 2, 3, '#a81e46'); put(-3, -2, 7, 5, '#de325c');
      put(-1, -2, 1, 5, '#ffe0ee'); put(2, -2, 1, 5, '#ffe0ee');
      put(4, -1, 2, 3, '#ff82a8'); put(4, -1, 1, 1, '#0b1420');
    } else if (f.kind === 'clown') {
      put(-4, -1 + wag, 2, 3, '#ff6a18'); put(-2, -2, 6, 4, '#ff7e22');
      put(0, -2, 1, 4, '#ffffff'); put(3, -1, 1, 2, '#ffffff'); put(4, -1, 1, 1, '#0a121c');
    } else {
      put(-3, -1 + wag, 1, 2, '#e4801a'); put(-2, -1, 5, 2, '#ffc03e'); put(3, -1, 1, 1, '#102030');
    }
  }

  function drawSardine(g, s, t) {
    const x = Math.round(s.x), y = Math.round(s.y), dir = s.vx >= 0 ? 1 : -1;
    const flash = Math.sin(t * 7 + s.ph) > 0.62;
    g.fillStyle = flash ? '#ffffff' : '#b2f4fc';
    g.fillRect(x - 1, y, 4, 1);
    g.fillStyle = flash ? '#d8ffff' : '#4aa8c4';
    g.fillRect(x - (dir > 0 ? 2 : -1), y + 1, 3, 1);
    g.fillRect(x - dir * 3, y, 1, 1);
  }

  /* ---- HERO ARTICULATED SCUBA DIVER */
  function drawDiver(g, d, pal, t) {
    const flip = d.face < 0, x0 = Math.round(d.x), y0 = Math.round(d.y);
    const pitch = clamp(d.pitch, -0.38, 0.38), cP = Math.cos(pitch), sP = Math.sin(pitch);
    const kick = t * (3.8 + d.effort * 2.4);
    const put = (lx, ly, w, h, c) => {
      const rx = lx * cP - ly * sP, ry = lx * sP + ly * cP;
      g.fillStyle = c; g.fillRect(flip ? x0 - Math.round(rx) - w : x0 + Math.round(rx), y0 + Math.round(ry), w, h);
    };

    // Dive-torch beam (1 single translucent quad instead of 28 fillRects!)
    const torchAlpha = pal.torchGain * (0.8 + 0.2 * Math.sin(t * 2.4));
    if (torchAlpha > 0.14) {
      const dir = flip ? -1 : 1, hx = x0 + dir * 18, hy = y0 + 2 + Math.round(pitch * 15);
      if (typeof g.beginPath === 'function' && typeof g.fill === 'function') {
        g.fillStyle = 'rgba(196, 255, 248, ' + (torchAlpha * 0.16).toFixed(3) + ')';
        g.beginPath();
        g.moveTo(hx, hy - 2); g.lineTo(hx + dir * 52, hy - 10 + Math.round(pitch * 52));
        g.lineTo(hx + dir * 52, hy + 10 + Math.round(pitch * 52)); g.lineTo(hx, hy + 2);
        g.closePath(); g.fill();
      } else {
        g.fillStyle = 'rgba(196, 255, 248, ' + (torchAlpha * 0.14).toFixed(3) + ')';
        g.fillRect(dir > 0 ? hx : hx - 44, hy - 5, 44, 10);
      }
    }

    for (let leg = 0; leg < 2; leg++) {
      const ph = kick + leg * Math.PI, hipY = leg === 0 ? -1 : 1;
      const k1 = Math.sin(ph) * 3.0, k2 = Math.sin(ph - 0.65) * 4.8, k3 = Math.sin(ph - 1.25) * 6.5;
      const suit = leg === 0 ? '#101d2c' : '#1e344a', fin = leg === 0 ? '#142438' : '#28445e', tip = leg === 0 ? '#c89820' : '#ffda4c';
      put(-11, hipY + k1 * 0.4, 6, 3, suit);
      put(-16, hipY + k1 * 0.85, 6, 3, suit);
      put(-21, hipY + k2 * 0.9, 6, 3, fin);
      put(-26, hipY + k3 * 0.95, 6, 3, fin);
      put(-28, hipY + k3 * 0.95, 4, 3, tip);
    }
    const armBob = Math.sin(t * 2.1) * 1.2;
    put(-2, 3 + armBob * 0.4, 6, 2, '#132132');
    put(-6, -3, 15, 6, '#1a2e44'); put(-5, -2, 13, 3, '#2d4f6a'); put(-3, -1, 8, 1, '#38e6e0');
    put(-6, -7, 12, 4, '#ecb828'); put(-5, -7, 10, 1, '#fff08c'); put(-6, -4, 12, 1, '#9a6a10');
    put(-3, -7, 2, 4, '#142232'); put(2, -7, 2, 4, '#142232'); put(6, -7, 2, 3, '#dceef6'); put(7, -6, 4, 1, '#101c28');
    put(9, -4, 7, 6, '#182a3e'); put(13, -3, 4, 3, '#98fff8'); put(14, -3, 2, 1, '#ffffff');
    put(13, 0, 3, 2, '#e6aa7e'); put(14, 1, 3, 2, '#243a4c');
    put(5, 1 + armBob * 0.5, 8, 3, '#243e56'); put(11, 1 + armBob * 0.5, 2, 2, '#3ef0ea');
    put(13, 1 + armBob * 0.5, 4, 3, '#3c4e5e'); put(16, 1 + armBob * 0.5, 2, 2, '#eafffc');

    if (d.flash > 0) {
      const fx = x0 + (flip ? -19 : 19), fy = y0 + 1, r = Math.round(6 + (1 - d.flash) * 14);
      g.fillStyle = 'rgba(255, 255, 238, ' + (d.flash * 0.85).toFixed(2) + ')';
      g.fillRect(fx - r, fy, r * 2, 1); g.fillRect(fx, fy - r, 1, r * 2);
      g.fillStyle = 'rgba(200, 255, 252, ' + (d.flash * 0.40).toFixed(2) + ')';
      g.fillRect(fx - (r >> 1), fy - (r >> 1), r, r);
    }
  }

  function drawBubble(g, b) {
    const x = Math.round(b.x), y = Math.round(b.y), r = b.r;
    if (r <= 1) {
      g.fillStyle = 'rgba(206, 255, 254, 0.78)'; g.fillRect(x, y, 2, 2);
      g.fillStyle = '#ffffff'; g.fillRect(x, y, 1, 1);
      return;
    }
    // Rounded translucent pixel-art bubble (NO blocky squares!)
    g.fillStyle = 'rgba(148, 242, 248, 0.58)';
    g.fillRect(x - 1, y - 2, 3, 1); g.fillRect(x - 1, y + 2, 3, 1);
    g.fillRect(x - 2, y - 1, 1, 3); g.fillRect(x + 2, y - 1, 1, 3);
    g.fillStyle = '#ffffff'; g.fillRect(x - 1, y - 1, 1, 1);
  }

  function drawBubbleRing(g, br) {
    const x = Math.round(br.x), y = Math.round(br.y), rx = Math.round(br.rx), ry = Math.max(2, Math.round(br.rx * 0.34));
    const a = clamp(1 - br.age / 6.5, 0.15, 0.9).toFixed(2);
    g.fillStyle = 'rgba(196, 255, 252, ' + a + ')';
    for (let i = 0; i < 10; i++) {
      const th = (i / 10) * Math.PI * 2;
      g.fillRect(Math.round(x + Math.cos(th) * rx), Math.round(y + Math.sin(th) * ry), 2, 1);
    }
  }

  function drawCoin(g, c, t) {
    const a = clamp(1 - (c.fade || 0), 0, 1);
    if (a <= 0.01) return;
    const x = Math.round(c.x), y = Math.round(c.y), spin = Math.abs(Math.cos(t * 10 + c.ph));
    const w = spin > 0.55 ? 3 : spin > 0.25 ? 2 : 1;
    const aStr = a.toFixed(3);
    if (a > 0.35 && spin > 0.72) {
      g.fillStyle = (c.gem ? 'rgba(130,255,224,' : 'rgba(255,232,126,') + (a * 0.28).toFixed(3) + ')';
      g.fillRect(x - 2, y - 2, 5, 5);
    }
    g.fillStyle = (c.gem ? 'rgba(62,248,180,' : 'rgba(244,192,46,') + aStr + ')';
    g.fillRect(x - (w >> 1), y - 1, w, 3);
    g.fillStyle = (c.gem ? 'rgba(200,255,234,' : 'rgba(255,248,176,') + aStr + ')';
    g.fillRect(x - (w >> 1), y - 1, 1, 1);
  }

  /* ---- swaying foreground kelp (drawn in 6px steps -> 6x faster than 1px, same lush curved silhouette!) */
  const KELP = [
    { x: 14, base: 427, h: 96,  w: 4, ph: 0.2, dark: '#081822', mid: '#1f4d3b', lit: '#4e8c52' },
    { x: 30, base: 427, h: 120, w: 5, ph: 1.4, dark: '#091b24', mid: '#2b6044', lit: '#6aa85a' },
    { x: 48, base: 425, h: 78,  w: 4, ph: 2.7, dark: '#081822', mid: '#22523d', lit: '#549254' },
    { x: 124, base: 350, h: 48, w: 3, ph: 0.9, dark: '#0f343c', mid: '#26604e', lit: '#58985e' },
    { x: 238, base: 427, h: 84, w: 4, ph: 1.9, dark: '#081822', mid: '#1e4a38', lit: '#48824c' },
    { x: 254, base: 427, h: 114, w: 5, ph: 3.1, dark: '#07141e', mid: '#265640', lit: '#5e9c54' },
  ];

  function drawKelp(g, t) {
    for (const k of KELP) {
      for (let i = 0; i < k.h; i += 6) {
        const frac = i / k.h, sway = Math.sin(t * 1.15 - frac * 3.1 + k.ph) * (3 + frac * 9.5);
        const x = Math.round(k.x + sway), y = k.base - i - 6;
        const w = Math.max(1, Math.round(k.w * (1 - frac * 0.65)));
        g.fillStyle = k.dark; g.fillRect(x, y, w + 1, 6);
        g.fillStyle = frac > 0.45 ? k.lit : k.mid; g.fillRect(x, y, w, 6);
      }
    }
  }

  /* ---- world state & deterministic 30 Hz simulation */
  const DIVER_WAYPOINTS = [
    [144, 152], [198, 134], [202, 206], [146, 224], [116, 178], [176, 166], [194, 232], [126, 136],
  ];

  function createWorld(seed) {
    const rnd = seeded(seed || 4242);
    // Streamlined cast of the most iconic, readable creatures (clean composition + super fast on tablet!)
    const jellies = [
      { x: 142, y: 118, r: 6, pink: true,  ph: 0.4, animPh: 0.4, speed: 2.2, vx:  0.10, homeY: 120 },
      { x: 86,  y: 168, r: 7, pink: false, ph: 1.9, animPh: 1.9, speed: 1.9, vx: -0.06, homeY: 170 },
      { x: 148, y: 254, r: 6, pink: true,  ph: 4.5, animPh: 4.5, speed: 2.0, vx: -0.08, homeY: 256 },
    ];
    const fish = [];
    for (let i = 0; i < 4; i++) fish.push({ kind: 'teal', x: 52 + rnd() * 170, y: 125 + rnd() * 120, vx: (rnd() < 0.5 ? -1 : 1) * (0.38 + rnd() * 0.2), vy: 0, ph: rnd() * 6.28, animPh: rnd() * 6.28, homeY: 138 + rnd() * 105 });
    for (let i = 0; i < 4; i++) fish.push({ kind: 'crimson', x: 78 + rnd() * 64, y: 92 + rnd() * 48, vx: 0.30 + rnd() * 0.16, vy: 0, ph: rnd() * 6.28, animPh: rnd() * 6.28, homeY: 100 + rnd() * 40 });
    for (let i = 0; i < 2; i++) fish.push({ kind: 'clown', x: ANEMONE.x + (i ? 6 : -6), y: ANEMONE.y - 12 - i * 5, vx: i ? 0.22 : -0.22, vy: 0, ph: i * 3.1, animPh: i * 3.1, homeY: ANEMONE.y - 14 });
    // 20 shimmering silver sardines forming a clean, crisp reactive bait-ball!
    const sardines = [];
    for (let i = 0; i < 20; i++) {
      const ang = (i / 20) * Math.PI * 2, rad = 8 + rnd() * 16;
      sardines.push({ x: 168 + Math.cos(ang) * rad, y: 178 + Math.sin(ang) * rad * 0.65, vx: -0.55, vy: 0, ph: rnd() * 6.28 });
    }
    const bubbles = [];
    const vents = [{ x: 112, y: 214, rate: 0.05 }, { x: 244, y: 256, rate: 0.035 }];
    for (let i = 0; i < 10; i++) {
      const v = vents[i % vents.length];
      bubbles.push({ x: v.x + (rnd() - 0.5) * 8, y: 26 + rnd() * (v.y - 26), r: rnd() < 0.65 ? 1 : 2, vy: -0.48 - rnd() * 0.38, ph: rnd() * 6.28 });
    }
    const motes = [];
    for (let i = 0; i < 14; i++) motes.push({ x: rnd() * W, y: 52 + rnd() * 290, vx: 0.07 + rnd() * 0.08, vy: -0.02 + rnd() * 0.05, ph: rnd() * 6.28 });

    return {
      rnd, t: 0, steps: 0,
      diver: {
        x: 148, y: 172, vx: 0.46, vy: 0, face: 1, pitch: 0, effort: 0.25, kickPh: 0, wp: 1,
        breathTimer: 1.0, breathBurst: 0, ringTimer: 4.5, flash: 0, flashCooldown: 2.0,
        target: null, targetTimer: 0,
        inRoom: null, visit: null, visitCooldown: 9.5, nextRoom: 'left',
      },
      rooms: {
        left:  { id: 'left',  light: 0, hold: 0, magic: 0, pulse: 0, sparkles: [] },
        right: { id: 'right', light: 0, hold: 0, magic: 0, pulse: 0, sparkles: [], eel: 0 },
      },
      megafauna: { kind: 'whale', x: 186, y: 152, vx: -0.18, animPh: 0, cooldown: 0 },
      shark: { x: -45, y: 188, vx: 0.46, animPh: 0, cooldown: 4.0 },
      dolphin: { x: 295, y: 110, vx: -0.88, vy: 0, animPh: 0, cooldown: 2.5 },
      turtle: { x: 214, y: 116, vx: -0.28, vy: 0, ph: 0.5, animPh: 0.5 },
      chest: { open: 0.25, timer: 4.0, burst: 0 },
      clam: { open: 0.8, timer: 0 },
      octopus: { x: 230, y: 231, homeX: 230, homeY: 231, vx: 0, vy: 0, jet: 0, animPh: 0, inks: [] },
      jellies, fish, sardines, bubbles, bubbleRings: [], coins: [], vents, motes,
      ripples: [],
      stats: { pokes: 0, breaths: 0, rings: 0, flashes: 0, chestOpens: 0, inks: 0, roomVisits: 0, roomInteractions: 0 },
    };
  }

  function triggerChest(w) {
    w.chest.burst = 3.6; w.chest.timer = 11 + w.rnd() * 6; w.stats.chestOpens++;
    for (let i = 0; i < 12 && w.coins.length < 28; i++) {
      w.coins.push({
        x: CHEST.x + (w.rnd() - 0.5) * 14, y: CHEST.y - 6,
        vx: (w.rnd() - 0.5) * 1.1, vy: -1.1 - w.rnd() * 1.0,
        age: 0, ph: w.rnd() * 6.28, gem: i % 4 === 0,
        landed: false, fade: 0, floorY: CHEST.y + 6 + w.rnd() * 4.5,
      });
    }
    for (let i = 0; i < 6 && w.bubbles.length < 28; i++) {
      w.bubbles.push({ x: CHEST.x + (w.rnd() - 0.5) * 16, y: CHEST.y - 4, r: i % 2 ? 2 : 1, vy: -0.6 - w.rnd() * 0.45, ph: w.rnd() * 6.28 });
    }
  }

  function triggerRoomInteraction(w, id) {
    const rm = w.rooms && w.rooms[id];
    const spec = ROOMS[id];
    if (!rm || !spec) return;
    rm.magic = 1.0;
    rm.hold = Math.max(rm.hold, 1.4);
    w.diver.flash = 1.0;
    w.stats.roomInteractions++;
    const [rx, ry] = spec.relic;
    for (let i = 0; i < 10 && rm.sparkles.length < 20; i++) {
      const ang = (i / 10) * Math.PI * 2 + (w.rnd() - 0.5) * 0.4;
      rm.sparkles.push({
        x: rx + (w.rnd() - 0.5) * 10,
        y: ry + (w.rnd() - 0.5) * 10,
        vx: Math.cos(ang) * (0.18 + w.rnd() * 0.34),
        vy: -0.18 - w.rnd() * 0.36,
        age: 0,
        life: 1.6 + w.rnd() * 1.1,
        gold: i % 2 === 0,
      });
    }
    for (let i = 0; i < 5 && w.bubbles.length < 32; i++) {
      w.bubbles.push({ x: rx + (w.rnd() - 0.5) * 12, y: ry - 2, r: i % 2 ? 2 : 1, vy: -0.58 - w.rnd() * 0.36, ph: w.rnd() * 6.28 });
    }
  }

  function sendDiverToRoom(w, id) {
    const spec = ROOMS[id];
    const rm = w.rooms && w.rooms[id];
    if (!spec || !rm) return false;
    const d = w.diver;
    rm.pulse = 1.0;
    d.target = null;
    if (d.visit && d.visit.id === id) {
      if (d.visit.stage === 'inspect') {
        triggerRoomInteraction(w, id);
        d.visit.timer = Math.max(d.visit.timer, 3.0);
      } else if (d.visit.stage === 'exit') {
        d.visit.stage = 'enter';
        d.visit.interacted = false;
      }
      return true;
    }
    if (d.visit && d.inRoom && d.inRoom !== id) {
      // Respect 3D walls: exit current chamber cleanly through its entrance before heading to the new one!
      d.visit.stage = 'exit';
      d.visit.queued = id;
      return true;
    }
    d.visit = { id, stage: 'approach', timer: 0, interacted: false, queued: null };
    return true;
  }

  function drawInkBlob(g, cx, cy, rx, ry) {
    // Organic stepped 16-bit pixel-art rounded ellipse (ZERO square corners!)
    const x = Math.round(cx), y = Math.round(cy);
    const w = Math.max(2, Math.round(rx)), h = Math.max(2, Math.round(ry));
    if (w <= 2 && h <= 2) { g.fillRect(x - 1, y - 1, 2, 2); return; }
    const w1 = Math.max(2, Math.round(w * 0.56)), w2 = Math.max(2, Math.round(w * 0.86));
    const h1 = Math.max(1, Math.round(h * 0.28)), h2 = Math.max(1, Math.round(h * 0.62));
    g.fillRect(x - w1, y - h, w1 * 2, h * 2);
    g.fillRect(x - w2, y - h2, w2 * 2, h2 * 2);
    g.fillRect(x - w, y - h1, w * 2, h1 * 2);
  }

  function drawOctopusInks(g, inks, t) {
    for (let i = 0; i < inks.length; i++) {
      const ic = inks[i];
      if (ic.age < 0) continue;
      const frac = ic.age / ic.life;
      if (frac >= 1) continue;
      // Smooth bloom-in (0..0.12) then silky underwater dispersal fade!
      const env = (frac < 0.10 ? frac / 0.10 : 1.0) * (1.0 - frac) * (1.0 - frac * 0.45);
      const rad = ic.r0 + Math.sqrt(frac) * ic.grow;
      const swirl = Math.sin(t * 2.1 + ic.ph) * (1.2 + frac * 3.0);
      const lift = Math.cos(t * 1.6 + ic.ph * 1.3) * (0.8 + frac * 1.8);
      // 1. Soft smoky violet-indigo diffusion halo (widest outer veil)
      g.fillStyle = 'rgba(38, 18, 76, ' + (env * 0.34).toFixed(3) + ')';
      drawInkBlob(g, ic.x + swirl * 0.65, ic.y + lift * 0.5, rad * 1.28, rad * 0.96);
      // 2. Asymmetric billowing midnight-indigo ink cloud (two curling overlapping rounded lobes!)
      g.fillStyle = 'rgba(14, 10, 38, ' + (env * 0.66).toFixed(3) + ')';
      drawInkBlob(g, ic.x - swirl * 0.35, ic.y - lift * 0.25, rad * 0.96, rad * 0.78);
      drawInkBlob(g, ic.x + swirl * 0.55 + ic.lx * rad * 0.48, ic.y + ic.ly * rad * 0.38, rad * 0.74, rad * 0.62);
      // 3. Dense jet-black siphon core (strong when freshly ejected, breaks up organically as it disperses!)
      if (frac < 0.58) {
        const coreA = (1.0 - frac / 0.58) * env * 0.78;
        g.fillStyle = 'rgba(6, 5, 18, ' + coreA.toFixed(3) + ')';
        drawInkBlob(g, ic.x - swirl * 0.18, ic.y, rad * 0.52, rad * 0.42);
      }
      // 4. Delicate curling wispy ink droplets trailing off the expanding edges
      g.fillStyle = 'rgba(24, 14, 54, ' + (env * 0.52).toFixed(3) + ')';
      const dx1 = Math.round(ic.x + Math.cos(ic.ph + t * 1.1) * (rad * 1.22));
      const dy1 = Math.round(ic.y + Math.sin(ic.ph + t * 0.9) * (rad * 0.88));
      g.fillRect(dx1, dy1, 2, 1);
      if (frac > 0.22) {
        const dx2 = Math.round(ic.x - Math.sin(ic.ph * 1.7 + t * 0.8) * (rad * 1.35));
        const dy2 = Math.round(ic.y + Math.cos(ic.ph * 1.4 - t * 0.7) * (rad * 0.95));
        g.fillRect(dx2, dy2, 2, 2);
      }
    }
  }

  function startleOctopus(w) {
    const oc = w.octopus;
    oc.jet = 2.6; oc.vx = -0.95; oc.vy = -0.55; w.stats.inks++;
    // Eject an organic, swirling 10-puff billowing underwater ink cloud + trailing jet plume!
    for (let i = 0; i < 10 && oc.inks.length < 18; i++) {
      const ang = (i / 10) * Math.PI * 2 + (w.rnd() - 0.5) * 0.45;
      const spd = 0.25 + w.rnd() * 0.55;
      oc.inks.push({
        x: oc.x + 2 + (w.rnd() - 0.5) * 6,
        y: oc.y + 5 + (w.rnd() - 0.5) * 4,
        vx: 0.35 + Math.cos(ang) * spd,
        vy: 0.12 + Math.sin(ang) * spd * 0.72,
        r0: 2.2 + w.rnd() * 2.2,
        grow: 6.5 + w.rnd() * 6.5,
        lx: Math.cos(ang),
        ly: Math.sin(ang),
        ph: w.rnd() * 6.28,
        age: i < 5 ? 0 : -(i - 4) * 0.09,
        life: 2.9 + w.rnd() * 1.2,
      });
    }
  }

  function stepWorld(w, dt, viewBottom) {
    const rnd = w.rnd;
    w.t += dt; w.steps++;
    const safeBottom = clamp(finite(viewBottom) ? viewBottom - 28 : 280, 165, 312);
    const maxRoomY = clamp(finite(viewBottom) ? viewBottom - 4 : 286, 165, 306);

    const d = w.diver;
    // Autonomous periodic sanctuary exploration (alternating left Atlantis sanctuary & right Poseidon vault!)
    if (!d.visit && !d.target) {
      d.visitCooldown -= dt;
      if (d.visitCooldown <= 0 && maxRoomY >= 248) {
        const pick = d.nextRoom || 'left';
        d.nextRoom = pick === 'left' ? 'right' : 'left';
        d.visitCooldown = 18 + rnd() * 8;
        sendDiverToRoom(w, pick);
      }
    }

    let tx, ty, speed = 0.48, xMin = 62, xMax = 220, yMax = safeBottom;
    if (d.visit) {
      const v = d.visit;
      const spec = ROOMS[v.id];
      xMin = 48; xMax = 248; yMax = maxRoomY;
      const clampPt = (pt) => [pt[0], clamp(pt[1], 88, maxRoomY)];
      if (v.stage === 'approach') {
        [tx, ty] = clampPt(spec.approach);
        speed = 0.84;
        if (Math.hypot(tx - d.x, ty - d.y) < 10) v.stage = 'enter';
      } else if (v.stage === 'enter') {
        const [dxDoor, dyDoor] = clampPt(spec.door);
        const [sx, sy] = clampPt(spec.spot);
        const passedDoor = spec.id === 'left' ? d.x <= dxDoor + 4 : d.x >= dxDoor - 4;
        [tx, ty] = passedDoor ? [sx, sy] : [dxDoor, dyDoor];
        speed = 0.66;
        if (Math.hypot(sx - d.x, sy - d.y) < 7) {
          v.stage = 'inspect';
          v.timer = 4.2;
          v.interacted = false;
          w.stats.roomVisits++;
        }
      } else if (v.stage === 'inspect') {
        [tx, ty] = clampPt(spec.spot);
        speed = 0.24;
        v.timer -= dt;
        if (!v.interacted && v.timer <= 3.35) {
          v.interacted = true;
          triggerRoomInteraction(w, v.id);
        }
        if (v.timer <= 0) v.stage = 'exit';
      } else {
        const [dxDoor, dyDoor] = clampPt(spec.door);
        const [ax, ay] = clampPt(spec.approach);
        const clearedDoor = spec.id === 'left' ? d.x >= dxDoor - 6 : d.x <= dxDoor + 6;
        [tx, ty] = clearedDoor ? [ax, ay] : [dxDoor, dyDoor];
        speed = 0.68;
        if (Math.hypot(ax - d.x, ay - d.y) < 10) {
          const queued = v.queued;
          d.visit = null;
          d.inRoom = null;
          if (queued) sendDiverToRoom(w, queued);
        }
      }
      // Pixel-exact 3D depth transition right at the outer edge of the front fluted column (zero Z-popping!)
      if (d.visit) {
        const inside = spec.id === 'left' ? d.x < spec.depthX : d.x > spec.depthX;
        d.inRoom = (v.stage !== 'approach' && inside) ? spec.id : null;
      }
    } else if (d.target && d.targetTimer > 0) {
      tx = d.target[0]; ty = clamp(d.target[1], 88, safeBottom);
      speed = 0.82;
      d.targetTimer -= dt;
      if (Math.hypot(tx - d.x, ty - d.y) < 12 || d.targetTimer <= 0) d.target = null;
    } else {
      const wp = DIVER_WAYPOINTS[d.wp];
      tx = wp[0]; ty = clamp(wp[1], 88, safeBottom);
      if (Math.hypot(tx - d.x, ty - d.y) < 14) d.wp = (d.wp + 1) % DIVER_WAYPOINTS.length;
    }

    const dx = tx - d.x, dy = ty - d.y, dist = Math.hypot(dx, dy) || 1;
    d.vx = lerp(d.vx, (dx / dist) * speed, d.visit ? 0.075 : 0.036);
    d.vy = lerp(d.vy, (dy / dist) * speed * 0.78, d.visit ? 0.08 : 0.04);
    d.x = clamp(d.x + d.vx, xMin, xMax);
    d.y = clamp(d.y + d.vy + Math.sin(w.t * 1.4) * 0.08, 88, yMax);
    if (d.visit && d.visit.stage === 'inspect') d.face = ROOMS[d.visit.id].face;
    else if (Math.abs(d.vx) > 0.08) d.face = d.vx > 0 ? 1 : -1;
    d.pitch = lerp(d.pitch, clamp((d.vy / (Math.abs(d.vx) + 0.45)) * 0.45 * d.face, -0.35, 0.35), 0.08);
    const activeEffort = d.visit ? (d.visit.stage === 'inspect' ? 0.28 : 0.72) : (d.target ? 0.95 : 0.25);
    d.effort = lerp(d.effort, activeEffort, 0.06);
    // Continuous 12-frame flexing-fin flutter kick cadence coupled smoothly to actual swim speed & effort!
    d.kickPh += dt * (4.0 + d.effort * 3.8 + Math.hypot(d.vx, d.vy) * 1.8);

    // Update ancient chamber whole-room lighting, magic pulses, sparkles & cave creature!
    for (const id of ['left', 'right']) {
      const rm = w.rooms[id];
      const occupied = d.inRoom === id;
      if (occupied) {
        rm.light = lerp(rm.light, 1.0, 0.072);
        rm.hold = 0.75;
      } else if (rm.hold > 0) {
        rm.hold -= dt;
      } else {
        rm.light = lerp(rm.light, 0.0, 0.034);
        if (rm.light < 0.006) rm.light = 0;
      }
      if (rm.magic > 0) rm.magic = Math.max(0, rm.magic - dt * 0.32);
      if (rm.pulse > 0) rm.pulse = Math.max(0, rm.pulse - dt * 1.2);
      if (id === 'right') {
        const eelTarget = rm.light > 0.25 ? clamp((rm.light - 0.2) * 1.15 + rm.magic * 0.45, 0, 1.25) : 0;
        rm.eel = lerp(rm.eel, eelTarget, 0.07);
      }
      for (let i = rm.sparkles.length - 1; i >= 0; i--) {
        const sp = rm.sparkles[i];
        sp.age += dt;
        sp.x += sp.vx + Math.sin(w.t * 4.5 + i) * 0.10;
        sp.y += sp.vy;
        sp.vx *= 0.97;
        if (sp.age >= sp.life) rm.sparkles.splice(i, 1);
      }
    }

    d.breathTimer -= dt;
    if (d.breathTimer <= 0) { d.breathTimer = 2.8 + rnd() * 1.2; d.breathBurst = 4 + Math.floor(rnd() * 3); w.stats.breaths++; }
    if (d.breathBurst > 0 && w.steps % 3 === 0) {
      d.breathBurst--;
      if (w.bubbles.length < 28) w.bubbles.push({ x: d.x + d.face * 14 + (rnd() - 0.5) * 3, y: d.y - 2, r: rnd() < 0.45 ? 2 : 1, vy: -0.65 - rnd() * 0.4, ph: rnd() * 6.28 });
    }
    d.ringTimer -= dt;
    if (d.ringTimer <= 0 && w.bubbleRings.length < 3) {
      d.ringTimer = 6.5 + rnd() * 4.0;
      w.bubbleRings.push({ x: d.x + d.face * 15, y: d.y - 4, rx: 3.5, vy: -0.52, age: 0, ph: rnd() * 6.28 });
      w.stats.rings++;
    }
    if (d.flash > 0) d.flash = Math.max(0, d.flash - dt * 2.8);
    if (d.flashCooldown > 0) d.flashCooldown -= dt;
    if (d.flashCooldown <= 0 && !d.inRoom && (Math.hypot(w.turtle.x - d.x, w.turtle.y - d.y) < 42 || (w.dolphin.cooldown <= 0 && Math.hypot(w.dolphin.x - d.x, w.dolphin.y - d.y) < 50))) {
      d.flash = 1.0; d.flashCooldown = 5.5; w.stats.flashes++;
    }

    w.chest.timer -= dt;
    if (w.chest.timer <= 0) triggerChest(w);
    if (w.chest.burst > 0) { w.chest.burst -= dt; w.chest.open = lerp(w.chest.open, 1.0, 0.14); }
    else w.chest.open = lerp(w.chest.open, 0.18 + 0.08 * Math.sin(w.t * 1.1), 0.04);
    for (let i = w.coins.length - 1; i >= 0; i--) {
      const c = w.coins[i];
      c.age += dt;
      if (!c.landed) {
        c.x += c.vx + Math.sin(w.t * 5 + c.ph) * 0.16;
        c.vx *= 0.99;
        c.y += c.vy;
        c.vy += 0.020;
        const floorY = c.floorY || (CHEST.y + 8);
        if (c.y >= floorY || c.age >= 2.5) {
          c.y = Math.min(c.y, floorY);
          c.landed = true;
          c.vx *= 0.18;
          c.vy = 0;
        }
      } else {
        c.x += c.vx;
        c.vx *= 0.85;
        c.fade = (c.fade || 0) + dt / COIN_FADE;
        if (c.fade >= 1) w.coins.splice(i, 1);
      }
    }

    if (w.clam.timer > 0) { w.clam.timer -= dt; w.clam.open = lerp(w.clam.open, 0.0, 0.25); }
    else w.clam.open = lerp(w.clam.open, 0.55 + 0.45 * Math.sin(w.t * 0.55), 0.06);

    const oc = w.octopus;
    oc.animPh += dt * (oc.jet > 0 ? 11.5 : 3.2);
    if (oc.jet > 0) { oc.jet -= dt; oc.x = clamp(oc.x + oc.vx, 128, 245); oc.y = clamp(oc.y + oc.vy, 130, 250); oc.vx *= 0.96; oc.vy *= 0.96; }
    else { oc.x = lerp(oc.x, oc.homeX + Math.sin(w.t * 0.9) * 3, 0.02); oc.y = lerp(oc.y, oc.homeY + Math.cos(w.t * 1.1) * 2, 0.02); }
    for (let i = oc.inks.length - 1; i >= 0; i--) {
      const ic = oc.inks[i];
      ic.age += dt;
      if (ic.age >= 0) {
        ic.x += ic.vx + Math.sin(w.t * 1.8 + ic.ph) * 0.14;
        ic.y += ic.vy - 0.06;
        ic.vx *= 0.94;
        ic.vy *= 0.94;
      }
      if (ic.age > ic.life) oc.inks.splice(i, 1);
    }

    const m = w.megafauna;
    if (m.cooldown > 0) {
      m.cooldown -= dt;
      if (m.cooldown <= 0) {
        m.kind = m.kind === 'whale' ? 'manta' : 'whale';
        const fromRight = rnd() < 0.55;
        m.x = fromRight ? W + 48 : -48; m.y = 112 + rnd() * 88;
        m.vx = (fromRight ? -1 : 1) * (m.kind === 'whale' ? 0.18 : 0.28);
      }
    } else {
      m.animPh += dt * (m.kind === 'whale' ? 2.1 : 3.0);
      m.x += m.vx; m.y += Math.sin(m.animPh * 0.5) * 0.08;
      if (m.x < -64 || m.x > W + 64) m.cooldown = 5 + rnd() * 6;
    }

    const sh = w.shark;
    if (sh.cooldown > 0) {
      sh.cooldown -= dt;
      if (sh.cooldown <= 0) {
        const fromLeft = rnd() < 0.5;
        sh.x = fromLeft ? -44 : W + 44; sh.y = 148 + rnd() * 78;
        sh.vx = (fromLeft ? 1 : -1) * (0.48 + rnd() * 0.18);
      }
    } else {
      sh.animPh += dt * 5.8;
      sh.x += sh.vx; sh.y += Math.sin(sh.animPh * 0.35) * 0.08;
      if (oc.jet <= 0 && Math.hypot(sh.x - oc.x, sh.y - oc.y) < 38) startleOctopus(w);
      if (sh.x < -56 || sh.x > W + 56) sh.cooldown = 7 + rnd() * 7;
    }

    const dl = w.dolphin;
    if (dl.cooldown > 0) {
      dl.cooldown -= dt;
      if (dl.cooldown <= 0) {
        const fromRight = rnd() < 0.5;
        dl.x = fromRight ? W + 32 : -32; dl.y = 92 + rnd() * 34;
        dl.vx = (fromRight ? -1 : 1) * (0.88 + rnd() * 0.25); dl.vy = 0;
      }
    } else {
      dl.animPh += dt * 7.6;
      dl.x += dl.vx; dl.vy = Math.cos(dl.animPh * 0.5) * 0.48; dl.y = clamp(dl.y + dl.vy, 72, 152);
      if (w.steps % 6 === 0 && w.bubbles.length < 28) w.bubbles.push({ x: dl.x - Math.sign(dl.vx) * 14, y: dl.y, r: 1, vy: -0.45, ph: rnd() * 6.28 });
      if (dl.x < -42 || dl.x > W + 42) dl.cooldown = 8 + rnd() * 7;
    }

    const tu = w.turtle;
    tu.animPh += dt * 2.9;
    // Real sea-turtle underwater flight propulsion: glides faster during power downstroke & coasts on recovery!
    const turtleSurge = 0.72 + Math.max(0, Math.sin(tu.animPh)) * 0.64;
    tu.x += tu.vx * turtleSurge;
    tu.y = clamp(tu.y + Math.sin(tu.animPh - 0.5) * 0.18, 90, safeBottom - 10);
    if (tu.x < -34) { tu.x = -32; tu.vx = 0.26 + rnd() * 0.1; tu.y = 96 + rnd() * 98; }
    else if (tu.x > W + 34) { tu.x = W + 32; tu.vx = -(0.26 + rnd() * 0.1); tu.y = 96 + rnd() * 98; }

    for (const jf of w.jellies) {
      jf.animPh += dt * jf.speed;
      // Medusa jet-propulsion locked directly to bell contraction phase of its 8-frame cycle!
      const thrust = Math.max(0, Math.sin(jf.animPh));
      jf.y -= thrust * 0.30 - 0.11; jf.y += (jf.homeY - jf.y) * 0.004;
      jf.x += jf.vx + Math.sin(w.t * 0.5 + jf.ph) * 0.06;
      if (jf.x < 24) jf.vx = Math.abs(jf.vx); if (jf.x > W - 24) jf.vx = -Math.abs(jf.vx);
      if (jf.y < 76) jf.y = 76; if (jf.y > 318) jf.y = 318;
    }

    const bx = 166 + Math.sin(w.t * 0.35) * 38, by = 186 + Math.cos(w.t * 0.48) * 28;
    const lure = w.ripples.length ? w.ripples[w.ripples.length - 1] : null;
    for (let i = 0; i < w.sardines.length; i++) {
      const s = w.sardines[i];
      const slotX = bx + Math.cos(w.t * 0.85 + s.ph) * (14 + (i % 5) * 6);
      const slotY = by + Math.sin(w.t * 1.15 + s.ph * 1.3) * (8 + (i % 4) * 4);
      s.vx = lerp(s.vx, (slotX - s.x) * 0.06, 0.10);
      s.vy = lerp(s.vy, (slotY - s.y) * 0.06, 0.10);
      const threats = [[d.x, d.y, 28, 0.42]];
      if (sh.cooldown <= 0) threats.push([sh.x, sh.y, 48, 0.72]);
      if (lure && lure.age < 1.2) threats.push([lure.x, lure.y, 46, 0.68]);
      for (const [tx0, ty0, rad, push] of threats) {
        const rx = s.x - tx0, ry = s.y - ty0, rd = Math.hypot(rx, ry);
        if (rd > 0.1 && rd < rad) { const f = (1 - rd / rad) * push; s.vx += (rx / rd) * f; s.vy += (ry / rd) * f; }
      }
      const sp = Math.hypot(s.vx, s.vy) || 1;
      if (sp > 1.85) { s.vx = (s.vx / sp) * 1.85; s.vy = (s.vy / sp) * 1.85; }
      s.x = clamp(s.x + s.vx, 76, W - 20); s.y = clamp(s.y + s.vy, 92, 294);
    }

    for (const f of w.fish) {
      f.animPh += dt * (6.2 + Math.abs(f.vx) * 6.8);
      if (f.kind === 'clown') {
        f.vx = lerp(f.vx, (ANEMONE.x - f.x) * 0.025 + Math.sin(w.t * 2.2 + f.ph) * 0.28, 0.08);
        f.vy = lerp(f.vy, ((ANEMONE.y - 12) - f.y) * 0.03 + Math.cos(w.t * 2.8 + f.ph) * 0.18, 0.08);
        f.x += f.vx; f.y += f.vy; continue;
      }
      if (lure && lure.age < 3.4 && Math.hypot(lure.x - f.x, lure.y - f.y) < 96) {
        const fx = lure.x - f.x, fy = lure.y - f.y, fd = Math.hypot(fx, fy) || 1;
        f.vx = lerp(f.vx, (fx / fd) * 0.72, 0.05); f.vy = lerp(f.vy, (fy / fd) * 0.46, 0.05);
      } else {
        f.vy = lerp(f.vy, (f.homeY - f.y) * 0.012 + Math.sin(w.t * 2 + f.ph) * 0.10, 0.06);
        const sp = f.kind === 'teal' ? 0.42 : 0.32;
        f.vx = lerp(f.vx, (f.vx >= 0 ? 1 : -1) * sp, 0.03);
      }
      f.x += f.vx; f.y = clamp(f.y + f.vy, 76, 330);
      if (f.x < -18) f.x = W + 16; if (f.x > W + 18) f.x = -16;
    }

    for (const v of w.vents) {
      if (rnd() < v.rate && w.bubbles.length < 28) w.bubbles.push({ x: v.x + (rnd() - 0.5) * 8, y: v.y, r: rnd() < 0.7 ? 1 : 2, vy: -0.45 - rnd() * 0.42, ph: rnd() * 6.28 });
    }
    for (let i = w.bubbles.length - 1; i >= 0; i--) {
      const b = w.bubbles[i]; b.y += b.vy; b.x += Math.sin(w.t * 3.8 + b.ph) * 0.28;
      if (b.y < 16) w.bubbles.splice(i, 1);
    }
    for (let i = w.bubbleRings.length - 1; i >= 0; i--) {
      const br = w.bubbleRings[i]; br.age += dt; br.y += br.vy; br.rx += 0.055; br.x += Math.sin(w.t * 2.4 + br.ph) * 0.25;
      if (br.y < 18 || br.age > 6.5) w.bubbleRings.splice(i, 1);
    }
    for (const mo of w.motes) {
      mo.x += mo.vx + Math.sin(w.t * 0.7 + mo.ph) * 0.05; mo.y += mo.vy;
      if (mo.x > W + 2) mo.x = -2; if (mo.y < 48) mo.y = 342; if (mo.y > 344) mo.y = 50;
    }
    for (let i = w.ripples.length - 1; i >= 0; i--) { w.ripples[i].age += dt; if (w.ripples[i].age > 3.5) w.ripples.splice(i, 1); }
  }

  function pokeWorld(w, x, y) {
    const cx = clamp(x, 6, W - 6), cy = clamp(y, 70, 385);
    w.stats.pokes++;
    w.ripples.push({ x: cx, y: cy, age: 0 });
    if (Math.hypot(cx - CHEST.x, cy - CHEST.y) < 34) {
      triggerChest(w);
    } else if (Math.hypot(cx - w.octopus.x, cy - w.octopus.y) < 26) {
      startleOctopus(w);
    } else if (Math.hypot(cx - CLAM.x, cy - CLAM.y) < 26) {
      w.clam.timer = 2.4;
    } else if (cx <= 108 && cy >= 210 && cy <= 346) {
      // Tap inside Left Atlantis Sanctuary -> send diver cleanly through the colonnade entrance!
      sendDiverToRoom(w, 'left');
      return;
    } else if (cx >= 216 && cy >= 248 && cy <= 344) {
      // Tap inside Right Poseidon Vault -> send diver cleanly behind the right fluted column!
      sendDiverToRoom(w, 'right');
      return;
    } else if (w.bubbleRings.length < 4) {
      w.bubbleRings.push({ x: cx, y: cy, rx: 4.5, vy: -0.58, age: 0, ph: w.rnd() * 6.28 });
      w.stats.rings++;
    }
    // If diver is currently inside a dark chamber, gracefully exit through its doorway before swimming to open water!
    if (w.diver.visit && w.diver.inRoom) {
      w.diver.visit.stage = 'exit';
      w.diver.visit.queued = null;
    } else {
      w.diver.visit = null;
      w.diver.target = [clamp(cx, 24, W - 24), clamp(cy, 88, 300)];
      w.diver.targetTimer = 5.5;
      w.diver.flash = 0.85;
    }
    for (let i = 0; i < 6 && w.bubbles.length < 54; i++) {
      const ang = (i / 6) * Math.PI * 2;
      w.bubbles.push({ x: cx + Math.cos(ang) * 5, y: cy + Math.sin(ang) * 4, r: i % 3 === 0 ? 2 : 1, vy: -0.55 - w.rnd() * 0.4, ph: w.rnd() * 6.28 });
    }
  }

  function drawPlate(g, s, name) {
    const f = s.frames && s.frames[name];
    if (s.atlas && f) { g.drawImage(s.atlas, f[0], f[1], f[2], f[3], 0, 0, f[2], f[3]); return true; }
    return false;
  }

  const TWO_PI = Math.PI * 2;
  function phaseIdx(ph, n) {
    const f = ((ph % TWO_PI) + TWO_PI) % TWO_PI;
    return Math.floor((f / TWO_PI) * n) % n;
  }

  function drawSprite(g, s, name, cx, cy) {
    const f = s.frames && s.frames[name];
    if (!s.atlas || !f) return false;
    g.drawImage(s.atlas, f[0], f[1], f[2], f[3], Math.round(cx - f[2] * 0.5), Math.round(cy - f[3] * 0.5), f[2], f[3]);
    return true;
  }

  // Graceful sprite lookup: if a tablet briefly runs newer JS against a stale 2-frame cached atlas,
  // reuse its baked 0/1 frames instead of flickering into procedural fallbacks!
  function drawAnimSprite(g, s, prefix, idx, dir, cx, cy) {
    if (!s.atlas || !s.frames) return false;
    const sfx = dir ? '_' + dir : '';
    const f = s.frames[prefix + '_' + idx + sfx]
      || s.frames[prefix + '_' + (idx & 1) + sfx]
      || s.frames[prefix + '_0' + sfx];
    if (!f) return false;
    g.drawImage(s.atlas, f[0], f[1], f[2], f[3], Math.round(cx - f[2] * 0.5), Math.round(cy - f[3] * 0.5), f[2], f[3]);
    return true;
  }

  function drawDiverEntity(g, s, d, pal, t) {
    const dd = d.face >= 0 ? 'r' : 'l';
    const df = phaseIdx(d.kickPh, 12);
    if (s.frames && s.frames['diver_0_' + dd]) {
      drawDiverEffects(g, d, pal, t);
      drawAnimSprite(g, s, 'diver', df, dd, d.x, d.y);
    } else {
      drawDiver(g, d, pal, t);
    }
  }

  function drawPlateAt(g, s, name, dx, dy, alpha) {
    const f = s.frames && s.frames[name];
    if (!s.atlas || !f) return false;
    const prev = typeof g.globalAlpha === 'number' ? g.globalAlpha : 1;
    if (alpha !== undefined && alpha < 0.999) g.globalAlpha = clamp(alpha, 0, 1);
    g.drawImage(s.atlas, f[0], f[1], f[2], f[3], dx, dy, f[2], f[3]);
    if (alpha !== undefined && alpha < 0.999) g.globalAlpha = prev;
    return true;
  }

  function drawRoomInterior(g, s, rm, t) {
    const spec = ROOMS[rm.id];
    const lit = rm.light;
    // Even in total darkness, a tiny mysterious breathing glyph spark teases the hidden room!
    if (lit < 0.08) {
      const hint = (0.20 + 0.18 * Math.sin(t * 2.2 + (rm.id === 'left' ? 0 : 2.1)) + rm.pulse * 0.55) * (1 - lit * 8);
      if (hint > 0.08) {
        const [rx, ry] = spec.relic;
        g.fillStyle = (rm.id === 'left' ? 'rgba(92,248,244,' : 'rgba(255,222,108,') + clamp(hint, 0, 0.85).toFixed(3) + ')';
        g.fillRect(rx - 1, ry - 1, 2, 2);
      }
      if (lit <= 0.01) return;
    }

    // 1. Full-room baked 16-bit illuminated sanctuary wall/mural/shrine plate (1 drawImage with smooth globalAlpha!)
    const [lx, ly] = spec.litPos;
    if (!drawPlateAt(g, s, spec.litPlate, lx, ly, lit)) {
      // Lightweight warm-glow fallback if running against an older cached atlas
      const [hx, hy, hw, hh] = spec.hit;
      g.fillStyle = (rm.id === 'left' ? 'rgba(84,206,196,' : 'rgba(222,196,104,') + (lit * 0.36).toFixed(3) + ')';
      g.fillRect(hx, hy, hw, hh);
    }

    // 2. Soft whole-room volumetric underwater glow wash (so the ENTIRE hall glows warmly, not just a torch beam!)
    const [hx, hy, hw, hh] = spec.hit;
    const magicBoost = rm.magic * 0.22;
    g.fillStyle = (rm.id === 'left' ? 'rgba(138,248,236,' : 'rgba(255,224,132,') + ((lit * 0.10 + magicBoost * 0.5)).toFixed(3) + ')';
    g.fillRect(hx + 2, hy + 4, hw - 4, hh - 10);

    // 3. Living animated interior treasures & interactive secrets!
    if (rm.id === 'left') {
      // Levitating glowing Atlantean Crystal Orb above the marble pedestal (x=68, y=276) with soft rounded halo!
      const cx = 68, cy = Math.round(276 + Math.sin(t * 2.6) * 2.0);
      const glowR = 6 + Math.round(rm.magic * 5);
      g.fillStyle = 'rgba(116,255,248,' + (lit * (0.20 + rm.magic * 0.28)).toFixed(3) + ')';
      drawInkBlob(g, cx, cy, glowR + 2, glowR + 2);
      g.fillStyle = 'rgba(255,244,170,' + (lit * (0.34 + rm.magic * 0.36)).toFixed(3) + ')';
      drawInkBlob(g, cx, cy, Math.max(3, glowR - 2), Math.max(3, glowR - 2));
      g.fillStyle = 'rgba(136,255,252,' + lit.toFixed(3) + ')';
      g.fillRect(cx - 1, cy - 3, 3, 6); g.fillRect(cx - 2, cy - 1, 5, 2);
      g.fillStyle = 'rgba(255,255,255,' + lit.toFixed(3) + ')';
      g.fillRect(cx, cy - 2, 1, 3);

      // Expanding magic rune ring & cascading wall runes when the diver interacts with the crystal!
      if (rm.magic > 0.04) {
        const rad = Math.round(6 + (1 - rm.magic) * 20);
        g.fillStyle = 'rgba(164,255,248,' + (rm.magic * 0.78).toFixed(3) + ')';
        for (let k = 0; k < 12; k++) {
          const th = (k / 12) * Math.PI * 2 + t * 1.4;
          g.fillRect(Math.round(cx + Math.cos(th) * rad), Math.round(cy + Math.sin(th) * rad * 0.85), 2, 2);
        }
        // Cascading golden rune pulse on left gallery compass-sun mural!
        g.fillStyle = 'rgba(255,238,144,' + (rm.magic * 0.65).toFixed(3) + ')';
        drawInkBlob(g, 19, 248, 5, 5);
      }

      // 2 tiny fluttering golden luminous cave sprites awakening in the lit hall!
      if (lit > 0.22) {
        for (let k = 0; k < 2; k++) {
          const sx = Math.round((k === 0 ? 24 : 70) + Math.sin(t * (1.8 + k * 0.5) + k * 2.4) * (k === 0 ? 9 : 11));
          const sy = Math.round((k === 0 ? 258 : 250) + Math.cos(t * (2.3 + k * 0.4) + k) * 8);
          g.fillStyle = 'rgba(255,236,134,' + ((lit - 0.15) * 0.55).toFixed(3) + ')';
          g.fillRect(sx - 2, sy - 1, 5, 3);
          g.fillStyle = 'rgba(255,255,230,' + lit.toFixed(3) + ')';
          g.fillRect(sx, sy, 2, 1);
        }
      }
    } else {
      // Right Poseidon Vault: gleaming Golden Crown & Trident magic shimmer!
      const cx = 251, cy = 288;
      if (rm.magic > 0.04) {
        const rad = Math.round(5 + (1 - rm.magic) * 16);
        g.fillStyle = 'rgba(132,255,204,' + (rm.magic * 0.75).toFixed(3) + ')';
        for (let k = 0; k < 10; k++) {
          const th = (k / 10) * Math.PI * 2 - t * 1.5;
          g.fillRect(Math.round(cx + Math.cos(th) * rad), Math.round(cy + Math.sin(th) * rad), 2, 1);
        }
        g.fillStyle = 'rgba(255,244,162,' + (rm.magic * 0.34).toFixed(3) + ')';
        drawInkBlob(g, cx, cy - 2, 5, 9);
      }
      // Friendly Emerald-Gold Cave Moray Eel peeking curiously out of the stone altar crevice (y=313)!
      if (rm.eel > 0.08) {
        const ext = Math.round(rm.eel * 9);
        const sway = Math.round(Math.sin(t * (rm.magic > 0.1 ? 7.5 : 3.2)) * 1.6);
        const ex = 254 - ext, ey = 313 + sway;
        // Undulating emerald body tucked back into the crevice
        g.fillStyle = 'rgba(24,132,94,' + lit.toFixed(3) + ')';
        g.fillRect(ex + 3, ey, ext + 2, 4);
        g.fillStyle = 'rgba(78,224,158,' + lit.toFixed(3) + ')';
        g.fillRect(ex + 2, ey - 1, ext + 1, 2);
        // Cute rounded moray head with blinking golden eye!
        g.fillStyle = 'rgba(54,196,138,' + lit.toFixed(3) + ')';
        g.fillRect(ex - 2, ey - 1, 6, 5);
        g.fillStyle = 'rgba(164,255,212,' + lit.toFixed(3) + ')';
        g.fillRect(ex - 1, ey - 2, 4, 1);
        const blink = Math.sin(t * 2.1) > 0.94;
        g.fillStyle = blink ? '#103828' : '#fff488';
        g.fillRect(ex, ey, 2, 2);
        if (!blink) { g.fillStyle = '#0a1820'; g.fillRect(ex, ey + 1, 1, 1); }
      }
    }

    // 4. Rising arcane gold/turquoise sparkles inside the chamber!
    for (let i = 0; i < rm.sparkles.length; i++) {
      const sp = rm.sparkles[i];
      const a = clamp((1 - sp.age / sp.life) * Math.max(lit, rm.magic), 0, 1);
      if (a <= 0.02) continue;
      g.fillStyle = (sp.gold ? 'rgba(255,244,152,' : 'rgba(146,255,246,') + a.toFixed(3) + ')';
      g.fillRect(Math.round(sp.x), Math.round(sp.y), 2, 2);
    }
  }

  function drawRoomOcclude(g, s, rm, diverInRoom) {
    if (rm.light <= 0.01 && diverInRoom !== rm.id) return;
    const spec = ROOMS[rm.id];
    drawPlateAt(g, s, spec.occPlate, spec.occPos[0], spec.occPos[1], 1);
  }

  // Curated bioluminescent coral, sea-fan & ruin-moss glow nodes anchored strictly ON reef corals & stonework
  const BIO_NODES = [
    [48, 30, 7, 'rgba(255,104,218,'],   [50, 86, 8, 'rgba(255,104,218,'],
    [22, 188, 7, 'rgba(56,248,255,'],   [44, 192, 8, 'rgba(255,104,218,'],
    [62, 196, 7, 'rgba(40,255,196,'],   [216, 224, 9, 'rgba(255,104,218,'],
    [238, 234, 7, 'rgba(56,248,255,'],  [24, 304, 8, 'rgba(255,104,218,'],
    [36, 336, 7, 'rgba(40,255,196,'],   [76, 354, 8, 'rgba(56,248,255,'],
    [116, 342, 7, 'rgba(40,255,196,'],  [208, 346, 9, 'rgba(255,104,218,'],
    [248, 354, 8, 'rgba(40,255,196,'],  [254, 320, 8, 'rgba(74,168,255,'],
  ];

  function drawSoftGlow(g, cx, cy, r, rgbaPrefix, alpha) {
    if (alpha <= 0.01) return;
    if (typeof g.createRadialGradient === 'function') {
      const grad = g.createRadialGradient(cx, cy, 0, cx, cy, r);
      grad.addColorStop(0.0, rgbaPrefix + alpha.toFixed(3) + ')');
      grad.addColorStop(0.45, rgbaPrefix + (alpha * 0.42).toFixed(3) + ')');
      grad.addColorStop(1.0, rgbaPrefix + '0)');
      g.fillStyle = grad;
      g.fillRect(Math.floor(cx - r), Math.floor(cy - r), Math.ceil(r * 2), Math.ceil(r * 2));
    } else {
      g.fillStyle = rgbaPrefix + (alpha * 0.5).toFixed(3) + ')';
      drawInkBlob(g, Math.round(cx), Math.round(cy), Math.round(r * 0.65), Math.round(r * 0.55));
    }
  }

  function drawAtmosphereVeil(g, pal) {
    if (!pal.veilMid) return;
    if (typeof g.createLinearGradient === 'function') {
      const grad = g.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0.0, pal.veilTop);
      grad.addColorStop(0.45, pal.veilMid);
      grad.addColorStop(1.0, pal.veilBot);
      g.fillStyle = grad;
      g.fillRect(0, 0, W, H);
    } else {
      g.fillStyle = pal.veilTop; g.fillRect(0, 0, W, 120);
      g.fillStyle = pal.veilMid; g.fillRect(0, 120, W, 160);
      g.fillStyle = pal.veilBot; g.fillRect(0, 280, W, H - 280);
    }
  }

  function drawBioluminescentCorals(g, pal, t, low) {
    if (!pal.bioCoral) return;
    const step = low ? 2 : 1;
    const canAdd = typeof g.save === 'function' && typeof g.restore === 'function';
    if (canAdd) { g.save(); g.globalCompositeOperation = 'lighter'; }
    for (let i = 0; i < BIO_NODES.length; i += step) {
      const [bx, by, br, col] = BIO_NODES[i];
      const pulse = 0.52 + 0.48 * Math.sin(t * (2.1 + (i % 4) * 0.45) + i * 1.37);
      const a = pulse * pal.bioGlow;
      drawSoftGlow(g, bx, by, br + 3, col, a * 0.42);
      // Tiny crisp 1px glowing coral polyp spark
      g.fillStyle = col + (a * 0.85).toFixed(3) + ')';
      g.fillRect(bx, by, 1, 1);
    }
    if (canAdd) g.restore();
  }

  function drawDiverEffects(g, d, pal, t) {
    const flip = d.face < 0, x0 = Math.round(d.x), y0 = Math.round(d.y);
    const pitch = clamp(d.pitch, -0.38, 0.38);
    const torchAlpha = Math.max(pal.torchGain, d.inRoom ? 0.82 : 0) * (0.88 + 0.12 * Math.sin(t * 2.4));
    if (torchAlpha > 0.14) {
      const dir = flip ? -1 : 1, hx = x0 + dir * 20, hy = y0 + 2 + Math.round(pitch * 15);
      const strong = torchAlpha >= 0.6;
      const outerLen = strong ? 102 : 54, innerLen = strong ? 74 : 38;
      const outerSpread = strong ? 28 : 11, innerSpread = strong ? 12 : 5;
      const canAdd = strong && typeof g.save === 'function' && typeof g.restore === 'function';
      if (canAdd) { g.save(); g.globalCompositeOperation = 'lighter'; }
      if (typeof g.beginPath === 'function' && typeof g.fill === 'function') {
        const endX = hx + dir * outerLen, endY = hy + Math.round(pitch * outerLen);
        if (typeof g.createLinearGradient === 'function') {
          const og = g.createLinearGradient(hx, hy, endX, endY);
          og.addColorStop(0.0, 'rgba(154, 240, 255, ' + (torchAlpha * (strong ? 0.34 : 0.16)).toFixed(3) + ')');
          og.addColorStop(0.45, 'rgba(116, 224, 255, ' + (torchAlpha * (strong ? 0.18 : 0.08)).toFixed(3) + ')');
          og.addColorStop(1.0, 'rgba(92, 200, 255, 0)');
          g.fillStyle = og;
        } else {
          g.fillStyle = 'rgba(132, 232, 255, ' + (torchAlpha * (strong ? 0.22 : 0.14)).toFixed(3) + ')';
        }
        g.beginPath();
        g.moveTo(hx, hy - 2);
        g.lineTo(endX, endY - outerSpread);
        g.lineTo(endX, endY + outerSpread);
        g.lineTo(hx, hy + 2);
        g.closePath(); g.fill();
        if (strong) {
          const iEndX = hx + dir * innerLen, iEndY = hy + Math.round(pitch * innerLen);
          if (typeof g.createLinearGradient === 'function') {
            const ig = g.createLinearGradient(hx, hy, iEndX, iEndY);
            ig.addColorStop(0.0, 'rgba(236, 255, 254, ' + (torchAlpha * 0.46).toFixed(3) + ')');
            ig.addColorStop(0.55, 'rgba(182, 250, 255, ' + (torchAlpha * 0.18).toFixed(3) + ')');
            ig.addColorStop(1.0, 'rgba(140, 232, 255, 0)');
            g.fillStyle = ig;
          } else {
            g.fillStyle = 'rgba(222, 255, 252, ' + (torchAlpha * 0.26).toFixed(3) + ')';
          }
          g.beginPath();
          g.moveTo(hx, hy - 1);
          g.lineTo(iEndX, iEndY - innerSpread);
          g.lineTo(iEndX, iEndY + innerSpread);
          g.lineTo(hx, hy + 1);
          g.closePath(); g.fill();
          // Smooth headlamp lens halo right at the torch tip
          drawSoftGlow(g, hx + dir * 2, hy, 8, 'rgba(224,255,255,', torchAlpha * 0.65);
          g.fillStyle = 'rgba(255, 255, 255, ' + (torchAlpha * 0.92).toFixed(3) + ')';
          g.fillRect(hx, hy, 2, 2);
        }
      } else {
        g.fillStyle = 'rgba(196, 255, 248, ' + (torchAlpha * 0.18).toFixed(3) + ')';
        g.fillRect(dir > 0 ? hx : hx - outerLen, hy - 6, outerLen, 12);
      }
      if (canAdd) g.restore();
    }
    if (d.flash > 0) {
      const fx = x0 + (flip ? -21 : 21), fy = y0 + 2, r = Math.round(6 + (1 - d.flash) * 14);
      g.fillStyle = 'rgba(255, 255, 238, ' + (d.flash * 0.85).toFixed(2) + ')';
      g.fillRect(fx - r, fy, r * 2, 1); g.fillRect(fx, fy - r, 1, r * 2);
      g.fillStyle = 'rgba(200, 255, 252, ' + (d.flash * 0.40).toFixed(2) + ')';
      g.fillRect(fx - (r >> 1), fy - (r >> 1), r, r);
    }
  }

  function renderFrame(g, s, tier) {
    const w = s.world;
    const pal = PALETTES[s.phase] || PALETTES.day;
    const low = tier === 'low' || tier === 'light';
    if ('imageSmoothingEnabled' in g) g.imageSmoothingEnabled = false;

    // 1. Pre-baked water gradient (1 drawImage instead of 176 fillRects!)
    if (s.backdrops && s.backdrops[s.phase]) {
      g.drawImage(s.backdrops[s.phase], 0, 0);
    } else {
      const stops = pal.water;
      for (let y = 0; y < SAND_Y + 6; y += 4) {
        const f = y / (SAND_Y + 6), pos = f * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(pos)), fr = pos - i;
        g.fillStyle = 'rgb(' + Math.round(lerp(stops[i][0], stops[i + 1][0], fr)) + ',' + Math.round(lerp(stops[i][1], stops[i + 1][1], fr)) + ',' + Math.round(lerp(stops[i][2], stops[i + 1][2], fr)) + ')';
        g.fillRect(0, y, W, 4);
      }
    }

    // 2. Animated Snell's-window ocean surface (1 ImageData drawImage, refreshed at 15 Hz — 50x faster!)
    if (s.surfBuf) {
      const stride = low ? 3 : 2;
      if (s.surfPhase !== s.phase || s.surfTick < 0 || (w.steps - s.surfTick) >= stride) {
        updateSurfaceBuffer(s.surfBuf, pal, w.t);
        s.surfTick = w.steps; s.surfPhase = s.phase;
      }
      g.drawImage(s.surfBuf.canvas, 0, 0, SW, SH, 0, 0, W, SH);
    } else {
      drawSurfaceFallback(g, pal, w.t);
    }

    // 3. Deep pelagic Humpback Whale / Giant Manta Ray (8-frame biomechanical cycle -> 1 drawImage!)
    if (w.megafauna.cooldown <= 0) {
      const m = w.megafauna;
      const dir = m.vx >= 0 ? 'r' : 'l';
      const frm = phaseIdx(m.animPh, 8);
      if (!drawAnimSprite(g, s, m.kind, frm, dir, m.x, m.y)) {
        if (m.kind === 'whale') drawWhale(g, m, w.t); else drawManta(g, m, w.t);
      }
    }

    // 4. Baked distant Atlantis archway, misty citadel & sunlit sand plate
    if (!drawPlate(g, s, 'bg')) { g.fillStyle = '#c8bc84'; g.fillRect(0, SAND_Y, W, H - SAND_Y); }

    // 5. Luminous volumetric sunbeams (14 seamless diagonal quads!)
    drawSunbeams(g, pal, w.t);

    // 6. Patrolling Reef Shark (8-frame sleek swim cycle!) & shimmering 20-sardine Bait-Ball!
    if (w.shark.cooldown <= 0) {
      const sh = w.shark, sf = phaseIdx(sh.animPh, 8), sd = sh.vx >= 0 ? 'r' : 'l';
      if (!drawAnimSprite(g, s, 'shark', sf, sd, sh.x, sh.y)) drawShark(g, sh, w.t);
    }
    for (const sd of w.sardines) drawSardine(g, sd, w.t);

    // 7. Baked foreground multi-tiered Atlantis temple, shipwreck bow, fluted columns, statues & living coral gardens
    drawPlate(g, s, 'fg');

    // 8. TRUE PHYSICAL RAY-REFRACTION CAUSTICS (crisp white sunlight by day, gentle silver moon-caustics at night!)
    if (s.causticBuf) {
      const stride = low ? 4 : 2;
      if (s.causticPhase !== s.phase || s.causticTick < 0 || (w.steps - s.causticTick) >= stride) {
        updateCausticBuffer(s.causticBuf, pal, w.t, s.causticMask);
        s.causticTick = w.steps; s.causticPhase = s.phase;
      }
      g.drawImage(s.causticBuf.canvas, 0, 0, CW, CH, 0, 0, W, H);
    } else {
      drawCausticsFallback(g, pal, w.t, s.causticMask);
    }

    // 9. Non-luminous reef props & sea creatures (darkened naturally by the dawn/dusk/night veil below!)
    const clamStage = Math.min(4, Math.max(0, Math.floor(clamp(w.clam.open, 0, 1) * 4.99)));
    if (!drawAnimSprite(g, s, 'clam', clamStage, '', CLAM.x, CLAM.y - 2)) {
      drawGiantClam(g, w.clam, pal, w.t);
    }
    g.fillStyle = 'rgba(12, 32, 42, 0.40)'; g.fillRect(CHEST.x - 14, CHEST.y + 8, 28, 3);
    const chestStage = Math.min(4, Math.max(0, Math.floor(clamp(w.chest.open, 0, 1) * 4.99)));
    if (!drawAnimSprite(g, s, 'chest', chestStage, '', CHEST.x, CHEST.y - 2)) {
      drawTreasureChest(g, w.chest, w.t);
    }
    drawAnemone(g, w.t);
    const oc = w.octopus;
    if (oc.inks.length) drawOctopusInks(g, oc.inks, w.t);
    const ocFrm = phaseIdx(oc.animPh, 10);
    if (!drawAnimSprite(g, s, 'octo', ocFrm, '', oc.x, oc.y + Math.sin(w.t * 2.5) * 1.4)) {
      drawOctopus(g, oc, w.t);
    }
    if (w.dolphin.cooldown <= 0) {
      const dl = w.dolphin, df = phaseIdx(dl.animPh, 10), dd = dl.vx >= 0 ? 'r' : 'l';
      if (!drawAnimSprite(g, s, 'dolphin', df, dd, dl.x, dl.y)) drawDolphin(g, dl, w.t);
    }
    {
      const tu = w.turtle, tf = phaseIdx(tu.animPh, 10), td = tu.vx >= 0 ? 'r' : 'l';
      if (!drawAnimSprite(g, s, 'turtle', tf, td, tu.x, tu.y)) drawTurtle(g, tu, w.t);
    }
    for (const f of w.fish) {
      const ff = phaseIdx(f.animPh, 6), fd = f.vx >= 0 ? 'r' : 'l';
      if (!drawAnimSprite(g, s, 'fish_' + f.kind, ff, fd, f.x, f.y)) drawFish(g, f, w.t);
    }
    drawKelp(g, w.t);

    // 10. DRAMATIC PHASE ATMOSPHERE VEIL (zero cost in day; warm golden tint at dawn; deep twilight indigo at dusk;
    //     true midnight ocean darkness at night so bioluminescence, rooms & the diver's headlamp blaze to life!)
    drawAtmosphereVeil(g, pal);

    // 11. TRUE 3D ANCIENT CHAMBERS (blazing warmly out of the dark ruins at dusk & night, with columns cleanly in front!)
    drawRoomInterior(g, s, w.rooms.left, w.t);
    drawRoomInterior(g, s, w.rooms.right, w.t);
    if (w.diver.inRoom) drawDiverEntity(g, s, w.diver, pal, w.t);
    drawRoomOcclude(g, s, w.rooms.left, w.diver.inRoom);
    drawRoomOcclude(g, s, w.rooms.right, w.diver.inRoom);

    // 12. LUMINOUS REEF MAGIC ABOVE THE DARKNESS: smooth radial bioluminescent corals, pearl clam glow, treasure gold,
    //     glowing jellyfish lanterns, dinoflagellate marine snow & hero diver's smooth cutting headlamp!
    drawBioluminescentCorals(g, pal, w.t, low);
    if (w.clam.open > 0.35) {
      const ca = (0.22 + pal.bioGlow * 0.42) * w.clam.open;
      drawSoftGlow(g, CLAM.x, CLAM.y - 5, pal.bioCoral ? 20 : 13, 'rgba(128,255,252,', ca);
    }
    if (w.chest.open > 0.28) {
      const a = w.chest.open * (0.28 + pal.bioGlow * 0.28 + 0.06 * Math.sin(w.t * 6));
      drawSoftGlow(g, CHEST.x, CHEST.y - 10, pal.bioCoral ? 24 : 16, 'rgba(255,220,96,', a);
    }
    for (const c of w.coins) drawCoin(g, c, w.t);

    if (!low) {
      for (const mo of w.motes) {
        const bright = pal.bioCoral || inSunbeam(mo.x, mo.y, w.t) > 0.22;
        const mx = Math.round(mo.x), my = Math.round(mo.y);
        if (pal.bioCoral && (mo.ph > 3.2)) {
          const glow = 0.20 + 0.22 * Math.sin(w.t * 2.8 + mo.ph * 2.1);
          g.fillStyle = 'rgba(72, 248, 255, ' + (glow * pal.bioGlow).toFixed(3) + ')';
          g.fillRect(mx - 1, my - 1, 3, 3);
        }
        g.fillStyle = bright ? pal.moteBright : pal.moteDim;
        g.fillRect(mx, my, 1, 1);
      }
    }

    for (const jf of w.jellies) {
      const jfrm = phaseIdx(jf.animPh, 8);
      const jpref = jf.pink ? 'jelly_pink' : 'jelly_cyan';
      if (pal.bioGlow > 0.40) {
        const jCol = jf.pink ? 'rgba(255,112,222,' : 'rgba(64,248,255,';
        const jPulse = 0.8 + 0.2 * Math.sin(w.t * 3.0 + jf.ph);
        drawSoftGlow(g, jf.x, jf.y - 1, pal.bioCoral ? 20 : 13, jCol, (0.22 + pal.bioGlow * 0.26) * jPulse);
      }
      if (!drawAnimSprite(g, s, jpref, jfrm, '', jf.x, jf.y + 6)) drawJellyfish(g, jf, pal, w.t);
    }
    if (!w.diver.inRoom) {
      drawDiverEntity(g, s, w.diver, pal, w.t);
    }

    // 13. Shimmering bubbles, rising Scuba Bubble Rings & bioluminescent touch ripples
    for (const b of w.bubbles) drawBubble(g, b);
    for (const br of w.bubbleRings) drawBubbleRing(g, br);
    for (const rp of w.ripples) {
      if (rp.age > 1.3) continue;
      const rad = Math.round(4 + rp.age * 22);
      const fade = 1 - rp.age / 1.3;
      if (pal.bioRipple) {
        g.fillStyle = 'rgba(56, 248, 255, ' + (fade * 0.34).toFixed(3) + ')';
        for (let ang = 0; ang < 12; ang++) {
          const th = (ang / 12) * Math.PI * 2;
          g.fillRect(Math.round(rp.x + Math.cos(th) * rad) - 1, Math.round(rp.y + Math.sin(th) * rad * 0.6) - 1, 4, 3);
        }
      }
      g.fillStyle = (pal.bioRipple ? 'rgba(180, 255, 255, ' : 'rgba(206, 255, 252, ') + (fade * 0.82).toFixed(2) + ')';
      for (let ang = 0; ang < 12; ang++) {
        const th = (ang / 12) * Math.PI * 2;
        g.fillRect(Math.round(rp.x + Math.cos(th) * rad), Math.round(rp.y + Math.sin(th) * rad * 0.6), 2, 1);
      }
    }
  }

  function makeImageBuf(w, h) {
    const m = makeCanvas(w, h, false);
    if (!m || typeof m.g.createImageData !== 'function') return null;
    const img = m.g.createImageData(w, h);
    return { canvas: m.canvas, g: m.g, img, u32: new Uint32Array(img.data.buffer) };
  }

  /* ---- scene module contract */
  const scene = {
    size: [W, H],
    post: 'crt-clear',
    dbg: {},
    init(api) {
      const seed = typeof api.random === 'function' ? Math.floor(api.random() * 4294967296) : 4242;
      const frames = api && api.json && api.json.frames && typeof api.json.frames === 'object' ? api.json.frames : null;
      this.s = {
        world: createWorld(seed),
        atlas: api && api.atlas ? api.atlas : null,
        frames,
        backdrops: makeBackdropCache(),
        surfBuf: makeImageBuf(SW, SH),
        causticBuf: makeImageBuf(CW, CH),
        causticMask: extractCausticMask(api && api.atlas, frames),
        surfTick: -99, surfPhase: '',
        causticTick: -99, causticPhase: '',
        phase: this.dbg.phase || phaseFromClock(this.dbg.now ? new Date(this.dbg.now) : new Date()),
        clockTick: 0,
      };
    },
    step(api, dt) {
      const s = this.s;
      if (!s) return;
      if (++s.clockTick % 120 === 0) s.phase = this.dbg.phase || phaseFromClock(this.dbg.now ? new Date(this.dbg.now) : new Date());
      const bottom = api && api.view && finite(api.view.bottom) ? api.view.bottom : H;
      stepWorld(s.world, dt || STEP, bottom);
    },
    draw(api, g) {
      const s = this.s;
      if (!s) return;
      renderFrame(g, s, api && api.tier);
    },
    poke(api, x, y) {
      if (this.s && finite(x) && finite(y)) pokeWorld(this.s.world, x, y);
    },
  };

  const logic = {
    W, H, STEP, SURFACE_H, SAND_Y, SW, SH, CW, CH, CHEST, CLAM, ANEMONE, COIN_FADE, ROOMS, PALETTES, RAYS, KELP, DIVER_WAYPOINTS,
    seeded, phaseFromClock, surfaceWave, rayAt, inSunbeam, createWorld, stepWorld, pokeWorld,
    triggerChest, startleOctopus, sendDiverToRoom, triggerRoomInteraction, updateSurfaceBuffer, updateCausticBuffer, renderFrame,
  };
  if (global.TabletGames && typeof global.TabletGames.define === 'function') global.TabletGames.define('underwater', scene);
  if (typeof module !== 'undefined' && module.exports) module.exports = Object.assign({ scene }, logic);
}(typeof window !== 'undefined' ? window : globalThis));
