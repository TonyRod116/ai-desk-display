/*
 * LCD look: a handheld's colour screen (WebGL 1; see scene-stage.js for the contract). Made for the game-boy still.
 *
 *   - every SOURCE pixel is one lit cell of the grid (period = one source pixel): a flat colour sampled at the cell's centre, a thin
 *     black gap between cells and, where the cell is big enough on the device (pixel ratio 2), three faint RGB sub-pixel stripes;
 *   - an LCD gamut: a little less saturated, black lifted a touch, a cool cast, highlights a hair below paper white;
 *   - backlight bleed along the edges (stronger at the bottom and in the corners), a faint reflection, a soft vignette;
 *   - soft ghosting when the source is a video (the previous frame lingers, as in a slow panel);
 *   - a thin dark frame with rounded corners and a soft shadow; the whole frame is contained in the area.
 * Quality: 'low' keeps the grid and the frame and drops the sub-pixel stripes, the bleed and the ghosting.
 */
(function (global) {
  'use strict';

  /* ---- tuning knobs ----------------------------------------------------------------------------------------------------- */
  const BEZEL = 0.014;            // frame thickness, share of the screen's width
  const RADIUS = 0.020;           // corner radius of the screen, share of its width
  const GAP = 0.035;              // black matrix: share of a cell lost on each side before the edge softens (a gap thinner than a pixel)
  const GAP_LEVEL = 0.40;         // how bright the gap between two cells is, against the cells (at full visibility)
  const SUB = 0.09;               // strength of the RGB sub-pixel stripes inside a cell (luminance neutral): a whisper
  const GHOST_TAU = 40;           // response time of the panel in ms: the share of the previous frame left after one frame is exp(-frame interval / this)
  const GHOST_MAX = 0.35;         // and never more than this, however fast the video
  const BLEED = 0.040;            // backlight bleed along the edges
  const SATURATION = 0.95;        // LCD gamut: a bit duller than the file
  const BLACK = 0.012;            // lifted black
  const TINT = [0.982, 1.0, 0.99];   // cool cast
  const WHITE = 0.975;            // highlights stay a hair below paper white
  const VIGNETTE = 0.10;
  const REFLECT = 0.020;
  const SHADOW = 0.42;            // the drop shadow under the frame
  const SHADOW_MARGIN = 0.07;     // canvas margin for the shadow, share of the frame's width

  const FS = function (lib) {
    return [
      'uniform sampler2D uTex; uniform sampler2D uPrev; uniform sampler2D uNoise;',
      'uniform vec2 uRes; uniform vec4 uFrame; uniform vec4 uScreen; uniform vec2 uSrc;',
      'uniform float uRadius, uBezel, uDpr, uGap, uGapLevel, uSub, uGhost, uBleed, uSat, uBlack, uWhite, uVignette, uReflect, uShadow, uDetail;',
      'uniform vec3 uTint;',
      lib,
      'void main() {',
      '  vec2 p = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);',
      '  vec2 fc = uFrame.xy + 0.5 * uFrame.zw;',
      '  float rOuter = uRadius + uBezel;',
      '  float dOuter = sdRoundBox(p - fc, 0.5 * uFrame.zw, rOuter);',
      '  float inside = 1.0 - smoothstep(-0.7, 0.7, dOuter);',
      '  float dSh = sdRoundBox(p - fc - vec2(0.0, 0.010 * uFrame.z), 0.5 * uFrame.zw, rOuter);',
      '  float sh = exp(-max(dSh, 0.0) / (0.016 * uFrame.z)) * uShadow;',
      '  vec4 shadow = vec4(0.0, 0.0, 0.0, sh * smoothstep(0.0, 0.03 * uFrame.z, min(min(p.x, uRes.x - p.x), min(p.y, uRes.y - p.y))));',
      '  if (inside <= 0.0) { gl_FragColor = shadow; return; }',
      '  vec2 sc = uScreen.xy + 0.5 * uScreen.zw;',
      '  float dGlass = sdRoundBox(p - sc, 0.5 * uScreen.zw, uRadius);',
      '  float glassMask = 1.0 - smoothstep(-0.7, 0.7, dGlass);',
      '  vec3 rgb = vec3(0.030, 0.032, 0.038);',
      '  vec2 n = gradRoundBox(p - fc, 0.5 * uFrame.zw, rOuter);',
      '  rgb += vec3(0.5, 0.52, 0.58) * 0.16 * smoothstep(-0.1, 0.95, dot(n, normalize(vec2(-0.55, -0.85)))) * (1.0 - smoothstep(0.0, 2.0 * uDpr, -dOuter));',
      '  if (glassMask > 0.0) {',
      '    vec2 g = (p - uScreen.xy) / uScreen.zw;',
      '    vec2 uv = clamp(g, 0.0, 1.0);',
      '    vec2 sp = uv * uSrc;',
      '    vec2 cell = fract(sp);',
      '    vec2 centre = (floor(min(sp, uSrc - 0.001)) + 0.5) / uSrc;',
      '    vec3 c = texture2D(uTex, centre).rgb;',
      '    if (uGhost > 0.0) c = mix(c, texture2D(uPrev, centre).rgb, uGhost);',
      '    float lum = dot(c, vec3(0.299, 0.587, 0.114));',
      '    c = mix(vec3(lum), c, uSat);',
      '    c = (c * uWhite * uTint) * (1.0 - uBlack) + vec3(uBlack);',
      '    vec2 cellPx = uScreen.zw / uSrc;',
      '    vec2 aa = 0.6 / cellPx;',
      '    vec2 lo = smoothstep(vec2(uGap), vec2(uGap) + aa, cell);',
      '    vec2 hi = 1.0 - smoothstep(vec2(1.0 - uGap) - aa, vec2(1.0 - uGap), cell);',
      '    float cover = lo.x * hi.x * lo.y * hi.y;',
      '    vec3 stripe = 1.0 - smoothstep(0.12, 0.22, abs(cell.x - vec3(1.0 / 6.0, 0.5, 5.0 / 6.0)));',
      '    vec3 lit = c * (1.0 + uSub * (stripe / 0.34 - 1.0));',
      '    vec3 pic = lit * mix(uGapLevel, 1.0, cover);',
      '    vec2 e = min(uv, 1.0 - uv);',
      '    float bleed = (exp(-e.x * 26.0) + exp(-e.y * 26.0) * (1.0 + 0.9 * uv.y) + exp(-(e.x + e.y) * 14.0) * 0.8) * uBleed;',
      '    pic += vec3(0.78, 0.86, 1.0) * bleed * (0.35 + 0.65 * uDetail);',
      '    vec2 q = g * 2.0 - 1.0;',
      '    pic *= 1.0 - uVignette * pow(clamp(dot(q, q) * 0.5, 0.0, 1.0), 1.5);',
      '    pic += vec3(0.80, 0.86, 1.0) * (1.0 - smoothstep(0.0, 0.9, length((q - vec2(-0.50, -0.65)) * vec2(0.9, 1.3)))) * uReflect;',
      '    pic *= mix(0.62, 1.0, smoothstep(0.0, 0.5 * uBezel + 3.0 * uDpr, -dGlass));',
      '    pic += (texture2D(uNoise, gl_FragCoord.xy / 256.0).b - 0.5) * (1.5 / 255.0);',
      '    rgb = mix(rgb, pic, glassMask);',
      '  }',
      '  gl_FragColor = vec4(rgb * inside + shadow.rgb * (1.0 - inside), inside + shadow.a * (1.0 - inside));',
      '}',
    ].join('\n');
  };

  function lcdLayout(ctx, kit) {
    const m = kit.math.monitorLayout(ctx.area, ctx.media.w, ctx.media.h, BEZEL);
    const margin = m.frame.w * SHADOW_MARGIN, c = ctx.container;
    const x0 = Math.max(0, m.frame.x - margin), y0 = Math.max(0, m.frame.y - margin);
    const x1 = Math.min(c.w, m.frame.x + m.frame.w + margin), y1 = Math.min(c.h, m.frame.y + m.frame.h + margin * 1.6);
    return {
      canvas: { x: x0, y: y0, w: Math.max(1, x1 - x0), h: Math.max(1, y1 - y0) }, frame: m.frame, screen: m.screen, picture: m.screen, bezel: m.bezel,
      radius: RADIUS * m.screen.w, container: c, grid: kit.math.sourceGrid(ctx.media.w, ctx.media.h, ctx.info.media.rows),
    };
  }

  /** How much of the previous frame a slow LCD still shows: a 30 fps film smears, a 6 fps one does not (the panel is long since settled). */
  function ghostFor(frameMs) {
    return Math.min(GHOST_MAX, Math.exp(-Math.max(0, frameMs) / GHOST_TAU));
  }

  /** How visible the grid is for a cell of `cellPx` device pixels: faint when the cell is tiny, whole at 4 pixels and above. */
  function gridVisibility(cellPx) {
    const t = Math.min(1, Math.max(0, (cellPx - 2) / 2));
    return t * t * (3 - 2 * t);
  }

  function factory(kit) {
    const px = kit.px;
    const liveApi = global.SceneStageLive;
    const touchOk = !!(liveApi && liveApi.createTouchKit && liveApi.compositeTouch);
    const PALETTE = { glow: [0.62, 0.78, 0.30], ring: [0.78, 0.95, 0.45], spark: [[0.55, 0.75, 0.25], [0.95, 1.0, 0.75]] };      // a lime flare on the green LCD
    return {
      name: 'lcd',
      opaque: false,
      history: 1,
      mipmapStills: false,
      animated() { return false; },

      layout(ctx) { return lcdLayout(ctx, kit); },

      create(gl) {
        const prog = kit.program(gl, FS(kit.glsl.lib));
        // a touch never re-runs this look's shader: the picture is drawn once into `cache`, then copied to the canvas with the glow, ring and sparks on top
        const touch = touchOk ? liveApi.createTouchKit(kit, gl) : null;
        let cache = null, cacheValid = false;

        function drawLook(f, target) {
          const L = f.layout, c = L.canvas, s = f.scale, grid = L.grid, heavy = !f.low;
          const cellPx = L.screen.w * s / grid.cols;
          const vis = gridVisibility(cellPx);
          if (target) target.bind(); else kit.toCanvas(gl, f);
          gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
          kit.bindTexture(gl, 0, f.tex);
          kit.bindTexture(gl, 1, f.texPrev || f.tex);
          kit.bindTexture(gl, 2, kit.noise(gl));
          prog.use().i1('uTex', 0).i1('uPrev', 1).i1('uNoise', 2)
            .f2('uRes', f.width, f.height)
            .f4('uFrame', (L.frame.x - c.x) * s, (L.frame.y - c.y) * s, L.frame.w * s, L.frame.h * s)
            .f4('uScreen', (L.screen.x - c.x) * s, (L.screen.y - c.y) * s, L.screen.w * s, L.screen.h * s)
            .f2('uSrc', grid.cols, grid.rows)
            .f1('uRadius', L.radius * s).f1('uBezel', L.bezel * s).f1('uDpr', s)
            .f1('uGap', GAP).f1('uGapLevel', 1 - (1 - GAP_LEVEL) * vis)
            .f1('uSub', heavy ? SUB * vis : 0)
            .f1('uGhost', heavy && f.isVideo && f.texPrev ? ghostFor(f.frameMs) : 0)
            .f1('uBleed', BLEED).f1('uDetail', heavy ? 1 : 0)
            .f1('uSat', SATURATION).f1('uBlack', BLACK).f1('uWhite', WHITE).f3('uTint', TINT[0], TINT[1], TINT[2])
            .f1('uVignette', VIGNETTE).f1('uReflect', REFLECT).f1('uShadow', SHADOW);
          kit.draw(gl);
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
          dispose() { if (cache) cache.dispose(); if (touch) touch.dispose(); prog.dispose(); },
        };
      },

      // the no-WebGL approximation: pixelated picture, a cell grid in CSS, a thin frame with a shadow
      css(L, info, el) {
        const f = L.frame, s = L.screen, cw = s.w / L.grid.cols, ch = s.h / L.grid.rows, rad = px(L.radius);
        const frame = el('div', { position: 'absolute', left: px(f.x), top: px(f.y), width: px(f.w), height: px(f.h), borderRadius: px(L.radius + L.bezel), pointerEvents: 'none',
          background: '#08090c', boxShadow: '0 ' + px(f.w * 0.012) + ' ' + px(f.w * 0.035) + ' rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.12)' });
        const grid = el('div', { position: 'absolute', left: px(s.x), top: px(s.y), width: px(s.w), height: px(s.h), borderRadius: rad, pointerEvents: 'none',
          backgroundImage: 'linear-gradient(to right, rgba(0,0,0,.20) 0%, rgba(0,0,0,0) 14%, rgba(0,0,0,0) 100%), linear-gradient(to bottom, rgba(0,0,0,.20) 0%, rgba(0,0,0,0) 14%, rgba(0,0,0,0) 100%)',
          backgroundSize: cw.toFixed(3) + 'px 100%, 100% ' + ch.toFixed(3) + 'px' });
        const glass = el('div', { position: 'absolute', left: px(s.x), top: px(s.y), width: px(s.w), height: px(s.h), borderRadius: rad, pointerEvents: 'none',
          background: 'radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 62%, rgba(0,0,0,.22) 100%)', boxShadow: 'inset 0 0 ' + px(L.bezel * 1.2) + ' rgba(0,0,0,.45)' });
        return { below: [frame], above: [grid, glass], pixelated: true };
      },
    };
  }

  const stage = global.SceneStage;
  if (stage && typeof stage.register === 'function') stage.register('lcd', factory);
  if (typeof module !== 'undefined' && module.exports) module.exports = { factory, lcdLayout, gridVisibility, ghostFor, BEZEL, RADIUS, GAP, SUB, GHOST_MAX };
})(typeof window !== 'undefined' ? window : globalThis);
