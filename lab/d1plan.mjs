// D1 "Fort18": #2 = 6 stars (centre + 5 ring) fully rimmed by 3 walls + 9 plains (rim is 12, not 11); #1 = 2-plain line; #3 = 1 plain.
import * as R from '../reference/rules.mjs';
import { runPlan, draw } from './handplan.mjs';
import { PLANS } from './humanplan.mjs';
const K = (q, r) => R.key(q, r), P = R.parse;
function d1(seat) {
  const keep = seat === 0 ? [1, 0] : [-1, 0];            // ring wall that stays (faces the enemy)
  const moveW = seat === 0 ? [[0, -1], [-1, 1]] : [[1, -1], [0, 1]]; // ring walls that move to the rim
  const wallDst = seat === 0 ? [[2, -1], [1, 1]] : [[-1, -1], [-2, 1]];
  const S6 = [[0, 0], ...R.DIRS.filter(([a, b]) => !(a === keep[0] && b === keep[1]))];
  const s6k = new Set(S6.map(([q, r]) => K(q, r)));
  const rim = new Set(); for (const [q, r] of S6) for (const n of R.neighbors(K(q, r))) if (!s6k.has(n)) rim.add(n);
  rim.delete(K(...keep)); for (const w of wallDst) rim.delete(K(...w));
  const plainDst = [...rim].map(P); // 8
  // sources: #3 star+5 plains (leave (0,1)?), #1 star + 3 plains (leave (1,-1),(0,-1),(-1,0) then straighten)
  const ring = R.DIRS;
  const src3 = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1]]; // 5 plains of #3; leaves (0,1)
  const src1 = [[1, 0], [0, 1], [-1, 1], [-1, 0]];           // 4 plains of #1; leaves (1,-1),(0,-1) (2-plain line)
  const steps = [];
  const srcs = [...src3.map((c) => [2, c]), ...src1.map((c) => [0, c])];
  if (plainDst.length !== 9) throw new Error('rim ' + plainDst.length);
  // order plain destinations so each is adjacent to current #2 (all rim cells touch S6 cells which exist except moved-wall spots; fine)
  plainDst.forEach((dst, i) => steps.push([srcs[i][0], srcs[i][1], 1, dst]));
  // walls out to rim, stars in: #3 star first? #3 centre (0,0) must leave AFTER its plains? removing centre of a partial ring may disconnect -> move #3 star now while (0,1) remains: rest = {(0,1)} connected.
  steps.push([1, moveW[0], 1, wallDst[0]], [2, [0, 0], 1, moveW[0]], [1, moveW[1], 1, wallDst[1]], [0, [0, 0], 1, moveW[1]]);
  return runPlan(seat, steps);
}
PLANS.blue_d1 = d1(0); PLANS.red_d1 = d1(1);
// D2: fortlite + E/NE wall out to rim corner + #3's star into the vacated ring spot (5 interior stars; #3 empty; #1 star+3 plains)
const FB = PLANS.blue_fort; const FR = PLANS.red_fort;
export { PLANS };
if (process.argv[1] && process.argv[1].endsWith('d1plan.mjs')) for (const n of ['blue_d1', 'red_d1']) { const p = PLANS[n]; console.log(`== ${n} (${p.moves.length} edits): ${p.moves.join(' ')}`); p.hand.forEach((b, i) => console.log(`#${i + 1}:\n${draw(b)}`)); }
// D2 "Fortlite-5P": like Fortlite but #3 keeps 1 PLAIN (star-free sniper) and its star goes into #2's interior
// (a ring wall steps out to the rim corner first). 11 edits. #2 = 5 interior stars, 3 walls, 9 plains; #1 = star + 2 plains; #3 = 1 plain.
PLANS.blue_d2 = runPlan(0, [
  [2, [1, 0], 1, [2, -2]], [2, [1, -1], 1, [2, -1]], [2, [0, -1], 1, [1, -2]], [2, [-1, 0], 1, [-2, 0]], [2, [-1, 1], 1, [-2, 1]],
  [0, [1, 0], 1, [-1, -1]], [0, [1, -1], 1, [0, 2]], [0, [0, -1], 1, [1, 1]], [0, [-1, 0], 1, [-1, 2]],
  [1, [1, 0], 1, [2, 0]], [2, [0, 0], 1, [1, 0]]]);
PLANS.red_d2 = runPlan(1, [
  [2, [1, 0], 1, [2, 0]], [2, [1, -1], 1, [2, -1]], [2, [0, -1], 1, [1, 1]], [2, [-1, 0], 1, [0, -2]], [2, [-1, 1], 1, [1, -2]],
  [0, [1, 0], 1, [-1, -1]], [0, [1, -1], 1, [-2, 2]], [0, [0, -1], 1, [-2, 1]], [0, [-1, 0], 1, [-1, 2]],
  [1, [-1, 0], 1, [-2, 0]], [2, [0, 0], 1, [-1, 0]]]);
if (process.argv[1] && process.argv[1].endsWith('d1plan.mjs')) for (const n of ['blue_d2', 'red_d2']) { const p = PLANS[n]; console.log(`== ${n} (${p.moves.length} edits): ${p.moves.join(' ')}`); p.hand.forEach((b, i) => console.log(`#${i + 1}:\n${draw(b)}`)); }
// "FortliteP": #2 identical to Fortlite (4 sealed stars), but #3 ends as 1 PLAIN sniper; #3's star is parked in #1 (#1 = 2 stars + 2 plains). 10 edits.
const fpSteps = (dst) => [
  [2, [1, 0], 1, dst[0]], [2, [1, -1], 1, dst[1]], [2, [0, -1], 1, dst[2]], [2, [-1, 0], 1, dst[3]], [2, [-1, 1], 1, dst[4]],
  [0, [1, 0], 1, dst[5]], [0, [1, -1], 1, dst[6]], [0, [0, -1], 1, dst[7]], [0, [-1, 0], 1, dst[8]],
  [2, [0, 0], 0, [1, 0]]];
PLANS.blue_fortP = runPlan(0, fpSteps([[2, -2], [2, -1], [1, -2], [-2, 0], [-2, 1], [-1, -1], [0, 2], [1, 1], [-1, 2]]));
PLANS.red_fortP = runPlan(1, fpSteps([[2, 0], [2, -1], [1, 1], [0, -2], [1, -2], [-1, -1], [-2, 2], [-2, 1], [-1, 2]]));
if (process.argv[1] && process.argv[1].endsWith('d1plan.mjs')) for (const n of ['blue_fortP', 'red_fortP']) { const p = PLANS[n]; console.log(`== ${n} (${p.moves.length} edits): ${p.moves.join(' ')}`); p.hand.forEach((b, i) => console.log(`#${i + 1}:\n${draw(b)}`)); }
// "FortliteS2": Fortlite + 1 edit: #1's star joins #3 -> #3 = 2-star domino sniper, #1 = 3-plain 120-degree chevron (star-free probe). 10 edits.
PLANS.blue_fortS2 = runPlan(0, [...PLANS.blue_fort.steps, [0, [0, 0], 2, [1, 0]]]);
PLANS.red_fortS2 = runPlan(1, [...PLANS.red_fort.steps, [0, [0, 0], 2, [1, 0]]]);
if (process.argv[1] && process.argv[1].endsWith('d1plan.mjs')) for (const n of ['blue_fortS2', 'red_fortS2']) { const p = PLANS[n]; console.log(`== ${n} (${p.moves.length} edits): ${p.moves.join(' ')}`); p.hand.forEach((b, i) => console.log(`#${i + 1}:\n${draw(b)}`)); }
// "Turtle" (opponent's hand): #3 = all 6 stars + 6 plains (never stamped), #2 = 3-wall straight line, #1 = 6-plain straight line. 11 edits.
const lineS = [[0, [1, 0], 0, [2, -1]], [0, [0, 1], 0, [3, -1]], [0, [-1, 1], 0, [-1, -1]], [0, [-1, 0], 0, [-2, -1]]];
PLANS.blue_turtle = runPlan(0, [
  [1, [0, 0], 2, [2, 0]], [1, [1, -1], 2, [2, -1]], [1, [1, 0], 1, [0, 0]], [1, [0, -1], 1, [1, -1]], [1, [-1, 0], 2, [3, -1]], [1, [0, 1], 2, [3, 0]],
  [0, [0, 0], 2, [2, 1]], ...lineS]);
PLANS.red_turtle = runPlan(1, [
  [1, [0, 0], 2, [2, 0]], [1, [1, 0], 2, [2, -1]], [1, [0, 1], 1, [0, 0]], [1, [1, -1], 1, [1, 0]], [1, [0, -1], 2, [3, -1]], [1, [-1, 1], 2, [3, 0]],
  [0, [0, 0], 2, [2, 1]], ...lineS]);
if (process.argv[1] && process.argv[1].endsWith('d1plan.mjs')) for (const n of ['blue_turtle', 'red_turtle']) { const p = PLANS[n]; console.log(`== ${n} (${p.moves.length} edits): ${p.moves.join(' ')}`); p.hand.forEach((b, i) => console.log(`#${i + 1}:\n${draw(b)}`)); }
// Replica of live opponent "aryan" (R9, Red): exact Red edits from the game log (plies 1,2,5,9,10,17):
// #1 = plain flower + 4-star line (5 stars), #2 = 3-wall zigzag (wall probe/attacker), #3 = plain flower.
PLANS.red_aryan = { moves: ['2:1,0>2:-1,0', '2:0,2>1:2,1', '2:1,0>1:3,1', '2:2,1>1:4,1', '2:1,2>2:-1,2', '2:1,1>1:5,1'] };
{ let h = R.setup().blueprints[1]; for (const m of PLANS.red_aryan.moves) { if (!R.editMoves(h).includes(m)) throw new Error('aryan ' + m); h = R.applyEdit(h, R.parseMove(m)).hand; } PLANS.red_aryan.hand = h; }
PLANS.blue_none = { moves: [] }; PLANS.red_none = { moves: [] };
// "Fortlite -> www": after Fortlite, convert at ply T: #2's 3 ring walls -> #3 (making *www), then #3's star -> #1. #3 = 'www' immune sniper/sealer.
PLANS.blue_fortWWW = runPlan(0, [...PLANS.blue_fort.steps, [1, [1, 0], 2, [1, 0]], [1, [0, -1], 2, [2, 0]], [1, [-1, 1], 2, [3, 0]], [2, [0, 0], 0, [1, 0]]]);
PLANS.red_fortWWW = runPlan(1, [...PLANS.red_fort.steps, [1, [1, -1], 2, [1, 0]], [1, [-1, 0], 2, [2, 0]], [1, [0, 1], 2, [3, 0]], [2, [0, 0], 0, [1, 0]]]);
if (process.argv[1] && process.argv[1].endsWith('d1plan.mjs')) for (const n of ['blue_fortWWW', 'red_fortWWW']) { const p = PLANS[n]; console.log(`== ${n} (${p.moves.length} edits): ${p.moves.join(' ')}`); p.hand.forEach((b, i) => console.log(`#${i + 1}:\n${draw(b)}`)); }
// Domino variants: Fortlite + 2 edits making #1 a 2-PLAIN domino ((-1,1),(0,1) remain).
PLANS.blue_domA = runPlan(0, [...PLANS.blue_fort.steps, [0, [0, 0], 2, [1, 0]], [0, [-1, 0], 1, [2, 0]]]);   // star -> #3 ('**'), plain -> #2 rim corner
PLANS.red_domA = runPlan(1, [...PLANS.red_fort.steps, [0, [0, 0], 2, [1, 0]], [0, [-1, 0], 1, [-2, 0]]]);
PLANS.blue_domB = runPlan(0, [...PLANS.blue_fort.steps, [0, [0, 0], 1, [2, 0]], [0, [-1, 0], 1, [0, -2]]]);   // star -> #2 rim corner, plain -> another corner
PLANS.red_domB = runPlan(1, [...PLANS.red_fort.steps, [0, [0, 0], 1, [-2, 0]], [0, [-1, 0], 1, [0, 2]]]);
if (process.argv[1] && process.argv[1].endsWith('d1plan.mjs')) for (const n of ['blue_domA', 'red_domA', 'blue_domB']) { const p = PLANS[n]; console.log(`== ${n} (${p.moves.length} edits): ${p.moves.join(' ')}`); p.hand.forEach((b, i) => console.log(`#${i + 1}:\n${draw(b)}`)); }
