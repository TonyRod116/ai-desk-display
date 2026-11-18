/* The tablet's three big panels, built from data: the settings sheet (the tablet's OWN settings, kept on the PC), the Computer page (everything about
   the PC: what uses the most, network, battery, the trend of the last hour, every disk) and the Small screen page (a remote for the touch board).
   app.js owns the data, the language and the layout; it hands this file a small context (`ctx`) and calls the render functions when something changed.
   Nothing here talks to the board directly: the remote goes through the tablet server, which only passes a short list of commands to the monitor. */
(function (global) {
  'use strict';
  let ctx = null;
  const $ = (selector, root = document) => root.querySelector(selector);
  const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
  const valid = (v) => typeof v === 'number' && Number.isFinite(v);
  const t = (key) => (ctx.words()[key] || key);

  /* ---- small drawing helpers (SVG made with the DOM, never from strings) */
  const NS = 'http://www.w3.org/2000/svg';
  function sparkline(values, { max = null, className = 'spark' } = {}) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 100 30'); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('class', className); svg.setAttribute('aria-hidden', 'true');
    const points = (Array.isArray(values) ? values : []).map((v, i, all) => ({ v, x: all.length > 1 ? i / (all.length - 1) * 100 : 50 })).filter((p) => valid(p.v));
    if (points.length < 2) return svg;
    const top = max !== null ? max : Math.max(1, ...points.map((p) => p.v)), floor = max !== null ? 0 : Math.min(...points.map((p) => p.v), 0);
    const y = (v) => 28 - (Math.min(top, Math.max(floor, v)) - floor) / ((top - floor) || 1) * 26;
    const line = document.createElementNS(NS, 'polyline');
    line.setAttribute('points', points.map((p) => p.x.toFixed(1) + ',' + y(p.v).toFixed(1)).join(' '));
    const area = document.createElementNS(NS, 'polygon');
    area.setAttribute('points', '0,30 ' + points.map((p) => p.x.toFixed(1) + ',' + y(p.v).toFixed(1)).join(' ') + ' 100,30');
    svg.append(area, line);
    return svg;
  }
  const rate = (bps) => {                       // the PC reports BITS per second, as network speeds are usually quoted
    if (!valid(bps) || bps < 0) return '—';
    if (bps >= 1e6) return (bps / 1e6).toFixed(bps >= 1e7 ? 0 : 1) + ' Mb/s';
    if (bps >= 1e3) return Math.round(bps / 1e3) + ' kb/s';
    return Math.round(bps) + ' b/s';
  };
  const duration = (seconds) => {
    if (!valid(seconds) || seconds < 0) return '—';
    const d = Math.floor(seconds / 86400), h = Math.floor(seconds % 86400 / 3600), m = Math.floor(seconds % 3600 / 60);
    return d ? d + 'd ' + h + 'h' : h ? h + 'h ' + m + 'm' : m + 'm';
  };
  const level = (percent) => percent >= 90 ? 'critical' : percent >= 75 ? 'low' : percent >= 55 ? 'warning' : 'healthy';   // a busy machine goes from green to red

  const memoryAction = { busy: false, result: null, timer: 0 };
  function availableSize(bytes) {
    const gb = bytes / (1024 ** 3);
    if (gb < 1) return Math.round(bytes / (1024 ** 2)) + ' MB';
    if (gb >= 1024) return (gb / 1024).toFixed(1) + ' TB';
    return gb.toFixed(1) + ' GB';
  }
  function memoryHint() {
    if (memoryAction.busy) return t('memory_working');
    const result = memoryAction.result;
    if (!result) return t('memory_touch');
    if (result.state === 'done') {
      const names = Array.isArray(result.apps) ? result.apps.filter((x) => x === 'Slack' || x === 'OneDrive').join(' + ') : '';
      const observed = valid(result.before) && valid(result.after) ? ' · ' + t('memory_available') + ' ' + availableSize(result.before) + ' → ' + availableSize(result.after) : '';
      return t('memory_done') + (names ? ': ' + names : '') + observed;
    }
    const word = { nothing: 'memory_nothing', unavailable: 'memory_unavailable', unknown: 'memory_unknown', busy: 'memory_busy', cooldown: 'memory_cooldown' }[result.state] || 'memory_unknown';
    return t(word);
  }
  async function releaseMemory() {
    if (memoryAction.busy) return;
    clearTimeout(memoryAction.timer); memoryAction.busy = true; memoryAction.result = null; renderComputer();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await fetch('/api/memory/release', { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}', cache:'no-store', signal:controller.signal });
      const result = await response.json();
      memoryAction.result = result && typeof result === 'object' ? result : {state:'unknown'};
    } catch (_) { memoryAction.result = {state:'unknown'}; }
    finally {
      clearTimeout(timer); memoryAction.busy = false; renderComputer();
      memoryAction.timer = setTimeout(() => { if (!memoryAction.busy) { memoryAction.result = null; renderComputer(); } }, 12000);
    }
  }

  /* ---- the Computer page */
  function gauge(title, big, unit, percent, history, extra) {
    const card = el('article', 'gauge'); if (valid(percent)) card.dataset.level = level(percent);
    const head = el('div', 'gauge-title'); head.append(el('span', '', title), el('b', '', valid(percent) ? Math.round(percent) + '%' : '—'));
    const value = el('div', 'gauge-value', big); if (unit) value.append(el('small', '', unit));
    const track = el('div', 'system-meter'); const fill = el('span'); track.append(fill); fill.style.width = (valid(percent) ? Math.max(0, Math.min(100, percent)) : 0) + '%';
    card.append(head, value, track, sparkline(history, { max: 100 }));
    if (extra) card.append(el('div', 'gauge-extra', extra));
    return card;
  }
  function usingList(title, rows, format, max) {
    const box = el('div', 'using');
    box.append(el('h3', '', title));
    const list = el('ol');
    rows.slice(0, 5).forEach((row) => {
      const item = el('li');
      const bar = el('i'); bar.style.width = Math.max(4, Math.min(100, row.value / (max || 1) * 100)) + '%';
      item.append(el('span', 'name', row.name), el('b', '', format(row)), bar);
      list.append(item);
    });
    if (!rows.length) list.append(el('li', 'empty', '—'));
    box.append(list);
    return box;
  }
  function renderComputer() {
    const root = $('#computer'); if (!root || !ctx) return;
    const latest = ctx.latest(), m = latest && latest.metrics || {}, history = m.history || {};
    const restoreMemoryFocus = document.activeElement?.dataset.memoryAction === 'true';
    root.replaceChildren();
    const head = el('div', 'sheet-head'); head.append(el('h2', '', t('computer')));
    const facts = el('div', 'facts');
    if (m.battery && valid(m.battery.percent)) facts.append(el('span', '', t('battery') + ' ' + Math.round(m.battery.percent) + '%' + (m.battery.charging ? ' · ' + t('charging') : m.battery.plugged ? ' · ' + t('plugged') : '')));
    if (valid(m.uptime_s)) facts.append(el('span', '', t('uptime') + ' ' + duration(m.uptime_s)));
    head.append(facts); root.append(head);

    const gpu = Array.isArray(m.gpus) ? m.gpus[0] || {} : {};
    const used = m.memory && valid(m.memory.total) && m.memory.total > 0 && valid(m.memory.free) ? m.memory.total - m.memory.free : null;
    const grid = el('div', 'gauges');
    const memoryCard = gauge(t('memory'), used === null ? '—' : ctx.size(used).replace(/ (GB|TB)$/, ''), used === null ? '' : ctx.size(used).slice(-2) + ' / ' + ctx.size(m.memory.total), used === null ? null : 100 * used / m.memory.total, history.memory);
    memoryCard.classList.add('gauge-action'); memoryCard.dataset.memoryAction = 'true';
    memoryCard.setAttribute('role', 'button'); memoryCard.setAttribute('tabindex', '0');
    memoryCard.setAttribute('aria-label', t('memory_touch') + '. ' + t('memory_scope'));
    const pcAvailable = Boolean(latest && m.memory);
    if (!pcAvailable) memoryCard.setAttribute('aria-label', t('memory_pc'));
    memoryCard.setAttribute('aria-disabled', String(memoryAction.busy || !pcAvailable));
    const hint = el('div', 'memory-action-hint', pcAvailable ? memoryHint() : t('memory_pc')); hint.setAttribute('aria-live', 'polite');
    const actionRow = el('div', 'memory-action-row'); actionRow.append(hint, el('div', 'memory-action-scope', t('memory_scope')));
    memoryCard.append(actionRow);
    memoryCard.addEventListener('click', () => { if (pcAvailable) releaseMemory(); });
    memoryCard.addEventListener('keydown', (event) => { if (pcAvailable && !event.repeat && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); releaseMemory(); } });
    grid.append(
      gauge('CPU', valid(m.cpu_temp_c) ? String(Math.round(m.cpu_temp_c)) : '—', '°C', m.cpu_percent, history.cpu),
      gauge('GPU', valid(gpu.temp_c) ? String(Math.round(gpu.temp_c)) : '—', '°C', gpu.percent, history.gpu),
      memoryCard);
    root.append(grid);
    if (restoreMemoryFocus) memoryCard.focus({ preventScroll: true });

    const procs = m.processes;
    if (procs && (Array.isArray(procs.cpu) || Array.isArray(procs.memory))) {
      const block = el('section', 'using-block'); block.append(el('h3', 'block-title', t('most_active')));
      const columns = el('div', 'using-columns');
      const cpu = (procs.cpu || []).filter((p) => valid(p.percent)), memory = (procs.memory || []).filter((p) => valid(p.mem_mb));
      const gpus = Array.isArray(procs.gpu) ? procs.gpu.filter((p) => valid(p.percent)) : null;
      columns.append(usingList('CPU', cpu.map((p) => ({ name: p.name, value: p.percent })), (r) => Math.round(r.value * 10) / 10 + '%', Math.max(10, ...cpu.map((p) => p.percent))));
      columns.append(usingList(t('memory'), memory.map((p) => ({ name: p.name, value: p.mem_mb })), (r) => (r.value >= 1024 ? (r.value / 1024).toFixed(1) + ' GB' : Math.round(r.value) + ' MB'), Math.max(1, ...memory.map((p) => p.mem_mb))));
      if (gpus && gpus.length) columns.append(usingList('GPU', gpus.map((p) => ({ name: p.name, value: p.percent })), (r) => Math.round(r.value) + '%', Math.max(10, ...gpus.map((p) => p.percent))));
      block.append(columns); root.append(block);
    }
    if (m.network && (valid(m.network.down_bps) || valid(m.network.up_bps))) {
      const net = el('section', 'network');
      net.append(el('h3', 'block-title', t('network')));
      const row = el('div', 'net-row');
      const down = el('div', 'net'); down.append(el('span', '', '↓ ' + t('down')), el('b', '', rate(m.network.down_bps)), sparkline(history.down));
      const up = el('div', 'net'); up.append(el('span', '', '↑ ' + t('up')), el('b', '', rate(m.network.up_bps)), sparkline(history.up));
      row.append(down, up); net.append(row); root.append(net);
    }
    const disks = el('section', 'disks-block'); disks.append(el('h3', 'block-title', t('disks')));
    const holder = el('div', 'disks'); (Array.isArray(m.disks) ? m.disks : []).forEach((disk) => { if (disk && typeof disk.name === 'string') { const item = ctx.diskItem(disk); if (item) holder.append(item); } });
    if (!holder.childElementCount) holder.append(el('span', 'disk-empty', '—'));
    disks.append(holder); root.append(disks);
    root.append(el('p', 'hint', t('last_hour_note')));
  }

  /* ---- the Small screen page (a remote; the board keeps its own settings in its own control room) */
  const remote = { status: null, loaded: false, busy: false, note: '', noteTimer: 0 };
  const remotePreviews = new Map(), previewQueue = [];
  let previewsLoading = 0;
  const remoteVisible = () => !document.hidden && document.querySelector('#dots [aria-current]')?.dataset.page === 'remote';
  function pumpPreviews() {
    if (!remoteVisible()) return;
    while (previewsLoading < 2 && previewQueue.length) {
      const { index, node } = previewQueue.shift();
      if (!node.isConnected || remotePreviews.get(index)?.node !== node) continue;
      previewsLoading++;
      let finished = false;
      const done = () => { if (!finished) { finished = true; previewsLoading--; pumpPreviews(); } };
      node.addEventListener('load', done, { once: true });
      node.addEventListener('error', () => { node.hidden = true; done(); }, { once: true });
      node.src = '/api/board/preview/' + index + '.png';
    }
  }
  function slotPreview(slot) {
    if (!Number.isInteger(slot.index) || slot.index < 0 || slot.index > 7 || !slot.name) return null;
    const cached = remotePreviews.get(slot.index), now = Date.now();
    if (cached && cached.name === slot.name && now - cached.at < 60000) return cached.node;
    const image = el('img', 'slot-preview');
    image.alt = ''; image.setAttribute('aria-hidden', 'true'); image.draggable = false;
    remotePreviews.set(slot.index, { name: slot.name, at: now, node: image });
    previewQueue.push({ index: slot.index, node: image });
    return image;
  }
  async function loadRemote() {
    try {
      const response = await fetch('/api/board', { cache: 'no-store' });
      if (response.status === 401) { window.location.replace('/login'); return; }
      remote.status = response.ok ? (await response.json()).board || null : null;
    } catch (_) { remote.status = null; }
    remote.loaded = true;
    renderRemote();
  }
  async function sendRemote(name, value) {
    if (remote.busy) return;
    remote.busy = true; renderRemote();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch('/api/board/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: name, value }), cache: 'no-store', signal: controller.signal });
      const result = await response.json().catch(() => ({ ok: false, error: 'unavailable' }));
      if (result.status) remote.status = result.status;
      note(result.ok ? t('sent') : t('err_' + (['invalid', 'busy', 'rejected', 'timeout'].includes(result.error) ? result.error : 'unavailable')));
    } catch (_) { note(t('err_timeout')); }      // no answer in time: the monitor may still carry it out, so it is not called a failure
    finally { clearTimeout(timer); }
    remote.busy = false; renderRemote();
  }
  function note(text) { remote.note = text; clearTimeout(remote.noteTimer); remote.noteTimer = setTimeout(() => { remote.note = ''; renderRemote(); }, 3500); }
  function segmented(options, current, onPick, disabled) {
    const group = el('div', 'segmented'); group.setAttribute('role', 'group');
    options.forEach(([value, label]) => {
      const b = el('button', '', label); b.type = 'button'; b.setAttribute('aria-pressed', String(value === current)); b.disabled = disabled;
      b.addEventListener('click', () => onPick(value)); group.append(b);
    });
    return group;
  }
  function renderRemote() {
    const root = $('#remote'); if (!root || !ctx) return;
    const s = remote.status;
    root.replaceChildren();
    const head = el('div', 'sheet-head'); head.append(el('h2', '', t('remote_title')));
    const state = !remote.loaded ? 'loading' : s ? s.state : 'unavailable';
    const words = { ok: t('connected'), loading: t('connecting'), offline: t('board_offline'), not_configured: t('board_none'), unavailable: t('board_offline') };
    const chip = el('span', 'chip board-state', words[state] || t('board_offline')); chip.dataset.state = state === 'ok' ? 'ok' : 'error';
    const facts = el('div', 'facts'); facts.append(chip); if (s && s.firmware) facts.append(el('span', '', 'FW ' + s.firmware));
    head.append(facts); root.append(head);
    const usable = Boolean(s && state === 'ok'), controls = usable && s.controls !== false, off = !controls || remote.busy;
    if (usable && s.controls === false) root.append(el('p', 'hint', t('board_old')));

    const slots = el('section', 'remote-block'); slots.append(el('h3', 'block-title', t('remote_screen')));
    const grid = el('div', 'slots');
    const list = Array.from({ length: s?.available_slots ?? 8 }, (_, i) =>
      s?.slots?.find(slot => slot.index === i) || { index: i, name: String(i + 1) });
    const mask = Number.isInteger(s?.enabled_pages) ? s.enabled_pages : null;
    list.slice(0, 8).forEach((slot) => {
      const bit = 1 << slot.index, enabled = mask === null || !!(mask & bit);
      const b = el('button', 'slot-button'); b.type = 'button'; b.disabled = off || !enabled; b.setAttribute('aria-pressed', String(s && s.page === slot.index));
      const preview = usable && remoteVisible() ? slotPreview(slot) : null; if (preview) b.append(preview);
      b.append(el('i', '', String(slot.index + 1)), el('span', '', slot.name || String(slot.index + 1)));
      b.addEventListener('click', () => sendRemote('page', slot.index));
      if (mask === null) {
        grid.append(b);
        return;
      }
      const tile = el('div', 'remote-slot'), label = el('label', 'remote-active'), toggle = el('input');
      tile.dataset.inactive = String(!enabled);
      toggle.type = 'checkbox'; toggle.checked = enabled; toggle.disabled = off || mask === bit;
      const title = t('remote_active');
      toggle.setAttribute('aria-label', title + ' · ' + (slot.name || String(slot.index + 1)));
      toggle.addEventListener('change', () => sendRemote('enable', {page:slot.index, enabled:toggle.checked}));
      label.append(toggle, el('span', '', title));
      tile.append(b, label); grid.append(tile);
    });
    slots.append(grid); root.append(slots);
    pumpPreviews();  // at most two local reads; never request pictures on another page

    const rows = el('section', 'remote-block');
    const row = (label, control) => { const r = el('div', 'remote-row'); r.append(el('span', 'remote-label', label), control); return r; };
    rows.append(row(t('remote_rotation'), segmented([[0, t('never')], [30, t('every_30')], [60, t('every_60')]], s ? s.rotation : null, (v) => sendRemote('rotation', v), off)));
    rows.append(row(t('remote_speed'), segmented([[75, t('slower')], [100, t('normal')], [125, t('faster')]], s ? s.speed : null, (v) => sendRemote('speed', v), off)));
    const night = s && s.night;                     // only when the small screen can dim; its schedule is its own
    if (night) {
      rows.append(row(t('remote_night'), segmented([[true, t('on')], [false, t('off')]], night.enabled, (v) => sendRemote('night', { ...night, enabled: v }), off)));
      rows.append(row(t('night_level') + ' · ' + night.level + '%', segmented([[10, '10'], [25, '25'], [50, '50'], [75, '75']], night.level, (v) => sendRemote('night', { ...night, level: v }), off)));
      rows.append(el('p', 'hint', t('night_times') + ' ' + night.start + ' – ' + night.end));
    }
    root.append(rows);
    root.append(el('p', 'hint', remote.note || t('remote_note')));
  }

  /* ---- the settings sheet: rows are described, not written out */
  function get(path) { return path.split('.').reduce((o, k) => (o ? o[k] : undefined), ctx.settings()); }
  function control(row) {
    const value = row.path ? get(row.path) : undefined, id = row.path ? 'set-' + row.path.replace(/\./g, '-') : '';
    if (row.type === 'toggle') {
      const b = el('button', 'switch'); b.type = 'button'; b.id = id; b.setAttribute('role', 'switch'); b.setAttribute('aria-checked', String(Boolean(value)));
      b.append(el('i')); b.addEventListener('click', () => { ctx.setSetting(row.path, !Boolean(get(row.path))); renderSettings(); }); return b;
    }
    if (row.type === 'segmented') {
      return segmented(row.options.map(([v, key]) => [v, t(key)]), value, (v) => { ctx.setSetting(row.path, v); renderSettings(); }, false);
    }
    if (row.type === 'every') {                               // quick choices; the stepper below keeps every five minutes available
      const hour = 'h';                                         // the same letter in English and Spanish
      return segmented([[5, '5'], [15, '15'], [30, '30'], [60, '1 ' + hour], [120, '2 ' + hour], [240, '4 ' + hour]], value, (v) => { ctx.setSetting(row.path, v); renderSettings(); }, false);
    }
    if (row.type === 'pool') {                                // which scenes the automatic mode may show: opens the chooser
      const b = el('button', 'action pool-open', ctx.poolSummary(row.which) + ' ›'); b.type = 'button'; b.addEventListener('click', () => ctx.choosePool(row.which)); return b;
    }
    if (row.type === 'stepper') {
      const box = el('div', 'stepper'), minus = el('button', '', '−'), plus = el('button', '', '+'), shown = el('b', '', value + (row.unit || ''));
      minus.type = plus.type = 'button'; minus.setAttribute('aria-label', '−'); plus.setAttribute('aria-label', '+');
      const move = (dir) => { const next = Math.max(row.min, Math.min(row.max, Math.round((get(row.path) + dir * row.step) * 100) / 100)); ctx.setSetting(row.path, next); renderSettings(); };
      minus.addEventListener('click', () => move(-1)); plus.addEventListener('click', () => move(1)); box.append(minus, shown, plus); return box;
    }
    if (row.type === 'range') {
      const input = el('input'); input.type = 'range'; input.id = id; input.min = row.min; input.max = row.max; input.step = row.step; input.value = value;
      const shown = el('b', '', value + (row.unit || '')); const box = el('div', 'range');
      input.addEventListener('input', () => { shown.textContent = input.value + (row.unit || ''); });
      input.addEventListener('change', () => ctx.setSetting(row.path, Number(input.value)));
      box.append(input, shown); return box;
    }
    if (row.type === 'time') {
      const input = el('input'); input.type = 'time'; input.id = id; input.value = value || '';
      input.addEventListener('change', () => { if (/^\d\d:\d\d$/.test(input.value)) ctx.setSetting(row.path, input.value); }); return input;
    }
    if (row.type === 'number') {
      const input = el('input'); input.type = 'number'; input.id = id; input.step = row.step; input.min = row.min; input.max = row.max; input.value = value;
      input.addEventListener('change', () => { const v = Number(input.value); if (Number.isFinite(v)) ctx.setSetting(row.path, v); }); return input;
    }
    if (row.type === 'button') {
      const b = el('button', 'action', t(row.action)); b.type = 'button'; b.addEventListener('click', () => ctx.action(row.action, b)); return b;
    }
    return el('span');
  }
  const SECTIONS = [
    { title: 'settings_scene', rows: [
      { type: 'segmented', path: 'auto.mode', label: 'scene_mode', options: [['daypart', 'scene_auto_day'], ['rotate', 'scene_auto_rotate']] },
      { type: 'every', path: 'auto.minutes', label: 'auto_every' },
      { type: 'stepper', path: 'auto.minutes', label: 'auto_minutes', min: 5, max: 240, step: 5, unit: ' min' },
      { type: 'pool', which: 'rotate', label: 'pool_rotate' }, { type: 'pool', which: 'dawn', label: 'pool_dawn' }, { type: 'pool', which: 'day', label: 'pool_day' },
      { type: 'pool', which: 'dusk', label: 'pool_dusk' }, { type: 'pool', which: 'night', label: 'pool_night' },
      { type: 'stepper', path: 'photos.seconds', label: 'photo_seconds', min: 5, max: 300, step: 5, unit: ' s' }] },
    { title: 'settings_night', rows: [
      { type: 'toggle', path: 'night.enabled', label: 'night_on' },
      { type: 'time', path: 'night.start', label: 'night_from' }, { type: 'time', path: 'night.end', label: 'night_to' },
      { type: 'range', path: 'night.level', label: 'night_level', min: 5, max: 100, step: 5, unit: '%' },
      { type: 'toggle', path: 'night.clock_only', label: 'night_clock' }] },
    { title: 'settings_sound', rows: [
      { type: 'toggle', path: 'sound.enabled', label: 'sound_on' },
      { type: 'range', path: 'sound.volume', label: 'sound_volume', min: 0, max: 100, step: 10, unit: '%' },
      { type: 'toggle', path: 'sound.at_night', label: 'sound_night' },
      { type: 'stepper', path: 'alerts.quota', label: 'alert_quota', min: 5, max: 30, step: 1, unit: '%' },
      { type: 'stepper', path: 'alerts.disk', label: 'alert_disk', min: 2, max: 15, step: 1, unit: '%' },
      { type: 'toggle', path: 'alerts.resets', label: 'alert_resets' },
      { type: 'button', action: 'sound_test', label: 'sound_test' }] },
    { title: 'settings_motion', rows: [
      { type: 'segmented', path: 'motion', label: 'settings_motion', options: [['auto', 'motion_auto'], ['on', 'motion_on'], ['off', 'motion_off']] }] },
    { title: 'settings_place', rows: [
      { type: 'toggle', path: 'weather.enabled', label: 'weather_on' },
      { type: 'number', path: 'place.lat', label: 'latitude', min: -90, max: 90, step: 0.01 }, { type: 'number', path: 'place.lon', label: 'longitude', min: -180, max: 180, step: 0.01 }] },
  ];
  function renderSettings() {
    const body = $('#settings-body'); if (!body || !ctx) return;
    const scroll = body.scrollTop;
    body.replaceChildren();
    for (const section of SECTIONS) {
      const card = el('section', 'settings-card'); card.append(el('h3', '', t(section.title)));
      for (const row of section.rows) { const r = el('div', 'settings-row'); r.append(el('label', '', t(row.label)), control(row)); card.append(r); }
      body.append(card);
    }
    const app = el('section', 'settings-card'); app.append(el('h3', '', t('settings_app')));
    const info = ctx.appInfo();
    const line = el('div', 'settings-row'); line.append(el('label', '', info.installed ? t('app_version') : t('app_none')), el('b', 'value', info.version || ''));
    app.append(line);
    if (info.offline) {
      const row = el('div', 'settings-row'), status = el('b', 'value'); status.id = 'offline-status'; status.setAttribute('role', 'status');
      row.append(el('label', '', t('local_scenes')), status); app.append(row);
      const details = el('p', 'hint'); details.id = 'offline-details'; app.append(details);
      app.append(el('p', 'hint', t('local_note')));
      const save = el('button', 'action', t('local_save')); save.type = 'button'; save.id = 'offline-save';
      save.addEventListener('click', () => { ctx.saveOffline(); updateOffline(); }); app.append(save);
    }
    if (info.installed && info.update) {
      const row = el('div', 'settings-row'); const b = el('button', 'action', t('app_update_button')); b.type = 'button'; b.addEventListener('click', () => ctx.startAppUpdate());
      row.append(el('label', '', t('app_update_ready') + ' · 1.' + info.update.from + ' → 1.' + info.update.to), b); app.append(row);
    } else if (info.installed && info.apk) { app.append(Object.assign(el('p', 'hint', t('app_up_to_date')))); }
    if (info.apk && !info.installed) { const row = el('div', 'settings-row'); const a = el('a', 'action', t('app_install')); a.href = '/app/ai-desk-tablet.apk'; a.setAttribute('download', ''); row.append(el('label', '', ''), a); app.append(row); }
    body.append(app);
    updateOffline();
    const about = el('section', 'settings-card'); about.append(el('h3', '', t('settings_about')));
    const lang = el('div', 'settings-row'); lang.append(el('label', '', t('language')), segmented([['en', 'English'], ['es', 'Español']], ctx.language(), (v) => ctx.setLanguage(v), false)); about.append(lang);
    about.append(el('p', 'hint', ctx.aboutText())); body.append(about);
    body.scrollTop = scroll;
  }

  function init(context) { ctx = context; }
  function updateOffline() {
    const status = $('#offline-status'); if (!status || !ctx) return;
    const info = ctx.appInfo().offline; if (!info) return;
    const key = info.busy ? 'local_saving' : info.state === 'storage' ? 'local_storage' : info.state === 'sign_in' ? 'local_sign_in' : info.ready ? 'local_ready' : 'local_waiting';
    status.textContent = t(key);
    const details = $('#offline-details');
    if (details) details.textContent = info.count ? info.done + '/' + info.count + ' ' + t('local_files') + ' · ' + availableSize(info.bytes) + ' / ' + availableSize(info.total) : '';
    const save = $('#offline-save'); if (save) save.disabled = Boolean(info.busy);
  }
  const api = { init, renderComputer, renderRemote, renderSettings, updateOffline, loadRemote, sparkline, rate, duration, level };
  global.TabletPanels = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
