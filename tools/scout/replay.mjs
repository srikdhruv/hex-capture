#!/usr/bin/env node
// Replays harvested games (lab/games/<room>.json) with the REFERENCE rules and emits per-ply metrics.
//   node tools/scout/replay.mjs lab/games/<room>.json [...]   -> one JSON object per line (per game)
// Per ply (after the action): seat, move, kind (edit/place), bp, stamp composition, points, stars removed,
// scores, star/wall/cell counts per seat, seal[s] = min #empty hexes that must become s's walls so no
// outside path reaches any of s's stars (lab/sealcut.mjs), holes[s] = empty hexes touching both an s star
// and an enemy cell (immediate snipe targets against s).
import * as R from '../../reference/rules.mjs';
import { Game } from '../../lab/fast.mjs';
import { minSeal } from '../../lab/sealcut.mjs';
import { readFileSync } from 'node:fs';

const comp = (bp) => {
  const c = { star: 0, wall: 0, plain: 0 };
  for (const v of Object.values(bp)) c[v]++;
  return `${Object.keys(bp).length}c:${c.star}s${c.wall}w${c.plain}p`;
};
const handStr = (h) => h.map(comp).join(' | ');

function holes(cells, s) {
  const out = new Set();
  for (const [k, [o, v]] of Object.entries(cells)) {
    if (o !== s || v !== R.STAR) continue;
    for (const n of R.neighbors(k)) {
      if (cells[n]) continue;
      if (R.neighbors(n).some((m) => cells[m] && cells[m][0] !== s)) out.add(n);
    }
  }
  return out.size;
}
// open[s]: s's stars with an empty neighbour connected through EMPTY hexes to outside the bounding box
// (i.e. not walled in by anyone; a cheap "reachable" measure next to the exact min-cut `seal`).
function openStars(cells) {
  let qmin = 1e9, qmax = -1e9, rmin = 1e9, rmax = -1e9;
  for (const k of Object.keys(cells)) { const [q, r] = R.parse(k); qmin = Math.min(qmin, q); qmax = Math.max(qmax, q); rmin = Math.min(rmin, r); rmax = Math.max(rmax, r); }
  qmin -= 2; qmax += 2; rmin -= 2; rmax += 2;
  const seen = new Set(), st = [R.key(qmin, rmin)]; seen.add(st[0]);
  while (st.length) {
    for (const n of R.neighbors(st.pop())) {
      if (seen.has(n) || cells[n]) continue;
      const [q, r] = R.parse(n); if (q < qmin || q > qmax || r < rmin || r > rmax) continue;
      seen.add(n); st.push(n);
    }
  }
  const out = [0, 0];
  for (const [k, [o, v]] of Object.entries(cells)) if (v === R.STAR && R.neighbors(k).some((n) => seen.has(n))) out[o]++;
  return out;
}
function counts(cells) {
  const c = { stars: [0, 0], walls: [0, 0], cells: [0, 0] };
  for (const [o, v] of Object.values(cells)) { c.cells[o]++; if (v === R.STAR) c.stars[o]++; if (v === R.WALL) c.walls[o]++; }
  return c;
}

const sealEvery = Number(process.env.SEAL_EVERY || 2);
for (const path of process.argv.slice(2)) {
  let g;
  try { g = JSON.parse(readFileSync(path, 'utf8')); } catch (e) { console.log(JSON.stringify({ path, error: String(e) })); continue; }
  let st = R.setup();
  const plies = [];
  const hands = {};
  let err = null;
  for (let i = 0; i < g.moves.length; i++) {
    const mv = g.moves[i];
    const seat = R.turnOf(st.ply);
    if (st.ply === 20 || st.ply === 40) hands[st.ply] = st.blueprints.map(handStr);
    const rec = { ply: st.ply, seat, move: mv };
    try {
      if (mv === 'pass') rec.kind = 'pass';
      else {
        const m = R.parseMove(mv);
        rec.kind = m.type;
        if (m.type === 'place') {
          const bp = st.blueprints[seat][m.blueprint];
          rec.bp = m.blueprint + 1; rec.comp = comp(bp);
          const res = R.stamp(st.cells, seat, bp, m.at);
          let rs = 0, rw = 0;
          for (const k of res.removed) { if (st.cells[k][1] === R.STAR) rs++; else rw++; }
          rec.starsRemoved = rs; rec.cellsRemoved = rs + rw;
          rec.dist = Math.abs(m.at[0]); // crude: horizontal distance of anchor from the centre line
        } else {
          rec.from = m.from[0] + 1; rec.to = m.to[0] + 1;
          rec.cell = st.blueprints[seat][m.from[0]][m.from[1]];
        }
      }
      const before = st.scores[seat];
      st = R.play(st, mv);
      rec.pts = st.scores[seat] - before;
    } catch (e) { err = `ply ${st.ply} ${mv}: ${e.message}`; break; }
    const c = counts(st.cells);
    Object.assign(rec, { scores: [...st.scores], stars: c.stars, walls: c.walls, cells: c.cells,
      holes: [holes(st.cells, 0), holes(st.cells, 1)], open: openStars(st.cells) });
    if (st.ply % sealEvery === 0 || st.ply >= g.moves.length) {
      const fg = Game.fromRef(st);
      rec.seal = [minSeal(fg, 0), minSeal(fg, 1)];
    }
    plies.push(rec);
  }
  if (!hands[20] && st.ply >= 20) hands[20] = st.blueprints.map(handStr);
  hands.final = st.blueprints.map(handStr);
  hands.finalRaw = st.blueprints;
  console.log(JSON.stringify({ room: g.room, players: g.players, tournament: g.tournament, result: g.result,
    claimedScores: g.scores, scores: st.scores, ply: st.ply, err, hands, plies }));
}
