#!/usr/bin/env node
// Lab replica bots behind the engine CLI contract (for tools/arena.py).
//   node engine/replica.mjs --bot eris|aryan|rusher [--time-ms N] < obs.json
// eris:   R8 wall-city (6-plain line, www, 6-star parking piece never stamped; seal-aware, no star stamps)
// aryan:  R9 www wall-sniper (5-star #1, 3-wall zigzag; star-free until ply 90)
// rusher: R10-style star rusher (moves both lone stars into #2, then stamps aggressively)
// Scripted edits follow lab/d1plan.mjs plans (legal edit sequences); then lab/bots.mjs chooseTurn decides.
import { readFileSync } from 'node:fs';
import { Game, R } from '../lab/fast.mjs';
import { chooseTurn, editPlan } from '../lab/bots.mjs';
import { PLANS } from '../lab/d1plan.mjs';

const argv = process.argv.slice(2);
const bot = argv.includes('--bot') ? argv[argv.indexOf('--bot') + 1] : 'eris';
const CFG = {
  eris: { P: { wStar: 0.5, wThreat: 1, noise: 0.5, starFreeUntil: 120, wSeal: 1 }, plans: ['blue_turtle', 'red_turtle'] },
  aryan: { P: { wStar: 0.5, wThreat: 1, noise: 0.5, starFreeUntil: 90 }, plans: ['blue_none', 'red_aryan'] },
  rusher: { P: { wStar: 3, wThreat: 0.5, noise: 0.5, plan: 'star6' }, plans: [null, null] },
}[bot];

function out(move, note = '') {
  process.stdout.write(JSON.stringify({ move, eval: 0, pv: [move], top: [], nodes: 0, note }) + '\n');
}
const sameHand = (a, b) => a.every((bp, i) => { const x = Object.entries(bp).sort().join(';'), y = Object.entries(b[i]).sort().join(';'); return x === y; });

let fallback = 'pass';
try {
  const obs = JSON.parse(readFileSync(0, 'utf8'));
  const view = obs.view || (obs.state && obs.state.view) || obs;
  if (view.moves && view.moves.length) fallback = view.moves[0];
  const st = { cells: view.cells, blueprints: view.blueprints, ply: view.ply, scores: view.scores || [0, 0] };
  const seat = R.turnOf(st.ply);
  // scripted plan: next edit if current hand is on the plan's prefix
  const planName = CFG.plans[seat];
  if (planName && PLANS[planName]) {
    const moves = PLANS[planName].moves; let h = R.setup().blueprints[seat];
    for (let k = 0; k < moves.length; k++) {
      if (sameHand(h, st.blueprints[seat])) {
        if (!view.moves || view.moves.includes(moves[k])) { out(moves[k], 'plan'); process.exit(0); }
        break;
      }
      h = R.applyEdit(h, R.parseMove(moves[k])).hand;
    }
  }
  const P = { beam: 12, final: 8, ...CFG.P };
  if (typeof P.plan === 'string') P.edits = editPlan(P.plan, { startPly: 0 });
  const g = Game.fromRef(st);
  const turn = chooseTurn(g, P);
  const m = turn[0];
  let mv = m === 'pass' || !m ? fallback : m.edit ? m.edit : g.moveString(m.b, m.a);
  if (view.moves && !view.moves.includes(mv)) mv = fallback;
  out(mv);
} catch (e) {
  process.stderr.write(String(e && e.stack || e) + '\n');
  out(fallback, 'error');
}
