import { runPlan, draw } from './handplan.mjs';
const lineSteps = [[0, [1, 0], 0, [2, -1]], [0, [0, 1], 0, [3, -1]], [0, [-1, 1], 0, [-1, -1]], [0, [-1, 0], 0, [-2, -1]]];
export const PLANS = {
  blue_hp1: runPlan(0, [
    [1, [1, 0], 2, [2, 0]], [0, [0, 0], 1, [1, 0]], [1, [0, -1], 2, [3, 0]], [2, [0, 0], 1, [0, -1]], [1, [-1, 1], 2, [4, 0]], ...lineSteps]),
  red_hp1: runPlan(1, [
    [1, [1, -1], 2, [-2, 0]], [0, [0, 0], 1, [1, -1]], [1, [-1, 0], 2, [-3, 0]], [2, [0, 0], 1, [-1, 0]], [1, [0, 1], 2, [-4, 0]], ...lineSteps]),
  // only the 5 star-stacking edits (no long piece)
  blue_stack5: runPlan(0, [[1, [1, 0], 2, [2, 0]], [0, [0, 0], 1, [1, 0]], [1, [0, -1], 2, [3, 0]], [2, [0, 0], 1, [0, -1]], [1, [-1, 1], 2, [4, 0]]]),
  red_stack5: runPlan(1, [[1, [1, -1], 2, [-2, 0]], [0, [0, 0], 1, [1, -1]], [1, [-1, 0], 2, [-3, 0]], [2, [0, 0], 1, [-1, 0]], [1, [0, 1], 2, [-4, 0]]]),
};
if (process.argv[1].endsWith('humanplan.mjs')) for (const [n, p] of Object.entries(PLANS)) { console.log(`== ${n} (${p.moves.length} edits): ${p.moves.join(' ')}`); p.hand.forEach((b, i) => console.log(`#${i + 1}:\n${draw(b)}`)); }
// Fortlite: wrap the 3 edge stars of #2 with 9 plains (3 from #1, 6 from #3), star by star.
export const FORT = {
  blue: runPlan(0, [
    [2, [1, 0], 1, [2, -2]], [2, [1, -1], 1, [2, -1]], [2, [0, -1], 1, [1, -2]],   // shield NE star
    [2, [-1, 0], 1, [-2, 0]], [2, [-1, 1], 1, [-2, 1]], [2, [0, 1], 1, [-1, -1]],  // shield W star
    [0, [1, 0], 1, [0, 2]], [0, [1, -1], 1, [1, 1]], [0, [0, -1], 1, [-1, 2]],     // shield S star
  ]),
  red: runPlan(1, [
    [2, [1, 0], 1, [2, 0]], [2, [1, -1], 1, [2, -1]], [2, [0, -1], 1, [1, 1]],     // shield E star
    [2, [-1, 0], 1, [0, -2]], [2, [-1, 1], 1, [1, -2]], [2, [0, 1], 1, [-1, -1]],  // shield N star
    [0, [1, 0], 1, [-2, 2]], [0, [1, -1], 1, [-2, 1]], [0, [0, -1], 1, [-1, 2]],   // shield SW star
  ]),
};
PLANS.blue_fort = FORT.blue; PLANS.red_fort = FORT.red;
if (process.argv[1].endsWith('humanplan.mjs')) for (const [n, p] of Object.entries(FORT)) { console.log(`== fort ${n} (${p.moves.length} edits): ${p.moves.join(' ')}`); p.hand.forEach((b, i) => console.log(`#${i + 1}:\n${draw(b)}`)); }
