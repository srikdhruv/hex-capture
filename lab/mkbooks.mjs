import fs from 'node:fs';
import * as R from '../reference/rules.mjs';
import { PLANS } from './d1plan.mjs';
function book(b, r) {
  // re-validate from setup
  for (const [seat, p] of [[0, b], [1, r]]) { let h = R.setup().blueprints[seat]; for (const m of p.moves) { if (!R.editMoves(h).includes(m)) throw new Error('bad ' + m); h = R.applyEdit(h, R.parseMove(m)).hand; } if (JSON.stringify(h) !== JSON.stringify(p.hand)) throw new Error('mismatch'); }
  return { maxPly: 40, edits: { 0: b.moves, 1: r.moves }, target: { 0: b.hand, 1: r.hand } };
}
fs.writeFileSync('books/fortlite.json', JSON.stringify(book(PLANS.blue_fort, PLANS.red_fort), null, 1));
fs.writeFileSync('books/hex19.json', JSON.stringify(book(PLANS.blue_fort19, PLANS.red_fort19), null, 1));
fs.writeFileSync('books/fort18.json', JSON.stringify(book(PLANS.blue_d1, PLANS.red_d1), null, 1));
console.log('ok');
