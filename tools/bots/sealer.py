#!/usr/bin/env python3
"""Wall-city "sealer" opponent bot under the real rules (engine CLI contract), modelled on R8 Eris (Blue) and
R9 aryan (Red).

  python3 tools/bots/sealer.py [--time-ms N] < state.json   ->  {"move": "...", "why": "..."}

Opening: the logged opponent's first 60 actions as a timing book. At its edit slots we play its edits verbatim
(Eris for Blue, aryan for Red: wall pieces 'www'/'ww', a plain line, stars parked in a piece we never stamp).
At stamp slots, and after the book, a deliberate seal plan picks each stamp:
  1. capture with a star-free piece (immune sniper), or with a star piece whose new stars are unreachable;
  2. while our stars are not sealed, the star-free stamp that most reduces the min-cut walls-to-seal
     (tools/analyze.py min_seal, a port of lab/sealcut.mjs);
  3. once sealed, late star growth: stamps whose new stars are unreachable by the enemy and keep the seal;
  4. otherwise a star-free stamp that thickens our walls, far from danger.
It never stamps exposed stars before the seal.
"""
import argparse
import time

import botlib as L
from botlib import A, P

BOOK = {
    0: ["1:0,1>3:-2,1", "1:1,0>1:2,1", "1:0,0>1:3,1", "1@-2,2", "1@3,2", "2:0,0>1:5,0", "1@0,-2", "1:1,1>1:1,0",
        "1:0,1>1:-1,0", "1@2,1", "1@6,-2", "1@12,-1", "1@8,2", "1@4,-1", "1@10,0", "1@11,1", "1@2,0",
        "2:-2,1>3:-3,1", "2:0,0>3:-4,1", "2:0,0>3:-5,1", "2:0,0>3:-6,1", "2:1,0>3:-7,1", "2@8,2", "2@8,3",
        "2@9,3", "2@9,4", "2@9,5", "1:6,0>2:1,-1", "2@-9,1", "2@-5,1", "2@-3,-1", "3:-7,1>3:2,1", "2@-11,2",
        "2@-11,-1", "2@-12,1", "2:-1,1>2:-1,0", "2@-9,-2", "2@-8,-1", "3:-6,1>2:2,0"],
    1: ["2:1,0>2:-1,0", "2:0,2>1:2,1", "2:1,0>1:3,1", "2@8,1", "2:2,1>1:4,1", "2:1,2>2:-1,2", "2@10,-3", "2@8,3",
        "2:1,1>1:5,1", "2@12,-5", "2@13,-2", "2@8,5", "2@5,2", "2@3,5", "2@12,1", "2@11,4", "2@9,5", "2@15,-5",
        "2@1,1", "2@1,-1", "2:0,0>3:-2,1"],
}


def choose(view, st, moves, seat, budget_s):
    t_end = time.time() + budget_s
    k = L.action_index(st["ply"], seat)
    b = L.book_move(BOOK[seat], k, moves)
    if b and b != "stamp":
        return b, f"book edit #{k}"
    places = [m for m in moves if "@" in m]
    if not places:
        return moves[0], "no placement"
    cells = st["cells"]
    enemy = 1 - seat
    reach = L.enemy_reach(cells, seat)  # every hex the enemy can ever reach
    infos = [L.placement_info(st, seat, m) for m in places]

    def stars_safe(info):  # no new star touches a hex the enemy can reach
        return all(n not in reach for k in info["stars"] for n in P.neighbors(k)
                   if n not in {kk for kk, _ in info["stamped"]})
    # 1. captures (immune pieces first)
    caps = [i for i in infos if i["caught"] and (not i["stars"] or stars_safe(i))]
    if caps:
        best = max(caps, key=lambda i: (i["points"], -len(i["stars"]), i["walls"]))
        return best["move"], f"capture +{best['points']}"
    seal_now = A.min_seal(cells, seat)
    own_stars = [kk for kk, c in cells.items() if c[0] == seat and c[1] == P.STAR]
    holes = {n for s in own_stars for n in P.neighbors(s) if n not in cells}
    near = {n for h in holes for n in P.neighbors(h)} | holes
    starfree = [i for i in infos if not i["stars"]]
    if seal_now and seal_now != float("inf") or (seal_now == float("inf") and starfree):
        # 2. seal: star-free stamps near our stars' holes, exact min-cut for the most promising ones
        def h(i):
            ks = {kk for kk, _ in i["stamped"]}
            return (len(ks & holes) * 3 + len(ks & near) + i["walls"] * 2, i["walls"])
        cand = sorted((i for i in starfree if h(i)[0] > 0), key=h, reverse=True)[:14]
        best, best_v = None, None
        for i in cand:
            if time.time() > t_end and best is not None:
                break
            v = A.min_seal(L.apply(st, seat, i), seat)
            key = (v, -h(i)[0])
            if best_v is None or key < best_v:
                best, best_v = i, key
        if best is not None and (best_v[0] < seal_now or seal_now == float("inf")):
            return best["move"], f"seal {seal_now}->{best_v[0]}"
    if seal_now == 0:
        # 3. late star growth inside the seal
        grow = sorted((i for i in infos if i["stars"] and stars_safe(i)), key=lambda i: -len(i["stars"]))[:6]
        for i in grow:
            if A.min_seal(L.apply(st, seat, i), seat) == 0:
                return i["move"], f"grow +{len(i['stars'])} stars inside the seal"
    # 4. star-free thickening, as far from danger as possible
    if starfree:
        def thick(i):
            ks = [kk for kk, _ in i["stamped"]]
            own_adj = sum(1 for kk in ks for n in P.neighbors(kk) if cells.get(n, [None])[0] == seat)
            return (i["walls"], own_adj, L.enemy_dist(cells, seat, ks))
        best = max(starfree, key=thick)
        return best["move"], "thicken"
    safe = [i for i in infos if stars_safe(i)]
    if safe:
        return safe[0]["move"], "safe stamp"
    edits = [m for m in moves if ">" in m]
    return (edits[0] if edits else places[0]), "fallback"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-ms", type=int, default=1000)
    ap.add_argument("--threads", type=int, default=1)
    args, _ = ap.parse_known_args()
    data, view, st, moves, seat = L.read_state()
    if not moves:
        return L.out("pass", "no moves")
    try:
        mv, why = choose(view, st, moves, seat, max(0.2, args.time_ms / 1000 * 0.8))
    except Exception as e:  # noqa: BLE001
        mv, why = moves[0], f"error {e}"
    L.out(mv if mv in moves else moves[0], why)


if __name__ == "__main__":
    main()
