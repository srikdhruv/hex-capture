// Reference rules for StrategyJam "Blueprints" (game version 3).
// Ported verbatim (de-minified) from https://strategyjam.org/g/blueprints/index-BY7APeWO.js
// This is the ground truth: any fast engine must match setup/legalMoves/play exactly.
export const WALL = 'wall', STAR = 'star', PLAIN = 'plain';
// Axial hex directions (q, r).
export const DIRS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];
export const key = (q, r) => `${q},${r}`;
export const parse = (k) => k.split(',').map(Number);
export const neighbors = (k) => { const [q, r] = parse(k); return DIRS.map(([a, b]) => key(q + a, r + b)); };
export const TOTAL_PLIES = 120;

export function parseMove(m) {
  const [a, b, c, d] = m.split(/[@:>]/);
  return m.includes('@')
    ? { type: 'place', blueprint: a - 1, at: parse(b) }
    : { type: 'edit', from: [a - 1, b], to: [c - 1, d] };
}
// Seat to move at a ply: Blue(0) moves once, then Red, Blue alternate pairs.
export const turnOf = (ply) => (ply === 0 || ((ply - 1) >> 1) % 2 === 1 ? 0 : 1);
export const movesLeftInTurn = (ply) => (ply === 0 ? 1 : Math.min(2 - ((ply - 1) % 2), TOTAL_PLIES - ply));

// Lowest r, then lowest q, cell is shifted to 0,0.
function minCell(keys) {
  let best = null;
  for (const k of keys) { const [q, r] = parse(k); if (!best || r < best[1] || (r === best[1] && q < best[0])) best = [q, r]; }
  return key(...best);
}
export function normalize(bp) {
  if (!Object.keys(bp).length) return [bp, [0, 0]];
  const [q0, r0] = parse(minCell(Object.keys(bp)));
  if (q0 === 0 && r0 === 0) return [bp, [0, 0]];
  const out = {};
  for (const [k, v] of Object.entries(bp)) { const [q, r] = parse(k); out[key(q - q0, r - r0)] = v; }
  return [out, [-q0, -r0]];
}
function flower(ring) { const bp = { [key(0, 0)]: STAR }; DIRS.forEach(([a, b], i) => { bp[key(a, b)] = ring[i]; }); return normalize(bp)[0]; }
const N = [PLAIN, PLAIN, PLAIN, PLAIN, PLAIN, PLAIN];
const START_RINGS = [
  [N, [WALL, STAR, WALL, STAR, WALL, STAR], N],
  [N, [STAR, WALL, STAR, WALL, STAR, WALL], N],
];
const START_X = [[-6, -10, -2], [6, 10, 2]];
const without = (bp, k) => { const { [k]: _, ...rest } = bp; return rest; };

export function applyEdit(hand, { from: [fi, fk], to: [ti, tk] }) {
  const out = [...hand]; const kind = hand[fi][fk];
  out[fi] = without(out[fi], fk); out[ti] = { ...out[ti], [tk]: kind };
  const shifts = hand.map(() => [0, 0]);
  for (const i of new Set([fi, ti])) [out[i], shifts[i]] = normalize(out[i]);
  return { hand: out, shifts };
}

// Stamp blueprint bp for seat at offset; returns stamped cells and opponent cells removed.
export function stamp(cells, seat, bp, [dq, dr]) {
  const stamped = Object.entries(bp).map(([k, v]) => { const [q, r] = parse(k); return [key(q + dq, r + dr), v]; });
  const removed = new Set();
  for (const [k] of stamped) for (const n of neighbors(k)) { const c = cells[n]; if (c && c[0] !== seat && c[1] !== WALL) removed.add(n); }
  return { stamped, removed };
}
export const starCounts = (cells) => { const t = [0, 0]; for (const [s, kind] of Object.values(cells)) if (kind === STAR) t[s]++; return t; };
function points(cells, seat, { removed }) { let n = 0; for (const k of removed) if (cells[k][1] === STAR) n++; return n * starCounts(cells)[seat]; }

function flood(start, ok) { const seen = new Set([start]), stack = [start]; while (stack.length) for (const n of neighbors(stack.pop())) if (ok(n) && !seen.has(n)) { seen.add(n); stack.push(n); } return seen; }
export const connected = (keys) => !keys.length || flood(keys[0], (k) => keys.includes(k)).size === keys.length;

export function setup() {
  const blueprints = START_RINGS.map((hand) => hand.map(flower));
  const cells = {};
  blueprints.forEach((hand, seat) => hand.forEach((bp, i) => {
    for (const [k, v] of stamp({}, seat, bp, [START_X[seat][i], -1]).stamped) cells[k] = [seat, v];
  }));
  return { ply: 0, cells, blueprints, scores: [0, 0] };
}

export function placeMoves(cells, frontier, bp, idx) {
  const offs = Object.keys(bp).map(parse), seen = new Set(), out = [];
  for (const f of frontier) {
    const [fq, fr] = parse(f);
    for (const [bq, br] of offs) {
      const dq = fq - bq, dr = fr - br, k = key(dq, dr);
      if (seen.has(k)) continue; seen.add(k);
      if (offs.every(([q, r]) => !cells[key(q + dq, r + dr)])) out.push(`${idx + 1}@${k}`);
    }
  }
  return out;
}
export function editMoves(hand) {
  const out = [];
  hand.forEach((bp, fi) => {
    for (const k of Object.keys(bp)) {
      const rest = without(bp, k), restKeys = Object.keys(rest), restOk = connected(restKeys);
      hand.forEach((other, ti) => {
        if (fi !== ti && !restOk) return;
        const target = fi === ti ? rest : other;
        const spots = new Set(Object.keys(target).length ? [] : [key(0, 0)]);
        for (const t of Object.keys(target)) for (const n of neighbors(t)) if (!(n in target)) spots.add(n);
        if (fi === ti) spots.delete(k);
        for (const s of spots) if (fi !== ti || restOk || connected([...restKeys, s])) out.push(`${fi + 1}:${k}>${ti + 1}:${s}`);
      });
    }
  });
  return out;
}
export function legalMoves({ cells, blueprints, ply }) {
  if (ply >= TOTAL_PLIES) return [];
  const seat = turnOf(ply), frontier = new Set();
  for (const [k, [s]] of Object.entries(cells)) if (s === seat) for (const n of neighbors(k)) if (!cells[n]) frontier.add(n);
  const hand = blueprints[seat];
  return [...hand.flatMap((bp, i) => placeMoves(cells, frontier, bp, i)), ...editMoves(hand)];
}

export function play(state, move) {
  if (move === 'pass') return { ...state, ply: state.ply + 1 };
  const seat = turnOf(state.ply), m = parseMove(move);
  if (m.type === 'place') {
    const res = stamp(state.cells, seat, state.blueprints[seat][m.blueprint], m.at), cells = {};
    for (const [k, v] of Object.entries(state.cells)) if (!res.removed.has(k)) cells[k] = v;
    for (const [k, v] of res.stamped) cells[k] = [seat, v];
    const scores = [...state.scores]; scores[seat] += points(state.cells, seat, res);
    return { ply: state.ply + 1, cells, blueprints: state.blueprints, scores };
  }
  const { hand } = applyEdit(state.blueprints[seat], m);
  const blueprints = seat === 0 ? [hand, state.blueprints[1]] : [state.blueprints[0], hand];
  return { ply: state.ply + 1, cells: state.cells, blueprints, scores: state.scores };
}

export function result({ ply, scores: [a, b] }) {
  if (ply < TOTAL_PLIES) return null;
  return a === b ? { winner: null, reason: 'tied score' } : { winner: a > b ? 0 : 1, reason: 'higher score' };
}
