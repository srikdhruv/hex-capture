// Blueprints game core: exact port of reference/rules.mjs on a bounded grid.
#pragma once
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <tuple>
#include <string>
#include <vector>
#include <algorithm>
#include "json.hpp"

constexpr int G = 256, OFF = 128;           // grid; internal coords in [-128,127]
constexpr int TOTAL_PLIES = 120;
constexpr int SAFE = 120;                   // stamped cells must satisfy |q|,|r| <= SAFE
enum Kind : uint8_t { EMPTY = 0, WALL = 1, STAR = 2, PLAIN = 3 };
inline int IDX(int q, int r) { return (r + OFF) * G + (q + OFF); }
inline int QOF(int i) { return i % G - OFF; }
inline int ROF(int i) { return i / G - OFF; }
constexpr int DQ[6] = {1, 1, 0, -1, -1, 0}, DR[6] = {0, -1, -1, 0, 1, 1};
constexpr int ND[6] = {1, 1 - G, -G, -1, -1 + G, G};
inline uint8_t mkcell(int seat, int kind) { return (uint8_t)(kind | (seat << 2)); }
inline int cseat(uint8_t c) { return c >> 2; }
inline int ckind(uint8_t c) { return c & 3; }
inline int turnOf(int ply) { return (ply == 0 || ((ply - 1) >> 1) % 2 == 1) ? 0 : 1; }
inline int movesLeftInTurn(int ply) { return ply == 0 ? 1 : std::min(2 - ((ply - 1) % 2), TOTAL_PLIES - ply); }
inline const char* kindName(int k) { return k == WALL ? "wall" : k == STAR ? "star" : "plain"; }

inline bool g_needCover = false;
struct BP {
  int n = 0, stars = 0, diam = 0, cover = 0;  // cover: sum over stars of in-shape neighbours
  int8_t q[24], r[24]; uint8_t k[24]; int d[24];
  void finalize() {
    stars = 0; diam = 0; cover = 0;
    for (int i = 0; i < n; i++) { d[i] = r[i] * G + q[i]; if (k[i] == STAR) stars++; }
    if (g_needCover) for (int i = 0; i < n; i++) if (k[i] == STAR) for (int dd = 0; dd < 6; dd++) if (find(q[i] + DQ[dd], r[i] + DR[dd]) >= 0) cover++;
    for (int i = 0; i < n; i++) for (int j = i + 1; j < n; j++) {
      int dq = q[i] - q[j], dr = r[i] - r[j], ds = -dq - dr;
      int h = (abs(dq) + abs(dr) + abs(ds)) / 2; if (h > diam) diam = h;
    }
  }
  int find(int qq, int rr) const { for (int i = 0; i < n; i++) if (q[i] == qq && r[i] == rr) return i; return -1; }
  void normalize() {
    if (!n) { finalize(); return; }
    int bq = q[0], br = r[0];
    for (int i = 1; i < n; i++) if (r[i] < br || (r[i] == br && q[i] < bq)) { bq = q[i]; br = r[i]; }
    for (int i = 0; i < n; i++) { q[i] -= bq; r[i] -= br; }
    finalize();
  }
  void remove(int i) { for (int j = i; j + 1 < n; j++) { q[j] = q[j + 1]; r[j] = r[j + 1]; k[j] = k[j + 1]; } n--; }
  void add(int qq, int rr, int kk) { q[n] = qq; r[n] = rr; k[n] = kk; n++; }
};
struct Hand { BP b[3]; };

struct Move {
  uint8_t type = 0;  // 0 place, 1 edit, 2 none
  uint8_t bp = 0; int16_t q = 0, r = 0;              // place: blueprint index, internal offset
  int8_t fi = 0, ti = 0, kq = 0, kr = 0, sq = 0, sr = 0;  // edit (blueprint-local coords)
  bool operator==(const Move& o) const {
    return type == o.type && (type == 0 ? (bp == o.bp && q == o.q && r == o.r)
                                        : (fi == o.fi && ti == o.ti && kq == o.kq && kr == o.kr && sq == o.sq && sr == o.sr));
  }
};

// small local bitmap for blueprint-space operations
struct LocalMap {
  static constexpr int W = 72, O = 36;
  uint8_t m[W * W];
  void clear() { memset(m, 0, sizeof m); }
  uint8_t& at(int q, int r) { return m[(r + O) * W + (q + O)]; }
};

inline bool connectedList(const int8_t* qs, const int8_t* rs, int n, LocalMap& lm) {
  if (n <= 1) return true;
  lm.clear();
  for (int i = 0; i < n; i++) lm.at(qs[i], rs[i]) = 1;
  int stq[32], str_[32], sp = 0, cnt = 1;
  lm.at(qs[0], rs[0]) = 2; stq[sp] = qs[0]; str_[sp] = rs[0]; sp++;
  while (sp) {
    sp--; int q = stq[sp], r = str_[sp];
    for (int d = 0; d < 6; d++) {
      uint8_t& c = lm.at(q + DQ[d], r + DR[d]);
      if (c == 1) { c = 2; cnt++; stq[sp] = q + DQ[d]; str_[sp] = r + DR[d]; sp++; }
    }
  }
  return cnt == n;
}

struct Undo {
  int nch = 0; int idx[200]; uint8_t old[200];
  int score[2], stars[2], ply, minq, maxq, minr, maxr;
  bool edit = false; int seat; Hand hand;
};

struct Game {
  uint8_t g[G * G];
  Hand hands[2];
  int score[2] = {0, 0}, stars[2] = {0, 0}, ply = 0;
  int minq = 0, maxq = 0, minr = 0, maxr = 0;   // bbox of occupied cells (internal)
  int shq = 0, shr = 0;                          // external = internal + shift
  // scratch
  uint32_t* seen = nullptr; uint32_t gen = 0;

  Game() { memset(g, 0, sizeof g); seen = new uint32_t[G * G](); }
  Game(const Game& o) { copyFrom(o); }
  Game& operator=(const Game& o) { if (this != &o) { delete[] seen; copyFrom(o); } return *this; }
  ~Game() { delete[] seen; }
  void copyFrom(const Game& o) {
    memcpy(g, o.g, sizeof g); memcpy(hands, o.hands, sizeof hands);
    score[0] = o.score[0]; score[1] = o.score[1]; stars[0] = o.stars[0]; stars[1] = o.stars[1]; ply = o.ply;
    minq = o.minq; maxq = o.maxq; minr = o.minr; maxr = o.maxr; shq = o.shq; shr = o.shr;
    seen = new uint32_t[G * G](); gen = 0;
  }
  uint32_t nextGen() { if (++gen == 0) { memset(seen, 0, sizeof(uint32_t) * G * G); gen = 1; } return gen; }

  void recomputeMeta() {
    stars[0] = stars[1] = 0; bool any = false;
    minq = minr = 1000; maxq = maxr = -1000;
    for (int i = 0; i < G * G; i++) if (g[i]) {
      if (ckind(g[i]) == STAR) stars[cseat(g[i])]++;
      int q = QOF(i), r = ROF(i); any = true;
      minq = std::min(minq, q); maxq = std::max(maxq, q); minr = std::min(minr, r); maxr = std::max(maxr, r);
    }
    if (!any) minq = maxq = minr = maxr = 0;
  }

  void setup() {
    memset(g, 0, sizeof g); score[0] = score[1] = 0; ply = 0; shq = shr = 0;
    const int rings[2][3][6] = {
      {{3, 3, 3, 3, 3, 3}, {WALL, STAR, WALL, STAR, WALL, STAR}, {3, 3, 3, 3, 3, 3}},
      {{3, 3, 3, 3, 3, 3}, {STAR, WALL, STAR, WALL, STAR, WALL}, {3, 3, 3, 3, 3, 3}}};
    const int sx[2][3] = {{-6, -10, -2}, {6, 10, 2}};
    for (int s = 0; s < 2; s++) for (int i = 0; i < 3; i++) {
      BP& b = hands[s].b[i]; b.n = 0; b.add(0, 0, STAR);
      for (int d = 0; d < 6; d++) b.add(DQ[d], DR[d], rings[s][i][d]);
      b.normalize();
      for (int j = 0; j < b.n; j++) g[IDX(b.q[j] + sx[s][i], b.r[j] - 1)] = mkcell(s, b.k[j]);
    }
    recomputeMeta();
  }

  // ---------------- move generation ----------------
  void genPlaces(std::vector<Move>& out, int seat) {
    static thread_local std::vector<int> front; front.clear();
    for (int r = minr - 1; r <= maxr + 1; r++) for (int q = minq - 1; q <= maxq + 1; q++) {
      int i = IDX(q, r); if (g[i]) continue;
      for (int d = 0; d < 6; d++) { uint8_t c = g[i + ND[d]]; if (c && cseat(c) == seat) { front.push_back(i); break; } }
    }
    const Hand& h = hands[seat];
    for (int b = 0; b < 3; b++) {
      const BP& bp = h.b[b]; if (!bp.n) continue;
      uint32_t gn = nextGen();
      for (int f : front) for (int j = 0; j < bp.n; j++) {
        int off = f - bp.d[j]; if (seen[off] == gn) continue; seen[off] = gn;
        int oq = QOF(off), orr = ROF(off); bool ok = true;
        for (int m = 0; m < bp.n; m++) {
          int qq = oq + bp.q[m], rr = orr + bp.r[m];
          if (qq < -SAFE || qq > SAFE || rr < -SAFE || rr > SAFE || g[off + bp.d[m]]) { ok = false; break; }
        }
        if (ok) { Move mv; mv.type = 0; mv.bp = b; mv.q = oq; mv.r = orr; out.push_back(mv); }
      }
    }
  }
  static void genEdits(const Hand& h, std::vector<Move>& out) {
    LocalMap lm, sp;
    for (int fi = 0; fi < 3; fi++) {
      const BP& bp = h.b[fi];
      for (int j = 0; j < bp.n; j++) {
        int8_t rq[24], rr[24]; int rn = 0;
        for (int x = 0; x < bp.n; x++) if (x != j) { rq[rn] = bp.q[x]; rr[rn] = bp.r[x]; rn++; }
        bool restOk = connectedList(rq, rr, rn, lm);
        for (int ti = 0; ti < 3; ti++) {
          if (fi != ti && !restOk) continue;
          const int8_t *tq, *tr; int tn;
          if (fi == ti) { tq = rq; tr = rr; tn = rn; } else { tq = h.b[ti].q; tr = h.b[ti].r; tn = h.b[ti].n; }
          // spots
          int spq[160], spr[160], sn = 0;
          sp.clear();
          for (int x = 0; x < tn; x++) sp.at(tq[x], tr[x]) = 1;
          if (tn == 0) { spq[sn] = 0; spr[sn] = 0; sn++; }
          for (int x = 0; x < tn; x++) for (int d = 0; d < 6; d++) {
            int nq = tq[x] + DQ[d], nr = tr[x] + DR[d];
            uint8_t& c = sp.at(nq, nr); if (c) continue; c = 2; spq[sn] = nq; spr[sn] = nr; sn++;
          }
          for (int s = 0; s < sn; s++) {
            if (fi == ti && spq[s] == bp.q[j] && spr[s] == bp.r[j]) continue;
            bool ok = fi != ti || restOk;
            if (!ok) { rq[rn] = spq[s]; rr[rn] = spr[s]; ok = connectedList(rq, rr, rn + 1, lm); }
            if (ok) { Move mv; mv.type = 1; mv.fi = fi; mv.ti = ti; mv.kq = bp.q[j]; mv.kr = bp.r[j]; mv.sq = spq[s]; mv.sr = spr[s]; out.push_back(mv); }
          }
        }
      }
    }
  }
  void genAll(std::vector<Move>& out) {
    out.clear(); if (ply >= TOTAL_PLIES) return;
    int seat = turnOf(ply);
    genPlaces(out, seat); genEdits(hands[seat], out);
  }

  // ---------------- make / unmake ----------------
  void apply(const Move& mv, Undo& u) {
    int seat = turnOf(ply);
    u.nch = 0; u.score[0] = score[0]; u.score[1] = score[1]; u.stars[0] = stars[0]; u.stars[1] = stars[1];
    u.ply = ply; u.minq = minq; u.maxq = maxq; u.minr = minr; u.maxr = maxr; u.edit = false; u.seat = seat;
    if (mv.type == 0) {
      const BP& bp = hands[seat].b[mv.bp]; int base = IDX(mv.q, mv.r);
      for (int j = 0; j < bp.n; j++) {
        int i = base + bp.d[j]; u.idx[u.nch] = i; u.old[u.nch++] = g[i]; g[i] = mkcell(seat, bp.k[j]);
        int qq = mv.q + bp.q[j], rr = mv.r + bp.r[j];
        if (qq < minq) minq = qq; if (qq > maxq) maxq = qq; if (rr < minr) minr = rr; if (rr > maxr) maxr = rr;
      }
      int erased = 0;
      for (int j = 0; j < bp.n; j++) {
        int i = base + bp.d[j];
        for (int d = 0; d < 6; d++) {
          int n = i + ND[d]; uint8_t c = g[n];
          if (c && cseat(c) != seat && ckind(c) != WALL) {
            u.idx[u.nch] = n; u.old[u.nch++] = c; g[n] = 0;
            if (ckind(c) == STAR) erased++;
          }
        }
      }
      score[seat] += erased * stars[seat];
      stars[seat] += bp.stars; stars[1 - seat] -= erased;
    } else if (mv.type == 1) {
      u.edit = true; u.hand = hands[seat];
      applyEditHand(hands[seat], mv);
    }
    ply++;
  }
  static void applyEditHand(Hand& h, const Move& mv) {
    BP& f = h.b[mv.fi]; int j = f.find(mv.kq, mv.kr); int kind = f.k[j];
    f.remove(j);
    h.b[mv.ti].add(mv.sq, mv.sr, kind);
    f.normalize(); if (mv.ti != mv.fi) h.b[mv.ti].normalize();
  }
  void undo(const Undo& u) {
    for (int x = u.nch - 1; x >= 0; x--) g[u.idx[x]] = u.old[x];
    if (u.edit) hands[u.seat] = u.hand;
    score[0] = u.score[0]; score[1] = u.score[1]; stars[0] = u.stars[0]; stars[1] = u.stars[1];
    ply = u.ply; minq = u.minq; maxq = u.maxq; minr = u.minr; maxr = u.maxr;
  }

  // ---------------- I/O ----------------
  std::string moveStr(const Move& m) const {
    char buf[64];
    if (m.type == 0) snprintf(buf, sizeof buf, "%d@%d,%d", m.bp + 1, m.q + shq, m.r + shr);
    else if (m.type == 1) snprintf(buf, sizeof buf, "%d:%d,%d>%d:%d,%d", m.fi + 1, m.kq, m.kr, m.ti + 1, m.sq, m.sr);
    else snprintf(buf, sizeof buf, "pass");
    return buf;
  }
  bool parseMove(const std::string& s, Move& m) const {
    int a, b, c, d, e, f;
    if (s.find('@') != std::string::npos) {
      if (sscanf(s.c_str(), "%d@%d,%d", &a, &b, &c) != 3) return false;
      m = Move(); m.type = 0; m.bp = a - 1; m.q = b - shq; m.r = c - shr; return a >= 1 && a <= 3;
    }
    if (sscanf(s.c_str(), "%d:%d,%d>%d:%d,%d", &a, &b, &c, &d, &e, &f) != 6) return false;
    m = Move(); m.type = 1; m.fi = a - 1; m.kq = b; m.kr = c; m.ti = d - 1; m.sq = e; m.sr = f; return true;
  }
  static int kindOf(const std::string& s) { return s == "wall" ? WALL : s == "star" ? STAR : PLAIN; }
  // Load from a view-like JSON object {cells, blueprints, scores, ply}. Returns false on failure.
  bool load(const JVal& v) {
    memset(g, 0, sizeof g);
    const JVal* cells = v.get("cells"); const JVal* bps = v.get("blueprints");
    const JVal* sc = v.get("scores"); const JVal* pl = v.get("ply");
    if (!cells || !bps || !pl) return false;
    ply = (int)pl->n;
    score[0] = score[1] = 0;
    if (sc && sc->t == JVal::ARR && sc->a.size() >= 2) { score[0] = (int)sc->a[0].n; score[1] = (int)sc->a[1].n; }
    // bbox for recentering
    std::vector<std::tuple<int, int, int, int>> cl;
    int mnq = 1 << 30, mxq = -(1 << 30), mnr = 1 << 30, mxr = -(1 << 30);
    for (auto& p : cells->o) {
      int q, r; if (sscanf(p.first.c_str(), "%d,%d", &q, &r) != 2) return false;
      if (p.second.t != JVal::ARR || p.second.a.size() < 2) return false;
      cl.emplace_back(q, r, (int)p.second.a[0].n, kindOf(p.second.a[1].s));
      mnq = std::min(mnq, q); mxq = std::max(mxq, q); mnr = std::min(mnr, r); mxr = std::max(mxr, r);
    }
    if (cl.empty()) { shq = shr = 0; } else { shq = (mnq + mxq) / 2; shr = (mnr + mxr) / 2; }
    for (auto& [q, r, s, k] : cl) {
      int iq = q - shq, ir = r - shr;
      if (iq < -SAFE - 2 || iq > SAFE + 2 || ir < -SAFE - 2 || ir > SAFE + 2) return false;
      g[IDX(iq, ir)] = mkcell(s, k);
    }
    if (bps->t != JVal::ARR || bps->a.size() < 2) return false;
    for (int s = 0; s < 2; s++) {
      const JVal& hs = bps->a[s];
      for (int i = 0; i < 3; i++) {
        BP& b = hands[s].b[i]; b.n = 0;
        if (i < (int)hs.a.size()) for (auto& p : hs.a[i].o) {
          int q, r; if (sscanf(p.first.c_str(), "%d,%d", &q, &r) != 2) return false;
          if (b.n >= 22) return false;
          b.add(q, r, kindOf(p.second.s));
        }
        b.finalize();
      }
    }
    recomputeMeta();
    return true;
  }
  std::string stateJson() const {
    std::string o = "{\"ply\":" + std::to_string(ply) + ",\"scores\":[" + std::to_string(score[0]) + "," + std::to_string(score[1]) + "],\"cells\":{";
    bool first = true;
    for (int r = minr; r <= maxr; r++) for (int q = minq; q <= maxq; q++) {
      uint8_t c = g[IDX(q, r)]; if (!c) continue;
      if (!first) o += ","; first = false;
      o += "\"" + std::to_string(q + shq) + "," + std::to_string(r + shr) + "\":[" + std::to_string(cseat(c)) + ",\"" + kindName(ckind(c)) + "\"]";
    }
    o += "},\"blueprints\":[";
    for (int s = 0; s < 2; s++) {
      if (s) o += ","; o += "[";
      for (int i = 0; i < 3; i++) {
        if (i) o += ","; o += "{";
        const BP& b = hands[s].b[i];
        for (int j = 0; j < b.n; j++) { if (j) o += ","; o += "\"" + std::to_string(b.q[j]) + "," + std::to_string(b.r[j]) + "\":\"" + kindName(b.k[j]) + "\""; }
        o += "}";
      }
      o += "]";
    }
    return o + "]}";
  }
};
