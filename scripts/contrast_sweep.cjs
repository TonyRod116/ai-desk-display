/* Contrast and text-size sweep of the usage page, one appearance after another. Local page, fictional readings.
 *
 *   python3 -B scripts/sample_dashboard.py --port 18791 &
 *   node scripts/contrast_sweep.cjs --url http://127.0.0.1:18791 --width 1440 --height 1000 --out /tmp/sweep
 *
 * For each appearance in THEMES (plus the screen-library one) it lists every visible piece of text, its size, and its
 * contrast against what is really painted behind it: the page is drawn once with the text made transparent, and the
 * pixels under each word are sampled (gradients, scenery and tints count; text shadows do not). The ratio kept is the
 * 20th percentile of the samples, so a word half over a darker patch is judged by its worse half.
 * Strict rule, as in the review: every text at least 12 px and 4.5:1. Exit status 1 when any theme has an offender.
 * The last column repeats the check the way a simple checker does (computed rgb() backgrounds only, anything it cannot
 * parse, such as a colour mixed with color-mix(), taken as black): a surface that fools it shows up there.
 * Options: --themes a,b  --scenario name  --route /board (a page with no appearances)  --list N (offenders shown per theme).
 * PLAYWRIGHT_PACKAGE and CHROMIUM_EXECUTABLE pick the browser the same way scripts/test_web_browser.cjs does.
 */
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const arg = (name, fallback) => { const i = process.argv.indexOf('--' + name); return i > 0 ? process.argv[i + 1] : fallback; };
const url = arg('url', 'http://127.0.0.1:18791'), out = arg('out', '.runtime/contrast-sweep');
const width = Number(arg('width', 1440)), height = Number(arg('height', 1000)), scenario = arg('scenario', 'normal'); // --scenario a,b,c runs several stories
const only = arg('themes', '').split(',').filter(Boolean), route = arg('route', '/'), listed = Number(arg('list', 12));
const MIN_SIZE = 12, MIN_CONTRAST = 4.5;

/* Runs inside the page: every visible piece of text with its size, colour and the boxes it occupies. */
function collect() {
  const parse = value => {
    const n = value.match(/-?[\d.]+(?:e-?\d+)?/g).map(Number);
    return value.startsWith('color(') ? [n[0] * 255, n[1] * 255, n[2] * 255, n[3] ?? 1] : [n[0], n[1], n[2], n[3] ?? 1];
  };
  const simple = value => { // what a simple checker reads: rgb()/rgba() only, everything else is black
    const m = value.match(/^rgba?\(([^)]*)\)$/);
    if (!m) return [0, 0, 0, 1];
    const n = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return [n[0], n[1], n[2], n[3] ?? 1];
  };
  const boxes = [], byElement = new Map();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node; (node = walker.nextNode());) {
    const el = node.parentElement;
    if (!node.nodeValue.trim() || !el || el.closest('script,style,noscript,.visually-hidden,option,select,[hidden],dialog:not([open])')) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    let opacity = 1;
    for (let up = el; up; up = up.parentElement) opacity *= Number(getComputedStyle(up).opacity);
    if (opacity < 0.05) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter(r => r.width >= 2 && r.height >= 2).map(r => [r.left + scrollX, r.top + scrollY, r.width, r.height]);
    if (!rects.length) continue;
    const known = byElement.get(el);
    if (known) { known.rects.push(...rects); known.text += ' ' + node.nodeValue.trim(); continue; }
    // The colour the styles alone promise: backgrounds stacked up to the first opaque one (gradients and pictures are unknown).
    let flat = true; const layers = [];
    for (let up = el; up; up = up.parentElement) {
      const s = getComputedStyle(up); if (s.backgroundImage !== 'none') flat = false;
      const c = parse(s.backgroundColor); layers.push(c); if (c[3] >= 1) break;
    }
    let under = [255, 255, 255];
    for (const c of layers.reverse()) under = under.map((u, k) => c[3] * c[k] + (1 - c[3]) * u);
    let blunt = [255, 255, 255]; const rough = [];
    for (let up = el; up; up = up.parentElement) { const c = simple(getComputedStyle(up).backgroundColor); rough.push(c); if (c[3] >= 1) break; }
    for (const c of rough.reverse()) blunt = blunt.map((u, k) => c[3] * c[k] + (1 - c[3]) * u);
    const roughColor = simple(getComputedStyle(el).color);
    const color = parse(style.color), box = {
      text: node.nodeValue.trim().slice(0, 48), tag: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
      size: parseFloat(style.fontSize), color: color.slice(0, 3), alpha: color[3] * opacity, rects, flat, under, blunt, roughColor
    };
    byElement.set(el, box); boxes.push(box);
  }
  return boxes;
}

async function contrastOf(page) {
  const boxes = await page.evaluate(collect);
  await page.addStyleTag({content: '*,*::before,*::after{color:transparent!important;text-shadow:none!important;-webkit-text-fill-color:transparent!important}'}).then(h => h.evaluate(n => n.id = 'sweep-hide'));
  const png = (await page.screenshot({fullPage: true, animations: 'disabled'})).toString('base64');
  await page.evaluate(() => document.getElementById('sweep-hide').remove());
  return page.evaluate(async ({boxes, png}) => {
    const image = new Image(); image.src = 'data:image/png;base64,' + png; await image.decode();
    const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
    const g = canvas.getContext('2d', {willReadFrequently: true}); g.drawImage(image, 0, 0);
    const lum = ([r, gr, b]) => { const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(gr) + 0.0722 * f(b); };
    return boxes.map(b => {
      const ratios = [];
      for (const [x, y, w, h] of b.rects) {
        for (let i = 0; i < 6; i++) for (let j = 0; j < 3; j++) {
          const px = Math.min(image.width - 1, Math.max(0, Math.round(x + (i + 0.5) * w / 6))), py = Math.min(image.height - 1, Math.max(0, Math.round(y + (j + 0.5) * h / 3)));
          const bg = g.getImageData(px, py, 1, 1).data;
          const fg = b.color.map((c, k) => b.alpha * c + (1 - b.alpha) * bg[k]);
          const [hi, lo] = [lum(fg), lum([bg[0], bg[1], bg[2]])].sort((a, c) => c - a);
          ratios.push((hi + 0.05) / (lo + 0.05));
        }
      }
      ratios.sort((a, c) => a - c);
      const pixel = ratios[Math.floor(ratios.length * 0.2)];
      const fg = b.color.map((c, k) => b.alpha * c + (1 - b.alpha) * b.under[k]);
      const [hi, lo] = [lum(fg), lum(b.under)].sort((a, c) => c - a);
      const style = (hi + 0.05) / (lo + 0.05);
      // Where the styles describe the background fully, the worse of the two readings counts.
      const mixed = b.roughColor.slice(0, 3).map((c, k) => b.roughColor[3] * c + (1 - b.roughColor[3]) * b.blunt[k]);
      const [top, low] = [lum(mixed), lum(b.blunt)].sort((a, c) => c - a);
      return {...b, rects: undefined, under: undefined, blunt: undefined, roughColor: undefined, simple: Math.round((top + 0.05) / (low + 0.05) * 100) / 100, ratio: Math.round((b.flat ? Math.min(pixel, style) : pixel) * 100) / 100, pixel: Math.round(pixel * 100) / 100, style: Math.round(style * 100) / 100};
    });
  }, {boxes, png});
}

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE});
  const summary = [];
  try {
    const context = await browser.newContext({viewport: {width, height}, reducedMotion: 'reduce'});
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message)); page.on('console', m => m.type() === 'error' && errors.push(m.text()));
    for (const story of scenario.split(',')) {
      await page.request.get(`${url}/__scenario/${story}`);
      await page.goto(url + route); await page.waitForSelector('.provider-card, .workbench', {timeout: 15000});
      const ids = route === '/' ? [...await page.evaluate(() => THEMES.map(t => t.id)), 'scene'] : [''];
      for (const id of ids) {
        if (only.length && !only.includes(id)) continue;
        if (id === 'scene') await page.evaluate(() => { selectedScene = 'cockpit'; });
        if (id) { await page.evaluate(t => setTheme(t), id); await page.waitForSelector('.provider-card'); }
        await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(250);
        const items = await contrastOf(page);
        const small = items.filter(i => i.size < MIN_SIZE), faint = items.filter(i => i.ratio < MIN_CONTRAST);
        const both = items.filter(i => i.size < MIN_SIZE && i.ratio < MIN_CONTRAST), rough = items.filter(i => i.simple < MIN_CONTRAST);
        summary.push({scenario: story, theme: id || route, texts: items.length, under12px: small.length, under4_5: faint.length, both: both.length, simple: rough.length,
          worst: [...new Set([...small, ...faint, ...rough])].sort((a, c) => a.ratio - c.ratio).slice(0, listed).map(i => `${i.ratio}:1 (pixels ${i.pixel}, styles ${i.style}, simple ${i.simple}) ${i.size}px  ${i.tag}  "${i.text}"`)});
      }
    }
    summary.push({consoleErrors: errors, overflowX: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)});
  } finally { await browser.close(); }
  fs.writeFileSync(path.join(out, `sweep-${width}x${height}-${scenario.replace(/,/g, '+')}.json`), JSON.stringify(summary, null, 2));
  console.log(`scenario        theme              texts  <12px  <4.5:1  both  simple checker <4.5:1   (${width}x${height})`);
  for (const s of summary.filter(s => s.theme)) console.log(`${s.scenario.padEnd(15)} ${s.theme.padEnd(18)} ${String(s.texts).padStart(5)}  ${String(s.under12px).padStart(5)}  ${String(s.under4_5).padStart(6)}  ${String(s.both).padStart(4)}  ${String(s.simple).padStart(10)}`);
  const tail = summary.at(-1); console.log(`console errors: ${tail.consoleErrors.length}${tail.consoleErrors.length ? ' (' + [...new Set(tail.consoleErrors)].join(' | ').slice(0, 300) + ')' : ''}   horizontal overflow: ${tail.overflowX}`);
  for (const s of summary.filter(s => s.theme && s.worst.length)) console.log(`\n${s.scenario} / ${s.theme}\n  ` + s.worst.join('\n  '));
  process.exitCode = summary.some(s => s.theme && (s.under12px || s.under4_5 || s.simple)) ? 1 : 0;
})().catch(e => { console.error(e); process.exit(2); });
