import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';

// The tablet's clock logic: where the sun is, the day's parts, the night's fade, the scene that suits the moment, the pixel shift.
const require = createRequire(import.meta.url);
const {sunTimes, daypart, nightAmount, autoScene, pixelShift, POOLS} = require('../token_tv/tablet_web/schedule.js');
const BCN = {lat: 41.39, lon: 2.17};
const utc = (y, m, d, h = 0, min = 0) => Date.UTC(y, m - 1, d, h, min);
const hours = ms => ms / 3600000;
const hourOfDay = ms => new Date(ms).getUTCHours() + new Date(ms).getUTCMinutes() / 60;

test('sun times in Barcelona: a November day is about ten hours, a June day about fifteen', () => {
  const nov = sunTimes(utc(2026, 11, 9, 12), BCN.lat, BCN.lon);
  assert.ok(hourOfDay(nov.sunrise) > 6.1 && hourOfDay(nov.sunrise) < 6.8, `sunrise ${hourOfDay(nov.sunrise)}`);
  assert.ok(hourOfDay(nov.sunset) > 16.3 && hourOfDay(nov.sunset) < 17.0, `sunset ${hourOfDay(nov.sunset)}`);
  assert.ok(hourOfDay(nov.noon) > 11.4 && hourOfDay(nov.noon) < 11.9);
  const length = hours(nov.sunset - nov.sunrise);
  assert.ok(length > 9.8 && length < 10.6, `length ${length}`);
  const jun = sunTimes(utc(2026, 6, 21, 12), BCN.lat, BCN.lon);
  assert.ok(hourOfDay(jun.sunrise) > 3.8 && hourOfDay(jun.sunrise) < 4.6 && hourOfDay(jun.sunset) > 19.2 && hourOfDay(jun.sunset) < 19.9);
  assert.ok(hours(jun.sunset - jun.sunrise) > 14.8 && hours(jun.sunset - jun.sunrise) < 15.8);
});

test('the equinox is about twelve hours everywhere and the poles have a polar night and day', () => {
  for (const [lat, lon] of [[51.48, 0], [-33.9, 151.2], [0, -78.5], [40.7, -74]]) {
    const s = sunTimes(utc(2026, 3, 20, 12), lat, lon);
    const length = hours(s.sunset - s.sunrise);
    assert.ok(length > 11.8 && length < 12.5, `${lat},${lon}: ${length}`);
    assert.ok(s.sunrise < s.noon && s.noon < s.sunset);
  }
  assert.deepEqual([sunTimes(utc(2026, 12, 21, 12), 80, 10).sunrise, sunTimes(utc(2026, 12, 21, 12), 80, 10).polar], [null, 'night']);
  assert.equal(sunTimes(utc(2026, 6, 21, 12), 80, 10).polar, 'day');
});

test('the events belong to the solar day of the moment asked, near midnight too', () => {
  for (const at of [utc(2026, 11, 9, 0, 5), utc(2026, 11, 9, 23, 55), utc(2026, 11, 9, 6, 0)]) {
    const s = sunTimes(at, BCN.lat, BCN.lon);
    assert.ok(Math.abs(s.noon - at) < 13 * 3600000, 'noon within half a day');
  }
  const [a, b] = [sunTimes(utc(2026, 11, 9, 1), BCN.lat, BCN.lon), sunTimes(utc(2026, 11, 9, 22), BCN.lat, BCN.lon)];
  assert.equal(a.sunrise, b.sunrise);
});

test('the parts of the day follow the sun, and a polar place has only day or night', () => {
  const sun = sunTimes(utc(2026, 11, 9, 12), BCN.lat, BCN.lon);
  const at = (h, m = 0) => daypart(utc(2026, 11, 9, h, m), sun);
  assert.deepEqual([at(3), at(6, 20), at(7, 30), at(10), at(14), at(15, 30), at(17), at(18), at(23)], ['night', 'dawn', 'dawn', 'day', 'day', 'dusk', 'dusk', 'night', 'night']);
  assert.equal(daypart(0, sunTimes(utc(2026, 6, 21, 12), 80, 10)), 'day');
  assert.equal(daypart(0, sunTimes(utc(2026, 12, 21, 12), 80, 10)), 'night');
});

test('night fades in and out at the edges and wraps past midnight', () => {
  const night = {enabled: true, start: '23:00', end: '07:30'};
  const at = (h, m) => nightAmount(new Date(2026, 10, 9, h, m), night);
  const near = (a, b) => assert.ok(Math.abs(a - b) < 0.02, `${a} is not ${b}`);
  near(at(12, 0), 0); near(at(22, 59), 0); near(at(23, 10), 0.5); near(at(23, 20), 1); near(at(3, 0), 1); near(at(7, 20), 0.5); near(at(7, 30), 0); near(at(8, 0), 0);
  assert.equal(nightAmount(new Date(2026, 10, 9, 3, 0), {...night, enabled: false}), 0);
  assert.equal(nightAmount(new Date(2026, 10, 9, 3, 0), {...night, start: '03:00', end: '03:00'}), 0);
  assert.equal(nightAmount(new Date(2026, 10, 9, 14, 0), {enabled: true, start: '13:00', end: '15:00'}), 1);
  assert.equal(nightAmount(new Date(2026, 10, 9, 16, 0), {enabled: true, start: '13:00', end: '15:00'}), 0);
  assert.equal(nightAmount(new Date(2026, 10, 9, 3, 0), {enabled: true, start: 'late', end: '07:30'}), 0);
  for (let minute = 0; minute < 1440; minute += 7) {
    const value = nightAmount(new Date(2026, 10, 9, 0, minute), night);
    assert.ok(value >= 0 && value <= 1);
  }
});

const ALL = ['city', 'paradise', 'surf', 'token-run', 'city-iso', 'fighting', 'neon-city', 'neon-district', 'violet-horizon'];

test('the new nocturnal films participate in the suggested night rotation when installed', () => {
  const available = ['infinite-express', 'midnight-video-club'];
  const start = utc(2026, 11, 9, 22);
  const picks = [0, 1].map(i => autoScene({...BCN, now: start + i * 20 * 60000, mode: 'daypart', minutes: 20, available}));
  assert.deepEqual(picks.sort(), available.slice().sort());
  assert.equal(POOLS.night.includes('neon-city'), false);
});

test('the scene suits the light of the moment, changes every N minutes and survives a reload', () => {
  const base = {...BCN, mode: 'daypart', minutes: 20, available: ALL};
  const day = utc(2026, 11, 9, 10), night = utc(2026, 11, 9, 22), dawn = utc(2026, 11, 9, 7);
  assert.ok(POOLS.day.includes(autoScene({...base, now: day})));
  assert.ok(POOLS.night.includes(autoScene({...base, now: night})));
  assert.ok(POOLS.dawn.includes(autoScene({...base, now: dawn})));
  assert.equal(autoScene({...base, now: day}), autoScene({...base, now: day + 5 * 60000 - (day % (20 * 60000))}), 'the same slot gives the same scene');
  const seen = new Set();
  for (let slot = 0; slot < 6; slot++) seen.add(autoScene({...base, now: day - (day % (20 * 60000)) + slot * 20 * 60000}));
  assert.ok(seen.size >= 2, 'it moves along the pool');
  assert.deepEqual([...new Set([0, 1, 2].map(i => autoScene({...base, now: night - (night % 1200000) + i * 1200000})))].every(name => POOLS.night.includes(name)), true);
});

test('auto falls back to what is available and never names a scene that is missing', () => {
  const only = ['surf', 'city'];
  for (const now of [utc(2026, 11, 9, 3), utc(2026, 11, 9, 10), utc(2026, 11, 9, 16)]) assert.ok(only.includes(autoScene({...BCN, now, mode: 'daypart', minutes: 20, available: only})));
  assert.equal(autoScene({...BCN, now: 0, mode: 'daypart', minutes: 20, available: []}), null);
  assert.equal(autoScene({...BCN, now: 0, mode: 'daypart', minutes: 20}), null);
  const rotate = [0, 1, 2, 3].map(i => autoScene({...BCN, now: i * 600000, mode: 'rotate', minutes: 10, available: ['a', 'b', 'c']}));
  assert.deepEqual(rotate.slice(0, 3).sort(), ['a', 'b', 'c']);
  assert.equal(autoScene({...BCN, now: 0, mode: 'rotate', minutes: 1, available: ['a', 'b']}), autoScene({...BCN, now: 4 * 60000, mode: 'rotate', minutes: 5, available: ['a', 'b']}), 'minutes are clamped to 5..240');
});

test('the pixel shift is small, slow and the same within a minute', () => {
  const t = utc(2026, 11, 9, 2, 0);
  assert.deepEqual(pixelShift(t, 6), pixelShift(t + 59000, 6));
  const values = new Set();
  for (let m = 0; m < 20; m++) { const s = pixelShift(t + m * 60000, 6); assert.ok(Math.abs(s.x) <= 6 && Math.abs(s.y) <= 6); values.add(s.x + ',' + s.y); }
  assert.ok(values.size >= 6);
});


// The user's own lists (2026-11-10): which scenes the rotation and each part of the day may use.
const EVERY = ['city', 'paradise', 'surf', 'city-iso', 'neon-city', 'neon-district', 'violet-horizon'];
const noon = utc(2026, 11, 9, 11);            // a November noon in Barcelona: the 'day' part
const midnight = utc(2026, 11, 9, 23, 30);    // the 'night' part

test('the rotation uses only the scenes the user chose, moving along them every `minutes`', () => {
  const picks = [];
  for (let m = 0; m < 6; m++) picks.push(autoScene({now: noon + m * 30 * 60000, ...BCN, mode: 'rotate', minutes: 30, available: EVERY, rotate: ['surf', 'city']}));
  assert.deepEqual([...new Set(picks)].sort(), ['city', 'surf']);
  for (let m = 1; m < 6; m++) assert.notEqual(picks[m], picks[m - 1], 'it moves to the next one every slot');
});

test('an empty or useless rotation list means every available scene, as before', () => {
  const seen = new Set();
  for (let m = 0; m < 14; m++) seen.add(autoScene({now: noon + m * 20 * 60000, ...BCN, mode: 'rotate', minutes: 20, available: EVERY, rotate: []}));
  assert.equal(seen.size, EVERY.length);
  assert.ok(EVERY.includes(autoScene({now: noon, ...BCN, mode: 'rotate', minutes: 20, available: EVERY, rotate: ['gone', 5, null]})));
  assert.ok(EVERY.includes(autoScene({now: noon, ...BCN, mode: 'rotate', minutes: 20, available: EVERY, rotate: 'surf'})));
});

test('the user\'s list for a part of the day replaces the built-in one, and only that part', () => {
  const day = autoScene({now: noon, ...BCN, mode: 'daypart', minutes: 20, available: EVERY, parts: {day: ['violet-horizon'], night: ['paradise']}});
  assert.equal(day, 'violet-horizon');
  const night = autoScene({now: midnight, ...BCN, mode: 'daypart', minutes: 20, available: EVERY, parts: {day: ['violet-horizon'], night: ['paradise']}});
  assert.equal(night, 'paradise');
  const other = autoScene({now: midnight, ...BCN, mode: 'daypart', minutes: 20, available: EVERY, parts: {day: ['violet-horizon']}});
  assert.ok(POOLS.night.includes(other), 'a part without a list keeps the built-in scenes');
});

test('a chosen scene that is not available falls back to the built-in pool, never to nothing', () => {
  const pick = autoScene({now: noon, ...BCN, mode: 'daypart', minutes: 20, available: ['city', 'paradise'], parts: {day: ['surf']}});
  assert.ok(['city', 'paradise'].includes(pick));
  assert.equal(autoScene({now: noon, ...BCN, mode: 'rotate', minutes: 20, available: [], rotate: ['surf']}), null);
});

test('with a one-hour step the scene changes exactly on the hour, so a change tells you an hour has gone by', () => {
  const at = (h, min) => autoScene({now: utc(2026, 11, 9, h, min), ...BCN, mode: 'rotate', minutes: 60, available: EVERY});
  assert.equal(at(10, 0), at(10, 59));
  assert.notEqual(at(10, 59), at(11, 0));
  assert.equal(at(11, 0), at(11, 59));
});

test('the quick choices and the list buttons exist in the settings sheet and the chooser dialog is in the page', async () => {
  const {readFileSync} = await import('node:fs');
  const panels = readFileSync(new URL('../token_tv/tablet_web/panels.js', import.meta.url), 'utf8');
  const html = readFileSync(new URL('../token_tv/tablet_web/index.html', import.meta.url), 'utf8');
  for (const which of ['rotate', 'dawn', 'day', 'dusk', 'night']) assert.match(panels, new RegExp(`which: '${which}'`));
  for (const minutes of [5, 15, 30, 60, 120, 240]) assert.match(panels, new RegExp(`\\[${minutes}, `));
  assert.match(html, /<dialog class="scene-dialog pool" id="pool-dialog"/);
});
