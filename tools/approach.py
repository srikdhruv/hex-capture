#!/usr/bin/env python3
"""Multi-turn APPROACH planner: walk toward the nearest crackable enemy star beyond the engine's horizon.

  python3 tools/approach.py <decision.json | state.json | game log --ply N | lab/positions/X.json> [--depth 4]

Beam search over OUR moves only (the opponent is ignored) for up to --depth actions (default 4 = 2 turns).
Placements are the main moves; edits that lengthen our longest piece are also tried, with a penalty.
Each node is scored on:
  D        distance-to-crack: cost from our frontier to the nearest enemy star hole (empty hex = 1; an enemy
           non-wall hex = L, i.e. it must be erased with one stamp; a shield cell next to the star = L + 1),
           where L = our longest piece span. Actions-to-reach = ceil(D / L).
  captures enemy stars actually removed by our stamps (exact, reference rules)
  exposed  our NEW stars placed where their longest piece could reach them in one stamp
  edits    penalty per edit
Score: 60*captured - 20*ceil(D/L) - D - 5*exposed - 6*edits (+ a small tie-break for our stars).
Output: the plan (first 2 moves highlighted), D and actions before and after this turn, and the projected
capture ply. Library use: plan(view, seat, depth, beam, time_s) -> dict (used by tools/pilot_daemon.py).
"""
import argparse
import heapq
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "client"))
import bprules as P  # noqa: E402
import analyze as A  # noqa: E402

W_CAPTURE, W_ACT, W_D, W_EXPOSED, W_EDIT, W_STAR = 60.0, 20.0, 1.0, 5.0, 6.0, 0.2


_SPAN = {}
DIRS = P.DIRS


def piece_span(bp):
    key = frozenset(bp)
    v = _SPAN.get(key)
    if v is None:
        pts = [P.parse(k) for k in bp]
        v = 1 + max(((abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[0] - b[0] + a[1] - b[1])) // 2
                     for a in pts for b in pts), default=0)
        _SPAN[key] = v
    return v


def longest_span(hand):
    return max((piece_span(bp) for bp in hand if bp), default=1)


def crack_field(cells, us, L, limit=None):
    """Cost-to-capture field: f["q,r"] = cost for a stamp path starting at empty hex x to reach an enemy star hole.
    Computed on integer tuples for speed; only costs up to `limit` (default 5L+2, i.e. ~5 actions) are kept."""
    limit = limit or 5 * L + 2
    them = 1 - us
    ct = {P.parse(k): v for k, v in cells.items()}
    heap = []
    for (q, r), c in ct.items():
        if c[0] != them or c[1] != P.STAR:
            continue
        for a, b in DIRS:
            n = (q + a, r + b)
            cn = ct.get(n)
            if cn is None:
                heap.append((1, n))
            elif cn[0] == them and cn[1] != P.WALL:
                heap.append((L + 1, n))  # erasable shield: erase it, then stamp into the hole it leaves
    heapq.heapify(heap)
    f = {}
    while heap:
        d, k = heapq.heappop(heap)
        if k in f or d > limit:
            continue
        f[k] = d
        q, r = k
        for a, b in DIRS:
            n = (q + a, r + b)
            if n in f:
                continue
            cn = ct.get(n)
            if cn is None:
                heapq.heappush(heap, (d + 1, n))
            elif cn[0] == them and cn[1] != P.WALL:
                heapq.heappush(heap, (d + L, n))
    return {f"{q},{r}": d for (q, r), d in f.items()}


def node_D(cells, us, f):
    best = math.inf
    for k in A.frontier(cells, us):
        v = f.get(k)
        if v is not None and v < best:
            best = v
    return best


def threat_zone(cells, them, Lthem):
    """Empty hexes their single stamp can cover (reach cost <= their span)."""
    return {k for k, d in A.reach(cells, them, Lthem, limit=Lthem).items() if k not in cells}


def our_ply_sequence(ply, us, n):
    out, p = [], ply
    while len(out) < n and p < P.TOTAL_PLIES:
        if P.turn_of(p) == us:
            out.append(p)
        p += 1
    return out


def score(node, L):
    D = node["D"]
    acts = math.ceil(D / L) if D != math.inf else 99
    return (W_CAPTURE * node["captured"] - W_ACT * acts - W_D * (D if D != math.inf else 99)
            - W_EXPOSED * node["exposed"] - W_EDIT * node["edits"] + W_STAR * node["stars_added"])


def expand(node, us, them, zone, deadline, allow_edits):
    st = node["state"]
    cells = st["cells"]
    hand = st["blueprints"][us]
    L = longest_span(hand)
    f = crack_field(cells, us, L)
    front = sorted(A.frontier(cells, us))
    enemy_stars = {k for k, c in cells.items() if c[0] == them and c[1] == P.STAR}
    mult = P.star_counts(cells)[us]
    kids, seen = [], set()
    for i, bp in enumerate(hand):
        if not bp:
            continue
        for m in P.place_moves(cells, front, bp, i):
            if time.time() > deadline:
                return kids
            at = P.parse(m.split("@")[1])
            stamped, removed = P.stamp(cells, us, bp, at)
            sig = frozenset(k for k, _ in stamped)
            if sig in seen:
                continue
            seen.add(sig)
            cap = sum(1 for k in removed if k in enemy_stars)
            dmin = node["D"]
            for k, _ in stamped:
                for n in P.neighbors(k):
                    v = f.get(n)
                    if v is not None and n not in sig and v < dmin:
                        dmin = v
                if k in f and f[k] <= 1:  # stamped straight into a hole
                    dmin = min(dmin, 0)
            for r in removed:  # erased enemy cells become empty: crossing costs 1, not L; an erased shield is a hole
                v = f.get(r)
                if v is not None and r not in enemy_stars:
                    shield = any(n in enemy_stars for n in P.neighbors(r))
                    dmin = min(dmin, v - L if shield else v - L + 1)
            new_stars = [k for k, v in stamped if v == P.STAR]
            exposed = sum(1 for k in new_stars if any(n in zone for n in P.neighbors(k)))
            kids.append({"moves": node["moves"] + [m], "parent": node, "pending": (i, at, removed),
                         "D": dmin, "captured": node["captured"] + cap, "points": node["points"] + cap * mult,
                         "exposed": node["exposed"] + exposed, "edits": node["edits"],
                         "stars_added": node["stars_added"] + len(new_stars), "L": L})
    if allow_edits:
        for m in P.edit_moves(hand):
            if time.time() > deadline:
                break
            fr, to = m.split(">")
            fi, fk = fr.split(":")
            ti, tk = to.split(":")
            new_hand = P.apply_edit(hand, (int(fi) - 1, fk), (int(ti) - 1, tk))
            L2 = longest_span(new_hand)
            if L2 <= L:
                continue
            kids.append({"moves": node["moves"] + [m], "parent": node, "pending": ("edit", new_hand),
                         "D": node["D"], "captured": node["captured"], "points": node["points"],
                         "exposed": node["exposed"], "edits": node["edits"] + 1,
                         "stars_added": node["stars_added"], "L": L2})
    return kids


def materialize(kid, us):
    """Build the child's rules state lazily (only for nodes kept in the beam)."""
    st = kid["parent"]["state"]
    pend = kid["pending"]
    if pend[0] == "edit":
        bps = list(st["blueprints"])
        bps[us] = pend[1]
        kid["state"] = {**st, "blueprints": bps}
    else:
        i, at, removed = pend
        bp = st["blueprints"][us][i]
        stamped, _ = P.stamp(st["cells"], us, bp, at)
        cells = {k: v for k, v in st["cells"].items() if k not in removed}
        for k, v in stamped:
            cells[k] = [us, v]
        kid["state"] = {**st, "cells": cells}
    hand = kid["state"]["blueprints"][us]
    L = longest_span(hand)
    kid["L"] = L
    # exact D for kept nodes (captures/erasures change the field)
    kid["D"] = node_D(kid["state"]["cells"], us, crack_field(kid["state"]["cells"], us, L))
    return kid


def plan(view, seat, depth=4, beam=6, time_s=1.2, allow_edits=True):
    t0 = time.time()
    deadline = t0 + time_s
    st = P.from_view(view)
    us, them = seat, 1 - seat
    L0 = longest_span(st["blueprints"][us])
    D0 = node_D(st["cells"], us, crack_field(st["cells"], us, L0))
    Lthem = longest_span(st["blueprints"][them])
    zone = threat_zone(st["cells"], them, Lthem)
    root = {"moves": [], "state": st, "D": D0, "captured": 0, "points": 0, "exposed": 0, "edits": 0,
            "stars_added": 0, "L": L0}
    frontier_nodes, best = [root], root
    plies = our_ply_sequence(st["ply"], us, depth)
    depth = min(depth, len(plies))
    for level in range(depth):
        kids = []
        for node in frontier_nodes:
            kids += expand(node, us, them, zone, deadline, allow_edits and level == 0)
            if time.time() > deadline:
                break
        if not kids:
            break
        kids.sort(key=lambda k: score(k, k["L"]), reverse=True)
        frontier_nodes = [materialize(k, us) for k in kids[:beam]]
        frontier_nodes.sort(key=lambda k: score(k, k["L"]), reverse=True)
        if score(frontier_nodes[0], frontier_nodes[0]["L"]) > score(best, best["L"]) or best is root:
            best = frontier_nodes[0]
        if time.time() > deadline:
            break
    # Capture ply: first action in the plan that captured a star
    cap_ply = None
    node, chain = best, []
    while node is not None and node.get("parent") is not None:
        chain.append(node)
        node = node["parent"]
    chain.reverse()
    for idx, n in enumerate(chain):
        prev = n["parent"]["captured"]
        if n["captured"] > prev:
            cap_ply = plies[idx] if idx < len(plies) else None
            break
    acts_left = math.ceil(best["D"] / best["L"]) if best["D"] != math.inf else None
    if cap_ply is None and acts_left is not None:
        more = our_ply_sequence(st["ply"], us, len(best["moves"]) + acts_left + 1)
        cap_ply = more[-1] if more else None
        cap_note = "projected"
    else:
        cap_note = "in plan" if cap_ply is not None else "none"
    left = P.moves_left_in_turn(st["ply"]) if P.turn_of(st["ply"]) == us else 0
    this_turn = best["moves"][:max(1, left)] if left else []
    D_after_turn = chain[len(this_turn) - 1]["D"] if this_turn and len(chain) >= len(this_turn) else D0
    return {"moves": best["moves"], "this_turn": this_turn, "D0": D0, "acts0": math.ceil(D0 / L0) if D0 != math.inf else None,
            "D_after_turn": D_after_turn, "D_end": best["D"], "acts_end": acts_left, "captured": best["captured"],
            "points": best["points"], "exposed": best["exposed"], "edits": best["edits"], "capture_ply": cap_ply,
            "capture_note": cap_note, "plies": plies[:len(best["moves"])], "L0": L0, "Lthem": Lthem,
            "ms": int((time.time() - t0) * 1000)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--ply", type=int)
    ap.add_argument("--seat", type=int)
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--beam", type=int, default=6)
    ap.add_argument("--time", type=float, default=1.2, help="time budget in seconds")
    ap.add_argument("--no-edits", action="store_true")
    args = ap.parse_args()
    st = A.load(args.path, args.ply)
    view = st["view"]
    seat = args.seat if args.seat is not None else (st.get("you") or [view.get("turn", 0)])[0]
    r = plan(view, seat, args.depth, args.beam, args.time, not args.no_edits)
    fmt = lambda d: "inf" if d == math.inf else d  # noqa: E731
    print(f"ply {view['ply']} we are {A.NAME[seat]}; distance-to-crack D={fmt(r['D0'])} (~{r['acts0']} act, span {r['L0']}); "
          f"their span {r['Lthem']}")
    print("plan: " + "  ".join(f"[{p}] {m}" for p, m in zip(r["plies"], r["moves"])))
    print(f"this turn: {' '.join(r['this_turn']) or '(not our turn)'}  -> D {fmt(r['D_after_turn'])}; "
          f"end of plan D {fmt(r['D_end'])} (~{r['acts_end']} act), captured {r['captured']} (+{r['points']}), "
          f"exposed new stars {r['exposed']}, edits {r['edits']}")
    print(f"capture ply: {r['capture_ply']} ({r['capture_note']})   [{r['ms']} ms]")


if __name__ == "__main__":
    main()
