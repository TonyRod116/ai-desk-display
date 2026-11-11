/*
 * CRT look: a pixel-art scene on a well-adjusted arcade monitor (WebGL 1 fragment shaders; see scene-stage.js for the contract).
 *
 * What the shader does, in the order the light travels:
 *   - sharp-bilinear horizontal sampling on the SOURCE pixel grid (crisp pixels, no shimmer at non-integer scales);
 *   - scanlines aligned to the source rows: a Gaussian beam per row whose width follows the pixel's brightness (bright pixels fatten
 *     the beam and close the gaps), summed from the two nearest rows in linear light, widened by the screen pixel's own size so a
 *     small area does not beat against the pixel grid;
 *   - aperture-grille RGB mask on device pixels (luminance neutral, strong at pixel ratio 2, gentle at 1);
 *   - bloom/halation from a tiny blurred bright-pass texture, barrel curvature, rounded glass, vignette, a faint reflection;
 *   - the monitor: dark bezel with a soft inner shadow and a rim light, and a faint glow spilling into the room tinted by the picture.
 * Quality: the 'low' level drops the mask, the bloom passes and the tinted glow first; scanlines, curvature and the bezel stay.
 */
(function (global) {
  'use strict';

  /* ---- tuning knobs: all by eye, all here ------------------------------------------------------------------------------- */
  const BEZEL = 0.034;            // bezel thickness, share of the screen's width
  const GLASS_RADIUS = 0.058;     // corner radius of the glass, share of the screen's width
  const CURVE = 0.034;            // barrel distortion of the picture (0 = flat glass): a few percent
  const SIGMA_DARK = 0.20;        // beam half-width in source rows for a dark pixel: clear black gaps between the lines
  const SIGMA_BRIGHT = 0.37;      // ... and for a bright pixel: the beam swells and the gaps nearly close
  const GAIN = 1.25;              // makes up the light the gaps take away so the picture is not dark
  const H_SOFT = 0.20;            // horizontal softness, in source pixels (never less than one screen pixel)
  const MASK_HI = 0.15, MASK_LO = 0.07;   // aperture grille strength at pixel ratio >= 2 and at 1 (luminance neutral)
  const BLOOM = 0.60;             // bloom strength
  const BLOOM_THRESHOLD = 0.30;   // linear level above which light blooms
  const GLOW = 0.30;              // warm light the monitor throws on its surroundings (share of alpha at the bezel's edge)
  const GLOW_REACH = 0.07;        // how far the glow reaches, share of the frame's width
  const GLOW_MARGIN = 0.20;       // canvas margin around the frame for the glow, share of the frame's width
  const VIGNETTE = 0.30;          // corner darkening of the glass
  const REFLECT = 0.030;          // faint reflection of the room on the glass
  const FLICKER = 0.004;          // barely perceptible phosphor breathing; 0 = none
  const SATURATION = 1.06;        // a CRT's phosphors are a touch richer than the file

  const BRIGHT_FS = [
    'uniform sampler2D uTex; uniform vec2 uOut; uniform vec2 uStep; uniform float uThreshold;',
    'void main() {',
    '  vec2 uv = gl_FragCoord.xy / uOut;',
    '  vec3 s = texture2D(uTex, uv + vec2(-uStep.x, -uStep.y)).rgb + texture2D(uTex, uv + vec2(uStep.x, -uStep.y)).rgb',
    '         + texture2D(uTex, uv + vec2(-uStep.x, uStep.y)).rgb + texture2D(uTex, uv + vec2(uStep.x, uStep.y)).rgb;',
    '  vec3 c = s * 0.25; c = c * c;',
    '  gl_FragColor = vec4(sqrt(max(c - vec3(uThreshold), vec3(0.0))), 1.0);',
    '}',
  ].join('\n');

  // 9-tap Gaussian, sigma 2 texels, along uDir (the weights are exp(-x^2/8) normalised)
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

  // the picture's average colour field, 16x12 texels: tints the glow, the bezel's lip and the room
  const AMBIENT_FS = [
    'uniform sampler2D uTex; uniform vec2 uOut;',
    'void main() {',
    '  vec2 uv = gl_FragCoord.xy / uOut; vec3 sum = vec3(0.0);',
    '  for (int j = 0; j < 4; j++) { for (int i = 0; i < 4; i++) {',
    '    vec2 o = (vec2(float(i), float(j)) - 1.5) / 4.0 / uOut; vec3 t = texture2D(uTex, uv + o).rgb; sum += t * t; } }',
    '  gl_FragColor = vec4(sqrt(sum / 16.0), 1.0);',
    '}',
  ].join('\n');

  const MAIN_FS = function (lib) {
    return [
      'uniform sampler2D uTex; uniform sampler2D uBloom; uniform sampler2D uAmbient; uniform sampler2D uNoise;',
      'uniform vec2 uRes; uniform vec4 uFrame; uniform vec4 uScreen; uniform vec2 uSrc;',
      'uniform float uNative, uRadius, uBezel, uDpr, uTime, uMask, uBloomAmt, uGlowAmt, uGlowLen, uGlowFade, uCurve, uHSoft, uVignette, uReflect, uFlicker, uAmbientOn;',
      'uniform float uSigmaDark, uSigmaBright, uGain, uSat;',
      'uniform vec3 uGlowFlat;',
      lib,
      'void main() {',
      '  vec2 p = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);',
      '  vec2 fc = uFrame.xy + 0.5 * uFrame.zw;',
      '  float rOuter = uRadius + uBezel;',
      '  float dOuter = sdRoundBox(p - fc, 0.5 * uFrame.zw, rOuter);',
      '  float inside = 1.0 - smoothstep(-0.7, 0.7, dOuter);',
      // the glass: the picture's own outline after the barrel warp, rounded; the bezel starts exactly where the picture ends
      '  vec2 g = (p - uScreen.xy) / uScreen.zw;',
      '  vec2 q0 = g * 2.0 - 1.0;',
      '  vec2 q = q0 * (1.0 + uCurve * dot(q0, q0)) / (1.0 + uCurve);',
      '  float dGlass = sdRoundBox(q * 0.5 * uScreen.zw, 0.5 * uScreen.zw, uRadius);',
      '  vec2 gn = clamp(g, 0.0, 1.0);',
      // ---- the light the monitor throws on the room: soft, tinted by the picture, gone before the canvas ends
      '  vec4 glow = vec4(0.0);',
      '  if (dOuter > -2.0) {',
      '    vec3 local = texture2D(uAmbient, gn).rgb;',
      '    vec3 mean = 0.25 * (texture2D(uAmbient, vec2(0.25, 0.3)).rgb + texture2D(uAmbient, vec2(0.75, 0.3)).rgb + texture2D(uAmbient, vec2(0.25, 0.7)).rgb + texture2D(uAmbient, vec2(0.75, 0.7)).rgb);',
      '    vec3 am = mix(mean, local, 0.45);',
      '    vec3 lin = mix(uGlowFlat, am * am * 1.5, uAmbientOn);',
      '    float edge = min(min(p.x, uRes.x - p.x), min(p.y, uRes.y - p.y));',
      '    float ga = clamp(uGlowAmt * exp(-max(dOuter, 0.0) / uGlowLen) * smoothstep(0.0, uGlowFade, edge), 0.0, 1.0);',
      '    glow = vec4(sqrt(lin) * ga, ga);',
      '  }',
      '  if (inside <= 0.0) { gl_FragColor = glow; return; }',
      '  float glassMask = 1.0 - smoothstep(-0.7, 0.7, dGlass);',
      '  vec3 rgb = vec3(0.0);',
      // ---- the plastic bezel
      '  if (glassMask < 1.0) {',
      '    vec3 bez = vec3(0.046, 0.049, 0.056);',
      '    float depth = clamp(dGlass / max(uBezel, 1.0), 0.0, 1.0);',
      '    bez *= mix(0.46, 1.06, smoothstep(0.0, 0.9, depth));',
      '    bez *= 1.0 + 0.16 * (0.5 - (p.y - uFrame.y) / uFrame.w);',
      '    vec2 n = gradRoundBox(p - fc, 0.5 * uFrame.zw, rOuter);',
      '    float rim = smoothstep(-0.1, 0.95, dot(n, normalize(vec2(-0.55, -0.85)))) * (1.0 - smoothstep(0.0, 2.4 * uDpr, -dOuter));',
      '    bez += vec3(0.55, 0.56, 0.62) * rim * 0.20;',
      '    vec3 lip = texture2D(uAmbient, gn).rgb;',
      '    bez += lip * exp(-max(dGlass, 0.0) / (0.34 * uBezel)) * 0.16 * uAmbientOn;',
      '    rgb = bez;',
      '  }',
      // ---- the picture on the glass
      '  if (glassMask > 0.0) {',
      '    vec2 uv = q * 0.5 + 0.5;',
      '    vec2 sp = uv * uSrc;',
      '    float tpp = uSrc.x / uScreen.z;',
      '    float footY = uSrc.y / uScreen.w;',
      '    float trans = mix(1.0, max(tpp, uHSoft), uNative);',
      '    float seam = floor(sp.x + 0.5);',
      '    float sx = seam + clamp((sp.x - seam) / trans, -0.5, 0.5);',
      '    float xn = sx / uSrc.x;',
      '    float row = floor(sp.y);',
      '    float fy = sp.y - row;',
      '    float d0 = fy - 0.5;',
      '    float dir = d0 < 0.0 ? -1.0 : 1.0;',
      '    float d1 = 1.0 - abs(d0);',
      '    vec3 t0 = texture2D(uTex, vec2(xn, (row + 0.5) / uSrc.y)).rgb;',
      '    vec3 t1 = texture2D(uTex, vec2(xn, (row + 0.5 + dir) / uSrc.y)).rgb;',
      '    vec3 s0 = mix(vec3(uSigmaDark), vec3(uSigmaBright), t0);',
      '    vec3 s1 = mix(vec3(uSigmaDark), vec3(uSigmaBright), t1);',
      '    float foot = footY * footY / 12.0;',
      '    vec3 e0 = sqrt(s0 * s0 + foot);',
      '    vec3 e1 = sqrt(s1 * s1 + foot);',
      '    vec3 w0 = (s0 / e0) * exp(-0.5 * d0 * d0 / (e0 * e0));',
      '    vec3 w1 = (s1 / e1) * exp(-0.5 * d1 * d1 / (e1 * e1));',
      '    vec3 col = (t0 * t0 * w0 + t1 * t1 * w1) * uGain;',
      '    float lum = dot(col, vec3(0.299, 0.587, 0.114));',
      '    col = mix(vec3(lum), col, uSat);',
      '    col *= 1.0 + uMask * cos(6.2831853 * (gl_FragCoord.x / 3.0 - vec3(0.0, 1.0, 2.0) / 3.0));',
      '    vec3 bl = texture2D(uBloom, clamp(uv, 0.0, 1.0)).rgb;',
      '    col += bl * bl * uBloomAmt;',
      '    vec3 over = max(col - 0.85, vec3(0.0));',
      '    col = min(col, vec3(0.85)) + 0.15 * over / (over + 0.15);',
      '    vec3 pic = fromLin(col);',
      '    pic *= 1.0 - uVignette * pow(clamp(dot(q0, q0) * 0.5, 0.0, 1.0), 1.4);',
      '    pic *= mix(0.55, 1.0, smoothstep(0.0, 0.40 * uBezel + 3.0 * uDpr, -dGlass));',
      '    pic += vec3(0.80, 0.86, 1.0) * (1.0 - smoothstep(0.0, 0.85, length((q0 - vec2(-0.55, -0.62)) * vec2(0.95, 1.25)))) * uReflect;',
      '    pic *= 1.0 + uFlicker * sin(uTime * 3.7);',
      '    pic += (texture2D(uNoise, gl_FragCoord.xy / 256.0).b - 0.5) * (1.5 / 255.0);',
      '    rgb = mix(rgb, pic, glassMask);',
      '  }',
      '  gl_FragColor = vec4(rgb * inside + glow.rgb * (1.0 - inside), inside + glow.a * (1.0 - inside));',
      '}',
    ].join('\n');
  };

  /* ---- pure geometry (also used by the tests) ---------------------------------------------------------------------------- */
  function maskStrength(scale) {
    const t = Math.min(1, Math.max(0, scale - 1));
    return MASK_LO + (MASK_HI - MASK_LO) * t * t * (3 - 2 * t);
  }

  function crtLayout(ctx, kit) {
    const m = kit.math.monitorLayout(ctx.area, ctx.media.w, ctx.media.h, BEZEL);
    const margin = m.frame.w * GLOW_MARGIN, c = ctx.container;
    const x0 = Math.max(0, m.frame.x - margin), y0 = Math.max(0, m.frame.y - margin);
    const x1 = Math.min(c.w, m.frame.x + m.frame.w + margin), y1 = Math.min(c.h, m.frame.y + m.frame.h + margin);
    return {
      canvas: { x: x0, y: y0, w: Math.max(1, x1 - x0), h: Math.max(1, y1 - y0) }, frame: m.frame, screen: m.screen, picture: m.screen, bezel: m.bezel,
      radius: GLASS_RADIUS * m.screen.w, container: c, grid: kit.math.sourceGrid(ctx.media.w, ctx.media.h, ctx.info.media.rows),
    };
  }

  /* ---- the look ---------------------------------------------------------------------------------------------------------- */
  function factory(kit) {
    const px = kit.px;
    const liveApi = global.SceneStageLive;
    const touchOk = !!(liveApi && liveApi.createTouchKit && liveApi.compositeTouch);
    const PALETTE = { glow: [1.0, 0.72, 0.38], ring: [1.0, 0.82, 0.55], spark: [[1.0, 0.35, 0.12], [1.0, 0.92, 0.6]] };      // a warm phosphor flare, sparks that cool from white to orange
    return {
      name: 'crt',
      opaque: false,
      history: 0,
      mipmapStills: false,

      layout(ctx) { return crtLayout(ctx, kit); },

      // a still crt picture never moves; a video draws on its own frames
      animated() { return false; },

      create(gl) {
        const main = kit.program(gl, MAIN_FS(kit.glsl.lib));
        // a touch never re-runs this look's shader: the picture is drawn once into `cache`, then copied to the canvas with the glow, ring and sparks on top
        const touch = touchOk ? liveApi.createTouchKit(kit, gl) : null;
        let cache = null, cacheValid = false;
        const bright = kit.program(gl, BRIGHT_FS), blur = kit.program(gl, BLUR_FS), ambient = kit.program(gl, AMBIENT_FS);
        let targets = null;

        function ensureTargets(cols, rows) {
          const bw = Math.max(16, Math.round(cols / 2)), bh = Math.max(12, Math.round(rows / 2));
          if (targets && targets.bw === bw && targets.bh === bh) return targets;
          if (targets) { targets.a.dispose(); targets.b.dispose(); targets.e.dispose(); }
          targets = { bw, bh, a: kit.target(gl, bw, bh), b: kit.target(gl, bw, bh), e: kit.target(gl, 16, 12) };
          return targets;
        }

        function passes(f, grid) {
          const t = ensureTargets(grid.cols, grid.rows);
          kit.bindTexture(gl, 0, f.tex);
          t.a.bind();
          bright.use().i1('uTex', 0).f2('uOut', t.bw, t.bh).f2('uStep', 0.5 / grid.cols, 0.5 / grid.rows).f1('uThreshold', BLOOM_THRESHOLD);
          kit.draw(gl);
          kit.bindTexture(gl, 0, t.a.tex);
          t.b.bind();
          blur.use().i1('uTex', 0).f2('uOut', t.bw, t.bh).f2('uDir', 1, 0);
          kit.draw(gl);
          kit.bindTexture(gl, 0, t.b.tex);
          t.a.bind();
          blur.f2('uDir', 0, 1);
          kit.draw(gl);
          kit.bindTexture(gl, 0, f.tex);
          t.e.bind();
          ambient.use().i1('uTex', 0).f2('uOut', 16, 12);
          kit.draw(gl);
          return t;
        }

        return {
          draw(f) {
            const pokes = touch && f.live && f.live.pokes && f.live.pokes.length;
            if (!pokes) { drawLook(f, null); return; }
            if (!cache || cache.w !== f.width || cache.h !== f.height) { if (cache) cache.dispose(); cache = kit.target(gl, f.width, f.height); cacheValid = false; }
            if (f.fresh || !cacheValid) { drawLook(f, cache); cacheValid = true; }
            liveApi.compositeTouch(touch, gl, kit, f, f.layout, cache.tex, f.layout.grid && f.layout.grid.cols, PALETTE);
          },
          /** A touch on the picture area bumps it. It asks nothing of this look's geometry (the stage already checked the touch is inside the area), so it survives a look without a frame. */
          pokeKind() { return touchOk ? 'bump' : null; },
          dispose() {
            if (cache) cache.dispose();
            if (touch) touch.dispose();
            if (targets) { targets.a.dispose(); targets.b.dispose(); targets.e.dispose(); targets = null; }
            main.dispose(); bright.dispose(); blur.dispose(); ambient.dispose();
          },
        };

        function drawLook(f, target) {
          {
            const L = f.layout, grid = L.grid, c = L.canvas, s = f.scale, heavy = !f.low;
            const t = heavy ? passes(f, grid) : null;
            if (target) target.bind(); else kit.toCanvas(gl, f);
            gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
            kit.bindTexture(gl, 0, f.tex);
            if (t) { kit.bindTexture(gl, 1, t.a.tex); kit.bindTexture(gl, 2, t.e.tex); } else { kit.bindTexture(gl, 1, f.tex); kit.bindTexture(gl, 2, f.tex); }
            kit.bindTexture(gl, 3, kit.noise(gl));
            main.use().i1('uTex', 0).i1('uBloom', 1).i1('uAmbient', 2).i1('uNoise', 3)
              .f2('uRes', f.width, f.height)
              .f4('uFrame', (L.frame.x - c.x) * s, (L.frame.y - c.y) * s, L.frame.w * s, L.frame.h * s)
              .f4('uScreen', (L.screen.x - c.x) * s, (L.screen.y - c.y) * s, L.screen.w * s, L.screen.h * s)
              .f2('uSrc', grid.cols, grid.rows).f1('uNative', grid.native ? 1 : 0)
              .f1('uRadius', L.radius * s).f1('uBezel', L.bezel * s).f1('uDpr', s).f1('uTime', f.time % 600)
              .f1('uMask', heavy ? maskStrength(s) : 0).f1('uBloomAmt', heavy ? BLOOM : 0)
              .f1('uGlowAmt', GLOW).f1('uGlowLen', Math.max(8, GLOW_REACH * L.frame.w * s)).f1('uGlowFade', Math.max(8, 0.5 * GLOW_MARGIN * L.frame.w * s)).f1('uAmbientOn', heavy ? 1 : 0)
              .f3('uGlowFlat', 0.30, 0.17, 0.08)
              .f1('uCurve', CURVE).f1('uHSoft', H_SOFT).f1('uVignette', VIGNETTE).f1('uReflect', REFLECT)
              .f1('uFlicker', f.motion && f.isVideo ? FLICKER : 0)
              .f1('uSigmaDark', SIGMA_DARK).f1('uSigmaBright', SIGMA_BRIGHT).f1('uGain', GAIN).f1('uSat', SATURATION);
            kit.draw(gl);
          }
        }
      },

      // the no-WebGL approximation: a dark bezel, row-aligned scanlines, a vignette; the video or picture is scaled with nearest neighbour
      css(L, info, el) {
        const f = L.frame, s = L.screen, row = s.h / L.grid.rows, rad = px(L.radius);
        const frame = el('div', { position: 'absolute', left: px(f.x), top: px(f.y), width: px(f.w), height: px(f.h), borderRadius: px(L.radius + L.bezel), pointerEvents: 'none',
          background: 'linear-gradient(180deg, #181a1f, #0a0b0e)', boxShadow: '0 0 ' + px(f.w * 0.07) + ' rgba(255,170,90,.13), inset 0 1px 0 rgba(255,255,255,.10)' });
        const lines = el('div', { position: 'absolute', left: px(s.x), top: px(s.y), width: px(s.w), height: px(s.h), borderRadius: rad, pointerEvents: 'none',
          backgroundImage: 'linear-gradient(to bottom, rgba(0,0,0,0) 0%, rgba(0,0,0,0) 38%, rgba(0,0,0,.36) 100%)', backgroundSize: '100% ' + row.toFixed(3) + 'px' });
        const vignette = el('div', { position: 'absolute', left: px(s.x), top: px(s.y), width: px(s.w), height: px(s.h), borderRadius: rad, pointerEvents: 'none',
          background: 'radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 58%, rgba(0,0,0,.42) 100%)', boxShadow: 'inset 0 0 ' + px(L.bezel * 1.4) + ' rgba(0,0,0,.55)' });
        return { below: [frame], above: [lines, vignette], pixelated: true };
      },
    };
  }

  const stage = global.SceneStage;
  if (stage && typeof stage.register === 'function') stage.register('crt', factory);
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { factory, maskStrength, crtLayout, BEZEL, GLASS_RADIUS, CURVE, SIGMA_DARK, SIGMA_BRIGHT, GAIN, MASK_HI, MASK_LO, GLOW_MARGIN };
  }
})(typeof window !== 'undefined' ? window : globalThis);
