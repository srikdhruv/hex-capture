// Which small probe shapes (1-3 plains) crack which shield designs, and for how many stars, in ONE enemy turn.
// Enemy (Red) = inner flower at origin + hand [P, Red Fortlite #2 (big eraser), P]. Our design stamp placed at gaps 2..6.
import { Game, idx, qr, compile } from './fast.mjs';
import { bestCapture } from './bots.mjs';
import { PLANS } from './d1plan.mjs';
import * as R from '../reference/rules.mjs';
const dist = (a, b) => { const [q1, r1] = qr(a), [q2, r2] = qr(b); const dq = q1 - q2, dr = r1 - r2; return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2; };
// fixed polyhexes up to size 3
function polys(n) {
  let cur = new Set([JSON.stringify(R.normalize({ '0,0': 'plain' })[0])]);
  const all = [...cur];
  for (let s = 2; s <= n; s++) {
    const nx = new Set();
    for (const p of cur) { const bp = JSON.parse(p); for (const k of Object.keys(bp)) for (const nb of R.neighbors(k)) if (!(nb in bp)) { const b2 = { ...bp, [nb]: 'plain' }; nx.add(JSON.stringify(R.normalize(Object.fromEntries(Object.entries(b2).sort()))[0], Object.keys(R.normalize(b2)[0]).sort())); } }
    cur = nx; all.push(...nx);
  }
  return [...new Set(all.map((s) => JSON.stringify(Object.keys(JSON.parse(s)).sort())))].map((s) => Object.fromEntries(JSON.parse(s).map((k) => [k, 'plain'])));
}
const base = R.setup();
export function crack(designBp, probe, big = PLANS.red_fort.hand[1]) {
  let best = 0, where = null;
  for (let q = -9; q <= 9; q++) for (let r = -9; r <= 9; r++) {
    const st = { ply: 1, scores: [0, 0], blueprints: [base.blueprints[0], [probe, big, probe]], cells: {} };
    for (const [k, v] of Object.entries(base.cells)) { const [qq, rr] = R.parse(k); if (v[0] === 1 && qq >= 1 && qq <= 3) st.cells[R.key(qq - 2, rr)] = v; }
    const g = Game.fromRef(st); const bp = compile(designBp); const a = idx(q, r);
    let ok = true; for (const o of bp.offs) if (g.own[a + o] >= 0) ok = false; if (!ok) continue;
    let md = 99; for (const o of bp.offs) for (const rc of g.occupied(1)) md = Math.min(md, dist(a + o, rc)); if (md < 2 || md > 5) continue;
    for (let k = 0; k < bp.offs.length; k++) { g.own[a + bp.offs[k]] = 0; g.kind[a + bp.offs[k]] = bp.kinds[k]; }
    g.stars[0] += bp.stars; g.occ = null;
    const c2 = bestCapture(g, 1, 2)[1]; if (c2 > best) { best = c2; where = [q, r, md]; }
  }
  return best;
}
const P = polys(3);
const show = (bp) => Object.keys(bp).join(' ');
const designs = { fortlite: PLANS.blue_fort.hand[1], 'D2 fortlite-5P': PLANS.blue_d2.hand[1], 'fort18': PLANS.blue_d1.hand[1], hex19: PLANS.blue_fort19.hand[1] };
if (process.argv[1].endsWith('probes.mjs')) {
  console.log('probes:', P.length);
  for (const [dn, d] of Object.entries(designs)) {
    const row = P.map((p) => crack(d, p));
    console.log(dn.padEnd(16), P.map((p, i) => `[${show(p)}]:${row[i]}`).join('  '));
  }
}
