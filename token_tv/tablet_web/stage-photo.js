/*
 * Photo look: a realistic picture or video that uses the tablet's resolution and motion (WebGL 1; see scene-stage.js for the contract).
 *
 * Still pictures (the night cities) get, all restrained:
 *   - a very slow camera drift: zoom 1.00 to 1.03 about the focus point and a few pixels of pan, a cosine ping-pong over about two
 *     minutes (60 s each way) with zero speed at both ends, never abrupt, never uncovering the area;
 *   - twinkling of the brightest SMALL lights: a once-per-picture "top-hat" mask (a pixel much brighter than its surroundings) says
 *     which lights are windows and neon; each light breathes a little and, now and then, goes out for a few seconds and comes back,
 *     on its own slow clock (a value-noise lattice of per-node waves), so it never looks like a disco;
 *   - soft bloom around those highlights (two blurred levels computed once), a faint drifting haze in the lower third of the area,
 *     a gentle colour grade, film grain at a whisper and a soft vignette.
 * Videos (Paradise): no drift and no motion of our own at all (the camera must not sway): only a soft grade, faint grain, a vignette.
 * The 'low' level shows the picture or video with only the vignette. Still pictures are uploaded as mip-mapped power-of-two textures
 * (scene-stage.js) so a slow drift over a picture larger than the screen does not shimmer.
 *
 * A scene with a `live` block (stage-live.js) is drawn differently: a still is baked ONCE with this same shader (grade, bloom, vignette, no drift, no haze) into a target the
 * size of the canvas and every frame reads that (one read per pixel), plus the coarse meshes, sprites and craft of stage-live.js; a film is read directly. With live off, with
 * motion off, or if the live shader fails, the classic pass of this file draws, unchanged.
 *
 * The picture never ends inside the screen with a dragged last row. A tall picture (covering the whole screen needs at most 1.15 times the zoom of covering the slot) covers the
 * whole screen; a wide one covers the slot, and past its edge the shader reads the picture as its own reflection (a triangle wave of the coordinate), blurred more and more and
 * faded into the page's colour over FADE pixels. `?off=mirror` (testing) brings the old clamp back for before and after frames.
 */
(function (global) {
  'use strict';

  /* ---- tuning knobs ----------------------------------------------------------------------------------------------------- */
  const DRIFT = { period: 120, zoom: 0.03, pan: 0.7, panPx: 12 };   // seconds for a whole there-and-back, zoom gain, share of the margin used by the pan, and the most it may be in pixels
  const BREATH = 0.15;            // a light dims by up to this much while it breathes
  const OFF_FLOOR = 0.30;         // brightness of a light that has gone out for a while (it never goes fully black)
  const OFF_FROM = 0.86, OFF_TO = 0.97;   // part of the slow wave during which a light is out (about one fifth of the time)
  const CELL = 9;                 // picture pixels between value-noise nodes: neighbouring windows move independently, one window rarely straddles two
  const CELL_BIG = 36;            // ... and for larger lit things (neon signs), which breathe as a whole
  const BLOOM = 0.55;             // strength of the glow around highlights
  const BLOOM_THRESHOLD = 0.42;   // linear light above which a highlight blooms
  const HAZE = 0.085;             // strength of the drifting haze (screen blend)
  const GRAIN = 0.013;            // film grain amplitude (share of full scale)
  const GRAIN_SIZE = 1.3;         // grain size in device pixels
  const VIGNETTE = 0.20;          // corner darkening, relative to the area
  const GRADE = { contrast: 0.16, saturation: 0.07, shadow: [-0.010, 0.002, 0.020], highlight: [0.016, 0.007, -0.006] };
  const FADE = 200;               // CSS px over which a picture that ends inside the container fades (blurred) into the page background

  // per-scene defaults, by info.name; anything unnamed is `night` for a still and `natural` for a video
  const PRESETS = {
    night: { drift: 1, twinkle: 1, haze: 1, bloom: 1, grade: 1, grain: 1, vignette: 1, tint: [0.60, 0.66, 0.82] },
    natural: { drift: 0, twinkle: 0, haze: 0, bloom: 0, grade: 0.55, grain: 0.7, vignette: 0.75, tint: [0.7, 0.7, 0.7] },
  };
  PRESETS.city = PRESETS.night;
  PRESETS['neon-city'] = Object.assign({}, PRESETS.night, { bloom: 1.15, tint: [0.72, 0.58, 0.84] });
  PRESETS['neon-district'] = PRESETS.natural; // Cozy Mountain Home retains its historical id
  PRESETS['violet-horizon'] = Object.assign({}, PRESETS.night, { haze: 1.1, tint: [0.80, 0.62, 0.88] });
  PRESETS.paradise = PRESETS.natural;
  // city-iso is a video of a drawing whose own sprites move: the gentle grade only, a lighter grain (it draws at 6 frames a second)
  PRESETS['city-iso'] = Object.assign({}, PRESETS.natural, { grade: 0.7, grain: 0.35, vignette: 0.6 });

  function presetFor(info, isVideo) {
    const named = info && PRESETS[info.name];
    if (named) return isVideo ? Object.assign({}, named, { drift: 0, twinkle: 0, haze: 0, bloom: 0 }) : named;   // a video never gets our own motion
    return isVideo ? PRESETS.natural : PRESETS.night;
  }

  // R: small lights (a pixel far brighter than its ~3 px neighbourhood: windows, lamps; a thin neon bar is NOT one). G: larger lit things
  // (neon bars and signs, up to ~30 px): they only breathe, as a whole, and never go out.
  const MASK_FS = function (lib) {
    return [
      'uniform sampler2D uTex; uniform vec2 uOut; uniform vec2 uUvScale;',
      lib,
      'void main() {',
      '  vec2 tuv = (gl_FragCoord.xy / uOut) * uUvScale;',
      '  float l0 = luma(texture2D(uTex, tuv).rgb);',
      '  float la = luma(texture2D(uTex, tuv, 1.5).rgb);',
      '  float lb = luma(texture2D(uTex, tuv, 3.0).rgb);',
      '  float lc = luma(texture2D(uTex, tuv, 5.0).rgb);',
      '  float small = smoothstep(0.12, 0.30, l0 - la) * smoothstep(0.22, 0.50, l0);',
      '  float big = smoothstep(0.10, 0.30, lb - lc) * smoothstep(0.30, 0.55, lb) * (1.0 - small);',
      '  gl_FragColor = vec4(small, big, 0.0, 1.0);',
      '}',
    ].join('\n');
  };

  const BRIGHT_FS = [
    'uniform sampler2D uTex; uniform vec2 uOut; uniform vec2 uUvScale; uniform float uThreshold;',
    'void main() {',
    '  vec2 tuv = (gl_FragCoord.xy / uOut) * uUvScale;',
    '  vec3 c = texture2D(uTex, tuv, 0.5).rgb; c = c * c;',
    '  gl_FragColor = vec4(sqrt(max(c - vec3(uThreshold), vec3(0.0))), 1.0);',
    '}',
  ].join('\n');

  const DOWN_FS = [
    'uniform sampler2D uTex; uniform vec2 uOut;',
    'void main() {',
    '  vec2 uv = gl_FragCoord.xy / uOut; vec2 d = vec2(0.25) / uOut;',
    '  gl_FragColor = vec4((texture2D(uTex, uv + vec2(-d.x, -d.y)).rgb + texture2D(uTex, uv + vec2(d.x, -d.y)).rgb',
    '                     + texture2D(uTex, uv + vec2(-d.x, d.y)).rgb + texture2D(uTex, uv + vec2(d.x, d.y)).rgb) * 0.25, 1.0);',
    '}',
  ].join('\n');

  const BLUR_FS = [
    'uniform sampler2D uTex; uniform vec2 uOut; uniform vec2 uDir;',
    'void main() {',
    '  vec2 uv = gl_FragCoord.xy / uOut; vec2 d = uDir / uOut;',
    '  vec3 c = texture2D(uTex, uv).rgb * 0.2042;',
    '  c += (texture2D(uTex, uv + d).rgb + texture2D(uTex, uv - d).rgb) * 0.1802;',
    '  c += (texture2D(uTex, uv + 2.0 * d).rgb + texture2D(uTex, uv - 2.0 * d).rgb) * 0.1238;',
    '  c += (texture2D(uTex, uv + 3.0 * d).rgb + texture2D(uTex, uv - 3.0 * d).rgb) * 0.0663;',
    '  c += (texture2D(uTex, uv + 4.0 * d).rgb + texture2D(uTex, uv - 4.0 * d).rgb) * 0.0276;',
    '  gl_FragColor = vec4(c, 1.0);',
    '}',
  ].join('\n');

  const MAIN_FS = function (lib) {
    return [
      'uniform sampler2D uTex; uniform sampler2D uMask; uniform sampler2D uBloomA; uniform sampler2D uBloomB; uniform sampler2D uNoise;',
      'uniform vec2 uRes; uniform vec4 uPic; uniform vec4 uArea; uniform vec2 uUvScale; uniform vec2 uTexel; uniform vec2 uCells; uniform vec2 uCellsBig;',
      'uniform vec3 uBase; uniform vec3 uHazeTint; uniform vec3 uShadow; uniform vec3 uHighlight; uniform vec2 uGrainShift;',
      'uniform float uMirror, uTime, uScale, uHeavy, uTwinkle, uHaze, uBloomAmt, uGrain, uGrainSize, uGrade, uContrast, uSaturation, uVignette, uFade, uBreath, uOffFloor, uOffFrom, uOffTo;',
      lib,
      'float h12(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }',
      // one lattice node: a breathing wave and a slow on/off wave, each with its own period (whole numbers of 1/1000 Hz so the clock can wrap)
      'vec2 nodeLight(vec2 id, float t) {',
      '  float a = h12(id), b = h12(id + 17.31), c = h12(id + 41.7), d = h12(id + 5.9);',
      '  float w1 = 6.2831853 * (14.0 + floor(a * 70.0)) / 1000.0;',
      '  float w2 = 6.2831853 * (7.0 + floor(b * 22.0)) / 1000.0;',
      '  return vec2(0.5 + 0.5 * sin(t * w1 + c * 6.2831853), 0.5 + 0.5 * sin(t * w2 + d * 6.2831853));',
      '}',
      'float lightFactor(vec2 puv, float t, vec2 cells, float breath, float outDepth) {',
      '  vec2 q = puv * cells; vec2 i = floor(q); vec2 f = fract(q); f = f * f * (3.0 - 2.0 * f);',
      '  vec2 n = mix(mix(nodeLight(i, t), nodeLight(i + vec2(1.0, 0.0), t), f.x), mix(nodeLight(i + vec2(0.0, 1.0), t), nodeLight(i + vec2(1.0, 1.0), t), f.x), f.y);',
      '  float off = smoothstep(uOffFrom, uOffTo, n.y);',
      '  return (1.0 - breath * n.x) * (1.0 - outDepth * (1.0 - uOffFloor) * off);',
      '}',
      'void main() {',
      '  vec2 p = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);',
      '  vec2 puv = (p - uPic.xy) / uPic.zw;',
      // past the picture's edge the picture goes on as its own reflection (a triangle wave of the coordinate: 1.2 reads 0.8, -0.2 reads 0.2), and fades into the page's colour:
      // never the last row dragged downwards. `uMirror` 0 brings back the old clamp, for before and after frames.
      '  vec2 cuv = mix(clamp(puv, vec2(0.0), vec2(1.0)), vec2(1.0) - abs(vec2(1.0) - mod(puv, vec2(2.0))), uMirror);',
      '  vec2 tuv = clamp(cuv * uUvScale, 0.5 * uTexel, uUvScale - 0.5 * uTexel);',
      '  vec2 out2 = max(max(uPic.xy - p, p - (uPic.xy + uPic.zw)), vec2(0.0));',
      '  float dEdge = length(out2);',
      '  vec3 c = texture2D(uTex, tuv, min(dEdge / (0.25 * uFade), 1.0) * 4.0).rgb;',
      '  vec2 m = vec2(0.0);',
      '  if (uHeavy > 0.5 && uTwinkle > 0.0) { m = texture2D(uMask, cuv).rg; }',
      '  vec3 bl = vec3(0.0);',
      '  if (uHeavy > 0.5 && uBloomAmt > 0.0) {',
      '    vec3 a = texture2D(uBloomA, cuv).rgb; vec3 b = texture2D(uBloomB, cuv).rgb;',
      '    bl = a * a * 0.8 + b * b * 0.6;',
      '  }',
      '  float tw = 1.0;',
      '  float twB = 1.0;',
      '  if (uTwinkle > 0.0) {',
      '    if (m.r > 0.01 || bl.r + bl.g + bl.b > 0.01) { tw = lightFactor(cuv, uTime, uCells, uBreath, 1.0); }',
      '    if (m.g > 0.01) { twB = lightFactor(cuv, uTime + 333.0, uCellsBig, uBreath * 0.7, 0.0); }',
      '    c *= mix(1.0, tw, m.r * uTwinkle) * mix(1.0, twB, m.g * uTwinkle);',
      '  }',
      '  float lum = luma(c);',
      '  if (uHeavy > 0.5) {',
      '    c = min(c, vec3(1.0));',
      '    c = mix(c, c * c * (3.0 - 2.0 * c), uContrast * uGrade);',
      '    c = mix(vec3(lum), c, 1.0 + uSaturation * uGrade);',
      '    c += (uShadow * (1.0 - lum) * (1.0 - lum) + uHighlight * lum * lum) * uGrade;',
      '  }',
      '  if (uHeavy > 0.5 && uBloomAmt > 0.0) {',
      '    c += bl * uBloomAmt * mix(1.0, tw * mix(1.0, twB, min(1.0, m.g * 4.0)), 0.8 * uTwinkle);',
      '  }',
      '  if (uHeavy > 0.5 && uHaze > 0.0) {',
      '    float band = smoothstep(uArea.y + 0.55 * uArea.w, uArea.y + 0.95 * uArea.w, p.y);',
      '    if (band > 0.0) {',
      '      vec2 hp = vec2(p.x / (uScale * 560.0) + uTime * 0.005, p.y / (uScale * 380.0));',
      '      float n = texture2D(uNoise, hp).r * 0.6 + texture2D(uNoise, hp * 2.3 + vec2(0.37 - uTime * 0.003, 0.11)).g * 0.4;',
      '      float hz = smoothstep(0.30, 0.90, n) * band * uHaze;',
      '      c = vec3(1.0) - (vec3(1.0) - c) * (vec3(1.0) - uHazeTint * hz);',
      '    }',
      '  }',
      '  vec2 a2 = (p - (uArea.xy + 0.5 * uArea.zw)) / (0.5 * uArea.zw);',
      '  c *= 1.0 - uVignette * smoothstep(0.55, 1.45, min(length(a2), 1.6));',
      '  c = mix(c, uBase, smoothstep(0.0, uFade, dEdge));',
      '  if (uHeavy > 0.5 && uGrain > 0.0) {',
      '    float gn = texture2D(uNoise, gl_FragCoord.xy / (256.0 * uGrainSize) + uGrainShift).b;',
      '    c += (gn - 0.5) * uGrain * (1.0 - 0.6 * abs(2.0 * lum - 1.0));',
      '  }',
      '  c += (texture2D(uNoise, gl_FragCoord.xy / 256.0).a - 0.5) * (1.5 / 255.0);',
      '  gl_FragColor = vec4(c, 1.0);',
      '}',
    ].join('\n');
  };

  /* ---- pure geometry (also used by the tests) ---------------------------------------------------------------------------- */

  const FULL_COVER_LIMIT = 1.15;     // a picture covers the whole screen when that needs at most this much more zoom than covering the picture slot

  /** Where the picture sits at rest. It always covers the slot (the area the page gave the stage) with its focus point at the slot's centre where it can. When covering the
   *  WHOLE screen needs no more than FULL_COVER_LIMIT times the zoom of covering the slot (a tall picture), it does, and then never ends inside the screen at all; otherwise it
   *  covers the slot and the shader carries it on past its end as a fading reflection. `cover` is the rectangle that must stay covered. */
  function placePicture(slot, screen, mw, mh, focus, limit) {
    const fx = focus ? focus[0] : 0.5, fy = focus ? focus[1] : 0.5;
    const scaleSlot = Math.max(slot.width / mw, slot.height / mh), scaleScreen = Math.max(screen.width / mw, screen.height / mh);
    const full = scaleScreen <= scaleSlot * (limit || FULL_COVER_LIMIT);
    const cover = full ? { left: 0, top: 0, width: screen.width, height: screen.height } : slot, scale = full ? Math.max(scaleSlot, scaleScreen) : scaleSlot;
    const w = mw * scale, h = mh * scale, lo = (v, a, b) => (v < a ? a : v > b ? b : v);
    return { x: lo(slot.left + slot.width / 2 - fx * w, cover.left + cover.width - w, cover.left), y: lo(slot.top + slot.height / 2 - fy * h, cover.top + cover.height - h, cover.top),
      w, h, scale, full, cover };
  }

  function photoLayout(ctx, kit) {
    const c = ctx.container, m = kit.math;
    let place = placePicture(ctx.area, { width: c.w, height: c.h }, ctx.media.w, ctx.media.h, ctx.info.focus);
    // In portrait picture mode, keep both ends of City's quota bridge in view.
    // A 4:3 picture cannot cover the whole portrait screen without cropping one
    // of them. The existing soft extension fills the space above and below.
    if (ctx.info.name === 'city' && ctx.area.height >= c.h * .95 && c.w / c.h < .8) {
      const scale = c.w / (.72 * ctx.media.w), w = ctx.media.w * scale, h = ctx.media.h * scale;
      const x = c.w / 2 - .558 * w, y = c.h * .15;
      place = { x, y, w, h, scale, full: false, cover: { left: 0, top: y, width: c.w, height: h } };
    }
    const picture = { x: place.x, y: place.y, w: place.w, h: place.h, scale: place.scale };
    // The canvas ends where the picture, at its largest drift, has faded into the page's own background; below it the page shows through.
    let bottom = picture.y + picture.h;
    for (const dir of [[0, 1], [0, -1], [1, 1], [-1, 1]]) {
      const r = m.coverRect(place.cover, ctx.media.w, ctx.media.h, ctx.info.focus, 1 + DRIFT.zoom, [dir[0] * DRIFT.pan, dir[1] * DRIFT.pan], DRIFT.panPx, picture);
      bottom = Math.max(bottom, r.y + r.h);
    }
    const height = Math.max(1, Math.min(c.h, Math.ceil(bottom + FADE)));
    return { canvas: { x: 0, y: 0, w: c.w, h: height }, picture, area: ctx.area, cover: place.cover, full: place.full, container: c };
  }

  /** The picture's rectangle at a given moment: drift only for a still picture with motion on and not in the low tier. */
  function pictureAt(L, info, mediaW, mediaH, seconds, drifting, math) {
    const rest = L.picture;
    if (!drifting) return { x: rest.x, y: rest.y, w: rest.w, h: rest.h, scale: rest.scale };
    const d = math.driftState(seconds, DRIFT, math.driftDirection(info.name));
    return math.coverRect(L.cover || L.area, mediaW, mediaH, info.focus, d.zoom, d.pan, DRIFT.panPx, rest);
  }

  function factory(kit) {
    const px = kit.px;
    return {
      name: 'photo',
      opaque: true,
      history: 0,
      mipmapStills: true,

      layout(ctx) { return photoLayout(ctx, kit); },
      // a still moves at every tier but css: with the live module even the lowest one keeps a slow drift of the baked picture (one read a pixel); without it, as before
      animated(info, low) { const p = presetFor(info, false); return low ? !!(global.SceneStageLive && global.SceneStageLive.createLiveRenderer) : (p.drift > 0 || p.twinkle > 0 || p.haze > 0); },
      /** Do the scene's live effects run now? (stage-live.js: water, clouds, lights, mist, rain, craft, and the answer to touch; every WebGL tier, each with its own small budget; not without motion) */
      live(info, ctx) { return !!(info.live && ctx && ctx.live && ctx.motion && global.SceneStageLive && global.SceneStageLive.createLiveRenderer); },

      create(gl) {
        const main = kit.program(gl, MAIN_FS(kit.glsl.lib));
        const mask = kit.program(gl, MASK_FS(kit.glsl.lib));
        const bright = kit.program(gl, BRIGHT_FS), down = kit.program(gl, DOWN_FS), blur = kit.program(gl, BLUR_FS);
        const highp = (gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER, gl.HIGH_FLOAT) || { precision: 0 }).precision > 0;
        let derived = null;     // targets computed once from a still picture: lights mask and two bloom levels
        const blank = kit.texture(gl);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
        // the live effects (stage-live.js): a still picture is baked once into `baked` (the graded picture at the canvas size) and every frame reads that
        const liveApi = global.SceneStageLive;
        const live = liveApi && typeof liveApi.createLiveRenderer === 'function' ? liveApi.createLiveRenderer(kit, gl) : null;
        let curSrc = null, srcId = 0, baked = null, bakedKey = '', liveBroken = false, liveProblem = '';

        function disposeDerived() {
          if (derived) { for (const t of derived.list) t.dispose(); derived = null; }
        }

        function pass(program, target, setup) {
          target.bind();
          program.use();
          setup(program);
          kit.draw(gl);
        }

        function blurPair(a, tmp, w, h) {
          kit.bindTexture(gl, 0, a.tex);
          pass(blur, tmp, (p) => p.i1('uTex', 0).f2('uOut', w, h).f2('uDir', 1, 0));
          kit.bindTexture(gl, 0, tmp.tex);
          pass(blur, a, (p) => p.i1('uTex', 0).f2('uOut', w, h).f2('uDir', 0, 1));
        }

        function build(src) {
          const side = Math.max(src.w, src.h), dim = (limit) => { const k = Math.min(1, limit / side); return [Math.max(8, Math.round(src.w * k)), Math.max(8, Math.round(src.h * k))]; };
          const [mw, mh] = dim(1024), [aw, ah] = dim(256), [bw, bh] = dim(64);
          const t = { mask: kit.target(gl, mw, mh), a: kit.target(gl, aw, ah), a2: kit.target(gl, aw, ah), b: kit.target(gl, bw, bh), b2: kit.target(gl, bw, bh) };
          t.list = [t.mask, t.a, t.a2, t.b, t.b2];
          derived = t;
          kit.bindTexture(gl, 0, src.tex);
          pass(mask, t.mask, (p) => p.i1('uTex', 0).f2('uOut', mw, mh).f2('uUvScale', src.uvScale[0], src.uvScale[1]));
          pass(bright, t.a, (p) => p.i1('uTex', 0).f2('uOut', aw, ah).f2('uUvScale', src.uvScale[0], src.uvScale[1]).f1('uThreshold', BLOOM_THRESHOLD));
          blurPair(t.a, t.a2, aw, ah);
          kit.bindTexture(gl, 0, t.a.tex);
          pass(down, t.b, (p) => p.i1('uTex', 0).f2('uOut', bw, bh));
          blurPair(t.b, t.b2, bw, bh);
        }

        function disposeBaked() {
          if (baked) { baked.dispose(); baked = null; bakedKey = ''; }
        }

        /** The classic pass. `dynamic` false draws the picture at rest (no drift, lights, haze or grain): that is what is baked for the live effects. */
        function drawMain(f, pic, P, dynamic) {
          const L = f.layout, s = f.scale, heavy = !f.low;
          const off = (f.tuning && f.tuning.off) || [];
          const on = (name) => off.indexOf(name) < 0;
          const seconds = dynamic && f.motion ? f.time : 0;
          const lights = dynamic && heavy && f.isStill && f.motion && derived && highp && P.twinkle > 0 && on('twinkle');       // a still for reduced motion keeps every light on
          const bloom = heavy && f.isStill && derived && P.bloom > 0 && on('bloom');
          kit.bindTexture(gl, 0, f.tex);
          kit.bindTexture(gl, 1, lights ? derived.mask.tex : blank);
          kit.bindTexture(gl, 2, bloom ? derived.a.tex : blank);
          kit.bindTexture(gl, 3, bloom ? derived.b.tex : blank);
          kit.bindTexture(gl, 4, kit.noise(gl));
          const base = f.base, area = L.area;
          const jitter = f.frameIndex * 0.6180339887;
          main.use().i1('uTex', 0).i1('uMask', 1).i1('uBloomA', 2).i1('uBloomB', 3).i1('uNoise', 4)
            .f2('uRes', f.width, f.height)
            .f4('uPic', pic.x * s, pic.y * s, pic.w * s, pic.h * s)
            .f4('uArea', area.left * s, area.top * s, area.width * s, area.height * s)
            .f2('uUvScale', f.uvScale[0], f.uvScale[1]).f2('uTexel', 1 / f.texW, 1 / f.texH)
            .f2('uCells', Math.max(8, f.mediaW / CELL), Math.max(8, f.mediaH / CELL))
            .f2('uCellsBig', Math.max(4, f.mediaW / CELL_BIG), Math.max(4, f.mediaH / CELL_BIG))
            .f3('uBase', base[0] / 255, base[1] / 255, base[2] / 255)
            .f3('uHazeTint', P.tint[0], P.tint[1], P.tint[2])
            .f3('uShadow', GRADE.shadow[0], GRADE.shadow[1], GRADE.shadow[2]).f3('uHighlight', GRADE.highlight[0], GRADE.highlight[1], GRADE.highlight[2])
            .f2('uGrainShift', dynamic ? (jitter * 0.37) % 1 : 0, dynamic ? (jitter * 0.61) % 1 : 0)
            .f1('uMirror', on('mirror') ? 1 : 0).f1('uTime', seconds % 1000).f1('uScale', s).f1('uHeavy', heavy ? 1 : 0)
            .f1('uTwinkle', lights ? P.twinkle : 0).f1('uHaze', dynamic && heavy && f.isStill && on('haze') ? HAZE * P.haze : 0).f1('uBloomAmt', bloom ? BLOOM * P.bloom : 0)
            .f1('uGrain', dynamic && heavy && on('grain') ? GRAIN * P.grain : 0).f1('uGrainSize', GRAIN_SIZE * Math.max(1, s * 0.8))
            .f1('uGrade', on('grade') ? P.grade : 0).f1('uContrast', GRADE.contrast).f1('uSaturation', GRADE.saturation)
            .f1('uVignette', VIGNETTE * P.vignette).f1('uFade', FADE * s)
            .f1('uBreath', BREATH).f1('uOffFloor', OFF_FLOOR).f1('uOffFrom', OFF_FROM).f1('uOffTo', OFF_TO);
          kit.draw(gl);
        }

        /** A still picture graded once, at the canvas size, into a target: redone only when the picture, the canvas or the layout changes. */
        function bake(f, pic, P) {
          const key = [f.width, f.height, pic.x, pic.y, pic.w, pic.h, f.scale, f.base.join(), srcId, !!derived, f.low, f.layout.area.top, f.layout.area.height].join('|');
          if (baked && bakedKey === key) return baked;
          disposeBaked();
          baked = kit.target(gl, f.width, f.height);
          baked.bind();
          drawMain(f, pic, P, false);
          gl.bindFramebuffer(gl.FRAMEBUFFER, null);
          bakedKey = key;
          return baked;
        }

        /** One live frame; false (and the classic pass after it) when it cannot be drawn. A failure switches the live effects off for this scene for good. */
        function drawLive(f, P, empty) {
          const off = (f.tuning && f.tuning.off) || [], on = (name) => off.indexOf(name) < 0;
          try {
            if (!curSrc) return false;
            const pic = f.layout.picture, s = f.scale;
            const base = f.isStill ? bake(f, pic, P).tex : null;
            // the grade of a film (a still's is baked); with no light, glint or craft to move, a still at the lowest tier still drifts: a zoom of a few per cent, one read
            const grade = { contrast: GRADE.contrast, saturation: GRADE.saturation, shadow: GRADE.shadow, highlight: GRADE.highlight, amount: on('grade') ? P.grade : 0,
              vignette: VIGNETTE * P.vignette, fade: FADE };
            const d = pictureDrift(f, pic, s);
            return live.draw(f, { src: curSrc, base, pic, grade, drift: d, empty: !!empty });
          } catch (e) {
            liveBroken = true; liveProblem = 'live effects off: ' + String(e && e.message || e).slice(0, 160);
            disposeBaked();
            gl.bindFramebuffer(gl.FRAMEBUFFER, null);
            return false;
          }
        }

        /** The slow camera drift as a transform of the baked picture (canvas uv): zoom about the scene's focus point and a few pixels of pan. */
        function pictureDrift(f, pic, s) {
          const d = kit.math.driftState(f.time, DRIFT, kit.math.driftDirection(f.info.name));
          return { zoom: d.zoom, pan: [d.pan[0] * DRIFT.panPx * s, -d.pan[1] * DRIFT.panPx * s],
            cx: clamp01((pic.x + f.info.focus[0] * pic.w) * s / f.width), cy: clamp01(1 - (pic.y + f.info.focus[1] * pic.h) * s / f.height) };
        }
        const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

        return {
          setSource(src) {
            disposeDerived();
            disposeBaked();
            if (live) live.invalidate();
            curSrc = { tex: src.tex, w: src.w, h: src.h, texW: src.texW, texH: src.texH, uvScale: src.uvScale, id: ++srcId, mipmapped: !!src.isStill };
            if (!src.isStill) return;
            try { build(src); } catch (e) { disposeDerived(); }
          },

          draw(f) {
            const info = f.info, P = presetFor(info, f.isVideo), heavy = !f.low;
            if (live && !liveBroken && f.live && f.live.on && f.live.cfg && f.motion && drawLive(f, P, false)) return;
            // the lowest tier with nothing live to draw (no block, or the page switched the extras off): the baked picture with its slow drift, so it is never at rest
            if (live && !liveBroken && f.low && f.isStill && f.motion && drawLive(f, P, true)) return;
            const off = (f.tuning && f.tuning.off) || [];
            const on = (name) => off.indexOf(name) < 0;
            const seconds = f.motion ? f.time : 0;
            const drifting = heavy && f.motion && f.isStill && P.drift > 0 && on('drift');
            const pic = pictureAt(f.layout, info, f.mediaW, f.mediaH, seconds, drifting, kit.math);
            kit.toCanvas(gl, f);
            drawMain(f, pic, P, true);
          },

          /** What a touch at (x, y) (CSS px in the container) does here: a ring on water, a glow with sparkles elsewhere; null when this scene has no live block. */
          pokeKind(q) {
            if (!live || liveBroken || !q.info.live || !q.layout || !q.layout.picture) return null;
            const pic = q.layout.picture, u = (q.x - pic.x) / pic.w, v = (q.y - pic.y) / pic.h;
            if (!(u >= 0 && u <= 1 && v >= 0 && v <= 1)) return null;
            return live.onWater(q.info.live, u, v) ? 'ripple' : 'glow';
          },
          liveBroken() { return liveBroken; },
          cost() { return live ? live.cost() : null; },
          problem() { return liveProblem; },

          dispose() {
            disposeDerived();
            disposeBaked();
            if (live) live.dispose();
            gl.deleteTexture(blank);
            main.dispose(); mask.dispose(); bright.dispose(); down.dispose(); blur.dispose();
          },
        };
      },

      // the no-WebGL approximation: the picture covers the area (never stretched), a soft vignette about the area that carries on below it,
      // a fade into the page background where the picture ends
      css(L, info, el) {
        const a = L.area, p = L.picture, c = L.container, rgb = (L.base || [9, 18, 27]).join(',');
        const rx = a.width / 2 * 1.45, ry = a.height / 2 * 1.45, dark = (VIGNETTE * 1.25).toFixed(2);
        const vignette = el('div', { position: 'absolute', left: '0px', top: '0px', width: '100%', height: '100%', pointerEvents: 'none',
          background: 'radial-gradient(' + px(rx) + ' ' + px(ry) + ' at ' + px(a.left + a.width / 2) + ' ' + px(a.top + a.height / 2) + ', rgba(0,0,0,0) 38%, rgba(0,0,0,' + dark + ') 100%)' });
        const above = [vignette];
        if (p.y + p.h < c.h - 1) {
          const top = Math.max(0, p.y + p.h - FADE);
          above.push(el('div', { position: 'absolute', left: '0px', width: '100%', top: px(top), height: px(c.h - top), pointerEvents: 'none',
            background: 'linear-gradient(to bottom, rgba(' + rgb + ',0) 0px, rgb(' + rgb + ') ' + px(p.y + p.h - top) + ')' }));
        }
        return { below: [], above, pixelated: false };
      },
    };
  }

  const stage = global.SceneStage;
  if (stage && typeof stage.register === 'function') stage.register('photo', factory);
  if (typeof module !== 'undefined' && module.exports) module.exports = { factory, photoLayout, pictureAt, placePicture, presetFor, PRESETS, DRIFT, BREATH, OFF_FLOOR, HAZE, GRAIN, VIGNETTE, FULL_COVER_LIMIT };
})(typeof window !== 'undefined' ? window : globalThis);
