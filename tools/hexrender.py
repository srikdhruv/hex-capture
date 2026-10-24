"""Terminal rendering of Blueprints boards and blueprints (axial hex coords, pointy-top, offset rows).

Board cells: {"q,r": [seat, kind]} with seat 0 = Blue, 1 = Red and kind star/wall/plain.
Tokens: B* Bw Bo / R* Rw Ro. Empty hexes show their q coordinate (dim); each row is labelled r=.
A trailing "!" marks a star in danger.
"""
import os
import sys

KIND_CH = {"star": "*", "wall": "w", "plain": "o"}
SEAT_CH = {0: "B", 1: "R"}
SEAT_NAME = {0: "Blue", 1: "Red"}
DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def use_color(flag=None):
    if flag is not None:
        return flag
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


class Style:
    def __init__(self, color):
        self.color = color

    def _w(self, code, s):
        return f"\033[{code}m{s}\033[0m" if self.color else s

    def seat(self, seat, s, bold=False):
        code = "94" if seat == 0 else "91"
        return self._w(("1;" if bold else "") + code, s)

    def dim(self, s):
        return self._w("2", s)

    def warn(self, s):
        return self._w("1;93", s)

    def bold(self, s):
        return self._w("1", s)


def parse(k):
    q, r = k.split(",")
    return int(q), int(r)


def render_board(cells, color=None, danger=(), margin=1, highlight=()):
    """Return the board as a string. danger: keys marked with '!'; highlight: keys marked with '+'."""
    st = Style(use_color(color))
    danger, highlight = set(danger), set(highlight)
    if not cells:
        return "(empty board)"
    pts = [parse(k) for k in cells]
    keys = set(cells)
    for k in highlight:
        pts.append(parse(k))
    rmin = min(r for _, r in pts) - margin
    rmax = max(r for _, r in pts) + margin
    # x = 2q + r (doubled columns); bound by occupied x range +- margin.
    xs = [2 * q + r for q, r in pts]
    xmin, xmax = min(xs) - 2 * margin, max(xs) + 2 * margin
    lines = []
    width = 4  # chars per cell; half-cell offset of 2 between rows
    header = f"{'':6}" + "empty hexes next to pieces show their q; rows show r.  B=Blue R=Red  *=star w=wall o=plain  !=star in danger"
    lines.append(st.dim(header))
    for r in range(rmin, rmax + 1):
        row = []
        # q range for this row such that xmin <= 2q + r <= xmax
        qlo = -((r - xmin) // 2)  # ceil((xmin - r)/2)
        qhi = (xmax - r) // 2
        col0 = (2 * qlo + r - xmin) * (width // 2)
        for q in range(qlo, qhi + 1):
            k = f"{q},{r}"
            c = cells.get(k)
            if c:
                seat, kind = int(c[0]), c[1]
                tok = SEAT_CH.get(seat, "?") + KIND_CH.get(kind, "?")
                mark = "!" if k in danger else ("+" if k in highlight else " ")
                s = st.seat(seat, tok, bold=(kind == "star"))
                s += st.warn(mark) if mark == "!" else mark
            elif k in highlight:
                s = st.warn(f"{q:>2}+")
            elif any(f"{q + a},{r + b}" in keys for a, b in DIRS):
                s = st.dim(f"{q:>3}")
            else:
                s = st.dim("  .")
            row.append(s)
        lines.append(f"r={r:>3} " + " " * col0 + " ".join(row))
    return "\n".join(lines)


def render_blueprint(bp, color=None, seat=None):
    """Small render of one blueprint (relative coords). '(x)' marks the anchor cell 0,0."""
    st = Style(use_color(color))
    if not bp:
        return ["(empty)"]
    pts = [parse(k) for k in bp]
    rmin, rmax = min(r for _, r in pts), max(r for _, r in pts)
    xs = [2 * q + r for q, r in pts]
    xmin, xmax = min(xs), max(xs)
    out = []
    for r in range(rmin, rmax + 1):
        line = [" "] * ((xmax - xmin) * 2 + 4)
        segs = []
        for q, rr in pts:
            if rr != r:
                continue
            x = (2 * q + r - xmin) * 2
            ch = KIND_CH.get(bp[f"{q},{r}"], "?")
            segs.append((x, ch, (q, r) == (0, 0)))
        s, pos = "", 0
        for x, ch, anchor in sorted(segs):
            s += " " * (x - pos)
            tok = f"({ch})" if anchor else f" {ch} "
            s += st.seat(seat, tok, bold=ch == "*") if seat is not None else tok
            pos = x + 3
        out.append(s)
        del line
    return out


def bp_keys(bp):
    """Compact listing of blueprint cells for typing edit moves, e.g. '0,0=w 1,0=*'."""
    def sk(k):
        q, r = parse(k)
        return (r, q)
    return " ".join(f"{k}={KIND_CH.get(v, '?')}" for k, v in sorted(bp.items(), key=lambda kv: sk(kv[0])))


def render_hand(hand, seat, color=None):
    """Blueprints side by side with headers, plus key listings below."""
    st = Style(use_color(color))
    blocks = []
    for i, bp in enumerate(hand):
        stars = sum(1 for v in bp.values() if v == "star")
        title = f"#{i + 1} ({len(bp)} cells, {stars}*)"
        body = render_blueprint(bp, color, seat)
        blocks.append([title] + body)
    import re
    strip = lambda s: re.sub(r"\033\[[0-9;]*m", "", s)  # noqa: E731
    widths = [max(len(strip(l)) for l in b) + 4 for b in blocks]
    height = max(len(b) for b in blocks)
    lines = [st.seat(seat, f"{SEAT_NAME[seat]} hand:", bold=True)]
    for row in range(height):
        parts = []
        for b, w in zip(blocks, widths):
            cell = b[row] if row < len(b) else ""
            parts.append(cell + " " * (w - len(strip(cell))))
        lines.append("  " + "".join(parts).rstrip())
    for i, bp in enumerate(hand):
        lines.append(st.dim(f"  #{i + 1}: {bp_keys(bp)}"))
    return "\n".join(lines)
