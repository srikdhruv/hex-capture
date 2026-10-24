#!/usr/bin/env python3
"""Pair-play helper for Blueprints: render the position and suggest moves.

Input (one of):
  python3 tools/suggest.py state.json                # server state {"view":...}, bare view, or rules state
  python3 tools/suggest.py client/logs/game-X.jsonl  # latest "state" record of a bot game log (--ply N for another)
  python3 tools/suggest.py --moves "2@-3,-3 2@9,-3"  # replay from setup (reference rules)
  ... | python3 tools/suggest.py -                   # JSON on stdin

Options: --seat N (perspective for the danger list; default = side to move), --time-ms N (engine think
time, default 3000), --top N, --engine CMD (default engine/bp, fallback node tools/greedy.mjs),
--no-engine, --color/--no-color.

Output: board (B*/Bw/Bo, R*/Rw/Ro, empty hexes show q, rows labelled r), scores, star counts,
turn + actions left, both hands, top suggestions with points/captures and the opponent's best reply,
and the danger list (stars of --seat the opponent could capture with one placement).
"""
import argparse
import json
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "client"))
import hexrender as H  # noqa: E402  (shared with the packaged bot: client/hexrender.py)

BPCLI = os.path.join(HERE, "bpcli.mjs")
GREEDY = os.path.join(HERE, "greedy.mjs")


def bpcli(req):
    p = subprocess.run(["node", BPCLI], input=json.dumps(req).encode(), capture_output=True, timeout=120, cwd=REPO)
    if p.returncode != 0:
        raise SystemExit("rules error: " + p.stderr.decode(errors="replace")[-600:])
    out = json.loads(p.stdout)
    if "error" in out:
        raise SystemExit("rules error: " + out["error"])
    return out


def load_input(args):
    if args.moves is not None:
        moves = [m for m in args.moves.replace(",", ",").split() if m]
        return bpcli({"op": "replay", "moves": moves})["view"], None
    if not args.file:
        raise SystemExit("give a state file, '-' for stdin, or --moves")
    text = sys.stdin.read() if args.file == "-" else open(args.file).read()
    raw = None
    if args.file.endswith(".jsonl"):
        for line in text.splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") == "state" and rec.get("state"):
                if args.ply is None or rec["state"].get("ply", (rec["state"].get("view") or {}).get("ply")) == args.ply:
                    raw = rec["state"]
        if raw is None:
            raise SystemExit("no state records in " + args.file)
    else:
        raw = json.loads(text)
    view = bpcli({"op": "view", "state": raw})["view"]
    src_view = raw.get("view", raw) if isinstance(raw, dict) else {}
    if isinstance(src_view.get("moves"), list) and src_view["moves"]:
        view["moves"] = src_view["moves"]  # server's legal list is authoritative
    return view, raw


def engine_cmd(spec):
    if spec:
        return shlex.split(spec)
    bp = os.path.join(REPO, "engine", "bp")
    if os.path.isfile(bp) and os.access(bp, os.X_OK):
        return [bp]
    return ["node", GREEDY]


def run_engine(cmd, view, time_ms):
    payload = {"you": [view["turn"]], "turn": view["turn"], "ply": view["ply"], "view": view}
    try:
        p = subprocess.run(cmd + ["--time-ms", str(time_ms)], input=json.dumps(payload).encode(),
                           capture_output=True, timeout=time_ms / 1000 + 10, cwd=REPO)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    for line in reversed(p.stdout.decode(errors="replace").splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line), None
            except ValueError:
                pass
    return None, p.stderr.decode(errors="replace")[-300:] or f"exit {p.returncode}"


def top_moves(res):
    """Normalise engine output into [(move, eval)], best first."""
    out, seen = [], set()
    items = list(res.get("top") or [])
    if res.get("move"):
        items.insert(0, {"move": res["move"], "eval": res.get("eval")})
    for it in items:
        if isinstance(it, dict):
            m, e = it.get("move"), it.get("eval", it.get("score"))
        elif isinstance(it, (list, tuple)) and it:
            m, e = it[0], (it[1] if len(it) > 1 else None)
        else:
            m, e = it, None
        if isinstance(m, str) and m not in seen:
            seen.add(m)
            out.append((m, e))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("--moves", help='space-separated move list replayed from setup, e.g. "2@-3,-3 2@9,-3"')
    ap.add_argument("--ply", type=int, help="with a .jsonl game log: use the state at this ply (default: latest)")
    ap.add_argument("--seat", type=int, help="perspective for the danger list (default: side to move)")
    ap.add_argument("--time-ms", type=int, default=3000)
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--engine", default=os.environ.get("ENGINE_CMD"))
    ap.add_argument("--no-engine", action="store_true")
    ap.add_argument("--color", dest="color", action="store_true", default=None)
    ap.add_argument("--no-color", dest="color", action="store_false")
    args = ap.parse_args()

    view, raw = load_input(args)
    st = H.Style(H.use_color(args.color))
    turn, ply, left = view["turn"], view["ply"], view["left"]
    seat = args.seat if args.seat is not None else (
        (raw or {}).get("you", [turn])[0] if isinstance(raw, dict) and raw.get("you") else turn)
    opp = 1 - seat

    threats = bpcli({"op": "threats", "state": view, "attacker": opp})["threats"]
    danger = {}
    for t in threats:
        for k in t["starKeys"]:
            d = danger.setdefault(k, {"best": 0, "moves": []})
            d["best"] = max(d["best"], t["points"])
            d["moves"].append(t["move"])

    print(H.render_board(view["cells"], args.color, danger=danger.keys()))
    print()
    sc, stars = view["scores"], view["stars"]
    print(f"Ply {ply}/120   " + st.seat(0, f"Blue score {sc[0]}  stars {stars[0]}", True) + "   "
          + st.seat(1, f"Red score {sc[1]}  stars {stars[1]}", True))
    if view.get("result"):
        print(st.bold(f"GAME OVER: {json.dumps(view['result'])}"))
    else:
        print(f"To move: " + st.seat(turn, H.SEAT_NAME[turn], True) + f"  (actions left this turn: {left})"
              + f"   perspective: {H.SEAT_NAME[seat]}")
    print()
    for s in (0, 1):
        print(H.render_hand(view["blueprints"][s], s, args.color))
    print()

    if not args.no_engine and not view.get("result") and view["moves"]:
        cmd = engine_cmd(args.engine)
        res, err = run_engine(cmd, view, args.time_ms)
        name = os.path.basename(cmd[-1] if cmd[0] == "node" else cmd[0])
        if res is None:
            print(st.warn(f"engine {name} failed: {err}"))
            if cmd[0] != "node":
                res, err = run_engine(["node", GREEDY], view, min(args.time_ms, 1500))
                name = "greedy.mjs"
        if res:
            legal = set(view["moves"])
            cands = [(m, e) for m, e in top_moves(res) if m in legal][: args.top]
            analysis = {r["move"]: r for r in bpcli({"op": "analyze", "state": view, "moves": [m for m, _ in cands]})["results"]}
            pv = res.get("pv") or []
            print(st.bold(f"Suggestions for {H.SEAT_NAME[turn]} ({name}, {args.time_ms}ms)") +
                  (f"   pv: {' '.join(pv[:6])}" if pv else ""))
            for i, (m, e) in enumerate(cands):
                a = analysis.get(m, {})
                sa = a.get("starsAfter", stars)
                desc = (f"+{a.get('points', 0)} pts, captures {a.get('removedStars', 0)}* "
                        f"({a.get('removedCells', 0)} cells), stars B{sa[0]}/R{sa[1]}") if a.get("type") == "place" else "edit blueprint"
                reply = f"opp best reply {a.get('oppBestReply')} = {a.get('oppBestReplyPoints')} pts" if a.get("oppBestReplyPoints") else "opp no capture reply"
                ev = "" if e is None else f"eval {e}"
                print(f"  {i + 1}. {st.bold(m):14s}  {ev:12s} {desc};  {reply}")
            print()

    # Danger list.
    title = f"Danger: {H.SEAT_NAME[seat]} stars {H.SEAT_NAME[opp]} can capture with one placement"
    if not danger:
        print(st.bold(title) + ": none")
    else:
        print(st.bold(title) + ":")
        for k, d in sorted(danger.items(), key=lambda kv: -kv[1]["best"]):
            mv = " ".join(d["moves"][:4]) + (" ..." if len(d["moves"]) > 4 else "")
            print(f"  {st.warn(k):>8}  up to {d['best']} pts   via {mv}")
        if threats:
            t = threats[0]
            print(f"  worst single placement: {t['move']} takes {t['starsRemoved']}* = {t['points']} pts")


if __name__ == "__main__":
    main()
