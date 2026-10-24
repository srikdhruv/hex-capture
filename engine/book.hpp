// Opening book: explicit edit sequences or target hands per seat.
// File format (JSON), either or both:
//   {"maxPly": 40,
//    "edits":  {"0": ["1:0,1>2:2,0", ...], "1": [...]},          // played in order from the setup hand
//    "target": {"0": [{"q,r":"kind",...},{...},{...}], "1": [...]}} // greedy edits towards this hand
// The engine plays the book edit unless the search finds a move better by more than bookMargin.
#pragma once
#include "game.hpp"
#include <fstream>
#include <sstream>

struct Book {
  bool ok = false; int maxPly = 40;
  std::vector<std::string> edits[2];
  bool hasTarget[2] = {false, false}; Hand target[2];
};

inline bool loadBookStr(const std::string& text, Book& B);
inline bool loadBook(const std::string& path, Book& B) {
  std::ifstream f(path); if (!f) return false;
  std::stringstream ss; ss << f.rdbuf();
  return loadBookStr(ss.str(), B);
}
inline bool loadBookStr(const std::string& text, Book& B) {
  JVal v = JParser(text).parse();
  if (const JVal* m = v.get("maxPly")) B.maxPly = (int)m->n;
  if (const JVal* e = v.get("edits")) for (int s = 0; s < 2; s++) {
    if (const JVal* l = e->get(std::to_string(s))) for (auto& x : l->a) B.edits[s].push_back(x.s);
  }
  if (const JVal* t = v.get("target")) for (int s = 0; s < 2; s++) {
    const JVal* h = t->get(std::to_string(s)); if (!h || h->a.size() != 3) continue;
    for (int i = 0; i < 3; i++) {
      BP& b = B.target[s].b[i]; b.n = 0;
      for (auto& p : h->a[i].o) { int q, r; if (sscanf(p.first.c_str(), "%d,%d", &q, &r) == 2 && b.n < 22) b.add(q, r, Game::kindOf(p.second.s)); }
      b.normalize();
    }
    B.hasTarget[s] = true;
  }
  B.ok = true; return true;
}

inline bool bpEq(const BP& a, const BP& b) {
  if (a.n != b.n) return false;
  for (int i = 0; i < a.n; i++) { int j = b.find(a.q[i], a.r[i]); if (j < 0 || b.k[j] != a.k[i]) return false; }
  return true;
}
inline bool handEq(const Hand& a, const Hand& b) { for (int i = 0; i < 3; i++) if (!bpEq(a.b[i], b.b[i])) return false; return true; }

// Mismatch between bp and target under the best translation (cells+kinds).
inline int bpDist(const BP& a, const BP& t) {
  if (!a.n || !t.n) return a.n + t.n;
  int best = 0;
  for (int i = 0; i < a.n; i++) for (int j = 0; j < t.n; j++) {
    int dq = t.q[j] - a.q[i], dr = t.r[j] - a.r[i], ov = 0;
    for (int x = 0; x < a.n; x++) { int y = t.find(a.q[x] + dq, a.r[x] + dr); if (y >= 0 && t.k[y] == a.k[x]) ov++; }
    best = std::max(best, ov);
  }
  return a.n + t.n - 2 * best;
}
inline int handDist(const Hand& h, const Hand& t) { int d = 0; for (int i = 0; i < 3; i++) d += bpDist(h.b[i], t.b[i]); return d; }

inline bool parseEdit(const std::string& s, Move& m) {
  int a, b, c, d, e, f;
  if (sscanf(s.c_str(), "%d:%d,%d>%d:%d,%d", &a, &b, &c, &d, &e, &f) != 6) return false;
  m = Move(); m.type = 1; m.fi = a - 1; m.kq = b; m.kr = c; m.ti = d - 1; m.sq = e; m.sr = f;
  return m.fi >= 0 && m.fi < 3 && m.ti >= 0 && m.ti < 3;
}

// Next book edit for the side to move, or "" when out of book.
std::string bookNext(const Book& B, const Game& g) {
  if (!B.ok || g.ply >= B.maxPly || g.ply >= TOTAL_PLIES) return "";
  int seat = turnOf(g.ply);
  const Hand& cur = g.hands[seat];
  std::vector<Move> legal; Game::genEdits(cur, legal);
  auto isLegal = [&](const Move& m) { for (auto& x : legal) if (x == m) return true; return false; };
  if (!B.edits[seat].empty()) {
    Game s0; s0.setup(); Hand h = s0.hands[seat];
    const auto& seq = B.edits[seat];
    int match = -1;
    for (size_t k = 0; k <= seq.size(); k++) {
      if (handEq(h, cur)) match = k;
      if (k == seq.size()) break;
      Move m; if (!parseEdit(seq[k], m)) break;
      std::vector<Move> lg; Game::genEdits(h, lg);
      bool ok = false; for (auto& x : lg) if (x == m) ok = true;
      if (!ok) break;
      Game::applyEditHand(h, m);
    }
    if (match >= 0 && match < (int)seq.size()) {
      Move m; if (parseEdit(seq[match], m) && isLegal(m)) return seq[match];
    }
    if (match == (int)seq.size()) return "";
  }
  if (B.hasTarget[seat]) {
    int d0 = handDist(cur, B.target[seat]);
    if (d0 == 0) return "";
    int bestD = d0; Move best; bool found = false;
    for (auto& m : legal) {
      Hand h = cur; Game::applyEditHand(h, m);
      int d = handDist(h, B.target[seat]);
      if (d < bestD) { bestD = d; best = m; found = true; }
    }
    if (found) { Game tmp; return tmp.moveStr(best); }
  }
  return "";
}

// Built-in default book: lab Fortlite (31-1 vs no-book v5 in arena, 1s/move).
static const char* BUILTIN_BOOK = R"BOOK({"maxPly":40,"edits":{"0":["3:1,1>2:2,-1","3:1,0>2:0,1","3:0,0>2:-1,0","3:0,0>2:-3,2","3:-1,1>2:-3,3","3:0,1>2:-2,1","1:1,1>2:-1,4","1:1,0>2:0,3","1:0,0>2:-2,4"],"1":["3:1,1>2:2,1","3:1,0>2:2,0","3:0,0>2:1,2","3:0,0>2:0,-1","3:-1,1>2:1,0","3:0,1>2:-1,1","1:1,1>2:-2,4","1:1,0>2:-2,3","1:0,0>2:-1,4"]},"target":{"0":[{"1,0":"star","0,0":"plain","0,1":"plain","1,1":"plain"},{"-1,2":"star","0,2":"wall","0,1":"star","-1,1":"wall","-2,2":"star","-2,3":"wall","-1,3":"star","1,0":"plain","1,1":"plain","0,0":"plain","-3,2":"plain","-3,3":"plain","-2,1":"plain","-1,4":"plain","0,3":"plain","-2,4":"plain"},{"0,0":"star"}],"1":[{"1,0":"star","0,0":"plain","0,1":"plain","1,1":"plain"},{"0,2":"star","1,2":"star","1,1":"wall","0,1":"star","-1,2":"wall","-1,3":"star","0,3":"wall","2,2":"plain","2,1":"plain","1,3":"plain","0,0":"plain","1,0":"plain","-1,1":"plain","-2,4":"plain","-2,3":"plain","-1,4":"plain"},{"0,0":"star"}]}})BOOK";
