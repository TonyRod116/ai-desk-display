// Standalone local visual check. All artwork is invented in the browser;
// this script never opens an installed atlas, account data or a device.
// Run: node tests/visual_tablet_blue_lightning.cjs [output-dir] [baseline-js]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const nodeVersions = path.join(os.homedir(), '.nvm/versions/node');
const candidates = (fs.existsSync(nodeVersions) ? fs.readdirSync(nodeVersions) : [])
  .map(v => path.join(nodeVersions, v, 'lib/node_modules/@playwright/cli/node_modules/playwright-core'))
  .filter(p => fs.existsSync(p));
const {chromium} = require(process.env.PLAYWRIGHT_PACKAGE || candidates.at(-1) || 'playwright');
const out = path.resolve(process.argv[2] || path.join(os.tmpdir(), 'blue-lightning-visual'));
const baseline = process.argv[3] && path.resolve(process.argv[3]);
const current = path.resolve(__dirname, '../token_tv/tablet_web/game-blue-lightning.js');
const logic = require(current), fixtureSeed = 12345, geo = logic.layout(320);
const baselineLogic = baseline ? require(baseline) : null;
const findTime = predicate => {
  for (let i = 0; i < 18000; i++) if (predicate(logic.aircraft(i / 30, geo, fixtureSeed))) return i / 30;
  throw new Error('fictional flight does not contain the requested maneuver');
};
const preview = {left: findTime(p => p.bank < -.7), right: findTime(p => p.bank > .7),
  climb: findTime(p => p.pitch > .7 && Math.abs(p.bank) < .3), dive: findTime(p => p.pitch < -.7 && Math.abs(p.bank) < .3),
  low: findTime(p => p.altitude < .005 && Math.abs(p.pitch) < .01 && Math.abs(p.bank) < .01),
  middle: findTime(p => Math.abs(p.altitude - .5) < .005 && Math.abs(p.pitch) < .01 && Math.abs(p.bank) < .01),
  high: findTime(p => p.altitude > .995 && Math.abs(p.pitch) < .01 && Math.abs(p.bank) < .01)};
const rearSpec = logic.MISSIONS.find(spec => spec.hit && logic.enemyAt(spec.offset, spec, geo, null, fixtureSeed).rear);
if (!rearSpec) throw new Error('fictional seed does not contain a rear encounter with a hit');
const rearPreview = [0, 2.5, 4, 5.8, 6.3].map(age => {
  const time = rearSpec.offset + age, player = logic.aircraft(time, geo, fixtureSeed), camera = logic.cameraAt(time, geo, player);
  const enemy = logic.enemyAt(time, rearSpec, {...geo, horizon: camera.horizon}, camera, fixtureSeed);
  return {time, age, enemy};
});
const ascentPreview = Object.fromEntries([['after', logic], ...(baselineLogic ? [['before', baselineLogic]] : [])].map(([name, b]) => {
  const bounds = {left: 50, right: 50, top: 51, bottom: 51}, layout = b.layout(320, bounds), top = bounds.top * layout.planeScale;
  const shapes = [{width: 118 / 159, height: 14 / 159}, {width: 1, height: 30 / 159}], start = 47.4;
  return [name, Array.from({length: 6}, (_, i) => {
    const time = start + i * .2, distance = 13600 + i * .2 * (name === 'before' ? 6000 : 6900);
    const player = b.aircraft(time, layout, fixtureSeed), camera = b.cameraAt(time, layout, player);
    const cloud = b.cloudFeatures({time, distance, seed: fixtureSeed, boost: 0}, layout, camera, shapes, top).find(c => c.id === '4:1');
    return {time, distance, altitude: player.altitude, cloud: cloud && {x: cloud.x, y: cloud.y + camera.roll * (cloud.x - 100)}};
  })];
}));

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: 670}, deviceScaleFactor: 1});
    const problems = [];
    page.on('pageerror', e => problems.push(e.message));
    page.on('console', m => { if (m.type() === 'error') problems.push(m.text()); });
    await page.route('**/*', route => route.abort());
    await page.setContent('<style>body{background:#111;margin:0;color:#fff;font:14px sans-serif;display:flex}figure{margin:0}figcaption{height:30px;padding:5px;box-sizing:border-box}canvas{width:400px;height:640px;image-rendering:pixelated}</style><figure><figcaption>Fictional fields</figcaption><canvas width=200 height=320></canvas></figure><figure><figcaption>Fictional desert</figcaption><canvas width=200 height=320></canvas></figure><figure><figcaption>Fictional water</figcaption><canvas width=200 height=320></canvas></figure>');
    await page.addScriptTag({content: 'window.TabletGames = {define(name, scene) {window.registeredScene = scene;}}; window.scenes = {};'});
    if (baseline) {
      await page.addScriptTag({path: baseline});
      await page.evaluate(() => { window.scenes.before = window.registeredScene; });
    }
    await page.addScriptTag({path: current});
    await page.evaluate(() => { window.scenes.after = window.registeredScene; });
    await page.evaluate(({fixtureSeed, preview, rearPreview, ascentPreview}) => {
      const atlas = document.createElement('canvas'); atlas.width = 1024; atlas.height = 1024;
      const ctx = atlas.getContext('2d'), frames = {}, anchors = {}; let x = 0, y = 0, row = 0;
      function make(name, width, height, draw) {
        const w = Math.ceil(width), h = Math.ceil(height);
        if (x + w > atlas.width) { x = 0; y += row; row = 0; }
        row = Math.max(row, h + 2); frames[name] = [x, y, w, h]; anchors[name] = [Math.floor(w / 2), Math.floor(h * .6)];
        ctx.save(); ctx.translate(x, y); draw(w, h); ctx.restore(); x += w + 2;
      }
      function fictionalJet(p, attitude = 0) {
        // The unreflected fictional wings have the right wing higher, matching
        // the measured orientation without reproducing private artwork.
        ctx.fillStyle = '#142e6f'; ctx.fillRect(3, 15 + p, 19, 5); ctx.fillRect(26, 15 - p, 19, 5); ctx.fillRect(20, 4 - attitude, 8, 25 + attitude * 2);
        ctx.fillStyle = '#65b9f6'; ctx.fillRect(5, 16 + p, 15, 2); ctx.fillRect(28, 16 - p, 15, 2); ctx.fillRect(22, 6 - attitude, 4, 17 + attitude * 2);
        ctx.fillStyle = '#fff'; ctx.fillRect(23, 10, 2, 5);
      }
      for (let p = 0; p < 6; p++) make('player-' + p, 48, 32, () => fictionalJet(p));
      function fictionalLargeJet(w, h, p, attitude = 0) {
        const mid = Math.floor(h / 2), slope = p * 2;
        ctx.fillStyle = '#142e6f';
        for (let j = 0; j < 5; j++) {
          ctx.fillRect(5 + j * 8, mid + (4 - j) * slope, 9, 5);
          ctx.fillRect(55 + j * 8, mid - (j + 1) * slope, 9, 5);
        }
        ctx.fillRect(45, mid - 14 - attitude, 10, 29 + attitude * 2);
        ctx.fillStyle = '#65b9f6'; ctx.fillRect(48, mid - 11 - attitude, 4, 19 + attitude * 2);
      }
      for (const [family, attitude] of [['level', 0], ['up', 2], ['down', -2]]) for (let p = 0; p < 5; p++) {
        const name = `player-${family}-${p}`, height = 30 + p * 18;
        make(name, 100, height, (w, h) => fictionalLargeJet(w, h, p, attitude));
        anchors[name] = [50, Math.floor(height / 2)];
      }
      for (const [name, attitude] of [['player-up-transition', 1], ['player-down-transition', -1]]) {
        make(name, 100, 40, (w, h) => fictionalLargeJet(w, h, 0, attitude));
        anchors[name] = [50, 20];
      }
      for (let m = 0; m < 2; m++) for (const n of [5, 7, 10, 14, 18, 24, 32, 42, 54]) {
        make(`enemy-${m}-${n}`, n, Math.max(5, n / 2), (w, h) => {
          ctx.fillStyle = m ? '#ee958a' : '#efdfcb'; ctx.fillRect(0, h * .55, w, h * .2); ctx.fillRect(w * .44, 0, w * .12, h);
        });
      }
      const enemyWidths = [5, 7, 10, 14, 18, 24, 32, 42, 54];
      const enemyPoses = Array.from({length: 12}, (_, pose) => ({
        frames: enemyWidths.map(n => {
          const name = `enemy-pose-${pose}-${n}`, narrow = pose === 7 || pose === 8;
          const width = Math.max(1, Math.round(n * (narrow ? .2 : .8))), height = Math.max(2, Math.round(n * (narrow ? .9 : .35)));
          make(name, width, height, (w, h) => {
            ctx.fillStyle = pose % 2 ? '#d58f82' : '#f4ddbf';
            const slopes = {1: 1, 2: 1, 3: -1, 5: 1, 6: 1, 7: 1, 10: 1, 11: 1};
            const slope = (slopes[pose] || 0) * Math.max(1, Math.floor(h * .15)), mid = Math.floor(h * .5);
            ctx.fillRect(0, mid - slope, Math.ceil(w / 2), Math.max(1, Math.ceil(h * .16)));
            ctx.fillRect(Math.floor(w / 2), mid + slope, Math.ceil(w / 2), Math.max(1, Math.ceil(h * .16)));
            ctx.fillRect(Math.floor(w * .42), 0, Math.max(1, Math.ceil(w * .16)), h);
          });
          anchors[name] = [Math.floor(width / 2), Math.floor(height / 2)];
          return name;
        }),
        flips: pose === 4 ? [[true, false]] : [[false, false], [true, false]],
      }));
      for (const n of [12, 18, 26, 38, 55, 80, 110]) make('mesa-' + n, n, n * .5, (w, h) => {
        ctx.fillStyle = '#af743c'; ctx.fillRect(0, h * .6, w, h * .4); ctx.fillStyle = '#e6aa67'; ctx.fillRect(w * .2, 0, w * .6, h * .6);
      });
      for (const n of [10, 16, 24, 36, 52, 72]) make('ship-' + n, n, n * .4, (w, h) => {
        ctx.fillStyle = '#eae9dd'; ctx.fillRect(0, h * .6, w, h * .25); ctx.fillStyle = '#84949f'; ctx.fillRect(w * .4, h * .1, w * .2, h * .5);
      });
      const cloudWidths = [16, 24, 36, 54, 80, 120, 180];
      const cloudPoses = [[118, 14], [159, 30]].map(([sourceW, sourceH], style) => ({
        source_size: [sourceW, sourceH], source_anchor: style ? [0, -1] : [-25, -14],
        flips: style ? [[false, false]] : [[false, false], [true, false]],
        frames: cloudWidths.map(n => {
          const name = `cloud-pose-${style}-${n}`, width = Math.max(1, Math.round(n * sourceW / 159));
          const height = Math.max(1, Math.round(n * sourceH / 159));
          make(name, width, height, (w, h) => {
            ctx.fillStyle = '#c2e0e9'; ctx.fillRect(0, Math.floor(h * .65), w, Math.max(1, Math.ceil(h * .35)));
            ctx.fillStyle = '#f4fcff'; ctx.fillRect(Math.floor(w * .08), Math.floor(h * .3), Math.max(1, Math.floor(w * .84)), Math.max(1, Math.ceil(h * .45)));
            ctx.fillRect(Math.floor(w * .28), 0, Math.max(1, Math.floor(w * .45)), Math.max(1, Math.ceil(h * .4)));
          });
          anchors[name] = [Math.floor(width / 2), Math.floor(height / 2)];
          return name;
        }),
      }));
      const aircraft_poses = {version: 1, bank_angles: [0, 22.5, 45, 67.5, 90], right_flip: true,
        level: [0, 1, 2, 3, 4].map(i => `player-level-${i}`), up: [0, 1, 2, 3, 4].map(i => `player-up-${i}`),
        down: [0, 1, 2, 3, 4].map(i => `player-down-${i}`), up_transition: 'player-up-transition', down_transition: 'player-down-transition'};
      window.visualApi = {json: {frames, anchors}, atlas, flightSeed: fixtureSeed, view: {bottom: 320}};
      const enemy_poses = {version: 1, reference_width: 72, widths: enemyWidths, poses: enemyPoses, sequence: [4, 5, 6, 7, 8, 7, 6, 5, 4]};
      const cloud_poses = {version: 1, anchor_mode: 'visual_center', reference_width: 159, widths: cloudWidths, poses: cloudPoses};
      window.poseApi = {json: {frames, anchors, aircraft_poses, enemy_poses, cloud_poses}, atlas, flightSeed: fixtureSeed, view: {bottom: 320}};
      window.renderVisual = name => {
        const distances = name === 'before' ? [10000, 340000, 670000] : [10000, 389500, 769000];
        const variants = [preview.left, preview.right, preview.dive].map((time, i) => [time, distances[i]]), api = window.visualApi;
        [...document.querySelectorAll('canvas')].forEach((canvas, i) => {
          const instance = Object.create(window.scenes[name]); instance.init(api);
          instance.s.world.time = variants[i][0]; instance.s.world.distance = variants[i][1];
          instance.draw(api, canvas.getContext('2d'));
        });
      };
      window.renderManeuvers = usePoses => {
        const samples = [['Left turn', preview.left], ['Right turn', preview.right], ['Climb', preview.climb], ['Dive', preview.dive]];
        document.body.style.display = 'grid'; document.body.style.gridTemplateColumns = 'repeat(4, 300px)';
        document.body.innerHTML = samples.map(([label]) => `<figure><figcaption>${label} · fictional aircraft</figcaption><canvas width=200 height=320 style="width:300px;height:480px"></canvas></figure>`).join('');
        const api = usePoses ? window.poseApi : window.visualApi; api.view.bottom = 320;
        [...document.querySelectorAll('canvas')].forEach((canvas, i) => {
          const instance = Object.create(window.scenes.after); instance.init(api);
          instance.s.world.time = samples[i][1]; instance.s.world.distance = 10000;
          instance.draw(api, canvas.getContext('2d'));
        });
      };
      window.renderCompact = (name = 'after') => {
        const bottoms = [110, 150, 186], api = window.poseApi;
        document.body.style.display = 'grid'; document.body.style.gridTemplateColumns = 'repeat(3, 400px)';
        document.body.innerHTML = bottoms.map(bottom => `<figure><figcaption>Fictional dock · bottom=${bottom}</figcaption><canvas width=200 height=320></canvas></figure>`).join('');
        [...document.querySelectorAll('canvas')].forEach((canvas, i) => {
          api.view.bottom = bottoms[i];
          const instance = Object.create(window.scenes[name]); instance.init(api);
          instance.s.world.time = preview.right; instance.s.world.distance = 10000;
          const ctx = canvas.getContext('2d'); instance.draw(api, ctx);
          ctx.fillStyle = 'rgba(10,15,25,.82)'; ctx.fillRect(0, bottoms[i], 200, 320 - bottoms[i]);
        });
      };
      window.renderRear = () => {
        const api = window.poseApi; api.view.bottom = 320;
        document.body.style.display = 'grid'; document.body.style.gridTemplateColumns = 'repeat(5, 240px)';
        document.body.innerHTML = rearPreview.map(({age}) => `<figure><figcaption>Rear encounter · ${age.toFixed(1)} s</figcaption><canvas width=200 height=320 style="width:240px;height:384px"></canvas></figure>`).join('');
        [...document.querySelectorAll('canvas')].forEach((canvas, i) => {
          const instance = Object.create(window.scenes.after); instance.init(api);
          instance.s.world.time = rearPreview[i].time; instance.s.world.distance = 10000 + rearPreview[i].time * 6900;
          const ctx = canvas.getContext('2d'); instance.draw(api, ctx);
          const e = rearPreview[i].enemy;
          if (e && e.y >= 0 && e.y < 320) {
            ctx.strokeStyle = '#ffef93'; ctx.lineWidth = 1; ctx.strokeRect(Math.round(e.x - 8), Math.round(e.y - 8), 16, 16);
          }
        });
      };
      window.renderRearDock = () => {
        const bottoms = [110, 150, 186], api = window.poseApi, time = rearPreview[0].time + 3.2;
        document.body.style.display = 'grid'; document.body.style.gridTemplateColumns = 'repeat(3, 400px)';
        document.body.innerHTML = bottoms.map(bottom => `<figure><figcaption>Rear encounter · fictional dock ${bottom}</figcaption><canvas width=200 height=320></canvas></figure>`).join('');
        [...document.querySelectorAll('canvas')].forEach((canvas, i) => {
          api.view.bottom = bottoms[i];
          const instance = Object.create(window.scenes.after); instance.init(api);
          instance.s.world.time = time; instance.s.world.distance = 10000 + time * 6900;
          const ctx = canvas.getContext('2d'); instance.draw(api, ctx);
          ctx.fillStyle = 'rgba(10,15,25,.82)'; ctx.fillRect(0, bottoms[i], 200, 320 - bottoms[i]);
        });
      };
      window.renderAltitudes = (usePoses, name = 'after') => {
        const samples = [['Low', preview.low], ['Middle', preview.middle], ['High', preview.high]];
        const api = usePoses ? window.poseApi : window.visualApi; api.view.bottom = 320;
        document.body.style.display = 'grid'; document.body.style.gridTemplateColumns = 'repeat(3, 400px)';
        document.body.innerHTML = samples.map(([label]) => `<figure><figcaption>${label} altitude · fictional art</figcaption><canvas width=200 height=320></canvas></figure>`).join('');
        [...document.querySelectorAll('canvas')].forEach((canvas, i) => {
          const instance = Object.create(window.scenes[name]); instance.init(api);
          instance.s.world.time = samples[i][1]; instance.s.world.distance = 15700;
          instance.draw(api, canvas.getContext('2d'));
        });
      };
      window.renderAscent = name => {
        const samples = ascentPreview[name], api = window.poseApi; api.view.bottom = 320;
        document.body.style.display = 'grid'; document.body.style.gridTemplateColumns = 'repeat(6, 200px)';
        document.body.innerHTML = samples.map(({altitude}) => `<figure><figcaption>Ascent ${Math.round(altitude * 100)}% · same cloud</figcaption><canvas width=200 height=320 style="width:200px;height:320px"></canvas></figure>`).join('');
        [...document.querySelectorAll('canvas')].forEach((canvas, i) => {
          const instance = Object.create(window.scenes[name]); instance.init(api);
          instance.s.world.time = samples[i].time; instance.s.world.distance = samples[i].distance;
          const ctx = canvas.getContext('2d'); instance.draw(api, ctx);
          const cloud = samples[i].cloud;
          if (cloud) { ctx.strokeStyle = '#ffe787'; ctx.lineWidth = 1; ctx.strokeRect(Math.round(cloud.x - 8), Math.round(cloud.y - 6), 16, 12); }
        });
      };
      window.exerciseVisual = name => {
        const api = window.visualApi, instance = Object.create(window.scenes[name]); instance.init(api);
        const canvas = document.createElement('canvas'); canvas.width = 200; canvas.height = 320;
        const sink = canvas.getContext('2d'), holes = [];
        for (const bottom of [110, 186, 320]) for (let time = 0; time < 12; time += .5) {
          api.view.bottom = bottom; instance.s.world.time = time; instance.s.world.distance = 10000 + time * 6900;
          instance.draw(api, sink);
          for (const [x, y] of [[0, 0], [199, 0], [0, 319], [199, 319]]) {
            if (sink.getImageData(x, y, 1, 1).data[3] !== 255) holes.push([bottom, time, x, y]);
          }
        }
        instance.poke(api, 100, 100);
        const boost = instance.s.world.boost;
        api.view.bottom = 320;
        for (let i = 0; i < 20; i++) { instance.s.world.time = i / 30; instance.s.world.distance = 10000 + i * 33; instance.draw(api, sink); }
        const timings = [];
        for (let i = 0; i < 90; i++) {
          instance.s.world.time = i / 30; instance.s.world.distance = 10000 + i * 33;
          const start = performance.now(); instance.draw(api, sink); timings.push(performance.now() - start);
        }
        timings.sort((a, b) => a - b);
        return {holes, boost, medianMs: timings[45], p95Ms: timings[85], samples: timings.length};
      };
      window.compareDrawCosts = () => {
        const api = window.visualApi; api.view.bottom = 320;
        const rows = ['before', 'after'].map(name => {
          const instance = Object.create(window.scenes[name]); instance.init(api);
          const canvas = document.createElement('canvas'); canvas.width = 200; canvas.height = 320;
          return {name, instance, sink: canvas.getContext('2d'), times: []};
        });
        for (let i = 0; i < 240; i++) for (const row of (i % 2 ? rows : [rows[1], rows[0]])) {
          row.instance.s.world.time = i / 30; row.instance.s.world.distance = 10000 + i * 200;
          const start = performance.now(); row.instance.draw(api, row.sink);
          if (i >= 40) row.times.push(performance.now() - start);
        }
        return Object.fromEntries(rows.map(row => {
          row.times.sort((a, b) => a - b);
          return [row.name, {samples: row.times.length, medianMs: row.times[100], p95Ms: row.times[190]}];
        }));
      };
    }, {fixtureSeed, preview, rearPreview, ascentPreview});
    const poseStatus = await page.evaluate(() => {
      const instance = Object.create(window.scenes.after); instance.init(window.poseApi);
      return {player: !!instance.s.poses, enemies: !!instance.s.enemyPoses, clouds: !!instance.s.cloudPoses};
    });
    assert.deepEqual(poseStatus, {player: true, enemies: true, clouds: true}, 'the complete fictional pose atlas is used');
    const results = {};
    for (const name of baseline ? ['before', 'after'] : ['after']) {
      results[name] = await page.evaluate(name => window.exerciseVisual(name), name);
      await page.evaluate(name => window.renderVisual(name), name);
      await page.screenshot({path: path.join(out, name + '.png')});
      assert.deepEqual(results[name].holes, [], `${name}: transparent edges while banking`);
      assert.equal(results[name].boost, 3, `${name}: tap starts the boost`);
    }
    await page.evaluate(() => window.renderManeuvers(false));
    await page.screenshot({path: path.join(out, 'maneuvers.png')});
    await page.evaluate(() => window.renderManeuvers(true));
    await page.screenshot({path: path.join(out, 'maneuvers-pose-grid.png')});
    await page.evaluate(() => window.renderCompact());
    await page.screenshot({path: path.join(out, 'compact-pose-grid.png')});
    await page.evaluate(() => window.renderRear());
    await page.screenshot({path: path.join(out, 'rear-encounter.png')});
    await page.evaluate(() => window.renderRearDock());
    await page.screenshot({path: path.join(out, 'rear-dock.png')});
    if (baseline) {
      await page.evaluate(() => window.renderAltitudes(true, 'before'));
      await page.screenshot({path: path.join(out, 'altitudes-before.png')});
      await page.evaluate(() => window.renderCompact('before'));
      await page.screenshot({path: path.join(out, 'compact-before.png')});
      await page.evaluate(() => window.renderAscent('before'));
      await page.screenshot({path: path.join(out, 'ascent-before.png')});
    }
    await page.evaluate(() => window.renderAltitudes(false));
    await page.screenshot({path: path.join(out, 'altitudes-procedural.png')});
    await page.evaluate(() => window.renderAltitudes(true));
    await page.screenshot({path: path.join(out, 'altitudes-pose-grid.png')});
    await page.evaluate(() => window.renderAscent('after'));
    await page.screenshot({path: path.join(out, 'ascent-after.png')});
    const paired = baseline ? await page.evaluate(() => window.compareDrawCosts()) : null;
    assert.deepEqual(problems, []);
    console.log(JSON.stringify({fictionalAtlas: true, viewport: '1200x670', results, paired, output: out}));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
