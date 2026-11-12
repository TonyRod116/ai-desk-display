import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';

// Static checks of the tablet page: its word tables, the files it loads and the rule that a disk never writes a percentage.
const web = new URL('../token_tv/tablet_web/', import.meta.url);
const read = name => fs.readFileSync(new URL(name, web), 'utf8');
const app = read('app.js'), html = read('index.html');
const words = (() => {
  const source = app.match(/const words = (\{[\s\S]*?\n  \});/)[1];
  return vm.runInNewContext('(' + source + ')');
})();

test('English and Spanish word tables have exactly the same keys', () => {
  assert.deepEqual(Object.keys(words.es).sort(), Object.keys(words.en).sort());
  for (const language of ['en', 'es']) for (const [key, value] of Object.entries(words[language])) assert.ok(value.length > 1, `${language}.${key}`);
});

test('every word the page asks for by id exists', () => {
  for (const [, key] of html.matchAll(/data-i18n="([a-z_]+)"/g)) assert.ok(key in words.en, key);
  for (const [, key] of app.matchAll(/words\[language\]\.([a-z_]+)/g)) assert.ok(key in words.en, key);
  for (const state of ['on', 'blocked', 'unsupported']) for (const suffix of ['', '_title']) assert.ok(`awake_${state}${suffix}` in words.en);
});

test('the page loads only scripts and styles that exist, with names the server serves', () => {
  const files = [...html.matchAll(/(?:src|href)="\/([^"]+)"/g)].map(m => m[1]).filter(name => /\.(js|css)$/.test(name));
  assert.ok(files.includes('app.js') && files.includes('style.css'));
  for (const name of files) { assert.match(name, /^[a-z0-9-]{1,40}\.(js|css)$/); assert.ok(fs.existsSync(new URL(name, web)), name); }
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>/, 'no inline script (the content policy forbids it)');
  assert.doesNotMatch(html, /https?:\/\//, 'nothing from outside');
});

test('a disk shows its free size, never a percentage', () => {
  const body = app.match(/function diskItem\(disk\) \{[\s\S]*?\n  \}\n/)[0];
  assert.doesNotMatch(body, /showPercent|'%'|"%"|\+ '%|% '/, 'no percentage text in a disk');
  assert.match(body, /cloudSize\(disk\.free\)/);
  assert.match(body, /role', 'group'/);
});

test('free space is coloured at the agreed limits', () => {
  const freeLevel = vm.runInNewContext(app.match(/const (freeLevel = [^\n]+);/)[1] + '; freeLevel');
  const at = value => freeLevel(value);
  assert.deepEqual([4.99, 5, 9.99, 10, 19.99, 20, 80].map(at), ['critical', 'low', 'low', 'warning', 'warning', 'healthy', 'healthy']);
  const quotaLevel = vm.runInNewContext(app.match(/const (quotaLevel = [^\n]+);/)[1] + '; quotaLevel');
  assert.deepEqual([0, 11.99, 12, 24.99, 25, 26, 39.99, 40, 59.99, 60, 100].map(quotaLevel), ['critical', 'critical', 'low', 'low', 'warning', 'warning', 'warning', 'good', 'good', 'healthy', 'healthy'], 'the quota bars change colour step by step: Claude five hours at 26 % is yellow');
});

test('the page cannot scroll: the document is locked and the layout shrinks to fit instead', () => {
  const css = read('style.css');
  assert.match(css, /html, body \{[^}]*overflow: hidden/);
  assert.match(css, /overscroll-behavior: none/, 'no pull-down that would reload the page and leave full screen');
  assert.match(css, /--u: calc\(min\([^;]*var\(--app-h[^;]*\* var\(--fit, 1\)\)/, 'the scale unit follows the measured height and the fit factor');
  assert.match(css, /\.display \{[^}]*height: var\(--app-h/, 'the page is exactly as tall as the visible screen');
  assert.doesNotMatch(css, /min-height: 100d?vh/, 'a page that may grow taller than the screen is a page that scrolls');
  const fit = app.match(/function fit\(\) \{[\s\S]*?\n  \}\n/)[0];
  assert.match(fit, /--app-h/);
  assert.match(fit, /fitPart\(root/, 'the shell has a factor');
  assert.match(fit, /querySelectorAll\('\.page'\)/, 'and so does every page');
  assert.match(app.match(/function fitPart\([^)]*\) \{[\s\S]*?\n  \}\n/)[0], /--fit/);
  assert.match(app.match(/const ratioOf = [^\n]+/)[0], /scrollHeight/, 'overflow is measured on the boxes');
  assert.match(app.match(/const overflowOf = [^\n]+/)[0], /\.page, \.sheet/);
  assert.match(read('style.css'), /\.page \{ --u: calc\(min\([^;]*var\(--fit, 1\)\)/, 'a page redeclares its own scale unit');
  for (const trigger of [/addEventListener\('resize'[^\n]*fit\(\)/, /fullscreenchange[^\n]*fit\(\)/, /orientationchange[^\n]*fit\(\)/]) assert.match(app, trigger);
  assert.match(app.match(/function render\(\) \{[\s\S]*?\n  \}\n/)[0], /fit\(\)/, 'new readings (more disks) fit again');
});

test('what the page reports about itself is only what the server allows, and never a reading', () => {
  const measure = app.match(/function measure\(why\) \{[\s\S]*?\n  \}\n/)[0];
  assert.doesNotMatch(measure, /latest|providers|metrics|password|cookie|localStorage/);
  const server = fs.readFileSync(new URL('../tablet_server.py', web), 'utf8');
  const allowed = new Set(['scene', 'media', 'canvas', 'clip', 'boxes', 'notes']);
  for (const table of ['_REPORT_WORDS', '_REPORT_NUMBERS', '_REPORT_TEXT']) {
    const block = server.match(new RegExp(table + ' = \\{([\\s\\S]*?)\\}\\n')) || server.match(new RegExp(table + ' = \\{([\\s\\S]*?)\\)\\}'));
    for (const [, key] of block[1].matchAll(/'([a-z0-9]+)':/g)) allowed.add(key);
  }
  for (const [, list] of server.matchAll(/_REPORT_(?:FLAGS|BOXES) = \(([^)]*)\)/g)) for (const [, key] of list.matchAll(/'([a-z0-9]+)'/g)) allowed.add(key);
  assert.ok(allowed.has('vw') && allowed.has('renderer') && allowed.has('fs') && allowed.has('dock'), 'the allow-list was read');
  const sent = new Set([...measure.matchAll(/\b([a-z][a-z0-9]*): /g)].map(m => m[1]).concat([...measure.matchAll(/out\.([a-z0-9]+) =/g)].map(m => m[1])));
  for (const key of sent) if (!['status', 'info', 'out', 'node'].includes(key)) assert.ok(allowed.has(key), `the page sends "${key}" but the server drops it`);
});

test('the wake lock is only asked for in full screen and released when it ends', () => {
  const keep = app.match(/async function keepAwake\(\) \{[\s\S]*?\n  \}\n/)[0];
  assert.match(keep, /document\.fullscreenElement/);
  assert.match(keep, /isSecureContext/);
  assert.match(app, /fullscreenchange[^\n]*letSleep/);
});

test('every word the panels and the settings sheet ask for exists in both languages', () => {
  const panels = read('panels.js');
  const keys = new Set([...panels.matchAll(/\bt\('([a-z_0-9]+)'\)/g)].map(m => m[1]));
  for (const [, key] of panels.matchAll(/\b(?:title|label|action): '([a-z_0-9]+)'/g)) keys.add(key);
  for (const [, key] of panels.matchAll(/\['[a-z0-9-]+', '([a-z_0-9]+)'\]/g)) keys.add(key);            // the options of the segmented controls
  assert.ok(keys.size > 40, 'the panels were read');
  for (const key of keys) for (const language of ['en', 'es']) assert.ok(words[language][key], `${language}.${key}`);
  for (const [, key] of app.matchAll(/words\[language\]\['([a-z_]+)'/g)) if (!key.endsWith('_')) assert.ok(words.en[key], key);   // 'awake_' + state is built on the fly
  for (const page of ['home', 'computer', 'remote']) assert.ok(words.en['page_' + page] && words.es['page_' + page], page);
});

test('the page starts from the same settings the server does (the PC keeps the real ones)', () => {
  const python = new URL('../.venv/bin/python', web.href.replace('token_tv/tablet_web/', ''));
  if (!fs.existsSync(python)) return;
  const server = JSON.parse(execFileSync(python.pathname, ['-B', '-c', 'import json; from token_tv.tablet_settings import defaults; print(json.dumps(defaults()))'], {cwd: new URL('..', web.href.replace('tablet_web/', '')).pathname}).toString());
  const page = vm.runInNewContext('(' + app.match(/const DEFAULT_SETTINGS = (\{[\s\S]*?\});\n/)[1] + ')');
  delete server.version;
  assert.deepEqual(page, server);
});

test('the pages, the dots and the details row are in the markup, and the bars carry their parts', () => {
  for (const page of ['home', 'computer', 'remote']) { assert.match(html, new RegExp('id="page-' + page + '"')); assert.match(html, new RegExp('data-page="' + page + '"')); }
  assert.deepEqual([...html.matchAll(/class="meter" data-parts="(\d)"/g)].map(m => m[1]), ['7', '7', '5']);
  for (const id of ['settings-dialog', 'settings-body', 'update', 'toast', 'flash', 'night-shade', 'busy', 'machine', 'intro']) assert.match(html, new RegExp('id="' + id + '"'), id);
  const css = read('style.css');
  assert.match(css, /scroll-snap-type: x mandatory/);
  for (const parts of [5, 7]) assert.match(css, new RegExp('\\.meter\\[data-parts="' + parts + '"\\]::after'));
});

test('a weak GPU (the tablet has a Mali-T860) gets a plain dock, a modern one keeps the glass', () => {
  const weak = vm.runInNewContext(app.match(/const WEAK_GPU = (\/.*\/i);/)[1]);
  for (const name of ['ANGLE (ARM, Mali-T860, OpenGL ES 3.2)', 'ANGLE (ARM, Mali-T720)', 'Adreno (TM) 306', 'PowerVR Rogue']) assert.ok(weak.test(name), name);
  for (const name of ['ANGLE (ARM, Mali-G78 MC14, OpenGL ES 3.2)', 'Adreno (TM) 650', 'ANGLE (Apple, Apple M2)', 'Google SwiftShader']) assert.ok(!weak.test(name), name);
});

test('credits replace a verified exhausted weekly quota only and never invent an unknown balance', () => {
  const source = app.match(/function creditBalance\(data, remaining\) \{[\s\S]*?\n  \}/);
  assert.ok(source, 'the shared page credit selector exists');
  const get = vm.runInNewContext('(' + source[0] + ')');
  assert.equal(get({credits:'2468'},0),'2468');
  assert.equal(get({credits:'0'},0),'0','a real zero balance remains zero');
  assert.equal(get({credits:'?'},0),'?','a missing balance stays unknown');
  assert.equal(get({credits:'<0.01'},0),'<0.01');
  assert.equal(get({credits:'-2.35'},0),'-2.35');
  for(const value of [null,undefined,'','NaN','1e6','12<script>','999999999999999999999']) assert.equal(get({credits:value},0),null,String(value));
  for(const left of [null, 0.001, 1, 50, 100]) assert.equal(get({credits:'2468'},left),null,`weekly left ${left}`);
});
