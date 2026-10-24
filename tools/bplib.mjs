// Shared helpers for Blueprints tools (greedy policy, analysis, rendering helpers).
// Ground truth rules live in reference/rules.mjs; everything here is built on top of them.
import * as R from '../reference/rules.mjs';
export { R };

const KINDS = { star: 'star', wall: 'wall', plain: 'plain', s: 'star', w: 'wall', p: 'plain', '*': 'star', o: 'plain' };
const normKind = (k) => KINDS[String(k).toLowerCase()] || String(k);

function normCell(v) {
  if (Array.isArray(v)) return [Number(v[0]), normKind(v[1])];
  if (v && typeof v === 'object') {
    const seat = v.seat ?? v.owner ?? v.player ?? v.s ?? v[0];
    const kind = v.kind ?? v.type ?? v.k ?? v[1];
    return [Number(seat), normKind(kind)];
  }
  return null;
}

// Accept cells as {"q,r": [seat, kind]} (rules format), {"q,r": {seat, kind}}, or [{q, r, seat, kind}].
export function normCells(cells) {
  const out = {};
  if (!cells) return out;
  if (Array.isArray(cells)) {
    for (const c of cells) {
      const k = c.key ?? (c.q !== undefined ? R.key(c.q, c.r) : null);
      const v = normCell(c.cell ?? c.v ?? c);
      if (k && v) out[k] = v;
    }
    return out;
  }
  for (const [k, v] of Object.entries(cells)) { const c = normCell(v); if (c) out[k] = c; }
  return out;
}

function normBp(bp) {
  if (Array.isArray(bp)) { const o = {}; for (const c of bp) o[c.key ?? R.key(c.q, c.r)] = normKind(c.kind ?? c.type); return o; }
  const o = {}; for (const [k, v] of Object.entries(bp || {})) o[k] = normKind(v); return o;
}

// Accept a full server state {view:{...}}, a bare view, or a rules state. Returns rules state + extras.
export function toState(input) {
  const view = input && input.view ? input.view : input;
  const state = {
    ply: Number(view.ply ?? input.ply ?? 0),
    cells: normCells(view.cells),
    blueprints: (view.blueprints || []).map((hand) => hand.map(normBp)),
    scores: (view.scores || [0, 0]).map(Number),
  };
  const moves = Array.isArray(view.moves) ? view.moves.slice() : R.legalMoves(state);
  return { state, moves, view, you: input.you };
}

export function toView(state) {
  const moves = R.legalMoves(state);
  return {
    ply: state.ply, turn: R.turnOf(state.ply), left: state.ply >= R.TOTAL_PLIES ? 0 : R.movesLeftInTurn(state.ply),
    cells: state.cells, blueprints: state.blueprints, scores: state.scores, stars: R.starCounts(state.cells),
    moves, result: R.result(state),
  };
}

export function replay(moves) {
  let s = R.setup();
  for (const m of moves) {
    const legal = R.legalMoves(s);
    if (m !== 'pass' && !legal.includes(m)) throw new Error(`illegal move ${m} at ply ${s.ply}`);
    s = R.play(s, m);
  }
  return s;
}

export function frontierOf(cells, seat) {
  const f = new Set();
  for (const [k, [s]] of Object.entries(cells)) if (s === seat) for (const n of R.neighbors(k)) if (!cells[n]) f.add(n);
  return f;
}

// Immediate effect of a placement for `seat` (no full play): points, removed stars/cells.
export function placeEffect(cells, seat, bp, at, myStars) {
  const { removed } = R.stamp(cells, seat, bp, at);
  let stars = 0; const starKeys = [];
  for (const k of removed) if (cells[k][1] === R.STAR) { stars++; starKeys.push(k); }
  return { points: stars * myStars, starsRemoved: stars, starKeys, removed: [...removed] };
}

// All placements by `seat` with its current hand, regardless of whose turn it is.
export function placementsFor(state, seat) {
  const frontier = frontierOf(state.cells, seat);
  const hand = state.blueprints[seat];
  const out = [];
  hand.forEach((bp, i) => { for (const m of R.placeMoves(state.cells, frontier, bp, i)) out.push(m); });
  return out;
}

// Threats: for every placement `attacker` could make, which of the victim's stars it removes.
export function threats(state, attacker) {
  const stars = R.starCounts(state.cells)[attacker];
  const res = [];
  for (const m of placementsFor(state, attacker)) {
    const pm = R.parseMove(m);
    const e = placeEffect(state.cells, attacker, state.blueprints[attacker][pm.blueprint], pm.at, stars);
    if (e.starsRemoved) res.push({ move: m, ...e });
  }
  res.sort((a, b) => b.points - a.points);
  return res;
}

export function maxThreat(state, attacker) {
  const stars = R.starCounts(state.cells)[attacker];
  let best = 0, bestMove = null;
  const frontier = frontierOf(state.cells, attacker);
  state.blueprints[attacker].forEach((bp, i) => {
    for (const m of R.placeMoves(state.cells, frontier, bp, i)) {
      const pm = R.parseMove(m);
      const { removed } = R.stamp(state.cells, attacker, bp, pm.at);
      let n = 0; for (const k of removed) if (state.cells[k][1] === R.STAR) n++;
      if (n * stars > best) { best = n * stars; bestMove = m; }
    }
  });
  return { points: best, move: bestMove };
}

// Describe the immediate result of a move from `state` (whoever is to move).
export function describeMove(state, move) {
  const seat = R.turnOf(state.ply);
  const before = R.starCounts(state.cells);
  const next = R.play(state, move);
  const after = R.starCounts(next.cells);
  const m = move === 'pass' ? { type: 'pass' } : R.parseMove(move);
  let removedStars = 0, removedCells = 0;
  if (m.type === 'place') {
    const e = placeEffect(state.cells, seat, state.blueprints[seat][m.blueprint], m.at, before[seat]);
    removedStars = e.starsRemoved; removedCells = e.removed.length;
  }
  return {
    move, type: m.type, seat,
    points: next.scores[seat] - state.scores[seat],
    removedStars, removedCells,
    starsBefore: before, starsAfter: after,
    scoresAfter: next.scores,
    next,
  };
}
