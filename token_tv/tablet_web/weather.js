/* The outside weather beside the clock, as pure functions: a WMO weather code (the PC fetched it, see tablet_weather.py) becomes an icon and
   a few words in English or Spanish, and the temperature becomes "14°". Icons are small inline SVGs drawn here (no files, no network). app.js
   uses them; the Node tests check that every code the server accepts has an icon and words in both languages. Unknown is never a number: a
   reading that is missing or old (`age` over 90 minutes) gives no icon at all. */
(function (global) {
  'use strict';

  const FRESH_SECONDS = 90 * 60;

  /* code -> [icon, English by day, Spanish by day, English by night, Spanish by night]; a night word equal to the day word is left out. */
  const TABLE = {
    0: ['clear', 'Sunny', 'Soleado', 'Clear', 'Despejado'],
    1: ['clear', 'Mostly sunny', 'Poco nuboso', 'Mostly clear', 'Poco nuboso'],
    2: ['partly', 'Partly cloudy', 'Nubes y claros'],
    3: ['cloud', 'Cloudy', 'Nublado'],
    45: ['fog', 'Fog', 'Niebla'], 48: ['fog', 'Freezing fog', 'Niebla helada'],
    51: ['drizzle', 'Light drizzle', 'Llovizna débil'], 53: ['drizzle', 'Drizzle', 'Llovizna'], 55: ['drizzle', 'Heavy drizzle', 'Llovizna fuerte'],
    56: ['drizzle', 'Freezing drizzle', 'Llovizna helada'], 57: ['drizzle', 'Freezing drizzle', 'Llovizna helada'],
    61: ['rain', 'Light rain', 'Lluvia débil'], 63: ['rain', 'Rain', 'Lluvia'], 65: ['heavy', 'Heavy rain', 'Lluvia fuerte'],
    66: ['rain', 'Freezing rain', 'Lluvia helada'], 67: ['heavy', 'Freezing rain', 'Lluvia helada'],
    71: ['snow', 'Light snow', 'Nieve débil'], 73: ['snow', 'Snow', 'Nieve'], 75: ['snow', 'Heavy snow', 'Nieve fuerte'], 77: ['snow', 'Snow grains', 'Nieve granulada'],
    80: ['showers', 'Light showers', 'Chubascos débiles'], 81: ['showers', 'Showers', 'Chubascos'], 82: ['heavy', 'Heavy showers', 'Chubascos fuertes'],
    85: ['snow', 'Snow showers', 'Chubascos de nieve'], 86: ['snow', 'Heavy snow showers', 'Chubascos de nieve fuertes'],
    95: ['storm', 'Thunderstorm', 'Tormenta'], 96: ['storm', 'Thunderstorm and hail', 'Tormenta con granizo'], 99: ['storm', 'Thunderstorm and hail', 'Tormenta con granizo'],
  };
  const CODES = Object.keys(TABLE).map(Number);

  /* Shapes in a 48 x 48 box. Fixed strings: nothing from the network is ever put into the markup, only a key picked from this table. */
  const CLOUD = 'M14 37c-4.7 0-8.5-3.6-8.5-8.1 0-4 3-7.4 7-8 1.2-5.2 5.8-9 11.3-9 5.4 0 9.9 3.7 11 8.7.5-.1 1-.1 1.5-.1 4.4 0 8 3.5 8 7.8 0 4.4-3.6 8-8 8H14z';
  const cloud = (shift = '', fill = '#e6eef5') => `<g transform="${shift}"><path d="${CLOUD}" fill="${fill}"/><path d="M14 37c-4.7 0-8.5-3.6-8.5-8.1 0-.5.1-1 .2-1.500 2 2.600 6 3.800 11 3.800h20c3.700 0 6.700-1.500 7.800-3.800-.6 4.100-4.100 7.600-8 7.600H14z" fill="#9db4c6" opacity=".55"/></g>`;
  const SUN = '#ffcf5a', MOON = '#eef2fa', DROP = '#79c4ff', SNOW = '#ffffff';
  const sun = (cx, cy, r, ray0, ray1) => {
    let rays = '';
    for (let i = 0; i < 8; i++) {
      const a = i * Math.PI / 4, c = Math.cos(a), s = Math.sin(a);
      rays += `M${(cx + c * ray0).toFixed(1)} ${(cy + s * ray0).toFixed(1)}L${(cx + c * ray1).toFixed(1)} ${(cy + s * ray1).toFixed(1)}`;
    }
    return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${SUN}"/><path d="${rays}" stroke="${SUN}" stroke-width="3" stroke-linecap="round" fill="none"/>`;
  };
  const moon = (x, y, k) => `<path transform="translate(${x} ${y}) scale(${k})" d="M26 4C14.500 4 5 13.500 5 25s9.500 21 21 21c6.800 0 12.800-3.200 16.600-8.200C31 41 21.600 32 21.600 21.500c0-6.900 3.700-12.900 9.200-16.200C29.300 4.400 27.700 4 26 4z" fill="${MOON}"/>`;
  const lines = (list, colour, width) => `<path d="${list}" stroke="${colour}" stroke-width="${width}" stroke-linecap="round" fill="none"/>`;
  const UP = 'translate(0 -6)';

  const ICONS = {
    clear: (day) => day ? sun(24, 24, 8.5, 13, 19) : moon(5, 1, .9),
    partly: (day) => (day ? sun(17, 17, 6.5, 10, 14.500) : moon(0, 0, .6)) + cloud('translate(7 8) scale(.84)'),
    cloud: () => cloud('translate(0 2)'),
    fog: () => cloud('translate(8 -9) scale(.7)', '#cfdae3') + lines('M7 30h34M11 37h30M7 44h26', '#cfdae3', 3.200),
    drizzle: () => cloud(UP + ' scale(.95)') + lines('M16 38l-1.500 4M24 38l-1.500 4M32 38l-1.500 4M20 44l-1 3M28 44l-1 3', DROP, 2.600),
    rain: () => cloud(UP + ' scale(.95)') + lines('M15 38l-3 8M24 38l-3 8M33 38l-3 8', DROP, 3),
    heavy: () => cloud(UP + ' scale(.95)', '#c3d0dc') + lines('M12 38l-3 9M19 38l-3 9M26 38l-3 9M33 38l-3 9M40 38l-3 9', DROP, 3.200),
    showers: (day) => (day ? sun(14, 12, 5.200, 8, 11.500) : '') + cloud('translate(5 -3) scale(.88)') + lines('M17 36l-3 8M26 36l-3 8M35 36l-3 8', DROP, 3),
    snow: () => cloud(UP + ' scale(.95)') + `<g fill="${SNOW}"><circle cx="15" cy="41" r="2.300"/><circle cx="24" cy="45" r="2.300"/><circle cx="33" cy="41" r="2.300"/><circle cx="19.500" cy="35.500" r="1.800" opacity="0"/></g>`,
    storm: () => cloud(UP + ' scale(.95)', '#b7c4d1') + `<path d="M26 31l-8 11.500h6l-2.500 7 10-13h-6.500z" fill="${SUN}"/>`,
  };

  function entry(code) { return Object.prototype.hasOwnProperty.call(TABLE, code) ? TABLE[code] : null; }

  /** `{icon, text}` for a WMO code, a day/night flag and 'en' or 'es'; null for a code the page does not know. */
  function describe(code, day, language) {
    const row = entry(code);
    if (!row) return null;
    const es = language === 'es', night = day === false && row.length > 3;
    return { icon: row[0], text: night ? row[es ? 4 : 3] : row[es ? 2 : 1] };
  }

  /** The SVG markup (a fixed string, 48 x 48 box) of an icon key, drawn for day or night. */
  function svg(icon, day) {
    const draw = ICONS[icon];
    if (!draw) return '';
    return `<svg viewBox="0 0 48 48" width="48" height="48" aria-hidden="true" focusable="false">${draw(day !== false)}</svg>`;
  }

  /** "14°", "-3°" with a real minus sign; null when the value is not a finite number. */
  function degrees(temp) {
    if (typeof temp !== 'number' || !Number.isFinite(temp)) return null;
    const whole = Math.round(temp);
    return (whole < 0 ? '−' : '') + Math.abs(whole) + '°';
  }

  /** What to show for the server's `weather` object, or null (show nothing): a known code, a finite temperature and a fresh age. */
  function view(weather, language) {
    if (!weather || typeof weather !== 'object') return null;
    const age = weather.age === undefined ? 0 : weather.age;
    if (typeof age !== 'number' || !(age >= 0) || age > FRESH_SECONDS) return null;
    const shown = degrees(weather.temp), day = weather.day !== false, info = describe(weather.code, day, language);
    if (shown === null || !info) return null;
    const es = language === 'es';
    return { icon: info.icon, day, text: info.text, temp: shown, label: (es ? 'Tiempo fuera: ' : 'Weather outside: ') + info.text + ', ' + shown.replace('−', es ? 'menos ' : 'minus ').replace('°', es ? ' grados' : ' degrees') };
  }

  const api = { CODES, FRESH_SECONDS, describe, svg, degrees, view, ICONS: Object.keys(ICONS) };
  global.TabletWeather = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
