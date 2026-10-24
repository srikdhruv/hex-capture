#!/usr/bin/env node
// Fast fallback policy for Blueprints. Same CLI contract as engine/bp:
//   node tools/greedy.mjs [--time-ms N] < state.json
// stdin: {"view":{...}} (full server state) or a bare view. stdout: one JSON line
//   {"move": "...", "eval": number, "pv": [...], "top": [{"move","eval","points"}...]}
import { R, toState, placeEffect, frontierOf, maxThreat } from './bplib.mjs';
import { readFileSync } from 'node:fs';

const W_MY_STAR = 3.0;     // value of one extra own star (future multiplier)
const W_OPP_STAR = 3.5;    // value of removing an opponent star (beyond points)
const W_OPP_CELL = 0.25;   // removing opponent plains shrinks their frontier
const W_THREAT = 0.75;     // fraction of opponent's best immediate capture we fear
const EDIT_LATER = 0.7;     // an edit when the turn ends right after it pays off only after the opponent moves

const bpStars = (bp) => Object.values(bp).filter((v) => v === R.STAR).length;

// Static (no-lookahead) value of placing bp at `at` for `seat`.
function staticPlace(state, seat, bp, at, myStars) {
  const e = placeEffect(state.cells, seat, bp, at, myStars);
  const oppCells = e.removed.length - e.starsRemoved;
  return { v: e.points + W_MY_STAR * bpStars(bp) + W_OPP_STAR * e.starsRemoved + W_OPP_CELL * oppCells, points: e.points };
}

function bestStaticForHand(state, seat, hand, only, myStars, deadline) {
  const frontier = frontierOf(state.cells, seat);
  let best = -Infinity;
  for (const i of only) {
    const bp = hand[i];
    for (const m of R.placeMoves(state.cells, frontier, bp, i)) {
      const v = staticPlace(state, seat, bp, R.parseMove(m).at, myStars).v;
      if (v > best) best = v;
    }
    if (Date.now() > deadline) break;
  }
  return best;
}

export function choose(input, timeMs = 1500) {
  const t0 = Date.now();
  const budget = Math.max(150, Math.min(timeMs * 0.8, 1800));
  const deadline = t0 + budget;
  const { state, moves } = toState(input);
  if (!moves.length) return { move: 'pass', eval: 0, pv: ['pass'], top: [] };
  const seat = R.turnOf(state.ply), opp = 1 - seat;
  const myStars = R.starCounts(state.cells)[seat];
  const left = R.movesLeftInTurn(state.ply);
  const scored = [];

  const places = moves.filter((m) => m.includes('@'));
  const edits = moves.filter((m) => !m.includes('@'));
  for (const m of places) {
    const pm = R.parseMove(m), bp = state.blueprints[seat][pm.blueprint];
    const s = staticPlace(state, seat, bp, pm.at, myStars);
    scored.push({ move: m, v: s.v, points: s.points, kind: 'place' });
  }
  scored.sort((a, b) => b.v - a.v);

  // Threat lookahead for the best static candidates, within budget.
  const threatNow = maxThreat(state, opp).points;
  const lookN = Math.min(scored.length, 40);
  for (let i = 0; i < lookN; i++) {
    if (Date.now() > t0 + budget * 0.6 && i >= 3) break;
    const c = scored[i];
    const next = R.play(state, c.move);
    c.threat = maxThreat(next, opp).points;
    c.v -= W_THREAT * c.threat;
    c.looked = true;
  }
  for (const c of scored) if (!c.looked) c.v -= W_THREAT * threatNow + 0.01;

  // Edits cost a tempo: edit+place is worth it only if the reshaped placement beats two plain placements,
  // so an edit is valued at (best placement with new hand) - (best placement now).
  const bestNow = places.length ? Math.max(...scored.filter((c) => c.kind === 'place').map((c) => c.v + (c.looked ? W_THREAT * c.threat : W_THREAT * threatNow + 0.01))) : 0;
  const disc = left >= 2 ? 1 : EDIT_LATER;
  for (const m of edits) {
    if (Date.now() > deadline) break;
    const em = R.parseMove(m);
    const { hand } = R.applyEdit(state.blueprints[seat], em);
    const only = [...new Set([em.from[0], em.to[0]])];
    const b = bestStaticForHand(state, seat, hand, only, myStars, deadline);
    if (b === -Infinity) continue;
    scored.push({ move: m, v: disc * (b - bestNow) - W_THREAT * threatNow - 0.5, points: 0, kind: 'edit' });
  }

  scored.sort((a, b) => b.v - a.v);
  const best = scored[0] || { move: moves[0], v: 0 };
  const round = (x) => Math.round(x * 100) / 100;
  return {
    move: best.move, eval: round(best.v), pv: [best.move],
    top: scored.slice(0, 8).map((c) => ({ move: c.move, eval: round(c.v), points: c.points, threat: c.threat ?? null })),
    ms: Date.now() - t0, engine: 'greedy',
  };
}

const isMain = process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href;
if (isMain) {
  const args = process.argv.slice(2);
  const i = args.indexOf('--time-ms');
  const timeMs = i >= 0 ? Number(args[i + 1]) : 1500;
  const input = JSON.parse(readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify(choose(input, timeMs)) + '\n');
}
