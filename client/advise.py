"""Advice rendering for `hexbot --advise` (human plays manually; nothing is ever posted)."""
import bprules as P
import hexrender as H


def threats(view, attacker):
    """Placements of `attacker` that remove the other side's stars: {star_key: (best_points, [moves])}."""
    st = P.from_view(view)
    cells = st["cells"]
    stars = P.star_counts(cells)[attacker]
    frontier, fset = [], set()
    for k, c in cells.items():
        if c[0] == attacker:
            for n in P.neighbors(k):
                if n not in cells and n not in fset:
                    fset.add(n)
                    frontier.append(n)
    out = {}
    for i, bp in enumerate(st["blueprints"][attacker]):
        for m in P.place_moves(cells, frontier, bp, i):
            at = P.parse(m.split("@")[1])
            _, removed = P.stamp(cells, attacker, bp, at)
            hit = [k for k in removed if cells[k][1] == P.STAR]
            if not hit:
                continue
            pts = len(hit) * stars
            for k in hit:
                best, moves = out.get(k, (0, []))
                moves.append(m)
                out[k] = (max(best, pts), moves)
    return out


def describe(view, move):
    """(points, stars captured, stamped cell keys) of a move for the side to move."""
    st = P.from_view(view)
    seat = P.turn_of(st["ply"])
    nxt = P.play(st, move)
    pts = nxt["scores"][seat] - st["scores"][seat]
    if "@" not in move:
        return pts, 0, []
    i, at = move.split("@")
    bp = st["blueprints"][seat][int(i) - 1]
    stamped, removed = P.stamp(st["cells"], seat, bp, P.parse(at))
    caught = sum(1 for k in removed if st["cells"][k][1] == P.STAR)
    return pts, caught, [k for k, _ in stamped]


def top_moves(view, info, n=3):
    legal = set(view.get("moves") or [])
    out, seen = [], set()
    items = []
    if info.get("move"):
        items.append({"move": info["move"], "eval": info.get("eval")})
    items += list(info.get("top") or [])
    for it in items:
        m = it.get("move") if isinstance(it, dict) else it
        if m in legal and m not in seen:
            seen.add(m)
            out.append((m, it.get("eval", it.get("score")) if isinstance(it, dict) else None))
        if len(out) >= n:
            break
    return out


def render(view, seat, info, header="", color=None, clock_ms=None):
    st = H.Style(H.use_color(color))
    opp = 1 - seat
    danger = threats(view, opp)
    sugg = top_moves(view, info)
    best_cells = describe(view, sugg[0][0])[2] if sugg else []
    lines = []
    if header:
        lines.append(st.bold(header))
    lines.append(H.render_board(view["cells"], color, danger=danger.keys(), highlight=best_cells))
    sc, stars = view.get("scores") or [0, 0], view.get("stars") or P.star_counts(P.from_view(view)["cells"])
    you = H.SEAT_NAME[seat]
    clock = f"   your clock {clock_ms / 1000:.0f}s" if clock_ms is not None else ""
    lines.append(f"Ply {view['ply']}/120  You are {st.seat(seat, you, True)} (actions left: {view.get('left')}){clock}")
    lines.append(st.seat(0, f"Blue {sc[0]} pts, {stars[0]} stars", True) + "   " + st.seat(1, f"Red {sc[1]} pts, {stars[1]} stars", True))
    if sugg:
        lines.append(st.bold("Top moves:") + ("   (pv: " + " ".join((info.get("pv") or [])[:4]) + ")" if info.get("pv") else ""))
        for i, (m, ev) in enumerate(sugg):
            pts, caught, _ = describe(view, m)
            what = f"+{pts} pts, captures {caught} star(s)" if "@" in m else "edit blueprint"
            evs = ""  # engine evals of the PV and of the root list use different scales; omit for humans
            lines.append(f"  {i + 1}. {st.bold(m):<14} {what}{evs}" + ("   <- '+' on board" if i == 0 and best_cells else ""))
    else:
        lines.append("No suggestion available.")
    if danger:
        worst = sorted(danger.items(), key=lambda kv: -kv[1][0])[:4]
        txt = ", ".join(f"{k} ({p} pts via {ms[0]})" for k, (p, ms) in worst)
        lines.append(st.warn("Danger:") + f" {H.SEAT_NAME[opp]} can capture your stars at {txt}" + (" ..." if len(danger) > 4 else ""))
    else:
        lines.append("Danger: none of your stars can be captured by a single placement.")
    return "\n".join(lines)
