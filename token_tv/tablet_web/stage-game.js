/* The tablet's real-time pixel scenes ("games"): window.TabletGames.
 *
 * A pixel scene is no longer a looping video inside a monitor. It is a small program that draws portrait pixel art (native 200 x 320 "art pixels" by default: x4 is
 * exactly this tablet's 800 x 1280) 30 times a second, and this file shows it FULL-BLEED behind the page with an old-CRT treatment (scanlines on the art rows, a faint
 * phosphor mask, horizontal colour bleed, a soft glow, a vignette and a barely-there flicker; NO curvature and NO bezel, so nothing is lost at the edges).
 *
 * A scene is a file `game-<name>.js` that registers itself:
 *
 *   TabletGames.define('platform', {
 *     size: [200, 320],                  // native art pixels, portrait; the engine covers the screen with it (top aligned)
 *     post: 'crt',                       // 'crt' (default), 'crt-clear', 'lcd', 'plain', or 'handheld' (smooth casing, LCD pixel grid within pixelRect)
 *     pixelRect() { return [x, y, w, h]; }, // for 'handheld': the screen rectangle in art pixels, including any current shift
 *     init(api) {},                      // once, after the atlas (api.atlas, a private picture) and api.json (its frames) are loaded
 *     step(api, dt) {},                  // fixed 30 Hz logic step (dt = 1/30): move things here
 *     draw(api, g) {},                   // g: the 2D context of the native-size canvas; draw the whole picture every call (opaque)
 *     poke(api, x, y) {},                // optional: a touch, in native pixels
 *   });
 *
 *   api = { name, size, atlas (Image or null), json (object or null), time (seconds), tier ('high'|'medium'|'light'|'low'), random() (seeded, repeatable),
 *           view: {top, bottom} (the art rows that stay visible above the page's glass dock; keep the action inside them, the rest is ground or sky seen in picture mode),
 *           readings() (the page's latest readings, only for scenes that show quota in the picture), sprite(g, name, x, y, flip) }
 *
 * The engine owns: the loop, the loader, the CRT pass (WebGL 1, one pass, at most four reads per pixel; the tier lowers the effects and then the frame rate on a weak
 * GPU such as the tablet's Mali-T860), a CSS fallback without WebGL, pause/resume, motion off (a still), touch and an honest status(). Art that comes from a game's ROM
 * stays private: it is only ever the atlas picture served from the tablet's private folder; this file and the scene files hold no copyrighted pixels.
 */
(function (global) {
  'use strict';

  const STEP = 1 / 30;
  const MAX_STEPS = 4;                       // never run more than this many logic steps for one frame (a slow frame must not spiral)
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const LEVELS = [
    { name: 'high', scale: 1, fx: 2, every: 1 },     // full device resolution, bleed and glow, every step is shown
    { name: 'medium', scale: 0.85, fx: 2, every: 1 },
    { name: 'light', scale: 0.7, fx: 1, every: 1 },   // no glow
    { name: 'low', scale: 0.55, fx: 0, every: 2 },    // a plain pass, every other step (15 fps)
  ];

  /* ---- pure helpers (the Node tests run these) */

  /** Cover the screen with the art, top aligned. Returns the rectangle the art covers (CSS px, it may reach past the screen at the bottom or the sides). */
  function coverLayout(viewW, viewH, nw, nh) {
    const scale = Math.max(viewW / nw, viewH / nh);
    const w = nw * scale, h = nh * scale;
    return { scale, x: (viewW - w) / 2, y: 0, w, h };
  }
  /** The art rows that stay visible above the glass dock (the page's area), and the whole picture when the dock is gone. */
  function visibleRows(layout, nh, areaBottom, viewH) {
    const bottom = clamp(areaBottom, 0, viewH);
    return { top: 0, bottom: clamp(Math.ceil(bottom / layout.scale - 0.01), 1, nh) };      // a row that is partly visible counts as visible
  }
  /** A fixed-step clock: how many logic steps a frame of `elapsed` seconds owes (never more than MAX_STEPS; a longer frame is forgiven). */
  function makeClock(step = STEP, max = MAX_STEPS) {
    let acc = 0;
    return {
      advance(elapsed) {
        acc += clamp(elapsed, 0, step * max * 2);
        let n = 0;
        while (acc >= step && n < max) { acc -= step; n++; }
        if (n === max) acc = 0;
        return n;
      },
      reset() { acc = 0; },
    };
  }
  /** A repeatable random number generator (mulberry32): the same seed gives the same sequence, so a scene can be tested and screenshot. */
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
  /** The quality governor: feed it frame times; it says 'down' after a spell of late frames and 'up' after a long clean one. */
  class Governor {
    constructor(options) { this.o = Object.assign({ late: 0.045, window: 45, lateShare: 0.35, hold: 3, calm: 40 }, options || {}); this.reset(0); }
    reset(now) { this.samples = []; this.holdUntil = now + this.o.hold; this.calmSince = null; }
    feed(dt, now) {
      this.samples.push(dt);
      if (this.samples.length > this.o.window) this.samples.shift();
      if (now < this.holdUntil || this.samples.length < this.o.window) return null;
      const late = this.samples.filter((s) => s > this.o.late).length / this.samples.length;
      if (late >= this.o.lateShare) { this.reset(now); return 'down'; }
      if (late === 0) { if (this.calmSince === null) this.calmSince = now; if (now - this.calmSince >= this.o.calm) { this.calmSince = null; return 'up'; } } else this.calmSince = null;
      return null;
    }
  }
  const localUrl = (value) => {
    try {
      const u = new URL(String(value), global.location ? global.location.href : 'http://localhost/');
      return global.location && u.origin !== global.location.origin ? null : u.pathname + u.search;
    } catch (_) { return null; }
  };

  /* ---- the CRT pass */
  const VERT = 'attribute vec2 p; varying vec2 uv; uniform vec4 rect; void main(){ uv = p * 0.5 + 0.5; uv.y = 1.0 - uv.y; vec2 s = rect.xy + uv * rect.zw; gl_Position = vec4(s.x * 2.0 - 1.0, 1.0 - s.y * 2.0, 0.0, 1.0); }';
  // rect = the art rectangle in 0..1 screen units (it may reach past the screen: the art covers it)
  const FRAG = [
    '#ifdef GL_FRAGMENT_PRECISION_HIGH',
    'precision highp float;',
    '#else',
    'precision mediump float;',
    '#endif',
    'varying vec2 uv; uniform sampler2D base, glow; uniform vec2 native; uniform vec4 pixelRect; uniform float fx, time, mode;',
    'void main(){',
    '  vec2 a = uv * native; vec2 cell = floor(a); vec2 f = fract(a);',
    '  vec2 px = (cell + 0.5) / native;',
    '  bool screen = a.x >= pixelRect.x && a.y >= pixelRect.y && a.x < pixelRect.x + pixelRect.z && a.y < pixelRect.y + pixelRect.w;',
    '  vec3 c = texture2D(base, mode > 2.5 && mode < 3.5 && !screen ? uv : px).rgb;',
    '  if (mode > 3.5) {',
    '    float beam = 1.0 - 0.16 * smoothstep(0.5, 1.0, abs(f.y - 0.5) * 2.0);',
    '    vec2 q = uv * 2.0 - 1.0; c *= beam * (1.0 - 0.07 * dot(q, q) * 0.5);',
    '    gl_FragColor = vec4(c, 1.0); return;',
    '  }',
    '  if (mode > 2.5) {',
    '    if (screen) { vec2 e = smoothstep(0.0, 0.32, f) * (1.0 - smoothstep(0.68, 1.0, f)); c *= mix(0.68, 1.0, e.x * e.y); }',
    '    gl_FragColor = vec4(c, 1.0); return;',
    '  }',
    '  if (mode > 1.5) { gl_FragColor = vec4(c, 1.0); return; }',
    '  if (mode > 0.5) { vec2 e = smoothstep(0.0, 0.16, f) * smoothstep(1.0, 0.84, f); c *= mix(0.80, 1.0, e.x * e.y); if (fx > 1.5) c += texture2D(glow, uv).rgb * 0.10; vec2 q2 = uv * 2.0 - 1.0; c *= 1.0 - 0.10 * dot(q2, q2) * 0.5; gl_FragColor = vec4(c, 1.0); return; }',
    '  if (fx > 0.5) { vec2 o = vec2(1.0 / native.x, 0.0); c = c * 0.76 + (texture2D(base, px - o).rgb + texture2D(base, px + o).rgb) * 0.12; }',
    '  float dy = abs(f.y - 0.5) * 2.0; float beam = 1.0 - 0.34 * smoothstep(0.42, 1.0, dy);',
    '  float dx = abs(f.x - 0.5) * 2.0; beam *= 1.0 - 0.08 * smoothstep(0.62, 1.0, dx);',
    '  float m = mod(gl_FragCoord.x, 3.0); vec3 mask = vec3(m < 1.0 ? 1.0 : 0.88, (m >= 1.0 && m < 2.0) ? 1.0 : 0.88, m >= 2.0 ? 1.0 : 0.88);',
    '  c *= beam * mask * 1.14;',
    '  if (fx > 1.5) c += texture2D(glow, uv).rgb * 0.30;',
    '  vec2 q = uv * 2.0 - 1.0; c *= 1.0 - 0.16 * dot(q, q) * 0.5;',
    '  float roll = smoothstep(0.0, 0.5, 1.0 - abs(fract(uv.y * 1.0 - time * 0.05) - 0.5) * 2.0); c *= 1.0 + 0.018 * roll;',
    '  c *= 1.0 + 0.010 * sin(time * 47.0);',
    '  gl_FragColor = vec4(c, 1.0);',
    '}'].join('\n');

  const registry = Object.create(null);
  function define(name, module) {
    if (typeof name !== 'string' || !/^[a-z0-9-]{1,40}$/.test(name) || !module || typeof module.draw !== 'function') return false;
    registry[name] = module;
    return true;
  }

  /** The stage for game scenes: the same calls the page makes to the photo stage (show, setArea, setMotion, setQuality, setLive, pause, resume, poke, status, destroy). */
  function create(container, opts) {
    opts = opts || {};
    const doc = container.ownerDocument || global.document;
    const canvas = doc.createElement('canvas');
    Object.assign(canvas.style, { position: 'absolute', inset: '0', width: '100%', height: '100%', opacity: '0', transition: 'opacity .6s' });
    canvas.setAttribute('aria-hidden', 'true');
    container.append(canvas);
    const art = doc.createElement('canvas'), glowCanvas = doc.createElement('canvas');
    const g = art.getContext('2d', { alpha: false });
    const gg = glowCanvas.getContext('2d', { alpha: false });
    const state = { info: null, module: null, api: null, ready: false, error: '', notes: [], paused: false, motion: true, live: true, quality: 'auto', level: 0, area: null,
      raf: 0, last: 0, frames: 0, dropped: 0, fpsMark: 0, fps: 0, started: 0, time: 0, readings: null, token: 0, gl: null, dead: false, stillDrawn: false };
    const clock = makeClock(), governor = new Governor();
    const note = (text) => { state.notes.push(String(text).slice(0, 90)); if (state.notes.length > 8) state.notes.shift(); };
    const emit = () => { if (typeof opts.onStatus === 'function') { try { opts.onStatus(status()); } catch (_) { /* the page's callback must not break the stage */ } } };

    function initGL() {
      if (state.gl !== null) return state.gl;
      state.gl = false;
      let gl = null;
      try { gl = canvas.getContext('webgl', { alpha: false, antialias: false, depth: false, stencil: false, preserveDrawingBuffer: false, powerPreference: 'low-power' }); } catch (_) { gl = null; }
      if (!gl) { note('no WebGL: CSS fallback'); return false; }
      const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error('shader: ' + gl.getShaderInfoLog(s)); return s; };
      try {
        const program = gl.createProgram();
        gl.attachShader(program, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(program, sh(gl.FRAGMENT_SHADER, FRAG)); gl.linkProgram(program);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('link');
        gl.useProgram(program);
        const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        const loc = gl.getAttribLocation(program, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
        const tex = (unit, filter) => { const t = gl.createTexture(); gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, t);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE); return t; };
        const u = (n) => gl.getUniformLocation(program, n);
        state.gl = { gl, program, base: tex(0, gl.NEAREST), glow: tex(1, gl.LINEAR), linear: false, u: { rect: u('rect'), native: u('native'), pixelRect: u('pixelRect'), fx: u('fx'), time: u('time'), mode: u('mode'), base: u('base'), glow: u('glow') } };
        gl.uniform1i(state.gl.u.base, 0); gl.uniform1i(state.gl.u.glow, 1);
        canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); state.gl = null; note('WebGL context lost'); });
        canvas.addEventListener('webglcontextrestored', () => { state.gl = null; initGL(); });
      } catch (e) { note(String(e && e.message || e)); state.gl = false; }
      return state.gl;
    }

    function viewSize() {
      const w = Math.max(1, container.clientWidth || (global.innerWidth || 1)), h = Math.max(1, container.clientHeight || (global.innerHeight || 1));
      return { w, h };
    }
    function layout() {
      const { w, h } = viewSize(), nw = state.api ? state.api.size[0] : 200, nh = state.api ? state.api.size[1] : 320;
      const l = coverLayout(w, h, nw, nh);
      if (state.api) state.api.view = visibleRows(l, nh, state.area ? state.area.top + state.area.height : h, h);
      return { l, w, h, nw, nh };
    }
    function sizeCanvas() {
      const { w, h } = viewSize();
      const dpr = clamp(global.devicePixelRatio || 1, 1, 2), level = LEVELS[state.level];
      const cw = Math.max(2, Math.round(w * dpr * level.scale)), ch = Math.max(2, Math.round(h * dpr * level.scale));
      if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
    }

    function present(nw, nh, l, w, h) {
      const t = state.gl && state.gl.gl ? state.gl : initGL();
      const level = LEVELS[state.level];
      const post = state.module && state.module.post;
      const handheld = post === 'handheld';
      const pixelRect = handheld && typeof state.module.pixelRect === 'function' ? state.module.pixelRect(state.api) : [0, 0, 0, 0];
      if (t && t.gl) {
        const gl = t.gl;
        sizeCanvas();
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, t.base);
        if (t.linear !== handheld) {
          const filter = handheld ? gl.LINEAR : gl.NEAREST;
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
          t.linear = handheld;
        }
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, art);
        if (level.fx > 1 && post !== 'plain' && post !== 'crt-clear' && !handheld) {
          gg.imageSmoothingEnabled = true; gg.filter = 'blur(1.5px)'; gg.drawImage(art, 0, 0, glowCanvas.width, glowCanvas.height); gg.filter = 'none';
          gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, t.glow); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, glowCanvas);
        }
        gl.uniform4f(t.u.rect, l.x / w, l.y / h, l.w / w, l.h / h);
        gl.uniform4f(t.u.pixelRect, ...pixelRect);
        gl.uniform2f(t.u.native, nw, nh); gl.uniform1f(t.u.fx, level.fx); gl.uniform1f(t.u.time, state.time % 1000);
        gl.uniform1f(t.u.mode, post === 'crt-clear' ? 4 : handheld ? 3 : post === 'lcd' ? 1 : post === 'plain' ? 2 : 0);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        return 'webgl';
      }
      // CSS fallback: smooth the casing, then add crisp LCD pixels and their fine grid only over the screen.
      if (!state.cssArt) {
        state.cssArt = art; Object.assign(art.style, { position: 'absolute', imageRendering: 'pixelated', pointerEvents: 'none' });
        const overlay = doc.createElement('div'); overlay.setAttribute('aria-hidden', 'true'); state.cssOverlay = overlay;
        Object.assign(overlay.style, { position: 'absolute', inset: '0', pointerEvents: 'none' });
        canvas.style.display = 'none'; container.append(art, overlay);
      }
      Object.assign(art.style, { left: l.x + 'px', top: l.y + 'px', width: l.w + 'px', height: l.h + 'px', opacity: '1', imageRendering: handheld ? 'auto' : 'pixelated' });
      const lineAlpha = post === 'crt-clear' ? '.16' : '.32';
      state.cssOverlay.style.background = handheld || post === 'plain' ? 'none' : 'repeating-linear-gradient(180deg, rgba(0,0,0,0) 0, rgba(0,0,0,0) ' + (l.scale * 0.55) + 'px, rgba(0,0,0,' + lineAlpha + ') ' + (l.scale * 0.55) + 'px, rgba(0,0,0,' + lineAlpha + ') ' + l.scale + 'px)';
      state.cssOverlay.style.backgroundPosition = '0 ' + l.y + 'px';
      if (handheld) {
        if (!state.cssPixels) {
          state.cssPixels = doc.createElement('canvas');
          Object.assign(state.cssPixels.style, { position: 'absolute', imageRendering: 'pixelated', pointerEvents: 'none' });
          state.cssPixels.setAttribute('aria-hidden', 'true');
          container.append(state.cssPixels);
          state.cssGrid = doc.createElement('div');
          state.cssGrid.setAttribute('aria-hidden', 'true');
          Object.assign(state.cssGrid.style, { position: 'absolute', pointerEvents: 'none',
            backgroundImage: 'linear-gradient(to right, rgba(0,0,0,.24), transparent 32%, transparent 68%, rgba(0,0,0,.24)), linear-gradient(to bottom, rgba(0,0,0,.24), transparent 32%, transparent 68%, rgba(0,0,0,.24))' });
          container.append(state.cssGrid);
        }
        const pixels = state.cssPixels;
        if (pixels.width !== nw || pixels.height !== nh) { pixels.width = nw; pixels.height = nh; }
        pixels.getContext('2d').drawImage(art, 0, 0);
        const [x, y, pw, ph] = pixelRect;
        Object.assign(pixels.style, { display: 'block', left: l.x + 'px', top: l.y + 'px', width: l.w + 'px', height: l.h + 'px',
          clipPath: `inset(${clamp(y / nh * 100, 0, 100)}% ${clamp((nw - x - pw) / nw * 100, 0, 100)}% ${clamp((nh - y - ph) / nh * 100, 0, 100)}% ${clamp(x / nw * 100, 0, 100)}%)` });
        Object.assign(state.cssGrid.style, { display: 'block', left: (l.x + x * l.scale) + 'px', top: (l.y + y * l.scale) + 'px',
          width: (pw * l.scale) + 'px', height: (ph * l.scale) + 'px', backgroundSize: `${l.scale}px ${l.scale}px` });
      } else if (state.cssPixels) { state.cssPixels.style.display = 'none'; state.cssGrid.style.display = 'none'; }
      return 'css';
    }

    function frame(now) {
      state.raf = 0;
      if (state.dead || state.paused || !state.ready) return;
      const t = now / 1000, dt = state.last ? Math.min(0.25, t - state.last) : STEP;
      state.last = t;
      if (state.motion) {
        const owed = clock.advance(dt);
        for (let i = 0; i < owed; i++) { state.time += STEP; try { state.module.step(state.api, STEP); } catch (e) { fail('step: ' + (e && e.message || e)); return; } state.frames++; }
        state.api.time = state.time;
        if (owed > 0 && (state.frames % LEVELS[state.level].every === 0 || LEVELS[state.level].every === 1)) render();
        const verdict = governor.feed(dt, t);
        if (verdict === 'down' && state.quality === 'auto' && state.level < LEVELS.length - 1) { state.level++; if (state.api) state.api.tier = LEVELS[state.level].name; note('quality lowered to ' + LEVELS[state.level].name); emit(); }
        else if (verdict === 'up' && state.quality === 'auto' && state.level > 0) { state.level--; if (state.api) state.api.tier = LEVELS[state.level].name; note('quality raised to ' + LEVELS[state.level].name); emit(); }
        if (dt > 0.045) state.dropped++;
      } else if (!state.stillDrawn) { render(); state.stillDrawn = true; }
      if (t - state.fpsMark >= 1) { state.fps = Math.round(state.fpsCount * 10 / (t - state.fpsMark)) / 10; state.fpsMark = t; state.fpsCount = 0; }
      schedule();
    }
    function render() {
      const { l, w, h, nw, nh } = layout();
      try { state.module.draw(state.api, g); } catch (e) { fail('draw: ' + (e && e.message || e)); return; }
      state.renderer = present(nw, nh, l, w, h);
      state.fpsCount = (state.fpsCount || 0) + 1;
      canvas.style.opacity = '1';
    }
    function schedule() { if (!state.raf && !state.dead && !state.paused && state.ready) state.raf = (global.requestAnimationFrame || ((fn) => setTimeout(() => fn(Date.now()), 33)))(frame); }
    function fail(text) { state.error = text; note(text); state.ready = false; emit(); }

    async function show(info) {
      const token = ++state.token;
      if (state.raf && global.cancelAnimationFrame) global.cancelAnimationFrame(state.raf);
      state.raf = 0; state.ready = false; state.error = ''; state.stillDrawn = false;
      if (!info) { state.info = null; state.module = null; canvas.style.opacity = '0'; if (state.cssArt) state.cssArt.style.opacity = '0'; if (state.cssPixels) { state.cssPixels.style.display = 'none'; state.cssGrid.style.display = 'none'; } emit(); return; }
      const name = String(info.name || '').toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 40), module = registry[name];
      state.info = { name, atlas: info.media && localUrl(info.media.url), data: localUrl(info.data) };
      if (!module) { fail('no game named ' + name); return; }
      const loadImage = (url) => new Promise((resolve) => { if (!url) { resolve(null); return; } const img = new global.Image(); const timer = setTimeout(() => resolve(null), 20000); img.onload = () => { clearTimeout(timer); resolve(img); }; img.onerror = () => { clearTimeout(timer); resolve(null); }; img.src = url; });
      const loadJson = (url) => (url ? global.fetch(url, { cache: 'no-cache' }).then((r) => (r.ok ? r.json() : null)).catch(() => null) : Promise.resolve(null));
      const [atlas, json] = await Promise.all([loadImage(state.info.atlas), loadJson(state.info.data)]);
      if (token !== state.token || state.dead) return;
      if (module.needsAtlas && !atlas) { fail('the atlas of ' + name + ' did not load'); return; }
      const size = Array.isArray(module.size) && module.size.length === 2 && module.size.every(finite) ? [clamp(Math.round(module.size[0]), 32, 512), clamp(Math.round(module.size[1]), 32, 768)] : [200, 320];
      art.width = size[0]; art.height = size[1]; glowCanvas.width = Math.max(8, size[0] >> 1); glowCanvas.height = Math.max(8, size[1] >> 1);
      const random = seeded(0x5eed ^ name.length * 7919);
      state.api = { name, size, atlas, json, time: 0, tier: LEVELS[state.level].name, random, view: { top: 0, bottom: size[1] }, readings: () => state.readings,
        sprite(ctx, frameName, x, y, flip) {
          const f = json && json.frames && json.frames[frameName]; if (!f || !atlas) return false;
          if (flip) { ctx.save(); ctx.translate(Math.round(x) + f[2], Math.round(y)); ctx.scale(-1, 1); ctx.drawImage(atlas, f[0], f[1], f[2], f[3], 0, 0, f[2], f[3]); ctx.restore(); }
          else ctx.drawImage(atlas, f[0], f[1], f[2], f[3], Math.round(x), Math.round(y), f[2], f[3]);
          return true;
        } };
      g.imageSmoothingEnabled = false;
      try { module.init(state.api); } catch (e) { fail('init: ' + (e && e.message || e)); return; }
      state.module = module; state.ready = true; state.last = 0; state.time = 0; clock.reset(); governor.reset(0); state.started = Date.now();
      render(); emit(); schedule();
    }

    function status() {
      const l = LEVELS[state.level];
      return { renderer: state.renderer === 'webgl' || state.renderer === 'css' ? state.renderer : 'plain', look: 'game', scene: state.info ? state.info.name : null, ready: state.ready,
        fps: state.fps || 0, dropped: state.dropped, tier: state.renderer === 'css' ? 'css' : l.name, level: state.level, scale: l.scale, quality: state.quality, motion: state.motion,
        paused: state.paused, video: false, live: state.ready && state.motion && !state.paused, gpu: state.gl && state.gl.gl ? 'game' : '', media: state.api ? state.api.size : null,
        canvas: [canvas.width, canvas.height], notes: state.notes.slice(-6), error: state.error || undefined };
    }
    return {
      show,
      setArea(rect) { state.area = rect && finite(rect.top) && finite(rect.height) ? { top: rect.top, height: rect.height } : null; if (state.ready) render(); },
      setMotion(on) { const next = !!on; if (next === state.motion) return; state.motion = next; state.stillDrawn = false; clock.reset(); state.last = 0; schedule(); emit(); },
      setQuality(q) { state.quality = q === 'high' || q === 'low' ? q : 'auto'; state.level = q === 'low' ? LEVELS.length - 1 : 0; if (state.api) state.api.tier = LEVELS[state.level].name; governor.reset(state.last); emit(); },
      setLive() { /* the game IS the live effect; the page's switch only concerns the photo effects */ },
      setReadings(latest) { state.readings = latest || null; },
      pause() { state.paused = true; if (state.raf && global.cancelAnimationFrame) global.cancelAnimationFrame(state.raf); state.raf = 0; emit(); },
      resume() { if (!state.paused) return; state.paused = false; state.last = 0; clock.reset(); governor.reset(0); schedule(); emit(); },
      poke(x, y) {
        if (!state.ready || !state.motion || state.paused || !state.module || typeof state.module.poke !== 'function' || !finite(x) || !finite(y)) return;
        const { l, nw, nh } = layout(), r = container.getBoundingClientRect ? container.getBoundingClientRect() : { left: 0, top: 0 };
        const ax = (x - r.left - l.x) / l.scale, ay = (y - r.top - l.y) / l.scale;
        if (ax < 0 || ay < 0 || ax >= nw || ay >= nh) return;
        try { state.module.poke(state.api, ax, ay); } catch (e) { note('poke: ' + (e && e.message || e)); }
      },
      status,
      destroy() { state.dead = true; if (state.raf && global.cancelAnimationFrame) global.cancelAnimationFrame(state.raf); canvas.remove(); if (state.cssArt) { state.cssArt.remove(); state.cssOverlay.remove(); } if (state.cssPixels) { state.cssPixels.remove(); state.cssGrid.remove(); } },
    };
  }

  const api = { define, create, coverLayout, visibleRows, makeClock, seeded, Governor, STEP, LEVELS, localUrl, registry, FRAG, VERT };
  global.TabletGames = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
