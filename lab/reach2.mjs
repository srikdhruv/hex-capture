// Vulnerability of a sealed Fortlite #2 stamp vs enemy hands, by gap distance. Enemy = Red inner flower at origin.
import { Game, idx, qr, compile } from './fast.mjs';
import { bestCapture } from './bots.mjs';
import { PLANS } from './d1plan.mjs';
import * as R from '../reference/rules.mjs';
const dist = (a, b) => { const [q1, r1] = qr(a), [q2, r2] = qr(b); const dq = q1 - q2, dr = r1 - r2; return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2; };
const base = R.setup();
function run(blueBp, redHand, label) {
  const res = {};
  for (let q = -14; q <= 14; q++) for (let r = -14; r <= 14; r++) {
    const st = { ply: 1, scores: [0, 0], blueprints: [base.blueprints[0], redHand], cells: {} };
    for (const [k, v] of Object.entries(base.cells)) { const [qq, rr] = R.parse(k); if (v[0] === 1 && qq >= 1 && qq <= 3) st.cells[R.key(qq - 2, rr)] = v; }
    const g = Game.fromRef(st); const bp = compile(blueBp); const a = idx(q, r);
    let ok = true; for (const o of bp.offs) if (g.own[a + o] >= 0) ok = false; if (!ok) continue;
    let md = 99; for (const o of bp.offs) for (const rc of g.occupied(1)) md = Math.min(md, dist(a + o, rc)); if (md < 2) continue;
    for (let k = 0; k < bp.offs.length; k++) { g.own[a + bp.offs[k]] = 0; g.kind[a + bp.offs[k]] = bp.kinds[k]; }
    g.stars[0] += bp.stars; g.occ = null;
    const c2 = bestCapture(g, 1, 2)[1];
    (res[md] ||= { n: 0, c2: 0, maxSt: 0 }); res[md].n++; if (c2) res[md].c2++; res[md].maxSt = Math.max(res[md].maxSt, c2);
  }
  console.log(label); for (const [d, v] of Object.entries(res)) if (+d <= 9) console.log(`  gap ${d}: capturable ${v.c2}/${v.n} max stars ${v.maxSt}`);
}
const std = base.blueprints[1];
run(base.blueprints[0][1], std, 'plain 4-star flower vs standard hand');
run(PLANS.blue_fort.hand[1], std, 'Fortlite #2 vs standard hand (flowers only)');
run(PLANS.blue_fort.hand[1], PLANS.red_fort.hand, 'Fortlite #2 vs Fortlite hand (has 1-hex sniper)');
run(PLANS.blue_d1.hand[1], PLANS.red_fort.hand, 'Fort18 #2 vs Fortlite hand');
run(PLANS.blue_fort19.hand[1], PLANS.red_fort.hand, 'Hex19 #2 vs Fortlite hand');
