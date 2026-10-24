#!/usr/bin/env node
// Persistent game referee (reference rules) speaking JSON lines, used by tools/arena.py.
// in:  {"cmd":"new","opening":["2@-3,-3", ...]}   out: {"view":{...}}
//      {"cmd":"play","move":"..."}                  out: {"view":{...}} or {"error":"illegal ..."}
//      {"cmd":"random_opening","plies":N,"seed":S}  out: {"moves":[...]}  (random legal placements)
import { R, toView } from './bplib.mjs';
import { createInterface } from 'node:readline';

let s = R.setup();
const rl = createInterface({ input: process.stdin });
const out = (o) => process.stdout.write(JSON.stringify(o) + '\n');
rl.on('line', (line) => {
  if (!line.trim()) return;
  let req;
  try { req = JSON.parse(line); } catch { out({ error: 'bad json' }); return; }
  try {
    if (req.cmd === 'new') {
      s = R.setup();
      for (const m of req.opening || []) {
        if (!R.legalMoves(s).includes(m)) throw new Error(`illegal opening move ${m} at ply ${s.ply}`);
        s = R.play(s, m);
      }
      out({ view: toView(s) });
    } else if (req.cmd === 'play') {
      const legal = R.legalMoves(s);
      if (req.move !== 'pass' && !legal.includes(req.move)) { out({ error: `illegal ${req.move} at ply ${s.ply}` }); return; }
      s = R.play(s, req.move);
      out({ view: toView(s) });
    } else if (req.cmd === 'random_opening') {
      let seed = (req.seed ?? 1) >>> 0;
      const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
      let t = R.setup(); const moves = [];
      for (let i = 0; i < (req.plies ?? 2); i++) {
        const places = R.legalMoves(t).filter((m) => m.includes('@'));
        const m = places[Math.floor(rnd() * places.length)];
        moves.push(m); t = R.play(t, m);
      }
      out({ moves });
    } else out({ error: `unknown cmd ${req.cmd}` });
  } catch (e) { out({ error: String(e.message || e) }); }
});
