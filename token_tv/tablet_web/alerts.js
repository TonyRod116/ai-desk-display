/* Alerts for the tablet: a rule engine that watches the readings the page already has and says when something just happened (a quota fell
   under its limit, a window renewed, a disk filled), and a small synthesised chime for it (no sound files: WebAudio only). The engine never
   alerts on what it sees first (a page opened with a disk already full is not news), waits for a recovery before it can alert again, and
   says nothing about unknown readings. The page decides how to show an alert and whether it may sound (settings, night, the browser's rule
   that audio starts after a first touch). */
(function (global) {
  'use strict';
  const valid = (v) => typeof v === 'number' && Number.isFinite(v);

  function create() {
    const state = new Map();
    /* One watched number against one limit. `crossed` is true only when it goes from at-or-above the limit to under it; once under, it must
       climb `margin` above the limit before it can cross again. The first value seen only sets the baseline. */
    function watch(key, value, limit, margin) {
      if (!valid(value)) return false;
      const s = state.get(key) || { seen: false, low: false };
      let crossed = false;
      if (!s.seen) { s.seen = true; s.low = value < limit; }
      else if (!s.low && value < limit) { s.low = true; crossed = true; }
      else if (s.low && value >= limit + margin) s.low = false;
      state.set(key, s);
      return crossed;
    }
    /* A window renewed when its reset time jumps forward by half an hour or more (a few seconds of jitter is not a renewal). */
    function renewed(key, resetsAt) {
      if (!valid(resetsAt)) return false;
      const s = state.get(key) || { at: null };
      const jumped = s.at !== null && resetsAt - s.at >= 1800;
      s.at = resetsAt;
      state.set(key, s);
      return jumped;
    }

    function feed(latest, rules, now) {
      const out = [], limits = rules || {}, quotaLimit = valid(limits.quota) ? limits.quota : 10, diskLimit = valid(limits.disk) ? limits.disk : 5;
      const providers = latest && latest.providers || {};
      for (const [provider, data] of Object.entries(providers)) {
        for (const [window, label] of [['weekly', 'week'], ['session', 'five']]) {
          const reading = data && data[window];
          if (!reading || !valid(reading.remaining) || reading.remaining < 0 || reading.remaining > 100) continue;
          if (reading.resets_at !== undefined && valid(reading.resets_at) && reading.resets_at * 1000 <= now) continue;   // an expired window is not a reading
          const base = { provider, window: label, value: Math.floor(reading.remaining) };
          if (watch(`q:${provider}:${window}`, reading.remaining, quotaLimit, 3)) out.push({ ...base, kind: 'quota-low', level: 'warning' });
          if (quotaLimit > 5 && watch(`c:${provider}:${window}`, reading.remaining, 5, 2)) out.push({ ...base, kind: 'quota-critical', level: 'critical' });
          if (renewed(`r:${provider}:${window}`, reading.resets_at) && limits.resets !== false) out.push({ ...base, kind: 'reset', level: 'info' });
        }
      }
      const disks = latest && latest.metrics && Array.isArray(latest.metrics.disks) ? latest.metrics.disks : [];
      for (const disk of disks) {
        if (!disk || typeof disk.name !== 'string' || disk.kind === 'google_drive') continue;       // the cloud reading is manual and dated: never an alarm
        if (!valid(disk.total) || disk.total <= 0 || !valid(disk.free) || disk.free < 0 || disk.free > disk.total) continue;
        const percent = 100 * disk.free / disk.total;
        if (watch(`d:${disk.name}`, percent, diskLimit, 2)) out.push({ kind: 'disk-low', level: 'critical', name: disk.name, free: disk.free, total: disk.total, value: Math.floor(percent) });
      }
      return out;
    }
    return { feed, reset: () => state.clear() };
  }

  const RANK = { info: 0, warning: 1, critical: 2 };
  const worst = (list) => list.reduce((a, b) => (!a || RANK[b.level] > RANK[a.level] ? b : a), null);

  /* Notes: [frequency Hz, start s, length s]. Soft, short, never harsh: a tablet speaker on a desk. */
  const TUNES = {
    info: { wave: 'sine', notes: [[523.25, 0, 0.18], [659.25, 0.16, 0.18], [783.99, 0.32, 0.42]] },
    warning: { wave: 'sine', notes: [[659.25, 0, 0.22], [880, 0.2, 0.4]] },
    critical: { wave: 'triangle', notes: [[880, 0, 0.18], [698.46, 0.2, 0.18], [880, 0.4, 0.18], [698.46, 0.6, 0.34]] },
  };

  /* `Context` is the browser's AudioContext class (or a stand-in). A context starts suspended until the page has been touched (the browser's
     rule), so `unlock()` is called from the first touch; `state()` says whether a chime would be heard. */
  function createSound(Context) {
    let ctx = null;
    const ensure = () => {
      if (!ctx && typeof Context === 'function') { try { ctx = new Context(); } catch (_) { ctx = null; } }
      return ctx;
    };
    function unlock() {
      const c = ensure();
      if (c && c.state === 'suspended' && typeof c.resume === 'function') { try { const p = c.resume(); if (p && p.catch) p.catch(() => {}); } catch (_) { /* still locked */ } }
      return state();
    }
    function state() {
      if (typeof Context !== 'function') return 'unsupported';
      return ctx && ctx.state === 'running' ? 'ready' : 'locked';
    }
    function play(level, volume) {
      const gain = Math.max(0, Math.min(1, Number(volume) / 100)) * 0.32;
      const tune = TUNES[level] || TUNES.warning;
      if (!(gain > 0) || state() !== 'ready') return false;
      const t0 = ctx.currentTime + 0.02;
      for (const [freq, start, length] of tune.notes) {
        const osc = ctx.createOscillator(), envelope = ctx.createGain();
        osc.type = tune.wave; osc.frequency.value = freq;
        envelope.gain.setValueAtTime(0.0001, t0 + start);
        envelope.gain.exponentialRampToValueAtTime(gain, t0 + start + 0.015);
        envelope.gain.exponentialRampToValueAtTime(0.0001, t0 + start + length);
        osc.connect(envelope); envelope.connect(ctx.destination);
        osc.start(t0 + start); osc.stop(t0 + start + length + 0.05);
      }
      return true;
    }
    return { unlock, state, play };
  }

  const api = { create, createSound, worst, TUNES };
  global.TabletAlerts = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
