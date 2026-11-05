'use strict';
/* Local dashboard: the appearance changes, the account data stays the same. */
const PERSONAL_THEMES = [
 {id:'game-boy', name:'Game Boy Green', eyebrow:'LOCAL DASHBOARD', title:'USAGE DASHBOARD', note:'Hearts: saved resets · Bar: remaining quota', remaining:true},
 {id:'game-boy-pocket', name:'Game Boy Pocket', eyebrow:'POCKET · LOCAL DASHBOARD', title:'USAGE DASHBOARD', note:'Hearts: saved resets · Bar: remaining quota', remaining:true},
 {id:'retro', name:'Pixel Retro', eyebrow:'', title:'AI PROVIDERS', note:'REMAINING QUOTA', remaining:true},
 {id:'amber-terminal', name:'Amber Terminal', eyebrow:'LOCAL DASHBOARD', title:'QUOTA / TERMINAL', note:'Remaining quota and saved resets', remaining:true},
 {id:'orbit', name:'Orbit', eyebrow:'LOCAL DASHBOARD', title:'ORBIT', note:'Remaining quota and saved resets', remaining:true}
];
const THEMES = PERSONAL_THEMES;
const SCENE_THEME = {id:'scene', eyebrow:'LOCAL DASHBOARD', title:'USAGE DASHBOARD', note:'Hearts: saved resets · Bar: remaining quota', remaining:true};
const themeConfig = id => id === 'scene' ? SCENE_THEME : THEMES.find(t => t.id === id);
const STATUS = {loading:'Loading', auth_required:'Login needed', identity_mismatch:'Check identity', quota_unavailable:'Quota unavailable', usage_blocked:'Blocked by Codex', stale:'OLD · Previous value', rate_limited:'Retry later', error:'Fetch failed'};
const PROVIDERS = ['codex', 'claude', 'grok'];
const COMPANIES = {claude:'ANTHROPIC', codex:'OPENAI', grok:'XAI'};
const svgNS = 'http://www.w3.org/2000/svg';
const $ = s => document.querySelector(s);
const readPreference = (k, f) => {try {return JSON.parse(localStorage.getItem(k)) ?? f} catch {return f}};
const savePreference = (k, v) => {try {localStorage.setItem(k, JSON.stringify(v))} catch {/* Private browsing may disallow storage. */}};
let accountChoices = readPreference('tokentv.accounts', {});
if (!accountChoices || typeof accountChoices !== 'object' || Array.isArray(accountChoices)) accountChoices = {};
// The static demo (scripts/build_demo.py) serves sample data and pre-rendered clock frames.
const DEMO = document.documentElement.hasAttribute('data-demo');
let snapshot = null, offline = false, polling = false, displayInfo = null, displayOffline = false;
let historyData = null, historyAt = 0, historyPolling = false; // GET /history: web only, never the board
let selectedScene = readPreference('ai-desk-display.dashboard-scene', null);
if (typeof selectedScene !== 'string' || !/^[a-z0-9-]+$/.test(selectedScene)) selectedScene = null;
const el = (tag, text, cls) => {const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n};
function svgNode(tag, attrs) {const n = document.createElementNS(svgNS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n}
const clamp = v => Math.max(0, Math.min(100, v));
/* Unlit seven-segment cells behind Digital numerals: every glyph cell becomes 8. */
const ghost = text => text.replace(/[^\s:]/g, '8');
const pad = n => String(n).padStart(2, '0');
function seeded(seed) {return () => {seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296}}

/* Provider marks: vector glyphs for most themes, the project's pixel mascots for Pixel Retro. */
function icon(provider) {
 const s = svgNode('svg', {viewBox:'0 0 48 48', 'aria-hidden':'true', fill:'none', stroke:'currentColor', 'stroke-linecap':'round', 'stroke-linejoin':'round', class:'glyph'});
 if (provider === 'claude') {
  const reach = [19.5, 15, 18, 14, 19, 15.5, 18.5, 14, 19.5, 15, 18, 14.5];
  reach.forEach((r, i) => s.append(svgNode('path', {d:`M24 ${24 - 6} V${24 - r}`, 'stroke-width':3.4, transform:`rotate(${i * 30 + (i % 2 ? 4 : 0)} 24 24)`})));
 } else if (provider === 'codex') {
  s.append(svgNode('path', {d:'M24 5 40.5 14.5V33.5L24 43 7.5 33.5V14.5Z', 'stroke-width':3.2}));
  s.append(svgNode('path', {d:'M7.5 14.5 24 24 40.5 14.5M24 24V43', 'stroke-width':3.2}));
 } else {
  s.append(svgNode('circle', {cx:24, cy:24, r:12.5, 'stroke-width':3.4}));
  s.append(svgNode('path', {d:'M5 43C17 33 31 19 43 5 34 19 21 32 5 43Z', fill:'currentColor', stroke:'currentColor', 'stroke-width':1.6}));
 }
 return s;
}
function mascot(provider) {const img = el('img', undefined, 'pixel-mascot'); img.src = `/assets/${provider}-pixel.png`; img.alt = ''; img.width = 32; img.height = 32; img.decoding = 'async'; return img}
function clockGlyph() {
 const s = svgNode('svg', {viewBox:'0 0 24 24', 'aria-hidden':'true', fill:'none', stroke:'currentColor', 'stroke-width':1.8, 'stroke-linecap':'round', class:'clock-icon'});
 s.append(svgNode('circle', {cx:12, cy:12, r:9}), svgNode('path', {d:'M12 7.5V12l3 2'}));
 const p = svgNode('svg', {viewBox:'0 0 9 9', 'aria-hidden':'true', 'shape-rendering':'crispEdges', class:'clock-pixel'});
 for (const [x, y, w, h, c] of [[2,0,5,1,'o'],[1,1,1,1,'o'],[7,1,1,1,'o'],[0,2,1,5,'o'],[8,2,1,5,'o'],[1,7,1,1,'o'],[7,7,1,1,'o'],[2,8,5,1,'o'],[1,2,7,5,'f'],[2,1,5,1,'f'],[2,7,5,1,'f'],[4,2,1,3,'o'],[5,4,2,1,'o']])
  p.append(svgNode('rect', c === 'o' ? {x, y, width:w, height:h, fill:'currentColor'} : {x, y, width:w, height:h, fill:'#fff3d6', class:'face'}));
 const wrap = el('span', undefined, 'clock-mark'); wrap.setAttribute('aria-hidden', 'true'); wrap.append(s, p); return wrap;
}

/* Pixel Retro scenery on a 200×62 logical grid, anchored bottom-right. Sky objects sit
 * near x≈138 so they fall between the title row and the score column. */
function scene(provider) {
 const W = 200, H = 62, rnd = seeded({claude:11, codex:23, grok:37}[provider]);
 const s = svgNode('svg', {viewBox:`0 0 ${W} ${H}`, preserveAspectRatio:'xMaxYMax slice', 'shape-rendering':'crispEdges', class:'scene', 'aria-hidden':'true'});
 const rect = (x, y, w, h, fill, cls) => {const r = svgNode('rect', {x, y, width:w, height:h, fill}); if (cls) r.setAttribute('class', cls); s.append(r)};
 const bands = colors => colors.forEach((c, i) => rect(0, Math.floor(i * H / colors.length), W, Math.ceil(H / colors.length) + 1, c));
 const ridge = (f, fill) => {let d = `M0 ${H}`; for (let x = 0; x < W; x += 2) d += `V${Math.round(f(x))}H${x + 2}`; s.append(svgNode('path', {d:d + `V${H}Z`, fill}))};
 const disc = (cx, cy, r, fill) => {for (let dy = -r; dy <= r; dy++) {const w = Math.round(Math.sqrt(r * r - dy * dy)); rect(cx - w, cy + dy, 2 * w + 1, 1, fill)}};
 const pine = (x, base, h, fill) => {for (let i = 0; i < h; i++) {const w = 1 + 2 * Math.floor(i / 2); rect(x - Math.floor(w / 2), base - h + i, w, 1, fill)} rect(x, base, 1, 2, fill)};
 const stars = (n, x0, y1, colors) => {for (let i = 0; i < n; i++) rect(x0 + Math.floor(rnd() * (W - x0)), Math.floor(rnd() * y1), 1, 1, colors[i % colors.length], i % 3 ? '' : 'twinkle')};
 if (provider === 'claude') {
  bands(['#2a1330', '#3a1834', '#4d1f36', '#652836', '#7f3335', '#9a4133', '#b65231', '#cf6630']);
  disc(138, 15, 9, '#ff9e4f'); disc(138, 15, 7, '#ffc067'); disc(138, 14, 4, '#ffe08f');
  for (const y of [17, 20, 23]) rect(128, y, 21, 1, '#4d1f36');
  for (const [x, y] of [[112, 24], [119, 21], [126, 27]]) {rect(x, y, 1, 1, '#2a1330'); rect(x + 1, y + 1, 1, 1, '#2a1330'); rect(x + 2, y, 1, 1, '#2a1330')}
  ridge(x => 41 - 9 * Math.max(0, Math.sin((x - 40) / 18)) - 3 * Math.sin(x / 6) - (x > 150 ? 5 * Math.max(0, Math.sin((x - 150) / 10)) : 0), '#5a2236');
  ridge(x => 49 - 3 * Math.sin(x / 9 + 1) - 2 * Math.sin(x / 4), '#371428');
  for (const x of [152, 158, 163, 182, 188, 194]) pine(x, 52, 7 + (x % 3), '#24101e');
 } else if (provider === 'codex') {
  bands(['#06171d', '#082027', '#0b2a2e', '#0e3434', '#113f39', '#15493e', '#195443', '#1e6048']);
  stars(30, 40, 26, ['#9bffd2', '#e6fff3']);
  disc(137, 11, 5, '#d9ffe9'); disc(139, 10, 4, '#082027');
  let x = 52;
  while (x < W) {const w = 6 + Math.floor(rnd() * 7), h = 10 + Math.floor(rnd() * 13); rect(x, 52 - h, w, h + 10, '#0b3530'); for (let wy = 54 - h; wy < 50; wy += 3) for (let wx = x + 1; wx < x + w - 1; wx += 2) if (rnd() > .55) rect(wx, wy, 1, 1, rnd() > .7 ? '#e8ffa6' : '#7dffb9'); x += w + 2}
  for (let p = 0; p < W; p += 5) pine(p + 2, 58, 6 + Math.floor(rnd() * 5), '#05201a');
  for (let i = 0; i < 9; i++) rect(60 + Math.floor(rnd() * 138), 38 + Math.floor(rnd() * 12), 1, 1, '#c8ff8a', 'twinkle');
 } else {
  bands(['#0d0a28', '#120d33', '#170f3e', '#1c1349', '#211654', '#271a5f', '#2d1e6a', '#33226f']);
  stars(80, 0, 46, ['#efe6ff', '#b9a6ff', '#ffffff']);
  disc(140, 15, 8, '#8f6cf2'); disc(138, 13, 6, '#a98bff'); disc(136, 11, 2, '#cdbbff');
  for (let i = -15; i <= 15; i++) rect(140 + i, 16 + Math.round(-i * .28), 1, 1, Math.abs(i) < 8 ? '#e2d6ff' : '#bca8ff');
  disc(108, 26, 2, '#d9cff7');
  ridge(x => 50 - 4 * Math.abs(Math.sin(x / 13)) - 2 * Math.sin(x / 5), '#120c33');
  ridge(x => 56 - 2 * Math.abs(Math.sin(x / 8 + 2)), '#0a0722');
  for (const [cx, cy] of [[120, 58], [150, 59], [184, 58]]) rect(cx, cy, 3, 1, '#1d1550');
 }
 return s;
}
function buildStarfield() {
 const rnd = seeded(5), s = svgNode('svg', {viewBox:'0 0 480 300', preserveAspectRatio:'xMidYMid slice', 'shape-rendering':'crispEdges'});
 for (let i = 0; i < 140; i++) {const big = i % 17 === 0, r = svgNode('rect', {x:Math.floor(rnd() * 480), y:Math.floor(rnd() * 300), width:big ? 2 : 1, height:big ? 2 : 1, fill:['#ffffff', '#b9c8ff', '#ffe9a8'][i % 3]}); if (i % 4 === 0) r.setAttribute('class', 'twinkle'); r.style.animationDelay = (-rnd() * 4).toFixed(2) + 's'; s.append(r)}
 $('#starfield').append(s);
}
function resetTime(epoch) {if (!Number.isFinite(epoch) || epoch <= 0) return '—'; let m = Math.ceil((epoch - Date.now() / 1000) / 60); if (m <= 0) return 'Awaiting reset'; return m >= 1440 ? `${Math.floor(m / 1440)}d ${Math.floor(m % 1440 / 60)}h` : `${Math.floor(m / 60)}h ${pad(m % 60)}m`}
function period(w) {if (!w) return 'QUOTA'; return w.label === 'BUDGET' ? 'CLI BUDGET' : w.label === 'WEEK' ? 'WEEKLY' : w.label === '5H' ? '5-HOUR' : String(w.label || 'QUOTA')}
function level(v) {return v < 50 ? 'low' : v < 80 ? 'medium' : v < 90 ? 'high' : 'critical'}
function levelText(v) {return v >= 100 ? 'Limit reached' : v >= 90 ? 'Near limit' : v >= 80 ? 'High usage' : v >= 50 ? 'Moderate' : 'Low usage'}
function gauge(value, label, used = value) {
 const g = el('div', undefined, 'meter');
 if (Number.isFinite(value)) {value = clamp(value); g.dataset.level = level(used); g.style.setProperty('--value', value + '%'); g.style.setProperty('--v', String(Math.max(1, value))); g.setAttribute('role', 'meter'); g.setAttribute('aria-label', label); g.setAttribute('aria-valuemin', '0'); g.setAttribute('aria-valuemax', '100'); g.setAttribute('aria-valuenow', String(value))}
 else {g.classList.add('unknown-meter'); g.setAttribute('aria-label', label + ' unavailable')}
 for (let i = 0; i < 10; i++) {const seg = el('span', undefined, 'meter-segment'), fill = el('span', undefined, 'meter-fill'); seg.style.setProperty('--i', String(i)); fill.style.setProperty('--fill', Number.isFinite(value) ? clamp((value - i * 10) * 10) + '%' : '0%'); seg.append(fill); g.append(seg)}
 return g;
}

// An automatic count is current for 3 minutes; after that it stays, marked old by the discreet dot, for up to 72 hours (Tony,
// 2026-10-20: "the last known count when old"). The same tiers as token_tv/reset_balances.py, which keeps it as `last_known`.
const RESET_FRESH = 180, RESET_LAST_KNOWN = 72 * 3600;
function resetReading(info, unavailable = offline) {
 const kept = info?.available == null && Number.isInteger(info?.last_known);
 const count = kept ? info.last_known : info?.available, age = Date.now() / 1000 - info?.confirmed_at;
 const timed = kept || ['codex_cli','claude_web'].includes(info?.source), until = info?.valid_until;
 const expired = timed && (unavailable || !Number.isFinite(info.confirmed_at) || !Number.isFinite(age) || age < -60 || age > RESET_LAST_KNOWN
  || until != null && (!Number.isFinite(until) || until <= Date.now() / 1000)
  || info.source === 'claude_web' && count > 0 && !Number.isFinite(until));
 return expired || !Number.isInteger(count) || count < 0 ? {count: null, old: false} : {count, old: timed && age > RESET_FRESH};
}
function knownResetCount(info, unavailable = offline) {return resetReading(info, unavailable).count}
/* Three hearts, one per available saved reset. Unknown is three faint hearts and one discreet dot, as on the board;
 * an old count, or a reading a few minutes old, keeps its count and gets the same dot. Never a question mark, never zero. */
function savedHearts(info, aged = false) {
 const {count, old} = resetReading(info), known = count !== null;
 const hearts = el('span', undefined, 'saved-hearts');
 const label = known ? `${count} saved resets` + (old ? ' · checked a few minutes ago' : '') : 'Saved-reset balance unknown';
 hearts.setAttribute('role', 'img'); hearts.setAttribute('aria-label', label);
 hearts.title = label + (info?.source === 'user_confirmed' ? ' · confirmed by you' : '');
 for (let i = 0; i < 3; i++) {
  const filled = known && count > i;
  const s = svgNode('svg', {viewBox:'0 0 7 6', 'aria-hidden':'true', 'shape-rendering':'crispEdges'});
  s.append(svgNode('path', {d:'M1 0h2v1h1V0h2v1h1v2H6v1H5v1H4v1H3V5H2V4H1V3H0V1h1Z', fill:filled ? 'currentColor' : 'none', stroke:'currentColor', 'stroke-width':filled ? 0 : .75}));
  s.dataset.filled = String(filled); hearts.append(s);
 }
 if (known && count > 3) hearts.append(el('span', '+'));
 if (!known || aged || old) {const dot = el('i', undefined, 'hearts-dot'); dot.setAttribute('aria-hidden', 'true'); hearts.append(dot)}
 return hearts;
}

function visibleWindows(a) {
 let windows = (a.windows || []).filter(w => Number.isFinite(w.used_percent));
 if (a.status === 'identity_mismatch') return [];
 if (['claude_official_cli', 'claude_official_statusline', 'claude_browser', 'codex_official_cli'].includes(a.quota_origin)) {
  const now = Date.now() / 1000, age = now - a.fetched_at;
  // A rolled-over Claude five-hour window is unknown; the weekly one has its own reset.
  if (a.quota_origin.startsWith('claude_')) windows = windows.filter(w => w.label === 'WEEK' || (Number.isFinite(w.resets_at) && w.resets_at > now));
  // Tony, 2026-11-03: the number stays up to 480 s (the monitor marks it `reading_aged` after 180 s); older is unknown.
  if (offline || a.status !== 'ok' || !Number.isFinite(a.fetched_at) || !Number.isFinite(age) || age < -60 || age > 480
      || !windows.some(w => w.label === 'WEEK') || windows.some(w => !Number.isFinite(w.resets_at) || w.resets_at <= now)) return [];
  if (a.quota_origin === 'codex_official_cli' && a.ordinary_usage_allowed !== true) {
   windows = a.ordinary_usage_allowed === false ? windows.filter(w => w.label === 'WEEK' && w.used_percent === 100) : [];
  }
 }
 return windows;
}

// Balance is a decimal string from the verified official reader, never a
// floating-point quota percentage. Keep tiny positive balances visible.
function formatCredits(value) {
 if (typeof value !== 'string' || value.length < 1 || value.length > 24) return '?';
 const text = value.trim();
 if (!/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return '?';
 const negative = text.startsWith('-');
 let [integer, fraction = ''] = (negative ? text.slice(1) : text).split('.');
 integer = (integer || '0').replace(/^0+(?=\d)/, '');
 fraction = fraction.replace(/0+$/, '');
 if (fraction.length > 10 || integer.length > 10 || Number(integer) > 1000000000 || (Number(integer) === 1000000000 && fraction)) return '?';
 const nonzero = Number(integer) !== 0 || /[1-9]/.test(fraction);
 if (!nonzero) return '0';
 if (Number(integer) === 0 && Number((fraction + '00').slice(0, 2)) === 0) return (negative ? '-' : '') + '<0.01';
 const decimals = fraction.slice(0, 2).replace(/0+$/, '');
 return (negative ? '-' : '') + integer + (decimals ? '.' + decimals : '');
}
function exhaustedBalance(a, primary) {
 if (offline || a.provider !== 'codex' || a.status !== 'ok' || a.identity_verified !== true ||
     a.quota_origin !== 'codex_official_cli' || !primary || primary.label !== 'WEEK' || primary.used_percent !== 100) return null;
 return formatCredits(a.credits_balance);
}

function setTheme(theme) {
 const config = (theme !== 'scene' || selectedScene && !DEMO ? themeConfig(theme) : null) || THEMES[0];
 document.documentElement.dataset.theme = config.id; savePreference('tokentv.theme', config.id);
 $('#eyebrow').textContent = config.eyebrow; $('#eyebrow').hidden = !config.eyebrow;
 $('#page-title').textContent = config.title;
 $('#intro-note').textContent = config.note; $('#intro-note').hidden = !config.note;
 for (const b of document.querySelectorAll('[data-theme-choice]')) b.setAttribute('aria-pressed', String(b.dataset.themeChoice === config.id));
 const libraryButton = $('#scene-browse');
 if (libraryButton) libraryButton.setAttribute('aria-pressed', String(config.id === 'scene'));
 $('#dashboard-scene').hidden = config.id !== 'scene';
 if (config.id === 'scene') refreshScene(); else clearScene();
 renderAccounts();
}
for (const t of THEMES) {
 const b = el('button', undefined, 'theme-button'); b.type = 'button'; b.dataset.themeChoice = t.id; b.setAttribute('aria-pressed', 'false');
 const sw = el('span', undefined, 'swatch'); sw.dataset.swatch = t.id; sw.setAttribute('aria-hidden', 'true'); sw.append(el('i'), el('i'), el('i'));
 b.append(sw, el('span', t.name, 'theme-name')); b.onclick = () => setTheme(t.id); $('#themes').append(b);
}
/* How old a reading is, in the words a person uses: "just now", "40 s", "2 min", "1 h 5 min". */
function spanShort(seconds) {
 const s = Math.max(0, Math.round(seconds));
 if (s < 100) return `${s} s`;
 const m = Math.round(s / 60);
 if (m < 60) return `${m} min`;
 const h = Math.floor(m / 60);
 return h < 48 ? `${h} h${m % 60 ? ` ${m % 60} min` : ''}` : `${Math.floor(h / 24)} days`;
}
const ageText = (label, epoch) => Date.now() / 1000 - epoch < 5 ? `${label} just now` : `${label} ${spanShort(Date.now() / 1000 - epoch)} ago`;
const clockText = epoch => new Date(epoch * 1000).toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'});

/* One more window of the same account, shown beside the week: the five hours stop work first. */
function windowLine(a, w, remaining) {
 const v = remaining ? clamp(100 - w.used_percent) : w.used_percent, name = period(w);
 const line = el('div', undefined, 'window-detail'), left = resetTime(w.resets_at), timer = el('span', undefined, 'window-timer');
 if (/^[\ddh ]+m?$/.test(left) && left !== '—') timer.append(el('span', 'resets in', 'window-timer-label'), ' ', el('span', left, 'window-timer-value'));
 else timer.append(left);
 line.append(el('span', name + (remaining ? ' LEFT' : ' USED'), 'window-name'), gauge(v, a.alias + ' ' + name + (remaining ? ' remaining quota' : ' used quota'), w.used_percent), el('span', Math.round(v) + '%', 'window-percent'), timer);
 return line;
}

/* The saved-reset counter's own reader (the browser extension), when the monitor reports it. */
function bankReader(provider) {
 const info = (snapshot?.display?.saved_resets || displayInfo?.saved_resets)?.[provider];
 return info?.reader && typeof info.reader === 'object' ? info.reader : null;
}

/* The chart and its one sentence, only while the reading itself is known and the history has something to say. */
function historyBlock(provider, accounts, a, windows, remaining) {
 if (DEMO || offline || a.status !== 'ok' || a.reading_aged === true || accounts.length !== 1 || !historyData || Date.now() / 1000 - historyData.now > 300) return null;
 const picked = pickForecast(historyData.windows?.[provider], windows.map(w => w.label));
 if (!picked) return null;
 // The answer is a minute old at most: count the time to 100% down from the moment it predicts, not from when it was asked.
 const ahead = picked.forecast.state === 'runs_out' ? {...picked.forecast, seconds:Math.max(0, picked.forecast.at - Date.now() / 1000)} : picked.forecast;
 const sentence = forecastSentence(ahead, picked.label);
 if (!sentence) return null;
 const block = el('div', undefined, 'history'); block.dataset.window = picked.label; block.dataset.state = picked.forecast.state;
 const key = [provider, picked.label, historyData.now, remaining, document.documentElement.lang].join('|');
 let kept = historyFigures.get(provider);
 if (kept?.key !== key) {kept = {key, node:historyFigure(picked, {remaining, name:a.alias, provider})}; historyFigures.set(provider, kept)}
 const words = el('p', undefined, 'history-sentence'), lead = sentence.match(/^(At this pace,)(.*)$/);
 if (lead) words.append(el('span', lead[1], 'history-lead'), lead[2]); else words.textContent = sentence;
 block.append(words, kept.node);
 return block;
}
const historyFigures = new Map(); // the chart is kept between redraws, so hovering or focusing it survives them

/* What went wrong, in order of what a person can do about it. Nothing at all when everything is fine. */
function cardFoot(provider, a, primary, stale, aged, reader, failing) {
 const foot = el('div', undefined, 'card-foot'), now = Date.now() / 1000;
 const checked = stale ? a.last_success_at : a.fetched_at;
 if (offline) foot.append(el('span', 'Offline · previous value', 'foot-age'));
 else if (primary && Number.isFinite(checked) && checked > 0) {
  const when = el('time', ageText(stale ? 'Last good' : 'Checked', checked), 'foot-age'), d = new Date(checked * 1000);
  when.dateTime = d.toISOString(); when.title = d.toLocaleString('en-GB');
  if (aged) {when.dataset.aged = 'true'; const dot = el('i', undefined, 'age-dot'); dot.setAttribute('aria-hidden', 'true'); when.append(dot)}
  foot.append(when);
  if (a.quota_origin === 'claude_browser') foot.append(el('span', 'Browser backup · claude.ai', 'foot-retry'));
 } else if (failing && Number.isFinite(reader.since) && reader.since > 0) foot.append(el('span', `No reading for ${spanShort(now - reader.since)}`, 'foot-age'));
 if (failing && Number.isFinite(reader.retry_at) && reader.retry_at > now) foot.append(el('span', `Next try in ${spanShort(reader.retry_at - now)}`, 'foot-retry'));
 const notes = [];
 if (failing && primary) notes.push(typeof reader.text === 'string' && reader.text ? reader.text : 'The quota reader is not updating.');
 const bank = provider === 'claude' ? bankReader(provider) : null;
 if (bank?.state === 'failing') notes.push((typeof bank.text === 'string' && bank.text ? bank.text : 'The saved-reset counter is not updating.') + (Number.isFinite(bank.last_delivery) && bank.last_delivery > 0 ? ` Last update ${clockText(bank.last_delivery)}.` : ''));
 if (!reader && !['ok', 'quota_unavailable', 'stale'].includes(a.status) && STATUS[a.status]) notes.push(STATUS[a.status]);
 for (const text of notes) {
  const note = el('p', undefined, 'foot-note'), mark = el('span', undefined, 'note-mark'); mark.setAttribute('aria-hidden', 'true');
  note.append(mark, el('span', text)); foot.append(note);
 }
 return foot.children.length ? foot : null;
}

function providerCard(provider, accounts) {
 const remaining = Boolean(themeConfig(document.documentElement.dataset.theme)?.remaining);
 let a = accounts.find(x => x.key === accountChoices[provider]) || accounts[0];
 if (!a) a = {key:provider, alias:provider.toUpperCase(), provider, status:'loading', windows:[]};
 const stale = offline || a.status === 'stale';
 const windows = visibleWindows(a);
 const candidates = remaining && ['claude', 'codex'].includes(provider) ? windows.filter(w => w.label === 'WEEK') : windows;
 const primary = candidates.reduce((p, w) => !p || w.used_percent > p.used_percent ? w : p, null);
 const value = primary ? clamp(remaining ? 100 - primary.used_percent : primary.used_percent) : null;
 const credits = exhaustedBalance(a, primary);
 const aged = a.reading_aged === true && Boolean(primary);
 const reader = a.reader && typeof a.reader === 'object' ? a.reader : null, failing = reader?.state === 'failing';
 const shell = el('div', undefined, 'card-shell'); shell.dataset.provider = provider;
 const card = el('article', undefined, 'provider-card');
 Object.assign(card.dataset, {provider, key:a.key, stale:String(stale), aged:String(aged), level:primary ? level(primary.used_percent) : 'unknown', credits:String(credits !== null)});
 const art = el('div', undefined, 'card-art'); art.setAttribute('aria-hidden', 'true'); art.append(scene(provider));
 const head = el('div', undefined, 'card-head'), logo = el('div', undefined, 'provider-icon'); logo.append(icon(provider), mascot(provider));
 const name = el('div', undefined, 'provider-name'); name.append(el('h2', provider.toUpperCase(), 'provider-title'), el('span', COMPANIES[provider], 'company'));
 if (remaining) name.append(savedHearts(a.status === 'identity_mismatch' ? null : a.banked_resets, aged));
 const tabs = el('div', undefined, 'account-tabs'); tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', provider.toUpperCase() + ' accounts');
 for (const row of accounts) {const letter = (row.alias || '').split(' ').at(-1); const b = el('button', letter, 'account-tab'); b.type = 'button'; b.dataset.account = row.key; b.title = row.alias; b.setAttribute('aria-label', row.alias); b.setAttribute('aria-pressed', String(row.key === a.key)); b.onclick = () => {accountChoices[provider] = row.key; savePreference('tokentv.accounts', accountChoices); renderAccounts(); $(`[data-account="${row.key}"]`)?.focus()}; tabs.append(b)}
 tabs.hidden = remaining && accounts.length <= 1;
 head.append(logo, name, tabs);
 const reading = el('div', undefined, 'reading'), meta = el('div', undefined, 'reading-meta');
 meta.append(el('span', credits !== null ? 'EXTRA CREDITS' : period(primary) + (remaining ? ' LEFT' : ' USED'), 'reading-label'));
 if (credits !== null) meta.append(el('span', credits === '?' ? 'Balance unavailable' : 'Weekly limit reached', 'level-label'));
 else if (primary) meta.append(el('span', stale ? 'OLD · Last known usage' : levelText(primary.used_percent), 'level-label'));
 else meta.append(el('span', failing && typeof reader.text === 'string' && reader.text ? reader.text :
  ['claude_official_cli', 'claude_official_statusline', 'claude_browser', 'codex_official_cli'].includes(a.quota_origin) ?
  'No recent weekly reading. Retrying automatically.' :
  a.status === 'quota_unavailable' && a.source === 'local' && provider === 'claude' ?
  'No current local Claude reading. This page does not refresh the Claude Code reader.' :
  a.status === 'quota_unavailable' ? 'No quota reported.' : STATUS[a.status] || 'No reading available.', 'unknown-message'));
 const num = el('div', credits !== null ? credits : value === null ? '—' : undefined, 'percentage');
 if (credits === null && value !== null) {const digits = el('span', String(Math.round(value)), 'pct-num'); digits.dataset.ghost = ghost(digits.textContent); num.append(digits, el('span', '%', 'percent-sign'))}
 num.style.setProperty('--quota', (value ?? 0) + '%');
 reading.append(meta, num);
 const timer = el('div', undefined, 'timer'), until = el('span', primary ? resetTime(primary.resets_at) : '—', 'timer-value');
 if (/^[\ddh ]+$/.test(until.textContent)) until.dataset.ghost = ghost(until.textContent);
 timer.append(clockGlyph(), el('span', 'RESETS IN', 'timer-label'), until);
 const row = el('div', undefined, 'gauge'); row.append(gauge(value, a.alias + ' ' + period(primary) + (remaining ? ' remaining quota' : ' used quota'), primary?.used_percent), el('span', value === null ? '—' : Math.round(value) + '%', 'gauge-value'));
 card.append(art, head, reading, timer, row);
 const more = el('div', undefined, 'more-windows');
 for (const w of windows.filter(w => w !== primary)) more.append(windowLine(a, w, remaining));
 const block = primary ? historyBlock(provider, accounts, a, windows, remaining) : null;
 if (block) more.append(block);
 if (more.children.length) card.append(more);
 const foot = cardFoot(provider, a, primary, stale, aged, reader, failing);
 if (foot) card.append(foot);
 card.dataset.foot = String(Boolean(foot));
 shell.append(card); return shell;
}
function renderAccounts() {
 paintSavedResets();
 if (!snapshot) return;
 const focused = document.activeElement?.dataset?.account, plot = document.activeElement?.classList?.contains('history-plot') ? document.activeElement.dataset.provider : null;
 const rows = Object.values(snapshot.accounts || {}), fragment = document.createDocumentFragment();
 const used = PROVIDERS.filter(p => rows.some(a => a.provider === p)); // only services that are set up
 for (const provider of used.length ? used : PROVIDERS) fragment.append(providerCard(provider, rows.filter(a => a.provider === provider)));
 $('#providers').replaceChildren(fragment);
 if (focused) {const b = [...document.querySelectorAll('[data-account]')].find(b => b.dataset.account === focused); b?.focus({preventScroll:true})}
 if (plot) document.querySelector(`.history-plot[data-provider="${plot}"]`)?.focus({preventScroll:true});
}
/* Demo data stores resets as seconds from now so the timers stay plausible on any day. */
function demoSnapshot(data) {
 const now = Date.now() / 1000;
 for (const a of Object.values(data.accounts)) {a.fetched_at = a.last_success_at = now; for (const w of a.windows) w.resets_at = now + w.resets_in}
 return {...data, updated_at: now};
}
async function update() {
 if (polling) return; polling = true;
 const wasOffline = offline;
 try {
  const r = await fetch(DEMO ? '/demo-snapshot.json' : '/snapshot', {cache:'no-store', signal:AbortSignal.timeout(4000)}); if (!r.ok) throw Error();
  const data = DEMO ? demoSnapshot(await r.json()) : await r.json(); if (!data.accounts || !Number.isFinite(data.updated_at)) throw Error();
  snapshot = data; offline = false;
  const staleCount = Object.values(data.accounts).filter(a => a.status === 'stale').length;
  $('#connection').textContent = DEMO ? 'Demo · sample data' : staleCount ? `${staleCount} stale · Live server` : 'Live';
  $('#notice').hidden = !staleCount; $('#notice').textContent = staleCount + ' account' + (staleCount === 1 ? ' has' : 's have') + ' an older reading. Check the selected account’s source and last successful update.';
 } catch {
  offline = true; $('#connection').textContent = 'Server offline'; $('#notice').hidden = false;
  $('#notice').textContent = snapshot ? 'Local connection lost. Official quotas remain unknown until readings recover.' : 'Cannot reach the local monitor. Is it running?';
  if (!snapshot) $('#providers').replaceChildren(el('p', 'No usage data received.', 'loading'));
 } finally {
  polling = false; document.body.dataset.offline = String(offline); renderAccounts();
  if (!offline && Date.now() - historyAt > 55000) refreshHistory();
  if (document.documentElement.dataset.theme === 'scene') {
   if (offline) showSceneOffline();
   else if (wasOffline) refreshScene();
  }
  if (offline && library.open) pauseLibrary('Local connection lost. Waiting for current readings.');
 }
}
function showClock(show) {$('#clock-panel').hidden = !show; $('#clock-toggle').setAttribute('aria-expanded', String(show)); if (show) {refreshDisplay(); $('#close-clock').focus()} else $('#clock-toggle').focus()}
$('#clock-toggle').onclick = () => showClock($('#clock-panel').hidden); $('#close-clock').onclick = () => showClock(false);
function paintSavedResets() {
 const form = $('#saved-resets-form'); form.hidden = DEMO;
 if (!displayInfo || DEMO) return;
 for (const provider of ['codex','claude']) {
  const input = $('#resets-' + provider), info = displayInfo.saved_resets?.[provider];
  const automatic = displayInfo.automatic_reset_providers?.includes(provider);
  const count = automatic && info?.source !== {codex:'codex_cli',claude:'claude_web'}[provider] && info?.source !== 'claude_not_eligible' ? null : knownResetCount(info, offline || displayOffline);
  input.readOnly = Boolean(automatic);
  if (automatic || (document.activeElement !== input && !input.dataset.dirty)) input.value = count ?? '';
  $('#resets-' + provider + '-source').textContent = automatic ?
   count !== null ? 'Official check: ' + new Date(info.confirmed_at * 1000).toLocaleString('en-GB') : 'Official check pending or unavailable.' :
   count !== null && info?.confirmed_at ? 'Confirmed by you: ' + new Date(info.confirmed_at * 1000).toLocaleString('en-GB') : 'Balance awaiting confirmation.';
 }
}
for (const provider of ['codex','claude']) $('#resets-' + provider).oninput = e => {e.target.dataset.dirty = 'true'};
$('#saved-resets-form').onsubmit = async e => {
 e.preventDefault();
 try {
  for (const provider of ['codex','claude']) {
   const input = $('#resets-' + provider); if (input.readOnly) continue;
   const available = input.value === '' ? null : Number(input.value);
   if (available !== null && (!Number.isInteger(available) || available < 0 || available > 999)) throw Error();
   const response = await fetch('/display/resets', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({provider,available})});
   if (!response.ok) throw Error();
   displayInfo = await response.json(); displayOffline = false; delete input.dataset.dirty;
  }
  $('#saved-resets-status').textContent = 'Balance saved locally. No reset was used.';
  paintSavedResets();
 } catch {$('#saved-resets-status').textContent = 'Could not save. Check the values and try again.'}
};
let displayPolling = false;
async function refreshDisplay() {
 if (displayPolling) return;
 displayPolling = true;
 try {
  const r = await fetch(DEMO ? '/demo-display.json' : '/display', {cache:'no-store', signal:AbortSignal.timeout(4000)});
  if (!r.ok) throw Error();
  displayInfo = await r.json(); displayOffline = false;
 } catch {displayOffline = true}
 finally {displayPolling = false; paintSavedResets()}
}
/* Numbers for the chart. A failed or stalled request clears them: nothing is better than an old forecast. */
async function refreshHistory() {
 if (DEMO || historyPolling) return;
 historyPolling = true;
 try {
  const r = await fetch('/history', {cache:'no-store', signal:AbortSignal.timeout(4000)});
  if (!r.ok) throw Error();
  const data = await r.json();
  if (!data || typeof data.windows !== 'object' || !Number.isFinite(data.now)) throw Error();
  historyData = data;
 } catch {historyData = null}
 finally {historyPolling = false; historyAt = Date.now(); renderAccounts()}
}
/* Screen previews are rendered by the local service; opening this library never
 * changes a device setting or polls the physical board. */
const library = $('#screen-library'), libraryContent = $('#library-content');
let sceneImage = $('#scene-image');
const sceneMessage = $('#scene-message');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let catalogPromise = null, sceneEpoch = 0, sceneLoading = false, sceneUpdatedAt = 0;
let libraryEpoch = 0, libraryQueue = [], libraryBusy = false, libraryObserver = null;
let libraryOpenedAt = 0, libraryPaused = false;

async function getCatalog() {
 if (!catalogPromise) catalogPromise = fetch('/board/catalog', {cache:'no-store', signal:AbortSignal.timeout(5000)})
  .then(r => {if (!r.ok) throw Error(); return r.json()})
  .then(data => {
   if (!Array.isArray(data.scene_catalog) || !Array.isArray(data.scene_ids)) throw Error();
   const screens = data.scene_catalog.filter(s => typeof s.id === 'string' && /^[a-z0-9-]+$/.test(s.id) && typeof s.name === 'string');
   return {screens, assigned:data.scene_ids};
  }).catch(error => {catalogPromise = null; throw error});
 return catalogPromise;
}
function previewURL(id, animation) {return `/board/library/${encodeURIComponent(id)}.${animation ? 'webp' : 'png'}?t=${Date.now()}`}
function loadPreview(image, id, animation) {
 return new Promise((resolve, reject) => {
  image.onload = () => resolve();
  image.onerror = () => {
   if (animation) {animation = false; image.src = previewURL(id, false)}
   else reject(Error('Preview unavailable'));
  };
  image.src = previewURL(id, animation);
 });
}
function clearScene() {
 sceneEpoch++; sceneLoading = false; sceneUpdatedAt = 0;
 sceneImage.hidden = true; sceneImage.removeAttribute('src');
}
function showSceneOffline() {
 clearScene(); sceneMessage.hidden = false;
 sceneMessage.textContent = 'Local connection lost. Waiting for current readings.';
}
async function refreshScene() {
 if (DEMO || document.hidden || !selectedScene || document.documentElement.dataset.theme !== 'scene' || sceneLoading) return;
 if (offline) {showSceneOffline(); return}
 const epoch = ++sceneEpoch, id = selectedScene;
 sceneLoading = true;
 if (!sceneImage.hasAttribute('src')) {sceneMessage.hidden = false; sceneMessage.textContent = 'Loading preview…'}
 try {
  const catalog = await getCatalog();
  const item = catalog.screens.find(s => s.id === id);
  if (!item) {
   if (epoch === sceneEpoch) {sceneImage.hidden = true; sceneMessage.hidden = false; sceneMessage.textContent = 'Screen unavailable. Choose another screen.'}
   return;
  }
  if (epoch === sceneEpoch) $('#scene-title').textContent = item.name;
  const next = new Image(); next.id = 'scene-image'; next.alt = 'Selected screen with current usage';
  await loadPreview(next, id, !reducedMotion.matches);
  if (epoch !== sceneEpoch || offline) return;
  sceneImage.replaceWith(next); sceneImage = next; sceneMessage.hidden = true;
  sceneUpdatedAt = Date.now();
 } catch {
  if (epoch === sceneEpoch) {
   sceneImage.hidden = true; sceneImage.removeAttribute('src'); sceneMessage.hidden = false;
   sceneMessage.textContent = 'Preview unavailable.';
  }
 } finally {if (epoch === sceneEpoch) sceneLoading = false}
}
function chooseScene(item) {
 selectedScene = item.id; savePreference('ai-desk-display.dashboard-scene', selectedScene);
 clearScene(); $('#scene-title').textContent = item.name;
 library.close(); setTheme('scene');
 $('#dashboard-scene').scrollIntoView({behavior:reducedMotion.matches ? 'auto' : 'smooth', block:'start'});
}
function pumpLibrary(epoch) {
 if (epoch !== libraryEpoch || !library.open || document.hidden || libraryBusy || !libraryQueue.length) return;
 const {image, state, item} = libraryQueue.shift();
 libraryBusy = true;
 loadPreview(image, item.id, !reducedMotion.matches).then(() => {
  if (epoch === libraryEpoch) {image.hidden = false; state.hidden = true}
 }).catch(() => {if (epoch === libraryEpoch) state.textContent = 'Preview unavailable.'})
  .finally(() => {if (epoch === libraryEpoch) {libraryBusy = false; pumpLibrary(epoch)}});
}
function librarySection(title, screens, epoch) {
 if (!screens.length) return;
 const section = el('section', undefined, 'library-section');
 section.append(el('h3', title));
 const grid = el('div', undefined, 'library-grid');
 for (const item of screens) {
  const button = el('button', undefined, 'library-card'); button.type = 'button';
  button.dataset.sceneId = item.id;
  button.setAttribute('aria-pressed', String(document.documentElement.dataset.theme === 'scene' && selectedScene === item.id));
  const frame = el('span', undefined, 'library-frame');
  const image = el('img'); image.alt = ''; image.hidden = true; image.decoding = 'async';
  const state = el('span', 'Loading preview…', 'library-frame-state'); state.setAttribute('aria-hidden', 'true');
  frame.append(image, state); button.append(frame, el('span', item.name, 'library-card-name'));
  button.onclick = () => chooseScene(item); grid.append(button);
  const entry = {image, state, item};
  if (libraryObserver) {button._previewEntry = entry; libraryObserver.observe(button)}
  else libraryQueue.push(entry);
 }
 section.append(grid); libraryContent.append(section);
 pumpLibrary(epoch);
}
async function openLibrary() {
 if (!library.open) library.showModal();
 libraryContent.replaceChildren(el('p', 'Loading screens…', 'library-message'));
 libraryPaused = false; libraryOpenedAt = Date.now();
 const epoch = ++libraryEpoch;
 catalogPromise = null; // Pick up screen versions added since the last visit.
 try {
  const {screens, assigned} = await getCatalog();
  if (epoch !== libraryEpoch || !library.open) return;
  const byId = new Map(screens.map(s => [s.id, s]));
  const onDisplay = [...new Set(assigned)].map(id => byId.get(id)).filter(Boolean);
  const assignedIds = new Set(onDisplay.map(s => s.id));
  const other = screens.filter(s => !assignedIds.has(s.id));
  libraryContent.replaceChildren();
  if ('IntersectionObserver' in window) libraryObserver = new IntersectionObserver(entries => {
   for (const entry of entries) if (entry.isIntersecting) {
    libraryObserver.unobserve(entry.target); libraryQueue.push(entry.target._previewEntry);
   }
   pumpLibrary(epoch);
  }, {root:library, rootMargin:'100px'});
  librarySection('On your display', onDisplay, epoch);
  librarySection('More screens', other, epoch);
 } catch {
  if (epoch !== libraryEpoch || !library.open) return;
  pauseLibrary('Could not load the screen library.');
 }
}
function pauseLibrary(message) {
 if (!library.open || libraryPaused) return;
 libraryPaused = true; libraryEpoch++; libraryQueue = []; libraryBusy = false;
 libraryObserver?.disconnect(); libraryObserver = null;
 const retry = el('button', 'Try again', 'library-retry'); retry.type = 'button';
 retry.onclick = openLibrary;
 libraryContent.replaceChildren(el('p', message, 'library-message'), retry);
}
library.addEventListener('close', () => {
 libraryEpoch++; libraryQueue = []; libraryBusy = false;
 libraryObserver?.disconnect(); libraryObserver = null;
 if (Date.now() - sceneUpdatedAt >= 60000) refreshScene();
});
$('#library-close').onclick = () => library.close();
$('#scene-change').onclick = openLibrary;
if (!DEMO) {
 const button = el('button', undefined, 'theme-button library-button');
 button.id = 'scene-browse'; button.type = 'button'; button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-pressed', 'false');
 const swatch = el('span', undefined, 'library-swatch'); swatch.setAttribute('aria-hidden', 'true');
 swatch.append(el('i'), el('i'), el('i')); button.append(swatch, el('span', 'Screen library', 'theme-name'));
 button.onclick = openLibrary; $('#themes').append(button);
}
reducedMotion.addEventListener?.('change', () => {if (document.documentElement.dataset.theme === 'scene') {clearScene(); refreshScene()}});
document.addEventListener('visibilitychange', () => {
 if (!document.hidden && library.open) {
  if (Date.now() - libraryOpenedAt >= 120000) pauseLibrary('Previews paused. Reload them for current readings.');
  else pumpLibrary(libraryEpoch);
 }
 if (!document.hidden && !library.open && document.documentElement.dataset.theme === 'scene' && Date.now() - sceneUpdatedAt >= 60000) {
  clearScene(); refreshScene();
 }
});
setTheme(readPreference('tokentv.theme', 'game-boy'));
buildStarfield();
update(); refreshDisplay(); setInterval(update, 30000); setInterval(() => {renderAccounts(); if (!$('#clock-panel').hidden) refreshDisplay()}, 5000);
setInterval(() => {
 if (library.open && Date.now() - libraryOpenedAt >= 120000) pauseLibrary('Previews paused. Reload them for current readings.');
 else if (!library.open && document.documentElement.dataset.theme === 'scene') {
  if (sceneUpdatedAt && Date.now() - sceneUpdatedAt >= 120000) {
   sceneImage.hidden = true; sceneMessage.hidden = false; sceneMessage.textContent = 'Waiting for an updated preview…';
  }
  if (Date.now() - sceneUpdatedAt >= 60000) refreshScene();
 }
}, 10000);
