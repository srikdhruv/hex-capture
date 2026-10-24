// Cross-check fast engine vs reference rules on random games (incl. edits).
import { Game, R, qr } from './fast.mjs';
let seed = 12345; const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
const games = +(process.argv[2] || 30);
for (let gi = 0; gi < games; gi++) {
  let ref = R.setup(); const g = Game.start();
  while (ref.ply < R.TOTAL_PLIES) {
    const lm = R.legalMoves(ref);
    const s = g.seat();
    const pl = g.placements(s); const fastPlace = new Set(); for (let j = 0; j < pl.length; j += 2) fastPlace.add(g.moveString(pl[j], pl[j + 1]));
    const refPlace = new Set(lm.filter((m) => m.includes('@')));
    if (fastPlace.size !== refPlace.size || [...refPlace].some((m) => !fastPlace.has(m))) { console.log('placement mismatch', gi, ref.ply, fastPlace.size, refPlace.size); process.exit(1); }
    const edits = lm.filter((m) => !m.includes('@'));
    let mv;
    if (rnd() < 0.15 && edits.length) mv = edits[Math.floor(rnd() * edits.length)];
    else { const p = [...refPlace]; mv = p.length ? p[Math.floor(rnd() * p.length)] : 'pass'; }
    // bias toward captures sometimes
    ref = R.play(ref, mv); g.playString(mv);
    const a = JSON.stringify(ref.scores), b = JSON.stringify(g.scores);
    if (a !== b || Object.keys(ref.cells).length !== g.ncell[0] + g.ncell[1]) { console.log('state mismatch', gi, ref.ply, a, b); process.exit(1); }
    const sc = R.starCounts(ref.cells); if (sc[0] !== g.stars[0] || sc[1] !== g.stars[1]) { console.log('stars mismatch'); process.exit(1); }
  }
  // test undo: replay check
  if (gi % 10 === 0) console.log('game', gi, 'ok scores', ref.scores);
}
// undo test
{
  const g = Game.start(); const snap = JSON.stringify(g.toRef());
  const us = [];
  for (let i = 0; i < 40; i++) { const pl = g.placements(g.seat()); const j = 2 * Math.floor(rnd() * pl.length / 2); us.push(g.place(pl[j], pl[j + 1])); }
  while (us.length) g.undo(us.pop());
  g.occ = null;
  console.log('undo ok', JSON.stringify(g.toRef()) === snap);
}
