// Parallel round-robin tournament. Usage: node tourney.mjs configs.json gamesPerColorPerPair [workers]
// configs.json: [{name, ...params}] passed to makeBot (or {name, module, export, ...} for custom bots).
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import fs from 'node:fs';
import os from 'node:os';

async function loadBot(cfg) {
  if (cfg.module) { const m = await import(cfg.module); return m[cfg.export || 'default'](cfg); }
  const { makeBot } = await import('./bots.mjs');
  if (cfg.design) { const { DESIGNS } = await import('./designs.mjs'); const d = DESIGNS[cfg.design]; cfg = { ...cfg, designHand: d.hand, designCost: cfg.designCost ?? d.cost }; }
  if (cfg.plans) { const { PLANS } = await import('./d1plan.mjs'); cfg = { ...cfg, seq: { 0: PLANS[cfg.plans[0]].moves, 1: PLANS[cfg.plans[1]].moves } }; }
  return makeBot(cfg);
}

if (isMainThread) {
  const cfgs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const n = +(process.argv[3] || 4), W = +(process.argv[4] || os.cpus().length);
  const jobs = [];
  const onlyVs = process.env.VS; // if set, only pairings involving this name
  for (let i = 0; i < cfgs.length; i++) for (let j = 0; j < cfgs.length; j++) if (i !== j) {
    if (onlyVs && cfgs[i].name !== onlyVs && cfgs[j].name !== onlyVs) continue;
    for (let k = 0; k < n; k++) jobs.push([i, j, k]);
  }
  const res = cfgs.map(() => ({ w: 0, l: 0, d: 0, asBlue: [0, 0], asRed: [0, 0], margin: 0, pts: 0, games: 0 }));
  const pair = {};
  let done = 0; const t0 = Date.now();
  await new Promise((resolve) => {
    let next = 0, active = 0;
    const spawn = () => {
      if (next >= jobs.length) { if (active === 0) resolve(); return; }
      const job = jobs[next++]; active++;
      const w = new Worker(new URL(import.meta.url), { workerData: { cfgs, job } });
      w.on('message', ({ scores }) => {
        const [i, j] = job; const [a, b] = scores;
        const ri = res[i], rj = res[j];
        ri.games++; rj.games++; ri.margin += a - b; rj.margin += b - a; ri.pts += a; rj.pts += b;
        const key = `${cfgs[i].name} (B) vs ${cfgs[j].name} (R)`; pair[key] = pair[key] || [0, 0, 0]; pair[key][a > b ? 0 : a < b ? 1 : 2]++;
        if (a > b) { ri.w++; rj.l++; ri.asBlue[0]++; rj.asRed[1]++; } else if (b > a) { rj.w++; ri.l++; rj.asRed[0]++; ri.asBlue[1]++; } else { ri.d++; rj.d++; }
        done++;
      });
      w.on('error', (e) => { console.error(e); });
      w.on('exit', () => { active--; spawn(); });
    };
    for (let k = 0; k < W; k++) spawn();
  });
  console.log(`games ${done} in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  const rows = cfgs.map((c, i) => ({ name: c.name, ...res[i], winPct: (100 * (res[i].w + res[i].d / 2) / res[i].games).toFixed(1), avgMargin: (res[i].margin / res[i].games).toFixed(0), avgPts: (res[i].pts / res[i].games).toFixed(0) }));
  rows.sort((a, b) => b.winPct - a.winPct);
  for (const r of rows) console.log(`${r.name.padEnd(22)} win% ${r.winPct.padStart(5)}  W-L-D ${r.w}-${r.l}-${r.d}  blue ${r.asBlue.join('-')} red ${r.asRed.join('-')}  avgMargin ${r.avgMargin} avgPts ${r.avgPts}`);
  if (process.env.PAIRS) for (const [k, v] of Object.entries(pair)) console.log(k, v.join('-'));
} else {
  const { cfgs, job } = workerData;
  const { playGame } = await import('./bots.mjs');
  const a = await loadBot(cfgs[job[0]]), b = await loadBot(cfgs[job[1]]);
  const r = playGame(a, b);
  parentPort.postMessage({ scores: r.scores });
}
