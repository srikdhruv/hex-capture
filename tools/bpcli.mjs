#!/usr/bin/env node
// JSON-in/JSON-out bridge to the reference rules, used by tools/suggest.py and client tests.
//   echo '{"op":"replay","moves":["2@-1,0"]}' | node tools/bpcli.mjs
// ops:
//   replay   {moves}                 -> {view}             (view: ply, turn, left, cells, blueprints, scores, stars, moves, result)
//   view     {state}                 -> {view}             (state: server state / bare view / rules state)
//   analyze  {state, moves:[...]}    -> {results:[{move, points, removedStars, removedCells, starsAfter, scoresAfter}]}
//   threats  {state, attacker}       -> {threats:[{move, points, starKeys}]}  (placements of attacker that capture stars)
//   selfplay {plies, seed?}          -> {states:[view...], moves:[...]}  (random-ish legal game for tests)
import { R, toState, toView, replay, describeMove, threats } from './bplib.mjs';
import { readFileSync } from 'node:fs';

const req = JSON.parse(readFileSync(0, 'utf8'));
let out;
switch (req.op) {
  case 'replay': out = { view: toView(replay(req.moves || [])) }; break;
  case 'view': out = { view: toView(toState(req.state).state) }; break;
  case 'analyze': {
    const { state } = toState(req.state);
    out = { results: (req.moves || []).map((m) => { try { const { next, ...d } = describeMove(state, m); return d; } catch (e) { return { move: m, error: String(e.message || e) }; } }) };
    break;
  }
  case 'threats': {
    const { state } = toState(req.state);
    const t = threats(state, req.attacker).map(({ move, points, starsRemoved, starKeys }) => ({ move, points, starsRemoved, starKeys }));
    out = { threats: t };
    break;
  }
  case 'selfplay': {
    let seed = req.seed ?? 1;
    const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
    let s = R.setup(); const states = [toView(s)], moves = [];
    for (let i = 0; i < (req.plies ?? 20) && s.ply < R.TOTAL_PLIES; i++) {
      const legal = R.legalMoves(s);
      const places = legal.filter((m) => m.includes('@'));
      const pool = places.length && rnd() < 0.85 ? places : legal;
      const m = pool[Math.floor(rnd() * pool.length)];
      moves.push(m); s = R.play(s, m); states.push(toView(s));
    }
    out = { states, moves };
    break;
  }
  default: out = { error: `unknown op ${req.op}` };
}
process.stdout.write(JSON.stringify(out) + '\n');
