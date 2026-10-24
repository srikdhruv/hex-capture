// Fast Blueprints engine for experiments. Mirrors reference/rules.mjs exactly (verified by verify.mjs).
import * as R from '../reference/rules.mjs';

export const S = 256, OFF = 128;
export const WALL = 1, STAR = 2, PLAIN = 3;
const KIND = { wall: WALL, star: STAR, plain: PLAIN };
const KNAME = [null, 'wall', 'star', 'plain'];
export const NB = [1, 1 - S, -S, -1, -1 + S, S];
export const idx = (q, r) => (q + OFF) + (r + OFF) * S;
export const qr = (i) => [(i % S) - OFF, Math.floor(i / S) - OFF];
export const turnOf = R.turnOf;
export const TOTAL = R.TOTAL_PLIES;

// compiled blueprint: {cells:[[q,r,kind]], offs:Int32Array, kinds:Int8Array, stars}
export function compile(bp) {
  const cells = Object.entries(bp).map(([k, v]) => { const [q, r] = R.parse(k); return [q, r, KIND[v]]; });
  return { bp, cells, offs: Int32Array.from(cells.map(([q, r]) => q + r * S)), kinds: Int8Array.from(cells.map((c) => c[2])), stars: cells.filter((c) => c[2] === STAR).length };
}

export class Game {
  constructor() {}
  static fromRef(st) {
    const g = new Game();
    g.own = new Int8Array(S * S).fill(-1); g.kind = new Int8Array(S * S);
    g.stars = [0, 0]; g.ncell = [0, 0];
    for (const [k, [s, v]] of Object.entries(st.cells)) { const [q, r] = R.parse(k); const i = idx(q, r); g.own[i] = s; g.kind[i] = KIND[v]; if (KIND[v] === STAR) g.stars[s]++; g.ncell[s]++; }
    g.hands = st.blueprints.map((h) => h.map(compile));
    g.ply = st.ply; g.scores = [...st.scores];
    g.mark = new Int32Array(S * S); g.gen = 1;
    g.list = null; // lazily rebuilt occupied lists
    return g;
  }
  static start() { return Game.fromRef(R.setup()); }
  clone() {
    const g = new Game();
    g.own = this.own.slice(); g.kind = this.kind.slice(); g.stars = [...this.stars]; g.ncell = [...this.ncell];
    g.hands = this.hands.map((h) => [...h]); g.ply = this.ply; g.scores = [...this.scores];
    g.mark = new Int32Array(S * S); g.gen = 1; g.occ = this.occ ? [this.occ[0].slice(), this.occ[1].slice()] : null;
    return g;
  }
  toRef() {
    const cells = {};
    for (const s of [0, 1]) for (const i of this.occupied(s)) { const [q, r] = qr(i); cells[R.key(q, r)] = [s, KNAME[this.kind[i]]]; }
    return { ply: this.ply, cells, blueprints: this.hands.map((h) => h.map((c) => c.bp)), scores: [...this.scores] };
  }
  // occupied list per seat (recomputed lazily, maintained by place)
  occupied(s) {
    if (!this.occ) { this.occ = [[], []]; for (let i = 0; i < S * S; i++) if (this.own[i] >= 0) this.occ[this.own[i]].push(i); }
    return this.occ[s];
  }
  seat() { return turnOf(this.ply); }
  over() { return this.ply >= TOTAL; }
  frontier(s) {
    const g = ++this.gen, m = this.mark, out = [];
    for (const i of this.occupied(s)) for (let d = 0; d < 6; d++) { const n = i + NB[d]; if (this.own[n] < 0 && m[n] !== g) { m[n] = g; out.push(n); } }
    return out;
  }
  // list of placements for seat s: array of [bpIndex, anchorIdx]
  placements(s, which = null) {
    const fr = this.frontier(s), out = [], own = this.own;
    const hand = this.hands[s];
    for (let b = 0; b < hand.length; b++) {
      if (which !== null && which !== b) continue;
      const offs = hand[b].offs; if (!offs.length) continue;
      const g = ++this.gen, m = this.mark;
      for (const f of fr) for (let j = 0; j < offs.length; j++) {
        const a = f - offs[j]; if (m[a] === g) continue; m[a] = g;
        let ok = true; for (let k = 0; k < offs.length; k++) if (own[a + offs[k]] >= 0) { ok = false; break; }
        if (ok) out.push(b, a);
      }
    }
    return out; // flat pairs
  }
  // evaluate a placement without applying: returns {stars, cells} erased
  peek(s, b, a) {
    const bp = this.hands[s][b], g = ++this.gen, m = this.mark; let st = 0, ce = 0;
    const o = 1 - s;
    for (let k = 0; k < bp.offs.length; k++) { const c = a + bp.offs[k]; for (let d = 0; d < 6; d++) { const n = c + NB[d]; if (this.own[n] === o && this.kind[n] !== WALL && m[n] !== g) { m[n] = g; ce++; if (this.kind[n] === STAR) st++; } } }
    return [st, ce];
  }
  // apply placement; returns undo record
  place(b, a) {
    const s = this.seat(), o = 1 - s, bp = this.hands[s][b];
    const removed = []; const g = ++this.gen, m = this.mark; let st = 0;
    for (let k = 0; k < bp.offs.length; k++) { const c = a + bp.offs[k]; for (let d = 0; d < 6; d++) { const n = c + NB[d]; if (this.own[n] === o && this.kind[n] !== WALL && m[n] !== g) { m[n] = g; removed.push(n, this.kind[n]); if (this.kind[n] === STAR) st++; } } }
    const pts = st * this.stars[s];
    for (let j = 0; j < removed.length; j += 2) { this.own[removed[j]] = -1; }
    for (let k = 0; k < bp.offs.length; k++) { const c = a + bp.offs[k]; this.own[c] = s; this.kind[c] = bp.kinds[k]; }
    this.stars[o] -= st; this.stars[s] += bp.stars; this.ncell[o] -= removed.length / 2; this.ncell[s] += bp.offs.length;
    this.scores[s] += pts; this.ply++;
    if (this.occ) {
      if (removed.length) { const L = this.occ[o]; let w = 0; for (let j = 0; j < L.length; j++) { const i = L[j]; if (m[i] !== g) L[w++] = i; } L.length = w; }
      for (let k = 0; k < bp.offs.length; k++) this.occ[s].push(a + bp.offs[k]);
    }
    return { t: 'p', s, b, a, removed, pts, st };
  }
  undo(u) {
    if (u.t === 'pass') { this.ply--; return; }
    if (u.t === 'e') { this.hands[u.s] = u.prev; this.ply--; return; }
    const s = u.s, o = 1 - s, bp = this.hands[s][u.b];
    for (let k = 0; k < bp.offs.length; k++) this.own[u.a + bp.offs[k]] = -1;
    for (let j = 0; j < u.removed.length; j += 2) { this.own[u.removed[j]] = o; this.kind[u.removed[j]] = u.removed[j + 1]; }
    this.stars[o] += u.st; this.stars[s] -= bp.stars; this.ncell[o] += u.removed.length / 2; this.ncell[s] -= bp.offs.length;
    this.scores[s] -= u.pts; this.ply--;
    if (this.occ) {
      const n = bp.offs.length; this.occ[s].length -= n;
      for (let j = 0; j < u.removed.length; j += 2) this.occ[o].push(u.removed[j]);
    }
  }
  pass() { this.ply++; return { t: 'pass' }; }
  // edit using reference move string semantics: from [fi,fk] to [ti,tk]
  edit(mv) {
    const s = this.seat(); const m = R.parseMove(mv);
    const prev = this.hands[s];
    const { hand } = R.applyEdit(prev.map((c) => c.bp), m);
    this.hands[s] = hand.map((bp, i) => (bp === prev[i].bp ? prev[i] : compile(bp)));
    this.ply++;
    return { t: 'e', s, prev };
  }
  setHand(s, bps) { this.hands[s] = bps.map(compile); }
  editMoves(s) { return R.editMoves(this.hands[s].map((c) => c.bp)); }
  moveString(b, a) { const [q, r] = qr(a); return `${b + 1}@${q},${r}`; }
  playString(mv) {
    if (mv === 'pass') return this.pass();
    const m = R.parseMove(mv);
    if (m.type === 'place') return this.place(m.blueprint, idx(m.at[0], m.at[1]));
    return this.edit(mv);
  }
  movesLeftInTurn() { return R.movesLeftInTurn(this.ply); }
}
export { R };
