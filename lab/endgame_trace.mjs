// Trace Fortlite mirror games: points scored by ply bucket and by last turns.
import { makeBot } from './bots.mjs';
import { Game } from './fast.mjs';
import { PLANS } from './d1plan.mjs';
const seq = { 0: PLANS.blue_fort.moves, 1: PLANS.red_fort.moves };
const N = +(process.argv[2] || 4);
const buckets = {}; const last = { b119: 0, r117_118: 0, b115_116: 0 }; let tot = [0, 0], wins = [0, 0];
for (let gi = 0; gi < N; gi++) {
  const A = makeBot({ wStar: 0.5, wThreat: 1, noise: 0.5, seq }), B = makeBot({ wStar: 0.5, wThreat: 1, noise: 0.5, seq });
  const g = Game.start(); const bots = [A, B];
  while (g.ply < 120) { const s = g.seat(); const t = bots[s](g); for (const m of t) { if (g.seat() !== s || g.ply >= 120) break; if (m === 'pass') { g.pass(); continue; } if (m.edit) { g.edit(m.edit); continue; } const p = g.ply; const u = g.place(m.b, m.a); const bk = Math.floor(p / 20) * 20; buckets[bk] = (buckets[bk] || 0) + u.pts; if (p === 119) last.b119 += u.pts; if (p === 117 || p === 118) last.r117_118 += u.pts; if (p === 115 || p === 116) last.b115_116 += u.pts; } }
  tot[0] += g.scores[0]; tot[1] += g.scores[1]; wins[g.scores[0] > g.scores[1] ? 0 : 1]++;
  console.log('game', gi, g.scores, g.stars);
}
console.log('points by ply bucket (both sides):', buckets, 'last turns:', last, 'avg', tot.map((x) => x / N), 'wins B/R', wins);
