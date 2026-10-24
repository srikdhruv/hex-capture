"""Shared helpers for the real-rules opponent bots (tools/bots/*.py). Engine CLI contract: state JSON on
stdin, one JSON line {"move": ...} on stdout."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(REPO, "client"))
import bprules as P  # noqa: E402,F401
import analyze as A  # noqa: E402,F401


def read_state():
    data = json.load(sys.stdin)
    view = data.get("view", data)
    st = P.from_view(view)
    moves = view.get("moves") or P.legal_moves(st)
    seat = P.turn_of(st["ply"])
    return data, view, st, moves, seat


def action_index(ply, seat):
    """How many actions `seat` has already played before `ply`."""
    return sum(1 for p in range(ply) if P.turn_of(p) == seat)


def book_move(book, k, moves):
    """The book's k-th action if it is an edit and legal now ('E' slot), 'stamp' for a stamp slot, None past it."""
    if k >= len(book):
        return None
    m = book[k]
    if ">" in m:
        return m if m in moves else "stamp"
    return "stamp"


def placement_info(st, seat, m):
    i, at = m.split("@")
    bp = st["blueprints"][seat][int(i) - 1]
    stamped, removed = P.stamp(st["cells"], seat, bp, P.parse(at))
    cells = st["cells"]
    caught = sum(1 for k in removed if cells[k][1] == P.STAR)
    mult = P.star_counts(cells)[seat]
    return {"move": m, "piece": int(i) - 1, "bp": bp, "stamped": stamped, "removed": removed,
            "points": caught * mult, "caught": caught,
            "stars": [k for k, v in stamped if v == P.STAR],
            "walls": sum(1 for _, v in stamped if v == P.WALL), "size": len(stamped)}


def apply(st, seat, info):
    cells = {k: v for k, v in st["cells"].items() if k not in info["removed"]}
    for k, v in info["stamped"]:
        cells[k] = [seat, v]
    return cells


def enemy_dist(cells, seat, keys):
    enemy = [P.parse(k) for k, c in cells.items() if c[0] != seat]
    best = 99
    for k in keys:
        q, r = P.parse(k)
        for eq, er in enemy:
            d = (abs(q - eq) + abs(r - er) + abs(q - eq + r - er)) // 2
            if d < best:
                best = d
    return best


def enemy_reach(cells, seat):
    """Hexes the enemy (1-seat) can ever get a stamp next to: flood from its frontier through empty hexes and our
    non-wall cells (erasable), blocked by walls, inside the occupied bounding box + 3."""
    enemy = 1 - seat
    pts = [P.parse(k) for k in cells]
    qmin, qmax = min(q for q, _ in pts) - 3, max(q for q, _ in pts) + 3
    rmin, rmax = min(r for _, r in pts) - 3, max(r for _, r in pts) + 3
    seen = set()
    stack = [k for k in A.frontier(cells, enemy)]
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        q, r = P.parse(k)
        if not (qmin <= q <= qmax and rmin <= r <= rmax):
            continue
        c = cells.get(k)
        if c is not None and (c[1] == P.WALL or c[0] == enemy):
            continue
        seen.add(k)
        stack.extend(P.neighbors(k))
    return seen


def out(move, why=""):
    print(json.dumps({"move": move, "why": why}))
