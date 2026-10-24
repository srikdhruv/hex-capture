// Reconstruct the full move list of a live game log (client/logs/game-*.jsonl) by matching consecutive states.
import fs from 'node:fs';
import * as R from '../reference/rules.mjs';
const f = process.argv[2];
const L = fs.readFileSync(f, 'utf8').trim().split('\n').map((l) => JSON.parse(l)).filter((x) => x.type === 'state' && x.state.view);
const byPly = new Map(); for (const x of L) byPly.set(x.state.ply, x.state);
const plies = [...byPly.keys()].sort((a, b) => a - b);
const norm = (v) => ({ ply: v.ply, cells: v.cells, blueprints: v.blueprints, scores: v.scores });
const canon = (s) => JSON.stringify([s.ply, Object.entries(s.cells).sort(), s.blueprints.map((h) => h.map((b) => Object.entries(b).sort())), s.scores]);
let st = R.setup(); const moves = []; const seats = byPly.get(plies[0]).seats;
for (let p = 0; p < plies[plies.length - 1]; p++) {
  const target = byPly.get(p + 1);
  if (!target) { // jump to next available state
    const nx = plies.find((x) => x > p + 1); if (nx === undefined) break;
    const sv = byPly.get(nx); st = norm({ ...sv.view, ply: sv.ply }); for (let k = p; k < nx; k++) moves.push('?'); p = nx - 1; continue;
  }
  const tv = norm({ ...target.view, ply: target.ply });
  let found = null;
  for (const m of [...R.legalMoves(st), 'pass']) { const n = R.play(st, m); if (canon(n) === canon(tv)) { found = m; st = n; break; } }
  if (!found) { console.error('no match at ply', p); break; }
  moves.push(found);
}
const out = { seats, moves, final: st.scores, hands: st.blueprints };
console.log(JSON.stringify(out));
