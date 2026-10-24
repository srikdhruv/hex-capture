// Cross-check engine/bp --dump against reference/rules.mjs on random games.
// usage: node engine/test_movegen.mjs [games=40] [seed=1]
import { setup, legalMoves, play, TOTAL_PLIES } from '../reference/rules.mjs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const games = +(process.argv[2] || 40);
let seed = +(process.argv[3] || 1);
const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
const pick = (a) => a[Math.floor(rnd() * a.length)];

const positions = [];
for (let gi = 0; gi < games; gi++) {
  let st = setup();
  const editBias = rnd() * 0.5; // vary edit frequency per game
  while (st.ply < TOTAL_PLIES) {
    const moves = legalMoves(st);
    if (!moves.length) { st = play(st, 'pass'); continue; }
    if (rnd() < 0.35 || st.ply < 3) {
      const sample = [];
      const n = Math.min(moves.length, 25);
      for (let i = 0; i < n; i++) sample.push(pick(moves));
      positions.push({ state: st, apply: sample, moves });
    }
    const places = moves.filter((m) => m.includes('@')), edits = moves.filter((m) => !m.includes('@'));
    // prefer captures sometimes to make scores non-trivial
    let mv;
    if (edits.length && (rnd() < editBias || !places.length)) mv = pick(edits);
    else mv = pick(places);
    st = play(st, mv);
  }
}

const input = positions.map((p) => JSON.stringify({ state: p.state, apply: p.apply })).join('\n') + '\n';
const r = spawnSync(path.join(here, 'bp'), ['--dump'], { input, maxBuffer: 1 << 30 });
if (r.status !== 0) { console.error('bp failed', r.stderr.toString()); process.exit(1); }
const lines = r.stdout.toString().trim().split('\n');
if (lines.length !== positions.length) { console.error('line count mismatch', lines.length, positions.length); process.exit(1); }

const canonCells = (c) => JSON.stringify(Object.keys(c).sort().map((k) => [k, c[k]]));
const canonBps = (b) => JSON.stringify(b.map((hand) => hand.map((bp) => Object.keys(bp).sort().map((k) => [k, bp[k]]))));
let bad = 0, checkedMoves = 0, checkedResults = 0;
positions.forEach((p, i) => {
  const out = JSON.parse(lines[i]);
  const ref = [...p.moves].sort();
  const got = out.moves;
  const refSet = new Set(ref), gotSet = new Set(got);
  if (ref.length !== got.length || ref.some((m) => !gotSet.has(m))) {
    bad++;
    if (bad < 5) {
      console.error(`pos ${i} ply ${p.state.ply}: movegen mismatch ref ${ref.length} got ${got.length}`);
      console.error(' missing:', ref.filter((m) => !gotSet.has(m)).slice(0, 10));
      console.error(' extra:', got.filter((m) => !refSet.has(m)).slice(0, 10));
    }
    return;
  }
  checkedMoves += ref.length;
  p.apply.forEach((mv, j) => {
    const exp = play(p.state, mv), g = out.results[j];
    checkedResults++;
    if (!g || g.ply !== exp.ply || JSON.stringify(g.scores) !== JSON.stringify(exp.scores) ||
        canonCells(g.cells) !== canonCells(exp.cells) || canonBps(g.blueprints) !== canonBps(exp.blueprints)) {
      bad++;
      if (bad < 5) console.error(`pos ${i} move ${mv}: result mismatch`, JSON.stringify(exp.scores), g && JSON.stringify(g.scores));
    }
  });
});
console.log(`positions ${positions.length} moves ${checkedMoves} results ${checkedResults} failures ${bad}`);
process.exit(bad ? 1 : 0);
