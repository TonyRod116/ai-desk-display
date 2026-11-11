import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// The page's side of the app update: when it offers one, what it sends to the app, and that a browser or an old app never sees it.
const source = readFileSync(new URL('../token_tv/tablet_web/app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../token_tv/tablet_web/index.html', import.meta.url), 'utf8');
const panels = readFileSync(new URL('../token_tv/tablet_web/panels.js', import.meta.url), 'utf8');
const SHA = 'a05d8d5f13a902efeb6e68d1434986f5c5298dca97378d744827dc551f41ec26';

// Build the page's own functions (appBuild, appUpdate, startAppUpdate, window.aiDeskAppUpdate) around a fake bridge and a fake status.
function page({version = '1.2', app = {version_code: 3, version_name: '1.3', size: 28000, sha256: SHA}, bridge = 'full', answer = 'started'} = {}) {
  const start = source.indexOf('  const appBuild = ');
  const end = source.indexOf('  function alertText(a)');
  assert.ok(start > 0 && end > start, 'the update block is where the test expects it');
  const toasts = [], calls = [];
  const fake = bridge === 'none' ? null : bridge === 'old' ? {version: () => version} : {version: () => version, installUpdate: (sha) => { calls.push(sha); return answer; }};
  const body = source.slice(start, end) + '\n  return {appBuild, appUpdate, startAppUpdate, renderAppUpdate};';
  const window = {};
  const make = new Function('bridge', 'native', 'latest', 'appUpdateChip', 'words', 'language', 'showToast', 'window', body);
  const chip = {hidden: true};
  const words = {en: {app_state_busy: 'busy', app_state_failed: 'failed', app_state_done: 'done', app_state_confirm: 'confirm', app_state_downloading: 'downloading'}};
  const native = (name, ...args) => fake && typeof fake[name] === 'function' ? fake[name](...args) : undefined;
  const api = make(fake, native, app === undefined ? null : {app}, chip, words, 'en', (text, level) => toasts.push([text, level]), window);
  return {...api, chip, toasts, calls, window};
}

test('an update is offered only to the app, only when the PC has a newer build, and only with a real SHA-256', () => {
  assert.deepEqual(page().appUpdate(), {from: 2, to: 3, sha: SHA});
  assert.equal(page({version: '1.3'}).appUpdate(), null);                       // the same build
  assert.equal(page({version: '1.4'}).appUpdate(), null);                       // the app is newer than the PC's file
  assert.equal(page({bridge: 'none'}).appUpdate(), null);                       // a browser
  assert.equal(page({bridge: 'old'}).appUpdate(), null);                        // an app without the door
  assert.equal(page({version: 'garbage'}).appUpdate(), null);
  assert.equal(page({version: '2.1'}).appUpdate(), null);                       // another contract
  assert.equal(page({app: false}).appUpdate(), null);                           // no APK on offer
  assert.equal(page({app: {sha256: SHA}}).appUpdate(), null);                   // no version to compare
  assert.equal(page({app: {version_code: 3.5, sha256: SHA}}).appUpdate(), null);
  assert.equal(page({app: {version_code: '3', sha256: SHA}}).appUpdate(), null);
  for (const bad of ['', 'xyz', SHA.toUpperCase(), SHA.slice(1), SHA + '0', 5]) assert.equal(page({app: {version_code: 3, sha256: bad}}).appUpdate(), null, String(bad));
});

test('the chip shows exactly when an update is offered', () => {
  const on = page(); on.renderAppUpdate(); assert.equal(on.chip.hidden, false);
  const off = page({version: '1.3'}); off.renderAppUpdate(); assert.equal(off.chip.hidden, true);
});

test('a tap sends the hash the PC announced and tells the user when it cannot start', () => {
  const ok = page(); ok.startAppUpdate();
  assert.deepEqual(ok.calls, [SHA]);
  assert.deepEqual(ok.toasts, []);
  const busy = page({answer: 'busy'}); busy.startAppUpdate();
  assert.deepEqual(busy.toasts, [['busy', 'info']]);
  const refused = page({answer: 'invalid'}); refused.startAppUpdate();
  assert.deepEqual(refused.toasts, [['failed', 'warning']]);
  const none = page({version: '1.3'}); none.startAppUpdate();
  assert.deepEqual(none.calls, []);                                             // nothing to update: nothing is sent
});

test('the app answers through one global with fixed words; anything else is ignored', () => {
  const p = page();
  p.window.aiDeskAppUpdate('downloading'); p.window.aiDeskAppUpdate('confirm'); p.window.aiDeskAppUpdate('done'); p.window.aiDeskAppUpdate('failed');
  assert.deepEqual(p.toasts, [['downloading', 'info'], ['confirm', 'info'], ['done', 'info'], ['failed', 'warning']]);
  p.window.aiDeskAppUpdate('<img src=x onerror=alert(1)>'); p.window.aiDeskAppUpdate(undefined); p.window.aiDeskAppUpdate('constructor');
  assert.equal(p.toasts.length, 4);
});

test('the markup and the settings sheet carry the chip and the button, hidden until needed, in both languages', () => {
  assert.match(html, /<button type="button" class="chip chip-button" id="app-update" hidden>/);
  assert.match(source, /app_update:'APP UPDATE'/);
  assert.match(source, /app_update:'ACTUALIZAR APP'/);
  assert.match(source, /app_update_button:'Update the app'/);
  assert.match(source, /app_update_button:'Actualizar la app'/);
  assert.match(panels, /info\.installed && info\.update/);
  assert.match(panels, /ctx\.startAppUpdate\(\)/);
  assert.match(source, /renderAppUpdate\(\);\n      if \(typeof latest\.build === 'string'\)/);
  // the page never builds markup from what the app says
  assert.doesNotMatch(source.slice(source.indexOf('window.aiDeskAppUpdate')), /innerHTML/);
});
