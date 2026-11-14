// usage: node render.mjs <serverRoot> <modelUrl> <outDir> [scale]
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
import fs from 'fs';
const [,, base, model, out, scale='1'] = process.argv;
const VIEWS = {
  '01_front':         [0, 10, 0.34, 0.056, 28],
  '02_left_side':     [80, 22, 0.34, 0.058, 28],
  '03_back':          [180, 20, 0.34, 0.058, 28],
  '04_right_side':    [-95, 6, 0.34, 0.058, 28],
  '05_top':           [10, 72, 0.34, 0.06, 28],
  '06_three_quarter': [35, 38, 0.30, 0.07, 28],
  'closeup_face':     [12, 12, 0.17, 0.085, 28],
};
fs.mkdirSync(out, {recursive:true});
const browser = await chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page = await browser.newPage({viewport:{width:1600,height:1200}, deviceScaleFactor:+scale});
page.on('console', m => { if (m.type()==='error') console.log('console:', m.text()); });
await page.goto(`${base}/render.html?model=${encodeURIComponent(model)}&w=1600&h=1200`);
await page.waitForFunction(() => window.ready || window.loadError, null, {timeout: 300000});
const err = await page.evaluate(() => window.loadError);
if (err) { console.error('LOAD ERROR', err); process.exit(1); }
console.log(JSON.stringify(await page.evaluate(() => window.stats)));
for (const [name, v] of Object.entries(VIEWS)) {
  await page.evaluate(v => window.view(...v), v);
  await page.screenshot({path: `${out}/${name}.png`});
}
await browser.close();
