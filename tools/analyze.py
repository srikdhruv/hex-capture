#!/usr/bin/env python3
"""Fast position analysis for the live pilot (about 1s, at most ~30 lines).

  python3 tools/analyze.py client/pilot/decision.json          # finds the state in the room's game log
  python3 tools/analyze.py client/logs/game-<room>.jsonl [--ply N]
  python3 tools/analyze.py state.json | lab/positions/X.json [--seat S]

Prints:
 1. Enemy stars: holes (empty neighbours), erasable shields (enemy non-wall neighbours), walls, and the
    estimated number of our actions to reach a hole. Dijkstra from our frontier: an empty hex costs 1, an
    enemy non-wall hex costs L (it must be erased first: one stamp). L is our longest piece span, and
    actions = ceil(cost / L). "NOW" means a single legal placement captures it (exact). "sealed" means
    unreachable.
 2. The same from their side toward our stars (our danger list), with their longest piece.
 3. The minimum number of walls each side still needs to seal all its stars: an exact min vertex cut from
    outside to the stars (port of lab/sealcut.mjs).
 4. Opponent style from the move history: rusher / wall-sealer / Fortlite / stacker, with evidence.
 5. Crack target: the enemy star with the fewest actions to reach, plus a 2-placement line that captures it
    (exact search with the reference rules), if one exists.
"""
import argparse
import heapq
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "client"))
import bprules as P  # noqa: E402

NAME = {0: "Blue", 1: "Red"}
LOG_DIRS = [os.path.join(REPO, "client", "logs"), os.path.join(os.path.expanduser("~"), ".hexbot", "logs")]


# ----------------------------------------------------------------------------- input

def _states_from_log(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("type") == "state" and isinstance(r.get("state"), dict) and r["state"].get("view"):
                out.append(r["state"])
    return out


def load(path, ply=None):
    """Return a server-style state {you, turn, ply, view, history?}."""
    if path.endswith(".jsonl"):
        sts = _states_from_log(path)
        if ply is not None:
            sts = [s for s in sts if s.get("ply", s["view"].get("ply")) == ply] or sts
        if not sts:
            raise SystemExit("no states in " + path)
        return sts[-1]
    data = json.load(open(path, encoding="utf-8"))
    if "board_text" in data and "room" in data:  # pilot decision.json: find the state in the game log
        want = ply if ply is not None else data.get("ply")
        for d in LOG_DIRS:
            f = os.path.join(d, f"game-{data['room']}.jsonl")
            if os.path.isfile(f):
                sts = [s for s in _states_from_log(f) if s.get("ply", s["view"].get("ply")) == want]
                if sts:
                    st = sts[-1]
                    st.setdefault("you", [data.get("seat")])
                    return st
        raise SystemExit(f"decision.json: no logged state for room {data['room'][:12]} ply {want} in {LOG_DIRS}")
    if "state" in data and isinstance(data["state"], dict) and "view" in data["state"]:
        st = data["state"]
        if data.get("seat") is not None and not st.get("you"):
            st["you"] = [data["seat"]]
        return st
    if "view" in data:
        return data
    return {"view": data, "you": [P.turn_of(data.get("ply", 0))]}


# ----------------------------------------------------------------------------- geometry

def hexdist(a, b):
    (q1, r1), (q2, r2) = P.parse(a), P.parse(b)
    dq, dr = q1 - q2, r1 - r2
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def span(bp):
    ks = list(bp)
    return 1 + max((hexdist(a, b) for a in ks for b in ks), default=0)


def frontier(cells, seat):
    f = set()
    for k, c in cells.items():
        if c[0] == seat:
            for n in P.neighbors(k):
                if n not in cells:
                    f.add(n)
    return f


def reach(cells, attacker, L, limit):
    """Dijkstra cost (in hexes) from attacker's frontier; empty = 1, defender non-wall = L, walls/own = blocked."""
    dist = {}
    heap = [(1, k) for k in frontier(cells, attacker)]
    heapq.heapify(heap)
    while heap:
        d, k = heapq.heappop(heap)
        if k in dist or d > limit:
            continue
        dist[k] = d
        for n in P.neighbors(k):
            if n in dist:
                continue
            c = cells.get(n)
            if c is None:
                w = 1
            elif c[0] != attacker and c[1] != P.WALL:
                w = L
            else:
                continue
            heapq.heappush(heap, (d + w, n))
    return dist


def star_report(state, attacker, cap_moves=None):
    """For each defender star: holes, shields, walls, est. actions (exact 1 if capturable now)."""
    cells = state["cells"]
    defender = 1 - attacker
    hand = state["blueprints"][attacker]
    L = max((span(bp) for bp in hand if bp), default=1)
    dist = reach(cells, attacker, L, limit=L * 8)
    now = capture_now(state, attacker)
    rows = []
    for k, c in cells.items():
        if c[0] != defender or c[1] != P.STAR:
            continue
        holes, shields, walls = [], [], 0
        for n in P.neighbors(k):
            cn = cells.get(n)
            if cn is None:
                holes.append(n)
            elif cn[1] == P.WALL:
                walls += 1
            elif cn[0] == defender:
                shields.append(n)
        best = min([dist[h] for h in holes if h in dist] + [dist[s] for s in shields if s in dist], default=None)
        if k in now:
            acts = 1
        elif best is None:
            acts = None
        else:
            acts = max(2, math.ceil(best / L))  # not capturable now (exact), so at least 2
        rows.append({"star": k, "holes": holes, "shields": shields, "walls": walls, "actions": acts,
                     "now": now.get(k)})
    rows.sort(key=lambda r: (r["actions"] is None, r["actions"] or 0, -len(r["holes"])))
    return rows, L


def capture_now(state, attacker):
    """Exact: {star_key: (points, move)} capturable by one placement of attacker."""
    cells = state["cells"]
    stars = P.star_counts(cells)[attacker]
    f = sorted(frontier(cells, attacker))
    out = {}
    for i, bp in enumerate(state["blueprints"][attacker]):
        if not bp:
            continue
        for m in P.place_moves(cells, f, bp, i):
            _, removed = P.stamp(cells, attacker, bp, P.parse(m.split("@")[1]))
            hit = [k for k in removed if cells[k][1] == P.STAR]
            for k in hit:
                pts = len(hit) * stars
                if k not in out or pts > out[k][0]:
                    out[k] = (pts, m)
    return out


# ----------------------------------------------------------------------------- min wall cut (lab/sealcut.mjs)

def min_seal(cells, s, cap_at=30):
    occ = [P.parse(k) for k in cells]
    if not occ:
        return 0
    qmin, qmax = min(q for q, _ in occ) - 3, max(q for q, _ in occ) + 3
    rmin, rmax = min(r for _, r in occ) - 3, max(r for _, r in occ) + 3
    ids, nodes = {}, []
    for r in range(rmin, rmax + 1):
        for q in range(qmin, qmax + 1):
            k = P.key(q, r)
            c = cells.get(k)
            if c and c[0] == s and c[1] == P.WALL:
                continue
            ids[k] = len(nodes)
            nodes.append(k)
    N = len(nodes)
    SRC, SNK, INF = 2 * N, 2 * N + 1, 10 ** 9
    head = [-1] * (2 * N + 2)
    to, cap, nxt = [], [], []

    def add(u, v, c):
        for a, b, cc in ((u, v, c), (v, u, 0)):
            to.append(b)
            cap.append(cc)
            nxt.append(head[a])
            head[a] = len(to) - 1
    for k, i in ids.items():
        q, r = P.parse(k)
        c = cells.get(k)
        add(2 * i, 2 * i + 1, 1 if c is None else INF)
        if q in (qmin, qmax) or r in (rmin, rmax):
            add(SRC, 2 * i, INF)
        if c and c[0] == s and c[1] == P.STAR:
            add(2 * i + 1, SNK, INF)
        for n in P.neighbors(k):
            j = ids.get(n)
            if j is not None:
                add(2 * i + 1, 2 * j, INF)
    flow = 0
    while True:
        prev = [-1] * (2 * N + 2)
        prev[SRC] = -2
        qu = [SRC]
        h = 0
        while h < len(qu) and prev[SNK] == -1:
            u = qu[h]
            h += 1
            e = head[u]
            while e != -1:
                if cap[e] > 0 and prev[to[e]] == -1:
                    prev[to[e]] = e
                    qu.append(to[e])
                e = nxt[e]
        if prev[SNK] == -1:
            return flow
        v, f = SNK, INF
        while v != SRC:
            e = prev[v]
            f = min(f, cap[e])
            v = to[e ^ 1]
        v = SNK
        while v != SRC:
            e = prev[v]
            cap[e] -= f
            cap[e ^ 1] += f
            v = to[e ^ 1]
        flow += f
        if flow > cap_at:
            return math.inf  # not realistically sealable


# ----------------------------------------------------------------------------- style

def load_fortlite():
    try:
        return json.load(open(os.path.join(REPO, "engine", "books", "fortlite.json")))
    except (OSError, ValueError):
        return None


def style(history, state, opp, seal=None):
    """Classify the opponent from its moves (history: list of moves from setup)."""
    if not history:
        return ["style: no move history in this state"]
    s = P.setup()
    mine_moves, first_contact, place_dists = [], None, []
    for ply, m in enumerate(history):
        seat = P.turn_of(ply)
        if seat == opp:
            mine_moves.append((ply, m))
        if ply >= 30:
            continue  # contact/rush stats only need the opening; skip the expensive replay after it
        if seat == opp:
            if "@" in m:
                i, at = m.split("@")
                bp = s["blueprints"][seat][int(i) - 1]
                dq, dr = P.parse(at)
                cells_new = [P.key(P.parse(k)[0] + dq, P.parse(k)[1] + dr) for k in bp]
                others = [k for k, c in s["cells"].items() if c[0] != seat]
                d = min((hexdist(a, b) for a in cells_new for b in others), default=99) if others else 99
                place_dists.append((ply, d))
                if d <= 1 and first_contact is None:
                    first_contact = ply
        try:
            s = P.play(s, m)
        except Exception:  # noqa: BLE001
            break
    edits = [m for _, m in mine_moves if "@" not in m]
    early = [d for p, d in place_dists if p < 30]
    tags = []
    fl = load_fortlite()
    if fl:
        book = fl.get("edits", {}).get(str(opp), [])
        hit = sum(1 for e in book if e in edits)
        if hit >= 5:
            tags.append(f"FORTLITE ({hit}/{len(book)} book edits)")
    if first_contact is not None and first_contact < 25 and early and sum(early) / len(early) <= 2.5:
        tags.append(f"RUSHER (first contact ply {first_contact}, early stamp gap avg {sum(early) / len(early):.1f})")
    cells = state["cells"]
    theirs = [c for c in cells.values() if c[0] == opp]
    walls = sum(1 for c in theirs if c[1] == P.WALL)
    seal = min_seal(cells, opp) if seal is None else seal
    nstars = sum(1 for c in theirs if c[1] == P.STAR)
    if theirs and seal <= max(4, nstars // 10):
        tags.append(f"WALL-SEALER (only {seal} more walls seal all {nstars} stars; {walls}/{len(theirs)} cells are walls)")
    hand = state["blueprints"][opp]
    big = max(hand, key=lambda bp: sum(1 for v in bp.values() if v == P.STAR))
    bstars = sum(1 for v in big.values() if v == P.STAR)
    if bstars >= 6 or len(big) >= 12:
        tags.append(f"STACKER (piece of {len(big)} cells with {bstars} stars)")
    snipers = [f"#{i + 1}({len(bp)})" for i, bp in enumerate(hand) if 0 < len(bp) <= 3]
    lines = [f"style: {', '.join(tags) or 'no clear style'}; {len(edits)} edits in {len(mine_moves)} moves"
             + (f"; snipers {' '.join(snipers)}" if snipers else "")]
    lines.append("their first 10: " + " ".join(m for _, m in mine_moves[:10]))
    return lines


# ----------------------------------------------------------------------------- crack line

def apply_place(state, seat, move):
    i, at = move.split("@")
    bp = state["blueprints"][seat][int(i) - 1]
    stamped, removed = P.stamp(state["cells"], seat, bp, P.parse(at))
    pts = sum(1 for k in removed if state["cells"][k][1] == P.STAR) * P.star_counts(state["cells"])[seat]
    cells = {k: v for k, v in state["cells"].items() if k not in removed}
    for k, v in stamped:
        cells[k] = [seat, v]
    return {**state, "cells": cells}, pts


def crack_line(state, seat, target, L, budget_s=0.6):
    """Best 2-placement line (by total points) whose 2nd placement captures `target`."""
    t_end = time.time() + budget_s
    cells = state["cells"]
    f = sorted(frontier(cells, seat))
    best = None
    for i, bp in enumerate(state["blueprints"][seat]):
        if not bp:
            continue
        for m1 in P.place_moves(cells, f, bp, i):
            if time.time() > t_end:
                return best
            dq, dr = P.parse(m1.split("@")[1])
            near = min(hexdist(P.key(P.parse(k)[0] + dq, P.parse(k)[1] + dr), target) for k in bp)
            if near > L + 1:
                continue
            s2, p1 = apply_place(state, seat, m1)
            if target not in s2["cells"]:
                if best is None or p1 > best[2]:
                    best = (m1, None, p1)
                continue
            f2 = sorted(frontier(s2["cells"], seat))
            for j, bp2 in enumerate(s2["blueprints"][seat]):
                if not bp2:
                    continue
                for m2 in P.place_moves(s2["cells"], f2, bp2, j):
                    _, removed = P.stamp(s2["cells"], seat, bp2, P.parse(m2.split("@")[1]))
                    if target in removed:
                        _, p2 = apply_place(s2, seat, m2)
                        if best is None or p1 + p2 > best[2]:
                            best = (m1, m2, p1 + p2)
    return best


# ----------------------------------------------------------------------------- main

def fmt_star(r, show_now=True):
    a = r["actions"]
    reach_s = "sealed" if a is None else (f"NOW {r['now'][1]} (+{r['now'][0]})" if r["now"] and show_now else f"{a} act")
    holes = " ".join(r["holes"][:3]) + ("…" if len(r["holes"]) > 3 else "")
    return (f"  {r['star']:>7}  holes {len(r['holes'])}{(' [' + holes + ']') if holes else ''}  "
            f"shields {len(r['shields'])}  walls {r['walls']}  -> {reach_s}")


def analyze(st, seat=None, max_rows=6):
    t0 = time.time()
    view = st["view"]
    state = P.from_view(view)
    if seat is None:
        seat = (st.get("you") or [view.get("turn", P.turn_of(state["ply"]))])[0]
    opp = 1 - seat
    sc, stars = state["scores"], P.star_counts(state["cells"])
    out = [f"ply {state['ply']}  we are {NAME[seat]}  score {sc[seat]}-{sc[opp]}  stars {stars[seat]}-{stars[opp]}  "
           f"to move {NAME[P.turn_of(state['ply'])]} (left {P.moves_left_in_turn(state['ply']) if state['ply'] < 120 else 0})"]
    ours, Lus = star_report(state, seat)
    theirs, Lthem = star_report(state, opp)
    n_now = sum(1 for r in ours if r["actions"] == 1)
    n_sealed = sum(1 for r in ours if r["actions"] is None)
    out.append(f"ENEMY STARS ({len(ours)}; capturable now {n_now}, sealed {n_sealed}; our longest piece span {Lus}):")
    out += [fmt_star(r) for r in ours[:max_rows]]
    d_now = sum(1 for r in theirs if r["actions"] == 1)
    d_sealed = sum(1 for r in theirs if r["actions"] is None)
    longest = max((len(bp) for bp in state["blueprints"][opp]), default=0)
    out.append(f"OUR DANGER ({len(theirs)} stars; they capture now {d_now}, sealed {d_sealed}; "
               f"their longest piece {longest} cells, span {Lthem}):")
    out += [fmt_star(r) for r in theirs[:max_rows] if r["actions"] is not None and r["actions"] <= 3] or ["  none within 3 actions"]
    seal_us, seal_them = min_seal(state["cells"], seat), min_seal(state["cells"], opp)
    fmt = lambda v: "30+ (unsealable)" if v == math.inf else str(v)  # noqa: E731
    out.append(f"WALLS TO SEAL ALL STARS: us {fmt(seal_us)}, them {fmt(seal_them)}")
    out += style(st.get("history"), state, opp, seal_them)
    reachable = [r for r in ours if r["actions"] is not None]
    if reachable:
        tgt = reachable[0]
        line = crack_line(state, seat, tgt["star"], Lus, budget_s=0.35)
        txt = f"CRACK TARGET {tgt['star']} ({tgt['actions']} act)"
        if line and line[1]:
            now2 = P.turn_of(state["ply"]) == seat and P.moves_left_in_turn(state["ply"]) >= 2
            txt += (f": line {line[0]} then {line[1]} (+{line[2]} pts total, "
                    f"{'this turn' if now2 else 'over our next 2 actions'})")
        elif line:
            txt += f": no 2-placement capture found; best approach {line[0]} (+{line[2]})"
        else:
            txt += ": no 2-placement capture found"
        out.append(txt)
    else:
        out.append("CRACK TARGET: none (all enemy stars sealed)")
    out.append(f"({time.time() - t0:.2f}s)")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="decision.json, game log .jsonl, server state, or lab/positions/*.json")
    ap.add_argument("--ply", type=int)
    ap.add_argument("--seat", type=int, help="our seat (default: state's 'you')")
    ap.add_argument("--rows", type=int, default=6, help="star rows per side")
    args = ap.parse_args()
    st = load(args.path, args.ply)
    print("\n".join(analyze(st, args.seat, args.rows)))


if __name__ == "__main__":
    main()
