// Blueprints engine CLI.
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
#include "search.hpp"
#include "book.hpp"
using namespace std;

static string readAll(istream& in) { stringstream ss; ss << in.rdbuf(); return ss.str(); }

// --dump: JSONL in: {"state":{...},"apply":[moves]} ; out: {"moves":[sorted],"results":[state...]}
static int runDump() {
  string line; Game gm; vector<Move> mv;
  while (getline(cin, line)) {
    if (line.empty()) continue;
    JVal v = JParser(line).parse();
    const JVal* st = v.get("state");
    if (!st || !gm.load(*st)) { printf("{\"error\":\"load\"}\n"); fflush(stdout); continue; }
    gm.genAll(mv);
    vector<string> ms; for (auto& m : mv) ms.push_back(gm.moveStr(m));
    sort(ms.begin(), ms.end());
    string o = "{\"moves\":[";
    for (size_t i = 0; i < ms.size(); i++) { if (i) o += ","; o += jesc(ms[i]); }
    o += "],\"results\":[";
    const JVal* ap = v.get("apply");
    if (ap) for (size_t i = 0; i < ap->a.size(); i++) {
      Move m; if (i) o += ",";
      if (!gm.parseMove(ap->a[i].s, m)) { o += "null"; continue; }
      Undo u; gm.apply(m, u); o += gm.stateJson(); gm.undo(u);
    }
    o += "]}";
    puts(o.c_str()); fflush(stdout);
  }
  return 0;
}

static void printFallback(const string& mv) {
  printf("{\"move\":%s,\"eval\":0,\"pv\":[%s],\"top\":[],\"nodes\":0}\n", jesc(mv).c_str(), jesc(mv).c_str());
  fflush(stdout);
}

int main(int argc, char** argv) {
  int timeMs = 8000, threads = 0, selfplay = -1; bool dump = false, perft = false;
  Params pa, pb; uint64_t seed = 12345; std::string bookPath, bookA, bookB;
  for (int i = 1; i < argc; i++) {
    string a = argv[i];
    auto nxt = [&]() -> string { return i + 1 < argc ? string(argv[++i]) : string(); };
    if (a == "--time-ms") timeMs = atoi(nxt().c_str());
    else if (a == "--threads") threads = atoi(nxt().c_str());
    else if (a == "--selfplay") selfplay = atoi(nxt().c_str());
    else if (a == "--dump") dump = true;
    else if (a == "--perft") perft = true;
    else if (a == "--seed") seed = strtoull(nxt().c_str(), nullptr, 10);
    else if (a == "--book") bookPath = nxt();
    else if (a == "--nobook") bookPath = "none";
    else if (a == "--booka") bookA = nxt();
    else if (a == "--bookb") bookB = nxt();
    else if (a == "--a") pa.set(nxt());
    else if (a == "--b") pb.set(nxt());
    else if (a == "--p") { string s = nxt(); pa.set(s); pb.set(s); }
  }
  if (threads <= 0) threads = max(1u, min(16u, thread::hardware_concurrency()));
  if (dump) return runDump();
  Book book, ba, bb;
  if (bookPath.empty()) { try { loadBookStr(BUILTIN_BOOK, book); } catch (...) {} }
  else if (bookPath != "none" && !loadBook(bookPath, book)) fprintf(stderr, "book load failed: %s\n", bookPath.c_str());
  if (bookA.empty()) ba = book; else if (bookA != "none") loadBook(bookA, ba);
  if (bookB.empty()) bb = book; else if (bookB != "none") loadBook(bookB, bb);
  if (getenv("BP_BOOKTEST")) {
    for (int seat = 0; seat < 2; seat++) {
      Game g; g.setup(); g.ply = seat == 0 ? 0 : 1;
      for (int k = 0; k < 30; k++) {
        string m = bookNext(book, g);
        int d = book.hasTarget[seat] ? handDist(g.hands[seat], book.target[seat]) : -1;
        printf("seat %d step %d dist %d move %s\n", seat, k, d, m.c_str());
        if (m.empty()) break;
        Move mv; if (!parseEdit(m, mv)) break; Game::applyEditHand(g.hands[seat], mv);
      }
    }
    return 0;
  }
  if (selfplay >= 0) return runSelfplay(selfplay, timeMs, threads, pa, pb, seed, &ba, &bb);

  string fallback;
  try {
    string in = readAll(cin);
    JVal root = JParser(in).parse();
    const JVal* view = root.get("view");
    if (!view) view = &root;
    vector<string> allowed;
    if (const JVal* mv = view->get("moves")) for (auto& x : mv->a) if (x.t == JVal::STR) allowed.push_back(x.s);
    if (!allowed.empty()) fallback = allowed[0];
    Game gm;
    if (!gm.load(*view)) throw runtime_error("load failed");
    if (perft) {
      vector<Move> mv; gm.genAll(mv);
      printf("{\"count\":%zu,\"moves\":[", mv.size());
      for (size_t i = 0; i < mv.size(); i++) printf("%s%s", i ? "," : "", jesc(gm.moveStr(mv[i])).c_str());
      printf("]}\n");
      return 0;
    }
    std::string bm;
    try { bm = bookNext(book, gm); } catch (...) { bm.clear(); }
    SearchResult res = searchRoot(gm, timeMs, threads, pa, allowed, true, nullptr, bm);
    if (res.move.empty()) { if (fallback.empty()) fallback = "pass"; printFallback(fallback); return 0; }
    puts(res.json.c_str()); fflush(stdout);
  } catch (exception& e) {
    fprintf(stderr, "error: %s\n", e.what());
    if (fallback.empty()) fallback = "pass";
    printFallback(fallback);
  }
  return 0;
}
