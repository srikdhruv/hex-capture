// Heuristic bots for Blueprints experiments.
import { Game, NB, STAR, WALL, TOTAL, turnOf, S, qr } from './fast.mjs';
import * as R from '../reference/rules.mjs';

// ---- evaluation helpers ----
// Count stars of seat s that have at least one empty neighbour (exposed to a one-stamp capture if reachable).
export function exposedStars(g, s) {
  let n = 0;
  for (const i of g.occupied(s)) if (g.kind[i] === STAR) for (let d = 0; d < 6; d++) if (g.own[i + NB[d]] < 0) { n++; break; }
  return n;
}

// Best points seat s can score with up to `k` actions (k=1 or 2) by placements only. Returns [points, starsTaken].
// 2-action search: a1 = any placement that erases something or comes within reach of a capture target; a2 = best capture.
const DG = new Int32Array(S * S); let dgen = 0; const DD = new Int8Array(S * S);
function diam(bp) { let m = 0; for (const [q1, r1] of bp.cells) for (const [q2, r2] of bp.cells) { const dq = q1 - q2, dr = r1 - r2; m = Math.max(m, (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2); } return m; }
// Max stars seat s can erase with ONE placement (targeted enumeration over cells next to enemy stars).
const TG = new Int32Array(S * S); let tgen = 0;
export function captureTargets(g, s) {
  const o = 1 - s, own = g.own; const gen = ++tgen; const targets = [];
  for (const i of g.occupied(o)) if (g.kind[i] === STAR) for (let d = 0; d < 6; d++) { const n = i + NB[d]; if (own[n] < 0 && TG[n] !== gen) { TG[n] = gen; targets.push(n); } }
  return targets;
}
export const STATS={calls:0,anchors:0,targets:0,fromCombo:0,fromThreat:0};
export function bestOneCapture(g, s, targets = null) {
  STATS.calls++;
  const o = 1 - s, own = g.own, hand = g.hands[s]; let best = 0;
  if (!targets) targets = captureTargets(g, s);
  if (!targets.length) return 0;
  STATS.targets += targets.length;
  for (let b = 0; b < hand.length; b++) {
    const offs = hand[b].offs; if (!offs.length) continue;
    const ag = ++tgen;
    for (const t of targets) for (let j = 0; j < offs.length; j++) {
      const a = t - offs[j]; if (TG[a] === ag) continue; TG[a] = ag; STATS.anchors++;
      let ok = true, touch = false;
      for (let k = 0; k < offs.length; k++) if (own[a + offs[k]] >= 0) { ok = false; break; }
      if (ok) for (let k = 0; k < offs.length && !touch; k++) { const c = a + offs[k]; for (let d = 0; d < 6; d++) if (own[c + NB[d]] === s) { touch = true; break; } }
      if (!ok || !touch) continue;
      const st = g.peekStars(s, b, a); if (st > best) best = st;
    }
  }
  return best;
}
export function bestCapture(g, s, k = 2) {
  const pl = g.placements(s);
  let best = 0, bestSt = 0;
  const my = g.stars[s], o = 1 - s;
  let maxAdd = 0; for (const bp of g.hands[s]) maxAdd = Math.max(maxAdd, bp.stars);
  const cand = [];
  for (let j = 0; j < pl.length; j += 2) {
    const [st, ce] = g.peek(s, pl[j], pl[j + 1]);
    if (st * my > best) { best = st * my; bestSt = st; }
    if (k === 2 && ce > 0) cand.push(pl[j], pl[j + 1]);
  }
  if (k === 2 && best > 0 && pl.length > 2) best = Math.max(best, bestSt * (my + maxAdd)); // build first, then capture
  if (k === 2) {
    // distance map from capture targets (empty cells next to enemy stars)
    let L = 0; for (const bp of g.hands[s]) if (bp.offs.length) L = Math.max(L, diam(bp)); L += 1;
    const gen = ++dgen; let frontier = [];
    for (const i of g.occupied(o)) if (g.kind[i] === STAR) for (let d = 0; d < 6; d++) { const n = i + NB[d]; if (g.own[n] < 0 && DG[n] !== gen) { DG[n] = gen; DD[n] = 0; frontier.push(n); } }
    for (let depth = 1; depth <= L && frontier.length; depth++) {
      const nf = [];
      for (const c of frontier) for (let d = 0; d < 6; d++) { const n = c + NB[d]; if (DG[n] !== gen) { DG[n] = gen; DD[n] = depth; nf.push(n); } }
      frontier = nf;
    }
    if (dgen > 2e9) { DG.fill(0); dgen = 0; }
    const hand = g.hands[s];
    for (let j = 0; j < pl.length; j += 2) {
      const bp = hand[pl[j]], a = pl[j + 1]; let near = false;
      for (const off of bp.offs) if (DG[a + off] === gen) { near = true; break; }
      if (near) cand.push(pl[j], a);
    }
    const targets0 = captureTargets(g, s);
    const tried = new Set();
    for (let c = 0; c < cand.length; c += 2) {
      const b = cand[c], a = cand[c + 1]; const kk = b * 1e6 + a; if (tried.has(kk)) continue; tried.add(kk);
      const u = placeAs(g, s, b, a);
      const pts1 = u.pts;
      let tg = null;
      if (!u.removed.length) { // targets unchanged; only those near a1 can newly become reachable
        const aq = a % S, ar = (a / S) | 0; const lim = 2 * L; tg = [];
        for (const t of targets0) { const dq = (t % S) - aq, dr = ((t / S) | 0) - ar; if ((Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2 <= lim) tg.push(t); }
      }
      const st2 = bestOneCapture(g, s, tg), b2 = st2 * g.stars[s];
      unplaceAs(g, u);
      if (pts1 + b2 > best) { best = pts1 + b2; bestSt = u.st + st2; }
    }
  }
  return [best, bestSt];
}
// place for an arbitrary seat (ignores turn order) -- used inside threat search
export function placeAs(g, s, b, a) {
  const ply = g.ply; g.ply = seatPly(s); const u = g.place(b, a); g.ply = ply; u.ply = ply; return u;
}
export function unplaceAs(g, u) { const ply = g.ply; g.ply = seatPly(u.s) + 1; g.undo(u); g.ply = ply; }
const seatPly = (s) => (s === 0 ? 0 : 1);

// ---- generic turn search bot ----
// params: wStar (value of one star of multiplier, scaled by remaining fraction), wThreat (weight of opp best capture),
// wExp (penalty per own exposed star), beam
export function makeBot(params = {}) {
  const P = { wStar: 3, wThreat: 1, wExp: 0, beam: 12, final: 8, edits: null, name: 'bot', ...params };
  if (typeof P.plan === 'string') P.edits = editPlan(P.plan, { startPly: P.planStart ?? 0 });
  let spent = 0, seqI = 0;
  const bot = (g) => {
    if (P.seqAt) { const sq = P.seqAt[g.seat()]; if (sq && seqI < sq.length && g.ply >= sq[seqI][0]) { const out = []; const n = g.movesLeftInTurn(); while (out.length < n && seqI < sq.length && g.ply + out.length >= sq[seqI][0]) out.push({ edit: sq[seqI++][1] }); if (out.length) return out; } }
    if (P.seq) { const sq = P.seq[g.seat()]; if (sq && seqI < sq.length && g.ply >= (P.seqStart || 0)) { const n = Math.min(g.movesLeftInTurn(), sq.length - seqI); const out = sq.slice(seqI, seqI + n).map((e) => ({ edit: e })); seqI += n; return out; } }
    if (P.designCost && spent < P.designCost) { const n = Math.min(g.movesLeftInTurn(), P.designCost - spent); spent += n; return Array(n).fill('pass'); }
    return chooseTurn(g, P);
  };
  bot.P = P; bot.label = P.name;
  return bot;
}

// Stars of seat s reachable from outside through empty / enemy / own non-wall cells (i.e. NOT enclosed by own walls).
const SG = new Int32Array(S * S); let sgen = 0; const STK = new Int32Array(S * S);
export function unsealedStars(g, s) {
  let qmin = 1e9, qmax = -1e9, rmin = 1e9, rmax = -1e9;
  for (const t of [0, 1]) for (const i of g.occupied(t)) { const q = i % S, r = (i / S) | 0; if (q < qmin) qmin = q; if (q > qmax) qmax = q; if (r < rmin) rmin = r; if (r > rmax) rmax = r; }
  qmin--; qmax++; rmin--; rmax++;
  const gen = ++sgen; let sp = 0, n = 0; const own = g.own, kind = g.kind;
  const push = (i) => { if (SG[i] === gen) return; const q = i % S, r = (i / S) | 0; if (q < qmin || q > qmax || r < rmin || r > rmax) return; if (own[i] === s && kind[i] === WALL) return; SG[i] = gen; STK[sp++] = i; };
  for (let q = qmin; q <= qmax; q++) { push(q + rmin * S); push(q + rmax * S); }
  for (let r = rmin; r <= rmax; r++) { push(qmin + r * S); push(qmax + r * S); }
  while (sp) { const i = STK[--sp]; if (own[i] === s && kind[i] === STAR) n++; for (let d = 0; d < 6; d++) push(i + NB[d]); }
  return n;
}
function staticEval(g, s, P) {
  const o = 1 - s, rem = Math.max(0, TOTAL - g.ply) / TOTAL;
  const ws = P.wStar * (P.flatStar ? 1 : rem);
  let v = (g.scores[s] - g.scores[o]) + ws * (g.stars[s] - g.stars[o]);
  if (P.wSeal) v += P.wSeal * rem * (0.5 * unsealedStars(g, o) * g.stars[s] - unsealedStars(g, s) * Math.max(6, g.stars[o]));
  if (!P.wExp) return v;
  return v - P.wExp * rem * exposedStars(g, s) * g.stars[o] / 6 + P.wExp * rem * exposedStars(g, o) * g.stars[s] / 6 * 0.3;
}

// Choose the full turn (1-2 actions). Returns list of move descriptors {b,a} or {edit:str} or 'pass'.
export function chooseTurn(g, P) {
  const s = g.seat(), n = g.movesLeftInTurn();
  // optional scripted edits (opening reshape plan)
  if (P.edits) { const e = P.edits(g, s); if (e) return e; }
  let pl = g.placements(s);
  let gapFilter = null;
  if (P.minGap) {
    // BFS distance from enemy cells; star-piece stamps must keep gap >= minGap unless they capture
    const o = 1 - s, gen = ++dgen; let fr = [];
    for (const i of g.occupied(o)) { DG[i] = gen; DD[i] = 0; fr.push(i); }
    for (let d = 1; d < P.minGap && fr.length; d++) { const nf = []; for (const c of fr) for (let k = 0; k < 6; k++) { const n = c + NB[k]; if (DG[n] !== gen) { DG[n] = gen; DD[n] = d; nf.push(n); } } fr = nf; }
    gapFilter = (list) => { const f = []; for (let j = 0; j < list.length; j += 2) { const bp = g.hands[s][list[j]], a = list[j + 1]; let ok = true; if (bp.stars) { for (const off of bp.offs) if (DG[a + off] === gen) { ok = false; break; } if (!ok && g.peekStars(s, list[j], a) > 0) ok = true; } if (ok) f.push(list[j], a); } return f.length ? f : list; };
    pl = gapFilter(pl);
  }
  if (P.starFreeUntil != null && g.ply < P.starFreeUntil) { const f = []; for (let j = 0; j < pl.length; j += 2) if (!g.hands[s][pl[j]].stars) f.push(pl[j], pl[j + 1]); if (f.length) pl = f; }
  if (P.starFreeAfter != null && g.ply >= P.starFreeAfter) { const f = []; for (let j = 0; j < pl.length; j += 2) if (!g.hands[s][pl[j]].stars) f.push(pl[j], pl[j + 1]); if (f.length) pl = f; }
  if (!pl.length) return ['pass'];
  // first action candidates by static eval after one action
  const first = [];
  for (let j = 0; j < pl.length; j += 2) {
    const u = g.place(pl[j], pl[j + 1]);
    first.push([staticEval(g, s, P) + (P.noise ? Math.random() * P.noise : 0), pl[j], pl[j + 1]]);
    g.undo(u);
  }
  first.sort((x, y) => y[0] - x[0]);
  let seqs = [];
  if (n === 1) seqs = first.slice(0, P.final).map(([v, b, a]) => [v, [[b, a]]]);
  else {
    const top = first.slice(0, P.beam);
    if (P.combo !== false) {
      // add erasing first actions that open a capture for the second action (erase-then-snipe)
      const combos = [];
      for (let j = 0; j < pl.length; j += 2) {
        const [, ce] = g.peek(s, pl[j], pl[j + 1]); if (!ce) continue;
        const u = g.place(pl[j], pl[j + 1]); const st2 = bestOneCapture(g, s); const v = u.pts + st2 * g.stars[s]; g.undo(u);
        if (st2 > 0) combos.push([v, pl[j], pl[j + 1]]);
      }
      combos.sort((x, y) => y[0] - x[0]);
      for (const c of combos.slice(0, 6)) if (!top.some((t) => t[1] === c[1] && t[2] === c[2])) top.push(c);
    }
    // also include top capturing first moves and erasers? (static eval already credits captures)
    for (const [, b, a] of top) {
      const u = g.place(b, a);
      let pl2 = g.placements(s); if (gapFilter) pl2 = gapFilter(pl2);
      for (let j = 0; j < pl2.length; j += 2) {
        const u2 = g.place(pl2[j], pl2[j + 1]);
        seqs.push([staticEval(g, s, P) + (P.noise ? Math.random() * P.noise : 0), [[b, a], [pl2[j], pl2[j + 1]]]]);
        g.undo(u2);
      }
      g.undo(u);
    }
    seqs.sort((x, y) => y[0] - x[0]);
    // dedupe identical end positions approx by value+set
    seqs = seqs.slice(0, P.final * 3);
  }
  // threat check: opponent best capture after our turn
  let best = null, bestV = -Infinity;
  const cands = seqs.slice(0, P.final);
  cands.sort((x, y) => y[0] - x[0]);
  for (const [v, mv] of cands) {
    if (v <= bestV) break; // threat penalty is >= 0, cannot beat current best
    const us = mv.map(([b, a]) => g.place(b, a));
    let val = v;
    if (P.wThreat && g.ply < TOTAL) {
      const o = 1 - s;
      const k = g.movesLeftInTurn() >= 2 ? 2 : 1;
      const [pts, st] = bestCapture(g, o, k);
      const rem = Math.max(0, TOTAL - g.ply) / TOTAL, ws = P.wStar * (P.flatStar ? 1 : rem);
      val -= P.wThreat * (pts + ws * st);
    }
    for (let i = us.length - 1; i >= 0; i--) g.undo(us[i]);
    if (val > bestV) { bestV = val; best = mv; }
  }
  return best.map(([b, a]) => ({ b, a }));
}

export function playGame(botA, botB, { log = false, maxPly = TOTAL, start = null } = {}) {
  const g = start ? start.clone() : Game.start();
  const bots = [botA, botB];
  bots.forEach((b, s) => { if (b.P && b.P.designHand) g.setHand(s, b.P.designHand(s)); });
  const hist = [];
  while (g.ply < maxPly) {
    const s = g.seat();
    const turn = bots[s](g);
    for (const m of turn) {
      if (g.ply >= maxPly || g.seat() !== s) break;
      if (m === 'pass') { g.pass(); hist.push('pass'); continue; }
      if (m.edit) { g.edit(m.edit); hist.push(m.edit); continue; }
      hist.push(g.moveString(m.b, m.a)); g.place(m.b, m.a);
    }
    if (log) console.log(g.ply, g.scores, g.stars);
  }
  return { scores: g.scores, stars: g.stars, hist, g };
}

// ---- scripted edit plans ----
// 'star6': move the lone stars of blueprints 1 and 3 into blueprint 2 (most compact spot). Returns a turn or null.
function bpNeighborsCount(bp, k) { let n = 0; for (const x of R.neighbors(k)) if (x in bp) n++; return n; }
export function editPlan(kind, opts = {}) {
  const startPly = opts.startPly ?? 0;
  return (g, s) => {
    if (g.ply < startPly) return null;
    const hand = g.hands[s].map((c) => c.bp);
    const out = [];
    let h = hand; const n = g.movesLeftInTurn();
    for (let a = 0; a < n; a++) {
      const mv = nextEdit(kind, h, opts); if (!mv) break;
      out.push({ edit: mv }); h = R.applyEdit(h, R.parseMove(mv)).hand;
    }
    if (!out.length) return null;

    return out;
  };
}
function nextEdit(kind, h, opts) {
  const T = opts.target ?? 1;
  if (kind === 'star6') {
    for (let f = 0; f < h.length; f++) {
      if (f === T) continue;
      const sk = Object.keys(h[f]).find((k) => h[f][k] === 'star'); if (!sk) continue;
      const moves = R.editMoves(h).filter((m) => m.startsWith(`${f + 1}:${sk}>${T + 1}:`));
      if (!moves.length) continue;
      moves.sort((a, b) => score(b) - score(a));
      function score(m) { const tk = m.split('>')[1].split(':')[1]; return bpNeighborsCount(h[T], tk) * 10 + R.neighbors(tk).filter((x) => h[T][x] === 'wall').length; }
      return moves[0];
    }
    return null;
  }
  return null;
}
