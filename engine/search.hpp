// Turn-based selective search for Blueprints.
#pragma once
#include <bits/stdc++.h>
#include "game.hpp"

struct Params {
  double alpha = 0.10;    // value of a star per remaining ply (star diff * alpha * R)
  double beta = 0.5;      // weight of my 1-action capture threat at the leaf (I move next)
  double ordMy = 0.8;     // ordering: weight of my follow-up capture (mid-turn)
  double ordOpp = 1.0;    // ordering: weight of opponent 1-action capture
  double expo = 0.0;      // static: penalty per exposed own star * opp stars
  int maxK1 = 96, maxK2 = 32;
  int openRand = 0;       // selfplay: randomize among top-N for first plies
  int openPlies = 0;
  void set(const std::string& kv) {
    auto p = kv.find('='); if (p == std::string::npos) return;
    std::string k = kv.substr(0, p); double v = atof(kv.c_str() + p + 1);
    if (k == "alpha") alpha = v; else if (k == "beta") beta = v; else if (k == "ordMy") ordMy = v;
    else if (k == "ordOpp") ordOpp = v; else if (k == "expo") expo = v;
    else if (k == "maxK1") maxK1 = (int)v; else if (k == "maxK2") maxK2 = (int)v;
    else if (k == "openRand") openRand = (int)v; else if (k == "openPlies") openPlies = (int)v;
    else fprintf(stderr, "unknown param %s\n", k.c_str());
  }
};

using Clock = std::chrono::steady_clock;
inline double msSince(Clock::time_point t) { return std::chrono::duration<double, std::milli>(Clock::now() - t).count(); }

// ---------- evaluation helpers ----------
inline double staticEval(const Game& g, int S, const Params& P) {
  int R = TOTAL_PLIES - g.ply;
  return (g.score[S] - g.score[1 - S]) + P.alpha * R * (g.stars[S] - g.stars[1 - S]);
}

// Candidate placements for X near Y's stars (mode 0) or near Y stars / Y plains touching Y stars (mode 1).
inline void attackCands(Game& g, int X, int mode, std::vector<Move>& out) {
  out.clear();
  int Y = 1 - X;
  static thread_local std::vector<int> att; att.clear();
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
  if (att.empty()) return;
  const Hand& h = g.hands[X];
  for (int b = 0; b < 3; b++) {
    const BP& bp = h.b[b]; if (!bp.n) continue;
    uint32_t gn = g.nextGen();
    for (int e : att) for (int j = 0; j < bp.n; j++) {
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

// Best immediate capture (points) for X with one placement.
inline int bestCap1(Game& g, int X, Move* best = nullptr) {
  static thread_local std::vector<Move> c; attackCands(g, X, 0, c);
  int bestN = 0;
  for (auto& m : c) { int n = starsErased(g, X, m); if (n > bestN) { bestN = n; if (best) *best = m; } }
  return bestN * g.stars[X];
}

struct Reply { double val; Move m1, m2; };

// Opponent O replies with L actions (capture-oriented). Returns best static(O) and moves.
inline Reply replySearch(Game& g, int O, int L, const Params& P) {
  Reply rep; rep.val = staticEval(g, O, P); rep.m1.type = 2; rep.m2.type = 2;
  if (L <= 0 || g.ply >= TOTAL_PLIES) return rep;
  // pure one-action capture from the current position
  std::vector<Move> c1; attackCands(g, O, 1, c1);
  for (auto& m : c1) {
    Undo u; g.apply(m, u);
    double v = staticEval(g, O, P); Move m2; m2.type = 2;
    if (L >= 2 && g.ply < TOTAL_PLIES) {
      Move bm; int pts = bestCap1(g, O, &bm);
      if (pts > 0) { Undo u2; g.apply(bm, u2); v = staticEval(g, O, P); g.undo(u2); m2 = bm; }
    }
    g.undo(u);
    if (v > rep.val) { rep.val = v; rep.m1 = m; rep.m2 = m2; }
  }
  return rep;
}

struct SearchResult { std::string move, json; double eval = 0; };

struct Combo { int i, j; double val = -1e18; bool done = false; Move r1, r2; };

inline SearchResult searchRoot(Game& root, int timeMs, int threads, const Params& P,
                               const std::vector<std::string>& allowed, bool verbose, std::mt19937_64* rng = nullptr) {
  auto t0 = Clock::now();
  double budget = std::max(50.0, timeMs * 0.92 - 30);
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
  // Ordering of first actions
  int n1 = A.size(); std::vector<double> ov(n1, -1e18);
  par(n1, [&](Game& g, int k) {
    Undo u; g.apply(A[k], u);
    double v = staticEval(g, S, P);
    if (L >= 2) v += P.ordMy * bestCap1(g, S); else v -= P.ordOpp * bestCap1(g, O);
    g.undo(u); ov[k] = v; nodes++;
  });
  std::vector<int> ord(n1); std::iota(ord.begin(), ord.end(), 0);
  std::stable_sort(ord.begin(), ord.end(), [&](int a, int b) { return ov[a] > ov[b]; });
  // Second-action lists (lazy)
  std::vector<std::vector<Move>> second(n1);
  std::vector<char> secondReady(n1, 0);
  auto buildSecond = [&](Game& g, int i) {
    Undo u; g.apply(A[ord[i]], u);
    std::vector<Move> B; g.genAll(B);
    std::vector<std::pair<double, int>> sc(B.size());
    for (size_t k = 0; k < B.size(); k++) {
      Undo u2; g.apply(B[k], u2);
      double v = staticEval(g, S, P) - P.ordOpp * bestCap1(g, O);
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
    if (g.ply >= TOTAL_PLIES) v = staticEval(g, S, P);
    else {
      int LO = movesLeftInTurn(g.ply);
      Reply rp = replySearch(g, O, LO, P);
      c.r1 = rp.m1; c.r2 = rp.m2;
      Undo a, b;
      if (rp.m1.type != 2) g.apply(rp.m1, a);
      if (rp.m2.type != 2) g.apply(rp.m2, b);
      v = staticEval(g, S, P);
      if (g.ply < TOTAL_PLIES) v += P.beta * bestCap1(g, S);
      if (rp.m2.type != 2) g.undo(b);
      if (rp.m1.type != 2) g.undo(a);
    }
    if (two) g.undo(u2);
    g.undo(u1);
    c.val = v; c.done = true; nodes++;
  };
  std::vector<Combo> combos;
  std::set<std::pair<int, int>> have;
  const int K1s[] = {4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256};
  const int K2s[] = {4, 6, 8, 10, 12, 16, 20, 24, 32, 32, 32, 32};
  int stage = 0;
  for (; stage < 12; stage++) {
    if (msSince(t0) > budget * 0.5 && stage > 0) break;
    int K1 = std::min({K1s[stage], n1, L >= 2 ? P.maxK1 : 100000});
    if (L < 2) K1 = std::min(n1, K1s[stage] * 4);
    std::vector<int> needSecond;
    if (L >= 2) for (int i = 0; i < K1; i++) if (!secondReady[i]) needSecond.push_back(i);
    if (!needSecond.empty()) par(needSecond.size(), [&](Game& g, int k) { buildSecond(g, needSecond[k]); });
    size_t startIdx = combos.size();
    for (int i = 0; i < K1; i++) {
      if (L >= 2) {
        if (!secondReady[i]) continue;
        int K2 = std::min<int>(K2s[stage], second[i].size());
        if (second[i].empty() && !have.count({i, -1})) { have.insert({i, -1}); combos.push_back({i, -1}); }
        for (int j = 0; j < K2; j++) if (!have.count({i, j})) { have.insert({i, j}); combos.push_back({i, j}); }
      } else if (!have.count({i, -1})) { have.insert({i, -1}); combos.push_back({i, -1}); }
    }
    int nn = combos.size() - startIdx;
    par(nn, [&](Game& g, int k) { leafEval(g, combos[startIdx + k]); });
    bool allDone = true; for (size_t k = startIdx; k < combos.size(); k++) if (!combos[k].done) allDone = false;
    if (!allDone) break;
    if (K1 >= n1 && (L < 2 || K1s[stage] >= P.maxK1)) { stage++; break; }
  }
  // choose best
  int bi = -1;
  std::vector<int> doneIdx; for (size_t k = 0; k < combos.size(); k++) if (combos[k].done) doneIdx.push_back(k);
  std::sort(doneIdx.begin(), doneIdx.end(), [&](int a, int b) { return combos[a].val > combos[b].val; });
  if (doneIdx.empty()) {
    // no leaf finished: fall back to ordering
    Combo c; c.i = 0; c.j = -1; c.val = ov[ord[0]]; combos.push_back(c); doneIdx.push_back(combos.size() - 1);
  }
  bi = doneIdx[0];
  if (rng && root.ply < P.openPlies && P.openRand > 1) {
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
  if (verbose) fprintf(stderr, "ply %d side %d L %d moves %d leaves %zu stage %d time %.0fms eval %.2f\n",
                       root.ply, S, L, n1, doneIdx.size(), stage, msSince(t0), res.eval);
  return res;
}

inline int runSelfplay(int N, int timeMs, int threads, const Params& pa, const Params& pb, uint64_t seed) {
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
        SearchResult r = searchRoot(g, timeMs, innerThreads, P, none, false, &rng);
        Move m;
        if (r.move.empty() || !g.parseMove(r.move, m)) { g.ply++; continue; }
        Undo u; g.apply(m, u);
        moves += r.move + " ";
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
