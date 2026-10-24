// Reach experiment: enemy (Red) owns a single 4-star flower at origin + nothing else; Blue stamps its #2 flower at varying
// positions. Report min hex distance (Blue star empty-neighbour to nearest Red cell) at which Red can capture in 1 or 2 actions.
import { Game, idx, qr } from './fast.mjs';
import { bestCapture } from './bots.mjs';
import * as R from '../reference/rules.mjs';
const dist = (a, b) => { const [q1, r1] = qr(a), [q2, r2] = qr(b); const dq = q1 - q2, dr = r1 - r2; return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2; };
const base = R.setup();
// keep only Red's flower at (10,0) and Blue's flower at (-10,0)?  Use a custom board: Red flower around origin, Blue flower far away + test stamp.
function board() {
  const st = { ply: 1, scores: [0, 0], blueprints: base.blueprints, cells: {} };
  for (const [k, v] of Object.entries(base.cells)) { const [q, r] = R.parse(k); if (v[0] === 1 && q >= 1 && q <= 3) st.cells[R.key(q - 2, r)] = v; } // Red inner plain flower at origin
  return st;
}
const res = {};
for (let q = -12; q <= 12; q++) for (let r = -12; r <= 12; r++) {
  const st = board();
  const g = Game.fromRef(st);
  // put Blue #2 flower centred at (q,r) directly (as if stamped from elsewhere)
  const bp = g.hands[0][1]; const a = idx(q, r - 1);
  let ok = true; for (const o of bp.offs) { if (g.own[a + o] >= 0) ok = false; for (let d = 0; d < 6; d++) {} }
  if (!ok) continue;
  // blue cells must not touch red (else they'd be adjacent already) -> require min distance >= 2
  let md = 99; for (const o of bp.offs) for (const rc of g.occupied(1)) md = Math.min(md, dist(a + o, rc));
  if (md < 2) continue;
  for (let k = 0; k < bp.offs.length; k++) { g.own[a + bp.offs[k]] = 0; g.kind[a + bp.offs[k]] = bp.kinds[k]; }
  g.stars[0] += bp.stars; g.occ = null;
  g.ply = 1; const c2 = bestCapture(g, 1, 2)[1]; const c1 = bestCapture(g, 1, 1)[1];
  (res[md] ||= { n: 0, c1: 0, c2: 0 }); res[md].n++; if (c1) res[md].c1++; if (c2) res[md].c2++;
}
console.log('min dist blue-cell to red-cell : placements, capturable by 1 action, by 2 actions');
for (const [d, v] of Object.entries(res)) console.log(d, v.n, v.c1, v.c2);
