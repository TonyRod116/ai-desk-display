import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';

// The weather beside the clock: every code the PC accepts has an icon and words in both languages, unknown is never a number.
const require = createRequire(import.meta.url);
const W = require('../token_tv/tablet_web/weather.js');
const python = readFileSync(new URL('../token_tv/tablet_weather.py', import.meta.url), 'utf8');
const serverCodes = (python.match(/CODES = frozenset\(\(([^)]*)\)\)/)[1].match(/\d+/g) || []).map(Number);

test('the page knows exactly the codes the server accepts', () => {
  assert.equal(serverCodes.length, 28);
  assert.deepEqual([...W.CODES].sort((a, b) => a - b), [...serverCodes].sort((a, b) => a - b));
});

test('every code has an icon that exists, and words in English and Spanish, by day and by night', () => {
  for (const code of W.CODES) {
    for (const language of ['en', 'es']) for (const day of [true, false]) {
      const info = W.describe(code, day, language);
      assert.ok(info, `code ${code}`);
      assert.ok(W.ICONS.includes(info.icon), `icon of ${code}`);
      assert.match(info.text, /^[A-Za-zÁÉÍÓÚáéíóúñ ,]{3,34}$/, `words of ${code}`);
      assert.ok(W.svg(info.icon, day).startsWith('<svg viewBox="0 0 48 48"'), `svg of ${code}`);
    }
  }
});

test('clear weather has its own words at night, the rest keep theirs', () => {
  assert.equal(W.describe(0, true, 'en').text, 'Sunny');
  assert.equal(W.describe(0, false, 'en').text, 'Clear');
  assert.equal(W.describe(0, true, 'es').text, 'Soleado');
  assert.equal(W.describe(0, false, 'es').text, 'Despejado');
  assert.equal(W.describe(61, false, 'es').text, 'Lluvia débil');
  assert.equal(W.describe(3, false, 'en').text, 'Cloudy');
  assert.equal(W.describe(999, true, 'en'), null);
  assert.equal(W.describe('3; alert(1)', true, 'en'), null);
  assert.equal(W.describe('constructor', true, 'en'), null);
});

test('the sun and the moon are drawn for day and night; the other icons need no choice', () => {
  assert.notEqual(W.svg('clear', true), W.svg('clear', false));
  assert.notEqual(W.svg('partly', true), W.svg('partly', false));
  assert.equal(W.svg('rain', true), W.svg('rain', false));
  assert.equal(W.svg('nothing', true), '');
});

test('the markup of every icon is only drawing: no script, no handler, no link, no external reference', () => {
  for (const icon of W.ICONS) for (const day of [true, false]) {
    const markup = W.svg(icon, day);
    const tags = [...markup.matchAll(/<\/?([a-zA-Z]+)/g)].map(m => m[1]);
    for (const tag of tags) assert.ok(['svg', 'g', 'path', 'circle'].includes(tag), `${icon}: <${tag}>`);
    assert.doesNotMatch(markup, /script|on[a-z]+=|href|url\(|http/i);
    assert.doesNotMatch(markup, /NaN|undefined/);
  }
});

test('degrees: whole numbers, a real minus sign, never a made-up value', () => {
  assert.equal(W.degrees(14.4), '14°');
  assert.equal(W.degrees(14.5), '15°');
  assert.equal(W.degrees(-3.6), '−4°');
  assert.equal(W.degrees(-0.2), '0°');
  assert.equal(W.degrees(0), '0°');
  for (const bad of [NaN, Infinity, '14', null, undefined, {}, true]) assert.equal(W.degrees(bad), null);
});

test('the view is null (nothing is shown) for a missing, old, unknown or broken reading', () => {
  const good = {temp: 14, code: 3, day: true, age: 0};
  assert.ok(W.view(good, 'en'));
  assert.equal(W.view(null, 'en'), null);
  assert.equal(W.view(undefined, 'en'), null);
  assert.equal(W.view('14', 'en'), null);
  assert.ok(W.view({...good, age: W.FRESH_SECONDS}, 'en'));
  assert.equal(W.view({...good, age: W.FRESH_SECONDS + 1}, 'en'), null);
  assert.equal(W.view({...good, age: -5}, 'en'), null);
  assert.equal(W.view({...good, age: 'x'}, 'en'), null);
  assert.equal(W.view({...good, temp: null}, 'en'), null);
  assert.equal(W.view({...good, temp: NaN}, 'en'), null);
  assert.equal(W.view({...good, code: 4}, 'en'), null);
});

test('the view carries the icon, the words, the degrees and a spoken label in both languages', () => {
  const en = W.view({temp: -3, code: 71, day: false, age: 30}, 'en');
  assert.deepEqual({icon: en.icon, day: en.day, text: en.text, temp: en.temp}, {icon: 'snow', day: false, text: 'Light snow', temp: '−3°'});
  assert.equal(en.label, 'Weather outside: Light snow, minus 3 degrees');
  const es = W.view({temp: 22, code: 0, day: true}, 'es');
  assert.equal(es.label, 'Tiempo fuera: Soleado, 22 grados');
  assert.equal(es.icon, 'clear');
  assert.equal(W.view({temp: 5, code: 0}, 'en').day, true);               // a reading without the day flag is a day reading
});
