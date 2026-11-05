import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// The dashboard's own wording, chart geometry and saved-reset hearts, run without a browser.
const history = fs.readFileSync(new URL('../token_tv/web/history.js', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../token_tv/web/app.js', import.meta.url), 'utf8');
const NB = String.fromCharCode(0xa0); // the no-break space between a number and its unit
const plain = value => JSON.parse(JSON.stringify(value)); // objects made inside the vm have their own prototypes

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.style = {}; this.className = ''; this.textContent = ''; }
  append(...kids) { this.children.push(...kids); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
}
const document = {createElement: tag => new Node(tag), createElementNS: (_, tag) => new Node(tag)};
const context = {document, Date, Number, Math, offline: false};
vm.createContext(context);
vm.runInContext(history, context);
const pick = pattern => app.match(pattern)[0];
vm.runInContext([
  pick(/const svgNS = [^\n]*\n/), pick(/const el = [^\n]*\n/), pick(/function svgNode\([^\n]*\n/),
  pick(/const RESET_FRESH[^\n]*\n/),
  pick(/function resetReading\(info, unavailable = offline\) \{[\s\S]*?\n\}\n/),
  pick(/function knownResetCount\([^\n]*\n/),
  pick(/function savedHearts\(info, aged = false\) \{[\s\S]*?\n\}\n/),
  pick(/function spanShort\(seconds\) \{[\s\S]*?\n\}\n/),
].join('\n'), context);

test('spans are about, never to the second', () => {
  const cases = [[0, 'less than 5 min'], [299, 'less than 5 min'], [300, `5${NB}min`], [1500, `25${NB}min`], [3300, `55${NB}min`], [3569, `1${NB}h`],
    [7800, `2${NB}h 10${NB}min`], [7199, `2${NB}h`], [35999, `10${NB}h`], [36000, `10${NB}h`], [3600 * 14.2, `14${NB}h`], [3600 * 47, `47${NB}h`],
    [3600 * 48, `2${NB}days`], [86400 * 2 + 3600 * 20, `2${NB}days 20${NB}h`]];
  for (const [seconds, expected] of cases) assert.equal(context.spanText(seconds), expected, String(seconds));
  for (const bad of [NaN, -1, Infinity, undefined, null]) assert.equal(context.spanText(bad), '', String(bad));
});

test('the sentence says "at this pace" and names the window when it is not the week', () => {
  assert.equal(context.forecastSentence({state: 'lasts'}, 'WEEK'), 'At this pace, the week lasts until it resets');
  assert.equal(context.forecastSentence({state: 'lasts'}, '5H'), 'At this pace, the 5-hour window lasts until it resets');
  assert.equal(context.forecastSentence({state: 'runs_out', seconds: 7800}, '5H'), `At this pace, the 5-hour window runs out in about 2${NB}h 10${NB}min`);
  assert.equal(context.forecastSentence({state: 'runs_out', seconds: 86400 * 3}, 'WEEK'), `At this pace, the week runs out in about 3${NB}days`);
  assert.equal(context.forecastSentence({state: 'runs_out', seconds: 90}, '5H'), 'At this pace, the 5-hour window runs out in less than 5 min');
  for (const nothing of [null, undefined]) assert.equal(context.forecastSentence(nothing, 'WEEK'), '');
  assert.equal(context.forecastSentence({state: 'runs_out', seconds: NaN}, 'WEEK'), '');
  for (const text of [context.forecastSentence({state: 'lasts'}, 'WEEK'), context.forecastSentence({state: 'runs_out', seconds: 600}, '5H')])
    assert.match(text, /^At this pace, /);
});

test('the window that runs out first is the one worth saying', () => {
  const lasts = {forecast: {state: 'lasts', seconds: null}}, soon = s => ({forecast: {state: 'runs_out', seconds: s}});
  const both = ['WEEK', '5H'];
  assert.equal(context.pickForecast({WEEK: lasts, '5H': soon(900)}, both).label, '5H');
  assert.equal(context.pickForecast({WEEK: soon(900), '5H': soon(5000)}, both).label, 'WEEK');
  assert.equal(context.pickForecast({WEEK: lasts, '5H': lasts}, both).label, 'WEEK');
  assert.equal(context.pickForecast({'5H': lasts}, both).label, '5H');
  assert.equal(context.pickForecast({WEEK: lasts, '5H': soon(900)}, ['WEEK']).label, 'WEEK');          // the card does not show the five hours: neither does the forecast
  assert.equal(context.pickForecast({WEEK: {forecast: null}, '5H': {forecast: null}}, both), null);    // thin evidence or flat usage: nothing
  assert.equal(context.pickForecast({WEEK: lasts}, []), null);                                       // no known reading on the card
  assert.equal(context.pickForecast(undefined, both), null);
});

test('the chart keeps gaps as gaps and puts the pace where it belongs', () => {
  const window = (segments, forecast) => ({resets_at: 1000, length: 1000, segments, forecast});
  const runs = context.chartShape(window([[[0, 0], [500, 50]]], {state: 'runs_out', at: 750, seconds: 250, end_used: 100}), true);
  assert.deepEqual(plain([runs.lines, runs.areas]), [['M0 0L50 50'], ['M0 0L50 50L50 100L0 100Z']]);
  assert.deepEqual(plain(runs.end), {x: 50, y: 50, t: 500, used: 50});
  assert.deepEqual([runs.ahead.x, runs.ahead.y, runs.ahead.reaches, runs.ahead.d], [75, 100, true, 'M50 50L75 100']);
  const lasts = context.chartShape(window([[[0, 0], [500, 50]]], {state: 'lasts', at: null, seconds: null, end_used: 80}), true);
  assert.deepEqual([lasts.ahead.x, lasts.ahead.y, lasts.ahead.reaches], [100, 80, false]);
  const broken = context.chartShape(window([[[0, 10], [100, 12]], [[600, 30], [700, 31]]], null), true);
  assert.equal(broken.lines.length, 2);                                                           // an outage is two lines, never one joined across it
  assert.equal(broken.ahead, null);
  assert.deepEqual(plain(context.chartShape(window([[[200, 5]]], null), true).lone), [{x: 20, y: 5}]);
  assert.deepEqual(plain(context.chartShape(window([], null), true).lines), []);
  const used = context.chartShape(window([[[0, 0], [500, 50]]], null), false);                    // "used" plots the other way up
  assert.equal(used.lines[0], 'M0 100L50 50');
  assert.deepEqual(plain(context.chartPoints(window([[[0, 1]], [[5, 2], [6, 3]]], null)).map(p => p.used)), [1, 2, 3]);
});

const hearts = (info, aged) => { context.__info = info; return vm.runInContext('savedHearts(__info, ' + Boolean(aged) + ')', context); };
const parts = h => ({svgs: h.children.filter(c => c.tag === 'svg'), dots: h.children.filter(c => c.tag === 'i' && c.className === 'hearts-dot'), words: h.children.filter(c => c.tag === 'span').map(c => c.textContent)});

test('unknown saved resets are three faint hearts and one discreet dot, never a question mark', () => {
  for (const info of [null, undefined, {available: null, source: 'unknown'}, {available: 'many', source: 'user_confirmed', confirmed_at: Date.now() / 1000}]) {
    const h = hearts(info), {svgs, dots, words} = parts(h);
    assert.equal(svgs.length, 3);
    assert.ok(svgs.every(s => s.dataset.filled === 'false'));
    assert.equal(dots.length, 1);
    assert.deepEqual(words, []);
    assert.equal(h.attrs['aria-label'], 'Saved-reset balance unknown');
    assert.equal(dots[0].attrs['aria-hidden'], 'true');
  }
  assert.ok(!/known \? '\+' : '\?'/.test(app), 'the question mark is gone from the source');
});

test('a known count keeps its hearts, with a dot only when the reading is a few minutes old', () => {
  const now = Date.now() / 1000, info = count => ({available: count, source: 'user_confirmed', confirmed_at: now - 5});
  let h = hearts(info(2));
  assert.deepEqual([parts(h).svgs.filter(s => s.dataset.filled === 'true').length, parts(h).dots.length, h.attrs['aria-label']], [2, 0, '2 saved resets']);
  assert.match(h.title, /confirmed by you/);
  h = hearts(info(0));                                                                             // zero is three faint hearts and no dot: it is known
  assert.deepEqual([parts(h).svgs.filter(s => s.dataset.filled === 'true').length, parts(h).dots.length, h.attrs['aria-label']], [0, 0, '0 saved resets']);
  h = hearts(info(2), true);
  assert.deepEqual([parts(h).svgs.filter(s => s.dataset.filled === 'true').length, parts(h).dots.length], [2, 1]);
  h = hearts(info(5));
  assert.deepEqual(parts(h).words, ['+']);
  const old = {available: 2, source: 'claude_web', confirmed_at: now - 600, valid_until: now + 86400};   // an automatic count past 180 s keeps its hearts and gets the dot
  assert.equal(parts(hearts(old)).dots.length, 1);
  assert.equal(parts(hearts(old)).svgs.filter(s => s.dataset.filled === 'true').length, 2);
  const gone = {available: 2, source: 'claude_web', confirmed_at: now - 72 * 3600 - 60, valid_until: now + 86400};   // past 72 h it is unknown
  assert.equal(parts(hearts(gone)).dots.length, 1);
  assert.ok(parts(hearts(gone)).svgs.every(s => s.dataset.filled === 'false'));
});

test('ages are written the way a person says them', () => {
  const cases = [[0, '0 s'], [40, '40 s'], [99, '99 s'], [100, '2 min'], [3000, '50 min'], [3600 + 300, '1 h 5 min'], [3 * 3600, '3 h'], [50 * 3600, '2 days']];
  for (const [seconds, expected] of cases) assert.equal(context.spanShort(seconds), expected, String(seconds));
});
