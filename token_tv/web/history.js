'use strict';
/* History and forecast on the usage page (web only; the board never shows a forecast).
 * The numbers come from GET /history. This file words them and draws one quiet chart in inline SVG:
 * the line of the current window, a dashed continuation "at this pace", and nothing where there is no reading. */

/* "2 h 10 min", "40 min", "14 h", "2 days 20 h": about, never to the second. */
function spanText(seconds) {
 const NB = '\u00a0'; // a number and its unit stay on one line
 if (!Number.isFinite(seconds) || seconds < 0) return '';
 if (seconds < 300) return 'less than 5 min';
 const m = Math.round(seconds / 300) * 5; // minutes, to the nearest five
 if (m < 60) return `${m}${NB}min`;
 if (seconds < 36000) {
  const h = Math.floor(m / 60);
  return m % 60 ? `${h}${NB}h ${m % 60}${NB}min` : `${h}${NB}h`;
 }
 const hours = Math.round(seconds / 3600);
 if (hours < 48) return `${hours}${NB}h`;
 const days = Math.floor(hours / 24), rest = hours % 24;
 return `${days}${NB}days${rest ? ` ${rest}${NB}h` : ''}`;
}

/* The one sentence. It always says "at this pace", and it names the window when it is not the week. */
function forecastSentence(forecast, label) {
 const what = label === '5H' ? 'the 5-hour window' : 'the week';
 if (!forecast) return '';
 if (forecast.state === 'lasts') return `At this pace, ${what} lasts until it resets`;
 const about = spanText(forecast.seconds);
 return about ? `At this pace, ${what} runs out in ${about === 'less than 5 min' ? '' : 'about '}${about}` : '';
}

/* Which window to talk about: the one that runs out first, else the week, else the five hours.
 * `windows` is one provider's part of /history; `known` lists the labels the card really shows. */
function pickForecast(windows, known) {
 const found = ['WEEK', '5H'].filter(l => windows?.[l]?.forecast && known.includes(l)).map(l => ({label: l, ...windows[l]}));
 const running = found.filter(w => w.forecast.state === 'runs_out').sort((a, b) => a.forecast.seconds - b.forecast.seconds);
 return running[0] || found[0] || null;
}

/* Geometry in a 100 x 100 box (x: 0 = start of the window, 100 = its reset; y: 0 = top). `remaining` plots what is left,
 * so the line falls toward the floor as quota is used. Gaps in the readings stay gaps: one path per unbroken part. */
function chartShape(win, remaining) {
 const start = win.resets_at - win.length, x = t => Math.max(0, Math.min(100, (t - start) / win.length * 100));
 const y = used => (remaining ? used : 100 - used);
 const fix = n => Math.round(n * 100) / 100;
 const parts = (win.segments || []).filter(s => s.length);
 const lines = parts.map(s => s.map(([t, u], i) => `${i ? 'L' : 'M'}${fix(x(t))} ${fix(y(u))}`).join(''));
 const areas = parts.filter(s => s.length > 1).map(s => `${s.map(([t, u], i) => `${i ? 'L' : 'M'}${fix(x(t))} ${fix(y(u))}`).join('')}L${fix(x(s.at(-1)[0]))} 100L${fix(x(s[0][0]))} 100Z`);
 const lone = parts.filter(s => s.length === 1).map(s => ({x: fix(x(s[0][0])), y: fix(y(s[0][1]))}));
 const lastPart = parts.at(-1), last = lastPart ? lastPart.at(-1) : null;
 const end = last ? {x: fix(x(last[0])), y: fix(y(last[1])), t: last[0], used: last[1]} : null;
 let ahead = null;
 const f = win.forecast;
 if (end && f) {
  ahead = f.state === 'lasts' ? {x: 100, y: fix(y(f.end_used)), reaches: false} : {x: fix(x(f.at)), y: remaining ? 100 : 0, reaches: true};
  ahead.d = `M${end.x} ${end.y}L${ahead.x} ${ahead.y}`;
 }
 return {lines, areas, lone, end, ahead, start};
}

/* All the points of the chart, oldest first, for the hover readout and the keyboard. */
function chartPoints(win) {return (win.segments || []).flat().map(([t, used]) => ({t, used}))}

const HISTORY_SVG = 'http://www.w3.org/2000/svg';
function historyNode(tag, attrs, svg) {
 const n = svg ? document.createElementNS(HISTORY_SVG, tag) : document.createElement(tag);
 for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
 return n;
}
function historyTime(epoch, label) {
 const d = new Date(epoch * 1000), locale = document.documentElement.lang === 'es' ? 'es-ES' : 'en-GB';
 const clock = d.toLocaleTimeString(locale, {hour: '2-digit', minute: '2-digit'});
 return label === 'WEEK' ? `${d.toLocaleDateString(locale, {weekday: 'short'})} ${clock}` : clock;
}

/* One chart: the figure, its caption and a table for screen readers. It is built once per data set and kept
 * between the dashboard's five-second redraws, so a hover or a focus survives them. */
function historyFigure(picked, {remaining, name, provider}) {
 const win = picked, label = picked.label;
 const shape = chartShape(win, remaining), points = chartPoints(win);
 const figure = historyNode('figure');
 figure.className = 'history-figure';
 const plot = historyNode('div'); plot.className = 'history-plot'; plot.tabIndex = 0; plot.dataset.provider = provider || '';
 plot.setAttribute('role', 'img');
 const what = label === '5H' ? '5-hour window' : 'week';
 plot.setAttribute('aria-label', `${name} ${what}: quota ${remaining ? 'left' : 'used'} so far, with the pace continued to the reset. Use the arrow keys to read points.`);
 const svg = historyNode('svg', {viewBox: '0 0 100 100', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false'}, true);
 svg.setAttribute('class', 'history-svg');
 for (const level of [0, 100]) svg.append(historyNode('path', {d: `M0 ${level}H100`, class: 'history-grid', 'vector-effect': 'non-scaling-stroke'}, true));
 for (const d of shape.areas) svg.append(historyNode('path', {d, class: 'history-area'}, true));
 if (shape.ahead) svg.append(historyNode('path', {d: shape.ahead.d, class: 'history-ahead', 'vector-effect': 'non-scaling-stroke'}, true));
 for (const d of shape.lines) svg.append(historyNode('path', {d, class: 'history-line', 'vector-effect': 'non-scaling-stroke'}, true));
 plot.append(svg);
 const dot = (cls, p) => {const n = historyNode('i'); n.className = cls; n.style.left = p.x + '%'; n.style.top = p.y + '%'; n.setAttribute('aria-hidden', 'true'); plot.append(n); return n};
 for (const p of shape.lone) dot('history-dot', p);
 if (shape.end) dot('history-dot history-now', shape.end);
 if (shape.ahead?.reaches) dot('history-stop', shape.ahead);
 const cursor = historyNode('i'); cursor.className = 'history-cursor'; cursor.hidden = true; cursor.setAttribute('aria-hidden', 'true');
 const readout = historyNode('span'); readout.className = 'history-readout'; readout.hidden = true; readout.setAttribute('aria-hidden', 'true');
 const live = historyNode('span'); live.className = 'visually-hidden'; live.setAttribute('aria-live', 'polite');
 plot.append(cursor, readout, live);
 let index = -1;
 const hide = () => {cursor.hidden = readout.hidden = true};
 const show = i => {
  const p = points[i];
  if (!p) return hide();
  index = i;
  const x = Math.max(0, Math.min(100, (p.t - shape.start) / win.length * 100));
  cursor.style.left = x + '%'; readout.style.left = x + '%'; readout.dataset.side = x < 25 ? 'start' : x > 75 ? 'end' : 'mid';
  readout.textContent = `${Math.round(remaining ? 100 - p.used : p.used)}% ${remaining ? 'left' : 'used'} · ${historyTime(p.t, label)}`;
  cursor.hidden = readout.hidden = false;
 };
 const nearest = clientX => {
  const box = plot.getBoundingClientRect(), t = shape.start + (clientX - box.left) / Math.max(1, box.width) * win.length;
  let best = -1, gap = Infinity;
  points.forEach((p, i) => {const d = Math.abs(p.t - t); if (d < gap) {gap = d; best = i}});
  return best;
 };
 plot.addEventListener('pointermove', e => show(nearest(e.clientX)));
 plot.addEventListener('pointerleave', () => {if (document.activeElement !== plot) hide()});
 plot.addEventListener('focus', () => show(index >= 0 ? index : points.length - 1));
 plot.addEventListener('blur', hide);
 plot.addEventListener('keydown', e => {
  const move = {ArrowLeft: -1, ArrowRight: 1, Home: -Infinity, End: Infinity}[e.key];
  if (move !== undefined) {
   e.preventDefault();
   const from = index < 0 ? points.length - 1 : index;
   show(Math.max(0, Math.min(points.length - 1, move === -Infinity ? 0 : move === Infinity ? points.length - 1 : from + move)));
   live.textContent = readout.textContent;
  } else if (e.key === 'Escape') hide();
 });
 const table = historyNode('table'); table.className = 'visually-hidden';
 const cap = historyNode('caption'); cap.textContent = `${name} ${what}, readings so far`;
 const head = historyNode('tr'); for (const h of ['Time', remaining ? 'Quota left' : 'Quota used']) {const th = historyNode('th'); th.scope = 'col'; th.textContent = h; head.append(th)}
 table.append(cap, head);
 const step = Math.max(1, Math.ceil(points.length / 12));
 for (const p of points.filter((_, i) => i % step === 0 || i === points.length - 1)) {
  const row = historyNode('tr'), a = historyNode('td'), b = historyNode('td');
  a.textContent = historyTime(p.t, label); b.textContent = `${Math.round(remaining ? 100 - p.used : p.used)}%`; row.append(a, b); table.append(row);
 }
 figure.append(plot, table);
 return figure;
}
