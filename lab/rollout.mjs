// Evaluate opening prefixes by noisy bot-vs-bot rollouts in parallel.
// Usage: node rollout.mjs prefixes.json gamesPerPrefix [botcfg.json]
// prefixes.json: [{name, moves:[...]}]; output: Blue win% and avg margin per prefix.
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import fs from 'node:fs';
import os from 'node:os';

if (isMainThread) {
  const prefixes = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const n = +(process.argv[3] || 16);
  const bot = process.argv[4] ? JSON.parse(fs.readFileSync(process.argv[4], 'utf8')) : { name: 'r', wStar: 0.5, wThreat: 1, noise: 2 };
  const jobs = []; prefixes.forEach((p, i) => { for (let k = 0; k < n; k++) jobs.push(i); });
  const res = prefixes.map(() => ({ bw: 0, n: 0, margin: 0 }));
  let next = 0, active = 0; const W = +(process.env.W || os.cpus().length);
  await new Promise((resolve) => {
    const spawn = () => {
      if (next >= jobs.length) { if (!active) resolve(); return; }
      const i = jobs[next++]; active++;
      const w = new Worker(new URL(import.meta.url), { workerData: { moves: prefixes[i].moves, bot } });
      w.on('message', ({ scores: [a, b] }) => { const r = res[i]; r.n++; r.margin += a - b; r.bw += a > b ? 1 : a === b ? 0.5 : 0; });
      w.on('error', (e) => console.error(e));
      w.on('exit', () => { active--; spawn(); });
    };
    for (let k = 0; k < W; k++) spawn();
  });
  const rows = prefixes.map((p, i) => [p.name, (100 * res[i].bw / res[i].n).toFixed(0), (res[i].margin / res[i].n).toFixed(0), res[i].n]);
  rows.sort((a, b) => b[2] - a[2]);
  for (const r of rows) console.log(`${r[0].padEnd(40)} blueWin% ${r[1].padStart(3)} avgMargin(B-R) ${r[2].padStart(6)} n=${r[3]}`);
} else {
  const { Game } = await import('./fast.mjs');
  const { makeBot, playGame } = await import('./bots.mjs');
  const g = Game.start();
  for (const m of workerData.moves) g.playString(m);
  const b = makeBot(workerData.bot);
  const r = playGame(b, b, { start: g });
  parentPort.postMessage({ scores: r.scores });
}
