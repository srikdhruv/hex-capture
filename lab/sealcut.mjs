// Minimum number of empty hexes that must become own WALLS so that no path from far outside reaches any of seat s's
// stars through empty / own non-wall cells (min vertex cut, unit capacity on empty cells). Start position by default.
import { Game, NB, S, STAR, WALL, idx, qr } from './fast.mjs';
export function minSeal(g, s, starsFilter = null) {
  let qmin = 1e9, qmax = -1e9, rmin = 1e9, rmax = -1e9;
  for (const t of [0, 1]) for (const i of g.occupied(t)) { const [q, r] = qr(i); qmin = Math.min(qmin, q); qmax = Math.max(qmax, q); rmin = Math.min(rmin, r); rmax = Math.max(rmax, r); }
  qmin -= 3; qmax += 3; rmin -= 3; rmax += 3;
  const cells = []; const id = new Map();
  for (let r = rmin; r <= rmax; r++) for (let q = qmin; q <= qmax; q++) { const i = idx(q, r); if (g.own[i] === s && g.kind[i] === WALL) continue; id.set(i, cells.length); cells.push(i); }
  // node split: in = 2k, out = 2k+1 ; SRC = 2N, SNK = 2N+1
  const N = cells.length, SRC = 2 * N, SNK = 2 * N + 1, INF = 1e9;
  const head = new Int32Array(2 * N + 2).fill(-1), to = [], cap = [], nxt = [];
  const add = (u, v, c) => { to.push(v); cap.push(c); nxt.push(head[u]); head[u] = to.length - 1; to.push(u); cap.push(0); nxt.push(head[v]); head[v] = to.length - 1; };
  cells.forEach((i, k) => {
    const [q, r] = qr(i); const empty = g.own[i] < 0;
    add(2 * k, 2 * k + 1, empty ? 1 : INF);
    if (q === qmin || q === qmax || r === rmin || r === rmax) add(SRC, 2 * k, INF);
    if (g.own[i] === s && g.kind[i] === STAR && (!starsFilter || starsFilter(i))) add(2 * k + 1, SNK, INF);
    for (let d = 0; d < 6; d++) { const n = i + NB[d]; if (id.has(n)) add(2 * k + 1, 2 * id.get(n), INF); }
  });
  let flow = 0; const capA = Int32Array.from(cap.map((c) => Math.min(c, 1e9)));
  for (;;) { // BFS augment
    const prev = new Int32Array(2 * N + 2).fill(-1); prev[SRC] = -2; const qu = [SRC];
    for (let h = 0; h < qu.length && prev[SNK] === -1; h++) { const u = qu[h]; for (let e = head[u]; e !== -1; e = nxt[e]) if (capA[e] > 0 && prev[to[e]] === -1) { prev[to[e]] = e; qu.push(to[e]); } }
    if (prev[SNK] === -1) break;
    let v = SNK, f = INF; while (v !== SRC) { const e = prev[v]; f = Math.min(f, capA[e]); v = to[e ^ 1]; }
    v = SNK; while (v !== SRC) { const e = prev[v]; capA[e] -= f; capA[e ^ 1] += f; v = to[e ^ 1]; }
    flow += f; if (flow >= INF) return Infinity;
  }
  return flow;
}
if (process.argv[1] && process.argv[1].endsWith('sealcut.mjs')) {
  const g = Game.start();
  for (const s of [0, 1]) {
    console.log(`seat ${s}: walls to seal all 6 start stars:`, minSeal(g, s));
    const stars = g.occupied(s).filter((i) => g.kind[i] === STAR);
    for (const st of stars) console.log('   star', qr(st).join(','), 'alone:', minSeal(g, s, (i) => i === st));
  }
}
