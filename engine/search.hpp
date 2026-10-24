// Turn-based selective search for Blueprints.
#pragma once
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iostream>
#include <mutex>
#include <numeric>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>
#if defined(_MSC_VER)
#include <intrin.h>
#endif
#include "game.hpp"

struct Params {
  double alpha = 0.10;    // value of a star per remaining ply (star diff * alpha * R)
  double beta = 0.5;      // weight of my 1-action capture threat at the leaf (I move next)
  double ordMy = 0.8;     // ordering: weight of my follow-up capture (mid-turn)
  double ordOpp = 1.0;    // ordering: weight of opponent 1-action capture
  double expo = 0.02;     // positional: exposed star (has empty neighbour) * enemy multiplier
  double approachW = 0;     // positional: (their approach cost - ours) to a hex next to an enemy star
  double expoB = 0;         // positional: BFS-reachable stars (targets) * multiplier, both sides
  double mob = 0.02;      // positional: frontier size difference
  double hcov = 0;        // hand: covered star-neighbour count of best star blueprint (shield value)
  double hw = 0.0;        // hand potential: stars in best blueprint * future stamps
  int editThreat = 1;     // reply search includes edit + capture
  int incr = 1;           // incremental follow-up capture computation
  int verify = 0;         // deep verification of top combos with a selective opponent turn
  int vK1 = 10, vK2 = 6;  // opponent widths in verification
  double widenFrac = 0.45;
  double widenStop = 0.85;
  double starScale[2] = {1, 1};  // per-side star value scale (set per search from enemy vulnerability)
  int noEditPly = 0;       // from this ply, edits only when they create a capture (0 = off)
  int bookYield = 2;        // 0: margin only, 1: yield if book concedes more stars, 2: yield on any threat/capture
  double minScale = 0.3;    // star scale floor
  int reachL = 12;          // BFS reach (empty hexes) for capture targets; 0 = use reachD hex distance
  int reachD = 7;           // enemy star counts as a target if within this hex distance of our cells (<=7)
  int vulnK = 4;            // star scale = min(1, vulnerable enemy stars / vulnK)  // no new widening stage after this fraction of the budget
  double bookMargin = 100; // play the book move if its value is within this of the best
  double buildBase = 0;   // reply baseline: unused actions build stars instead of passing
  int third = 1;          // leaf: 1 = my full 2-action capture turn, 0 = 1-action capture
  int maxK1 = 1024, maxK2 = 64;
  int openRand = 0;       // selfplay: randomize among top-N for first plies
  int openPlies = 0;
  int randPlies = 0;      // selfplay: first N plies are random placements
  void set(const std::string& kv) {
    auto p = kv.find('='); if (p == std::string::npos) return;
    std::string k = kv.substr(0, p); double v = atof(kv.c_str() + p + 1);
    if (k == "alpha") alpha = v; else if (k == "beta") beta = v; else if (k == "ordMy") ordMy = v;
    else if (k == "ordOpp") ordOpp = v; else if (k == "expo") expo = v;
    else if (k == "mob") mob = v; else if (k == "expoB") expoB = v; else if (k == "approachW") approachW = v; else if (k == "third") third = (int)v;
    else if (k == "hw") hw = v; else if (k == "hcov") { hcov = v; if (v != 0) g_needCover = true; } else if (k == "editThreat") editThreat = (int)v; else if (k == "incr") incr = (int)v;
    else if (k == "verify") verify = (int)v; else if (k == "vK1") vK1 = (int)v; else if (k == "vK2") vK2 = (int)v;
    else if (k == "widenFrac") widenFrac = v; else if (k == "widenStop") widenStop = v; else if (k == "vulnK") vulnK = (int)v; else if (k == "bookYield") bookYield = (int)v; else if (k == "noEditPly") noEditPly = (int)v; else if (k == "reachL") reachL = std::min(250, (int)v);
    else if (k == "minScale") minScale = v; else if (k == "reachD") reachD = std::min(7, (int)v); else if (k == "buildBase") buildBase = v;
    else if (k == "bookMargin") bookMargin = v;
    else if (k == "maxK1") maxK1 = (int)v; else if (k == "maxK2") maxK2 = (int)v;
    else if (k == "openRand") openRand = (int)v; else if (k == "openPlies") openPlies = (int)v; else if (k == "randPlies") randPlies = (int)v;
    else fprintf(stderr, "unknown param %s\n", k.c_str());
  }
};

inline int popcount64(uint64_t x) {
#if defined(__GNUC__) || defined(__clang__)
  return __builtin_popcountll(x);
#elif defined(_MSC_VER) && defined(_M_X64)
  return (int)__popcnt64(x);
#else
  x = x - ((x >> 1) & 0x5555555555555555ULL);
  x = (x & 0x3333333333333333ULL) + ((x >> 2) & 0x3333333333333333ULL);
  x = (x + (x >> 4)) & 0x0F0F0F0F0F0F0F0FULL;
  return (int)((x * 0x0101010101010101ULL) >> 56);
#endif
}

using Clock = std::chrono::steady_clock;
inline double msSince(Clock::time_point t) { return std::chrono::duration<double, std::milli>(Clock::now() - t).count(); }

// ---------- evaluation helpers ----------
inline double staticEval(const Game& g, int S, const Params& P) {
  int R = TOTAL_PLIES - g.ply;
  double v = (g.score[S] - g.score[1 - S]) + P.alpha * R * (g.stars[S] * P.starScale[S] - g.stars[1 - S] * P.starScale[1 - S]);
  if (P.hw != 0 || P.hcov != 0) {
    double b[2] = {0, 0}, cv[2] = {0, 0};
    for (int s = 0; s < 2; s++) for (int i = 0; i < 3; i++) {
      const BP& bp = g.hands[s].b[i];
      if (bp.stars > b[s]) b[s] = bp.stars;
      if (P.hcov != 0 && bp.stars) cv[s] = std::max(cv[s], (double)bp.cover);
    }
    v += P.hw * P.alpha * (b[S] - b[1 - S]) * (R * 0.5) * (R * 0.5);
    v += P.hcov * P.alpha * (cv[S] - cv[1 - S]) * (R * 0.5);
  }
  return v;
}

// Approach cost for X: fewest hexes X must cover (empty or erasable enemy plains) from its frontier
// to occupy a hex adjacent to an enemy star. Returns cap if none within cap.
inline int approachCost(Game& g, int X, int cap) {
  int Y = 1 - X;
  int q0 = std::max(-SAFE, g.minq - 2), q1 = std::min(SAFE, g.maxq + 2), r0 = std::max(-SAFE, g.minr - 2), r1 = std::min(SAFE, g.maxr + 2);
  static thread_local std::vector<uint8_t> dist; if (dist.empty()) dist.assign(G * G, 255);
  std::vector<int> touched, cur, nxt;
  auto passable = [&](int x) { uint8_t c = g.g[x]; return !c || (cseat(c) == Y && ckind(c) == PLAIN); };
  auto nearStar = [&](int x) { for (int d = 0; d < 6; d++) { uint8_t c = g.g[x + ND[d]]; if (c && cseat(c) == Y && ckind(c) == STAR) return true; } return false; };
  int found = cap;
  for (int r = g.minr - 1; r <= g.maxr + 1 && found == cap; r++) for (int q = g.minq - 1; q <= g.maxq + 1; q++) {
    int i = IDX(q, r); if (!passable(i) || dist[i] != 255) continue;
    for (int d = 0; d < 6; d++) { uint8_t c = g.g[i + ND[d]]; if (c && cseat(c) == X) { dist[i] = 1; touched.push_back(i); cur.push_back(i); if (nearStar(i)) found = 1; break; } }
  }
  for (int lev = 1; lev < cap && found == cap && !cur.empty(); lev++) {
    nxt.clear();
    for (int i : cur) for (int d = 0; d < 6; d++) {
      int x = i + ND[d]; if (dist[x] != 255 || !passable(x)) continue;
      int q = QOF(x), r = ROF(x); if (q < q0 || q > q1 || r < r0 || r > r1) continue;
      dist[x] = lev + 1; touched.push_back(x); nxt.push_back(x);
      if (nearStar(x)) { found = lev + 1; }
    }
    cur.swap(nxt);
  }
  for (int i : touched) dist[i] = 255;
  return found;
}

inline int reachableTargets(Game& g, int X, int L);
// Positional tie-break terms from S's perspective.
inline double positional(Game& g, int S, const Params& P) {
  double extra = 0;
  if (P.expoB != 0) {
    int O = 1 - S;
    int tS = reachableTargets(g, S, P.reachL), tO = reachableTargets(g, O, P.reachL);  // tO = my stars they can reach
    extra = P.expoB * (tS * g.stars[S] - tO * g.stars[O]);
  }
  if (P.approachW != 0) {
    int cS = approachCost(g, S, 24), cO = approachCost(g, 1 - S, 24);
    extra += P.approachW * (cO - cS);
  }
  if (P.expo == 0 && P.mob == 0) return extra;
  int expo[2] = {0, 0}, front[2] = {0, 0};
  for (int r = g.minr - 1; r <= g.maxr + 1; r++) for (int q = g.minq - 1; q <= g.maxq + 1; q++) {
    int i = IDX(q, r); uint8_t c = g.g[i];
    if (!c) {
      bool a0 = false, a1 = false;
      for (int d = 0; d < 6; d++) { uint8_t c2 = g.g[i + ND[d]]; if (c2) { if (cseat(c2)) a1 = true; else a0 = true; } }
      front[0] += a0; front[1] += a1;
    } else if (ckind(c) == STAR) {
      for (int d = 0; d < 6; d++) if (!g.g[i + ND[d]]) { expo[cseat(c)]++; break; }
    }
  }
  int O = 1 - S;
  return extra + P.expo * (expo[O] * g.stars[S] - expo[S] * g.stars[O]) + P.mob * (front[S] - front[O]);
}

// Attack cells: empty cells next to Y stars (mode 0) or next to Y stars / Y plains touching Y stars (mode 1).
inline void attackCells(Game& g, int X, int mode, std::vector<int>& att) {
  att.clear();
  int Y = 1 - X;
  uint32_t gm = g.nextGen();
  for (int r = g.minr; r <= g.maxr; r++) for (int q = g.minq; q <= g.maxq; q++) {
    int i = IDX(q, r); uint8_t c = g.g[i];
    if (!c || cseat(c) != Y) continue;
    int k = ckind(c);
    bool tgt = (k == STAR);
    if (!tgt && mode == 1 && k == PLAIN) {
      for (int d = 0; d < 6; d++) { uint8_t c2 = g.g[i + ND[d]]; if (c2 && cseat(c2) == Y && ckind(c2) == STAR) { tgt = true; break; } }
    }
    if (!tgt) continue;
    for (int d = 0; d < 6; d++) { int n = i + ND[d]; if (!g.g[n] && g.seen[n] != gm) { g.seen[n] = gm; att.push_back(n); } }
  }
}
// Hex disc offsets sorted by distance (radius <= 7).
struct Disc {
  std::vector<int> off; int upto[9];
  Disc() {
    for (int dist = 1; dist <= 7; dist++) {
      for (int dq = -dist; dq <= dist; dq++) for (int dr = -dist; dr <= dist; dr++) {
        int ds = -dq - dr; if ((abs(dq) + abs(dr) + abs(ds)) / 2 == dist) off.push_back(dr * G + dq);
      }
      upto[dist] = off.size();
    }
    upto[0] = 0; upto[8] = off.size();
  }
};
inline const Disc& disc() { static Disc d; return d; }
// Distance (capped at cap+1) from cell e to the nearest X-owned cell.
inline int nearDist(const Game& g, int X, int e, int cap) {
  const Disc& D = disc();
  if (cap > 7) return 0;
  for (int dist = 1; dist <= cap; dist++)
    for (int k = D.upto[dist - 1]; k < D.upto[dist]; k++) { uint8_t c = g.g[e + D.off[k]]; if (c && cseat(c) == X) return dist; }
  return cap + 1;
}
// Legal placements of X's blueprints (mask) covering at least one attack cell.
inline void candsFromCells(Game& g, int X, const std::vector<int>& att, int mask, std::vector<Move>& out) {
  out.clear();
  if (att.empty()) return;
  const Hand& h = g.hands[X];
  int maxRad = 0;
  for (int b = 0; b < 3; b++) if ((mask >> b & 1) && h.b[b].n) maxRad = std::max(maxRad, h.b[b].diam + 1);
  static thread_local std::vector<int> nd; nd.resize(att.size());
  for (size_t x = 0; x < att.size(); x++) nd[x] = nearDist(g, X, att[x], maxRad);
  for (int b = 0; b < 3; b++) {
    if (!(mask >> b & 1)) continue;
    const BP& bp = h.b[b]; if (!bp.n) continue;
    uint32_t gn = g.nextGen();
    for (size_t x = 0; x < att.size(); x++) {
      if (nd[x] > bp.diam + 1) continue;
      int e = att[x];
      for (int j = 0; j < bp.n; j++) {
      int off = e - bp.d[j]; if (g.seen[off] == gn) continue; g.seen[off] = gn;
      int oq = QOF(off), orr = ROF(off); bool ok = true, touch = false;
      for (int m = 0; m < bp.n; m++) {
        int qq = oq + bp.q[m], rr = orr + bp.r[m];
        if (qq < -SAFE || qq > SAFE || rr < -SAFE || rr > SAFE) { ok = false; break; }
        int i = off + bp.d[m];
        if (g.g[i]) { ok = false; break; }
        if (!touch) for (int d = 0; d < 6; d++) { uint8_t c = g.g[i + ND[d]]; if (c && cseat(c) == X) { touch = true; break; } }
      }
      if (ok && touch) { Move mv; mv.type = 0; mv.bp = b; mv.q = oq; mv.r = orr; out.push_back(mv); }
      }
    }
  }
}
inline void attackCands(Game& g, int X, int mode, std::vector<Move>& out) {
  static thread_local std::vector<int> att; attackCells(g, X, mode, att); candsFromCells(g, X, att, 7, out);
}

// Number of Y stars a placement by X would erase (no apply).
inline int starsErased(Game& g, int X, const Move& mv) {
  const BP& bp = g.hands[X].b[mv.bp]; int base = IDX(mv.q, mv.r);
  uint32_t gm = g.nextGen(); int n = 0;
  for (int j = 0; j < bp.n; j++) {
    int i = base + bp.d[j];
    for (int d = 0; d < 6; d++) {
      int x = i + ND[d]; uint8_t c = g.g[x];
      if (c && cseat(c) != X && ckind(c) == STAR && g.seen[x] != gm) { g.seen[x] = gm; n++; }
    }
  }
  return n;
}

inline int bestCapCells(Game& g, int X, const std::vector<int>& att, int mask, Move* best) {
  static thread_local std::vector<Move> c; candsFromCells(g, X, att, mask, c);
  int bestN = 0;
  for (auto& m : c) { int n = starsErased(g, X, m); if (n > bestN) { bestN = n; if (best) *best = m; } }
  return bestN * g.stars[X];
}
// Best immediate capture (points) for X with one placement.
inline int bestCap1(Game& g, int X, Move* best = nullptr) {
  static thread_local std::vector<int> att; attackCells(g, X, 0, att);
  return bestCapCells(g, X, att, 7, best);
}

// Precomputed capture list for X on a board: candidates with >0 stars, sorted by count desc.
struct CapC { Move m; int n; };
inline void capList(Game& g, int X, std::vector<CapC>& out) {
  out.clear();
  static thread_local std::vector<Move> c; attackCands(g, X, 0, c);
  for (auto& m : c) { int n = starsErased(g, X, m); if (n > 0) out.push_back({m, n}); }
  std::sort(out.begin(), out.end(), [](const CapC& a, const CapC& b) { return a.n > b.n; });
}
inline bool placeValid(const Game& g, int X, const Move& m) {
  const BP& bp = g.hands[X].b[m.bp]; int base = IDX(m.q, m.r); bool touch = false;
  for (int j = 0; j < bp.n; j++) {
    int i = base + bp.d[j]; if (g.g[i]) return false;
    if (!touch) for (int d = 0; d < 6; d++) { uint8_t c = g.g[i + ND[d]]; if (c && cseat(c) == X) { touch = true; break; } }
  }
  return touch;
}
// Best capture for X after a move whose changed cells are in u (board before = the one C0 was built on, same hand for X).
inline int bestCapAfter(Game& g, int X, const std::vector<CapC>& C0, const Undo& u, Move* best = nullptr) {
  int bestN = 0;
  for (auto& cc : C0) {
    if (cc.n <= bestN) break;
    if (!placeValid(g, X, cc.m)) continue;
    int n = starsErased(g, X, cc.m); if (n > bestN) { bestN = n; if (best) *best = cc.m; }
  }
  if (u.nch) {
    int md = 0; for (int b = 0; b < 3; b++) md = std::max(md, g.hands[X].b[b].diam);
    int R = std::min(7, md + 2);
    const Disc& D = disc();
    static thread_local std::vector<int> att; att.clear();
    uint32_t gm = g.nextGen(); int Y = 1 - X;
    for (int x = 0; x < u.nch; x++) {
      int c0 = u.idx[x];
      for (int k = -1; k < D.upto[R]; k++) {
        int y = k < 0 ? c0 : c0 + D.off[k];
        if (g.seen[y] == gm) continue; g.seen[y] = gm;
        if (g.g[y]) continue;
        for (int d = 0; d < 6; d++) { uint8_t c = g.g[y + ND[d]]; if (c && cseat(c) == Y && ckind(c) == STAR) { att.push_back(y); break; } }
      }
    }
    static thread_local std::vector<Move> c; candsFromCells(g, X, att, 7, c);
    for (auto& m : c) { int n = starsErased(g, X, m); if (n > bestN) { bestN = n; if (best) *best = m; } }
  }
  return bestN * g.stars[X];
}

struct Reply { double val, base = 0; Move m1, m2; };

// Radius-4 hex disc as 61 bits around a centre cell.
struct Disc4 {
  int bit[9][9]; int off[61]; int n = 0;
  Disc4() {
    for (int dq = -4; dq <= 4; dq++) for (int dr = -4; dr <= 4; dr++) {
      int ds = -dq - dr; bit[dq + 4][dr + 4] = -1;
      if ((abs(dq) + abs(dr) + abs(ds)) / 2 <= 4) { bit[dq + 4][dr + 4] = n; off[n] = dr * G + dq; n++; }
    }
  }
};
inline const Disc4& disc4() { static Disc4 d; return d; }
struct ShapeMasks { bool ok = false; int n = 0; uint64_t sm[24], nm[24]; int d[24]; };
inline void buildShapeMasks(const BP& bp, ShapeMasks& M) {
  M.ok = false; M.n = bp.n; if (bp.diam > 3 || bp.n == 0) return;
  const Disc4& D = disc4();
  for (int j = 0; j < bp.n; j++) {
    uint64_t sm = 0, nm = 0;
    for (int m = 0; m < bp.n; m++) sm |= 1ULL << D.bit[bp.q[m] - bp.q[j] + 4][bp.r[m] - bp.r[j] + 4];
    for (int m = 0; m < bp.n; m++) for (int d = 0; d < 6; d++) {
      int a = bp.q[m] - bp.q[j] + DQ[d], b = bp.r[m] - bp.r[j] + DR[d];
      if (a < -4 || a > 4 || b < -4 || b > 4) continue;
      int bt = D.bit[a + 4][b + 4]; if (bt >= 0) nm |= 1ULL << bt;
    }
    M.sm[j] = sm; M.nm[j] = nm & ~sm; M.d[j] = bp.d[j];
  }
  M.ok = true;
}
inline uint64_t shapeHash(const BP& bp) {
  uint64_t sum = 0;
  for (int j = 0; j < bp.n; j++) { uint64_t x = (uint64_t)(bp.q[j] + 64) * 131 + (bp.r[j] + 64); x *= 0x9E3779B97F4A7C15ULL; x ^= x >> 29; sum += x; }
  return sum ^ ((uint64_t)bp.n << 56);
}

// Edit + capture threats for O (board fixed, only O's hand changes). Updates rep if better.
inline void editCaptures(Game& g, int O, const Params& P, Reply& rep) {
  std::vector<int> att0, att, nd; attackCells(g, O, 0, att0);
  int md = 0; for (int b = 0; b < 3; b++) md = std::max(md, g.hands[O].b[b].diam);
  for (int e : att0) { int dd = nearDist(g, O, e, md + 2); if (dd <= md + 2) { att.push_back(e); nd.push_back(dd); } }
  if (att.empty()) return;
  // O frontier marks
  static thread_local std::vector<uint8_t> fr; if (fr.empty()) fr.assign(G * G, 0);
  std::vector<int> frl;
  for (int r = g.minr - 1; r <= g.maxr + 1; r++) for (int q = g.minq - 1; q <= g.maxq + 1; q++) {
    int i = IDX(q, r); if (g.g[i]) continue;
    for (int d = 0; d < 6; d++) { uint8_t c = g.g[i + ND[d]]; if (c && cseat(c) == O) { fr[i] = 1; frl.push_back(i); break; } }
  }
  struct Ent { int n; int off; };
  std::unordered_map<uint64_t, Ent> cache;
  std::vector<int> cand;
  // per attack cell neighbourhood masks
  const Disc4& D4 = disc4();
  std::vector<uint64_t> occM(att.size()), starM(att.size()), ownM(att.size());
  for (size_t x = 0; x < att.size(); x++) {
    uint64_t oc = 0, st = 0, ow = 0; int e = att[x];
    for (int k = 0; k < D4.n; k++) {
      uint8_t c = g.g[e + D4.off[k]]; if (!c) continue;
      oc |= 1ULL << k;
      if (cseat(c) == O) ow |= 1ULL << k; else if (ckind(c) == STAR) st |= 1ULL << k;
    }
    occM[x] = oc; starM[x] = st; ownM[x] = ow;
  }
  static thread_local std::unordered_map<uint64_t, ShapeMasks> smCache;
  if (smCache.size() > 20000) smCache.clear();
  auto fitSlow = [&](const BP& bp) -> Ent {
    Ent best{0, 0}; cand.clear();
    uint32_t gn = g.nextGen();
    for (size_t x = 0; x < att.size(); x++) {
      if (nd[x] > bp.diam + 1) continue;
      int e = att[x];
      for (int j = 0; j < bp.n; j++) {
        int off = e - bp.d[j]; if (g.seen[off] == gn) continue; g.seen[off] = gn;
        int oq = QOF(off), orr = ROF(off);
        if (oq < -SAFE + 22 || oq > SAFE - 22 || orr < -SAFE + 22 || orr > SAFE - 22) continue;
        bool ok = true, touch = false;
        for (int m = 0; m < bp.n; m++) { int i = off + bp.d[m]; if (g.g[i]) { ok = false; break; } touch |= fr[i]; }
        if (ok && touch) cand.push_back(off);
      }
    }
    for (int off : cand) {
      uint32_t gm = g.nextGen(); int n = 0;
      for (int j = 0; j < bp.n; j++) {
        int i = off + bp.d[j];
        for (int d = 0; d < 6; d++) { int x = i + ND[d]; uint8_t c = g.g[x]; if (c && cseat(c) != O && ckind(c) == STAR && g.seen[x] != gm) { g.seen[x] = gm; n++; } }
      }
      if (n > best.n) { best.n = n; best.off = off; }
    }
    return best;
  };
  auto fitBest = [&](const BP& bp) -> Ent {
    Ent best{0, 0};
    uint64_t hh = shapeHash(bp);
    auto it = smCache.find(hh);
    if (it == smCache.end()) { ShapeMasks M; buildShapeMasks(bp, M); it = smCache.emplace(hh, M).first; }
    const ShapeMasks& M = it->second;
    if (M.ok) {
      for (size_t x = 0; x < att.size(); x++) {
        if (nd[x] > bp.diam + 1) continue;
        int e = att[x];
        if (QOF(e) < -SAFE + 22 || QOF(e) > SAFE - 22 || ROF(e) < -SAFE + 22 || ROF(e) > SAFE - 22) continue;
        for (int j = 0; j < M.n; j++) {
          if ((M.sm[j] & occM[x]) || !(M.nm[j] & ownM[x])) continue;
          int n = popcount64(M.nm[j] & starM[x]);
          if (n > best.n) { best.n = n; best.off = e - M.d[j]; }
        }
      }
#ifdef CHECK_MASKS
      Ent slow = fitSlow(bp);
      if (slow.n != best.n) fprintf(stderr, "MASK MISMATCH %d vs %d\n", best.n, slow.n);
#endif
      return best;
    }
    return fitSlow(bp);
  };
  std::vector<Move> E; Game::genEdits(g.hands[O], E);
  for (auto& e : E) {
    Undo u; g.apply(e, u);
    int bb = -1; Ent be{0, 0};
    for (int b : {(int)e.fi, (int)e.ti}) {
      const BP& bp = g.hands[O].b[b]; if (!bp.n) continue;
      uint64_t h = 1469598103934665603ULL;
      uint64_t sum = 0; for (int j = 0; j < bp.n; j++) { uint64_t x = (uint64_t)(bp.q[j] + 64) * 131 + (bp.r[j] + 64); x *= 0x9E3779B97F4A7C15ULL; x ^= x >> 29; sum += x; }
      h ^= sum + bp.n;
      auto it = cache.find(h); Ent en;
      if (it == cache.end()) { en = fitBest(bp); cache.emplace(h, en); } else en = it->second;
      if (en.n > be.n) { be = en; bb = b; }
    }
    if (be.n > 0) {
      Move bm; bm.type = 0; bm.bp = bb; bm.q = QOF(be.off); bm.r = ROF(be.off);
      Undo u2; g.apply(bm, u2); double v = staticEval(g, O, P); g.undo(u2);
      if (v > rep.val) { rep.val = v; rep.m1 = e; rep.m2 = bm; }
    }
    g.undo(u);
  }
  for (int i : frl) fr[i] = 0;
}

// Side O plays L actions (capture-oriented): breach/capture placement + capture, or edit + capture.
inline Reply replySearch(Game& g, int O, int L, const Params& P) {
  Reply rep; rep.val = staticEval(g, O, P); rep.m1.type = 2; rep.m2.type = 2;
  if (L <= 0 || g.ply >= TOTAL_PLIES) { rep.base = rep.val; return rep; }
  double bv = 0;
  if (P.buildBase > 0) {
    int bs = 0; for (int b = 0; b < 3; b++) bs = std::max(bs, g.hands[O].b[b].stars);
    bv = P.buildBase * P.alpha * (TOTAL_PLIES - g.ply) * bs;
  }
  rep.val += bv * L; rep.base = rep.val;
  std::vector<Move> c1; attackCands(g, O, L >= 2 ? 1 : 0, c1);
  std::vector<CapC> C0; if (L >= 2) capList(g, O, C0);
  for (auto& m : c1) {
    Undo u; g.apply(m, u);
    double v = staticEval(g, O, P); Move m2; m2.type = 2;
    if (L >= 2 && g.ply < TOTAL_PLIES) {
      Move bm; int pts = P.incr ? bestCapAfter(g, O, C0, u, &bm) : bestCap1(g, O, &bm);
      if (pts > 0) { Undo u2; g.apply(bm, u2); v = staticEval(g, O, P); g.undo(u2); m2 = bm; }
      else v += bv;
    }
    g.undo(u);
    if (v > rep.val) { rep.val = v; rep.m1 = m; rep.m2 = m2; }
  }
  if (L >= 2 && P.editThreat && g.ply + 1 < TOTAL_PLIES) editCaptures(g, O, P, rep);
  return rep;
}

// Leaf value from S's perspective when S is to move: static + weighted own capture turn + positional.
inline double leafS(Game& g, int S, const Params& P) {
  double v = staticEval(g, S, P);
  if (g.ply >= TOTAL_PLIES) return v;
  if (P.third) { Reply mt = replySearch(g, S, movesLeftInTurn(g.ply), P); v += P.beta * (mt.val - mt.base); }
  else v += P.beta * bestCap1(g, S);
  return v + positional(g, S, P);
}

// Opponent (1-S) to move: selective search over their turn; returns min leafS value (S perspective).
// Always includes the greedy capture line, so the result is <= the shallow leaf value.
inline double deepOpp(Game& g, int S, const Params& P, int K1, int K2, const std::function<bool()>& stop, Move* bm1 = nullptr, Move* bm2 = nullptr) {
  if (g.ply >= TOTAL_PLIES) return staticEval(g, S, P);
  int O = 1 - S, LO = movesLeftInTurn(g.ply);
  double best;
  {
    Reply rp = replySearch(g, O, LO, P);
    Undo a, b;
    if (rp.m1.type != 2) g.apply(rp.m1, a);
    if (rp.m2.type != 2) g.apply(rp.m2, b);
    best = leafS(g, S, P);
    if (rp.m2.type != 2) g.undo(b);
    if (rp.m1.type != 2) g.undo(a);
    if (bm1) { *bm1 = rp.m1; *bm2 = rp.m2; }
  }
  std::vector<Move> A; g.genAll(A);
  std::vector<CapC> C0; if (LO >= 2) capList(g, O, C0); else capList(g, S, C0);
  std::vector<std::pair<double, int>> sc(A.size());
  for (size_t k = 0; k < A.size(); k++) {
    Undo u; g.apply(A[k], u);
    double v = staticEval(g, O, P);
    if (LO >= 2) v += P.ordMy * (A[k].type == 0 ? bestCapAfter(g, O, C0, u) : bestCap1(g, O));
    else v -= P.ordOpp * bestCapAfter(g, S, C0, u);
    g.undo(u); sc[k] = {v, (int)k};
  }
  std::partial_sort(sc.begin(), sc.begin() + std::min<size_t>(K1, sc.size()), sc.end(), [](auto& a, auto& b) { return a.first > b.first; });
  for (int i = 0; i < K1 && i < (int)sc.size(); i++) {
    if (stop()) break;
    const Move& m1 = A[sc[i].second];
    Undo u1; g.apply(m1, u1);
    if (LO >= 2 && g.ply < TOTAL_PLIES) {
      std::vector<Move> B; g.genAll(B);
      std::vector<CapC> CS; capList(g, S, CS);
      std::vector<std::pair<double, int>> s2(B.size());
      for (size_t k = 0; k < B.size(); k++) {
        Undo u2; g.apply(B[k], u2);
        s2[k] = {staticEval(g, O, P) - P.ordOpp * bestCapAfter(g, S, CS, u2), (int)k};
        g.undo(u2);
      }
      std::partial_sort(s2.begin(), s2.begin() + std::min<size_t>(K2, s2.size()), s2.end(), [](auto& a, auto& b) { return a.first > b.first; });
      for (int j = 0; j < K2 && j < (int)s2.size(); j++) {
        Undo u2; g.apply(B[s2[j].second], u2);
        double v = leafS(g, S, P);
        g.undo(u2);
        if (v < best) { best = v; if (bm1) { *bm1 = m1; *bm2 = B[s2[j].second]; } }
      }
    } else {
      double v = leafS(g, S, P);
      if (v < best) { best = v; if (bm1) { *bm1 = m1; bm2->type = 2; } }
    }
    g.undo(u1);
  }
  return best;
}

// Stars of Y that can ever be captured: connected through Y's non-wall cells to an empty cell.
inline int vulnerableStars(Game& g, int Y, int reach = 0) {
  std::vector<int> st, stars; uint32_t gm = g.nextGen();
  for (int r = g.minr; r <= g.maxr; r++) for (int q = g.minq; q <= g.maxq; q++) {
    int i = IDX(q, r); uint8_t c = g.g[i];
    if (!c || cseat(c) != Y || ckind(c) == WALL) continue;
    for (int d = 0; d < 6; d++) if (!g.g[i + ND[d]]) { g.seen[i] = gm; st.push_back(i); break; }
  }
  int n = 0;
  while (!st.empty()) {
    int i = st.back(); st.pop_back();
    if (ckind(g.g[i]) == STAR) { if (reach <= 0) n++; else stars.push_back(i); }
    for (int d = 0; d < 6; d++) {
      int x = i + ND[d]; uint8_t c = g.g[x];
      if (c && cseat(c) == Y && ckind(c) != WALL && g.seen[x] != gm) { g.seen[x] = gm; st.push_back(x); }
    }
  }
  for (int i : stars) if (nearDist(g, 1 - Y, i, reach) <= reach) n++;
  return n;
}

// Capture targets for X: enemy stars whose empty (or erasable) neighbour is reachable from X's frontier
// by a path of at most L empty hexes (BFS over empty cells; a connected blueprint can snake).
inline int reachableTargets(Game& g, int X, int L) {
  int Y = 1 - X, M = L + 2;
  int q0 = std::max(-SAFE, g.minq - M), q1 = std::min(SAFE, g.maxq + M), r0 = std::max(-SAFE, g.minr - M), r1 = std::min(SAFE, g.maxr + M);
  static thread_local std::vector<uint8_t> dist; if (dist.empty()) dist.assign(G * G, 255);
  std::vector<int> touched, cur, nxt;
  auto inBox = [&](int i) { int q = QOF(i), r = ROF(i); return q >= q0 && q <= q1 && r >= r0 && r <= r1; };
  for (int r = g.minr - 1; r <= g.maxr + 1; r++) for (int q = g.minq - 1; q <= g.maxq + 1; q++) {
    int i = IDX(q, r); if (g.g[i] || dist[i] != 255) continue;
    for (int d = 0; d < 6; d++) { uint8_t c = g.g[i + ND[d]]; if (c && cseat(c) == X) { dist[i] = 1; touched.push_back(i); cur.push_back(i); break; } }
  }
  for (int lev = 1; lev < L && !cur.empty(); lev++) {
    nxt.clear();
    for (int i : cur) for (int d = 0; d < 6; d++) {
      int x = i + ND[d]; if (g.g[x] || dist[x] != 255 || !inBox(x)) continue;
      dist[x] = lev + 1; touched.push_back(x); nxt.push_back(x);
    }
    cur.swap(nxt);
  }
  int n = 0;
  for (int r = g.minr; r <= g.maxr; r++) for (int q = g.minq; q <= g.maxq; q++) {
    int i = IDX(q, r); uint8_t c = g.g[i];
    if (!c || cseat(c) != Y || ckind(c) != STAR) continue;
    bool ok = false;
    for (int d = 0; d < 6 && !ok; d++) {
      int x = i + ND[d]; uint8_t cx = g.g[x];
      if (!cx) { if (dist[x] != 255) ok = true; }
      else if (cseat(cx) == Y && ckind(cx) != WALL) {
        for (int e = 0; e < 6; e++) { int y = x + ND[e]; if (!g.g[y] && dist[y] != 255 && dist[y] < L) { ok = true; break; } }
      }
    }
    if (ok) n++;
  }
  for (int i : touched) dist[i] = 255;
  return n;
}

struct SearchResult { std::string move, json; double eval = 0; };

struct Combo { int i, j; double val = -1e18; bool done = false; Move r1, r2; double deep = -1e18; bool verified = false; int myPts = 0, lost = 0; };

inline SearchResult searchRoot(Game& root, int timeMs, int threads, const Params& P0,
                               const std::vector<std::string>& allowed, bool verbose, std::mt19937_64* rng = nullptr,
                               const std::string& bookMove = "") {
  auto t0 = Clock::now();
  double budget = std::max(50.0, timeMs * 0.92 - 30);
  Params P = P0;
  if (P.vulnK > 0) for (int x = 0; x < 2; x++)
    P.starScale[x] = std::max(P.minScale, std::min(1.0, (P.reachL > 0 ? reachableTargets(root, x, P.reachL) : vulnerableStars(root, 1 - x, P.reachD)) / (double)P.vulnK));
  if (verbose) fprintf(stderr, "starScale %.2f %.2f approach %d %d\n", P.starScale[0], P.starScale[1], approachCost(root, 0, 24), approachCost(root, 1, 24));
  SearchResult res;
  if (root.ply >= TOTAL_PLIES) return res;
  int S = turnOf(root.ply), O = 1 - S, L = movesLeftInTurn(root.ply);
  std::vector<Move> A; root.genAll(A);
  if (!allowed.empty()) {
    std::unordered_set<std::string> al(allowed.begin(), allowed.end());
    std::vector<Move> B; for (auto& m : A) if (al.count(root.moveStr(m))) B.push_back(m);
    if (B.empty()) { for (auto& s : allowed) { Move m; if (root.parseMove(s, m)) B.push_back(m); } }
    A.swap(B);
  }
  if (A.empty()) return res;
  std::atomic<long long> nodes{0};
  auto par = [&](int n, const std::function<void(Game&, int)>& fn) {
    std::atomic<int> next{0};
    int T = std::max(1, std::min(threads, n));
    auto work = [&]() { Game g = root; int k; while ((k = next++) < n) { if (msSince(t0) > budget) break; fn(g, k); } };
    if (T == 1) { work(); return; }
    std::vector<std::thread> th; for (int t = 0; t < T; t++) th.emplace_back(work); for (auto& t : th) t.join();
  };
  // Post-book edit guard: after noEditPly, edits only if they increase our immediate capture.
  bool noEditNow = P.noEditPly > 0 && root.ply >= P.noEditPly;
  if (noEditNow) {
    int base = L >= 2 ? bestCap1(root, S) : 0;
    std::vector<Move> B;
    for (auto& m : A) {
      if (m.type != 1) { B.push_back(m); continue; }
      if (L < 2) continue;
      Undo u; root.apply(m, u); int c = bestCap1(root, S); root.undo(u);
      if (c > base) B.push_back(m);
    }
    if (!B.empty()) A.swap(B);
  }
  // Ordering of first actions
  int n1 = A.size(); std::vector<double> ov(n1, -1e18);
  std::vector<CapC> C0S, C0O;
  if (P.incr) { Game& gg = root; if (L >= 2) capList(gg, S, C0S); else capList(gg, O, C0O); }
  par(n1, [&](Game& g, int k) {
    Undo u; g.apply(A[k], u);
    double v = staticEval(g, S, P);
    if (L >= 2) v += P.ordMy * ((P.incr && A[k].type == 0) ? bestCapAfter(g, S, C0S, u) : bestCap1(g, S));
    else v -= P.ordOpp * (P.incr ? bestCapAfter(g, O, C0O, u) : bestCap1(g, O));
    g.undo(u); ov[k] = v; nodes++;
  });
  std::vector<int> ord(n1); std::iota(ord.begin(), ord.end(), 0);
  std::stable_sort(ord.begin(), ord.end(), [&](int a, int b) { return ov[a] > ov[b]; });
  bool haveBook = false;
  // Abandon the book once the opponent has scored against us (they attack instead of building).
  if (!bookMove.empty() && (P.bookYield < 1 || root.score[O] == 0)) {
    for (int k = 0; k < n1; k++) if (root.moveStr(A[ord[k]]) == bookMove) {
      int x = ord[k]; ord.erase(ord.begin() + k); ord.insert(ord.begin(), x); haveBook = true; break;
    }
  }
  // Second-action lists (lazy)
  std::vector<std::vector<Move>> second(n1);
  std::vector<char> secondReady(n1, 0);
  auto buildSecond = [&](Game& g, int i) {
    Undo u; g.apply(A[ord[i]], u);
    std::vector<Move> B; g.genAll(B);
    if (noEditNow) { std::vector<Move> B2; for (auto& m : B) if (m.type != 1) B2.push_back(m); if (!B2.empty()) B.swap(B2); }
    std::vector<std::pair<double, int>> sc(B.size());
    std::vector<CapC> C0; if (P.incr) capList(g, O, C0);
    for (size_t k = 0; k < B.size(); k++) {
      Undo u2; g.apply(B[k], u2);
      double v = staticEval(g, S, P) - P.ordOpp * (P.incr ? bestCapAfter(g, O, C0, u2) : bestCap1(g, O));
      g.undo(u2); sc[k] = {v, (int)k};
    }
    std::stable_sort(sc.begin(), sc.end(), [](auto& a, auto& b) { return a.first > b.first; });
    std::vector<Move> out; for (int k = 0; k < (int)sc.size() && k < P.maxK2; k++) out.push_back(B[sc[k].second]);
    g.undo(u); second[i] = std::move(out); secondReady[i] = 1; nodes += B.size();
  };
  // Leaf evaluation
  auto leafEval = [&](Game& g, Combo& c) {
    Undo u1, u2; bool two = (L >= 2 && c.j >= 0);
    g.apply(A[ord[c.i]], u1);
    if (two) g.apply(second[c.i][c.j], u2);
    double v;
    c.myPts = g.score[S] - root.score[S];
    if (g.ply >= TOTAL_PLIES) v = staticEval(g, S, P);
    else {
      int LO = movesLeftInTurn(g.ply);
      Reply rp = replySearch(g, O, LO, P);
      c.r1 = rp.m1; c.r2 = rp.m2;
      Undo a, b;
      int starsBefore = g.stars[S];
      if (rp.m1.type != 2) g.apply(rp.m1, a);
      if (rp.m2.type != 2) g.apply(rp.m2, b);
      c.lost = starsBefore - g.stars[S];
      v = leafS(g, S, P);
      if (rp.m2.type != 2) g.undo(b);
      if (rp.m1.type != 2) g.undo(a);
    }
    if (two) g.undo(u2);
    g.undo(u1);
    c.val = v; c.done = true; nodes++;
  };
  std::vector<Combo> combos;
  std::set<std::pair<int, int>> have;
  const int K1s[] = {4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024};
  const int K2s[] = {4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 56, 64, 64, 64, 64};
  const int NST = 16;
  int stage = 0;
  for (; stage < NST; stage++) {
    if (msSince(t0) > budget * (P.verify ? P.widenFrac : P.widenStop) && stage > 0) break;
    int K1 = std::min({K1s[stage], n1, L >= 2 ? P.maxK1 : 100000});
    if (L < 2) K1 = std::min(n1, K1s[stage] * 4);
    std::vector<int> needSecond;
    if (L >= 2) for (int i = 0; i < K1; i++) if (!secondReady[i]) needSecond.push_back(i);
    if (!needSecond.empty()) par(needSecond.size(), [&](Game& g, int k) { buildSecond(g, needSecond[k]); });
    size_t startIdx = combos.size();
    for (int i = 0; i < K1; i++) {
      if (L >= 2) {
        if (!secondReady[i]) continue;
        int K2 = std::min<int>({K2s[stage], (int)second[i].size(), P.maxK2});
        if (second[i].empty() && !have.count({i, -1})) { have.insert({i, -1}); combos.push_back({i, -1}); }
        for (int j = 0; j < K2; j++) if (!have.count({i, j})) { have.insert({i, j}); combos.push_back({i, j}); }
      } else if (!have.count({i, -1})) { have.insert({i, -1}); combos.push_back({i, -1}); }
    }
    int nn = combos.size() - startIdx;
    par(nn, [&](Game& g, int k) { leafEval(g, combos[startIdx + k]); });
    bool allDone = true; for (size_t k = startIdx; k < combos.size(); k++) if (!combos[k].done) allDone = false;
    if (!allDone) break;
    if (K1 >= n1 && (L < 2 || K2s[stage] >= P.maxK2 || stage == NST - 1)) { stage++; break; }
  }
  // choose best
  int bi = -1;
  std::vector<int> doneIdx; for (size_t k = 0; k < combos.size(); k++) if (combos[k].done) doneIdx.push_back(k);
  std::sort(doneIdx.begin(), doneIdx.end(), [&](int a, int b) { return combos[a].val > combos[b].val; });
  int nVer = 0;
  if (P.verify && !doneIdx.empty() && root.ply + L < TOTAL_PLIES) {
    std::mutex vm; double bestDeep = -1e18;
    auto stopFn = [&]() { return msSince(t0) > budget; };
    int nd = doneIdx.size();
    par(nd, [&](Game& g, int k) {
      Combo& c = combos[doneIdx[k]];
      { std::lock_guard<std::mutex> lk(vm); if (c.val <= bestDeep) return; }
      Undo u1, u2; bool two = (L >= 2 && c.j >= 0);
      g.apply(A[ord[c.i]], u1);
      if (two) g.apply(second[c.i][c.j], u2);
      Move r1, r2; r1.type = r2.type = 2;
      double v = deepOpp(g, S, P, P.vK1, P.vK2, stopFn, &r1, &r2);
      if (two) g.undo(u2);
      g.undo(u1);
      if (stopFn()) return;  // incomplete: discard
      std::lock_guard<std::mutex> lk(vm);
      c.deep = v; c.verified = true; c.r1 = r1; c.r2 = r2; nVer++;
      if (v > bestDeep) bestDeep = v;
    });
    std::vector<int> ver; for (int k : doneIdx) if (combos[k].verified) ver.push_back(k);
    if (!ver.empty()) {
      // verified combos ranked by deep value first, then the rest by shallow value
      std::stable_sort(ver.begin(), ver.end(), [&](int a, int b) { return combos[a].deep > combos[b].deep; });
      for (int k : ver) combos[k].val = combos[k].deep;
      std::vector<int> rest; for (int k : doneIdx) if (!combos[k].verified) rest.push_back(k);
      doneIdx = ver; doneIdx.insert(doneIdx.end(), rest.begin(), rest.end());
    }
  }
  if (doneIdx.empty()) {
    // no leaf finished: fall back to ordering
    Combo c; c.i = 0; c.j = -1; c.val = ov[ord[0]]; combos.push_back(c); doneIdx.push_back(combos.size() - 1);
  }
  bi = doneIdx[0];
  bool bookPlayed = false;
  if (haveBook) {
    for (int k : doneIdx) if (combos[k].i == 0) {
      const Combo& bc = combos[k]; const Combo& be = combos[bi];
      // Tactics override the book: never let the book concede stars the best line keeps, or skip our capture.
      bool tactical = false;
      if (P.bookYield == 1) tactical = (bc.lost > be.lost) || (be.myPts > bc.myPts);
      if (P.bookYield >= 2) tactical = (bc.lost > 0) || (bc.lost > be.lost) || (be.myPts > bc.myPts) || (be.myPts > 0);
      if (!tactical && bc.val >= be.val - P.bookMargin) { bi = k; bookPlayed = true; }
      break;
    }
    if (verbose) {
      int kb = -1; for (int k : doneIdx) if (combos[k].i == 0) { kb = k; break; }
      if (kb >= 0) fprintf(stderr, "book %s %s (book val %.1f lost %d pts %d | best val %.1f lost %d pts %d)\n", bookMove.c_str(), bookPlayed ? "played" : "overridden",
        combos[kb].val, combos[kb].lost, combos[kb].myPts, combos[doneIdx[0]].val, combos[doneIdx[0]].lost, combos[doneIdx[0]].myPts);
    }
  }
  if (!bookPlayed && rng && root.ply < P.openPlies && P.openRand > 1) {
    // pick among top distinct first actions
    std::vector<int> firsts; std::set<int> seenI;
    for (int k : doneIdx) if (seenI.insert(combos[k].i).second) { firsts.push_back(k); if ((int)firsts.size() >= P.openRand) break; }
    bi = firsts[(*rng)() % firsts.size()];
  }
  Combo& best = combos[bi];
  res.move = root.moveStr(A[ord[best.i]]); res.eval = best.val;
  std::string pv = jesc(res.move);
  if (best.j >= 0 && secondReady[best.i]) pv += "," + jesc(root.moveStr(second[best.i][best.j]));
  if (best.r1.type != 2) pv += "," + jesc(root.moveStr(best.r1));
  if (best.r2.type != 2) pv += "," + jesc(root.moveStr(best.r2));
  std::string top; std::set<int> seenI; int cnt = 0;
  for (int k : doneIdx) {
    if (!seenI.insert(combos[k].i).second) continue;
    if (cnt) top += ",";
    char buf[64]; snprintf(buf, sizeof buf, "%.2f", combos[k].val);
    top += "{\"move\":" + jesc(root.moveStr(A[ord[combos[k].i]])) + ",\"score\":" + buf + "}";
    if (++cnt >= 8) break;
  }
  char eb[64]; snprintf(eb, sizeof eb, "%.2f", res.eval);
  res.json = "{\"move\":" + jesc(res.move) + ",\"eval\":" + eb + ",\"pv\":[" + pv + "],\"top\":[" + top + "],\"nodes\":" + std::to_string(nodes.load()) + "}";
  if (verbose) fprintf(stderr, "ply %d side %d L %d moves %d leaves %zu stage %d verified %d time %.0fms eval %.2f\n",
                       root.ply, S, L, n1, doneIdx.size(), stage, nVer, msSince(t0), res.eval);
  return res;
}

struct Book; std::string bookNext(const Book& B, const Game& g, int myEdits);
inline int runSelfplay(int N, int timeMs, int threads, const Params& pa, const Params& pb, uint64_t seed,
                       const Book* ba = nullptr, const Book* bb = nullptr) {
  std::atomic<int> next{0}; std::mutex mu;
  int winsA = 0, winsB = 0, draws = 0; long long sumA = 0, sumB = 0;
  int par = std::max(1, std::min(threads, N));
  int innerThreads = std::max(1, threads / std::max(1, N));
  auto work = [&]() {
    int k;
    while ((k = next++) < N) {
      std::mt19937_64 rng(seed + k * 7919);
      Game g; g.setup();
      int aSeat = k % 2;
      std::vector<std::string> none;
      std::string moves;
      while (g.ply < TOTAL_PLIES) {
        int s = turnOf(g.ply);
        const Params& P = (s == aSeat) ? pa : pb;
        if (g.ply < P.randPlies) {
          std::vector<Move> mv; g.genPlaces(mv, s);
          if (!mv.empty()) { Undo u; Move m = mv[rng() % mv.size()]; moves += g.moveStr(m) + " "; g.apply(m, u); continue; }
        }
        const Book* bk = (s == aSeat) ? ba : bb;
        std::string bm = bk ? bookNext(*bk, g, -1) : std::string();
        SearchResult r = searchRoot(g, timeMs, innerThreads, P, none, false, &rng, bm);
        Move m;
        if (r.move.empty() || !g.parseMove(r.move, m)) { g.ply++; continue; }
        int before = g.score[s];
        Undo u; g.apply(m, u);
        moves += r.move + " ";
        if (getenv("BP_TRACE") && k == 0) fprintf(stderr, "T ply %d seat %d %s pts %d stars %d/%d score %d/%d\n", g.ply - 1, s, r.move.c_str(), g.score[s] - before, g.stars[0], g.stars[1], g.score[0], g.score[1]);
        if (getenv("BP_SAVE_PLY") && g.ply == atoi(getenv("BP_SAVE_PLY")) && k == 0) fprintf(stderr, "STATE %s\n", g.stateJson().c_str());
      }
      int sa = g.score[aSeat], sb = g.score[1 - aSeat];
      std::lock_guard<std::mutex> lk(mu);
      if (sa > sb) winsA++; else if (sb > sa) winsB++; else draws++;
      sumA += sa; sumB += sb;
      printf("game %d Aseat %d score A %d B %d stars %d/%d | %s\n", k, aSeat, sa, sb, g.stars[aSeat], g.stars[1 - aSeat], moves.c_str());
      fflush(stdout);
    }
  };
  std::vector<std::thread> th; for (int t = 0; t < par; t++) th.emplace_back(work); for (auto& t : th) t.join();
  printf("RESULT A %d B %d D %d avgA %.1f avgB %.1f\n", winsA, winsB, draws, (double)sumA / std::max(1, N), (double)sumB / std::max(1, N));
  return 0;
}
