// For a given Blue first move, enumerate all Red 2-placement turns; report how many are safe (Blue cannot capture next turn)
// and list Red turns that create the most immediate threat on Blue (Red's best capture available next Red turn if Blue passes).
import { Game } from './fast.mjs';
import { bestCapture } from './bots.mjs';
const bm = process.argv[2] || '2@-13,0';
const g = Game.start(); g.playString(bm);
const pl = g.placements(1); const rows = [];
const seen = new Set();
for (let j = 0; j < pl.length; j += 2) {
  const u = g.place(pl[j], pl[j + 1]); const m1 = g.moveString(pl[j], pl[j + 1]);
  const pl2 = g.placements(1);
  for (let k = 0; k < pl2.length; k += 2) {
    const m2 = g.moveString(pl2[k], pl2[k + 1]);
    const key = [m1, m2].sort().join(' '); if (seen.has(key)) continue; seen.add(key);
    const u2 = g.place(pl2[k], pl2[k + 1]);
    const [bp, bs] = bestCapture(g, 0, 2);
    rows.push([m1, m2, g.stars[1], bp, bs, g.scores[1]]);
    g.undo(u2);
  }
  g.undo(u);
}
const safe = rows.filter((r) => r[3] === 0);
console.log(`Blue ${bm}: Red turns ${rows.length}, safe ${safe.length}; red captures possible: ${rows.filter(r=>r[5]>0).length}`);
const by = {}; for (const r of safe) by[r[2]] = (by[r[2]] || 0) + 1; console.log('safe by red star count', by);
const s14 = safe.filter(r => r[2] === 14); console.log('example safe double-#2 turns:', s14.slice(0, 12).map(r => r[0] + ' ' + r[1]).join(' | '));
