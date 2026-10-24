// Execute a logical edit plan from the start hand and emit exact move strings (validated against R.editMoves).
// Logical coords: each blueprint keeps the coordinates it had at start (flower centre at (0,0)), independent of normalization.
import * as R from '../reference/rules.mjs';
export function runPlan(seat, steps) {
  let hand = R.setup().blueprints[seat];
  // logical = normalized + shift ; at start flower normalized has centre at (0,1) -> shift (0,-1)
  let shift = hand.map(() => [0, -1]);
  const moves = [];
  for (const [fi, from, ti, to] of steps) {
    const fk = R.key(from[0] - shift[fi][0], from[1] - shift[fi][1]);
    const tk = R.key(to[0] - shift[ti][0], to[1] - shift[ti][1]);
    if (!(fk in hand[fi])) throw new Error(`no cell ${from} in #${fi + 1}`);
    const mv = `${fi + 1}:${fk}>${ti + 1}:${tk}`;
    if (!R.editMoves(hand).includes(mv)) throw new Error(`illegal ${mv} (logical ${fi + 1}:${from}>${ti + 1}:${to})`);
    moves.push(mv);
    const { hand: h2, shifts } = R.applyEdit(hand, R.parseMove(mv));
    // applyEdit normalizes; if target was empty, key placed at given spot then normalized
    shift = shift.map((s, i) => [s[0] - shifts[i][0], s[1] - shifts[i][1]]);
    hand = h2;
  }
  return { moves, hand, shift };
}
export function draw(bp) {
  const ks = Object.keys(bp).map(R.parse); const rmin = Math.min(...ks.map((k) => k[1])), rmax = Math.max(...ks.map((k) => k[1]));
  const xs = ks.map(([q, r]) => 2 * q + r); const xmin = Math.min(...xs), xmax = Math.max(...xs); const out = [];
  for (let r = rmin; r <= rmax; r++) { let l = ''; for (let x = xmin; x <= xmax; x++) { if ((x - r) % 2) { l += ' '; continue; } const q = (x - r) / 2; const v = bp[R.key(q, r)]; l += v ? { star: '*', wall: '#', plain: 'o' }[v] : '.'; } out.push(l); }
  return out.join('\n');
}
