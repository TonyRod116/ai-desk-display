import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Exercise the actual picture-mode handlers with a controllable clock and
// pointer/click events. Browser QA separately checks actual touch dispatch.
const source = readFileSync(new URL('../token_tv/tablet_web/app.js', import.meta.url), 'utf8');
const start = source.indexOf('  // In picture mode horizontal swipes select scenes.');
const end = source.indexOf('  /* The pages:', start);
assert.ok(start > 0 && end > start, 'picture gesture handlers exist');

function harness() {
  const listeners = new Map(), clock = {now: 1000}, calls = {opened: 0, chosen: [], exited: 0};
  const timers = new Map(); let timerId = 0;
  const setTimer = (fn, delay) => { const id = ++timerId; timers.set(id, {fn, at: clock.now + delay}); return id; };
  const clearTimer = id => timers.delete(id);
  function advance(ms) {
    const end = clock.now + ms;
    for (;;) {
      const due = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]); clock.now = due[1].at; due[1].fn();
    }
    clock.now = end;
  }
  const clockTarget = {}, sceneTarget = {};
  const intro = {contains: target => target === clockTarget};
  const page = {clientWidth: 600, addEventListener(type, fn, capture = false) {
    const handlers = listeners.get(type) || [];
    handlers.push({fn, capture: capture === true || capture?.capture === true});
    listeners.set(type, handlers);
  }};
  const body = `let pictureMode = true, photos = [], availableScenes = ['city', 'surf'], photoMode = false, selectedScene = 'city';
    const sceneDialog = {open: false};
    function setPicture(on) { pictureMode = on; resetPictureTouches(); if (!on) calls.exited++; }
    function showScenes() { calls.opened++; sceneDialog.open = true; }
    function chooseScene(value) { calls.chosen.push(value); }
    ${source.slice(start, end)}
    return {setMode(on) { pictureMode = on; resetPictureTouches(); }, mode() { return pictureMode; }, setDialog(on) { sceneDialog.open = on; }};`;
  const api = new Function('$', 'intro', 'performance', 'setTimeout', 'clearTimeout', 'calls', body)(
    () => page, intro, {now: () => clock.now}, setTimer, clearTimer, calls);
  function event(type, id = 1, x = 100, y = 100, extras = {}) {
    const ev = {pointerType: 'touch', pointerId: id, isPrimary: id === 1, button: 0, clientX: x, clientY: y,
      target: sceneTarget, detail: 1, prevented: false, stopped: false,
      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }, ...extras};
    const handlers = [...(listeners.get(type) || [])].sort((a, b) => Number(b.capture) - Number(a.capture));
    for (const {fn} of handlers) { fn(ev); if (ev.stopped) break; }
    return ev;
  }
  function tap({target = sceneTarget, x = 100, y = 100, pointerType = 'touch'} = {}) {
    event('pointerdown', 1, x, y, {target, pointerType}); advance(65);
    event('pointerup', 1, x, y, {target, pointerType});
    const click = event('click', 1, x, y, {target});
    if (target === clockTarget && !click.stopped) api.setMode(!api.mode());
    advance(110); return click;
  }
  return {event, tap, advance, clock, calls, clockTarget, sceneTarget, ...api};
}

test('two nearby taps open the scene picker once in picture mode', () => {
  const h = harness(); h.tap(); assert.equal(h.calls.opened, 0); h.tap();
  assert.equal(h.calls.opened, 1); assert.equal(h.mode(), true);
  h.setDialog(false); h.setMode(false); h.tap(); h.tap(); assert.equal(h.calls.opened, 1);
  h.setMode(true); h.tap(); h.setMode(false); h.setMode(true); h.tap(); assert.equal(h.calls.opened, 1);
});

test('the clock supports both a double tap and the existing single-tap exit', () => {
  const h = harness(); h.tap({target: h.clockTarget}); assert.equal(h.mode(), true, 'wait for a possible second tap');
  h.tap({target: h.clockTarget}); h.advance(750);
  assert.equal(h.calls.opened, 1); assert.equal(h.mode(), true); assert.equal(h.calls.exited, 0);
  const single = harness(); single.tap({target: single.clockTarget}); single.advance(750);
  assert.equal(single.mode(), false); assert.equal(single.calls.opened, 0); assert.equal(single.calls.exited, 1);
});

test('a mouse double click works and a keyboard click is not intercepted', () => {
  const h = harness(); h.tap({pointerType: 'mouse'}); h.tap({pointerType: 'mouse'}); assert.equal(h.calls.opened, 1);
  const keyboard = harness().event('click', 1, 100, 100, {detail: 0});
  assert.equal(keyboard.prevented, false); assert.equal(keyboard.stopped, false);
});

test('slow or distant taps, extra fingers and cancelled gestures do not open the picker', () => {
  const slow = harness(); slow.tap(); slow.advance(1000); slow.tap(); assert.equal(slow.calls.opened, 0);
  const far = harness(); far.tap({x: 100}); far.tap({x: 300}); assert.equal(far.calls.opened, 0);
  const multi = harness();
  multi.event('pointerdown', 1); multi.event('pointerdown', 2, 125, 100);
  multi.event('pointerup', 1); multi.event('pointerup', 2, 125, 100);
  assert.equal(multi.event('click').prevented, true); multi.advance(1000); multi.tap(); assert.equal(multi.calls.opened, 0);
  const cancel = harness(); cancel.tap(); cancel.event('pointerdown'); cancel.event('pointercancel'); cancel.tap(); assert.equal(cancel.calls.opened, 0);
});

test('a horizontal swipe still changes scene and cannot count as a double tap', () => {
  const h = harness(); h.tap(); h.event('pointerdown', 1, 400, 200); h.event('pointermove', 1, 120, 200); h.event('pointerup', 1, 120, 200);
  assert.deepEqual(h.calls.chosen, ['surf']);
  assert.equal(h.event('click').prevented, true, 'the swipe does not click the clock');
  h.advance(800); h.tap(); assert.equal(h.calls.opened, 0);
});
