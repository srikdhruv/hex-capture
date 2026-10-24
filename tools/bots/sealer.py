#!/usr/bin/env python3
"""Wall-city SEALER playing policy (engine CLI contract; usable live via ENGINE_CMD) and replica opponent.

Production (default --book top16): the scout's top-16 sealer opening (empty #2's stars into #3/#1, leaving
#2 = a 3-wall bent chain 'www'), then per action: (1) the biggest capture; (2) block the enemy's best capture
threat on our stars; (3) the www stamp that most reduces the min-cut walls-to-seal; (4) once sealed, star
growth only fully inside the seal; (5) wall stamps near our stars. Never stamps exposed stars before sealing.
Under 1.5s per move; any error or illegal choice falls back to engine/bp, then the first legal move.
--book replica: the R8 Eris (Blue) / R9 aryan (Red) timing book instead (for arena replicas).

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


TOP16 = {  # scout: top-16 wall sealers (NDMath as Blue, RyanFourSJM as Red); "@" = a stamp slot
    0: ["2:1,0>3:-2,1", "2:0,1>3:-3,1", "2:1,1>2:0,1", "2:0,2>3:-1,0", "@", "2:-1,1>3:-1,2"],
    1: ["2:0,1>3:2,1", "2:0,0>3:3,1", "2:-2,1>2:-1,1", "2:-2,2>3:4,1", "2:0,1>3:5,1"],
}


def choose(view, st, moves, seat, budget_s, book="top16"):
    t_end = time.time() + budget_s
    k = L.action_index(st["ply"], seat)
    bk = (TOP16 if book == "top16" else BOOK)[seat]
    if k < len(bk) and ">" in bk[k]:
        if bk[k] in moves:
            return bk[k], f"book edit #{k}"
    places = [m for m in moves if "@" in m]
    if not places:
        return None, "no placement"
    cells = st["cells"]
    enemy = 1 - seat
    reach = L.enemy_reach(cells, seat)
    infos = [L.placement_info(st, seat, m) for m in places]

    def stars_safe(info):  # no new star touches a hex the enemy can reach
        own = {kk for kk, _ in info["stamped"]}
        return all(n not in reach for kk in info["stars"] for n in P.neighbors(kk) if n not in own)
    seal_now = A.min_seal(cells, seat)
    sealed = seal_now == 0
    # 1. biggest capture (any piece; star pieces only if their new stars are safe or we are sealed... captures win)
    caps = [i for i in infos if i["caught"]]
    if caps:
        best = max(caps, key=lambda i: (i["points"], stars_safe(i), -len(i["stars"]), i["walls"]))
        return best["move"], f"capture +{best['points']}"
    starfree = [i for i in infos if not i["stars"]]
    # 2. block the enemy's best capture threat on our stars (star-free stamps covering the threatened holes)
    threats = A.capture_now(st, enemy)
    if threats and starfree:
        worst = max(p for p, _ in threats.values())
        hot = {n for kk in threats for n in P.neighbors(kk) if n not in cells}
        cand = sorted((i for i in starfree if {kk for kk, _ in i["stamped"]} & hot),
                      key=lambda i: (-len({kk for kk, _ in i["stamped"]} & hot), -i["walls"]))[:8]
        best, best_v = None, worst
        for i in cand:
            if time.time() > t_end:
                break
            after = A.capture_now({**st, "cells": L.apply(st, seat, i)}, enemy)
            v = max((p for p, _ in after.values()), default=0)
            if v < best_v:
                best, best_v = i, v
        if best is not None:
            return best["move"], f"block threat {worst}->{best_v}"
    own_stars = [kk for kk, c in cells.items() if c[0] == seat and c[1] == P.STAR]
    holes = {n for x in own_stars for n in P.neighbors(x) if n not in cells}
    near = {n for h in holes for n in P.neighbors(h)} | holes
    # 3. seal: the star-free (www) stamp that most reduces the min-cut walls-to-seal
    if not sealed and starfree:
        def h(i):
            ks = {kk for kk, _ in i["stamped"]}
            return (len(ks & holes) * 3 + len(ks & near) + i["walls"] * 2, i["walls"])
        cand = sorted((i for i in starfree if h(i)[0] > 0), key=h, reverse=True)[:12]
        best, best_v = None, None
        for i in cand:
            if time.time() > t_end and best is not None:
                break
            v = A.min_seal(L.apply(st, seat, i), seat)
            key = (v, -h(i)[0])
            if best_v is None or key < best_v:
                best, best_v = i, key
        if best is not None and best_v[0] < seal_now:
            return best["move"], f"seal {seal_now}->{best_v[0]}"
    # 4. sealed: star growth only fully inside the seal
    if sealed:
        grow = sorted((i for i in infos if i["stars"] and stars_safe(i)), key=lambda i: -len(i["stars"]))[:6]
        for i in grow:
            if time.time() > t_end:
                break
            if A.min_seal(L.apply(st, seat, i), seat) == 0:
                return i["move"], f"grow +{len(i['stars'])} stars inside the seal"
    # 5. star-free stamp that thickens our walls near our stars, far from danger
    if starfree:
        def thick(i):
            ks = [kk for kk, _ in i["stamped"]]
            return (len(set(ks) & near), i["walls"], L.enemy_dist(cells, seat, ks))
        best = max(starfree, key=thick)
        return best["move"], "wall stamp"
    safe = [i for i in infos if stars_safe(i)]
    if safe:
        return max(safe, key=lambda i: len(i["stars"]))["move"], "safe star stamp"
    return None, "nothing safe"


def engine_fallback(state, time_ms):
    import json
    import os
    import subprocess
    exe = os.path.join(L.REPO, "engine", "bp" + (".exe" if os.name == "nt" else ""))
    p = subprocess.run([exe, "--time-ms", str(time_ms)], input=json.dumps(state), capture_output=True, text=True,
                       timeout=time_ms / 1000 + 10)
    for line in reversed(p.stdout.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line).get("move")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-ms", type=int, default=1000)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--book", default="top16", choices=["top16", "replica"],
                    help="top16: scout's top-16 sealer opening (production); replica: R8 Eris / R9 aryan timing book")
    args, _ = ap.parse_known_args()
    t0 = time.time()
    data, view, st, moves, seat = L.read_state()
    if not moves:
        return L.out("pass", "no moves")
    budget = min(1.5, max(0.2, args.time_ms / 1000 * 0.8))
    try:
        mv, why = choose(view, st, moves, seat, budget, args.book)
    except Exception as e:  # noqa: BLE001
        mv, why = None, f"error {type(e).__name__}: {e}"
    if mv not in moves:  # never crash, never return an illegal move: fall back to the engine
        try:
            left_ms = max(300, int(args.time_ms - (time.time() - t0) * 1000 - 500))
            em = engine_fallback(data, min(left_ms, 3000))
            mv, why = (em, why + " -> engine") if em in moves else (moves[0], why + " -> first legal")
        except Exception as e:  # noqa: BLE001
            mv, why = moves[0], why + f" -> engine failed ({type(e).__name__}) -> first legal"
    L.out(mv, why)


if __name__ == "__main__":
    main()
