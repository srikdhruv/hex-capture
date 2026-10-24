"""Python port of reference/rules.mjs (Blueprints, game version 3). Used for the offline self-test and the
no-node fallback in the packaged bot. Verified against the JS reference by client/test_rules.py."""
WALL, STAR, PLAIN = "wall", "star", "plain"
DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
TOTAL_PLIES = 120


def key(q, r):
    return f"{q},{r}"


def parse(k):
    a, b = k.split(",")
    return int(a), int(b)


def neighbors(k):
    q, r = parse(k)
    return [key(q + a, r + b) for a, b in DIRS]


def _parse_move(m):
    if "@" in m:
        i, at = m.split("@")
        return {"type": "place", "blueprint": int(i) - 1, "at": parse(at)}
    frm, to = m.split(">")
    fi, fk = frm.split(":")
    ti, tk = to.split(":")
    return {"type": "edit", "from": (int(fi) - 1, fk), "to": (int(ti) - 1, tk)}


def turn_of(ply):
    return 0 if ply == 0 or ((ply - 1) >> 1) % 2 == 1 else 1


def moves_left_in_turn(ply):
    return 1 if ply == 0 else min(2 - ((ply - 1) % 2), TOTAL_PLIES - ply)


def _min_cell(keys):
    best = None
    for k in keys:
        q, r = parse(k)
        if best is None or r < best[1] or (r == best[1] and q < best[0]):
            best = (q, r)
    return best


def normalize(bp):
    if not bp:
        return bp, (0, 0)
    q0, r0 = _min_cell(bp.keys())
    if q0 == 0 and r0 == 0:
        return bp, (0, 0)
    out = {}
    for k, v in bp.items():
        q, r = parse(k)
        out[key(q - q0, r - r0)] = v
    return out, (-q0, -r0)


def _flower(ring):
    bp = {key(0, 0): STAR}
    for i, (a, b) in enumerate(DIRS):
        bp[key(a, b)] = ring[i]
    return normalize(bp)[0]


_N = [PLAIN] * 6
START_RINGS = [
    [_N, [WALL, STAR, WALL, STAR, WALL, STAR], _N],
    [_N, [STAR, WALL, STAR, WALL, STAR, WALL], _N],
]
START_X = [[-6, -10, -2], [6, 10, 2]]


def _without(bp, k):
    return {kk: v for kk, v in bp.items() if kk != k}


def apply_edit(hand, frm, to):
    fi, fk = frm
    ti, tk = to
    out = list(hand)
    kind = hand[fi][fk]
    out[fi] = _without(out[fi], fk)
    out[ti] = {**out[ti], tk: kind}
    for i in {fi, ti}:
        out[i] = normalize(out[i])[0]
    return out


def stamp(cells, seat, bp, at):
    dq, dr = at
    stamped = []
    for k, v in bp.items():
        q, r = parse(k)
        stamped.append((key(q + dq, r + dr), v))
    removed = set()
    for k, _ in stamped:
        for n in neighbors(k):
            c = cells.get(n)
            if c and c[0] != seat and c[1] != WALL:
                removed.add(n)
    return stamped, removed


def star_counts(cells):
    t = [0, 0]
    for s, kind in cells.values():
        if kind == STAR:
            t[s] += 1
    return t


def connected(keys):
    if not keys:
        return True
    ks = set(keys)
    seen, stack = {keys[0]}, [keys[0]]
    while stack:
        for n in neighbors(stack.pop()):
            if n in ks and n not in seen:
                seen.add(n)
                stack.append(n)
    return len(seen) == len(ks)


def setup():
    blueprints = [[_flower(r) for r in hand] for hand in START_RINGS]
    cells = {}
    for seat, hand in enumerate(blueprints):
        for i, bp in enumerate(hand):
            for k, v in stamp({}, seat, bp, (START_X[seat][i], -1))[0]:
                cells[k] = [seat, v]
    return {"ply": 0, "cells": cells, "blueprints": blueprints, "scores": [0, 0]}


def place_moves(cells, frontier, bp, idx):
    offs = [parse(k) for k in bp]
    seen, out = set(), []
    for f in frontier:
        fq, fr = parse(f)
        for bq, br in offs:
            dq, dr = fq - bq, fr - br
            k = key(dq, dr)
            if k in seen:
                continue
            seen.add(k)
            if all(key(q + dq, r + dr) not in cells for q, r in offs):
                out.append(f"{idx + 1}@{k}")
    return out


def edit_moves(hand):
    out = []
    for fi, bp in enumerate(hand):
        for k in list(bp.keys()):
            rest = _without(bp, k)
            rest_keys = list(rest.keys())
            rest_ok = connected(rest_keys)
            for ti, other in enumerate(hand):
                if fi != ti and not rest_ok:
                    continue
                target = rest if fi == ti else other
                spots = [] if target else [key(0, 0)]
                spot_set = set(spots)
                for t in target:
                    for n in neighbors(t):
                        if n not in target and n not in spot_set:
                            spot_set.add(n)
                            spots.append(n)
                if fi == ti and k in spot_set:
                    spots.remove(k)
                for s in spots:
                    if fi != ti or rest_ok or connected(rest_keys + [s]):
                        out.append(f"{fi + 1}:{k}>{ti + 1}:{s}")
    return out


def legal_moves(state):
    if state["ply"] >= TOTAL_PLIES:
        return []
    cells = state["cells"]
    seat = turn_of(state["ply"])
    frontier, fset = [], set()
    for k, c in cells.items():
        if c[0] == seat:
            for n in neighbors(k):
                if n not in cells and n not in fset:
                    fset.add(n)
                    frontier.append(n)
    hand = state["blueprints"][seat]
    out = []
    for i, bp in enumerate(hand):
        out += place_moves(cells, frontier, bp, i)
    return out + edit_moves(hand)


def play(state, move):
    if move == "pass":
        return {**state, "ply": state["ply"] + 1}
    seat = turn_of(state["ply"])
    m = _parse_move(move)
    if m["type"] == "place":
        stamped, removed = stamp(state["cells"], seat, state["blueprints"][seat][m["blueprint"]], m["at"])
        cells = {k: v for k, v in state["cells"].items() if k not in removed}
        for k, v in stamped:
            cells[k] = [seat, v]
        scores = list(state["scores"])
        scores[seat] += sum(1 for k in removed if state["cells"][k][1] == STAR) * star_counts(state["cells"])[seat]
        return {"ply": state["ply"] + 1, "cells": cells, "blueprints": state["blueprints"], "scores": scores}
    hand = apply_edit(state["blueprints"][seat], m["from"], m["to"])
    bps = [hand, state["blueprints"][1]] if seat == 0 else [state["blueprints"][0], hand]
    return {"ply": state["ply"] + 1, "cells": state["cells"], "blueprints": bps, "scores": state["scores"]}


def result(state):
    if state["ply"] < TOTAL_PLIES:
        return None
    a, b = state["scores"]
    if a == b:
        return {"winner": None, "reason": "tied score"}
    return {"winner": 0 if a > b else 1, "reason": "higher score"}


def to_view(state):
    return {"ply": state["ply"], "turn": turn_of(state["ply"]),
            "left": 0 if state["ply"] >= TOTAL_PLIES else moves_left_in_turn(state["ply"]),
            "cells": state["cells"], "blueprints": state["blueprints"], "scores": state["scores"],
            "stars": star_counts(state["cells"]), "moves": legal_moves(state), "result": result(state)}


def from_view(view):
    return {"ply": view["ply"], "cells": {k: [int(v[0]), v[1]] for k, v in view["cells"].items()},
            "blueprints": view["blueprints"], "scores": list(view.get("scores") or [0, 0])}


def best_capture_move(view):
    """Tiny no-dependency fallback policy: the legal placement with the most immediate points
    (ties: more own stars placed), else the first legal move."""
    try:
        state = from_view(view)
        seat = turn_of(state["ply"])
        mine = star_counts(state["cells"])[seat]
        best, best_v = None, None
        for m in view.get("moves") or []:
            if "@" not in m:
                continue
            pm = _parse_move(m)
            bp = state["blueprints"][seat][pm["blueprint"]]
            _, removed = stamp(state["cells"], seat, bp, pm["at"])
            pts = sum(1 for k in removed if state["cells"][k][1] == STAR) * mine
            v = pts * 10 + sum(1 for x in bp.values() if x == STAR) + 0.1 * len(removed)
            if best_v is None or v > best_v:
                best, best_v = m, v
        return best or (view.get("moves") or ["pass"])[0]
    except Exception:  # noqa: BLE001
        return (view.get("moves") or ["pass"])[0]
