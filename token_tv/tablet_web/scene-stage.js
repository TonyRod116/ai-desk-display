/*
 * Scene stage for the tablet page: one picture or looping video drawn with a "look" (window.SceneStage).
 *
 *   const stage = SceneStage.create(container, {onStatus});   // container: <div id="stage">, position:absolute; inset:0
 *   stage.show(info)       info = one /api/scenes `info` entry plus {name}; null clears. Cross-fades from the previous scene.
 *   stage.setArea({left, top, width, height})   CSS px inside the container. photo/plain COVER the area centred on info.focus and
 *                          the picture goes on past it (same transform). crt/lcd CONTAIN the whole frame (bezel included) in it.
 *   stage.setMotion(on)    false: the still (info.still, else the first frame), nothing animates. true: animate.
 *   stage.setQuality(q)    'auto' (adaptive, default) | 'high' | 'low'. `?fx=off|low|high|css` in the page URL overrides it.
 *   stage.setLive(on)      the extra live effects of the scenes' `live` blocks (stage-live.js) and the answer to touch: on by default; off draws the scene as it was
 *                          before them (the gentle old drift and twinkle stay) and ignores touches. Night mode and battery saving use it.
 *   stage.setReadings(r)   the page's latest /api/status (null: it stopped arriving). Only a scene's `lamps` effect reads it (the quota as light); unrenewed for 45 s = unknown.
 *   stage.poke(x, y)       a touch at page coordinates (CSS px): rings on water, sparkles and a glow elsewhere, a bump and sparks on the pixel looks. Bounded to a
 *                          few at a time, ignored outside the area given to setArea, with motion off, paused, with live off, or at the css tier. Returns whether it took it.
 *   stage.pause() / resume() / status() / destroy()
 *   (testing only: create(container, {tuning: {off: ['drift', 'twinkle', ...]}}) switches single effects off, for before/after captures)
 *
 * Looks live in other files (stage-crt.js, stage-lcd.js, stage-photo.js) and register themselves:
 *
 *   SceneStage.register(name, (kit) => ({
 *     name, opaque,                 // opaque: the canvas has no transparent pixel (photo); false keeps an alpha channel
 *     history,                      // how many previous video frames the shader needs (lcd ghosting: 1)
 *     mipmapStills,                 // upload still pictures as a mip-mapped power-of-two texture (photo)
 *     layout(ctx) -> {canvas, picture, screen?, frame?, radius?, container, rows?, cols?},   // CSS px in the container
 *     create(gl, env) -> {setSource(src), draw(frame), dispose()},                           // WebGL 1 only
 *     animated(info, low) -> bool,  // a still picture that needs a 30 fps loop (drift, twinkle)
 *     live(info, ctx) -> bool,      // the scene's live effects run now (ctx: {live, motion, level}); the stage then draws at the tier's rate (30, 30, 24, 20 fps)
 *     pokeKind({info, layout, x, y}) -> 'ripple'|'glow'|'bump'|null,   // what a touch does here (the stage already checked it is inside the area)
 *     draw(frame) gets frame.live {on, cfg, pokes} and frame.fresh (the picture changed since the last draw: a look that caches it while a touch is alive redraws it)
 *     css(layout, info, el) -> {below: [nodes], above: [nodes], pixelated}                    // the no-WebGL approximation
 *   }))
 *
 * Tiers (status().tier): high (device pixel ratio up to 2) > medium (up to 1.5) > light (1) > low (heavy effects off) > css (no WebGL,
 * the plain <video>/<img> with CSS overlays). In 'auto' the governor steps down after about 2 s of late frames, waits, and never goes
 * back before 90 s of clean frames; a failed climb is banned for the rest of the session. A scene never ends on a blank screen: any
 * failure falls back to a lighter tier, the still picture, or leaves the previous scene in place.
 *
 * No network except the scene's own URLs, no inline script, no eval; shaders are strings.
 */
(function (global) {
  'use strict';

  const TAU = Math.PI * 2;
  const FADE_MS = 900;                 // cross-fade between two scenes
  const STILL_INTERVAL = 1000 / 30;    // animated still pictures draw at 30 fps
  const TOUCH_INTERVAL = 1000 / 30;    // a touch that is the only thing moving draws at 30 frames a second
  const LIVE_FILM_FPS = 24;            // a film below this rate gets its own loop for the live effects; a faster one draws them with its frames
  const NO_POKES = Object.freeze([]);
  const LOAD_TIMEOUT_MS = 12000;       // a video or picture that does not arrive in this time is given up
  const MAX_CANVAS_SIDE = 4096;
  const MAX_CANVAS_PIXELS = 5.2e6;     // backing store limit: about 1200x2000 plus margin, a mid-range tablet's comfortable ceiling
  const MAX_STILL_SIDE = 2048;         // stills above this are shrunk once when uploaded as mip-mapped textures
  const BASE_FALLBACK = [9, 18, 27];   // the page's own background, used when the container's cannot be read
  const LEVELS = [
    { name: 'high', dprCap: 2, low: false },
    { name: 'medium', dprCap: 1.5, low: false },
    { name: 'light', dprCap: 1, low: false },
    { name: 'low', dprCap: 1, low: true },
  ];
  const GOVERNOR = {
    windowMs: 2000,        // late frames must persist over this long to count
    minSamples: 3,         // and be at least this many frames: a machine that is far too slow delivers only a few in the window
    lateFraction: 0.5,     // half of the frames in the window late: step down
    holdMs: 1500,          // ignore frames this long after any change (shader compile, texture upload, resize)
    cooldownMs: 5000,      // extra pause after a step down
    upAfterMs: 90000,      // clean time needed before trying one level up
    upMaxLate: 0.03,       // at most this share of late frames in that time
    maxUps: 6,             // and never more than this many climbs in one session, whatever happens
    trialMs: 40000,        // a step down this soon after a climb bans that climb for good
  };

  /* ------------------------------------------------------------------------------------------------ pure helpers */

  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const mix = (a, b, t) => a + (b - a) * t;
  const smoothstep = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

  function hashString(text) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h >>> 0;
  }

  /** The largest rectangle with the media's aspect that fits (w, h), centred. */
  function containRect(areaW, areaH, w, h) {
    const s = Math.min(areaW / w, areaH / h);
    return { x: (areaW - w * s) / 2, y: (areaH - h * s) / 2, w: w * s, h: h * s, scale: s };
  }

  /** A monitor: the biggest screen of the media's aspect whose frame (screen plus the bezel all round) fits the area, centred in it.
   *  The bezel is `bezelFraction` of the screen's width. Everything in the area's CSS px. */
  function monitorLayout(area, mw, mh, bezelFraction) {
    const aspect = mh / mw, f = bezelFraction;
    const screenW = Math.max(1, Math.min(area.width / (1 + 2 * f), area.height / (aspect + 2 * f)));
    const screenH = screenW * aspect, bezel = f * screenW;
    const frame = { w: screenW + 2 * bezel, h: screenH + 2 * bezel };
    frame.x = area.left + (area.width - frame.w) / 2;
    frame.y = area.top + (area.height - frame.h) / 2;
    return { frame, screen: { x: frame.x + bezel, y: frame.y + bezel, w: screenW, h: screenH }, bezel };
  }

  /** The picture's rectangle (container px) when it COVERS the area centred on `focus` (0..1, 0..1) and carries on past it.
   *  `zoom` >= 1 scales about the focus point; `pan` (-1..1 each) moves the picture by that share of the margin it has on the side
   *  that would be uncovered (at most `maxPanPx` pixels of it), so the area stays covered whatever the zoom and pan.
   *  `rest`: a rectangle {x, y, w, h} the picture already has at rest (placed by the look); `area` is then only what must stay covered. */
  function coverRect(area, mw, mh, focus, zoom, pan, maxPanPx, rest) {
    const fx = focus ? focus[0] : 0.5, fy = focus ? focus[1] : 0.5;
    const base = rest ? rest.w / mw : Math.max(area.width / mw, area.height / mh);
    const w0 = rest ? rest.w : mw * base, h0 = rest ? rest.h : mh * base;
    const x0 = rest ? rest.x : clamp(area.left + area.width / 2 - fx * w0, area.left + area.width - w0, area.left);
    const y0 = rest ? rest.y : clamp(area.top + area.height / 2 - fy * h0, area.top + area.height - h0, area.top);
    const z = zoom > 1 ? zoom : 1;
    const w = w0 * z, h = h0 * z;
    let x = x0 + fx * w0 - fx * w, y = y0 + fy * h0 - fy * h;
    if (pan) {
      const cap = finite(maxPanPx) ? Math.max(0, maxPanPx) : Infinity;
      const gx = clamp(pan[0], -1, 1), gy = clamp(pan[1], -1, 1);
      x += gx > 0 ? gx * Math.min(cap, Math.max(0, area.left - x)) : gx * Math.min(cap, Math.max(0, x + w - (area.left + area.width)));
      y += gy > 0 ? gy * Math.min(cap, Math.max(0, area.top - y)) : gy * Math.min(cap, Math.max(0, y + h - (area.top + area.height)));
    }
    return { x, y, w, h, scale: base * z };
  }

  /** Slow camera drift: zoom 1..1+zoom and a pan that follows it, a cosine ping-pong (zero speed at both ends, no abrupt turn). */
  const DRIFT = { period: 120, zoom: 0.03, pan: 0.7, panPx: 12 };
  function driftState(seconds, config, dir) {
    const c = config || DRIFT, d = dir || [1, 0.6];
    const p = 0.5 - 0.5 * Math.cos(TAU * seconds / c.period);
    return { p, zoom: 1 + c.zoom * p, pan: [d[0] * c.pan * p, d[1] * c.pan * p] };
  }
  function driftDirection(name) {
    const h = hashString(String(name || ''));
    return [h & 1 ? 1 : -1, h & 2 ? 0.6 : -0.6];
  }

  /** How many rows (and columns) of the SOURCE picture a pixel scene has. The board's frames arrive doubled or tripled by nearest
   *  neighbour, and not every one is 4:3 (Versus is 640x398: 320x199): take the whole-number division of the media whose height is nearest
   *  to 240 rows within 100..300. An explicit `rows` wins. Nothing fits: 240 rows and smooth sampling (`native: false`). */
  function sourceGrid(mediaW, mediaH, override) {
    if (finite(override) && override >= 8 && override <= mediaH) {
      const scale = mediaH / override;
      return { rows: Math.round(override), cols: Math.max(1, Math.round(mediaW / scale)), scale, native: true };
    }
    let best = null;
    for (let k = 1; k <= 8; k++) {
      if (mediaW % k || mediaH % k) continue;
      const rows = mediaH / k;
      if (rows < 100 || rows > 300) continue;
      const distance = Math.abs(rows - 240);
      if (!best || distance < best.distance) best = { k, rows, distance };
    }
    if (best) return { rows: best.rows, cols: mediaW / best.k, scale: best.k, native: true };
    return { rows: 240, cols: Math.max(1, Math.round(mediaW * 240 / mediaH)), scale: mediaH / 240, native: false };
  }

  /** The next quality level down or up, skipping levels that would look the same at this device pixel ratio. */
  function stepLevel(level, direction, dpr, banned) {
    const effective = (l) => Math.min(dpr, LEVELS[l].dprCap) + '|' + LEVELS[l].low;
    const delta = direction === 'down' ? 1 : -1;
    for (let l = level + delta; l >= 0 && l < LEVELS.length; l += delta) {
      if (effective(l) === effective(level)) continue;
      if (delta < 0 && banned && banned.has(l)) return null;
      return l;
    }
    return null;
  }

  function parseFx(search) {
    const m = /[?&]fx=([a-z]+)/.exec(search || '');
    const v = m ? m[1] : '';
    return { off: v === 'off', css: v === 'css', quality: v === 'low' ? 'low' : v === 'high' ? 'high' : null };
  }

  /** The server's `info` entry, checked again: same-origin URLs only, a known look, numbers in range. Null when unusable. */
  function localUrl(url, origin) {
    if (typeof url !== 'string' || !url || url.length > 512 || /[\u0000-\u001f\s]/.test(url) || url.startsWith('//')) return null;
    if (url.startsWith('/')) return url;
    try {
      const u = new URL(url, origin || undefined);
      return origin && u.origin === origin ? u.pathname + u.search : null;
    } catch (_) { return null; }
  }
  function normalizeInfo(raw, origin) {
    if (!raw || typeof raw !== 'object' || !raw.media || typeof raw.media !== 'object') return null;
    const revision = typeof raw.resourceRevision === 'string' && /^[a-f0-9]{64}$/.test(raw.resourceRevision) ? raw.resourceRevision : '';
    const resource = value => {
      const local = localUrl(value, origin);
      if (!local || !revision) return local;
      const path = local.split('#', 1)[0], question = path.indexOf('?');
      const params = new URLSearchParams(question < 0 ? '' : path.slice(question + 1));
      params.set('adrev', revision);
      return (question < 0 ? path : path.slice(0, question)) + '?' + params.toString();
    };
    const url = resource(raw.media.url);
    if (!url) return null;
    const media = {
      kind: raw.media.kind === 'video' ? 'video' : 'image', url,
      width: finite(raw.media.width) ? clamp(raw.media.width, 16, 8192) : 640,
      height: finite(raw.media.height) ? clamp(raw.media.height, 16, 8192) : 480,
    };
    if (finite(raw.media.fps)) media.fps = clamp(raw.media.fps, 1, 120);
    if (finite(raw.media.loop_seconds)) media.loopSeconds = clamp(raw.media.loop_seconds, 0.1, 600);
    if (finite(raw.media.rows)) media.rows = raw.media.rows;
    const focus = Array.isArray(raw.focus) && raw.focus.length === 2 && raw.focus.every(finite) ? [clamp(raw.focus[0], 0, 1), clamp(raw.focus[1], 0, 1)] : [0.5, 0.5];
    const info = {
      name: String(raw.name || '').toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 40),
      look: ['crt', 'lcd', 'photo', 'plain'].includes(raw.look) ? raw.look : 'plain',
      media, still: resource(raw.still), focus, rate: finite(raw.rate) ? clamp(raw.rate, 0.25, 2) : 1,
    };
    // the optional `live` block (token_tv/tablet_live.py checks it on the server): checked once more by stage-live.js; without that file it is dropped
    const liveApi = global.SceneStageLive;
    // This old id now belongs to the mountain house; never inherit the
    // previous cyberpunk scene's rain or aircraft, even from a stale catalog.
    const mountainHouse = /^neon-district(?:-(?:dawn|day|dusk|night))?$/.test(info.name);
    if (raw.live && liveApi && typeof liveApi.normalizeLive === 'function') {
      const live = liveApi.normalizeLive(mountainHouse ? {wildlife: raw.live.wildlife} : raw.live);
      // An already-running older server drops the two new size/count fields. Keep the new Paradise preset working
      // after a page refresh; a restarted server sends the explicit values and takes precedence.
      const water = raw.live.water;
      if (info.name === 'paradise' && live && live.water && water) {
        if (water.glint_size === undefined) live.water.glint_size = 0.38;
        if (water.glint_density === undefined && water.glints === 0.8) live.water.glint_density = 0.35;
        if (water.glint_density === undefined && water.glints === 1.3) live.water.glint_density = 0.55;
      }
      if (live) {
        if (live.wildlife) live.wildlife = resource(live.wildlife);
        info.live = live;
      }
    }
    return info;
  }

  /** Quality governor: feeds on frames, answers 'down' after sustained lateness and 'up' after a long clean spell. Pure logic. */
  class Governor {
    constructor(options) {
      this.o = Object.assign({}, GOVERNOR, options || {});
      this.banned = new Set();
      this.trial = null;
      this.ups = 0;
      this.reset(0, 0);
    }
    reset(now, extraHold) {
      this.samples = [];
      this.holdUntil = now + this.o.holdMs + (extraHold || 0);
      this.total = 0; this.lateTotal = 0; this.stableSince = null;
    }
    push(now, late, expectedMs, level) {
      if (now < this.holdUntil) return null;
      if (this.stableSince === null) this.stableSince = now;
      this.total++; if (late) this.lateTotal++;
      const s = this.samples;
      s.push({ t: now, late });
      while (s.length && now - s[0].t > this.o.windowMs) s.shift();
      if (now - s[0].t >= this.o.windowMs * 0.75 && s.length >= this.o.minSamples) {
        let n = 0; for (const x of s) if (x.late) n++;
        if (n / s.length >= this.o.lateFraction) return 'down';
      }
      if (level > 0 && this.ups < this.o.maxUps && now - this.stableSince >= this.o.upAfterMs && this.lateTotal / this.total <= this.o.upMaxLate && !this.banned.has(level - 1)) return 'up';
      return null;
    }
    /** The caller applied a step; `level` is the level it moved to. */
    stepped(direction, now, level) {
      if (direction === 'down' && this.trial && now - this.trial.at < this.o.trialMs) this.banned.add(this.trial.level);
      this.trial = direction === 'up' ? { level, at: now } : null;
      if (direction === 'up') this.ups++;
      this.reset(now, direction === 'down' ? this.o.cooldownMs : 0);
    }
  }

  /* ------------------------------------------------------------------------------------------------ DOM helpers */

  function el(tag, style, attrs) {
    const node = document.createElement(tag);
    if (style) Object.assign(node.style, style);
    if (attrs) for (const k of Object.keys(attrs)) node.setAttribute(k, attrs[k]);
    return node;
  }
  const px = (n) => (Math.round(n * 100) / 100) + 'px';
  const FILL = { position: 'absolute', left: '0px', top: '0px', width: '100%', height: '100%', pointerEvents: 'none' };
  const nowMs = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

  /** The page's own background colour, so a picture that ends inside the container fades into it. */
  function readBase(node) {
    try {
      for (let n = node; n && n.nodeType === 1; n = n.parentElement) {
        const m = /rgba?\((\d+)[ ,]+(\d+)[ ,]+(\d+)(?:[ ,/]+([\d.]+))?/.exec(getComputedStyle(n).backgroundColor || '');
        if (m && (m[4] === undefined || parseFloat(m[4]) > 0.9)) return [+m[1], +m[2], +m[3]];
      }
    } catch (_) { /* detached or hostile environment */ }
    return BASE_FALLBACK;
  }

  /* ------------------------------------------------------------------------------------------------ WebGL kit */

  const VERTEX = 'attribute vec2 aPos;\nvoid main() { gl_Position = vec4(aPos, 0.0, 1.0); }\n';
  const FRAG_HEAD = '#ifdef GL_FRAGMENT_PRECISION_HIGH\nprecision highp float;\n#else\nprecision mediump float;\n#endif\n';
  const GLSL_LIB = [
    'float sdRoundBox(vec2 p, vec2 b, float r) { vec2 q = abs(p) - b + vec2(r); return min(max(q.x, q.y), 0.0) + length(max(q, vec2(0.0))) - r; }',
    'vec2 gradRoundBox(vec2 p, vec2 b, float r) { vec2 q = abs(p) - b + vec2(r); vec2 s = vec2(p.x < 0.0 ? -1.0 : 1.0, p.y < 0.0 ? -1.0 : 1.0);',
    '  if (q.x > 0.0 && q.y > 0.0) return s * normalize(q); return q.x > q.y ? vec2(s.x, 0.0) : vec2(0.0, s.y); }',
    'vec3 toLin(vec3 c) { return c * c; }',
    'vec3 fromLin(vec3 c) { return sqrt(max(c, vec3(0.0))); }',
    'float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }',
    '',
  ].join('\n');

  function mulberry32(seed) {
    let a = seed >>> 0;
    return () => { a = (a + 0x6D2B79F5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }

  /** A tileable 256x256 RGBA noise: R and G smooth fields (haze, light phases), B and A white noise (grain, dither). */
  function noiseData(size, seed) {
    const rnd = mulberry32(seed), out = new Uint8Array(size * size * 4);
    const field = (cells) => {
      const lat = new Float32Array(cells * cells);
      for (let i = 0; i < lat.length; i++) lat[i] = rnd();
      const f = new Float32Array(size * size);
      for (let y = 0; y < size; y++) {
        const fy = y / size * cells, y0 = Math.floor(fy), ty = smoothstep(0, 1, fy - y0), y1 = (y0 + 1) % cells;
        for (let x = 0; x < size; x++) {
          const fx = x / size * cells, x0 = Math.floor(fx), tx = smoothstep(0, 1, fx - x0), x1 = (x0 + 1) % cells;
          f[y * size + x] = mix(mix(lat[y0 * cells + x0], lat[y0 * cells + x1], tx), mix(lat[y1 * cells + x0], lat[y1 * cells + x1], tx), ty);
        }
      }
      return f;
    };
    for (let channel = 0; channel < 2; channel++) {
      const a = field(8), b = field(16), c = field(32);
      let lo = 1, hi = 0; const v = new Float32Array(size * size);
      for (let i = 0; i < v.length; i++) { v[i] = a[i] * 0.55 + b[i] * 0.3 + c[i] * 0.15; lo = Math.min(lo, v[i]); hi = Math.max(hi, v[i]); }
      for (let i = 0; i < v.length; i++) out[i * 4 + channel] = Math.round(255 * (v[i] - lo) / (hi - lo));
    }
    for (let i = 0; i < size * size; i++) { out[i * 4 + 2] = Math.floor(rnd() * 256); out[i * 4 + 3] = Math.floor(rnd() * 256); }
    return out;
  }

  const kit = {
    math: { clamp, mix, smoothstep, containRect, monitorLayout, coverRect, driftState, driftDirection, sourceGrid, hashString },
    glsl: { vertex: VERTEX, head: FRAG_HEAD, lib: GLSL_LIB },
    el, px,

    /** One-off per-context state: the shared full-screen quad on attribute 0, a shared noise texture. */
    initContext(gl) {
      if (gl.__stage) return gl.__stage;
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      gl.disable(gl.BLEND); gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.disable(gl.DITHER);
      const noise = this.texture(gl, { filter: gl.LINEAR, wrap: gl.REPEAT });
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 256, 0, gl.RGBA, gl.UNSIGNED_BYTE, noiseData(256, 20261109));
      gl.__stage = { buffer, noise };
      return gl.__stage;
    },
    noise(gl) { return this.initContext(gl).noise; },

    /** A program from a fragment body (the shared precision head is added) and, optionally, its own vertex shader (attribute 0 is `aPos`, the shared quad) and the
     *  names of further attributes, bound to 1, 2, ... in that order. */
    program(gl, fragmentBody, vertexBody, extraAttributes) {
      const compile = (type, source) => {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source); gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
          const log = gl.getShaderInfoLog(shader) || 'compile failed';
          gl.deleteShader(shader);
          throw new Error(log.slice(0, 300));
        }
        return shader;
      };
      const vs = compile(gl.VERTEX_SHADER, vertexBody || VERTEX), fs = compile(gl.FRAGMENT_SHADER, FRAG_HEAD + fragmentBody);
      const handle = gl.createProgram();
      gl.attachShader(handle, vs); gl.attachShader(handle, fs);
      gl.bindAttribLocation(handle, 0, 'aPos');
      (extraAttributes || []).forEach((name, i) => gl.bindAttribLocation(handle, i + 1, name));
      gl.linkProgram(handle);
      gl.deleteShader(vs); gl.deleteShader(fs);
      if (!gl.getProgramParameter(handle, gl.LINK_STATUS)) { const log = gl.getProgramInfoLog(handle) || 'link failed'; gl.deleteProgram(handle); throw new Error(log.slice(0, 300)); }
      const locations = {};
      const loc = (name) => (name in locations ? locations[name] : (locations[name] = gl.getUniformLocation(handle, name)));
      return {
        handle,
        use() { gl.useProgram(handle); return this; },
        f1(n, a) { gl.uniform1f(loc(n), a); return this; },
        f2(n, a, b) { gl.uniform2f(loc(n), a, b); return this; },
        f3(n, a, b, c) { gl.uniform3f(loc(n), a, b, c); return this; },
        f4(n, a, b, c, d) { gl.uniform4f(loc(n), a, b, c, d); return this; },
        fv4(n, array) { gl.uniform4fv(loc(n), array); return this; },       // a whole `uniform vec4 name[N]` from a Float32Array of 4N numbers
        i1(n, a) { gl.uniform1i(loc(n), a); return this; },
        dispose() { gl.deleteProgram(handle); },
      };
    },

    texture(gl, options) {
      const o = options || {}, t = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, o.filter || gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, o.filter || gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, o.wrap || gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, o.wrap || gl.CLAMP_TO_EDGE);
      return t;
    },

    /** A render target: RGBA 8-bit texture plus framebuffer. */
    target(gl, w, h) {
      const tex = this.texture(gl);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      const fbo = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      if (!ok) { gl.deleteFramebuffer(fbo); gl.deleteTexture(tex); throw new Error('framebuffer incomplete'); }
      return { tex, fbo, w, h, bind() { gl.bindFramebuffer(gl.FRAMEBUFFER, fbo); gl.viewport(0, 0, w, h); },
        dispose() { gl.deleteFramebuffer(fbo); gl.deleteTexture(tex); } };
    },

    bindTexture(gl, unit, tex) { gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, tex); },
    draw(gl) { gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); },
    toCanvas(gl, frame) { gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, frame.width, frame.height); },
  };

  const maxTexture = (gl) => gl.getParameter(gl.MAX_TEXTURE_SIZE) || 2048;
  const floorPot = (n) => { let p = 1; while (p * 2 <= n) p *= 2; return p; };

  /** A still picture as a plain texture (shrunk once if it is larger than the GPU's texture limit). */
  function uploadPlain(gl, image) {
    const w = image.naturalWidth || image.width, h = image.naturalHeight || image.height, limit = maxTexture(gl);
    let source = image, tw = w, th = h, canvas = null;
    if (Math.max(w, h) > limit) {
      const k = limit / Math.max(w, h);
      tw = Math.max(1, Math.floor(w * k)); th = Math.max(1, Math.floor(h * k));
      canvas = document.createElement('canvas'); canvas.width = tw; canvas.height = th;
      const c2d = canvas.getContext('2d', { alpha: false });
      c2d.imageSmoothingEnabled = true; c2d.imageSmoothingQuality = 'high';
      c2d.drawImage(image, 0, 0, tw, th);
      source = canvas;
    }
    const tex = kit.texture(gl);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
    if (canvas) canvas.width = canvas.height = 0;
    return { kind: 'image', tex, w, h, texW: tw, texH: th, uvScale: [1, 1], textures: [tex] };
  }

  /** A still picture as a mip-mapped power-of-two texture (WebGL 1 cannot mip-map any other size), shrunk once if very large, with the
   *  padding filled by the picture's own last row and column so no dark edge bleeds into the smaller mip levels. */
  function uploadMipmapped(gl, image, maxSide) {
    const w = image.naturalWidth || image.width, h = image.naturalHeight || image.height;
    maxSide = Math.min(maxSide, floorPot(maxTexture(gl)));
    const shrink = Math.min(1, maxSide / Math.max(w, h));
    const sw = Math.max(1, Math.round(w * shrink)), sh = Math.max(1, Math.round(h * shrink));
    const pot = (n) => { let p = 1; while (p < n) p *= 2; return p; };
    const tw = pot(sw), th = pot(sh);
    const canvas = document.createElement('canvas');
    canvas.width = tw; canvas.height = th;
    const c2d = canvas.getContext('2d', { alpha: false });
    c2d.imageSmoothingEnabled = true; c2d.imageSmoothingQuality = 'high';
    c2d.drawImage(image, 0, 0, sw, sh);
    if (tw > sw) c2d.drawImage(canvas, sw - 1, 0, 1, sh, sw, 0, tw - sw, sh);
    if (th > sh) c2d.drawImage(canvas, 0, sh - 1, tw, 1, 0, sh, tw, th - sh);
    const tex = kit.texture(gl);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.generateMipmap(gl.TEXTURE_2D);
    const aniso = gl.getExtension('EXT_texture_filter_anisotropic');
    if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(4, gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT) || 1));
    canvas.width = canvas.height = 0;
    return { kind: 'image', tex, w, h, texW: tw, texH: th, uvScale: [sw / tw, sh / th], textures: [tex] };
  }

  /* ------------------------------------------------------------------------------------------------ the built-in plain look */

  const PLAIN = {
    name: 'plain',
    opaque: true,
    layout(ctx) {
      const area = ctx.area;
      const picture = coverRect(area, ctx.media.w, ctx.media.h, ctx.info.focus, 1, null);
      return { canvas: { x: 0, y: 0, w: ctx.container.w, h: ctx.container.h }, picture, container: ctx.container };
    },
    css(L, info, node) {
      return { below: [], above: edgeFades(L, node), pixelated: false };
    },
  };

  /** CSS-only fade into the page background where a covering picture ends inside the container (the picture never stretches). */
  function edgeFades(L, node) {
    const out = [], p = L.picture, c = L.container, len = Math.max(40, Math.round(Math.min(c.w, c.h) * 0.12));
    const rgb = (L.base || BASE_FALLBACK).join(',');
    if (p.y + p.h < c.h - 1) {
      const top = Math.max(0, p.y + p.h - len);
      out.push(node('div', { position: 'absolute', left: '0px', width: '100%', top: px(top), height: px(c.h - top), pointerEvents: 'none',
        background: 'linear-gradient(to bottom, rgba(' + rgb + ',0) 0px, rgb(' + rgb + ') ' + px(p.y + p.h - top) + ')' }));
    }
    return out;
  }

  /* ------------------------------------------------------------------------------------------------ one scene */

  class Slot {
    constructor(stage, info) {
      this.stage = stage; this.info = info;
      this.def = stage.lookDef(info.look);
      this.look = this.def ? this.def.name : 'plain';
      this.mode = 'plain';
      // not quite 0: a fully transparent subtree may be skipped by the compositor, and with it the frames of the video that feeds the texture
      this.root = el('div', Object.assign({}, FILL, { opacity: '0.001', overflow: 'hidden', contain: 'layout paint' }), { 'aria-hidden': 'true' });
      this.source = null; this.video = null; this.still = null; this.videoPromise = null; this.stillPromise = null;
      this.ready = false; this.destroyed = false; this.frozen = false; this.blocked = false; this.error = null; this.videoFailed = false;
      this.layout = null; this.gl = null; this.canvas = null; this.renderer = null; this.lost = false;
      this.texMeta = null; this.textures = []; this.cur = 0; this.sourceDirty = false;
      this.dirty = true; this.frameDirty = false; this.pollMode = false; this.cbHandle = 0; this.lastCb = 0; this.lastTime = -1;
      this.stamps = []; this.lateCount = 0; this.clock = 0; this.lastRender = 0; this.lastDraw = 0; this.frameIndex = 0; this.pxScale = 1;
      this.cssLayer = null; this.cssMedia = null; this.fadeTimer = 0; this.dropBase = 0; this.videoFrames = [0, 0];
      this.bank = null; this.pokeClock = null; this.liveF = { on: false, cfg: null, q: 1, pokes: NO_POKES, readings: null, readingsAge: Infinity }; this.problemSeen = '';
      // the frame interval the governor judges lateness against: the manifest's own rate when it gives one, else the shortest gap seen between frames
      this.expectedFixed = finite(info.media.fps);
      this.expected = this.expectedFixed ? clamp(1000 / (info.media.fps * info.rate), 8, 1000) : STILL_INTERVAL;
      this.onFrameBound = (n, m) => this.onFrame(n, m);
    }

    /* ---- setup */
    init() {
      const s = this.stage;
      if (s.fx.off || !this.def || this.def.name === 'plain') this.mode = 'plain';
      else if (s.cssOnly || s.fx.css) this.mode = 'css';
      else this.mode = this.initGL() ? 'webgl' : 'css';
      if (this.mode !== 'webgl') this.buildCss();
      s.root.appendChild(this.root);
    }

    initGL() {
      const canvas = el('canvas', { position: 'absolute', display: 'block', pointerEvents: 'none' });
      let gl = null;
      try {
        const attrs = { alpha: !this.def.opaque, antialias: false, depth: false, stencil: false, premultipliedAlpha: true, preserveDrawingBuffer: false, powerPreference: 'default', failIfMajorPerformanceCaveat: false };
        gl = canvas.getContext('webgl', attrs) || canvas.getContext('experimental-webgl', attrs);
      } catch (_) { gl = null; }
      if (!gl) { this.error = 'no WebGL'; return false; }
      this.canvas = canvas; this.gl = gl;
      this.loseExt = gl.getExtension('WEBGL_lose_context');          // kept: a lost context no longer hands out extensions
      canvas.addEventListener('webglcontextlost', (e) => this.onContextLost(e), false);
      canvas.addEventListener('webglcontextrestored', () => this.onContextRestored(), false);
      this.root.appendChild(canvas);
      // The video that feeds the texture stays IN the document, in a 1 px, almost transparent box: some mobile browsers do not refresh the
      // frames of a video that is not attached (and not painted), and a fully transparent one may be skipped by the compositor.
      this.videoHost = el('div', { position: 'absolute', left: '0px', top: '0px', width: '1px', height: '1px', overflow: 'hidden', opacity: '0.01', pointerEvents: 'none' });
      this.root.appendChild(this.videoHost);
      try { this.buildRenderer(); } catch (e) {
        this.error = 'shader: ' + (e && e.message || e);
        this.root.removeChild(canvas); this.canvas = this.gl = null;
        return false;
      }
      const info = gl.getExtension('WEBGL_debug_renderer_info');
      this.stage.gpu = String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)).slice(0, 80);
      return true;
    }

    buildRenderer() {
      this.stage.kit.initContext(this.gl);
      this.renderer = this.def.create(this.gl, { kit: this.stage.kit, info: this.info });
      this.textures = []; this.texMeta = null; this.sourceDirty = true; this.dirty = true;
    }

    onContextLost(e) {
      e.preventDefault();
      if (this.destroyed) return;
      this.lost = true; this.stage.problem('WebGL context lost');
      this.setMode('css');
    }

    onContextRestored() {
      if (this.destroyed) return;
      this.lost = false;
      try {
        delete this.gl.__stage;
        this.buildRenderer();
        this.setMode('webgl');
        if (this.stage.errorText === 'WebGL context lost') this.stage.errorText = '';
        this.stage.note('WebGL context restored');
        this.stage.kick();
      } catch (e) { this.error = 'restore: ' + (e && e.message || e); }
    }

    /* ---- media */
    loadVideo() {
      if (this.videoPromise) return this.videoPromise;
      const v = document.createElement('video');
      Object.assign(v, { muted: true, defaultMuted: true, loop: true, playsInline: true, preload: 'auto', controls: false, tabIndex: -1,
        disablePictureInPicture: true, disableRemotePlayback: true });
      v.setAttribute('muted', ''); v.setAttribute('playsinline', ''); v.setAttribute('aria-hidden', 'true');
      v.defaultPlaybackRate = this.info.rate;
      this.video = v;
      v.addEventListener('loadedmetadata', () => { v.playbackRate = this.info.rate; });
      v.addEventListener('error', () => this.onVideoError());
      v.addEventListener('ended', () => { if (!this.destroyed) { v.currentTime = 0; this.play(); } });
      this.videoPromise = new Promise((resolve) => {
        let done = false, timer = 0;
        const finish = (ok) => { if (done) return; done = true; clearTimeout(timer); resolve(ok); };
        timer = setTimeout(() => finish(false), LOAD_TIMEOUT_MS);
        v.addEventListener('loadeddata', () => finish(true), { once: true });
        v.addEventListener('error', () => finish(false), { once: true });
        v.src = this.info.media.url;
        if (this.stage.running() && this.stage.motion) this.play();
      });
      return this.videoPromise;
    }

    loadStill(url) {
      if (this.stillPromise) return this.stillPromise;
      const img = new Image();
      img.decoding = 'async'; img.alt = ''; img.setAttribute('aria-hidden', 'true');
      this.still = img;
      this.stillPromise = new Promise((resolve) => {
        const timer = setTimeout(() => resolve(false), LOAD_TIMEOUT_MS);
        const finish = () => { clearTimeout(timer); resolve(img.naturalWidth > 0); };
        img.addEventListener('load', finish, { once: true });
        img.addEventListener('error', () => { clearTimeout(timer); resolve(false); }, { once: true });
        img.src = url;
      });
      return this.stillPromise;
    }

    play() {
      const v = this.video;
      if (!v || this.destroyed) return;
      let p;
      this.startedAt = nowMs();
      try { p = v.play(); } catch (_) { return; }
      if (p && typeof p.then === 'function') {
        p.then(() => { this.blocked = false; this.armFrameCallback(); this.stage.emit(); },
          (e) => this.onPlayRejected(e));
      }
    }

    onPlayRejected(e) {
      if (this.destroyed || (e && e.name === 'AbortError')) return;           // a new load or a pause interrupted it: not a refusal
      if (e && e.name !== 'NotAllowedError') { this.onVideoError(); return; }   // NotSupportedError and the like: this file cannot play at all
      this.blocked = true;
      this.stage.note('autoplay blocked: showing the still');
      if (this.info.still && this.source && this.source.kind === 'video') {
        this.loadStill(this.info.still).then((ok) => { if (ok && this.blocked && !this.destroyed) this.useSource('still'); });
      }
      this.stage.afterGesture(() => {
        if (this.destroyed || !this.video || !this.stage.motion) return;
        const p = this.video.play();
        if (p && p.then) p.then(() => { this.blocked = false; if (this.video.readyState >= 2) this.useSource('video'); }, () => {});
      });
      this.stage.emit();
    }

    onVideoError() {
      if (this.destroyed) return;
      this.error = 'video'; this.videoFailed = true;
      this.stage.problem('video error');
      this.cancelFrameCallback();
      if (this.source && this.source.kind === 'video' && this.info.still) {
        this.loadStill(this.info.still).then((ok) => { if (ok && !this.destroyed) this.useSource('still'); });
      }
      this.stage.emit();
    }

    /** Make the video or the still picture the thing that is shown. */
    useSource(kind) {
      const node = kind === 'video' ? this.video : this.still;
      if (!node) return;
      const w = kind === 'video' ? node.videoWidth : node.naturalWidth, h = kind === 'video' ? node.videoHeight : node.naturalHeight;
      if (!w || !h) return;
      const before = this.source;
      this.source = { kind: kind === 'video' ? 'video' : 'image', el: node, w, h };
      this.sourceDirty = true; this.dirty = true;
      if (this.mode !== 'webgl') this.mountMedia(); else this.mountHidden();
      if (!before || before.w !== w || before.h !== h) this.applyLayout();
      this.sync();
    }

    mountHidden() {
      const v = this.video;
      if (!this.videoHost || !v || v.parentNode === this.videoHost) return;
      Object.assign(v.style, { position: 'absolute', left: '0px', top: '0px', width: '1px', height: '1px', pointerEvents: 'none' });
      this.videoHost.appendChild(v);
    }

    mountMedia() {
      if (!this.cssMedia || !this.source) return;
      const node = this.source.el;
      for (const other of [this.video, this.still]) if (other && other !== node && other.parentNode === this.cssMedia) this.cssMedia.removeChild(other);
      if (node.parentNode !== this.cssMedia) {
        Object.assign(node.style, { position: 'absolute', left: '0px', top: '0px', width: '100%', height: '100%', objectFit: 'fill', display: 'block', pointerEvents: 'none' });
        this.cssMedia.appendChild(node);
        if (node === this.video && this.stage.running() && this.stage.motion) this.play();   // moving a video in the document pauses it
      }
    }

    async start() {
      const s = this.stage, info = this.info;
      this.init();
      let ok = false;
      if (info.media.kind === 'video') {
        if (!s.motion && info.still) {
          ok = await this.loadStill(info.still);
          if (ok && !this.destroyed) this.useSource('still');
        } else {
          ok = await this.loadVideo();
          if (this.destroyed) return false;
          if (ok) this.useSource('video');
          else if (info.still) { ok = await this.loadStill(info.still); if (ok && !this.destroyed) this.useSource('still'); }
        }
      } else {
        ok = await this.loadStill(info.media.url);
        if (ok && !this.destroyed) this.useSource('still');
      }
      if (!ok || this.destroyed || !this.source) return false;
      this.applyLayout();
      if (this.mode === 'webgl' && !this.renderNow(nowMs(), false)) this.setMode('css');
      this.ready = true;
      this.sync();
      return true;
    }

    /** React to the stage's motion switch: still picture or animated source. */
    applyMotion() {
      if (this.destroyed) return;
      const s = this.stage;
      if (this.info.media.kind !== 'video') { this.dirty = true; this.sync(); return; }
      if (s.motion) {
        if (this.video && this.video.readyState >= 2) this.useSource('video');
        else this.loadVideo().then((ok) => { if (ok && !this.destroyed && s.motion) this.useSource('video'); });
      } else if (this.info.still) {
        this.loadStill(this.info.still).then((ok) => { if (ok && !this.destroyed && !s.motion) this.useSource('still'); });
        this.sync();
      } else {
        this.sync();
        if (this.video) { try { this.video.currentTime = 0; } catch (_) { /* not seekable yet */ } this.video.addEventListener('seeked', () => { this.frameDirty = true; this.dirty = true; this.stage.kick(); }, { once: true }); }
      }
    }

    /** Align playback and loops with the stage's state (running, motion). */
    sync() {
      if (this.destroyed || this.frozen) return;
      const s = this.stage, run = s.running();
      const play = run && s.motion && this.source && this.source.kind === 'video' && !this.videoFailed;
      if (this.video) {
        if (play) { if (this.video.paused) this.play(); } else if (!this.video.paused) this.video.pause();
      }
      if (play) this.armFrameCallback(); else this.cancelFrameCallback();
      if (run) s.kick();
    }

    /* ---- frames */
    armFrameCallback() {
      const v = this.video;
      if (!v || this.cbHandle || this.pollMode || this.mode !== 'webgl' || typeof v.requestVideoFrameCallback !== 'function') return;
      this.cbHandle = v.requestVideoFrameCallback(this.onFrameBound);
    }

    cancelFrameCallback() {
      if (this.cbHandle && this.video && typeof this.video.cancelVideoFrameCallback === 'function') this.video.cancelVideoFrameCallback(this.cbHandle);
      this.cbHandle = 0;
    }

    onFrame(_now, meta) {
      this.cbHandle = 0;
      if (this.destroyed || this.frozen || this.mode !== 'webgl') return;
      const t = nowMs();
      this.lastCb = t;
      if (meta && finite(meta.mediaTime)) {
        const gap = Math.abs(meta.mediaTime - this.lastMediaTime);
        if (!this.expectedFixed && this.lastMediaTime !== undefined && gap > 0 && gap < 0.5) {
          this.minGap = Math.min(this.minGap || Infinity, gap);
          this.expected = clamp(this.minGap * 1000 / this.info.rate, 8, 400);
        }
        this.lastMediaTime = meta.mediaTime;
      }
      this.frameDirty = true;
      // a film that is also redrawn every animation frame (live effects, a touch in flight) is drawn by the tick, with this frame already marked new
      if (this.stage.running() && this.stage.motion && this.source && this.source.kind === 'video' && !this.liveVideoLoop() && !this.pokeAlive()) this.renderNow(t, true);
      this.armFrameCallback();
    }

    /** The scene is leaving: it keeps its last picture on screen, and stops drawing and playing so the newcomer has the GPU to itself. */
    freeze() {
      this.frozen = true;
      this.cancelFrameCallback();
      if (this.video && !this.video.paused) { try { this.video.pause(); } catch (_) { /* gone */ } }
    }

    needsTick() {
      if (this.destroyed || this.frozen || this.mode !== 'webgl' || !this.source || this.lost) return false;
      return this.dirty || this.wantsLoop() || this.pollingVideo() || this.liveVideoLoop() || this.pokeAlive();
    }
    /** Does this scene's look draw live effects right now (a `live` block, the stage's switch, motion, a tier that can afford them)? */
    liveOn() {
      const s = this.stage;
      if (this.mode !== 'webgl') return false;                                                        // the css and plain tiers draw nothing of it
      if (this.renderer && typeof this.renderer.liveBroken === 'function' && this.renderer.liveBroken()) return false;      // its shader failed: the classic pass draws alone
      return !!(this.def && this.def.live && this.info.live && this.def.live(this.info, { live: s.live, motion: s.motion, level: s.level }));
    }
    /** A still picture draws 30 times a second when it only drifts and twinkles; with live effects the tier sets the rate (30, 30, 24 and 20 frames a second). */
    stillInterval() { const live = global.SceneStageLive; return this.liveOn() && live && live.intervalFor ? live.intervalFor(this.stage.level) : this.stage.low() ? 1000 / 20 : STILL_INTERVAL; }
    wantsLoop() {
      const s = this.stage;
      if (!this.source || this.source.kind !== 'image' || !s.motion) return false;
      return this.liveOn() || !!(this.def.animated && this.def.animated(this.info, s.low()));
    }
    pollingVideo() {
      const s = this.stage;
      return !!(this.source && this.source.kind === 'video' && s.motion && this.video && !this.video.paused && (this.pollMode || typeof this.video.requestVideoFrameCallback !== 'function'));
    }
    /** A slow film (a few frames a second) with live effects on top: they get a loop of their own at the tier's rate. A film at 24 or more draws them with its frames. */
    liveVideoLoop() {
      return !!(this.source && this.source.kind === 'video' && this.video && !this.video.paused && this.mode === 'webgl' && this.liveOn() && (this.info.media.fps || 0) < LIVE_FILM_FPS);
    }
    pokeNow() { return this.pokeClock !== null ? this.pokeClock : nowMs() / 1000; }
    pokeAlive() { return !!(this.bank && this.bank.alive(this.pokeNow())); }

    /** A touch at (x, y) CSS px inside the stage's container. False when this scene does not answer to touch or it was too soon after the last one. */
    poke(x, y) {
      const live = global.SceneStageLive;
      if (this.destroyed || this.frozen || !this.ready || this.mode !== 'webgl' || this.lost || !this.renderer || typeof this.renderer.pokeKind !== 'function' || !live) return false;
      const a = this.layout && this.layout.area ? this.layout.area : this.stage.areaRect();
      if (!(x >= a.left && x <= a.left + a.width && y >= a.top && y <= a.top + a.height)) return false;      // a touch must land on the picture area the page gave the stage
      const kind = this.renderer.pokeKind({ info: this.info, layout: this.layout, x, y });
      if (!kind) return false;
      if (!this.bank) this.bank = new live.PokeBank();
      if (!this.bank.add(x, y, this.pokeNow(), kind)) return false;
      this.lastDraw = 0;                                      // the first frame of the touch starts at age zero, not after a long idle
      this.dirty = true;
      this.stage.kick();
      return true;
    }

    tick(now) {
      if (this.destroyed || this.frozen || this.mode !== 'webgl' || !this.source || this.lost) return false;
      const t = nowMs();
      if (this.pollingVideo() || this.liveVideoLoop()) {
        if (this.video.currentTime !== this.lastTime) { this.lastTime = this.video.currentTime; this.frameDirty = true; }
        if ((this.liveVideoLoop() && t - this.lastDraw >= this.stillInterval() - 3) || this.frameDirty || (this.pokeAlive() && t - this.lastDraw >= TOUCH_INTERVAL - 3)) this.renderNow(t, !this.pokeAlive());
        return true;
      }
      if (this.wantsLoop()) {
        if (t - this.lastDraw >= this.stillInterval() - 3) this.renderNow(t, !this.pokeAlive());
        return true;
      }
      if (this.pokeAlive()) { if (t - this.lastDraw >= TOUCH_INTERVAL - 3) this.renderNow(t, false); return true; }       // something that otherwise draws only when it changes, at 30 frames a second
      if (this.dirty) this.renderNow(t, false);
      return false;
    }

    /** Draw once. `sample`: this is a scheduled frame, so its timing feeds the governor. Returns false after a failure. */
    renderNow(t0, sample) {
      if (this.destroyed || this.mode !== 'webgl' || this.lost || !this.source || !this.renderer) return false;
      const s = this.stage, gl = this.gl;
      try {
        const fresh = this.dirty || this.frameDirty || this.sourceDirty;          // something the look draws has changed since its last frame (a touch alone does not count)
        if (this.sourceDirty || this.frameDirty) this.uploadSource();
        const dt = this.lastDraw ? Math.min(0.25, (t0 - this.lastDraw) / 1000) : 0;
        this.clock += dt * (this.source.kind === 'image' ? this.info.rate : 1);
        const level = s.level, c = this.canvas, lf = this.liveF;
        lf.on = this.liveOn(); lf.cfg = lf.on ? this.info.live : null; lf.q = level <= 1 ? 1 : 0;
        lf.pokes = this.bank ? this.bank.list(this.pokeNow()) : NO_POKES;
        lf.readings = s.readings; lf.readingsAge = s.readings ? t0 - s.readingsAt : Infinity;          // the quota for the effects that carry data (the lamps)
        this.renderer.draw({
          tex: this.textures.length ? this.textures[this.cur] : null, texPrev: this.def.history && this.textures.length > 1 ? this.textures[this.cur ^ 1] : null,
          mediaW: this.texMeta.w, mediaH: this.texMeta.h, texW: this.texMeta.texW, texH: this.texMeta.texH, uvScale: this.texMeta.uvScale,
          isVideo: this.source.kind === 'video', isStill: this.source.kind === 'image', info: this.info,
          time: this.clock, frameMs: this.source.kind === 'video' ? this.expected : 0, frameIndex: this.frameIndex++, width: c.width, height: c.height, scale: this.pxScale, layout: this.layout,
          level, low: LEVELS[level].low, motion: s.motion, base: s.base, tuning: s.tuning, live: lf, fresh,
        });
        if (gl.isContextLost()) throw new Error('context lost while drawing');
        const problem = this.renderer.problem ? this.renderer.problem() : '';
        if (problem && problem !== this.problemSeen) { this.problemSeen = problem; this.stage.note(problem); }
      } catch (e) {
        if (!this.lost) { this.error = 'draw: ' + (e && e.message || e); this.stage.problem(this.error); this.setMode('css'); }
        return false;
      }
      this.dirty = false; this.frameDirty = false;
      const t1 = nowMs(), gap = this.lastRender ? t0 - this.lastRender : 0;
      this.lastDraw = t0;
      this.stamps.push(t1); if (this.stamps.length > 90) this.stamps.shift();
      if (sample) {
        this.lastRender = t0;
        const expected = this.source.kind === 'video' ? (this.liveVideoLoop() ? this.stillInterval() : this.expected) : this.stillInterval();
        const late = gap > 0 && (gap > expected * 1.75 + 6) || (t1 - t0) > Math.max(14, expected * 0.8);
        if (late) this.lateCount++;
        if (gap > 0) s.sampleFrame(t1, late, expected);
      } else { this.lastRender = 0; }
      return true;
    }

    uploadSource() {
      const gl = this.gl, src = this.source, def = this.def;
      gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
      let changed = false;
      if (src.kind === 'image') {
        if (this.sourceDirty || !this.texMeta || this.texMeta.kind !== 'image') {
          this.releaseTextures();
          const meta = def.mipmapStills ? uploadMipmapped(gl, src.el, MAX_STILL_SIDE) : uploadPlain(gl, src.el);
          this.texMeta = meta; this.textures = meta.textures; this.cur = 0; changed = true;
        }
      } else {
        const v = src.el, w = v.videoWidth, h = v.videoHeight, m = this.texMeta;
        if (Math.max(w, h) > maxTexture(gl)) throw new Error('video larger than the GPU allows');
        if (!m || m.kind !== 'video' || m.w !== w || m.h !== h) {
          this.releaseTextures();
          const count = def.history ? 2 : 1;
          this.textures = [];
          for (let i = 0; i < count; i++) {
            const t = kit.texture(gl);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, v);
            this.textures.push(t);
          }
          this.texMeta = { kind: 'video', w, h, texW: w, texH: h, uvScale: [1, 1] };
          this.cur = 0; changed = true;
        } else {
          if (this.textures.length > 1) this.cur ^= 1;
          gl.bindTexture(gl.TEXTURE_2D, this.textures[this.cur]);
          gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, v);
        }
      }
      this.sourceDirty = false; this.frameDirty = false;
      if (changed && this.renderer.setSource) {
        this.renderer.setSource({ tex: this.textures[this.cur], w: this.texMeta.w, h: this.texMeta.h, texW: this.texMeta.texW, texH: this.texMeta.texH,
          uvScale: this.texMeta.uvScale, isVideo: src.kind === 'video', isStill: src.kind === 'image', info: this.info });
      }
    }

    releaseTextures() {
      if (this.gl && !this.gl.isContextLost()) for (const t of this.textures) this.gl.deleteTexture(t);
      this.textures = []; this.texMeta = null;
    }

    /* ---- geometry */
    sourceSize() { return this.source ? { w: this.source.w, h: this.source.h } : { w: this.info.media.width, h: this.info.media.height }; }

    shape() { return this.mode === 'plain' || !this.def ? PLAIN : this.def; }

    applyLayout() {
      if (this.destroyed) return;
      const s = this.stage, def = this.shape();
      const ctx = { info: this.info, area: s.areaRect(), container: s.containerSize(), media: this.sourceSize(), dpr: s.dpr, base: s.base };
      const L = def.layout(ctx);
      if (!L.container) L.container = ctx.container;
      if (!L.area) L.area = ctx.area;                              // every look's layout knows the area the page gave the stage (touch works from it, not from the look's own geometry)
      L.base = ctx.base;
      this.layout = L;
      if (this.mode === 'webgl') this.sizeCanvas(L); else this.placeCss(L);
      this.dirty = true;
    }

    sizeCanvas(L) {
      const c = L.canvas;
      let scale = this.stage.scale();
      const side = Math.max(c.w, c.h) * scale;
      if (side > MAX_CANVAS_SIDE) scale *= MAX_CANVAS_SIDE / side;
      if (c.w * c.h * scale * scale > MAX_CANVAS_PIXELS) scale = Math.sqrt(MAX_CANVAS_PIXELS / (c.w * c.h));
      const w = Math.max(1, Math.round(c.w * scale)), h = Math.max(1, Math.round(c.h * scale));
      Object.assign(this.canvas.style, { left: px(c.x), top: px(c.y), width: px(c.w), height: px(c.h) });
      if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
      this.pxScale = w / c.w;
    }

    buildCss() {
      if (this.cssLayer) { this.cssLayer.style.display = ''; return; }
      this.cssLayer = el('div', FILL);
      this.cssBelow = el('div', FILL); this.cssAbove = el('div', FILL);
      this.cssMedia = el('div', { position: 'absolute', overflow: 'hidden', pointerEvents: 'none' });
      this.cssLayer.append(this.cssBelow, this.cssMedia, this.cssAbove);
      this.root.appendChild(this.cssLayer);
      if (this.source) this.mountMedia();
    }

    placeCss(L) {
      if (!this.cssLayer) return;
      const def = this.shape(), box = L.screen || L.picture;
      Object.assign(this.cssMedia.style, { left: px(box.x), top: px(box.y), width: px(box.w), height: px(box.h), borderRadius: px(L.radius || 0) });
      const decor = (def.css ? def.css(L, this.info, el) : null) || { below: [], above: [] };
      this.cssBelow.replaceChildren(...(decor.below || []));
      this.cssAbove.replaceChildren(...(decor.above || []));
      for (const node of [this.video, this.still]) if (node) node.style.imageRendering = decor.pixelated ? 'pixelated' : 'auto';
    }

    /** Switch between the WebGL canvas and the CSS approximation (context lost, a failing shader, the governor's last step). */
    setMode(mode) {
      if (this.destroyed || this.mode === mode) return;
      this.mode = mode;
      if (mode === 'css') {
        this.cancelFrameCallback();
        if (this.canvas) this.canvas.style.display = 'none';
        this.buildCss();
        this.mountMedia();
      } else if (mode === 'webgl') {
        if (this.cssLayer) this.cssLayer.style.display = 'none';
        if (this.video && this.source && this.source.kind === 'video') { this.mountHidden(); if (this.stage.running() && this.stage.motion) this.play(); }
        this.canvas.style.display = '';
        this.sourceDirty = true;
      }
      this.applyLayout();
      this.sync();
      this.stage.emit();
    }

    /* ---- fading and teardown */
    fade(to, ms) {
      const st = this.root.style;
      clearTimeout(this.fadeTimer);
      if (ms <= 0) { st.transition = 'none'; st.opacity = String(to); st.willChange = ''; return; }
      st.willChange = 'opacity';
      st.transition = 'opacity ' + ms + 'ms cubic-bezier(.4,0,.2,1)';
      void this.root.offsetWidth;
      st.opacity = String(to);
      this.fadeTimer = setTimeout(() => { st.willChange = ''; }, ms + 60);
    }

    /** Testing aid: the average time of `frames` draws, each waited for with a one-pixel read. Software GL: only the ratio between tiers means anything. */
    benchmark(frames, withUpload) {
      if (this.mode !== 'webgl' || !this.gl || !this.source) return null;
      const gl = this.gl, probe = new Uint8Array(4);
      const t0 = nowMs();
      for (let i = 0; i < frames; i++) {
        if (withUpload && this.source.kind === 'video') this.frameDirty = true;
        this.dirty = true;
        if (!this.renderNow(nowMs(), false)) return null;
        gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, probe);
      }
      return (nowMs() - t0) / frames;
    }

    fpsEstimate() {
      const a = this.stamps;
      if (this.mode === 'webgl' && a.length > 2) {
        const recent = a.filter((t) => a[a.length - 1] - t <= 2000);
        if (recent.length > 2) return Math.round((recent.length - 1) * 10000 / (recent[recent.length - 1] - recent[0])) / 10;
      }
      return 0;
    }

    droppedFrames() {
      let n = this.lateCount;
      try { if (this.video && this.video.getVideoPlaybackQuality) n += this.video.getVideoPlaybackQuality().droppedVideoFrames || 0; } catch (_) { /* not available */ }
      return n;
    }

    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      clearTimeout(this.fadeTimer);
      this.cancelFrameCallback();
      if (this.video) { try { this.video.pause(); this.video.removeAttribute('src'); this.video.load(); } catch (_) { /* gone */ } }
      if (this.still) this.still.removeAttribute('src');
      if (this.gl) {
        try {
          if (this.renderer && this.renderer.dispose && !this.gl.isContextLost()) this.renderer.dispose();
          this.releaseTextures();
          if (this.loseExt) this.loseExt.loseContext();
        } catch (_) { /* context already gone */ }
      }
      if (this.canvas) { this.canvas.width = this.canvas.height = 0; }
      if (this.root.parentNode) this.root.parentNode.removeChild(this.root);
      this.gl = this.canvas = this.renderer = this.video = this.still = this.source = null;
    }
  }

  /* ------------------------------------------------------------------------------------------------ the stage */

  const registry = Object.create(null);
  const looks = Object.create(null);

  function register(name, factory) {
    if (typeof name === 'string' && typeof factory === 'function') { registry[name] = factory; delete looks[name]; }
  }

  function create(container, options) {
    const opts = options || {};
    const search = typeof opts.search === 'string' ? opts.search : (global.location && global.location.search) || '';
    const origin = (global.location && global.location.origin) || undefined;
    const fx = parseFx(search);
    if (opts.forceCss) fx.css = true;
    const governor = new Governor(opts.governor);

    if (global.getComputedStyle && global.getComputedStyle(container).position === 'static') container.style.position = 'relative';
    container.style.overflow = 'hidden';
    container.setAttribute('aria-hidden', 'true');
    const root = el('div', Object.assign({}, FILL, { overflow: 'hidden' }), { 'aria-hidden': 'true' });
    container.appendChild(root);

    const stage = {
      kit, root, fx, governor, origin,
      slots: [], current: null, pending: null, outgoing: null,
      area: null, motion: true, live: true, quality: fx.quality || 'auto', level: 0, cssOnly: false, paused: false, hidden: false, destroyed: false,
      dpr: 1, raf: 0, base: readBase(container), tuning: opts.tuning || {}, gpu: '', errorText: '', notes: [], lastSig: '', gestures: [], timers: [], readings: null, readingsAt: 0,
      running() { return !this.paused && !this.hidden && !this.destroyed; },
      low() { return LEVELS[this.level].low; },
      scale() { return Math.min(this.dpr, LEVELS[this.level].dprCap); },
      containerSize() { return { w: Math.max(1, container.clientWidth || 1), h: Math.max(1, container.clientHeight || 1) }; },
      areaRect() {
        const c = this.containerSize(), a = this.area;
        return a ? { left: a.left, top: a.top, width: a.width, height: a.height } : { left: 0, top: 0, width: c.w, height: c.h };
      },
      lookDef(name) {
        if (name === 'plain') return PLAIN;
        if (!looks[name] && registry[name]) { try { looks[name] = registry[name](kit); } catch (e) { stage.note('look ' + name + ': ' + (e && e.message || e)); } }
        return looks[name] || null;
      },
      note(text) { this.notes.push(text); if (this.notes.length > 12) this.notes.shift(); },
      problem(text) { this.errorText = text; this.note(text); },

      status() {
        const cur = this.current;
        const out = {
          renderer: cur ? cur.mode : 'plain', look: cur ? cur.look : null, scene: cur ? cur.info.name : null, ready: !!(cur && cur.ready),
          fps: cur ? cur.fpsEstimate() : 0, dropped: cur ? cur.droppedFrames() : 0,
          tier: cur && cur.mode === 'plain' ? 'plain' : this.cssOnly || (cur && cur.mode === 'css') ? 'css' : LEVELS[this.level].name, level: this.level, scale: cur && cur.mode === 'webgl' ? Math.round(cur.pxScale * 100) / 100 : 1,
          quality: this.quality, motion: this.motion, paused: !this.running(), video: !!(cur && cur.source && cur.source.kind === 'video'),
          live: this.live && !!cur && cur.liveOn(), liveEffects: cur && cur.info.live && global.SceneStageLive ? global.SceneStageLive.effectNames(cur.info.live) : [],
          pokes: cur && cur.bank ? cur.bank.items.length : 0,
          gpu: this.gpu,
          media: cur && cur.source ? [cur.source.w, cur.source.h] : null, canvas: cur && cur.canvas ? [cur.canvas.width, cur.canvas.height] : null,
          rows: cur && cur.layout && cur.layout.grid ? cur.layout.grid.rows : null,
          notes: this.notes.slice(-6),
        };
        const clip = cur && cur.video;                                  // [paused, readyState, seconds played, error code]: is the film really running?
        if (clip) out.clip = [clip.paused ? 1 : 0, clip.readyState, Math.round(clip.currentTime * 10) / 10, clip.error ? clip.error.code : 0];
        if (cur && cur.blocked) out.blocked = true;
        const error = this.errorText || (cur && cur.error);
        if (error) out.error = error;
        return out;
      },

      emit() {
        const s = this.status();
        const sig = [s.renderer, s.look, s.scene, s.ready, s.tier, s.paused, s.motion, s.quality, s.error || '', s.blocked || false, s.live].join('|');
        if (sig === this.lastSig) return;
        this.lastSig = sig;
        if (typeof opts.onStatus === 'function') { try { opts.onStatus(s); } catch (_) { /* the page's callback must not break the stage */ } }
      },

      /* ---- the scene */
      show(raw) {
        if (this.destroyed) return;
        const info = normalizeInfo(raw, origin);
        if (!info) { this.clear(); return; }
        const same = (slot) => slot && JSON.stringify(slot.info) === JSON.stringify(info);
        if (same(this.pending)) return;                                  // already on its way: do not start it over
        if (this.pending) { this.pending.destroy(); this.pending = null; }
        if (same(this.current)) return;
        if (this.outgoing) { this.outgoing.destroy(); this.outgoing = null; this.slots = this.slots.filter((x) => !x.destroyed); }
        this.errorText = '';
        const slot = new Slot(this, info);
        this.pending = slot; this.slots.push(slot);
        slot.start().then((ok) => {
          if (this.pending !== slot) return;
          this.pending = null;
          if (!ok || this.destroyed) {
            this.problem('scene "' + info.name + '" could not be shown' + (slot.error ? ' (' + slot.error + ')' : ''));
            slot.destroy(); this.slots = this.slots.filter((x) => !x.destroyed); this.emit();
            return;
          }
          this.promote(slot);
        }, () => { if (this.pending === slot) { this.pending = null; slot.destroy(); this.slots = this.slots.filter((x) => !x.destroyed); } });
      },

      promote(slot) {
        const old = this.current, ms = this.motion ? FADE_MS : 0;
        this.current = slot;
        if (old) old.freeze();
        slot.fade(1, old ? ms : Math.round(ms * 0.7));
        if (old) {
          // an opaque newcomer simply covers the old scene; anything with transparent corners has to fade the old one out with it
          const cover = slot.def ? slot.def.opaque : true;
          if (!cover) old.fade(0, ms);
          this.outgoing = old;
          this.timers.push(setTimeout(() => {
            if (this.outgoing === old) { old.destroy(); this.outgoing = null; this.slots = this.slots.filter((x) => !x.destroyed); this.kick(); }
          }, ms + 100));
        }
        this.governor.reset(nowMs(), 1000);
        this.kick(); this.emit();
      },

      clear() {
        if (this.pending) { this.pending.destroy(); this.pending = null; }
        const old = this.current;
        this.current = null;
        if (old) {
          old.freeze();
          old.fade(0, this.motion ? FADE_MS : 0);
          this.timers.push(setTimeout(() => { old.destroy(); this.slots = this.slots.filter((x) => !x.destroyed); }, FADE_MS + 100));
        }
        this.emit();
      },

      setArea(rect) {
        if (!rect || !['left', 'top', 'width', 'height'].every((k) => finite(rect[k])) || rect.width <= 0 || rect.height <= 0) { this.area = null; } else { this.area = { left: rect.left, top: rect.top, width: rect.width, height: rect.height }; }
        this.relayout();
      },

      setMotion(on) {
        const next = !!on;
        if (next === this.motion) return;
        this.motion = next;
        for (const s of this.slots) s.applyMotion();
        this.emit();
      },

      /** The extra effects of the `live` blocks and the answer to touch, on or off (default on): the scene stays, drawn as it was before them. */
      setLive(on) {
        const next = !!on;
        if (next === this.live) return;
        this.live = next;
        for (const s of this.slots) { if (!next && s.bank) s.bank.clear(); s.dirty = true; s.sync(); }
        this.kick(); this.emit();
      },

      /** The page's latest `/api/status` (or null when it stopped arriving): the effects that carry data (a scene's `lamps`) show the quota from it, and a reading the page has not
       *  renewed for 45 s counts as unknown. Nothing else in the stage reads it. */
      setReadings(latest) {
        this.readings = latest && typeof latest === 'object' ? latest : null;
        this.readingsAt = nowMs();
        const cur = this.current;
        if (cur && cur.info && cur.info.live && cur.info.live.lamps && cur.liveOn()) { cur.dirty = true; this.kick(); }
      },

      /** A touch at (x, y), CSS px in the page: the stage turns it into its container's own coordinates. Ignored when motion or live is off, the stage is paused or the scene has no answer. */
      poke(x, y) {
        if (this.destroyed || !this.running() || !this.motion || !this.live || !this.current || !finite(x) || !finite(y)) return false;
        let left = 0, top = 0;
        try { const r = container.getBoundingClientRect(); left = finite(r.left) ? r.left : 0; top = finite(r.top) ? r.top : 0; } catch (_) { /* no layout: the container is at the page's origin */ }
        return this.current.poke(x - left, y - top);
      },

      setQuality(q) {
        const next = fx.quality || (q === 'high' || q === 'low' ? q : 'auto');
        if (next === this.quality) return;
        this.quality = next;
        this.level = next === 'low' ? LEVELS.length - 1 : 0;
        this.cssOnly = false;
        this.governor.reset(nowMs(), 1000);
        this.relayout();
        for (const s of this.slots) if (s.mode === 'css' && s.gl && !s.lost && s.def) s.setMode('webgl');
        this.emit();
      },

      pause() { this.paused = true; this.syncRunning(); },
      resume() { this.paused = false; this.syncRunning(); },
      syncRunning() {
        if (this.destroyed) return;
        if (this.running()) { this.governor.reset(nowMs(), 800); for (const s of this.slots) { s.lastDraw = 0; s.lastRender = 0; } }
        else if (this.raf) { global.cancelAnimationFrame(this.raf); this.raf = 0; }
        for (const s of this.slots) s.sync();
        this.emit();
      },

      /* ---- layout and loops */
      relayout() {
        if (this.destroyed) return;
        this.dpr = clamp(global.devicePixelRatio || 1, 1, 4);
        for (const s of this.slots) s.applyLayout();
        this.kick();
      },

      scheduleRelayout() {
        if (this.relayoutTimer || this.destroyed) return;
        this.relayoutTimer = setTimeout(() => { this.relayoutTimer = 0; this.relayout(); }, 60);
      },

      kick() {
        if (this.raf || !this.running()) return;
        if (!this.slots.some((s) => s.needsTick())) return;
        this.raf = global.requestAnimationFrame((t) => this.tick(t));
      },

      tick(now) {
        this.raf = 0;
        if (!this.running()) return;
        let again = false;
        for (const s of this.slots) if (s.tick(now)) again = true;
        if (again) this.raf = global.requestAnimationFrame((t) => this.tick(t));
      },

      /** A scheduled frame's timing: the governor decides whether the tablet keeps up. */
      sampleFrame(t, late, expected) {
        if (this.quality !== 'auto' || this.cssOnly) return;
        const action = this.governor.push(t, late, expected, this.level);
        if (action === 'down') this.stepDown(t); else if (action === 'up') this.stepUp(t);
      },

      stepDown(t) {
        const next = stepLevel(this.level, 'down', this.dpr, this.governor.banned);
        if (next === null) {
          // even the lightest WebGL level is late: hand the video to the browser's own compositor
          this.cssOnly = true; this.note('GPU too slow: plain video with CSS overlays');
          this.governor.stepped('down', t, this.level);
          for (const s of this.slots) if (s.mode === 'webgl') s.setMode('css');
          this.emit();
          return;
        }
        this.level = next;
        this.governor.stepped('down', t, next);
        this.note('quality lowered to ' + LEVELS[next].name);
        for (const s of this.slots) if (s.mode === 'webgl') { s.applyLayout(); s.dirty = true; }
        this.kick(); this.emit();
      },

      stepUp(t) {
        const next = stepLevel(this.level, 'up', this.dpr, this.governor.banned);
        if (next === null) { this.governor.reset(t, 0); return; }
        this.level = next;
        this.governor.stepped('up', t, next);
        this.note('quality raised to ' + LEVELS[next].name);
        for (const s of this.slots) if (s.mode === 'webgl') { s.applyLayout(); s.dirty = true; }
        this.kick(); this.emit();
      },

      afterGesture(callback) {
        this.gestures.push(callback);
        if (this.gestureBound) return;
        this.gestureBound = true;
        const run = () => {
          for (const type of ['pointerdown', 'touchstart', 'keydown', 'click']) document.removeEventListener(type, run, true);
          this.gestureBound = false;
          const list = this.gestures; this.gestures = [];
          for (const f of list) { try { f(); } catch (_) { /* one failed retry must not stop the others */ } }
        };
        for (const type of ['pointerdown', 'touchstart', 'keydown', 'click']) document.addEventListener(type, run, { capture: true, passive: true });
      },

      destroy() {
        if (this.destroyed) return;
        this.destroyed = true;
        if (this.raf) global.cancelAnimationFrame(this.raf);
        this.timers.forEach(clearTimeout); clearTimeout(this.relayoutTimer); clearInterval(this.watchdog);
        for (const s of this.slots.slice()) s.destroy();
        this.slots = []; this.current = this.pending = this.outgoing = null;
        if (this.resizeObserver) this.resizeObserver.disconnect();
        global.removeEventListener('resize', this.onResize); global.removeEventListener('orientationchange', this.onResize);
        document.removeEventListener('visibilitychange', this.onVisibility);
        if (root.parentNode) root.parentNode.removeChild(root);
      },
    };

    stage.dpr = clamp(global.devicePixelRatio || 1, 1, 4);
    stage.hidden = typeof document !== 'undefined' && document.hidden === true;
    if (stage.quality === 'low') stage.level = LEVELS.length - 1;
    stage.onResize = () => stage.scheduleRelayout();
    stage.onVisibility = () => { stage.hidden = document.hidden === true; stage.syncRunning(); };
    if (typeof global.ResizeObserver === 'function') { stage.resizeObserver = new global.ResizeObserver(stage.onResize); stage.resizeObserver.observe(container); }
    global.addEventListener('resize', stage.onResize);
    global.addEventListener('orientationchange', stage.onResize);
    document.addEventListener('visibilitychange', stage.onVisibility);
    // some browsers present no frame callbacks for a video nobody sees: poll the clock instead if they stop for a moment
    stage.watchdog = setInterval(() => {
      if (!stage.running() || !stage.motion) return;
      const t = nowMs();
      for (const s of stage.slots) {
        if (s.mode === 'webgl' && s.source && s.source.kind === 'video' && !s.pollMode && s.video && !s.video.paused && s.video.readyState >= 2 && t - Math.max(s.lastCb, s.startedAt || 0) > 900) {
          s.pollMode = true; s.cancelFrameCallback(); stage.note('no frame callbacks: polling'); stage.kick();
        }
      }
    }, 600);
    if (stage.watchdog && typeof stage.watchdog.unref === 'function') stage.watchdog.unref();

    const api = {
      show: (info) => stage.show(info),
      setArea: (rect) => stage.setArea(rect),
      setMotion: (on) => stage.setMotion(on),
      setLive: (on) => stage.setLive(on),
      setReadings: (latest) => stage.setReadings(latest),
      poke: (x, y) => stage.poke(x, y),
      setQuality: (q) => stage.setQuality(q),
      pause: () => stage.pause(),
      resume: () => stage.resume(),
      status: () => stage.status(),
      destroy: () => stage.destroy(),
      // testing aids, not part of the page's contract
      debug: {
        loseContext() { const s = stage.current; const e = s && s.loseExt; if (e) e.loseContext(); return !!e; },
        restoreContext() { const s = stage.current; const e = s && s.loseExt; if (e) e.restoreContext(); return !!e; },
        setLevel(l) { stage.level = clamp(l | 0, 0, LEVELS.length - 1); for (const s of stage.slots) if (s.mode === 'webgl') { s.applyLayout(); s.dirty = true; } stage.kick(); stage.emit(); },
        notes() { return stage.notes.slice(); },
        governor() { const g = stage.governor; return { samples: g.samples.length, late: g.samples.filter((x) => x.late).length, hold: Math.round(g.holdUntil - nowMs()), banned: [...g.banned], ups: g.ups, expected: stage.current && Math.round(stage.current.expected) }; },
        benchmark(frames, withUpload) { const s = stage.current; return s ? s.benchmark(frames || 6, !!withUpload) : null; },
        setClock(seconds) { for (const s of stage.slots) { s.clock = seconds; s.dirty = true; } stage.kick(); },
        /** One frame at exactly `seconds` of the scene's clock, drawn at once (pause the stage first: the loop would carry on from there). */
        freezeAt(seconds) { const s = stage.current; if (!s) return false; s.clock = seconds; s.lastDraw = nowMs(); s.dirty = true; return s.renderNow(nowMs(), false); },
        /** What the last live frame read (pixels, reads, sprite and mesh areas, draw calls), or null: for reasoning about a GPU, not a speed. */
        cost() { const s = stage.current; return s && s.renderer && typeof s.renderer.cost === 'function' ? s.renderer.cost() : null; },
        pokes() { const s = stage.current; return s && s.bank ? s.bank.items.map((p) => ({ kind: p.kind, x: p.x, y: p.y })) : []; },
        /** A touch whose age is fixed at `age` seconds, on a fake clock, so a frame with it can be drawn again and again (age null: back to real time). */
        pokeAt(x, y, age) {
          const s = stage.current, live = global.SceneStageLive;
          if (!s || !live) return false;
          if (age === null || age === undefined) { s.pokeClock = null; if (s.bank) s.bank.clear(); return true; }
          s.pokeClock = 1000 + age;
          if (!s.bank) s.bank = new live.PokeBank();
          s.bank.clear();
          const kind = s.renderer && s.renderer.pokeKind ? s.renderer.pokeKind({ info: s.info, layout: s.layout, x, y }) : null;
          return kind ? s.bank.add(x, y, 1000, kind) : false;
        },
      },
    };
    return api;
  }

  const SceneStage = { create, register, version: 1 };
  global.SceneStage = SceneStage;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { SceneStage, containRect, monitorLayout, coverRect, driftState, driftDirection, sourceGrid, stepLevel, parseFx, normalizeInfo, localUrl,
      Governor, LEVELS, GOVERNOR, DRIFT, STILL_INTERVAL, LIVE_FILM_FPS, clamp, mix, smoothstep, hashString, noiseData };
  }
})(typeof window !== 'undefined' ? window : globalThis);
