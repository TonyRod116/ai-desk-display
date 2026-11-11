/* The tablet's clock logic, as pure functions: where the sun is (so the scene can follow the real day, computed here with no internet), whether
   it is night, how far into the night's fade, which scene suits the moment and a slow pixel shift against burn-in. app.js uses them; the Node
   tests check them. Nothing here reads the board's schedule: the tablet has its own settings. */
(function (global) {
  'use strict';
  const RAD = Math.PI / 180;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  /* The sunrise equation (Meeus / NOAA, good to about a minute). The "day" is the solar day at the place, so any longitude works.
     Returns epoch milliseconds, or null for the polar night or day (then `polar` says which). */
  function sunTimes(now, lat, lon) {
    const at = now instanceof Date ? now.getTime() : Number(now);
    const shifted = at + lon / 15 * 3600000;
    const day = new Date(shifted);
    const midnight = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate()) - lon / 15 * 3600000;   // solar midnight at the place
    const jd = midnight / 86400000 + 2440587.5;
    const n = Math.ceil(jd - 2451545.0 + 0.0008);
    const mean = n - lon / 360;                                  // east longitudes see noon earlier
    const anomaly = ((357.5291 + 0.98560028 * mean) % 360 + 360) % 360;
    const center = 1.9148 * Math.sin(anomaly * RAD) + 0.02 * Math.sin(2 * anomaly * RAD) + 0.0003 * Math.sin(3 * anomaly * RAD);
    const ecliptic = (anomaly + center + 180 + 102.9372) % 360;
    const transit = 2451545.0 + mean + 0.0053 * Math.sin(anomaly * RAD) - 0.0069 * Math.sin(2 * ecliptic * RAD);
    const declination = Math.asin(Math.sin(ecliptic * RAD) * Math.sin(23.4397 * RAD));
    const cosine = (Math.sin(-0.833 * RAD) - Math.sin(lat * RAD) * Math.sin(declination)) / (Math.cos(lat * RAD) * Math.cos(declination));
    const toMs = (julian) => (julian - 2440587.5) * 86400000;
    const noon = toMs(transit);
    if (!Number.isFinite(cosine)) return { sunrise: null, sunset: null, noon, polar: null };
    if (cosine > 1) return { sunrise: null, sunset: null, noon, polar: 'night' };
    if (cosine < -1) return { sunrise: null, sunset: null, noon, polar: 'day' };
    const half = Math.acos(cosine) / (2 * Math.PI);                  // a fraction of a day
    return { sunrise: toMs(transit - half), sunset: toMs(transit + half), noon, polar: null };
  }

  /* dawn: from 45 minutes before sunrise to two hours after; dusk: from two hours before sunset to 45 minutes after. */
  function daypart(now, sun) {
    if (!sun || (sun.polar && !sun.sunrise)) return sun && sun.polar === 'day' ? 'day' : 'night';
    const t = now instanceof Date ? now.getTime() : Number(now), M = 60000;
    if (t >= sun.sunrise - 45 * M && t < sun.sunrise + 120 * M) return 'dawn';
    if (t >= sun.sunrise + 120 * M && t < sun.sunset - 120 * M) return 'day';
    if (t >= sun.sunset - 120 * M && t < sun.sunset + 45 * M) return 'dusk';
    return 'night';
  }

  const minutesOf = (text) => /^([01]\d|2[0-3]):([0-5]\d)$/.test(text) ? Number(text.slice(0, 2)) * 60 + Number(text.slice(3)) : null;

  /* How far into the night it is, 0 (day) to 1 (night), fading over `ramp` minutes at each edge so the screen dims and brightens gently. */
  function nightAmount(now, night, ramp = 20) {
    if (!night || !night.enabled) return 0;
    const start = minutesOf(night.start), end = minutesOf(night.end);
    if (start === null || end === null || start === end) return 0;
    const d = now instanceof Date ? now : new Date(now);
    const minute = d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
    const length = (end - start + 1440) % 1440 || 1440, into = (minute - start + 1440) % 1440;
    if (into >= length) return 0;
    const edge = Math.min(ramp, length / 2);
    return clamp(Math.min(into / edge, (length - into) / edge), 0, 1);
  }

  const POOLS = { dawn: ['paradise', 'city'], day: ['city-iso', 'city', 'paradise'], dusk: ['violet-horizon', 'neon-district', 'city'],
                  night: ['neon-district', 'violet-horizon', 'infinite-express', 'midnight-video-club'] };

  /* The scene for this moment. `daypart` mode picks from the realistic scenes that suit the light and moves along them every `minutes`;
     `rotate` mode walks through every available scene. The slot comes from the clock, so a reload never restarts the sequence. */
  function autoScene({ now, lat, lon, mode, minutes, available, rotate, parts }) {
    const list = Array.isArray(available) ? available : [];
    if (!list.length) return null;
    const step = clamp(Number(minutes) || 20, 5, 240) * 60000;
    const t = now instanceof Date ? now.getTime() : Number(now);
    const mine = (names) => Array.isArray(names) ? names.filter((name) => typeof name === 'string' && list.includes(name)) : [];   // the user's own list, only scenes that exist now
    let pool = list;
    if (mode === 'rotate') {
      const chosen = mine(rotate);
      if (chosen.length) pool = chosen;
    } else {
      const part = daypart(t, sunTimes(t, lat, lon));
      const chosen = mine(parts && Object.hasOwn(parts, part) ? parts[part] : null);
      const wanted = chosen.length ? chosen : POOLS[part].filter((name) => list.includes(name));
      if (wanted.length) pool = wanted;
    }
    return pool[Math.floor(t / step) % pool.length];
  }

  /* A slow, small shift of the picture at night (burn-in and image retention): a different spot every minute, never more than `amount` px. */
  function pixelShift(now, amount) {
    const m = Math.floor((now instanceof Date ? now.getTime() : Number(now)) / 60000);
    return { x: Math.round(Math.sin(m * 0.9) * amount), y: Math.round(Math.cos(m * 1.3) * amount) };
  }

  const api = { sunTimes, daypart, nightAmount, autoScene, pixelShift, minutesOf, POOLS };
  global.TabletSchedule = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
