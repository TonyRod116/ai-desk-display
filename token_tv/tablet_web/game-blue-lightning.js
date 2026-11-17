/* BLUE LIGHTNING: a self-flying Lynx-style aerial scene for the tablet.
 * Original sprites, when available, are a separately prepared private atlas;
 * this file contains no cartridge bytes or account data. The picture adapts
 * to the normal dock and picture mode, and all action is decorative. */
(function (global) {
  'use strict';

  const W = 200, H = 320, STEP = 1 / 30, CYCLE = 32, OVERSCAN = 16, PROJECTION = 120000;
  const CRUISE_SPEED = 6900, BOOST_SPEED = 9000;
  const finite = Number.isFinite;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const mix = (a, b, t) => a + (b - a) * t;
  const ease = (t) => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };
  const wrap = (v, period) => { const n = v % period; return n < 0 ? n + period : n; };

  /** The jet stays above the clock and quota overlay in both layouts. */
  function layout(bottom, bounds) {
    bottom = clamp(finite(bottom) ? bottom : H, 110, H);
    const full = ease((bottom - 190) / 100);
    let horizon = Math.round(bottom * .34);
    let planeY = Math.round(Math.max(horizon + 38, bottom - mix(70, 100, full)));
    if (!bounds) return { horizon, bottom, planeY };
    const side = Math.max(bounds.left, bounds.right), height = bounds.top + bounds.bottom;
    const baseScale = Math.min(1, (W / 2 - 25) / side, (bottom - 26) / height);
    const baseMin = bounds.top * baseScale + 1, baseMax = bottom - bounds.bottom * baseScale - 1;
    const basePlaneY = clamp(planeY, baseMin + 12, baseMax - 12);
    horizon = Math.min(horizon, Math.floor(basePlaneY - 23));
    // Compact layouts reserve a small strip of sky above the full plane
    // envelope. One scale is shared by every pose and stays unchanged at 150+.
    const sky = bottom < 150 ? 18 : 0;
    const planeScale = Math.min(baseScale, (bottom - 26 - sky) / height);
    const minPlaneY = bounds.top * planeScale + 1 + sky, maxPlaneY = bottom - bounds.bottom * planeScale - 1;
    planeY = clamp(planeY, minPlaneY + 12, maxPlaneY - 12);
    return { horizon, bottom, planeY, planeScale, minPlaneY, maxPlaneY, horizonOffset: planeY - basePlaneY };
  }

  // Each slot chooses its own destination, start and duration. A seeded hash
  // gives random-access, repeatable tests without a growing event history or a
  // short repeating choreography during a long-running scene.
  const FLIGHT_SLOT = 7.2, DEFAULT_SEED = 0x41b17;
  const ALTITUDE_ORDERS = [[-12, 0, 12], [-12, 12, 0], [0, -12, 12], [0, 12, -12], [12, -12, 0], [12, 0, -12]];
  function flightRandom(seed, slot, salt) {
    let n = (seed ^ Math.imul(slot + 1, 0x9e3779b9) ^ Math.imul(salt, 0x85ebca6b)) >>> 0;
    n ^= n >>> 16; n = Math.imul(n, 0x7feb352d); n ^= n >>> 15; n = Math.imul(n, 0x846ca68b); n ^= n >>> 16;
    return (n >>> 0) / 4294967296;
  }
  function flightTarget(seed, slot, vertical) {
    const key = vertical ? Math.floor(slot / 2) : slot;
    if (key < 0) return 0;
    if (vertical) {
      return ALTITUDE_ORDERS[Math.floor(flightRandom(seed, Math.floor(key / 3), 3) * ALTITUDE_ORDERS.length)][key % 3];
    }
    return (flightRandom(seed, key, 1) < .5 ? -1 : 1) * (12 + flightRandom(seed, key, 2) * 12);
  }
  function flightPath(time, seed) {
    const slot = Math.floor(Math.max(0, time) / FLIGHT_SLOT), elapsed = Math.max(0, time) - slot * FLIGHT_SLOT;
    const start = .6 + flightRandom(seed, slot, 4) * 2.5, duration = .45 + flightRandom(seed, slot, 5) * 1.8;
    const u = clamp((elapsed - start) / duration, 0, 1);
    const verticalDuration = Math.max(2.7, duration * 1.5), v = clamp((elapsed - start) / verticalDuration, 0, 1);
    const curve = u * u * u * (u * (u * 6 - 15) + 10), pulse = Math.pow(Math.sin(Math.PI * u), 2);
    const verticalCurve = v * v * v * (v * (v * 6 - 15) + 10), verticalPulse = Math.pow(Math.sin(Math.PI * v), 2);
    const x0 = flightTarget(seed, slot - 1, false), x1 = flightTarget(seed, slot, false);
    const y0 = flightTarget(seed, slot - 1, true), y1 = flightTarget(seed, slot, true);
    const vx = (x1 - x0) * 30 * u * u * (u - 1) * (u - 1) / duration;
    const y = mix(y0, y1, verticalCurve);
    return { x: mix(x0, x1, curve), y, altitude: clamp((12 - y) / 24, 0, 1), vx,
      bank: clamp((x1 - x0) / 8, -1, 1) * pulse, pitch: clamp((y0 - y1) / 10, -1, 1) * verticalPulse };
  }

  /** Continuous, seeded flight with occasional coordinated diagonal moves. */
  function aircraft(time, geo, seed = DEFAULT_SEED) {
    const flight = flightPath(time, seed), x = 100 + flight.x, bank = flight.bank;
    const rawY = geo.planeY + flight.y;
    const y = clamp(rawY, finite(geo.minPlaneY) ? geo.minPlaneY : geo.horizon + 23,
      finite(geo.maxPlaneY) ? geo.maxPlaneY : geo.bottom - 20);
    return { x, y, bank, pitch: flight.pitch, altitude: flight.altitude, vx: flight.vx, frame: Math.min(5, Math.floor(Math.abs(bank) * 6)) };
  }

  /** One camera moves sky, ground and ground objects with the flight path. */
  function cameraAt(time, geo, player = aircraft(time, geo)) {
    const altitude = finite(player.altitude) ? clamp(player.altitude, 0, 1) : .5;
    return {
      player, altitude, groundProjection: PROJECTION * (.9 + altitude * .2), groundZoom: 1.18 - altitude * .36,
      horizon: Math.min(geo.horizon - (player.y - geo.planeY) * .6, player.y - (geo.horizonOffset || 0) - 22),
      lateral: -(player.x - 100) * .9,
      lateralVelocity: -player.vx * .9,
      roll: player.bank * .085,
    };
  }

  const MISSIONS = [
    { offset: 0, side: -1, hit: true, drift: .8, model: 0 },
    { offset: 3, side: 1, hit: false, drift: 1.1, model: 1 },
    { offset: 4.5, side: -1, hit: false, drift: .9, model: 0 },
    { offset: 6, side: 1, hit: true, drift: .6, model: 0 },
    { offset: 9, side: -1, hit: false, drift: 1.3, model: 1 },
    { offset: 12, side: -1, hit: true, drift: .7, model: 1 },
    { offset: 13.5, side: 1, hit: false, drift: 1.2, model: 1 },
    { offset: 15, side: 1, hit: true, drift: .9, model: 0 },
    { offset: 18, side: -1, hit: false, drift: 1.2, model: 1 },
    { offset: 21, side: 1, hit: true, drift: .8, model: 0 },
    { offset: 22.5, side: -1, hit: false, drift: .7, model: 0 },
    { offset: 24, side: -1, hit: false, drift: 1.1, model: 0 },
    { offset: 27, side: 1, hit: true, drift: .7, model: 1 },
    { offset: 30, side: -1, hit: false, drift: 1.0, model: 0 },
  ];
  const HIT = 6.2, SHOT = .56, EXPLOSION = 1, LIFE = 9.5;

  /** An attacker comes out of the distance, grows in perspective, and either
   * exits through an edge or is hit at the exact end of its shot. */
  function enemyAt(time, spec, geo, camera, seed = DEFAULT_SEED) {
    let cycle = Math.floor(time / CYCLE);
    const event = n => {
      const jitter = n === 0 ? 0 : (flightRandom(seed, n, 90 + spec.offset * 2) - .5) * 1.8;
      return n * CYCLE + clamp(spec.offset + jitter, 0, CYCLE - .001);
    };
    if (time < event(cycle)) cycle--;
    const age = time - event(cycle), side = flightRandom(seed, cycle, 190 + spec.offset * 2) < .5 ? spec.side : -spec.side;
    const rear = flightRandom(seed, cycle, 220 + spec.offset * 2) < .45;
    if (age >= LIFE || (spec.hit && age >= HIT + EXPLOSION)) return null;
    const p = clamp(age / LIFE, 0, 1), retreat = clamp(age / 7.4, 0, 1);
    const depth = rear ? 1 - ease(retreat) : Math.pow(p, 1.35);
    const depthRate = rear ? -6 * retreat * (1 - retreat) / 7.4 : (p ? 1.35 / LIFE * Math.pow(p, .35) : 0);
    const exitProgress = !spec.hit ? clamp((age - 6.7) / (LIFE - 6.7), 0, 1) : 0;
    const depart = ease(exitProgress), departRate = 6 * exitProgress * (1 - exitProgress) / (LIFE - 6.7);
    const salt = 260 + spec.offset * 2;
    const phaseX = flightRandom(seed, cycle, salt) * Math.PI * 2;
    const phaseY = flightRandom(seed, cycle, salt + 1) * Math.PI * 2;
    const rateX = .8 + flightRandom(seed, cycle, salt + 2) * .9;
    const rateY = 1.1 + flightRandom(seed, cycle, salt + 3) * 1.1;
    const amplitudeX = 8 + flightRandom(seed, cycle, salt + 4) * 10;
    const amplitudeY = 7 + flightRandom(seed, cycle, salt + 5) * 10;
    const weaveX = Math.sin(age * rateX + phaseX) - Math.sin(phaseX);
    const weaveY = Math.sin(age * rateY + phaseY) - Math.sin(phaseY);
    let x = 100 + side * (10 + 55 * depth + 165 * depart) + amplitudeX * weaveX * (.3 + .7 * depth);
    let vx = side * (55 * depthRate + 165 * departRate) + amplitudeX *
      (rateX * Math.cos(age * rateX + phaseX) * (.3 + .7 * depth) + weaveX * .7 * depthRate);
    const verticalSpan = rear ? geo.bottom + 45 - geo.horizon - 3 : geo.planeY - geo.horizon - 24;
    let y = geo.horizon + 3 + verticalSpan * depth + amplitudeY * weaveY * (.25 + .75 * depth);
    y = clamp(y, geo.horizon + 2, Math.max(geo.horizon + 2, rear ? geo.bottom + 45 : geo.planeY - 18));
    if (camera) {
      x -= camera.lateral * (.5 + depth * 2);
      vx -= (finite(camera.lateralVelocity) ? camera.lateralVelocity : 0) * (.5 + depth * 2) + camera.lateral * 2 * depthRate;
      y += camera.roll * (x - 100);
    }
    const width = 5 + 32 * depth;
    const opacity = ease(age / .8);
    return { x, y, width, age, opacity, side, rear, cycle, bank: clamp(vx / 45, -1, 1), exploding: spec.hit && age >= HIT,
      blast: clamp((age - HIT) / EXPLOSION, 0, 1), hit: spec.hit };
  }

  function shotAt(time, spec, geo, player, camera, seed, currentTarget) {
    const target = currentTarget || enemyAt(time, spec, geo, camera, seed);
    if (!target || !spec.hit || target.age < HIT - SHOT || target.age >= HIT) return null;
    const t = clamp((target.age - (HIT - SHOT)) / SHOT, 0, 1);
    return { x: mix(player.x, target.x, t), y: mix(player.y - 7, target.y, t),
      tailX: mix(player.x, target.x, Math.max(0, t - .16)), tailY: mix(player.y - 7, target.y, Math.max(0, t - .16)), target, t };
  }

  function makeWorld(seed = DEFAULT_SEED) {
    return { time: 0, distance: 0, boost: 0, seed: seed >>> 0 };
  }
  function stepWorld(world, dt) {
    dt = clamp(finite(dt) ? dt : STEP, 0, .1);
    world.time += dt;
    world.boost = Math.max(0, world.boost - dt);
    // The plane moves quickly even without changing the render frame rate.
    world.distance += dt * (world.boost > 0 ? BOOST_SPEED : CRUISE_SPEED);
  }

  // The ground is anchored to world distance, so shorelines and field edges
  // travel towards the viewer instead of the entire screen changing colour.
  const SPAN = CRUISE_SPEED * 55, TRANSITION = CRUISE_SPEED * 5;
  const TERRAIN = [
    { kind: 'fields', sky: [105, 200, 226], colors: [[73,126,64],[105,151,68],[145,170,75],[173,160,88],[205,186,125],[52,104,59]] },
    { kind: 'desert', sky: [76, 200, 229], colors: [[220,164,94],[235,181,110],[202,141,74],[244,194,122],[179,111,52],[248,207,147]] },
    { kind: 'water', sky: [91, 197, 226], colors: [[38,126,157],[37,124,155],[36,122,153],[57,147,171],[177,218,215],[22,92,137]] },
  ];
  function terrainAtDistance(distance) {
    const cycle = wrap(distance, SPAN * TERRAIN.length), index = Math.floor(cycle / SPAN);
    const blend = ease((cycle - index * SPAN - (SPAN - TRANSITION)) / TRANSITION);
    const a = TERRAIN[index], b = TERRAIN[(index + 1) % TERRAIN.length], out = { kind: a.kind, index, blend };
    out.sky = a.sky.map((v, i) => Math.round(mix(v, b.sky[i], blend)));
    for (const [key, n] of [['far', 0], ['near', 1], ['shade', 2]]) {
      out[key] = a.colors[n].map((v, i) => Math.round(mix(v, b.colors[n][i], blend)));
    }
    for (const terrain of TERRAIN) out[terrain.kind] = (a === terrain ? 1 - blend : 0) + (b === terrain ? blend : 0);
    return out;
  }
  function terrainAt(time) { return terrainAtDistance(time * CRUISE_SPEED); }
  const packed = (c) => (0xff000000 | (c[2] << 16) | (c[1] << 8) | c[0]) >>> 0;
  function shade(colour, factor) { return colour.map(v => clamp(Math.round(v * factor), 0, 255)); }

  // Six colours per terrain and precomputed cross-fade steps keep the inner
  // pixel loop free of colour allocation and avoid a full-screen fade.
  const BLEND_STEPS = 128;
  const SOLID = TERRAIN.map(t => t.colors.map(packed));
  const BLENDS = TERRAIN.map((a, index) => Array.from({ length: BLEND_STEPS + 1 }, (_, step) => {
    const b = TERRAIN[(index + 1) % TERRAIN.length];
    return a.colors.flatMap(c => b.colors.map(d => packed(c.map((v, i) => Math.round(mix(v, d[i], step / BLEND_STEPS))))));
  }));

  // The horizon sees a much wider slice of ground than the foreground. Cache
  // that slice so the perspective does not flatten into a fixed-width strip.
  const PATTERN_WIDTH = 2048, PATTERN_CENTER = PATTERN_WIDTH / 2, fieldPatterns = new Map();
  const roadPattern = new Uint8Array(PATTERN_WIDTH).fill(4);
  const dunes = Array.from({ length: 65 }, (_, phase) => {
    const pattern = new Uint8Array(PATTERN_WIDTH);
    for (let i = 0; i < PATTERN_WIDTH; i++) {
      const ridge = (i - PATTERN_CENTER + 100000 + phase - 32 + 200) % 135;
      pattern[i] = ridge < 14 ? 2 : ridge < 52 ? 0 : ridge < 64 ? 3 : ridge < 115 ? 1 : 2;
    }
    return pattern;
  });
  const CREST_WIDTH = [0, .45, 1, .8, .4], CREST_SHIFT = [0, -2, 0, 2, 3];
  const waves = Array.from({ length: 30 }, (_, n) => {
    const pattern = new Uint8Array(PATTERN_WIDTH), stripe = n % 5, parity = Math.floor(n / 5) % 2, band = Math.floor(n / 10);
    for (let i = 0; i < PATTERN_WIDTH; i++) {
      const x = i - PATTERN_CENTER + 100000;
      const shifted = x + parity * 23, cell = Math.floor(shifted / 48), within = shifted % 48;
      const hash = (Math.imul(cell, 374761393) ^ Math.imul(parity + 1, 668265263)) >>> 0;
      const start = (hash >>> 5) % 12 + CREST_SHIFT[stripe];
      const length = Math.max(1, Math.round((5 + (hash >>> 11) % 9) * CREST_WIDTH[stripe]));
      // Small irregular crests are anchored to the ground, never re-randomized per frame.
      pattern[i] = stripe && within >= start && within < start + length ? 3 : band;
    }
    return pattern;
  });
  function groundPattern(kind, longitudinal, dune, depth) {
    if (kind === 1) return dunes[clamp(Math.round(dune) + 32, 0, 64)];
    if (kind === 2) {
      const parity = Math.floor(longitudinal / 1000) % 2, band = Math.min(2, Math.floor(depth / 80));
      const phase = longitudinal % 1000, stripe = phase < 80 ? 1 + Math.floor(phase / 20) : 0;
      return waves[band * 10 + parity * 5 + stripe];
    }
    if (longitudinal % 2100 < 36) return roadPattern;
    const row = Math.floor(longitudinal / 2100);
    let patterns = fieldPatterns.get(row);
    if (!patterns) {
      patterns = [new Uint8Array(PATTERN_WIDTH), new Uint8Array(PATTERN_WIDTH)];
      for (let i = 0; i < PATTERN_WIDTH; i++) {
        const x = i - PATTERN_CENTER + 100000, column = Math.floor(x / 65);
        const hash = (Math.imul(column, 73856093) ^ Math.imul(row, 19349663)) >>> 0;
        const field = hash % 4, stripe = (field + 1) % 4, edge = x % 65 < 1.4;
        patterns[0][i] = edge ? 4 : (hash & 8) && x % 11 < 1.4 ? stripe : field;
        patterns[1][i] = edge ? 4 : (hash & 8) ? (x % 11 < 1.4 ? stripe : field) : stripe;
      }
      if (fieldPatterns.size >= 24) fieldPatterns.delete(fieldPatterns.keys().next().value);
      fieldPatterns.set(row, patterns);
    }
    return patterns[longitudinal % 1300 < 400 ? 1 : 0];
  }

  /** A pixel surface with a perspective-moving terrain, stable sky stipple and
   * no per-pixel allocations. Everything outside the private atlas is original. */
  function paintBackdrop(buf, world, geo, camera = cameraAt(world.time, geo, aircraft(world.time, geo, world.seed))) {
    const colors = terrainAtDistance(world.distance + 4000), sky = packed(colors.sky), skyLight = packed(shade(colors.sky, 1.08));
    const rows = Math.floor(buf.length / W), margin = (rows - H) / 2;
    const horizon = Math.round(camera.horizon + margin);
    for (let y = 0; y < horizon; y++) {
      const dither = y < horizon * .58;
      const row = y * W;
      for (let x = 0; x < W; x++) buf[row + x] = dither && ((x + (y & 1)) & 1) === 0 && ((x + y * 3) & 7) < 2 ? skyLight : sky;
    }
    for (let y = horizon; y < rows; y++) {
      const depth = 1 + y - horizon, ahead = camera.groundProjection / (depth + 9), longitudinal = world.distance + ahead;
      const cycle = wrap(longitudinal, SPAN * TERRAIN.length), kind = Math.floor(cycle / SPAN);
      const blend = Math.round(ease((cycle - kind * SPAN - (SPAN - TRANSITION)) / TRANSITION) * BLEND_STEPS);
      const palette = blend ? BLENDS[kind][blend] : SOLID[kind];
      const row = y * W, scale = Math.min(9.5, ahead / (1404 * camera.groundZoom));
      const left = camera.lateral - 100 * scale;
      const dune = Math.sin(longitudinal / 1700) * 32;
      const a = groundPattern(kind, longitudinal, dune, depth), x0 = left + PATTERN_CENTER;
      if (!blend) {
        for (let x = 0; x < W; x++) buf[row + x] = palette[a[(x0 + x * scale) | 0]];
      } else {
        const b = groundPattern((kind + 1) % 3, longitudinal, dune, depth);
        for (let x = 0; x < W; x++) {
          const at = (x0 + x * scale) | 0;
          buf[row + x] = palette[a[at] * 6 + b[at]];
        }
      }
    }
    return colors;
  }

  function readAtlas(json) {
    if (!json || !json.frames || typeof json.frames !== 'object') return null;
    return function (name) {
      const box = json.frames[name], a = json.anchors && json.anchors[name];
      if (!Array.isArray(box) || box.length !== 4 || !box.every(finite) || !Array.isArray(a) || a.length !== 2 || !a.every(finite)) return null;
      return { x: box[0], y: box[1], w: box[2], h: box[3], ax: a[0], ay: a[1] };
    };
  }
  function atlasFrameFits(frame, atlas, name) {
    if (!frame || !atlas || typeof name !== 'string') return false;
    const width = finite(atlas.naturalWidth) ? atlas.naturalWidth : atlas.width;
    const height = finite(atlas.naturalHeight) ? atlas.naturalHeight : atlas.height;
    const f = frame(name);
    return finite(width) && finite(height) && width > 0 && height > 0 && !!f && f.x >= 0 && f.y >= 0 &&
      f.w > 0 && f.h > 0 && f.x + f.w <= width && f.y + f.h <= height &&
      f.ax >= 0 && f.ax <= f.w && f.ay >= 0 && f.ay <= f.h;
  }
  /** Optional, evidence-mapped five-angle pose families; old atlases still work. */
  function readPoseGrid(json, frame, atlas) {
    const poses = json && json.aircraft_poses, angles = [0, 22.5, 45, 67.5, 90];
    if (!poses || poses.version !== 1 || poses.right_flip !== true || !Array.isArray(poses.bank_angles) ||
        poses.bank_angles.length !== angles.length || !poses.bank_angles.every((n, i) => n === angles[i]) || !frame) return null;
    const fits = name => atlasFrameFits(frame, atlas, name);
    for (const key of ['level', 'up', 'down']) {
      if (!Array.isArray(poses[key]) || poses[key].length !== angles.length ||
          !poses[key].every(fits)) return null;
    }
    if (!fits(poses.up_transition) || !fits(poses.down_transition)) return null;
    return poses;
  }
  function readEnemyPoseGrid(json, frame, atlas) {
    const grid = json && json.enemy_poses, widths = [5, 7, 10, 14, 18, 24, 32, 42, 54], sequence = [4, 5, 6, 7, 8, 7, 6, 5, 4];
    if (!grid || grid.version !== 1 || grid.reference_width !== 72 || !Array.isArray(grid.widths) || grid.widths.length !== widths.length ||
        !grid.widths.every((n, i) => n === widths[i]) || !Array.isArray(grid.poses) || grid.poses.length !== 12 ||
        !Array.isArray(grid.sequence) || grid.sequence.length !== sequence.length ||
        !grid.sequence.every((index, i) => index === sequence[i])) return null;
    for (const pose of grid.poses) {
      if (!pose || !Array.isArray(pose.frames) || pose.frames.length !== widths.length ||
          !pose.frames.every(name => atlasFrameFits(frame, atlas, name)) || !Array.isArray(pose.flips) || !pose.flips.length ||
          !pose.flips.every(pair => Array.isArray(pair) && pair.length === 2 && pair.every(value => typeof value === 'boolean'))) return null;
    }
    // Sign describes the measured visible wing slope, not a claim about the
    // original game's flight physics. Near-vertical 09 is used only in the
    // traced sequence; the other strong silhouettes are used only at high bank.
    const slopes = {1: 1, 2: 1, 3: -1, 5: 1, 6: 1, 7: 1, 10: 1, 11: 1};
    const observed = (index, x) => grid.poses[index].flips.some(pair => pair[0] === x && pair[1] === false);
    const neutral = [0, 4, 9].map(index => ({index, flipX: observed(index, true) ? true : false}))
      .filter(pose => observed(pose.index, pose.flipX));
    const choices = (indices, direction) => indices.flatMap(index => {
      const flipX = slopes[index] !== direction;
      return observed(index, flipX) ? [{index, flipX}] : [];
    });
    const left = {medium: choices([1, 5], -1), strong: choices([2, 3, 6, 7, 10, 11], -1)};
    const right = {medium: choices([1, 5], 1), strong: choices([2, 3, 6, 7, 10, 11], 1)};
    if (!neutral.length || !left.medium.length || !right.medium.length) return null;
    const leftSequence = grid.sequence.every(index => observed(index, true)) ? grid.sequence : null;
    const rightSequence = [5, 6, 7, 6, 5].every(index => observed(index, false)) ? [5, 6, 7, 6, 5] : null;
    return { widths: grid.widths, poses: grid.poses, neutral, left, right, leftSequence, rightSequence };
  }
  function readCloudPoseGrid(json, frame, atlas) {
    const grid = json && json.cloud_poses, widths = [16, 24, 36, 54, 80, 120, 180];
    if (!grid || grid.version !== 1 || grid.anchor_mode !== 'visual_center' || grid.reference_width !== 159 ||
        !Array.isArray(grid.widths) || grid.widths.length !== widths.length || !grid.widths.every((n, i) => n === widths[i]) ||
        !Array.isArray(grid.poses) || grid.poses.length !== 2) return null;
    for (const pose of grid.poses) {
      if (!pose || !Array.isArray(pose.source_size) || pose.source_size.length !== 2 ||
          !pose.source_size.every(n => finite(n) && n > 0) || !Array.isArray(pose.frames) || pose.frames.length !== widths.length ||
          !pose.frames.every(name => atlasFrameFits(frame, atlas, name)) || !Array.isArray(pose.flips) || !pose.flips.length ||
          !pose.flips.every(pair => Array.isArray(pair) && pair.length === 2 && pair.every(value => typeof value === 'boolean'))) return null;
    }
    return { widths: grid.widths, poses: grid.poses,
      shapes: grid.poses.map(pose => ({width: pose.source_size[0] / 159, height: pose.source_size[1] / 159})) };
  }
  function enemyPose(enemy, spec, grid, seed) {
    const salt = 420 + spec.offset * 2, amount = Math.abs(enemy.bank), direction = enemy.bank < 0 ? -1 : 1;
    const start = 1.6 + flightRandom(seed, enemy.cycle, salt + 1) * .8;
    const duration = 2 + flightRandom(seed, enemy.cycle, salt + 2) * .8;
    const trace = direction < 0 ? grid.leftSequence : grid.rightSequence;
    const sequence = amount >= .2 && trace && flightRandom(seed, enemy.cycle, salt) < .35 &&
      enemy.age >= start && enemy.age <= start + duration;
    let choice;
    if (sequence) {
      const phase = clamp((enemy.age - start) / duration, 0, 1);
      const selected = trace[Math.min(trace.length - 1, Math.floor(phase * trace.length))];
      const cap = 4 + Math.min(4, Math.floor(amount * 5));
      choice = { index: Math.max(direction > 0 ? 5 : 4, Math.min(selected, cap)), flipX: direction < 0 };
    } else {
      const directionGrid = direction < 0 ? grid.left : grid.right;
      const pool = amount < .2 ? grid.neutral : (amount >= .65 && directionGrid.strong.length ? directionGrid.strong : directionGrid.medium);
      choice = pool[Math.floor(flightRandom(seed, enemy.cycle, salt + 3) * pool.length)];
    }
    const index = choice.index, pair = [choice.flipX, false];
    const nominal = rung(enemy.width, grid.widths), name = grid.poses[index].frames[grid.widths.indexOf(nominal)];
    return { name, index, flipX: pair[0], flipY: pair[1], sequence };
  }
  function poseEnvelope(poses, frame) {
    const bounds = { left: 0, right: 0, top: 0, bottom: 10 };
    for (const name of [...poses.level, ...poses.up, ...poses.down, poses.up_transition, poses.down_transition]) {
      const f = frame(name);
      if (!f || f.w <= 0 || f.h <= 0 || f.ax < 0 || f.ax > f.w || f.ay < 0 || f.ay > f.h) return null;
      const side = Math.max(f.ax, f.w - f.ax);
      bounds.left = Math.max(bounds.left, side); bounds.right = Math.max(bounds.right, side);
      bounds.top = Math.max(bounds.top, f.ay); bounds.bottom = Math.max(bounds.bottom, f.h - f.ay);
    }
    return bounds;
  }
  function aircraftLayers(player, poses) {
    const bankIndex = clamp(Math.round(Math.abs(player.bank) * 4), 0, 4);
    const level = poses.level[bankIndex], direction = player.pitch >= 0 ? 'up' : 'down';
    const amount = Math.abs(player.pitch);
    if (amount < .2) return [{ name: level, opacity: 1 }];
    if (bankIndex === 0 && amount < .65) return [{ name: poses[direction + '_transition'], opacity: 1 }];
    return [{ name: amount < .45 ? level : poses[direction][bankIndex], opacity: 1 }];
  }
  function drawSprite(g, state, name, x, y, flip = false, opacity = 1, flipY = false) {
    const frame = state.frame && state.frame(name);
    if (!frame || !state.atlas || opacity <= 0) return false;
    g.save(); g.globalAlpha = clamp(opacity, 0, 1);
    g.translate(Math.round(x), Math.round(y));
    if (flip || flipY) g.scale(flip ? -1 : 1, flipY ? -1 : 1);
    g.drawImage(state.atlas, frame.x, frame.y, frame.w, frame.h, -frame.ax, -frame.ay, frame.w, frame.h);
    g.restore();
    return true;
  }
  function rung(value, options) {
    let best = options[0], error = Infinity;
    for (const n of options) { const d = Math.abs(value - n); if (d < error) { best = n; error = d; } }
    return best;
  }

  // A bounded ceiling above the aircraft mirrors the ground's inverse-depth
  // projection. Every cloud keeps a fixed world position and height.
  const CLOUD_GAP = 5000, CLOUD_FAR = 26000, CLOUD_OFFSETS = [200, 1600, 3000, 900, 2300, 3700];
  const CLOUD_SHAPES = [{width: 1, height: .3}, {width: 1, height: .3}];
  function cloudCeiling(geo, camera, planeTop = 18) {
    // Use the lowest safe horizon and highest plane position over the whole
    // altitude range. The ceiling stays fixed while clouds move vertically.
    const minPlaneY = Math.max(geo.planeY - 12, finite(geo.minPlaneY) ? geo.minPlaneY : geo.horizon + 23);
    const minHorizon = Math.min(geo.horizon - 7.2, minPlaneY - (geo.horizonOffset || 0) - 22);
    return Math.max(0, Math.min(geo.bottom, minHorizon, minPlaneY - planeTop) - 1);
  }
  function cloudFeatures(world, geo, camera = cameraAt(world.time, geo, aircraft(world.time, geo, world.seed)), shapes = CLOUD_SHAPES, planeTop = 18) {
    const seed = finite(world.seed) ? world.seed : DEFAULT_SEED, clouds = [], first = Math.floor(world.distance / CLOUD_GAP);
    const ceiling = cloudCeiling(geo, camera, planeTop);
    if (ceiling < 2) return clouds;
    const step = (world.boost > 0 ? BOOST_SPEED : CRUISE_SPEED) * STEP;
    for (let cell = first; cell <= first + Math.ceil(CLOUD_FAR / CLOUD_GAP); cell++) for (let lane = 0; lane < CLOUD_OFFSETS.length; lane++) {
      const salt = 600 + lane * 10, position = cell * CLOUD_GAP + CLOUD_OFFSETS[lane] + flightRandom(seed, cell, salt) * 900;
      const ahead = position - world.distance;
      if (ahead <= 100 || ahead >= CLOUD_FAR) continue;
      const spread = flightRandom(seed, cell, salt + 1);
      const lateral = lane === 0 ? -(55 + spread * 500) : lane === 2 ? 55 + spread * 500 :
        lane === 3 ? -(35 + spread * 260) : lane === 4 ? 35 + spread * 260 : (spread * 2 - 1) * (lane === 5 ? 320 : 180);
      const cloudLevel = 1.3 + flightRandom(seed, cell, salt + 2) * .7;
      const altitude = (cloudLevel - camera.altitude) * 10000 * geo.horizon / 109;
      const layerOffset = flightRandom(seed, cell, salt + 5) * ceiling * .35;
      const flightOffset = (1 - camera.altitude) * ceiling * .5;
      const sizeChoice = flightRandom(seed, cell, salt + 3);
      const span = 90 + sizeChoice * 110 + (sizeChoice > .85 ? 20 : 0);
      const style = flightRandom(seed, cell, salt + 4) < .5 ? 0 : 1, scale = 1404 / ahead;
      const x = 100 + (lateral - camera.lateral) * scale;
      const nominal = span * scale, width = nominal * shapes[style].width, height = nominal * shapes[style].height;
      const bankMargin = Math.abs(camera.roll) * (Math.abs(x - 100) + width / 2);
      const groundMargin = ceiling - camera.horizon + height / 2 + Math.abs(camera.roll) * width;
      const y = ceiling - .01 - flightOffset - Math.max(height / 2 + bankMargin, groundMargin, layerOffset + altitude / ahead);
      const screenY = y + camera.roll * (x - 100);
      if (x + width / 2 < 0 || x - width / 2 > W || screenY + height / 2 + Math.abs(camera.roll) * width / 2 < 0) continue;
      const next = Math.max(1, ahead - step), nextX = 100 + (lateral - camera.lateral) * 1404 / next;
      const nextWidth = span * shapes[style].width * 1404 / next, nextHeight = span * shapes[style].height * 1404 / next;
      const nextMargin = Math.max(nextHeight / 2 + Math.abs(camera.roll) * (Math.abs(nextX - 100) + nextWidth / 2),
        ceiling - camera.horizon + nextHeight / 2 + Math.abs(camera.roll) * nextWidth);
      const nextY = ceiling - .01 - flightOffset - Math.max(nextMargin, layerOffset + altitude / next);
      const shift = Math.max(Math.abs(nextX - x), Math.abs(nextY - y)) + Math.abs(nextWidth - width) * .5;
      const minimumFade = clamp(ceiling * .12, 3, 12), fade = clamp(minimumFade + shift * 6, minimumFade, 300);
      const edge = Math.min(x + width / 2, W - x + width / 2, screenY + height / 2 + Math.abs(camera.roll) * width / 2);
      const opacity = ease((CLOUD_FAR - ahead) / 3500) * ease((ahead - 900) / 1200) * ease(edge / fade) *
        ease((32 - shift) / 18) * ease((layerOffset + flightOffset + altitude / ahead) / 3);
      clouds.push({ id: cell + ':' + lane, x, y, width, height, nominal, opacity, ahead, lateral, style, lane, cloudLevel });
    }
    return clouds.sort((a, b) => b.ahead - a.ahead);
  }
  function makeCloudArt() {
    if (typeof document === 'undefined') return null;
    const art = document.createElement('canvas'); art.width = 64; art.height = 16;
    const ctx = art.getContext('2d');
    if (!ctx) return null;
    for (let i = 0; i < 2; i++) {
      const x = i * 32;
      ctx.fillStyle = '#bcdde5'; ctx.fillRect(x + 2, 11, 28, 3);
      ctx.fillStyle = '#f3fbff'; ctx.fillRect(x + 1, 8, 30, 4);
      ctx.fillRect(x + (i ? 7 : 5), 5, i ? 20 : 23, 4);
      ctx.fillRect(x + (i ? 13 : 11), 2, i ? 8 : 10, 4);
    }
    return art;
  }
  function drawClouds(g, s, clouds, camera, ceiling) {
    if (ceiling <= 0) return;
    g.save();
    if (s.surfaceContext) g.transform(1, -camera.roll, 0, 1, 0, 100 * camera.roll);
    g.beginPath(); g.rect(0, 0, W, ceiling); g.clip();
    if (s.surfaceContext) g.transform(1, camera.roll, 0, 1, 0, -100 * camera.roll);
    g.imageSmoothingEnabled = false;
    for (const cloud of clouds) {
      if (cloud.opacity <= .005) continue;
      const w = Math.max(2, Math.round(cloud.width)), h = Math.max(1, Math.round(cloud.height));
      const x = Math.round(cloud.x - w / 2), y = Math.round(cloud.y - h / 2);
      g.save(); g.globalAlpha = cloud.opacity;
      if (s.cloudPoses) {
        const pose = s.cloudPoses.poses[cloud.style], nominal = rung(cloud.nominal, s.cloudPoses.widths);
        const f = s.frame(pose.frames[s.cloudPoses.widths.indexOf(nominal)]);
        const wanted = cloud.lane === 0, pair = pose.flips.find(([flipX, flipY]) => flipX === wanted && !flipY) || pose.flips[0];
        g.translate(Math.round(cloud.x), Math.round(cloud.y));
        if (pair[0] || pair[1]) g.scale(pair[0] ? -1 : 1, pair[1] ? -1 : 1);
        g.drawImage(s.atlas, f.x, f.y, f.w, f.h, -w / 2, -h / 2, w, h);
      } else if (s.cloudArt) g.drawImage(s.cloudArt, cloud.style * 32, 0, 32, 16, x, y, w, h);
      else { g.fillStyle = '#f3fbff'; g.fillRect(x, y, w, h); }
      g.restore();
    }
    g.restore();
  }
  function projectGround(ahead, lateral, camera) {
    if (ahead <= 0) return null;
    const depth = camera.groundProjection / ahead - 10, scale = Math.min(9.5, ahead / (1404 * camera.groundZoom));
    return { x: 100 + (lateral - camera.lateral) / scale, y: Math.round(camera.horizon) + depth, depth };
  }
  const GROUND_LANES = [45, 120, 250];
  const GROUND_TYPES = [['tree', 'tree', 'farm'], ['mesa', 'cactus', 'mesa'], ['ship', 'buoy', 'ship']];
  /** Features are fixed to the ground, and use the same projection as its pixels. */
  function groundFeatures(world, geo, camera = cameraAt(world.time, geo, aircraft(world.time, geo, world.seed))) {
    const features = [], seed = finite(world.seed) ? world.seed : DEFAULT_SEED;
    const first = Math.floor(world.distance / 1800);
    for (let cell = first; cell <= first + 5; cell++) for (const side of [-1, 1]) for (let lane = 0; lane < 2; lane++) {
      const salt = side > 0 ? 20 : 30;
      const firstLane = Math.floor(flightRandom(seed, cell, salt) * GROUND_LANES.length);
      const laneIndex = lane ? (firstLane + 1 + Math.floor(flightRandom(seed, cell, salt + 1) * 2)) % 3 : firstLane;
      const position = cell * 1800 + (side > 0 ? 600 : 0) + lane * 300 + Math.floor(flightRandom(seed, cell, salt + 2 + lane) * 180);
      const ahead = position - world.distance;
      if (ahead <= 0 || ahead > 7500) continue;
      const lateral = side * (GROUND_LANES[laneIndex] + (flightRandom(seed, cell, salt + 4 + lane) - .5) * 18);
      const { x, y, depth } = projectGround(ahead, lateral, camera);
      const screenY = y + camera.roll * (x - 100);
      if (depth <= 0 || screenY >= H) continue;
      if (x < -45 || x > W + 45) continue;
      // At high speed an object can cross the bottom in one frame. Begin its
      // fade earlier in proportion to its projected approach for that frame.
      const stepDistance = (world.boost > 0 ? BOOST_SPEED : CRUISE_SPEED) * STEP;
      const approach = camera.groundProjection / Math.max(1, ahead - stepDistance) - camera.groundProjection / ahead;
      const fadeSpan = 32 + Math.min(H, approach) * 4;
      const edge = ease((x + 45) / 40) * ease((W + 45 - x) / 40);
      const info = terrainAtDistance(position), visibility = edge * ease((7500 - ahead) / 900) * ease((H - screenY) / fadeSpan);
      const add = (index, alpha) => {
        if (alpha <= .01) return;
        const type = GROUND_TYPES[index][wrap(cell + lane + (side > 0 ? 1 : 0), 3)];
        const size = 4 + Math.max(0, PROJECTION / ahead - 10) * .15 * camera.groundZoom;
        features.push({ id: cell + ':' + side + ':' + lane + ':' + index, type, position, lateral,
          x, y, size, opacity: visibility * alpha, side });
      };
      add(info.index, 1 - info.blend);
      add((info.index + 1) % 3, info.blend);
    }
    return features.sort((a, b) => a.y - b.y);
  }
  function drawGroundFeatures(g, s, world, geo, camera) {
    for (const f of groundFeatures(world, geo, camera)) {
      const x = Math.round(f.x), y = Math.round(f.y), size = Math.max(3, Math.round(f.size));
      if (f.type === 'mesa' && drawSprite(g, s, 'mesa-' + rung(size * 2.7, [12, 18, 26, 38, 55, 80, 110]), x, y, f.side < 0, f.opacity)) continue;
      if (f.type === 'ship' && drawSprite(g, s, 'ship-' + rung(size * 2, [10, 16, 24, 36, 52, 72]), x, y, f.side < 0, f.opacity)) continue;
      g.save(); g.globalAlpha = f.opacity;
      if (f.type === 'tree') {
        g.fillStyle = '#735033'; g.fillRect(x - 1, y, 2, Math.max(2, size >> 1));
        g.fillStyle = '#285d3f'; g.fillRect(x - size / 2, y - size / 2, size, size / 2);
        g.fillStyle = '#43834a'; g.fillRect(x - size / 3, y - size, size * 2 / 3, size * .65);
        g.fillStyle = '#6a9c55'; g.fillRect(x - size / 4, y - size, size / 3, Math.max(1, size / 4));
      } else if (f.type === 'farm') {
        g.fillStyle = '#e5c79b'; g.fillRect(x - size / 2, y - size / 2, size, size / 2);
        g.fillStyle = '#aa513a'; g.fillRect(x - size * .6, y - size * .7, size * 1.2, size / 4);
        g.fillStyle = '#5c5744'; g.fillRect(x - 1, y - size / 4, 2, Math.max(2, size / 4));
      } else if (f.type === 'cactus') {
        g.fillStyle = '#47774d'; g.fillRect(x - 1, y - size, 3, size); g.fillRect(x - size / 3, y - size * .65, size * .7, 2);
      } else if (f.type === 'buoy') {
        g.fillStyle = '#efc958'; g.fillRect(x - size / 4, y - size / 2, size / 2, size / 2);
        g.fillStyle = '#fff0c0'; g.fillRect(x - 1, y - size * .8, 2, size / 3);
      } else if (f.type === 'mesa') {
        g.fillStyle = '#b76d38'; g.fillRect(x - size, y - size / 2, size * 2, size / 2);
        g.fillStyle = '#d59759'; g.fillRect(x - size * .65, y - size, size * 1.3, size / 2);
      } else {
        g.fillStyle = '#d9e3df'; g.fillRect(x - size, y - size / 4, size * 2, Math.max(2, size / 3));
        g.fillStyle = '#6e8993'; g.fillRect(x - size / 3, y - size / 2, size * .7, size / 3);
      }
      g.restore();
    }
  }
  function drawExplosion(g, e) {
    const t = e.blast, r = 3 + 13 * Math.sin(Math.PI * t), alpha = (1 - t) * e.opacity;
    g.save(); g.globalAlpha = alpha;
    const x = Math.round(e.x), y = Math.round(e.y), size = Math.max(2, Math.round(r));
    const burst = (radius, colour) => {
      g.fillStyle = colour; g.beginPath();
      for (let i = 0; i < 16; i++) {
        const a = Math.PI * i / 8, reach = radius * (i % 2 ? .58 : 1);
        const px = Math.round(x + Math.cos(a) * reach), py = Math.round(y + Math.sin(a) * reach);
        if (i) g.lineTo(px, py); else g.moveTo(px, py);
      }
      g.closePath(); g.fill();
    };
    burst(size, '#d8441f'); burst(size * .75, '#ff922c'); burst(size * .48, '#ffe075');
    g.fillStyle = '#fff4c1'; g.fillRect(x - Math.max(1, size >> 3), y - Math.max(1, size >> 3), Math.max(2, size >> 2), Math.max(2, size >> 2));
    for (let i = 0; i < 6; i++) {
      const a = i * Math.PI / 3 + t, dist = size * (1 + t * .9);
      g.fillStyle = i & 1 ? '#ffd65c' : '#e84a21';
      g.fillRect(Math.round(x + Math.cos(a) * dist), Math.round(y + Math.sin(a) * dist), 2, 2);
    }
    g.restore();
  }
  function drawShot(g, shot) {
    g.save(); g.lineWidth = 2; g.strokeStyle = '#ffd046'; g.beginPath();
    g.moveTo(Math.round(shot.tailX), Math.round(shot.tailY)); g.lineTo(Math.round(shot.x), Math.round(shot.y)); g.stroke();
    g.fillStyle = '#fff7c0'; g.fillRect(Math.round(shot.x) - 1, Math.round(shot.y) - 1, 3, 3);
    const x = Math.round(shot.target.x), y = Math.round(shot.target.y), r = Math.max(4, shot.target.width * .6);
    g.strokeStyle = 'rgba(255,238,146,.9)'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(x-r,y-r+3); g.lineTo(x-r,y-r); g.lineTo(x-r+3,y-r);
    g.moveTo(x+r-3,y-r); g.lineTo(x+r,y-r); g.lineTo(x+r,y-r+3);
    g.moveTo(x-r,y+r-3); g.lineTo(x-r,y+r); g.lineTo(x-r+3,y+r);
    g.moveTo(x+r-3,y+r); g.lineTo(x+r,y+r); g.lineTo(x+r,y+r-3); g.stroke();
    g.restore();
  }

  const scene = {
    size: [W, H],
    init(api) {
      const seed = finite(api.flightSeed) ? api.flightSeed : Math.floor(Math.random() * 4294967296);
      const world = makeWorld(seed);
      const image = typeof ImageData === 'function' ? new ImageData(W, H + 2 * OVERSCAN) : null;
      const surface = typeof document !== 'undefined' ? document.createElement('canvas') : null;
      if (surface) { surface.width = W; surface.height = H + 2 * OVERSCAN; }
      const frame = readAtlas(api.json);
      let poses = api.atlas ? readPoseGrid(api.json, frame, api.atlas) : null;
      const poseBounds = poses && poseEnvelope(poses, frame);
      if (!poseBounds) poses = null;
      let legacyTop = 8;
      if (api.atlas && frame) for (let i = 0; i < 6; i++) {
        const f = frame('player-' + i);
        if (f) legacyTop = Math.max(legacyTop, f.ay * 1.12);
      }
      const cloudPoses = api.atlas ? readCloudPoseGrid(api.json, frame, api.atlas) : null;
      this.s = { world, image, pixels: image ? new Uint32Array(image.data.buffer) : null,
        surface, surfaceContext: surface && surface.getContext('2d'), cloudArt: cloudPoses ? null : makeCloudArt(), cloudPoses, frame, poses, poseBounds, legacyTop,
        enemyPoses: api.atlas ? readEnemyPoseGrid(api.json, frame, api.atlas) : null, atlas: api.atlas || null };
    },
    step(api, dt) { if (this.s) stepWorld(this.s.world, dt); },
    draw(api, g) {
      const s = this.s;
      if (!s || !s.pixels) return;
      const world = s.world, geo = layout(api.view && api.view.bottom, s.poseBounds), player = aircraft(world.time, geo, world.seed);
      const camera = cameraAt(world.time, geo, player), enemyGeo = Object.assign({}, geo, {
        horizon: camera.horizon, planeY: geo.planeY - (geo.horizonOffset || 0),
      });
      const planeTop = s.poseBounds ? s.poseBounds.top * geo.planeScale : s.legacyTop;
      const ceiling = cloudCeiling(geo, camera, planeTop);
      const clouds = cloudFeatures(world, geo, camera, s.cloudPoses ? s.cloudPoses.shapes : CLOUD_SHAPES, planeTop);
      paintBackdrop(s.pixels, world, geo, camera);
      g.save();
      if (s.surfaceContext) {
        s.surfaceContext.putImageData(s.image, 0, 0);
        g.transform(1, camera.roll, 0, 1, 0, -100 * camera.roll);
        g.imageSmoothingEnabled = false;
        g.drawImage(s.surface, 0, -OVERSCAN);
      } else g.putImageData(s.image, 0, -OVERSCAN);
      drawClouds(g, s, clouds, camera, ceiling);
      drawGroundFeatures(g, s, world, geo, camera);
      g.restore();
      const shots = [];
      // Rear entrants emerge from beneath the visible area without painting
      // over the clock or readings in the dock.
      g.save(); g.beginPath(); g.rect(0, 0, W, geo.bottom); g.clip();
      for (const spec of MISSIONS) {
        const e = enemyAt(world.time, spec, enemyGeo, camera, world.seed);
        if (!e) continue;
        if (e.exploding) drawExplosion(g, e);
        else {
          // The traced sequence is decorative: its frame numbers are not
          // assigned an unverified left/right or roll meaning.
          const pose = s.enemyPoses && enemyPose(e, spec, s.enemyPoses, world.seed);
          g.save(); g.translate(Math.round(e.x), Math.round(e.y));
          if (!pose) g.rotate(e.bank * .25);
          g.imageSmoothingEnabled = false;
          const name = pose ? pose.name : 'enemy-' + spec.model + '-' + rung(e.width, [5, 7, 10, 14, 18, 24, 32, 42, 54]);
          if (!drawSprite(g, s, name, 0, 0, pose ? pose.flipX : e.side < 0, e.opacity, pose && pose.flipY)) {
            g.save(); g.globalAlpha = e.opacity; g.fillStyle = spec.model ? '#f3b3a1' : '#d9e3df';
            g.fillRect(Math.round(-e.width / 2), 0, Math.round(e.width), 2);
            g.fillRect(-1, Math.round(-e.width / 4), 3, Math.max(3, Math.round(e.width / 2))); g.restore();
          }
          g.restore();
          const shot = shotAt(world.time, spec, enemyGeo, player, camera, world.seed, e);
          if (shot) shots.push(shot);
        }
      }
      for (const shot of shots) drawShot(g, shot);
      g.restore();
      // Old atlases use a restrained pitch adaptation. Evidence-mapped pose
      // families use their own anchors and are never deformed.
      g.save(); g.translate(Math.round(player.x), Math.round(player.y));
      const planeScale = geo.planeScale || 1;
      g.imageSmoothingEnabled = false;
      g.scale(planeScale, planeScale * (s.poses ? 1 : 1 + player.pitch * .12));
      if (s.poses || (s.atlas && s.frame && s.frame('player-' + player.frame))) {
        const layers = s.poses ? aircraftLayers(player, s.poses) : [{ name: 'player-' + player.frame, opacity: 1 }];
        for (const layer of layers) drawSprite(g, s, layer.name, 0, 0, player.bank > 0, layer.opacity);
        // Short afterburner pulses stay attached to the engines.
        if (!s.poses && player.frame < 3) {
          const flame = world.boost > 0 ? 7 : 2 + ((world.time * 7) | 0) % 3;
          g.fillStyle = '#ffb436';
          for (const dx of [-4, 4]) g.fillRect(dx, 3, 2, flame);
        }
      } else {
        g.fillStyle = '#113080'; g.fillRect(-20, 0, 40, 3);
        g.fillStyle = '#2464c8'; g.fillRect(-3, -8, 6, 15);
      }
      g.restore();
    },
    poke(api, x, y) { if (this.s && finite(x) && finite(y)) this.s.world.boost = 3; },
  };

  const logic = { W, H, STEP, CYCLE, HIT, SHOT, EXPLOSION, LIFE, MISSIONS, layout, aircraft, cameraAt, enemyAt, shotAt, makeWorld, stepWorld, terrainAt, terrainAtDistance, projectGround, groundFeatures, cloudCeiling, cloudFeatures, paintBackdrop, readAtlas, readPoseGrid, readEnemyPoseGrid, readCloudPoseGrid, enemyPose, poseEnvelope, aircraftLayers, rung, scene };
  if (global.TabletGames && typeof global.TabletGames.define === 'function') global.TabletGames.define('blue-lightning', scene);
  if (typeof module !== 'undefined' && module.exports) module.exports = logic;
}(typeof window !== 'undefined' ? window : globalThis));
