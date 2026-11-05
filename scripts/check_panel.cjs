/* Behaviour of the usage panel against scripts/sample_dashboard.py (fictional readings, localhost only):
 * the five hours under the week, ages, problems only, the quiet chart, keyboard and screen-reader hooks, Spanish.
 *
 *   python3 -B scripts/sample_dashboard.py --port 18791 &
 *   node scripts/check_panel.cjs --url http://127.0.0.1:18791 --out /tmp/panel-check
 *
 * PLAYWRIGHT_PACKAGE and CHROMIUM_EXECUTABLE pick the browser like scripts/test_web_browser.cjs. Exit status 1 on any failure.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.env.PLAYWRIGHT_PACKAGE || 'playwright');
const arg = (name, fallback) => { const i = process.argv.indexOf('--' + name); return i > 0 ? process.argv[i + 1] : fallback; };
const url = arg('url', 'http://127.0.0.1:18791'), out = arg('out', '.runtime/panel-check');
const results = [];
const check = async (name, body) => { try { await body(); results.push([name, true]); } catch (error) { results.push([name, false, error.message.split('\n').filter(Boolean).slice(0, 5).join(' | ')]); } };

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE});
  const problems = [];
  const open = async (scenario, {width = 1440, language = 'en', theme = 'orbit'} = {}) => {
    const context = await browser.newContext({viewport: {width, height: 1000}, reducedMotion: 'reduce'});
    await context.addInitScript(l => { try { localStorage.setItem('ai-desk-display.language', l); localStorage.setItem('tokentv.theme', JSON.stringify('orbit')); } catch (e) {} }, language);
    const page = await context.newPage();
    page.on('pageerror', e => problems.push(`${scenario}: ${e.message}`));
    page.on('console', m => { if (m.type() === 'error' && !(page.expectOffline && /Failed to load resource/.test(m.text()))) problems.push(`${scenario}: console ${m.text()}`); });
    page.on('requestfailed', r => { if (!page.expectOffline) problems.push(`${scenario}: failed ${r.url()}`); });
    await page.request.get(`${url}/__scenario/${scenario}`);
    await page.goto(url); await page.waitForSelector('.provider-card');
    await page.evaluate(t => setTheme(t), theme);
    await page.waitForFunction(() => document.querySelector('.card-foot, .provider-card[data-foot=false]') && historyAt > 0);   // the readings and the first answer of /history
    await page.waitForTimeout(300);
    return {page, context};
  };
  const card = (page, provider) => page.locator(`.provider-card[data-provider=${provider}]`);

  await check('normal: the five hours sit under the week, readable without opening anything', async () => {
    const {page, context} = await open('normal');
    const claude = card(page, 'claude');
    assert.equal(await claude.locator('.window-detail').count(), 1);
    assert.equal(await claude.locator('details').count(), 0);
    assert.match(await claude.locator('.window-name').innerText(), /5-HOUR LEFT/i);
    assert.equal(await claude.locator('.window-detail [role=meter]').getAttribute('aria-valuenow'), '59');
    assert.match(await claude.locator('.window-percent').innerText(), /^59%$/);
    assert.match(await claude.locator('.window-timer').innerText(), /resets in 2h 0\dm/);
    assert.match(await claude.locator('.percentage').innerText(), /^38\s*%$/);   // the week is still the headline
    assert.equal(await card(page, 'codex').locator('.window-detail').count(), 0); // Codex reports no five hours: nothing is invented
    await context.close();
  });
  await check('normal: how old, no "Connected", hearts without a question mark', async () => {
    const {page, context} = await open('normal');
    for (const provider of ['claude', 'codex']) assert.match(await card(page, provider).locator('.foot-age').innerText(), /^Checked (just now|\d+ s ago)$/);
    const text = await page.locator('body').innerText();
    for (const gone of ['Connected', 'Source', 'Account', 'Window', 'Reporting', 'Automatic updates', 'Server checked']) assert.ok(!text.includes(gone), gone);
    assert.equal(await page.locator('.saved-hearts').evaluateAll(n => n.map(h => h.textContent.includes('?')).filter(Boolean).length), 0);
    assert.equal(await page.locator('.foot-note, .age-dot, .hearts-dot').count(), 0);   // all is well: nothing else to say
    assert.equal(await page.locator('.card-foot').first().evaluate(e => e.children.length), 1);
    await context.close();
  });
  await check('normal: the age keeps counting', async () => {
    const {page, context} = await open('normal');
    const first = await card(page, 'codex').locator('.foot-age').innerText();
    await page.waitForTimeout(5600);
    const later = await card(page, 'codex').locator('.foot-age').innerText();
    assert.notEqual(first, later);
    await context.close();
  });
  await check('chart: one sentence, one quiet figure, honest about "at this pace"', async () => {
    const {page, context} = await open('normal');
    for (const provider of ['claude', 'codex']) {
      const block = card(page, provider).locator('.history');
      assert.match(await block.locator('.history-sentence').innerText(), /^At this pace, the week lasts until it resets$/);
      assert.ok(await block.locator('.history-line').count() >= 1);
      assert.equal(await block.locator('.history-ahead').count(), 1);
      assert.equal(await block.locator('.history-now').count(), 1);
      assert.equal(await block.locator('.history-plot').getAttribute('role'), 'img');
      assert.match(await block.locator('.history-plot').getAttribute('aria-label'), /arrow keys/);
      assert.equal(await block.locator('.history-plot').getAttribute('tabindex'), '0');
      assert.ok(await block.locator('table.visually-hidden tr').count() >= 3);
    }
    assert.equal(await page.locator('script[src*="://"], link[href*="://"]').count(), 0);   // no libraries, no CDNs
    await context.close();
  });
  await check('chart: hover and keyboard read the same numbers; focus and hover survive the redraw', async () => {
    const {page, context} = await open('normal');
    const plot = card(page, 'claude').locator('.history-plot'), readout = card(page, 'claude').locator('.history-readout');
    assert.equal(await readout.isVisible(), false);
    const box = await plot.boundingBox();
    await page.mouse.move(box.x + box.width * 0.2, box.y + box.height / 2);
    assert.match(await readout.innerText(), /^\d+% left · \w{3} \d\d:\d\d$/);
    await page.evaluate(() => renderAccounts());                       // the dashboard redraws every five seconds
    assert.equal(await card(page, 'claude').locator('.history-readout').isVisible(), true);
    await page.mouse.move(2, 2);
    assert.equal(await card(page, 'claude').locator('.history-readout').isVisible(), false);
    await page.keyboard.press('Tab');                                   // from the page start to the first stop; then walk to the chart
    await page.locator('.provider-card[data-provider=claude] .history-plot').focus();
    await page.keyboard.press('ArrowLeft');
    const left = await card(page, 'claude').locator('.history-readout').innerText();
    await page.keyboard.press('Home');
    const first = await card(page, 'claude').locator('.history-readout').innerText();
    await page.keyboard.press('End');
    const last = await card(page, 'claude').locator('.history-readout').innerText();
    assert.notEqual(first, last);
    assert.match(left, /% left/);
    await page.evaluate(() => renderAccounts());
    assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('history-plot') && document.activeElement.dataset.provider), 'claude');
    assert.equal(await card(page, 'claude').locator('.history-readout').isVisible(), true);
    await page.keyboard.press('Escape');
    assert.equal(await card(page, 'claude').locator('.history-readout').isVisible(), false);
    await context.close();
  });
  await check('chart: a visible focus ring for the keyboard', async () => {
    const {page, context} = await open('normal');
    await page.locator('.provider-card[data-provider=codex] .history-plot').focus();
    await page.keyboard.press('ArrowRight');
    assert.notEqual(await page.locator('.provider-card[data-provider=codex] .history-plot').evaluate(e => getComputedStyle(e).outlineStyle), 'none');
    await context.close();
  });
  await check('runs out: the soonest window is the sentence, and it names the window', async () => {
    const {page, context} = await open('runs_out');
    assert.match(await card(page, 'claude').locator('.history-sentence').innerText(), /^At this pace, the 5-hour window runs out in about 1\s*h 20\s*min$/);
    assert.match(await card(page, 'codex').locator('.history-sentence').innerText(), /^At this pace, the week runs out in about 3\s*days$/);
    assert.equal(await card(page, 'claude').locator('.history-stop').count(), 1);
    await context.close();
  });
  await check('thin history or flat usage: nothing at all, not a blank chart', async () => {
    const {page, context} = await open('thin');
    assert.equal(await page.locator('.history, .history-plot').count(), 0);
    assert.equal(await card(page, 'claude').locator('.window-detail').count(), 1);   // the readings themselves are untouched
    await context.close();
  });
  await check('an outage shows as a gap in the line', async () => {
    const {page, context} = await open('gap');
    assert.equal(await card(page, 'claude').locator('.history-line').count(), 2);
    await context.close();
  });
  await check('two accounts of one service: no chart (it would mix two lines)', async () => {
    const {page, context} = await open('two_accounts');
    assert.equal(await card(page, 'claude').locator('.history').count(), 0);
    assert.equal(await card(page, 'codex').locator('.history').count(), 1);
    await context.close();
  });
  await check('aged: the number stays, calmly: age with a dot, hearts with a dot, no forecast', async () => {
    const {page, context} = await open('aged');
    const claude = card(page, 'claude');
    assert.match(await claude.locator('.percentage').innerText(), /38/);
    assert.match(await claude.locator('.foot-age').innerText(), /^Checked [2-9] min ago$/);
    assert.equal(await claude.locator('.foot-age .age-dot').count(), 1);
    assert.equal(await claude.locator('.saved-hearts .hearts-dot').count(), 1);
    assert.equal(await claude.locator('.history').count(), 0);
    assert.match(await claude.locator('.foot-note').innerText(), /did not confirm a new reading/);
    assert.match(await claude.locator('.foot-retry').innerText(), /^Next try in \d+ s$/);
    assert.equal(await card(page, 'codex').locator('.age-dot, .hearts-dot').count(), 0);
    await context.close();
  });
  await check('quota reader failing: the sentence replaces the number, with since and next try', async () => {
    const {page, context} = await open('reader_failing');
    const claude = card(page, 'claude');
    assert.match(await claude.locator('.unknown-message').innerText(), /login was lost: run \/login/);
    assert.match(await claude.locator('.percentage').innerText(), /—/);
    assert.match(await claude.locator('.foot-age').innerText(), /^No reading for \d+ min$/);
    assert.match(await claude.locator('.foot-retry').innerText(), /^Next try in \d+ s$/);
    assert.equal(await claude.locator('.window-detail, .history').count(), 0);
    assert.equal(await claude.locator('.foot-note').count(), 0);              // said once, where the number would be
    await context.close();
  });
  await check('saved-reset counter failing: one note, three faint hearts and a dot', async () => {
    const {page, context} = await open('bank_failing');
    const claude = card(page, 'claude');
    assert.match(await claude.locator('.foot-note').innerText(), /saved-reset counter is not updating\. Last update \d\d:\d\d\./);
    assert.deepEqual(await claude.locator('.saved-hearts svg').evaluateAll(n => n.map(s => s.dataset.filled)), ['false', 'false', 'false']);
    assert.equal(await claude.locator('.saved-hearts .hearts-dot').count(), 1);
    await context.close();
  });
  await check('unknown with no reader news: the old plain message, no foot at all', async () => {
    const {page, context} = await open('unknown');
    const claude = card(page, 'claude');
    assert.match(await claude.locator('.unknown-message').innerText(), /No recent weekly reading/);
    assert.equal(await claude.locator('.card-foot').count(), 0);
    assert.equal(await claude.getAttribute('data-foot'), 'false');
    await context.close();
  });
  await check('Spanish: ages, sentences and reader words follow the language', async () => {
    const {page, context} = await open('runs_out', {language: 'es'});
    assert.match(await card(page, 'claude').locator('.foot-age').innerText(), /^Consultado (ahora mismo|hace \d+ s)$/);
    assert.match(await card(page, 'claude').locator('.history-sentence').innerText(), /^A este ritmo, la ventana de 5 horas se agota en aproximadamente 1\s*h 20\s*min$/);
    assert.match(await card(page, 'codex').locator('.history-sentence').innerText(), /^A este ritmo, la semana se agota en aproximadamente 3\s*días$/);
    await page.request.get(`${url}/__scenario/reader_failing`);
    await page.evaluate(() => update());
    await page.waitForFunction(() => /Se ha perdido el inicio de sesión/.test(document.body.innerText));
    await context.close();
  });
  await check('phone width: no sideways scroll, the five hours still readable', async () => {
    for (const width of [320, 390]) {
      const {page, context} = await open('runs_out', {width});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${width}`);
      assert.equal(await card(page, 'claude').locator('.window-detail').isVisible(), true);
      await context.close();
    }
  });
  await check('odd rows (old values, another service, wrong identity, offline) never break the page', async () => {
    const {page, context} = await open('normal');
    const now = Date.now() / 1000;
    const fixture = {schema: 1, updated_at: now, accounts: {
      a: {key: 'a', alias: 'CLAUDE A', provider: 'claude', status: 'stale', source: 'laptop', last_success_at: now - 3 * 3600, fetched_at: now - 3 * 3600,
          windows: [{label: '5H', used_percent: 82, resets_at: now + 3600}, {label: 'WEEK', used_percent: 50, resets_at: now + 8000}]},
      b: {key: 'b', alias: 'CODEX A', provider: 'codex', status: 'identity_mismatch', windows: [{label: 'WEEK', used_percent: 99}]},
      c: {key: 'c', alias: 'GROK A', provider: 'grok', status: 'ok', source: 'mini', fetched_at: now - 20, windows: [{label: 'BUDGET', used_percent: 61, resets_at: now + 6 * 86400}]}}};
    await page.route('**/snapshot', r => r.fulfill({json: fixture}));
    await page.evaluate(() => update());
    await page.waitForSelector('.provider-card[data-provider=grok] .percentage');
    assert.match(await card(page, 'claude').locator('.foot-age').innerText(), /^Last good 3 h ago$/);
    assert.match(await card(page, 'codex').locator('.foot-note').innerText(), /Check identity/);
    assert.match(await card(page, 'grok').locator('.foot-age').innerText(), /^Checked \d+ s ago$/);
    assert.equal(await page.locator('.history').count(), 0);
    await page.unroute('**/snapshot');
    page.expectOffline = true;
    await page.route('**/snapshot', r => r.abort());
    await page.evaluate(() => update());
    await page.waitForFunction(() => document.body.dataset.offline === 'true');
    assert.match(await card(page, 'grok').locator('.foot-age').innerText(), /^Offline · previous value$/);
    assert.equal(await page.locator('.history').count(), 0);
    assert.equal(await page.locator('.provider-card[data-stale=true]').count(), 3);   // old values are marked as old, never as current
    await context.close();
  });
  await browser.close();

  assert.ok(true);
  let failed = 0;
  for (const [name, ok, why] of results) { console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : '\n      ' + why}`); failed += ok ? 0 : 1; }
  const unique = [...new Set(problems)];
  console.log(unique.length ? `PAGE PROBLEMS (${unique.length}): ${unique.join(' | ').slice(0, 600)}` : 'no console errors, no failed requests');
  fs.writeFileSync(`${out}/check-panel.json`, JSON.stringify({results, problems: unique}, null, 2));
  process.exitCode = failed || unique.length ? 1 : 0;
})().catch(e => { console.error(e); process.exit(2); });
