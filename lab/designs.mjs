// Candidate reshaped hands (reference blueprint format) and their approximate edit cost (# of cells moved).
import * as R from '../reference/rules.mjs';
const D = R.DIRS;
const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
function bpFrom(list) { const o = {}; for (const [q, r, k] of list) o[R.key(q, r)] = k; return R.normalize(o)[0]; }
const start = R.setup().blueprints;
// ring1 kinds of each seat's #2 (in DIRS order)
const RING = [['wall', 'star', 'wall', 'star', 'wall', 'star'], ['star', 'wall', 'star', 'wall', 'star', 'wall']];
const ring2 = []; for (let d = 0; d < 6; d++) { ring2.push(add(D[d], D[d])); ring2.push(add(D[d], D[(d + 1) % 6])); }
function fortlite(seat) {
  // flower #2 + plains on ring2 cells adjacent to ring-1 stars
  const cells = [[0, 0, 'star']]; const ring = RING[seat];
  D.forEach((d, i) => cells.push([d[0], d[1], ring[i]]));
  const need = new Set();
  D.forEach((d, i) => { if (ring[i] === 'star') for (const n of R.neighbors(R.key(...d))) { const [q, r] = R.parse(n); if (Math.max(Math.abs(q), Math.abs(r), Math.abs(q + r)) === 2) need.add(n); } });
  for (const k of need) { const [q, r] = R.parse(k); cells.push([q, r, 'plain']); }
  return [bpFrom([[0, 0, 'star'], [1, 0, 'plain'], [0, 1, 'plain'], [1, -1, 'plain']]), bpFrom(cells), bpFrom([[0, 0, 'star']])];
}
function fort19(seat) {
  const cells = [[0, 0, 'star']]; D.forEach((d, i) => cells.push([d[0], d[1], i === 0 ? 'wall' : 'star']));
  ring2.forEach(([q, r], i) => cells.push([q, r, i === 0 || i === 6 ? 'wall' : 'plain']));
  return [bpFrom([[0, 0, 'plain']]), bpFrom(cells), bpFrom([[0, 0, 'plain']])];
}
function star6(seat) { // #2 + both lone stars attached compactly (what the edit plan produces)
  const h = start[seat].map((b) => ({ ...b }));
  return null;
}
function sniper(seat) { // #1 -> single plain, its 6 other cells appended to #3 (13 cells)
  const h = start[seat];
  const c3 = [[0, 0, 'star']]; D.forEach((d) => c3.push([d[0], d[1], 'plain']));
  c3.push([2, 0, 'plain'], [2, -1, 'plain'], [1, 1, 'plain'], [-1, 2, 'plain'], [-2, 2, 'star'], [-2, 1, 'plain']);
  return [bpFrom([[0, 0, 'plain']]), h[1], bpFrom(c3)];
}
export const DESIGNS = {
  fortlite: { cost: 9, hand: fortlite },
  fort19: { cost: 14, hand: fort19 },
  sniper: { cost: 6, hand: sniper },
};
function count(h) { const c = { star: 0, wall: 0, plain: 0 }; for (const b of h) for (const v of Object.values(b)) c[v]++; return c; }
if (process.argv[1] && process.argv[1].endsWith('designs.mjs')) for (const [n, d] of Object.entries(DESIGNS)) for (const s of [0, 1]) { const h = d.hand(s); console.log(n, s, JSON.stringify(count(h)), h.map((b) => Object.keys(b).length)); }
