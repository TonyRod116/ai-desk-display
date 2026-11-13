/* CITY IN THE SKY: the tablet's isometric city, in real time (a scene of the game engine, stage-game.js: window.TabletGames).
 *
 * Tony: "the isometric city: put even more things in it and more realism, and KEEP the lights in the buildings: I liked seeing in the buildings how much was left."
 *
 * What never moves is drawn offline into an ATLAS by scripts/prepare_game_city_iso.py (the city at four times of day, the sky, the window lights in ten batches, an
 * id picture that says which building owns each pixel, and the numbers below). The atlas is private (the tablet's folder), the code is original and goes to Git.
 * This file does the rest, cheaply, 30 times a second: it mixes the four times of day by the real clock, brings the window lights in batch by batch at dusk and
 * takes them out at dawn, and moves the small things (cars and buses between the red and green lights, pedestrians, boats with wakes, an elevated train, a
 * helicopter, a blimp with a moving billboard, steam, beacons, screens, fountains, clouds, stars and the observed weather) behind or in front of the
 * buildings by looking at the id picture. The camera stays fixed on the city.
 *
 * Only THREE buildings carry data, exactly as on the small board (board_city.py): the two towers are the WEEK (ten floors of ten windows: one window per percent,
 * Codex amber, Claude white, at least one while anything is left, none while unknown) and the small one beside Claude's is Claude's FIVE HOURS (left face the
 * quota, 20 % a floor; right face the time, an hour a floor; only from a fresh reading). Everything else is scenery and never covers them.
 *
 * The pure parts (the readings, the sun, the traffic, the hidden-behind test) come first and are exported for the Node tests (tests/test_tablet_game_city_iso.mjs).
 */
(function (global) {
  'use strict';

  const NAME = 'city-iso';
  const SIZE = [267, 427];
  const STEP = 1 / 30;
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const mixRgb = (a, b, t) => [Math.round(lerp(a[0], b[0], t)), Math.round(lerp(a[1], b[1], t)), Math.round(lerp(a[2], b[2], t))];
  const rgb = (c) => 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')';

  /* ------------------------------------------------------------------------------------------------------------ the data: readings to lit windows */

  const STALE_MS = 45000;            // the page asks every 5 s; a reading not renewed for this long is not shown (unknown, never old numbers)
  const WEEK_CELLS = 100;            // ten floors of ten windows: one window per percent
  const SMALL_FLOOR_CELLS = 8;       // eight windows across each face of the five-hour building, five floors: 40 per face
  const SMALL_CELLS = 40;

  const isPercent = (v) => finite(v) && v >= 0 && v <= 100;
  const future = (epoch, nowMs) => finite(epoch) && epoch * 1000 > nowMs;

  /** Windows lit for a weekly quota left: one per percent (rounded DOWN, like the number on the dock), at least one while anything is left, none for zero,
   *  and null (unknown) for anything that is not a percentage. 72.9 is 72, 0.4 is 1, 0 is 0, 100 is 100. */
  function weekCells(remaining) {
    if (!isPercent(remaining)) return null;
    if (remaining <= 0) return 0;
    return clamp(Math.floor(remaining + 1e-9), 1, WEEK_CELLS);
  }
  /** The five-hour building: left face = quota (20 % a floor, eight windows a floor, so 2.5 % a window, at least one while any is left), right face = time left
   *  (an hour a floor, 7.5 minutes a window, at least one while any is left). Both from the same fresh, known reading; otherwise null. */
  function sessionCells(session, nowMs) {
    if (!session || typeof session !== 'object' || !isPercent(session.remaining) || !future(session.resets_at, nowMs)) return null;
    const quota = session.remaining <= 0 ? 0 : clamp(Math.ceil(session.remaining / 2.5 - 1e-9), 1, SMALL_CELLS);
    const hours = clamp((session.resets_at * 1000 - nowMs) / 3600000, 0, 5);
    const time = hours <= 0 ? 0 : clamp(Math.round(hours * 8), 1, SMALL_CELLS);
    return { quota, time };
  }
  /** What the three buildings show. `ageMs` is how long ago the page last renewed its readings (a reading that stopped coming is unknown, not frozen). */
  function dataState(readings, nowMs, ageMs) {
    const out = { codex: { known: false, count: 0 }, claude: { known: false, count: 0 }, small: { known: false, quota: 0, time: 0 } };
    if (!readings || typeof readings !== 'object' || (finite(ageMs) && ageMs > STALE_MS)) return out;
    const providers = readings.providers;
    if (!providers || typeof providers !== 'object') return out;
    for (const name of ['codex', 'claude']) {
      const week = providers[name] && providers[name].weekly;
      const count = week && typeof week === 'object' && future(week.resets_at, nowMs) ? weekCells(week.remaining) : null;
      if (count !== null) out[name] = { known: true, count };
    }
    const cells = providers.claude ? sessionCells(providers.claude.session, nowMs) : null;
    if (cells) out.small = { known: true, quota: cells.quota, time: cells.time };
    return out;
  }
  /** Which cells of a data building are lit: the first `count` in reading order (floors from the ground, on each floor the left face and then the right). */
  const litFlags = (count, total) => Array.from({ length: total }, (_, i) => i < count);

  /* --------------------------------------------------------------------------------------------------------------------------- the sun and the clock */

  const RAD = Math.PI / 180;
  /** The sun's height above the horizon in degrees for a moment (ms since 1970) at a place (low-precision almanac formulas, good to a fraction of a degree). */
  function sunAltitude(ms, lat, lon) {
    const d = ms / 86400000 + 2440587.5 - 2451545.0;
    const g = (357.529 + 0.98560028 * d) * RAD;
    const q = 280.459 + 0.98564736 * d;
    const L = (q + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * RAD;
    const e = (23.439 - 0.00000036 * d) * RAD;
    const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
    const dec = Math.asin(Math.sin(e) * Math.sin(L));
    const gmst = ((18.697374558 + 24.06570982441908 * d) % 24 + 24) % 24;
    const H = (gmst * 15 + lon) * RAD - ra;
    return Math.asin(clamp(Math.sin(lat * RAD) * Math.sin(dec) + Math.cos(lat * RAD) * Math.cos(dec) * Math.cos(H), -1, 1)) / RAD;
  }
  const PHASES = ['day', 'gold', 'blue', 'night'];
  /** How much of each time of day the city shows at a sun height: day (high sun), golden hour (low sun), blue hour (just below the horizon), night. At most two
   *  neighbours are mixed, and the weights add up to one. */
  function phaseWeights(alt) {
    const w = { day: 0, gold: 0, blue: 0, night: 0 };
    if (alt >= 18) w.day = 1;
    else if (alt >= 6) { w.day = smooth(6, 18, alt); w.gold = 1 - w.day; }
    else if (alt >= 0) w.gold = 1;
    else if (alt >= -6) { w.blue = smooth(0, -6, alt); w.gold = 1 - w.blue; }
    else if (alt >= -14) { w.night = smooth(-6, -14, alt); w.blue = 1 - w.night; }
    else w.night = 1;
    return w;
  }
  const LIGHT_CURVE = [[14, 0.02], [6, 0.10], [0, 0.24], [-6, 0.62], [-12, 0.95], [-16, 1]];
  /** How far the window lights have come on, 0 to 1: a few offices by day, a quarter at sunset, most by the end of the blue hour, all at night. */
  function lightLevel(alt) {
    if (alt >= LIGHT_CURVE[0][0]) return LIGHT_CURVE[0][1];
    for (let i = 1; i < LIGHT_CURVE.length; i++) {
      const [a1, v1] = LIGHT_CURVE[i - 1], [a2, v2] = LIGHT_CURVE[i];
      if (alt >= a2) return lerp(v2, v1, (alt - a2) / (a1 - a2));
    }
    return 1;
  }
  /** How much of ten batches of window lights is shown: batch k has `clamp(level * 10 - k)` of its light, so they come on one after the other, never all at once. */
  const batchAlphas = (level, count) => Array.from({ length: count }, (_, k) => clamp(level * count - k, 0, 1));
  const dayState = (ms, place) => {
    const alt = sunAltitude(ms, place.lat, place.lon);
    // The same sun altitude occurs twice a day. A gentle slope distinguishes
    // a rosy morning from a warmer evening, without a jump around noon.
    const rising = smooth(-.2, .2, sunAltitude(ms + 600000, place.lat, place.lon) - sunAltitude(ms - 600000, place.lat, place.lon));
    return { alt, rising, weights: phaseWeights(alt), lights: lightLevel(alt), stars: smooth(-6, -15, alt), moon: smooth(-4, -12, alt), dusk: 1 - smooth(-8, 2, alt) };
  };
  /** The moon's phase, 0 (new) to 1, by the synodic month from a known new moon (2000-01-06 18:14 UTC). */
  const moonPhase = (ms) => ((((ms - Date.UTC(2000, 0, 6, 18, 14)) / 86400000) % 29.530588853) + 29.530588853) % 29.530588853 / 29.530588853;
  /** The page passes its already validated, fresh outside observation. Unknown
   *  is deliberately dry and never synthesises rain from the calendar. */
  function observedWeather(reading) {
    if (!reading || !Number.isInteger(reading.code)) return 'unknown';
    const c = reading.code;
    if (c === 0 || c === 1) return 'clear';
    if (c === 2) return 'partly';
    if (c === 3) return 'cloud';
    if (c === 45 || c === 48) return 'fog';
    if ([51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82].includes(c)) return 'rain';
    if ([71, 73, 75, 77, 85, 86].includes(c)) return 'snow';
    if (c === 95 || c === 96 || c === 99) return 'storm';
    return 'unknown';
  }
  function marketOpen(ms) {
    const d = new Date(ms), h = d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600;
    return smooth(7.5, 8, h) * (1 - smooth(19.5, 20, h));
  }

  /** One distinct bank at a time crosses the city. Let it leave completely,
   *  then leave a clear interval before a different one enters from an edge. */
  function stepFog(s, dt) {
    const active = s.fog.find(f => f.active);
    if (active) {
      active.x += active.dir * active.speed * dt;
      if ((active.dir > 0 && active.x >= s.W) || (active.dir < 0 && active.x + active.canvas.width <= 0)) {
        active.active = false;
        s.fogWait = 20 + s.rnd() * 45;
      }
      return;
    }
    s.fogWait -= dt;
    if (s.fogWait > 0) return;
    s.fogLast = (s.fogLast + 1 + Math.floor(s.rnd() * (s.fog.length - 1))) % s.fog.length;
    const next = s.fog[s.fogLast];
    next.dir = s.rnd() < .5 ? 1 : -1;
    next.x = next.dir > 0 ? -next.canvas.width : s.W;
    next.y = 85 + s.rnd() * 170;
    next.speed = 2.1 + s.rnd() * 1.5;
    next.active = true;
  }

  /* --------------------------------------------------------------------------------------------------------------------------- traffic and hiding */

  const LIGHT_PERIOD = 28;
  /** A traffic light's colour for a street direction ('x' or 'y') at a time: green 11 s, yellow 2 s, a second of red for everyone, then the other way. Each
   *  crossing is shifted by its index so the city does not breathe in step. */
  function lightState(index, axis, seconds) {
    const t = (((seconds + index * 5.3) % LIGHT_PERIOD) + LIGHT_PERIOD) % LIGHT_PERIOD;
    const u = axis === 'x' ? t : (t + LIGHT_PERIOD / 2) % LIGHT_PERIOD;
    return u < 11 ? 'g' : u < 13 ? 'y' : 'r';
  }
  /** Is the point (gx, gy) of the ground, `z` pixels up, hidden by the box `b` = [x0, y0, x1, y1, z0, z1] from where the camera is? The camera looks along (1, 1)
   *  and down, so a building hides what is behind it exactly when the line from the point towards the camera (gx + s, gy + s, z + 6 s) passes through it. */
  function hiddenBy(b, gx, gy, z) {
    const lo = Math.max(b[0] - gx, b[1] - gy, (b[4] - z) / 6, 1e-6);
    const hi = Math.min(b[2] - gx, b[3] - gy, (b[5] - z) / 6);
    return lo <= hi;
  }
  /** Same, for a pixel of the id picture: `ids[y * width + x]` is the building drawn there (0: none), `boxes[id]` its box (null: a lawn, which hides nothing). */
  function isHidden(ids, width, boxes, x, y, gx, gy, z, ignoreRail, ignoreId) {
    if (x < 0 || y < 0 || x >= width) return false;
    const id = ids[y * width + x];
    if (!id || id === ignoreId) return false;
    const b = boxes[id];
    if (!b || (ignoreRail && b[6] === 1)) return false;
    return hiddenBy(b, gx, gy, z);
  }

  /* Keep traffic visually subordinate to the streets at tablet size. The
   * sprites use whole pixels, so these dimensions are intentionally slightly
   * smaller than their physical scale to avoid exaggerating cars and lights. */
  const VEHICLES = {                 // length and width in cells, height in pixels, top speed in cells a second, weight
    car: { len: .33, wid: .14, h: 1.5, speed: 1.25, weight: 17 },
    taxi: { len: .33, wid: .14, h: 1.5, speed: 1.2, weight: 3 },
    van: { len: .44, wid: .16, h: 1.7, speed: 1.1, weight: 3 },
    truck: { len: .64, wid: .18, h: 2.0, speed: .95, weight: 1.2 },
    bus: { len: .74, wid: .18, h: 2.0, speed: .9, weight: 1.6 },
  };
  const GROUP_WALK_SPEED = .32;
  const groupWalk = (start, seconds, index, direction, length) => clamp(start + direction * (Math.max(0, seconds) * GROUP_WALK_SPEED - index * .18), 0, length);
  const routeLength = (route) => Array.isArray(route) ? route.slice(1).reduce((sum, p, i) => sum + Math.hypot(p[0] - route[i][0], p[1] - route[i][1]), 0) : 0;
  function routePoint(route, distance) {
    if (!Array.isArray(route) || route.length < 2) return null;
    let left = Math.max(0, distance);
    for (let i = 1; i < route.length; i++) {
      const a = route[i - 1], b = route[i], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (len > 0 && left <= len) return [lerp(a[0], b[0], left / len), lerp(a[1], b[1], left / len)];
      left -= len;
    }
    return route[route.length - 1].slice();
  }
  function linkedStory(start, now, route) {
    const len = routeLength(route);
    if (!finite(start) || !finite(now) || len <= 0) return {phase: 'waiting', time: 0};
    const age = Math.max(0, now - start), matchAt = 4 + len / GROUP_WALK_SPEED + 3;
    if (age < 4) return {phase: 'unloading', time: age};
    if (age < matchAt) return {phase: 'fans', time: age - 4};
    if (age < matchAt + 70) return {phase: 'match', time: age - matchAt};
    if (age < matchAt + 85) return {phase: 'fireworks', time: age - matchAt - 70};
    if (age < matchAt + 105) return {phase: 'parade', time: age - matchAt - 85};
    return {phase: 'done', time: age - matchAt - 105};
  }
  function nearestShelter(walk, along, shelters) {
    if (!walk || !Array.isArray(shelters)) return null;
    const dx = walk.b[0] - walk.a[0], dy = walk.b[1] - walk.a[1], len = Math.hypot(dx, dy);
    if (len <= 0) return null;
    let best = null, score = Infinity;
    for (const p of shelters) {
      const x = p[0] - walk.a[0], y = p[1] - walk.a[1], t = (x * dx + y * dy) / len;
      const across = Math.abs(x * dy - y * dx) / len;
      if (t < 0 || t > len || across > 1.25) continue;
      const cost = Math.abs(t - along) + across * 2;
      if (cost < score) { score = cost; best = t; }
    }
    return best;
  }
  function stepPedestrian(p, dt, wet) {
    if (wet && finite(p.shelter)) {
      const delta = p.shelter - p.s;
      p.s += clamp(delta, -p.speed * dt, p.speed * dt);
      p.sheltering = Math.abs(p.shelter - p.s) < .08;
      return;
    }
    p.sheltering = false;
    p.s += p.dir * p.speed * dt;
    if (p.s < 0 || p.s > p.len) { p.dir = -p.dir; p.s = clamp(p.s, 0, p.len); }
  }
  const CAR_COLOURS = [[226, 228, 234], [226, 228, 234], [30, 32, 42], [30, 32, 42], [150, 156, 168], [190, 194, 202], [168, 36, 36], [48, 74, 138], [40, 100, 82], [236, 176, 40], [214, 120, 40], [100, 66, 52], [92, 140, 196], [124, 60, 120]];
  const TRUCK_COLOURS = [[236, 238, 240], [196, 60, 48], [60, 100, 170], [210, 160, 50], [90, 130, 96]];
  const pickKind = (rnd) => {
    const total = Object.values(VEHICLES).reduce((a, v) => a + v.weight, 0);
    let r = rnd() * total;
    for (const [kind, v] of Object.entries(VEHICLES)) { r -= v.weight; if (r <= 0) return kind; }
    return 'car';
  };
  const MAX_VEHICLES = 132, CAR_SPACING = 3.5;       // the traffic is a fixed, small budget: about one vehicle every three and a half cells of the streets that can be seen
  /** The traffic of every visible street lane: cars, taxis, vans, trucks and buses that keep a gap behind the one in front, stop at a red light (and a yellow one, when
   *  they can), queue, and start again, leave at the far end and come back at the start. Pure: the random numbers are given, so a seed gives the same traffic. */
  function makeTraffic(lanes, rnd) {
    const sim = { lanes: [], t: 0 };
    const usable = lanes.filter((lane) => Math.hypot(lane.b[0] - lane.a[0], lane.b[1] - lane.a[1]) > 2);
    const wanted = usable.reduce((a, lane) => a + Math.hypot(lane.b[0] - lane.a[0], lane.b[1] - lane.a[1]) / CAR_SPACING, 0);
    const scale = wanted > MAX_VEHICLES ? MAX_VEHICLES / wanted : 1;
    for (const lane of usable) {
      const dx = lane.b[0] - lane.a[0], dy = lane.b[1] - lane.a[1], length = Math.hypot(dx, dy);
      const entry = { lane, length, ux: dx / length, uy: dy / length, cars: [], cross: lane.cross || [] };
      const count = clamp(Math.round(length / CAR_SPACING * scale), 1, 16);
      for (let i = 0; i < count; i++) entry.cars.push(newVehicle(entry, rnd, (i + rnd() * .7) / count * length));
      sim.lanes.push(entry);
    }
    return sim;
  }
  function newVehicle(entry, rnd, s) {
    const kind = pickKind(rnd), spec = VEHICLES[kind];
    const colour = kind === 'taxi' ? [238, 178, 40] : kind === 'bus' ? [[222, 120, 36], [60, 110, 190], [226, 228, 232], [196, 56, 52]][Math.floor(rnd() * 4)]
      : kind === 'truck' ? TRUCK_COLOURS[Math.floor(rnd() * TRUCK_COLOURS.length)] : CAR_COLOURS[Math.floor(rnd() * CAR_COLOURS.length)];
    return { kind, s, v: spec.speed * (.7 + rnd() * .3), vmax: spec.speed * (.75 + rnd() * .35), len: spec.len, colour, id: Math.floor(rnd() * 1e9) };
  }
  function stepTraffic(sim, dt, seconds, rnd, bridge) {
    sim.t = seconds;
    for (const entry of sim.lanes) {
      const cars = entry.cars;
      const bridgeLane = bridge && entry.lane.axis === 'y' && Math.abs(entry.lane.a[0] - bridge.gx - .5) < .8;
      cars.sort((a, b) => b.s - a.s);                                  // the front one first
      for (let i = 0; i < cars.length; i++) {
        const car = cars[i];
        let target = car.vmax;
        const ahead = i > 0 ? cars[i - 1] : null;
        if (ahead) {
          const gap = ahead.s - ahead.len / 2 - car.s - car.len / 2 - .2;             // free road in front, in cells (about two metres)
          target = Math.min(target, Math.max(0, gap * 1.2));
        }
        for (const [stop, light] of entry.cross) {
          const crossingY = entry.lane.a[1] + entry.uy * stop;
          if (bridgeLane && crossingY >= bridge.y0 - .1 && crossingY <= bridge.y1 + .1) continue; // there is no traffic light on the lifting deck
          const colour = lightState(light, entry.lane.axis, seconds);
          const room = stop - car.s;
          if (room > -.2 && room < 1.8 && (colour === 'r' || (colour === 'y' && room > .6))) target = Math.min(target, Math.max(0, room * 1.3));
        }
        if (bridgeLane && bridge.closed !== false) {
          const edge = entry.uy > 0 ? bridge.y0 - .7 : bridge.y1 + .7;
          const stop = (edge - entry.lane.a[1]) / entry.uy, room = stop - car.s;
          if (room > -.2 && room < 4) target = Math.min(target, Math.max(0, room * 1.5));
        }
        const carY = entry.lane.a[1] + entry.uy * car.s;
        const onDeck = bridgeLane && carY >= bridge.y0 - .6 && carY <= bridge.y1 + .6;
        if (!onDeck && car.kind === 'bus' && !car.stopped && finite(entry.pickup)) {
          const room = entry.pickup - car.s;
          if (room >= 0 && room < 1.6) target = Math.min(target, room);
          if (room >= 0 && room < .15 && car.v < .2) { car.stopped = true; car.stopLeft = 3 + rnd() * 2; }
        }
        if (!onDeck && (car.kind === 'taxi' || car.kind === 'van' || (car.kind === 'bus' && !finite(entry.pickup))) && !car.stopped && car.s > entry.length * .55 && car.s < entry.length * .75) {
          car.stopped = true; car.stopLeft = 1.8 + rnd() * 2;
        }
        if (car.stopLeft > 0) { car.stopLeft -= dt; target = 0; }
        car.v += clamp(target - car.v, -1.1 * dt, .5 * dt);
        car.s += car.v * dt;
        if (ahead) {
          const safe = ahead.s - (ahead.len + car.len) / 2 - .12;
          if (car.s > safe) { car.s = safe; car.v = Math.min(car.v, ahead.v); }
        }
      }
      const front = cars[0];
      if (front && front.s > entry.length + 3) {                         // out of the far end: back in at the start, a new vehicle
        cars.shift();
        const last = cars.length ? cars[cars.length - 1].s : entry.length;
        cars.push(newVehicle(entry, rnd, Math.min(-1.5, last - 1.2 - rnd() * 3)));
      }
    }
  }

  /* ---------------------------------------------------------------------------------------------------------------------------------- exports */
  const logic = { NAME, SIZE, STEP, STALE_MS, WEEK_CELLS, SMALL_CELLS, SMALL_FLOOR_CELLS, PHASES, LIGHT_PERIOD, VEHICLES, MAX_VEHICLES, weekCells, sessionCells, dataState, litFlags,
    sunAltitude, phaseWeights, lightLevel, batchAlphas, dayState, moonPhase, observedWeather, marketOpen, stepFog, lightState, hiddenBy, isHidden, makeTraffic, stepTraffic, groupWalk, GROUP_WALK_SPEED, routeLength, routePoint, linkedStory, nearestShelter, stepPedestrian, smooth, mixRgb };

  /* ------------------------------------------------------------------------------------------------------------------------------- camera and weather */
  /** Keep the city's camera fixed at the middle of the atlas margin. */
  function cameraAt(t, phase, margin) {
    const m = margin || [12, 12];
    return [m[0], m[1]];
  }
  Object.assign(logic, { cameraAt });

  /* A small, repeatable timetable keeps major events apart. Time is continuous:
   * all actors finish their journey before the timetable starts again. */
  function lifePhase(seconds) {
    const t = ((seconds % 240) + 240) % 240;
    const bridge = t < 150 || t >= 180 ? 0 : t < 156 ? smooth(150, 156, t) : t < 172 ? 1 : 1 - smooth(172, 180, t);
    return { t, match: t >= 15 && t < 103, goal: t >= 73 && t < 79,
      fireworks: t >= 103 && t < 118, parade: t >= 119 && t < 139,
      bridge, bridgeClosed: t >= 142 && t < 182 };
  }
  const bridgeFerryX = (seconds) => {
    const t = lifePhase(seconds).t;
    return t >= 125 && t < 190 ? lerp(38, 95, (t - 125) / 65) : null;
  };
  const travel = (a, b, u) => a.map((v, i) => lerp(v, b[i], smooth(0, 1, u)));
  function flightPads(pads) {
    if (!Array.isArray(pads) || pads.length < 2) return null;
    const hospital = pads.find(p => p.role === 'hospital');
    const rooftops = hospital ? pads.filter(p => p !== hospital) : pads;
    if (rooftops.length < 2) return {rescue: hospital || pads[0], a: pads[0], b: pads[1]};
    return {rescue: hospital || pads[0], a: rooftops[0], b: rooftops[1]};
  }
  function helicopterFlights(s, seconds) {
    const pads = (s.data.living && s.data.living.pads) || [];
    const sites = flightPads(pads);
    if (!sites) return [];
    const t = lifePhase(seconds).t, a = sites.a.point, b = sites.b.point, r = sites.rescue.point;
    const high = Math.max(a[2], b[2], r[2]) + 24, ah = [a[0], a[1], high], bh = [b[0], b[1], high], rh = [r[0], r[1], high];
    const [, sy] = projWorld(s, r[0], r[1], r[2]);
    const outside = unprojWorld(s, -30, sy - 65 + high).concat(high);
    let rescue = null;
    if (t >= 5 && t < 17) rescue = travel(outside, rh, (t - 5) / 12);
    else if (t >= 17 && t < 22) rescue = travel(rh, r, (t - 17) / 5);
    else if (t >= 22 && t < 32) rescue = r;
    else if (t >= 32 && t < 37) rescue = travel(r, rh, (t - 32) / 5);
    else if (t >= 37 && t < 49) rescue = travel(rh, outside, (t - 37) / 12);
    let shuttle = b, heading = t >= 99 && t < 130 ? 1 : -1;
    if (t >= 58 && t < 63) shuttle = travel(b, bh, (t - 58) / 5);
    else if (t >= 63 && t < 70) shuttle = travel(bh, ah, (t - 63) / 7);
    else if (t >= 70 && t < 75) shuttle = travel(ah, a, (t - 70) / 5);
    else if (t >= 75 && t < 94) shuttle = a;
    else if (t >= 94 && t < 99) shuttle = travel(a, ah, (t - 94) / 5);
    else if (t >= 99 && t < 106) { shuttle = travel(ah, bh, (t - 99) / 7); heading = 1; }
    else if (t >= 106 && t < 111) { shuttle = travel(bh, b, (t - 106) / 5); heading = 1; }
    return [{kind: 'shuttle', point: shuttle, heading}, ...(rescue ? [{kind: 'rescue', point: rescue, heading: t < 32 ? 1 : -1}] : [])];
  }
  Object.assign(logic, { lifePhase, bridgeFerryX, helicopterFlights, flightPads });

  /* ---------------------------------------------------------------------------------------------------------------------------------- small sprites */
  const HW = 6, HH = 3;
  const projPx = (gx, gy, z) => [(gx - gy) * HW, (gx + gy) * HH - (z || 0)];
  const inQuad = (q, x, y) => {                                                        // a point inside a convex quad (either winding)
    let pos = false, neg = false;
    for (let i = 0; i < q.length; i++) {
      const a = q[i], b = q[(i + 1) % q.length];
      const c = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]);
      if (c > 0) pos = true; else if (c < 0) neg = true;
      if (pos && neg) return false;
    }
    return true;
  };
  const bridgeDeckQuads = (quads) => (quads || []).map(q => q.map(([x, y]) => [x, y + 3]));
  const shade = (c, k) => [Math.min(255, Math.round(c[0] * k)), Math.min(255, Math.round(c[1] * k)), Math.min(255, Math.round(c[2] * k))];
  /** Rasterise little isometric boxes (and flat polygons) into whole pixels, no anti-aliasing: the vehicles, boats and trains of the scene.
   *  boxes: {x0, y0, x1, y1, z0, z1, body, roof, glass: [from, to] or null} in cells and pixels, drawn in order; polys: {pts: [[x, y]], colour} in pixels (a colour may
   *  carry a fourth number, its opacity: a headlight's beam). `ss` is how finely each pixel is sampled (1: the centre only; 3: nine samples and the commonest
   *  colour wins, which gives the tiny vehicles clean shapes). Returns the pixels (relative to the footprint centre of the first box) and a canvas holding them. */
  function rasterise(boxes, polys, ends, makeCanvas, ss) {
    const faces = [];
    for (const b of boxes) {
      const { x0, y0, x1, y1, z0, z1 } = b;
      faces.push({ q: [projPx(x0, y1, z0), projPx(x1, y1, z0), projPx(x1, y1, z1), projPx(x0, y1, z1)], c: shade(b.body, .62), side: 'left', b });
      faces.push({ q: [projPx(x1, y1, z0), projPx(x1, y0, z0), projPx(x1, y0, z1), projPx(x1, y1, z1)], c: b.body, side: 'right', b });
      faces.push({ q: [projPx(x0, y0, z1), projPx(x1, y0, z1), projPx(x1, y1, z1), projPx(x0, y1, z1)], c: b.roof || shade(b.body, 1.18), side: 'top', b });
    }
    for (const p of polys || []) faces.push({ q: p.pts, c: p.colour, side: 'flat' });
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    for (const f of faces) for (const p of f.q) { minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]); minY = Math.min(minY, p[1]); maxY = Math.max(maxY, p[1]); }
    const x0 = Math.floor(minX), y0 = Math.floor(minY), w = Math.ceil(maxX) - x0, h = Math.ceil(maxY) - y0;
    const grid = new Array(w * h).fill(null);
    const n = ss > 1 ? ss : 1;
    const colourAt = (f, px, py) => {
      if (f.b && f.b.glass && f.side !== 'top') {                                         // a band of windows along the sides
        const bottom = f.q[0][1] + (f.q[1][1] - f.q[0][1]) * clamp((px - f.q[0][0]) / ((f.q[1][0] - f.q[0][0]) || 1), 0, 1);
        const v = (bottom - py) / (f.b.z1 - f.b.z0);
        if (v > f.b.glass[0] && v < f.b.glass[1]) return f.b.windowColour || [34, 44, 64];
      }
      return f.c;
    };
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      if (n === 1) {
        const px = x0 + x + .5, py = y0 + y + .5;
        for (const f of faces) if (inQuad(f.q, px, py)) grid[y * w + x] = colourAt(f, px, py);
        continue;
      }
      const counts = new Map();
      let covered = 0;
      for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
        const px = x0 + x + (i + .5) / n, py = y0 + y + (j + .5) / n;
        let colour = null;
        for (const f of faces) if (inQuad(f.q, px, py)) colour = colourAt(f, px, py);
        if (!colour) continue;
        covered++;
        const key = colour.join(), e = counts.get(key);
        if (e) e.n++; else counts.set(key, { n: 1, c: colour });
      }
      if (covered < Math.ceil(n * n * .45)) continue;                                        // at least about half of the pixel covered
      let best = null;
      for (const e of counts.values()) if (!best || e.n > best.n) best = e;
      if (best) grid[y * w + x] = best.c;
    }
    if (ends) for (const e of ends) {                                                       // lights on the visible end face
      const f = faces.find((q) => q.side === e.face && q.b === boxes[0]);
      if (!f) continue;
      for (const t of e.spots || [.3, .7]) {
        const bx = f.q[0][0] + (f.q[1][0] - f.q[0][0]) * t, by = f.q[0][1] + (f.q[1][1] - f.q[0][1]) * t - (boxes[0].z1 - boxes[0].z0) * (e.height || .38);
        const gx = Math.floor(bx - x0), gy = Math.floor(by - y0);
        if (gx >= 0 && gy >= 0 && gx < w && gy < h) grid[gy * w + gx] = e.colour;
      }
    }
    const fx = (boxes[0].x0 + boxes[0].x1) / 2, fy = (boxes[0].y0 + boxes[0].y1) / 2;
    const anchor = projPx(fx, fy, 0);
    const css = (c) => (c.length > 3 ? 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + c[3] + ')' : rgb(c));
    const pixels = [];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (grid[y * w + x]) pixels.push([x, y, grid[y * w + x], css(grid[y * w + x])]);
    const canvas = makeCanvas(w, h), ctx = canvas.getContext('2d');
    for (const p of pixels) { ctx.fillStyle = p[3]; ctx.fillRect(p[0], p[1], 1, 1); }
    return { w, h, ax: Math.round(anchor[0] - x0), ay: Math.round(anchor[1] - y0), pixels, canvas };
  }

  const FONT = {
    A: '.#.|#.#|###|#.#|#.#', B: '##.|#.#|##.|#.#|##.', C: '.##|#..|#..|#..|.##', D: '##.|#.#|#.#|#.#|##.', E: '###|#..|##.|#..|###', F: '###|#..|##.|#..|#..',
    G: '.##|#..|#.#|#.#|.##', H: '#.#|#.#|###|#.#|#.#', I: '###|.#.|.#.|.#.|###', J: '..#|..#|..#|#.#|.#.', K: '#.#|#.#|##.|#.#|#.#', L: '#..|#..|#..|#..|###',
    M: '#.#|###|###|#.#|#.#', N: '##.|#.#|#.#|#.#|#.#', O: '.#.|#.#|#.#|#.#|.#.', P: '##.|#.#|##.|#..|#..', Q: '.#.|#.#|#.#|.##|..#', R: '##.|#.#|##.|#.#|#.#',
    S: '.##|#..|.#.|..#|##.', T: '###|.#.|.#.|.#.|.#.', U: '#.#|#.#|#.#|#.#|###', V: '#.#|#.#|#.#|#.#|.#.', W: '#.#|#.#|###|###|#.#', X: '#.#|#.#|.#.|#.#|#.#',
    Y: '#.#|#.#|.#.|.#.|.#.', Z: '###|..#|.#.|#..|###', 0: '###|#.#|#.#|#.#|###', 1: '.#.|##.|.#.|.#.|###', 2: '##.|..#|.#.|#..|###', 3: '##.|..#|.#.|..#|##.',
    4: '#.#|#.#|###|..#|..#', 5: '###|#..|##.|..#|##.', 6: '.##|#..|###|#.#|###', 7: '###|..#|.#.|.#.|.#.', 8: '###|#.#|###|#.#|###', 9: '###|#.#|###|..#|##.',
    '-': '...|...|###|...|...', ' ': '...|...|...|...|...', '*': '...|#.#|.#.|#.#|...', '.': '...|...|...|...|.#.',
  };
  /** The same line of text as a list of lit pixels [x, y], for drawing only the letters that are not behind a building. */
  function textPixels(text) {
    const out = [];
    [...text].forEach((ch, i) => (FONT[ch] || FONT[' ']).split('|').forEach((row, y) => { for (let x = 0; x < 3; x++) if (row[x] === '#') out.push([i * 4 + x, y]); }));
    return out;
  }
  /** A line of text in a 3 x 5 pixel font, white on transparent, with a gap after each letter: for the blimp's billboard. */
  function textStrip(text, makeCanvas, colour) {
    const canvas = makeCanvas(text.length * 4, 5), ctx = canvas.getContext('2d');
    ctx.fillStyle = colour || '#fff';
    [...text].forEach((ch, i) => {
      const rows = (FONT[ch] || FONT[' ']).split('|');
      rows.forEach((row, y) => { for (let x = 0; x < 3; x++) if (row[x] === '#') ctx.fillRect(i * 4 + x, y, 1, 1); });
    });
    return canvas;
  }
  function scorePicture(goal, makeCanvas) {
    const canvas = makeCanvas(7, 3), g = canvas.getContext('2d');
    const rows = goal ? ['.#..###', '.#..#.#', '.#..###'] : ['###.###', '#.#.#.#', '###.###'];
    g.fillStyle = '#e9f8c0';
    rows.forEach((row, y) => [...row].forEach((ch, x) => { if (ch === '#') g.fillRect(x, y, 1, 1); }));
    return canvas;
  }

  /* --------------------------------------------------------------------------------------------------------------------------------- the scene */
  const HEAD = [255, 246, 204], TAIL = [255, 64, 52];
  const PEOPLE = [[168, 96, 90], [98, 120, 168], [184, 160, 96], [150, 152, 162], [106, 148, 122], [138, 104, 158], [58, 58, 70]];
  const SCREEN_TEXT = 'AI DESK DISPLAY  *  ';
  const AIR_MESSAGES = [SCREEN_TEXT, 'CITY EXPRESS  *  ', 'WELCOME HOME  *  ', 'MATCH DAY  *  '];

  /** A vehicle for a heading, built of a few little boxes (a body and a cabin, a van's cab and cargo, a truck's cab and box, a bus's long window band) and sampled
   *  finely so that even four pixels have a clean shape. Only `lit` (after dusk) has its headlights and tail lights on, and a faint beam on the road ahead and a
   *  faint red glow behind (translucent pixels in the sprite itself, so they cost nothing more to draw). */
  function vehicleSprite(s, kind, colour, axis, sign, lit) {
    const key = kind + colour.join(',') + axis + sign + (lit ? 'L' : '');
    let sprite = s.sprites.get(key);
    if (sprite) return sprite;
    const spec = VEHICLES[kind], L = spec.len, Wd = spec.wid, H = spec.h;
    const along = (u0, u1, v0, v1) => (axis === 'x' ? [u0, v0, u1, v1] : [v0, u0, v1, u1]);          // (length, width) to (x0, y0, x1, y1)
    const front = (a, b) => (sign > 0 ? [a, b] : [L - b, L - a]);                                    // a stretch of the length, counted from the rear, as it lies on the road
    const box = (a, b, v0, v1, z0, z1, body, extra) => {
      const [u0, u1] = front(a, b), [x0, y0, x1, y1] = along(u0, u1, v0, v1);
      return Object.assign({ x0, y0, x1, y1, z0, z1, body }, extra || {});
    };
    const light = (c, k) => shade(c, k);
    const glass = [30, 40, 58], glassLit = [255, 226, 150];
    let boxes;
    if (kind === 'bus') boxes = [box(0, L, 0, Wd, 0, H, colour, { roof: light(colour, 1.28), glass: [.34, .8], windowColour: lit ? glassLit : [44, 60, 86] })];
    else if (kind === 'van') boxes = [box(0, L * .7, 0, Wd, 0, H, shade(colour, 1.0), { roof: light(colour, 1.25) }), box(L * .7, L, .02, Wd - .02, 0, H * .72, colour, { roof: light(colour, 1.2), glass: [.5, .95], windowColour: glass })];
    else if (kind === 'truck') boxes = [box(0, L * .76, 0, Wd, H * .12, H, [226, 228, 232], { roof: [244, 244, 246] }), box(L * .8, L, .02, Wd - .02, 0, H * .7, colour, { roof: light(colour, 1.25), glass: [.5, .95], windowColour: glass })];
    else {
      boxes = [box(0, L, 0, Wd, 0, H * .52, colour, { roof: light(colour, 1.22) }), box(L * .2, L * .66, Wd * .1, Wd * .9, H * .52, H, glass, { roof: light(colour, 1.1) })];
      if (kind === 'taxi') boxes.push(box(L * .36, L * .52, Wd * .3, Wd * .7, H, H + .6, [255, 244, 170], { roof: [255, 250, 210] }));
    }
    const pt = (u, v) => (axis === 'x' ? projPx(u, v, 0) : projPx(v, u, 0));
    const aheadU = sign > 0 ? [L, L + .32] : [0, -.32], behindU = sign > 0 ? [0, -.12] : [L, L + .12];
    const polys = lit ? [
      { pts: [pt(aheadU[0], Wd * .1), pt(aheadU[1], -Wd * .2), pt(aheadU[1], Wd * 1.2), pt(aheadU[0], Wd * .9)], colour: [255, 238, 190, .3] },
      { pts: [pt(behindU[0], Wd * .1), pt(behindU[1], Wd * .05), pt(behindU[1], Wd * .95), pt(behindU[0], Wd * .9)], colour: [255, 60, 50, .35] },
    ] : null;
    const ends = lit ? [{ face: axis === 'x' ? 'right' : 'left', colour: sign > 0 ? HEAD : TAIL, spots: [.22, .78], height: .32 }] : null;
    sprite = rasterise(boxes, polys, ends, s.mk, 3);
    s.sprites.set(key, sprite);
    return sprite;
  }
  function boatSprite(s, kind, axis, sign, lit) {
    const key = 'boat' + kind + axis + sign + (lit ? 'L' : '');
    let sprite = s.sprites.get(key);
    if (sprite) return sprite;
    let boxes, polys = [];
    const L = kind === 'f' ? 2.4 : kind === 't' ? 1.5 : 1.1, Wd = kind === 'f' ? .7 : kind === 't' ? .5 : .34;
    const lx = axis === 'x' ? L : Wd, ly = axis === 'x' ? Wd : L;
    const along = (u, v) => (axis === 'x' ? [u, v] : [v, u]);
    const box = (u0, v0, u1, v1, z0, z1, body, extra) => {
      const [a0, b0] = along(u0, v0), [a1, b1] = along(u1, v1);
      return Object.assign({ x0: a0, y0: b0, x1: a1, y1: b1, z0, z1, body }, extra || {});
    };
    if (kind === 'f') boxes = [box(0, 0, L, Wd, 0, 1.3, [226, 230, 236]), box(.45, .1, 1.75, Wd - .1, 1.3, 3.5, [244, 244, 248], { glass: [.25, .8], windowColour: lit ? [255, 222, 150] : [60, 80, 110] }),
      box(1.85, .24, 2.1, Wd - .24, 3.5, 5.2, [208, 66, 52])];
    else if (kind === 't') boxes = [box(0, 0, L, Wd, 0, 1.4, [196, 54, 46]), box(.25, .08, 1.0, Wd - .08, 1.4, 3.0, [240, 240, 244], { glass: [.3, .8], windowColour: lit ? [255, 214, 140] : [50, 70, 100] })];
    else {
      boxes = [box(0, 0, L, Wd, 0, 1.0, [238, 238, 232])];
      const mid = Wd / 2, pt = (u, z) => { const p = axis === 'x' ? projPx(u, mid, z) : projPx(mid, u, z); return p; };
      const flip = sign > 0 ? 1 : 0;                                                      // the sail leans from the mast towards the stern
      polys = [{ pts: [pt(.2, 1.0), pt(.95, 1.0), pt(.32 + flip * .0, 9.5)], colour: [250, 250, 244] }, { pts: [pt(.1, 1.0), pt(.24, 1.0), pt(.28, 8.5)], colour: [226, 230, 238] }];
    }
    sprite = rasterise(boxes, polys, null, s.mk);
    s.sprites.set(key, sprite);
    return sprite;
  }
  function trainSprite(s, loco, lit, sign) {
    const key = 'train' + loco + lit + sign;
    let sprite = s.sprites.get(key);
    if (sprite) return sprite;
    const body = loco ? [60, 92, 150] : [188, 196, 208];
    const car = { x0: 0, y0: 0, x1: 1.55, y1: .4, z0: 0, z1: 4.4, body, roof: shade(body, 1.2), glass: [.38, .78], windowColour: lit ? [255, 222, 140] : [40, 54, 80] };
    const stripe = { x0: 0, y0: 0, x1: 1.55, y1: .4, z0: 0, z1: 1.1, body: shade(body, .8) };
    sprite = rasterise([stripe, car], null, loco ? [{ face: 'right', colour: sign > 0 ? HEAD : TAIL }] : null, s.mk);
    s.sprites.set(key, sprite);
    return sprite;
  }
  function heliSprite(s, flip, frame, variant) {
    const key = 'heli' + flip + frame + (variant || '');
    let c = s.sprites.get(key);
    if (c) return c;
    // Real projected volumes, like the cars below: a glazed cockpit, cabin,
    // tapered tail, landing skids and two rotor blades seen from above.
    let boxes = [
      {x0:-.55,y0:-.38,x1:.60,y1:.38,z0:1.5,z1:5,body:[78,88,102],roof:[157,169,178],glass:[.45,.86],windowColour:[92,166,197]},
      {x0:.48,y0:-.12,x1:1.78,y1:.12,z0:2.7,z1:3.8,body:[89,98,110],roof:[171,178,182]},
      {x0:1.54,y0:-.10,x1:1.76,y1:.10,z0:3.6,z1:5.6,body:[103,110,120],roof:[185,190,188]},
      {x0:-.92,y0:-.32,x1:-.50,y1:.32,z0:1.9,z1:4.5,body:[66,105,126],roof:[138,181,194],glass:[.18,.91],windowColour:[128,204,228]},
    ];
    if (variant === 'rescue') boxes = boxes.map((b, i) => ({...b, body: i === 0 ? [220, 226, 225] : i === 3 ? [100, 157, 176] : [182, 45, 48], roof: i === 0 ? [246, 246, 236] : [232, 117, 95]}));
    if (variant === 'shuttle') boxes = boxes.map((b, i) => ({...b, body: i === 0 ? [47, 88, 126] : i === 3 ? [69, 123, 153] : [35, 66, 103], roof: [127, 174, 198]}));
    // Turn the helicopter around its vertical axis, not by mirroring the
    // already-projected bitmap: a screen mirror reverses only one ground
    // axis, making its nose point across the return path.
    const direction = flip ? -1 : 1;
    if (flip) boxes = boxes.map(b => ({...b, x0:-b.x1, x1:-b.x0, y0:-b.y1, y1:-b.y0}));
    boxes.sort((a,b) => (a.x1 + a.y1) - (b.x1 + b.y1));
    const p = (x,y,z) => projPx(x * direction,y * direction,z);
    const flat = (a, colour) => ({pts:a.map(q => p(...q)), colour});
    const blades = frame % 2 ? [
      flat([[-1.35,-.16,7],[1.30,-.16,7],[1.30,.16,7],[-1.35,.16,7]], [210,218,221]),
      flat([[-.16,-1.05,7],[.16,-1.05,7],[.16,1.05,7],[-.16,1.05,7]], [180,190,199]),
    ] : [
      flat([[-1.08,1,7],[-1.22,.86,7],[1.08,-1,7],[1.22,-.86,7]], [210,218,221]),
      flat([[-1.10,-.74,7],[-.90,-.90,7],[1.10,.74,7],[.90,.90,7]], [180,190,199]),
    ];
    const details = [
      flat([[-.70,.46,.6],[.75,.46,.6],[.75,.55,.6],[-.70,.55,.6]], [48,55,65]),
      flat([[-.70,-.55,.6],[.75,-.55,.6],[.75,-.46,.6],[-.70,-.46,.6]], [94,103,110]),
      flat([[-.45,.39,2.25],[.53,.39,2.25],[.53,.39,2.75],[-.45,.39,2.75]], [201,70,62]),
      flat([[-.1,0,5],[.1,0,5],[.1,0,7],[-.1,0,7]], [202,210,214]),
      ...blades,
    ];
    // The route helicopters are further away than the old fly-over and must
    // fit their pads and surrounding cars. Keep the old sprite for old atlases.
    const scale = variant ? .76 : 1;
    if (scale !== 1) {
      boxes = boxes.map(b => ({...b, x0:b.x0*scale, y0:b.y0*scale, x1:b.x1*scale, y1:b.y1*scale, z0:b.z0*scale, z1:b.z1*scale}));
      for (const part of details) part.pts = part.pts.map(([x,y]) => [x*scale, y*scale]);
    }
    c = rasterise(boxes, details, null, s.mk, 3);
    s.sprites.set(key, c);
    return c;
  }

  function bitmapSprite(s, key, rows, palette, flip) {
    const cache = key + ':' + (flip ? 1 : 0);
    let sprite = s.sprites.get(cache);
    if (sprite) return sprite;
    const w = Math.max(...rows.map(row => row.length)), h = rows.length, cv = s.mk(w,h), ctx = cv.getContext('2d'), pixels = [];
    rows.forEach((row,y) => [...row].forEach((ch,x) => {
      const colour = palette[ch]; if (!colour) return;
      const px = flip ? w - 1 - x : x;
      ctx.fillStyle = colour; ctx.fillRect(px,y,1,1); pixels.push([px,y,null,colour]);
    }));
    pixels.sort((a,b)=>a[1]-b[1] || a[0]-b[0]);
    sprite = {canvas:cv,w,h,ax:Math.floor(w/2),ay:Math.floor(h/2),pixels};
    s.sprites.set(cache,sprite);
    return sprite;
  }

  function pigeonSprite(s, flip, frame) {
    const rows = frame ? ['.L...', 'LLL..', '.DLL.', '..D..'] : ['.....', '.LL..', 'LDDLL', '..D..'];
    return bitmapSprite(s, 'pigeon'+frame, rows, {L:'#d9dedc',D:'#84949d'}, flip);
  }

  function courierSprite(s, flip, frame) {
    // A tiny original delivery drone with two alternating thruster flames.
    const exhaust = frame ? ['....F......F...', '.....F....F....'] : ['.....F....F....', '....F......F...'];
    const rows = ['....MMMMMMM....', '..MMMTTTTTMMM..', '.MMTLLTTTLLTMM.', '..MMTTTTTTTMM..', '....MMMAAMM....', '.....MMMMM.....', ...exhaust];
    return bitmapSprite(s, 'courier'+frame, rows, {M:'#d9e6ec',T:'#30485b',L:'#57dce4',A:'#ffcc72',F:'#f68cbb'}, flip);
  }
  function blimpSprite(s, flip) {
    const key = 'blimp' + flip;
    let c = s.sprites.get(key);
    if (c) return c;
    const w = 52, h = 20, cv = s.mk(w, h), cx = cv.getContext('2d');
    const img = cx.createImageData(w, h), d = img.data;
    const put = (x, y, col) => { const xx = flip ? w - 1 - x : x; if (xx < 0 || y < 0 || xx >= w || y >= h) return; const i = (y * w + xx) * 4; d[i] = col[0]; d[i + 1] = col[1]; d[i + 2] = col[2]; d[i + 3] = 255; };
    for (let y = 0; y < 14; y++) for (let x = 0; x < w; x++) {                              // an envelope: an ellipse, lit from above
      const u = (x - 25) / 25.4, v = (y - 6.5) / 6.8;
      if (u * u + v * v > 1) continue;
      const k = .55 + .45 * smooth(13, 0, y);
      put(x, y, [Math.round(196 * k + 30), Math.round(204 * k + 30), Math.round(214 * k + 30)]);
    }
    for (let i = 0; i < 6; i++) { put(46 + i, 1 + i, [150, 158, 172]); put(46 + i, 12 - i, [140, 148, 162]); put(48 + (i >> 1), 6, [150, 158, 172]); }   // tail fins
    for (let x = 22; x < 31; x++) for (let y = 14; y < 17; y++) put(x, y, [62, 68, 82]);                                                   // the gondola
    put(26, 13, [120, 126, 140]); put(27, 13, [120, 126, 140]);
    for (let x = 12; x < 40; x++) { put(x, 4, [26, 30, 42]); put(x, 10, [26, 30, 42]); }                                                  // the billboard's frame
    for (let y = 5; y < 10; y++) { put(12, y, [26, 30, 42]); put(39, y, [26, 30, 42]); for (let x = 13; x < 39; x++) put(x, y, [16, 20, 36]); }
    cx.putImageData(img, 0, 0);
    const pixels = [];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const i = (y * w + x) * 4; if (d[i + 3]) pixels.push([x, y, null, 'rgb(' + d[i] + ',' + d[i + 1] + ',' + d[i + 2] + ')']); }
    c = { canvas: cv, w, h, pixels, bx: flip ? w - 39 : 13, by: 5, bw: 26, bh: 5 };
    s.sprites.set(key, c);
    return c;
  }
  const glowSprite = (s, colour, w, h) => {
    const key = 'glow' + colour.join(',') + w + 'x' + h;
    let c = s.sprites.get(key);
    if (c) return c;
    const cv = s.mk(w, h), cx = cv.getContext('2d');
    const grad = cx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    grad.addColorStop(0, 'rgba(' + colour.join(',') + ',.55)'); grad.addColorStop(1, 'rgba(' + colour.join(',') + ',0)');
    cx.fillStyle = grad; cx.save(); cx.translate(0, h / 2); cx.scale(1, h / w); cx.translate(0, -w / 2); cx.fillRect(0, 0, w, w); cx.restore();
    c = { canvas: cv, w, h };
    s.sprites.set(key, c);
    return c;
  };

  /* ------------------------------------------------------------------------------------------------------------------------------- building the scene */
  function drawFrame(s, ctx, name, x, y) { const f = s.data.frames[name]; if (f) ctx.drawImage(s.atlas, f[0], f[1], f[2], f[3], x, y, f[2], f[3]); }
  const unprojWorld = (s, x, y) => { const p = s.data.proj, u = (x - p.ox) / p.hw, v = (y - p.oy) / p.hh; return [(u + v) / 2, (v - u) / 2]; };
  const projWorld = (s, gx, gy, z) => { const p = s.data.proj; return [p.ox + (gx - gy) * p.hw, p.oy + (gx + gy) * p.hh - (z || 0)]; };

  function buildScene(api, dbg) {
    const data = api.json, atlas = api.atlas;
    if (!data || !data.frames || !atlas || !data.world || !data.proj || !data.towers || !data.frames.idmap) throw new Error('the atlas of ' + NAME + ' is incomplete');
    const W = data.world[0], H = data.world[1], rnd = api.random;
    const mk = (w, h) => { const c = global.document.createElement('canvas'); c.width = w; c.height = h; return c; };
    const s = { data, atlas, W, H, mk, rnd, sprites: new Map(), dbg: dbg || {}, clock: 0, cam: [12, 12], camPhase: rnd() * 6.28, dayAt: -1e9, day: null, key: '',
      readingObj: undefined, readingSeen: 0, pokes: [], weather: 'unknown', rainAmount: 0, fogAmount: 0, cloudAmount: .35, quality: 1, cap: 1, drawMs: 0, govAt: 0, calm: 0 };
    const place = data.place || { lat: 41.39, lon: 2.17 };
    s.place = place;
    s.base = mk(W, H); s.baseCtx = s.base.getContext('2d');
    s.sky = mk(W, data.skyRows || 80); s.skyCtx = s.sky.getContext('2d');
    // the id picture: which building owns each pixel
    const f = data.frames.idmap, idc = mk(f[2], f[3]), idx = idc.getContext('2d');
    idx.drawImage(atlas, f[0], f[1], f[2], f[3], 0, 0, f[2], f[3]);
    const px = idx.getImageData(0, 0, f[2], f[3]).data;
    s.ids = new Uint16Array(f[2] * f[3]);
    for (let i = 0; i < s.ids.length; i++) s.ids[i] = px[i * 4] | (px[i * 4 + 1] << 8);
    s.boxes = data.boxes || [];
    s.marketCover = bakeMarketCover(s);
    // the three data buildings: a small picture each, redrawn only when a reading changes
    s.towers = {};
    for (const name of ['codex', 'claude', 'small']) {
      const t = data.towers[name];
      if (!t) continue;
      const box = t.box, c = mk(box[2] - box[0] + 1, box[3] - box[1] + 1);
      s.towers[name] = { t, canvas: c, ctx: c.getContext('2d'), ox: box[0], oy: box[1], sig: '' };
    }
    // traffic, people, boats, the train, the sky's visitors
    s.traffic = makeTraffic((data.lanes || []).map((l) => Object.assign({}, l)), rnd);
    s.traffic.lanes.forEach(entry => { entry.pickup = nearestShelter(entry.lane, entry.length * .5, data.living && data.living.shelters); });
    s.peds = [];
    for (const walk of data.walks || []) {
      const len = Math.hypot(walk.b[0] - walk.a[0], walk.b[1] - walk.a[1]);
      const n = walk.axis === 'p' ? (rnd() < .6 ? 1 : 0) : clamp(Math.round(len / 12), 1, 2);
      for (let i = 0; i < n && s.peds.length < 52; i++) s.peds.push({ walk, len, s: rnd() * len, dir: rnd() < .5 ? 1 : -1, speed: .22 + rnd() * .2, colour: PEOPLE[Math.floor(rnd() * PEOPLE.length)] });
    }
    const shelters = data.living && data.living.shelters;
    s.peds.forEach((p, i) => { if (i % 3 !== 0) p.shelter = nearestShelter(p.walk, p.s, shelters); });
    s.boats = [];
    const lanes = (data.boats || []).slice();
    for (let i = lanes.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [lanes[i], lanes[j]] = [lanes[j], lanes[i]]; }
    let ferryPlaced = false;
    for (const lane of lanes.slice(0, 7)) {
      const len = Math.hypot(lane.b[0] - lane.a[0], lane.b[1] - lane.a[1]);
      let kind = lane.kinds[Math.floor(rnd() * lane.kinds.length)];
      if (!ferryPlaced && lane.kinds.includes('f') && data.living && data.living.ferry_dock && Math.abs(lane.a[1] - data.living.ferry_dock[1]) < .3) { kind = 'f'; ferryPlaced = true; }
      s.boats.push({ lane, len, kind, s: rnd() * len, speed: (kind === 'f' ? .55 : kind === 't' ? .45 : .4) + rnd() * .2, wait: 0, wake: [], next: 0 });
    }
    s.train = { x: 0, dir: 1, speed: 3.2, v: 0, wait: 0, cars: 5, on: false };
    if (data.rail) {
      const station = data.living && data.living.station;
      s.train.x = finite(station) ? Math.max(data.rail.a[0], station - 10) : data.rail.a[0] + (data.rail.b[0] - data.rail.a[0]) * .3;
      s.train.on = true;
    }
    s.heli = { active: true, wait: 0, x: 90, y: 44, dir: 1, speed: 15, dip: 0, bob: rnd() * 6 };
    s.blimp = { active: false, wait: 20 + rnd() * 30, x: 0, y: 54, dir: 1, speed: 4.5, message: SCREEN_TEXT, text: textStrip(SCREEN_TEXT.repeat(2), mk, '#ffcf70'), textPixels: textPixels(SCREEN_TEXT.repeat(2)), scroll: 0 };
    s.vents = (data.vents || []).map((v) => ({ x: v[0], y: v[1], next: rnd() * 2 }));
    s.manholes = (data.manholes || []).map((v) => ({ x: v[0], y: v[1], next: rnd() * 3 }));
    s.steam = [];
    s.beacons = (data.beacons || []).map((b) => ({ x: b[0], y: b[1], period: 1.4 + rnd() * 1.1, phase: rnd() * 3 }));
    s.screens = (data.screens || []).map((sc) => ({ q: sc.q, c: sc.c, offset: rnd() * 6 }));
    s.fountains = (data.fountains || []).map((f2) => ({ x: f2[0], y: f2[1], phase: rnd(), clear: f2.length < 3 || Boolean(f2[2]) }));       // clear: no building near it, so its glow may be added to the picture
    s.clouds = Array.from({ length: 6 }, (_, i) => ({ n: i % 3, x: rnd() * (W + 80) - 40, y: 14 + rnd() * 26, speed: 1.4 + rnd() * 2.4 }));
    s.stars = Array.from({ length: 90 }, () => ({ x: rnd() * W, y: rnd() * 32, tw: rnd() * 6.28, big: rnd() < .12 }));
    s.starLayers = [0, 1, 2, 3].map((k) => {                                                  // the stars are four little pictures that twinkle together by groups: four calls, not a hundred
      const c = mk(W, 34), cx = c.getContext('2d');
      cx.fillStyle = '#ffffff';
      s.stars.forEach((st, i) => {
        if (i % 4 !== k) return;
        const x = Math.round(st.x), y = Math.round(st.y);
        cx.fillRect(x, y, 1, 1);
        if (st.big) { cx.globalAlpha = .5; cx.fillRect(x - 1, y, 3, 1); cx.fillRect(x, y - 1, 1, 3); cx.globalAlpha = 1; }
      });
      return { canvas: c, tw: s.stars[k].tw };
    });
    s.sparkles = [];
    const canal = data.canal || [66, 70];                                                      // the one canal: boats, glints and buoys live on it (under the dock, seen in picture mode)
    // The atlas draws the bridge roadway on the water plane (z = 0). Its
    // legacy quads were recorded at z = 3, three pixels too high: applying
    // those directly hid boats in open water above the bridge and let them
    // show through the real deck. Move the mask to the painted roadway.
    s.bridges = bridgeDeckQuads(data.bridges);
    const onCanal = (x, y) => { const [gx, gy] = unprojWorld(s, x, y), xi = Math.round(x), yi = Math.round(y); return xi >= 0 && xi < W && yi >= 0 && yi < H && gy >= canal[0] + .2 && gy <= canal[1] - .2 && !s.ids[yi * W + xi]; };
    for (let tries = 0; tries < 1500 && s.sparkles.length < 70; tries++) {
      const x = rnd() * W, y = 240 + rnd() * (H - 250);
      if (onCanal(x, y)) s.sparkles.push({ x: Math.round(x), y: Math.round(y), phase: rnd() * 6.28, rate: 1.1 + rnd() * 1.6 });
    }
    s.rain = Array.from({ length: 80 }, () => ({ x: rnd() * (W + 40), y: rnd() * H, v: 80 + rnd() * 60 }));
    s.fog = [128, 168, 112].map((width, i) => {
      const c = mk(width, 58), cx = c.getContext('2d');
      for (let k = 0; k < 9; k++) {
        const x = width * (.23 + rnd() * .54), y = 18 + rnd() * 22;
        const rx = Math.min(width * (.16 + rnd() * .18), x - 2, width - x - 2), ry = Math.min(8 + rnd() * 8, y - 2, 56 - y);
        const gradient = cx.createRadialGradient(0, 0, 0, 0, 0, 1);
        gradient.addColorStop(0, 'rgba(176,194,216,.20)');
        gradient.addColorStop(.5, 'rgba(176,194,216,.11)');
        gradient.addColorStop(1, 'rgba(176,194,216,0)');
        cx.save(); cx.translate(x, y); cx.scale(rx, ry); cx.fillStyle = gradient;
        cx.beginPath(); cx.arc(0, 0, 1, 0, Math.PI * 2); cx.fill(); cx.restore();
      }
      return {canvas: c, y: 108 + i * 60, speed: 2.7, x: i === 0 ? W * .22 : -width, active: i === 0, dir: 1};
    });
    s.fogLast = 0; s.fogWait = 0;
    // A pair of very soft, seamless cloud shadows passes over the city.
    // They are prepared once, not redrawn pixel by pixel every frame.
    s.cloudShadows = [0, 1].map((layer) => {
      const c = mk(W, H), cx = c.getContext('2d');
      for (let k = 0; k < 7; k++) {
        const x = rnd() * W, y = 105 + rnd() * (H - 140), rx = 38 + rnd() * 44, ry = 12 + rnd() * 18;
        cx.fillStyle = 'rgba(9,18,35,.022)';
        for (let j = 0; j < 4; j++) for (const shift of [-W, 0, W]) {
          cx.beginPath(); cx.ellipse(x + shift, y, rx * (1 - j * .16), ry * (1 - j * .16), 0, 0, 6.3); cx.fill();
        }
      }
      return {canvas: c, x: rnd() * W, speed: 1.0 + layer * .55};
    });
    s.birds = { active: false, wait: 8 + rnd() * 20, x: 0, y: 26, dir: 1, speed: 9, flock: Array.from({ length: 5 }, (_, i) => ({ dx: -i * 5 - (i % 2) * 3, dy: (i % 3) * 3 - 3, ph: rnd() * 6.28 })) };
    s.pigeons = {active:false, wait:10 + rnd() * 12, u:0, dir:1, duration:7};
    s.courier = {active:false, wait:30 + rnd() * 25, u:0, dir:1, duration:9};
    s.life = lifePhase(0); s.story = {started: null, seen: 0}; s.storyState = {phase: 'waiting', time: 0}; s.nextWindow = 8 + rnd() * 8;
    s.scores = [scorePicture(false, mk), scorePicture(true, mk)];
    s.buoys = [];
    for (let tries = 0; tries < 800 && s.buoys.length < 4; tries++) {                         // a few blinking buoys in the canal
      const x = 12 + rnd() * (W - 24), y = 250 + rnd() * (H - 270);
      if (onCanal(x, y)) s.buoys.push({ x: Math.round(x), y: Math.round(y), red: s.buoys.length % 2 === 0, period: 2.2 + rnd() * 1.4, phase: rnd() * 3 });
    }
    return s;
  }

  /* -------------------------------------------------------------------------------------------------------------------------- stepping (logic, 30 Hz) */
  const nowMs = (s) => (s.dbg && typeof s.dbg.now === 'function' ? s.dbg.now() : s.dbg && finite(s.dbg.now) ? s.dbg.now : Date.now());
  function safely(s, name, fn) {
    if (s.off && s.off[name]) return;
    try { fn(); } catch (e) { (s.off = s.off || {})[name] = String(e && e.message || e); }
  }
  function laneAt(lane, along) {
    const dx = lane.b[0] - lane.a[0], dy = lane.b[1] - lane.a[1], len = Math.hypot(dx, dy) || 1;
    return [lane.a[0] + dx / len * along, lane.a[1] + dy / len * along];
  }
  function sparkleColour(d) {
    const w = d.weights;
    return mixRgb(mixRgb([255, 255, 255], [255, 224, 176], w.gold), mixRgb([214, 196, 226], [200, 216, 255], w.night / Math.max(1e-6, w.blue + w.night)), w.blue + w.night);
  }

  /** The scene also watches its own drawing time: a slow frame lowers small
   *  things one notch; a long spell of fast ones brings them back. */
  function governor(s, t) {
    if (t < 6 || t - s.govAt < 2) return;
    s.govAt = t;
    if (s.drawMs > 14 && s.cap > 0) { s.cap = s.cap > .7 ? .6 : s.cap > .4 ? .3 : 0; s.calm = 0; }
    else if (s.drawMs < 5 && s.cap < 1) { s.calm += 2; if (s.calm >= 40) { s.cap = s.cap < .5 ? .6 : 1; s.calm = 0; } }
    else s.calm = 0;
  }

  function stepScene(s, api, dt) {
    s.clock += dt;
    const t = s.clock, rnd = s.rnd;
    governor(s, t);
    s.quality = Math.min(api.tier === 'high' ? 1 : api.tier === 'medium' ? .6 : api.tier === 'light' ? .3 : 0, s.cap);
    s.cam = s.dbg.cam || cameraAt(t, s.camPhase, s.data.margin);
    if (t - s.dayAt >= 1) {
      s.dayAt = t;
      s.day = dayState(nowMs(s), s.place);
      s.weather = s.dbg.weather || observedWeather(typeof api.weather === 'function' ? api.weather() : null);
    }
    const d = s.day;
    s.life = lifePhase(finite(s.dbg.lifeTime) ? s.dbg.lifeTime : t);
    // the readings: a new object from the page is a fresh reading; one that stops coming goes unknown after STALE_MS
    const readings = api.readings();
    if (readings !== s.readingObj) { s.readingObj = readings; s.readingSeen = Date.now(); }
    const age = s.dbg.noStale ? 0 : Date.now() - s.readingSeen;
    s.data_ = dataState(readings, nowMs(s), age);
    const bridge = s.data.living && s.data.living.bridge_grid && s.data.living.bridge_grid[0];
    safely(s, 'traffic', () => stepTraffic(s.traffic, dt, t, rnd, bridge ? {gx: bridge[0], y0: bridge[1], y1: bridge[2], closed: s.life.bridgeClosed} : null));
    safely(s, 'people', () => {
      const wet = s.weather === 'rain' || s.weather === 'storm';
      for (const p of s.peds) stepPedestrian(p, dt, wet);
    });
    safely(s, 'boats', () => stepBoats(s, dt));
    safely(s, 'train', () => stepTrain(s, dt));
    const route = s.data.living && s.data.living.fan_route;
    if (!finite(s.dbg.lifeTime) && routeLength(route) > 0) {
      if (s.story.started === null && (s.train.arrivals || 0) > s.story.seen) { s.story.started = t; s.story.seen = s.train.arrivals; }
      s.storyState = linkedStory(s.story.started, t, route);
      if (s.storyState.phase === 'done') { s.story.started = null; s.story.seen = s.train.arrivals || 0; s.storyState = {phase: 'waiting', time: 0}; }
      s.life.match = s.storyState.phase === 'match';
      s.life.matchTime = s.life.match ? s.storyState.time : null;
      s.life.goal = s.life.match && s.storyState.time >= 45 && s.storyState.time < 50;
      s.life.fireworks = s.storyState.phase === 'fireworks';
      s.life.fireTime = s.life.fireworks ? s.storyState.time : null;
      s.life.parade = s.storyState.phase === 'parade';
      s.life.paradeTime = s.life.parade ? s.storyState.time : null;
    }
    safely(s, 'sky', () => stepSky(s, dt, d));
    safely(s, 'steam', () => stepSteam(s, dt, d));
    const rainTarget = s.weather === 'storm' ? 1 : s.weather === 'rain' ? .75 : s.weather === 'snow' ? .65 : 0;
    const fogTarget = s.weather === 'fog' ? .55 : .04;
    const cloudTarget = ({ clear: .18, partly: .52, cloud: .95, fog: .85, rain: .9, snow: .88, storm: 1, unknown: .30 })[s.weather] || .3;
    s.rainAmount += clamp(rainTarget - s.rainAmount, -dt / 20, dt / 20);
    s.fogAmount += clamp(fogTarget - s.fogAmount, -dt / 20, dt / 20);
    s.cloudAmount += clamp(cloudTarget - s.cloudAmount, -dt / 30, dt / 30);
    if (s.rainAmount > .02) for (const r of s.rain) { const v = r.v * (s.weather === 'snow' ? .22 : 1); r.y += v * dt; r.x -= v * dt * .22; if (r.y > SIZE[1] + 4) { r.y = -4 - rnd() * 40; r.x = rnd() * (SIZE[0] + 60); } if (r.x < -4) r.x += SIZE[0] + 60; }
    stepFog(s, dt);
    for (const c of s.cloudShadows) c.x = (c.x + c.speed * dt) % s.W;
    if (s.pokes.length) s.pokes = s.pokes.filter((p) => t - p.t0 - p.delay < 8);
    s.nextWindow -= dt;
    if (s.nextWindow <= 0 && s.data.poke && s.data.poke.length) {
      s.nextWindow = 9 + rnd() * 18;
      const w = s.data.poke[Math.floor(rnd() * s.data.poke.length)];
      s.pokes.push({x: w[0], y: w[1], w: w[2], h: w[3], t0: t, delay: 0});
    }
  }
  function stepBoats(s, dt) {
    const rnd = s.rnd;
    for (const b of s.boats) {
      for (const w of b.wake) w.age += dt;
      while (b.wake.length && b.wake[0].age > 3.2) b.wake.shift();
      if (b.wait > 0) { b.wait -= dt; continue; }
      if (!finite(b.v)) b.v = b.speed;
      const dock = s.data.living && s.data.living.ferry_dock;
      let remaining = null, target = b.speed;
      if (b.kind === 'f' && dock && !b.docked && Math.abs(b.lane.a[1] - dock[1]) < .3) {
        const ux = (b.lane.b[0] - b.lane.a[0]) / b.len, along = (dock[0] - b.lane.a[0]) / ux;
        if (finite(along) && along >= 0 && along <= b.len && along >= b.s) {
          remaining = along - b.s;
          target = Math.min(target, Math.sqrt(2 * .3 * remaining));
        }
      }
      b.v += clamp(target - b.v, -.3 * dt, .16 * dt);
      const advance = b.v * dt;
      if (remaining !== null && remaining <= Math.max(.015, advance)) { b.s += remaining; b.v = 0; b.docked = true; b.wait = 6; }
      else b.s += advance;
      const [gx, gy] = laneAt(b.lane, b.s), [X, Y] = projWorld(s, gx, gy, 0);
      b.next -= dt;
      if (b.v > .12 && b.next <= 0 && s.quality > .3) { b.next = .28; b.wake.push({ x: X, y: Y + 1, age: 0 }); }
      if (b.s > b.len + 3) { b.s = -3 - rnd() * 4; b.v = 0; b.wait = 4 + rnd() * 20; b.docked = false; b.wake.length = 0; }
    }
  }
  function stepTrain(s, dt) {
    const r = s.data.rail, tr = s.train;
    if (!r) return;
    if (tr.dwell > 0) { tr.dwell -= dt; return; }
    const length = tr.cars * 1.7;
    if (!tr.on) {
      tr.wait -= dt;
      if (s.life && s.life.t < 2 && tr.wait > 1) tr.wait = 1; // the next match day begins with an arriving train, never by teleporting one already on the line
      if (tr.wait <= 0) { tr.on = true; tr.dir = -tr.dir; tr.x = tr.dir > 0 ? r.a[0] - 1 : r.b[0] + 1 + length; tr.v = 0; tr.stationDone = false; }
      return;
    }
    const station = s.data.living && s.data.living.station;
    const remaining = finite(station) && !tr.stationDone ? tr.dir * (station - tr.x) : -1;
    const target = remaining >= 0 ? Math.min(tr.speed, Math.sqrt(2 * .6 * remaining)) : tr.speed;
    tr.v += clamp(target - tr.v, -.6 * dt, .35 * dt);
    const advance = tr.v * dt;
    if (remaining >= 0 && remaining <= Math.max(.015, advance)) { tr.x = station; tr.v = 0; tr.dwell = 5; tr.stationDone = true; tr.arrivals = (tr.arrivals || 0) + 1; }
    else tr.x += tr.dir * advance;
    if ((tr.dir > 0 && tr.x - length > r.b[0] + 2) || (tr.dir < 0 && tr.x < r.a[0] - 2)) { tr.on = false; tr.wait = 35 + s.rnd() * 55; }
  }
  function stepSky(s, dt, d) {
    const rnd = s.rnd, W = s.W;
    for (const c of s.clouds) { c.x += c.speed * dt; if (c.x > W + 40) { c.x = -80; c.y = 14 + rnd() * 26; c.n = Math.floor(rnd() * 3); } }
    const h = s.heli, b = s.blimp;
    if (!h.active) {
      h.wait -= dt;
      if (h.wait <= 0) { h.active = true; h.dir = rnd() < .5 ? 1 : -1; h.x = h.dir > 0 ? -26 : W + 26; h.y = h.dir > 0 ? 20 : 20 + (W + 52) * .18; h.speed = 12 + rnd() * 5; }
    } else {
      h.x += h.dir * h.speed * dt; h.y += h.dir * h.speed * dt * .18; h.bob += dt; h.dip = Math.max(0, h.dip - dt / 2.8);
      if ((h.dir > 0 && h.x > W + 28) || (h.dir < 0 && h.x < -28)) { h.active = false; h.wait = 26 + rnd() * 50; }
    }
    const f = s.birds;
    if (!f.active) { f.wait -= dt; if (f.wait <= 0 && d.dusk < .5) { f.active = true; f.dir = rnd() < .5 ? 1 : -1; f.x = f.dir > 0 ? -30 : W + 30; f.y = 20 + rnd() * 26; f.speed = 8 + rnd() * 5; } else if (f.wait <= 0) f.wait = 10; }
    else { f.x += f.dir * f.speed * dt; if ((f.dir > 0 && f.x > W + 40) || (f.dir < 0 && f.x < -40)) { f.active = false; f.wait = 25 + rnd() * 55; } }
    const pigeons = s.pigeons;
    if (!pigeons.active) {
      pigeons.wait -= dt;
      if (pigeons.wait <= 0) { pigeons.active = true; pigeons.u = 0; pigeons.dir = rnd() < .5 ? 1 : -1; pigeons.duration = 6.5 + rnd() * 2; }
    } else {
      pigeons.u += dt / pigeons.duration;
      if (pigeons.u > 1.3) { pigeons.active = false; pigeons.wait = 55 + rnd() * 85; }
    }
    const hero = s.courier;
    if (!hero.active) {
      hero.wait -= dt;
      if (hero.wait <= 0) { hero.active = true; hero.u = 0; hero.dir = rnd() < .5 ? 1 : -1; hero.duration = 8 + rnd() * 2; }
    } else {
      hero.u += dt / hero.duration;
      if (hero.u >= 1) { hero.active = false; hero.wait = 110 + rnd() * 110; }
    }
    if (!b.active) {
      b.wait -= dt;
      if (b.wait <= 0) { b.active = true; b.dir = rnd() < .5 ? 1 : -1; b.x = b.dir > 0 ? -60 : W + 10; b.y = 40 + rnd() * 14; b.speed = 4 + rnd() * 2;
        b.message = AIR_MESSAGES[Math.floor(rnd() * AIR_MESSAGES.length)]; b.text = textStrip(b.message.repeat(2), s.mk, '#ffcf70'); b.textPixels = textPixels(b.message.repeat(2)); b.scroll = 0; }
    } else {
      b.x += b.dir * b.speed * dt; b.scroll += 9 * dt;
      if ((b.dir > 0 && b.x > W + 12) || (b.dir < 0 && b.x < -64)) { b.active = false; b.wait = 70 + rnd() * 90; }
    }
  }
  function stepSteam(s, dt, d) {
    if (s.quality < .3) { s.steam.length = 0; return; }
    const rnd = s.rnd, limit = Math.round(90 * s.quality);
    const emit = (src, rate) => {
      src.next -= dt;
      if (src.next <= 0 && s.steam.length < limit) { src.next = rate * (.7 + rnd() * .6); s.steam.push({ x: src.x, y: src.y, vx: (rnd() - .35) * 1.6, vy: -(3.2 + rnd() * 2.4), age: 0, life: 2.6 + rnd() * 1.6, size: 1 + Math.floor(rnd() * 2) }); }
    };
    const stride = s.quality > .8 ? 1 : 2;
    for (let i = 0; i < s.vents.length; i += stride) emit(s.vents[i], 1.3);
    for (let i = 0; i < s.manholes.length; i += stride) emit(s.manholes[i], 0.9);
    for (const p of s.steam) { p.age += dt; p.x += p.vx * dt; p.y += p.vy * dt; p.vy *= .985; p.vx += 0.4 * dt; }
    s.steam = s.steam.filter((p) => p.age < p.life);
  }

  /* ------------------------------------------------------------------------------------------------------------------------------------ drawing */
  function compose(s, d) {
    if (s.composedFor === d) return;                                                   // the day state is renewed once a second: nothing to do between
    s.composedFor = d;
    const q = 32, w = {};
    for (const p of PHASES) w[p] = Math.round(d.weights[p] * q) / q;
    const alphas = batchAlphas(d.lights, s.data.buckets || 10).map((a) => Math.round(a * 16) / 16);
    const morning = Math.round(d.rising * 16) / 16;
    const twilight = Math.round((w.gold * .18 + w.blue * .10) * 64) / 64;
    const key = PHASES.map((p) => w[p]).join(',') + '|' + alphas.join(',') + '|' + twilight + ':' + (twilight ? morning : 0);
    if (key === s.key) return;
    s.key = key;
    const active = PHASES.filter((p) => w[p] > 0).sort((a, b) => w[b] - w[a]);
    const A = active[0] || 'night', B = active[1];
    const tB = B ? w[B] / (w[A] + w[B]) : 0;
    s.phaseA = A; s.phaseB = B; s.phaseT = tB;
    const bc = s.baseCtx, sc = s.skyCtx;
    for (const [ctx, prefix, rows, withLights] of [[bc, 'city-', s.H, true], [sc, 'sky-', s.sky.height, false]]) {
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1; ctx.clearRect(0, 0, s.W, rows);
      drawFrame(s, ctx, prefix + A, 0, 0);
      if (B) { ctx.globalAlpha = tB; drawFrame(s, ctx, prefix + B, 0, 0); ctx.globalAlpha = 1; }
      if (twilight > 0) {
        const colour = mixRgb([255, 143, 84], [230, 162, 192], morning);
        ctx.globalCompositeOperation = 'source-atop'; ctx.globalAlpha = twilight;
        ctx.fillStyle = 'rgb(' + colour.join(',') + ')'; ctx.fillRect(0, 0, s.W, rows);
        ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
      }
      if (withLights) {
        ctx.globalCompositeOperation = 'lighter';
        alphas.forEach((a, k) => { if (a > 0) { ctx.globalAlpha = a; drawFrame(s, ctx, 'lights-' + k, 0, 0); } });
        ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
      }
    }
  }

  /** The pixels of a sprite that are not hidden, one call for each run of neighbours of the same colour in a row (the pixels are in reading order). */
  function drawVisible(g, px, mask, ox, oy) {
    let last = '', i = 0;
    while (i < px.length) {
      if (mask[i]) { i++; continue; }
      const p = px[i];
      let run = 1;
      while (i + run < px.length && !mask[i + run] && px[i + run][3] === p[3] && px[i + run][1] === p[1] && px[i + run][0] === p[0] + run) run++;
      if (p[3] !== last) { g.fillStyle = p[3]; last = p[3]; }
      g.fillRect(ox + p[0], oy + p[1], run, 1);
      i += run;
    }
  }
  /** Draw a sprite at a ground point, hiding the pixels that a nearer building covers (the id picture says which building owns a pixel). */
  function blit(s, g, spr, gx, gy, z, ignoreRail, alpha, extra, ignoreId, spriteDepth) {
    const [X, Y] = projWorld(s, gx, gy, z);
    const ox = Math.round(X) - spr.ax, oy = Math.round(Y) - spr.ay, ground = Y + z, W = s.W;
    const px = spr.pixels, ids = s.ids;
    let open = extra === undefined;                                                      // most vehicles are on open street: not one of their pixels is a building's
    for (let i = 0; open && i < px.length; i++) {
      const x = ox + px[i][0], y = oy + px[i][1];
      if (x >= 0 && y >= 0 && x < W && ids[y * W + x]) open = false;
    }
    if (open) {
      if (alpha !== undefined) g.globalAlpha = alpha;
      g.drawImage(spr.canvas, ox, oy);
      if (alpha !== undefined) g.globalAlpha = 1;
      return true;
    }
    let hidden = 0;
    const mask = spr.mask || (spr.mask = new Uint8Array(px.length));
    for (let i = 0; i < px.length; i++) {
      const p = px[i];
      // Wide aircraft span several sight lines: use the world position of each pixel.
      const offset = spriteDepth ? (ox + p[0] + .5 - X) / (2 * s.data.proj.hw) : 0;
      const hide = isHidden(ids, W, s.boxes, ox + p[0], oy + p[1], gx + offset, gy - offset, Math.max(0, ground - (oy + p[1] + .5)), ignoreRail, ignoreId) || (extra !== undefined && extra(ox + p[0], oy + p[1]));
      mask[i] = hide ? 1 : 0; if (hide) hidden++;
    }
    if (hidden === px.length) return false;
    if (alpha !== undefined) g.globalAlpha = alpha;
    if (hidden === 0) g.drawImage(spr.canvas, ox, oy);
    else drawVisible(g, px, mask, ox, oy);
    if (alpha !== undefined) g.globalAlpha = 1;
    return true;
  }
  /** A test for the pixels of a boat that a bridge's deck is in front of (the canal's bridges are not in the id picture: they are ground). */
  function underBridge(s) {
    if (!s.bridges.length) return undefined;
    return (x, y) => { for (let i = 0; i < s.bridges.length; i++) if (!(i === 0 && s.life && s.life.bridge > .01) && inQuad(s.bridges[i], x + .5, y + .5)) return true; return false; };
  }
  const seenAt = (s, x, y) => { const xi = Math.round(x), yi = Math.round(y); return xi >= 0 && yi >= 0 && xi < s.W && yi < s.H && s.ids[yi * s.W + xi] === 0; };

  function polygon(g, points, colour) {
    g.fillStyle = colour; g.beginPath(); g.moveTo(points[0][0], points[0][1]);
    for (let i = 1; i < points.length; i++) g.lineTo(points[i][0], points[i][1]);
    g.closePath(); g.fill();
  }
  function bakeMarketCover(s) {
    const stalls = s.data.living && s.data.living.stalls;
    if (!Array.isArray(stalls) || !stalls.length) return null;
    const canvas = s.mk(s.W, s.H), g = canvas.getContext('2d');
    for (const [gx, gy, axis] of stalls) {
      const a = axis === 'x' ? [.46, .2] : [.2, .46], [x, y] = projWorld(s, gx, gy, 0);
      // Shutter and tied-down canvas sit on the same stall footprint as the
      // daytime awning, so a closing stall does not become a floating patch.
      g.fillStyle = '#596460'; g.fillRect(Math.round(x) - 2, Math.round(y) - 3, 4, 3);
      polygon(g, [projWorld(s, gx-a[0]-.08, gy-a[1]-.08, 3.1), projWorld(s, gx+a[0]+.08, gy-a[1]-.08, 3.1),
        projWorld(s, gx+a[0]+.08, gy+a[1]+.08, 3.1), projWorld(s, gx-a[0]-.08, gy+a[1]+.08, 3.1)], '#89908a');
    }
    return canvas;
  }
  function drawMarketCover(s, g) {
    if (!s.marketCover) return;
    const closed = 1 - marketOpen(nowMs(s));
    if (closed <= .01) return;
    g.globalAlpha = closed; g.drawImage(s.marketCover, 0, 0); g.globalAlpha = 1;
  }
  function drawMovingBridge(s, g, d, foreground) {
    const grids = s.data.living && s.data.living.bridge_grid, amount = s.life.bridge;
    if (!grids || !grids.length || amount <= .01) return;
    const [x, a, b] = grids[0], mid = (a + b) / 2, p = (gx, gy, z) => projWorld(s, gx, gy, z);
    if (!foreground) {
      const water = rgb(mixRgb([29, 95, 125], [23, 49, 78], d.dusk));
      polygon(g, [p(x, a, 0), p(x + 1, a, 0), p(x + 1, b, 0), p(x, b, 0)], water);
      return;
    }
    const lift = amount * 12;
    for (const [outer, inner] of [[a, mid], [b, mid]]) {
      const left0 = p(x, outer, 3), right0 = p(x + 1, outer, 3), right1 = p(x + 1, inner, 3 + lift), left1 = p(x, inner, 3 + lift);
      polygon(g, [left0, right0, right1, left1], '#565e65');
      g.strokeStyle = '#c9c6b8'; g.lineWidth = .6;
      g.beginPath(); g.moveTo(left0[0], left0[1]); g.lineTo(left1[0], left1[1]); g.lineTo(right1[0], right1[1]); g.lineTo(right0[0], right0[1]); g.stroke();
      const edge = p(x + .5, inner, 3 + lift); g.fillStyle = '#f1d99a'; g.fillRect(Math.round(edge[0]), Math.round(edge[1]), 1, 1);
    }
    const lamp = p(x + .5, a - .3, 1); g.fillStyle = '#f45b4a'; g.fillRect(Math.round(lamp[0]), Math.round(lamp[1]), 1, 1);
  }

  function drawCityLife(s, g, d, q) {
    const life = s.data.living;
    if (!life) return;
    const t = s.clock, state = s.life, manual = finite(s.matchStarted) ? t - s.matchStarted : -1;
    const playing = state.match || (manual >= 0 && manual < 70), goal = state.goal || (manual >= 54 && manual < 59);
    const field = life.stadiums && life.stadiums[0];
    if (field && playing) {
      const [x0, y0, x1, y1, z] = field.field;
      const [cx, cy] = projWorld(s, (x0 + x1) / 2, (y0 + y1) / 2, z);
      const autoScored = finite(state.matchTime) ? state.matchTime >= 50 : state.t >= 79 && state.t < 103;
      const score = autoScored || (manual >= 59 && manual < 70) ? 1 : 0;
      const bx0 = Math.round(cx) + 4, by0 = Math.round(cy) + 6;
      const clearBoard = [[bx0 - 1, by0 - 1], [bx0 + 7, by0 - 1], [bx0 - 1, by0 + 3], [bx0 + 7, by0 + 3]].every(([x, y]) => {
        if (x < 0 || y < 0 || x >= s.W || y >= s.H) return false;
        const id = s.ids[y * s.W + x]; return !id || id === field.id;
      });
      if (clearBoard) { g.fillStyle = '#131e27'; g.fillRect(bx0 - 1, by0 - 1, 9, 5); g.drawImage(s.scores[score], bx0, by0); }
      // Tiny players and ball stay in the actual pitch plane and are hidden by
      // anything drawn in front of the stadium; two teams wear different kits.
      for (let i = 0; i < 10; i++) {
        const u = clamp(.15 + (i % 5) * .17 + Math.sin(t * .48 + i * 2.2) * .07, .06, .94);
        const v = clamp((i < 5 ? .32 : .68) + Math.sin(t * .61 + i * 1.4) * .14, .08, .92);
        const [px, py] = projWorld(s, lerp(x0, x1, u), lerp(y0, y1, v), z);
        const x = Math.round(px), y = Math.round(py), id = s.ids[y * s.W + x];
        if (x < 0 || y < 0 || x >= s.W || y >= s.H || (id && id !== field.id)) continue;
        g.fillStyle = i < 5 ? '#ffe8d0' : '#67cfff'; g.fillRect(x, y - 1, 1, 2);
      }
      const goalTime = state.goal ? (finite(state.matchTime) ? state.matchTime - 45 : state.t - 73) : manual - 54;
      const ballU = goal ? lerp(.56, .96, clamp(goalTime / 4, 0, 1)) : .5 + Math.sin(t * .65) * .28;
      const [bx, by] = projWorld(s, lerp(x0, x1, ballU), lerp(y0, y1, .5 + Math.sin(t * .47) * .18), z);
      g.fillStyle = '#fffbea'; g.fillRect(Math.round(bx), Math.round(by), 1, 1);
    }
    if (q >= .3) {
      const localHour = new Date(nowMs(s)).getHours();
      if (localHour >= 8 && localHour < 20) for (const r of (life.markets || []).slice(0, 2)) {
        for (let i = 0; i < 3; i++) {
          const [px, py] = projWorld(s, lerp(r[0] + .4, r[2] - .4, .5 + .35 * Math.sin(t * .15 + i * 2)), lerp(r[1] + .4, r[3] - .4, .36 + i * .14), 0);
          if (seenAt(s, px, py - 1)) { g.fillStyle = ['#e9c8a6', '#95cfe6', '#f3c653'][i]; g.fillRect(Math.round(px), Math.round(py) - 1, 1, 2); }
        }
      }
      // A little open-air screening after dusk, or a concert on another cycle.
      const park = life.parks && life.parks[0];
      if (park && d.dusk > .5 && (state.t > 180 || state.t < 5)) {
        const [px, py] = projWorld(s, lerp(park[0], park[2], .48), lerp(park[1], park[3], .47), 0), x = Math.round(px), y = Math.round(py);
        if (seenAt(s, x, y - 3)) {
          const concert = state.t >= 180 && state.t < 205;
          g.fillStyle = '#27303b'; g.fillRect(x - 3, y - 6, 7, 5);
          g.fillStyle = concert ? (Math.sin(t * 1.5) > 0 ? '#d99acb' : '#8ecae6') : (Math.sin(t * .7) > 0 ? '#d5e9ef' : '#e9c99f'); g.fillRect(x - 2, y - 5, 5, 3);
          if (concert) { g.fillStyle = '#ffdb98'; g.fillRect(x, y - 4, 1, 2); }
          g.fillStyle = '#e5bf86'; for (let i = 0; i < 4; i++) g.fillRect(x - 3 + i * 2, y + 2 + (i % 2), 1, 1);
        }
      }
      if (park && d.dusk < .5) {
        const [px, py] = projWorld(s, lerp(park[0], park[2], .34), lerp(park[1], park[3], .44), 0), x = Math.round(px), y = Math.round(py);
        if (seenAt(s, x, y - 1)) {
          g.fillStyle = '#f0c296'; g.fillRect(x, y - 2, 1, 2); // a person and a kite, both tiny at city scale
          const kx = x + 4 + Math.round(Math.sin(t * .4) * 2), ky = y - 8 + Math.round(Math.sin(t * .6));
          if (seenAt(s, kx, ky)) { g.fillStyle = '#f4d36d'; g.fillRect(kx, ky, 2, 2); g.fillStyle = '#e8e1c9'; g.fillRect(x + 2, y - 4, 1, 1); }
        }
        const [catx, caty] = projWorld(s, lerp(park[0], park[2], .24 + .05 * Math.sin(t * .2)), lerp(park[1], park[3], .64), 0);
        if (seenAt(s, catx, caty)) { g.fillStyle = '#56483f'; g.fillRect(Math.round(catx), Math.round(caty), 2, 1); }
        if (s.weather !== 'rain' && s.weather !== 'storm') for (const [gx, gy] of (life.picnics || []).slice(0, 1)) {
          const [px, py] = projWorld(s, gx, gy, 0), x = Math.round(px), y = Math.round(py);
          if (!seenAt(s, x, y)) continue;
          polygon(g, [projWorld(s, gx-.38, gy-.24, .1), projWorld(s, gx+.38, gy-.24, .1), projWorld(s, gx+.38, gy+.24, .1), projWorld(s, gx-.38, gy+.24, .1)], '#e7d9c7');
          g.fillStyle = '#bd605c'; g.fillRect(x - 1, y, 1, 1); g.fillRect(x + 1, y, 1, 1);
          g.fillStyle = '#d8aa83'; g.fillRect(x - 2, y - 1, 1, 1); g.fillRect(x + 2, y - 1, 1, 1);
        }
      }
      if (state.parade && s.data.walks && s.data.walks.length) {
        const lane = s.data.walks[0], len = Math.hypot(lane.b[0] - lane.a[0], lane.b[1] - lane.a[1]), start = Math.max(0, len * .5 - 3);
        const paradeTime = finite(state.paradeTime) ? state.paradeTime : state.t - 119;
        g.globalAlpha = smooth(0, 1, paradeTime) * (1 - smooth(19, 20, paradeTime));
        for (let i = 0; i < 7; i++) {
          const pos = groupWalk(start, paradeTime, i, 1, len), [gx, gy] = laneAt(lane, pos), [x, y] = projWorld(s, gx, gy, 0);
          if (seenAt(s, x, y - 1)) {
            const px = Math.round(x), py = Math.round(y);
            g.fillStyle = ['#f8d272', '#ff8e91', '#9ccfff'][i % 3]; g.fillRect(px, py - 1, 1, 2);
            if (i === 1 || i === 4) { g.fillStyle = i === 1 ? '#ef7e76' : '#86c9ed'; g.fillRect(px + 1, py - 3, 2, 1); }
          }
        }
        g.globalAlpha = 1;
      }
      const route = life.fan_route, story = s.storyState;
      if (story && story.phase === 'fans' && routeLength(route) > 0) {
        const len = routeLength(route);
        for (let i = 0; i < 5; i++) {
          const distance = story.time * GROUP_WALK_SPEED - i * .18;
          if (distance < 0 || distance > len) continue;
          const [gx, gy] = routePoint(route, distance), [x, y] = projWorld(s, gx, gy, 0);
          if (seenAt(s, x, y - 1)) { g.fillStyle = i % 2 ? '#7ac8f0' : '#f3d5b2'; g.fillRect(Math.round(x), Math.round(y) - 1, 1, 2); }
        }
      }
    }
    if (field && (state.fireworks || (manual >= 70 && manual < 82))) {
      const [x0, y0, x1, y1] = field.field, [cx, cy] = projWorld(s, (x0 + x1) / 2, (y0 + y1) / 2, 12);
      const eventTime = state.fireworks ? (finite(state.fireTime) ? state.fireTime : state.t - 103) : manual - 70;
      for (let n = 0; n < 3; n++) {
        const u = ((eventTime + n * 1.3) % 4.2) / 4.2, x = cx - 40 + (n - 1) * 6, y = cy - 32 - n * 5;
        g.fillStyle = ['#ffe57d', '#f48d8c', '#95d7ff'][n];
        if (u < .3) { const px = Math.round(lerp(cx, x, u / .3)), py = Math.round(lerp(cy - 3, y, u / .3)); if (!airHidden(s, px, py)) g.fillRect(px, py, 1, 2); }
        else if (u < .8) {
          const radius = (u - .3) * 18; g.globalAlpha = clamp((.8 - u) * 4, 0, 1);
          for (let j = 0; j < 8; j++) { const px = Math.round(x + Math.cos(j * Math.PI / 4) * radius), py = Math.round(y + Math.sin(j * Math.PI / 4) * radius * .65); if (!airHidden(s, px, py)) g.fillRect(px, py, j % 2 ? 1 : 2, j % 2 ? 1 : 2); }
          g.globalAlpha = 1;
        }
      }
    }
  }

  function drawGround(s, g, d, q) {
    const t = s.clock, dusk = d.dusk;
    const data = s.data;
    if (q > .3) safely(s, 'sparkles', () => {
      g.fillStyle = rgb(sparkleColour(d));
      const strength = d.weights.night * .8 + d.weights.gold + d.weights.blue * .7 + d.weights.day * .5;
      for (const k of s.sparkles) { const v = Math.sin(t * k.rate + k.phase); if (v > .93 - strength * .06) g.fillRect(k.x, k.y, 1, 1); }
    });
    safely(s, 'wakes', () => {
      g.fillStyle = '#dfeaf2';
      for (const b of s.boats) for (const w of b.wake) {
        const a = clamp(1 - w.age / 3.2, 0, 1) * .55;
        if (a < .06 || !seenAt(s, w.x, w.y)) continue;
        g.globalAlpha = a; const spread = Math.floor(w.age * 1.6);
        g.fillRect(Math.round(w.x) - spread, Math.round(w.y), 1, 1); g.fillRect(Math.round(w.x) + spread, Math.round(w.y), 1, 1);
      }
      g.globalAlpha = 1;
    });
    safely(s, 'fountains', () => {
      g.fillStyle = '#e8f6ff';
      for (const f of s.fountains) {
        for (let i = 0; i < 5; i++) {
          const u = (t * .9 + f.phase + i / 5) % 1;
          const jx = Math.round(f.x + (i - 2) * .9 * u), jy = Math.round(f.y - 2 - 7 * Math.sin(Math.PI * u));
          if (!f.clear && !seenAt(s, jx, jy)) continue;                                  // a fountain beside a building: its spray never shows on the wall in front of it
          g.globalAlpha = .9 - u * .5;
          g.fillRect(jx, jy, 1, 1);
        }
      }
      g.globalAlpha = 1;
      if (dusk > .2) {
        const glow = glowSprite(s, [120, 210, 255], 15, 8);
        g.globalCompositeOperation = 'lighter'; g.globalAlpha = .5 * dusk;
        for (const f of s.fountains) if (f.clear) g.drawImage(glow.canvas, Math.round(f.x) - 7, Math.round(f.y) - 5);
        g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
      }
    });
    if (s.rainAmount > .04 && q >= .3) safely(s, 'wetStreets', () => {
      const poles = s.data.poles || [];
      for (let i = 0; i < poles.length; i += 2) {
        const p = poles[i], x = Math.round(p[0]), y = Math.round(p[1] + 4);
        if (!seenAt(s, x, y)) continue;
        const c = lightState(p[2], p[3] === 0 ? 'x' : 'y', t);
        g.fillStyle = c === 'g' ? '#88cba6' : c === 'y' ? '#e5c978' : '#e1958e';
        g.globalAlpha = s.rainAmount * (.18 + dusk * .35); g.fillRect(x, y, 1, 2);
      }
      g.globalAlpha = 1;
    });
    safely(s, 'vehicles', () => {
      const lit = dusk > .3 && q > .5;
      for (const entry of s.traffic.lanes) {
        const lane = entry.lane, axis = lane.axis, sign = lane.sign;
        for (const car of entry.cars) {
          if (car.s < -2 || car.s > entry.length + 2) continue;
          const gx = lane.a[0] + entry.ux * car.s, gy = lane.a[1] + entry.uy * car.s;
          const spr = vehicleSprite(s, car.kind, car.colour, axis, sign, lit);
          const fade = clamp((projWorld(s, gx, gy, 0)[1] - 40) / 90, .5, 1);                       // far streets are in the haze: their traffic is a little fainter
          blit(s, g, spr, gx, gy, 0, false, fade < 1 ? fade : undefined);
        }
      }
    });
    if (q > .3) safely(s, 'people', () => {
      const n = Math.round(s.peds.length * Math.min(1, q + .1));
      for (let i = 0; i < n; i++) {
        const p = s.peds[i], [gx, gy] = laneAt(p.walk, p.s), [X, Y] = projWorld(s, gx, gy, 0);
        const x = Math.round(X), y = Math.round(Y);
        if (!seenAt(s, x, y - 1)) continue;
        g.fillStyle = rgb(p.colour); g.fillRect(x, y - 2, 1, 2);
        if ((s.weather === 'rain' || s.weather === 'storm') && !p.sheltering && i % 3 === 0) { g.fillStyle = i % 2 ? '#b5c7d8' : '#d17970'; g.fillRect(x - 1, y - 3, 3, 1); }
      }
    });
    safely(s, 'boats', () => {
      for (const b of s.boats) {
        // A ferry waiting at the quay stays visible; only a vessel waiting
        // outside the map is hidden until it enters.
        if ((b.wait > 0 && !b.docked) || b.s < -2 || b.s > b.len + 2) continue;
        const dx = b.lane.b[0] - b.lane.a[0], dy = b.lane.b[1] - b.lane.a[1];
        const axis = Math.abs(dx) >= Math.abs(dy) ? 'x' : 'y', sign = (axis === 'x' ? dx : dy) >= 0 ? 1 : -1;
        const lit = dusk > .3, spr = boatSprite(s, b.kind, axis, sign, lit), [gx, gy] = laneAt(b.lane, b.s);
        if (blit(s, g, spr, gx, gy, 0, false, undefined, underBridge(s)) && lit && b.kind !== 's') {                // a ferry's lit windows shimmer in the water below it
          const [X, Y] = projWorld(s, gx, gy, 0);
          g.fillStyle = '#ffd890';
          for (let k = 0; k < 3; k++) { g.globalAlpha = .3 * dusk; g.fillRect(Math.round(X) - 2 + k * 2 + (Math.floor(t * 2 + k) % 2), Math.round(Y) + 3 + k * 2, 1, 1); }
          g.globalAlpha = 1;
        }
      }
      const dock = data.living && data.living.ferry_dock;
      const crossing = bridgeFerryX(s.life.t);
      if (dock && crossing !== null) {
        // A scheduled ferry approaches from beyond the left edge, passes the
        // raised bridge, and leaves beyond the right edge in one continuous trip.
        const gy = dock[1], spr = boatSprite(s, 'f', 'x', 1, dusk > .3);
        blit(s, g, spr, crossing, gy, 0, false, undefined, underBridge(s));
      }
    });
    safely(s, 'train', () => {
      const r = data.rail, tr = s.train;
      if (!r || !tr.on) return;
      const lit = dusk > .35;
      for (let i = 0; i < tr.cars; i++) {
        const gx = tr.x - tr.dir * i * 1.7, gy = r.a[1];
        const spr = trainSprite(s, i === 0, lit, tr.dir);
        blit(s, g, spr, gx, gy, r.z, true);
      }
    });
    if (q > .3) safely(s, 'poles', () => {
      for (const p of data.poles || []) {
        const c = lightState(p[2], p[3] === 0 ? 'x' : 'y', t);
        g.fillStyle = c === 'g' ? '#62f088' : c === 'y' ? '#ffd23c' : '#ff4a40'; g.fillRect(Math.round(p[0]), Math.round(p[1]), 1, 1);
      }
    });
  }

  function drawRoof(s, g, d, q) {
    const t = s.clock, dusk = d.dusk;
    safely(s, 'cranes', () => {
      for (const [i, c] of ((s.data.living && s.data.living.cranes) || []).entries()) {
        const u = .3 + .25 * (1 + Math.sin(t * .12 + i * 2)), x = Math.round(lerp(c.top[0], c.far[0], u)), top = Math.round(lerp(c.top[1], c.far[1], u));
        const length = Math.round(c.height * (.3 + .13 * (1 + Math.sin(t * .09 + i))));
        g.fillStyle = '#a1a29b';
        for (let dy = 0; dy < length; dy++) { const y = top + dy, id = x >= 0 && y >= 0 && x < s.W && y < s.H ? s.ids[y * s.W + x] : -1; if (id === 0 || id === c.id) g.fillRect(x, y, 1, 1); }
        const y = top + length, id = x >= 0 && y >= 0 && x < s.W && y < s.H ? s.ids[y * s.W + x] : -1;
        if (id === 0 || id === c.id) { g.fillStyle = '#e49350'; g.fillRect(x - 1, y, 2, 2); }
      }
    });
    safely(s, 'steam', () => {
      const tint = mixRgb([240, 242, 248], [150, 162, 196], dusk);
      g.fillStyle = rgb(tint);
      for (const p of s.steam) { const x = Math.round(p.x), y = Math.round(p.y); if (airHidden(s, x, y)) continue; g.globalAlpha = .34 * (1 - p.age / p.life) * (p.age < .4 ? p.age / .4 : 1); g.fillRect(x, y, p.size, p.size); }    // never over a data building
      g.globalAlpha = 1;
    });
    safely(s, 'beacons', () => {
      for (const b of s.beacons) {
        const on = ((t + b.phase) % b.period) < .32;
        if (!on) continue;
        g.fillStyle = '#ff4a4a'; g.fillRect(Math.round(b.x) - 1, Math.round(b.y) - 1, 2, 2);
        if (dusk > .2) { g.globalAlpha = .32 * dusk; g.fillStyle = '#ff7060'; g.fillRect(Math.round(b.x) - 2, Math.round(b.y) - 2, 4, 4); g.globalAlpha = 1; }
      }
    });
    if (q > .3) safely(s, 'screens', () => {
      const n = Math.round(s.screens.length * Math.min(1, q + .1));
      for (let i = 0; i < n; i++) {
        const sc = s.screens[i], k = ((t * .33 + sc.offset) % 1 + 1) % 1, c = sc.c;
        let col = c;
        if (k < .4) col = c; else if (k < .5) col = mixRgb(c, [250, 250, 255], (k - .4) / .1); else if (k < .9) col = mixRgb([c[1], c[2], c[0]], [250, 250, 255], .1); else col = mixRgb([c[1], c[2], c[0]], c, (k - .9) / .1);
        const quad = sc.q, x0 = Math.round(quad[0][0]), x1 = Math.round(quad[1][0]);
        g.fillStyle = rgb(col);
        for (let x = x0; x < x1; x++) {
          const u = (x + .5 - quad[0][0]) / ((quad[1][0] - quad[0][0]) || 1);
          const yb = quad[0][1] + (quad[1][1] - quad[0][1]) * u, yt = quad[3][1] + (quad[2][1] - quad[3][1]) * u;
          const top = Math.round(yt), bottom = Math.round(yb);
          if (bottom > top) g.fillRect(x, top, 1, bottom - top);
        }
      }
    });
  }

  function drawWeather(s, g, d, q) {
    safely(s, 'weatherClouds', () => {
      if (s.cloudAmount <= .38 || q < .3) return;
      const a = clamp((s.cloudAmount - .38) * .42, 0, .27), phase = s.phaseA || 'day';
      g.globalAlpha = a;
      for (const c of s.clouds.slice(0, 4)) drawFrame(s, g, 'cloud-' + c.n + '-' + phase, Math.round(c.x), Math.round(c.y));
      g.globalAlpha = 1;
    });
    safely(s, 'cloudShadows', () => {
      if (q < .3) return;
      g.globalAlpha = (.25 + s.cloudAmount * .6) * (1 - d.dusk * .4);
      for (const c of s.cloudShadows) {
        const x = Math.round(c.x);
        g.drawImage(c.canvas, x, 0); g.drawImage(c.canvas, x - s.W, 0);
      }
      g.globalAlpha = 1;
    });
    safely(s, 'fog', () => {
      if (s.fogAmount < .03 || q < .3) return;
      for (const f of s.fog) if (f.active) { g.globalAlpha = clamp(s.fogAmount, 0, 1); g.drawImage(f.canvas, Math.round(f.x), Math.round(f.y)); }
      g.globalAlpha = 1;
    });
    safely(s, 'rain', () => {
      if (s.rainAmount < .03) return;
      const n = Math.round(s.rain.length * s.rainAmount * Math.max(.25, q));
      g.fillStyle = s.weather === 'snow' ? '#f5f8ff' : '#c4d2f0'; g.globalAlpha = .6;
      for (let i = 0; i < n; i++) { const r = s.rain[i]; g.fillRect(Math.round(r.x + s.cam[0]), Math.round(r.y + s.cam[1]), 1, s.weather === 'snow' ? 1 : 3); }
      g.globalAlpha = 1;
    });
  }

  /** Things in the air are far away, out over the harbour: a building drawn on a pixel (the id picture) is in front of them, so they pass behind the skyline,
   *  behind the data buildings' crowns and signs, and never cover them. (A bridge is lower than they are.) */
  function airHidden(s, x, y) {
    if (x < 0 || y < 0 || x >= s.W || y >= s.H) return false;
    const id = s.ids[y * s.W + x];
    if (!id) return false;
    const b = s.boxes[id];
    return Boolean(b) && b[6] === 3;
  }
  function airBlit(s, g, spr, x, y) {
    const px = spr.pixels, mask = spr.mask || (spr.mask = new Uint8Array(px.length));
    let hidden = 0;
    for (let i = 0; i < px.length; i++) { const p = px[i]; mask[i] = airHidden(s, x + p[0], y + p[1]) ? 1 : 0; hidden += mask[i]; }
    if (hidden === px.length) return hidden;
    if (!hidden) { g.drawImage(spr.canvas, x, y); return 0; }
    drawVisible(g, px, mask, x, y);
    return hidden;
  }
  function drawAerial(s, g, d) {
    const t = s.clock, dusk = d.dusk;
    safely(s, 'birds', () => {
      const f = s.birds;
      if (!f.active) return;
      g.fillStyle = dusk > .2 ? '#2a3050' : '#3a3f4e';
      for (const b of f.flock) {
        const x = Math.round(f.x + b.dx * f.dir), y = Math.round(f.y + b.dy + Math.sin(t * .8 + b.ph) * 1.2), up = Math.sin(t * 9 + b.ph) > 0;
        if (airHidden(s, x, y)) continue;
        if (up) { g.fillRect(x, y, 1, 1); g.fillRect(x + 2, y, 1, 1); g.fillRect(x + 1, y + 1, 1, 1); } else { g.fillRect(x, y + 1, 3, 1); }
      }
    });
    safely(s, 'buoys', () => {
      if (dusk < .15) return;
      for (const b of s.buoys) {
        if (((t + b.phase) % b.period) > .45) continue;
        g.fillStyle = b.red ? '#ff4a3c' : '#4cff8c'; g.globalAlpha = Math.min(1, dusk * 1.2); g.fillRect(b.x, b.y, 2, 2);
        g.globalAlpha = .28 * dusk; g.fillRect(b.x - 1, b.y - 1, 4, 4); g.globalAlpha = 1;
      }
    });
    safely(s, 'heli', () => {
      if (s.data.living && (s.data.living.pads || []).length >= 2) return;
      const h = s.heli;
      if (!h.active) return;
      const dip = Math.sin(Math.PI * (1 - h.dip)) * (h.dip > 0 ? 8 : 0);
      const y = Math.round(h.y + Math.sin(h.bob * 1.7) * .8 + dip), x = Math.round(h.x);
      const spr = heliSprite(s, h.dir > 0 ? 1 : 0, Math.floor(t * 15) % 3);
      if (airBlit(s, g, spr, x - Math.floor(spr.w / 2), y - Math.floor(spr.h / 2)) > 4) return;
      const tailX = h.dir > 0 ? x - Math.floor(spr.w / 2) + 2 : x + Math.floor(spr.w / 2) - 2;
      if (((t * .9) % 1) < .16 && !airHidden(s, tailX, y - 2)) { g.fillStyle = '#ff4040'; g.fillRect(tailX, y - 2, 1, 1); if (dusk > .2) { g.globalAlpha = .4; g.fillRect(tailX - 1, y - 3, 3, 3); g.globalAlpha = 1; } }
      if (((t * .45) % 1) < .06 && !airHidden(s, x, y + 4)) { g.fillStyle = '#ffffff'; g.fillRect(x, y + 4, 1, 1); }
    });
    safely(s, 'heliRoutes', () => {
      const flights = helicopterFlights(s, (finite(s.dbg.lifeTime) ? s.dbg.lifeTime : s.clock) + (s.heliOffset || 0));
      for (const h of flights) {
        const [gx, gy, z] = h.point, rotor = Math.floor(t * 12) % 2;
        const spr = heliSprite(s, h.heading > 0 ? 1 : 0, rotor, h.kind);
        const pad = s.data.living.pads.find(p => Math.hypot(p.point[0] - gx, p.point[1] - gy) < .2 && z < p.point[2] + 8);
        blit(s, g, spr, gx, gy, z, false, undefined, undefined, pad && pad.id, true);
      }
    });
    safely(s, 'pigeons', () => {
      const flock = s.pigeons;
      if (!flock.active) return;
      for (let i = 0; i < 4; i++) {
        const u = flock.u - i * .085;
        if (u < 0 || u > 1) continue;
        const x = flock.dir > 0 ? -12 + 98 * u : s.W + 12 - 98 * u;
        const y = 180 - 205 * u + (i % 2) * 4 + Math.sin(t * 4 + i) * 1.2;
        const z = 44, [gx,gy] = unprojWorld(s, x, y + z);
        blit(s, g, pigeonSprite(s, flock.dir < 0, Math.floor(t * 7 + i) % 2), gx, gy, z);
      }
    });
    safely(s, 'blimp', () => {
      const b = s.blimp;
      if (!b.active) return;
      const flip = b.dir > 0 ? 0 : 1, spr = blimpSprite(s, flip), x = Math.round(b.x), y = Math.round(b.y + Math.sin(t * .35) * .6);
      const hidden = airBlit(s, g, spr, x, y);
      const cycle = b.message.length * 4, sx = Math.floor(b.dir > 0 ? b.scroll % cycle : (cycle - (b.scroll % cycle)) % cycle);
      g.globalAlpha = .55 + .45 * dusk;
      if (!hidden) g.drawImage(b.text, sx, 0, spr.bw, 5, x + spr.bx, y + spr.by, spr.bw, 5);
      else {                                                                          // partly behind a building: only the letters that show
        g.fillStyle = '#ffcf70';
        for (const [tx, ty] of b.textPixels) {
          if (tx < sx || tx >= sx + spr.bw) continue;
          const wx = x + spr.bx + tx - sx, wy = y + spr.by + ty;
          if (!airHidden(s, wx, wy)) g.fillRect(wx, wy, 1, 1);
        }
      }
      g.globalAlpha = 1;
      if (((t * .8) % 1) < .12 && !airHidden(s, x + (flip ? 4 : 47), y + 7)) { g.fillStyle = '#ff5a4a'; g.fillRect(x + (flip ? 4 : 47), y + 7, 1, 1); }
    });
  }

  function drawData(s, g) {
    for (const name of ['codex', 'claude', 'small']) {
      const tw = s.towers[name];
      if (tw) g.drawImage(tw.canvas, tw.ox, tw.oy);
    }
  }

  function drawCourier(s, g) {
    safely(s, 'courier', () => {
      const hero = s.courier;
      if (!hero.active) return;
      const x = hero.dir > 0 ? -18 + (s.W + 36) * hero.u : s.W + 18 - (s.W + 36) * hero.u;
      const y = 122 + hero.u * 18 + Math.sin(hero.u * Math.PI) * 5;
      const spr = courierSprite(s, hero.dir < 0, Math.floor(s.clock * 5) % 2);
      const z = 46, [gx, gy] = unprojWorld(s, x, y + z);
      // Hide the drone behind nearer buildings and keep quota windows on top.
      g.save(); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
      blit(s, g, spr, gx, gy, z, false, undefined, (px, py) => airHidden(s, px, py)); g.restore();
    });
  }
  /** Draw the first `lit` cells of a data building in its lit colour and every other cell as a dark socket, on whole pixels (the same rule as the atlas script). */
  function paintCells(ctx, cells, w, rows, ox, oy, lit, left, right, socket, vary = false) {
    for (let i = 0; i < cells.length; i++) {
      const c = cells[i], on = i < lit;
      const colour = on ? (c[2] > 0 ? left : right) : socket;
      const strength = vary && on ? [1, 1, .95, 1, .9, 1, .97, 1][i % 8] : 1;
      ctx.fillStyle = rgb(strength === 1 ? colour : colour.map(channel => Math.round(channel * strength)));
      for (let k = 0; k < w; k++) {
        const yc = c[1] + c[2] * .5 * k;
        for (const row of rows) ctx.fillRect(c[0] + k - ox, Math.floor(yc - row[1] + .5) - oy, 1, row[1] - row[0]);
      }
    }
  }
  /** Redraw a data building only when what it shows has changed. Unknown is a neutral grey socket with nothing lit: never an empty or a full building. */
  function refreshData(s) {
    const st = s.data_;
    for (const name of ['codex', 'claude', 'small']) {
      const tw = s.towers[name];
      if (!tw) continue;
      const t = tw.t, state = st[name];
      const sig = name === 'small' ? (state.known ? 'k' + state.quota + ':' + state.time : 'u') : (state.known ? 'k' + state.count : 'u');
      if (sig === tw.sig) continue;
      tw.sig = sig;
      const ctx = tw.ctx;
      ctx.clearRect(0, 0, tw.canvas.width, tw.canvas.height);
      const socket = state.known ? t.socket : t.unknown;
      if (name === 'small') {
        paintCells(ctx, t.quota, t.w, t.rows, tw.ox, tw.oy, state.known ? state.quota : 0, t.lit_quota, t.lit_quota, socket);
        paintCells(ctx, t.time, t.w, t.rows, tw.ox, tw.oy, state.known ? state.time : 0, t.lit_time, t.lit_time, socket);
      } else paintCells(ctx, t.cells, t.w, t.rows, tw.ox, tw.oy, state.known ? state.count : 0, t.lit_left, t.lit, socket, true);
    }
  }
  function drawPokes(s, g) {
    if (!s.pokes.length) return;
    g.fillStyle = '#ffd68c';
    for (const p of s.pokes) {
      const age = s.clock - p.t0 - p.delay;
      if (age < 0) continue;
      const a = age < .3 ? age / .3 : age > 6 ? clamp(1 - (age - 6) / 2, 0, 1) : 1;
      g.globalAlpha = a * .95; g.fillRect(p.x, p.y, p.w, p.h);
    }
    g.globalAlpha = 1;
  }
  function drawMoonAndStars(s, g, d, q) {
    const t = s.clock;
    safely(s, 'stars', () => {
      if (d.stars < .02) return;
      const n = Math.max(1, Math.round(s.starLayers.length * Math.min(1, q + .2)));
      for (let i = 0; i < n; i++) {
        const layer = s.starLayers[i];
        g.globalAlpha = d.stars * (1 - s.cloudAmount * .7) * (.55 + .45 * Math.sin(t * 1.1 + layer.tw + i * 1.9));
        g.drawImage(layer.canvas, 0, 0);
      }
      g.globalAlpha = 1;
      const u = (t % 103) / 2.2;
      if (u < 1 && s.cloudAmount < .7) {
        const x = Math.round(20 + u * 75), y = Math.round(10 + u * 15);
        if (!airHidden(s, x, y)) { g.fillStyle = '#f4f4ff'; g.globalAlpha = Math.sin(Math.PI * u) * d.stars; g.fillRect(x, y, 3, 1); g.globalAlpha = 1; }
      }
    });
    safely(s, 'moon', () => {
      if (d.moon < .03) return;
      const cx = (s.data.sunX || 206) - 60, cy = 28, phase = moonPhase(nowMs(s)), lit = (1 - Math.cos(phase * 2 * Math.PI)) / 2;
      if (lit < .04) return;                                                                            // a new moon is not in the sky at all
      const key = Math.round(phase * 200);
      if (s.moonKey !== key) { s.moonKey = key; s.moon = moonPicture(s, phase, lit); }                  // its picture is made again only when its phase has moved a little
      g.globalAlpha = d.moon * (1 - s.cloudAmount * .65); g.drawImage(s.moon, cx - 6, cy - 6);
      g.globalAlpha = 1;
    });
  }
  /** The moon as a 12 x 12 picture: a faint halo, the disc, the lit part (it grows from the right while the moon waxes) and the dark part. */
  function moonPicture(s, phase, lit) {
    const c = s.moon || s.mk(12, 12), g = c.getContext('2d'), r = 4;
    g.clearRect(0, 0, 12, 12);
    g.globalAlpha = .3 * (.25 + .75 * lit); g.fillStyle = '#9db4ff'; g.fillRect(0, 1, 12, 10); g.fillRect(1, 0, 10, 12);
    for (let y = -r; y <= r; y++) for (let x = -r; x <= r; x++) {
      if (x * x + y * y > r * r + .4) continue;
      const edge = Math.sqrt(Math.max(0, r * r - y * y)), terminator = (1 - 2 * lit) * edge;
      const on = phase < .5 ? x >= terminator - .5 : x <= -terminator + .5;
      g.globalAlpha = on ? 1 : .22; g.fillStyle = on ? '#eef2ff' : '#3a4474'; g.fillRect(6 + x, 6 + y, 1, 1);
    }
    g.globalAlpha = 1;
    return c;
  }
  function drawClouds(s, g, d) {
    safely(s, 'clouds', () => {
      const A = s.phaseA || 'night', B = s.phaseB, tB = s.phaseT || 0;
      for (let i = 0; i < s.clouds.length; i++) {
        const c = s.clouds[i], opacity = clamp(s.cloudAmount * 6 - i, 0, 1) * .92;
        if (opacity <= 0) continue;
        g.globalAlpha = (B ? 1 - tB : 1) * opacity; drawFrame(s, g, 'cloud-' + c.n + '-' + A, Math.round(c.x), Math.round(c.y));
        if (B) { g.globalAlpha = tB * opacity; drawFrame(s, g, 'cloud-' + c.n + '-' + B, Math.round(c.x), Math.round(c.y)); }
      }
      g.globalAlpha = 1;
    });
  }

  function drawScene(s, api, g) {
    const started = typeof performance !== 'undefined' ? performance.now() : 0;
    const d = s.day || (s.day = dayState(nowMs(s), s.place)), q = s.quality;
    g.imageSmoothingEnabled = false;
    g.setTransform(1, 0, 0, 1, -s.cam[0], -s.cam[1]);
    g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
    safely(s, 'compose', () => compose(s, d));
    safely(s, 'data', () => refreshData(s));
    const cx = s.cam[0], cy = s.cam[1], skyH = Math.max(0, s.sky.height - cy);          // only what the screen shows: the sky is needed only where the city thins out
    if (skyH > 0) g.drawImage(s.sky, cx, cy, SIZE[0], skyH, cx, cy, SIZE[0], skyH);
    drawMoonAndStars(s, g, d, q);
    drawClouds(s, g, d);
    g.drawImage(s.base, cx, cy, SIZE[0], SIZE[1], cx, cy, SIZE[0], SIZE[1]);
    safely(s, 'marketCover', () => drawMarketCover(s, g));
    safely(s, 'movingBridgeWater', () => drawMovingBridge(s, g, d, false));
    drawGround(s, g, d, q);
    safely(s, 'movingBridgeDeck', () => drawMovingBridge(s, g, d, true));
    safely(s, 'cityLife', () => drawCityLife(s, g, d, q));
    drawRoof(s, g, d, q);
    drawWeather(s, g, d, q);
    drawAerial(s, g, d);
    safely(s, 'pokes', () => drawPokes(s, g));
    drawCourier(s, g);
    safely(s, 'towers', () => drawData(s, g));
    g.setTransform(1, 0, 0, 1, 0, 0);
    if (started) s.drawMs += (performance.now() - started - s.drawMs) * 0.06;
  }

  /** A touch: the helicopter dips towards it if it is near, and a few windows around it light up for a few seconds (never the data buildings: their windows are
   *  drawn last, and only from the readings). */
  function pokeScene(s, api, x, y) {
    const wx = x + s.cam[0], wy = y + s.cam[1], h = s.heli;
    if (h.active && Math.abs(wx - h.x) < 56 && Math.abs(wy - h.y) < 48) h.dip = 1;
    const living = s.data.living;
    if (living && living.stadiums && living.stadiums[0]) {
      const f = living.stadiums[0].field, [sx, sy] = projWorld(s, (f[0] + f[2]) / 2, (f[1] + f[3]) / 2, f[4]);
      if (Math.hypot(wx - sx, wy - sy) < 23) s.matchStarted = s.clock;
    }
    const sites = living && flightPads(living.pads);
    if (sites) {
      const p = sites.b.point, [px, py] = projWorld(s, ...p), phase = lifePhase(s.clock + (s.heliOffset || 0)).t;
      if (Math.hypot(wx - px, wy - py) < 14 && phase >= 120) s.heliOffset = 58 - s.clock;
    }
    const list = s.data.poke || [], near = [];
    for (let i = 0; i < list.length; i++) { const w = list[i], dist = Math.hypot(w[0] - wx, w[1] - wy); if (dist < 34) near.push([dist, w]); }
    if (near.length < 6) for (let i = 0; i < list.length; i++) { const w = list[i], dist = Math.hypot(w[0] - wx, w[1] - wy); if (dist >= 34 && dist < 80) near.push([dist, w]); }
    for (let i = near.length - 1; i > 0; i--) { const j = Math.floor(s.rnd() * (i + 1)); [near[i], near[j]] = [near[j], near[i]]; }
    for (const [dist, w] of near.slice(0, 14)) s.pokes.push({ x: w[0], y: w[1], w: w[2], h: w[3], t0: s.clock, delay: dist * .012 });
    if (s.pokes.length > 80) s.pokes.splice(0, s.pokes.length - 80);
  }

  /* ------------------------------------------------------------------------------------------------------------------------------------ the scene */
  const scene = {
    size: SIZE,
    post: 'crt-clear',
    needsAtlas: true,
    dbg: {},
    init(api) { this.s = buildScene(api, this.dbg); this.s.quality = 1; stepScene(this.s, api, 1 / 30); for (let i = 0; i < 90; i++) stepScene(this.s, api, 1 / 30); },
    step(api, dt) { if (this.s) stepScene(this.s, api, dt); },
    draw(api, g) { if (this.s) drawScene(this.s, api, g); },
    poke(api, x, y) { if (this.s) pokeScene(this.s, api, x, y); },
  };
  Object.assign(logic, { scene, rasterise, vehicleSprite, heliSprite, pigeonSprite, courierSprite, textStrip, FONT, paintCells, bridgeDeckQuads, underBridge, blit });
  if (global.TabletGames && typeof global.TabletGames.define === 'function') global.TabletGames.define(NAME, scene);
  if (typeof module !== 'undefined' && module.exports) module.exports = logic;
})(typeof window !== 'undefined' ? window : globalThis);
