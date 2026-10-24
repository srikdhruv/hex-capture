#!/usr/bin/env python3
"""Rusher opponent bot under the real rules (engine CLI contract), modelled on R10 wernerolaf (Blue).

  python3 tools/bots/rusher.py [--time-ms N] < state.json   ->  {"move": "...", "why": "..."}

Stamps the star-heavy #2 at us from ply 0 and captures greedily:
  1. the placement with the most immediate points (any piece);
  2. otherwise the piece with the most stars, placed as close to our cells as possible (ties: more stars);
Edit slots follow wernerolaf's first 40 actions (it moved #1/#3 stars into #2). As Red, where we have no log,
its edit slots move a star from #1/#3 into #2 next to the most #2 cells.
"""
import argparse

import botlib as L
from botlib import P

BOOK = ["2@-6,-4", "2@-9,2", "2@1,-3", "3:0,1>2:-2,3", "2@4,-4", "2@7,-4", "2@10,-4", "1:0,1>2:0,-1", "2@7,0",
        "2@5,5", "2@7,6", "2@10,-9", "2@14,-13", "2@4,1", "1@6,-1", "2@10,6", "2@13,1", "2@3,9", "2@0,10",
        "1:0,2>2:-3,4", "1@13,-1", "2@18,-6", "2@19,-10", "2@22,-15", "2@5,-8", "1@16,-7", "1@13,-5",
        "1:-1,2>2:-4,4", "1@11,-2", "1@11,-11"]


def star_to_two(st, seat, moves):
    hand = st["blueprints"][seat]
    best, best_v = None, -1
    for m in moves:
        if ">" not in m:
            continue
        fr, to = m.split(">")
        fi, fk = fr.split(":")
        ti, tk = to.split(":")
        if ti != "2" or fi == "2" or hand[int(fi) - 1].get(fk) != P.STAR:
            continue
        v = sum(1 for n in P.neighbors(tk) if n in hand[1])
        if v > best_v:
            best, best_v = m, v
    return best


def choose(view, st, moves, seat):
    k = L.action_index(st["ply"], seat)
    if k < len(BOOK) and ">" in BOOK[k]:
        if seat == 0 and BOOK[k] in moves:
            return BOOK[k], f"book edit #{k}"
        e = star_to_two(st, seat, moves)
        if e:
            return e, "star into #2"
    places = [m for m in moves if "@" in m]
    if not places:
        return moves[0], "no placement"
    infos = [L.placement_info(st, seat, m) for m in places]
    best = max(infos, key=lambda i: (i["points"], len(i["stars"])))
    if best["points"] > 0:
        return best["move"], f"capture +{best['points']}"
    cells = st["cells"]
    top = max(len(i["stars"]) for i in infos)
    pool = [i for i in infos if len(i["stars"]) == top]
    best = min(pool, key=lambda i: L.enemy_dist(cells, seat, [kk for kk, _ in i["stamped"]]))
    return best["move"], f"rush {len(best['stars'])} stars"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-ms", type=int, default=1000)
    ap.add_argument("--threads", type=int, default=1)
    ap.parse_known_args()
    data, view, st, moves, seat = L.read_state()
    if not moves:
        return L.out("pass", "no moves")
    try:
        mv, why = choose(view, st, moves, seat)
    except Exception as e:  # noqa: BLE001
        mv, why = moves[0], f"error {e}"
    L.out(mv if mv in moves else moves[0], why)


if __name__ == "__main__":
    main()
