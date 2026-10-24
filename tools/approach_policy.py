#!/usr/bin/env python3
"""Arena policy: engine/bp + pilot_daemon rules (e.g. the approach rule), same CLI contract as engine/bp.

  python3 tools/approach_policy.py --time-ms 300 [--rules '{"approach": {...}}'] [--engine engine/bp] [--threads 1]
stdin: server-style state JSON; stdout: {"move": ..., "why": ...}
Used to A/B the daemon's rules with tools/arena.py, e.g.
  python3 tools/arena.py --a "python3 tools/approach_policy.py --time-ms 300" --b "engine/bp --time-ms 300 --book lab/books/turtle.json"
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "client"))
import advise  # noqa: E402
import pilot_daemon as PD  # noqa: E402

DEFAULT_RULES = {"approach": {"ply_min": 10, "ply_max": 80, "min_gain": 2, "time_s": 0.8, "depth": 4}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-ms", type=int, default=300)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--engine", default=os.path.join(REPO, "engine", "bp"))
    ap.add_argument("--rules", default=None, help="daemon rules JSON (default: approach rule, plies 10-80)")
    args, extra = ap.parse_known_args()
    state = json.load(sys.stdin)
    view = state.get("view", state)
    seat = (state.get("you") or [view.get("turn")])[0]
    p = subprocess.run([args.engine, "--time-ms", str(args.time_ms), "--threads", str(args.threads)] + extra,
                       input=json.dumps(state), capture_output=True, text=True, timeout=args.time_ms / 1000 + 20)
    res = {}
    for line in reversed(p.stdout.splitlines()):
        if line.strip().startswith("{"):
            res = json.loads(line)
            break
    legal = set(view.get("moves") or [])
    engine_move = res.get("move") if res.get("move") in legal else (view.get("moves") or ["pass"])[0]
    top = []
    for it in [{"move": engine_move}] + list(res.get("top") or []):
        m = it.get("move")
        if m in legal and m not in [t["move"] for t in top]:
            pts, cap, _ = advise.describe(view, m)
            top.append({"move": m, "points": pts, "captures": cap})
        if len(top) >= 8:
            break
    dec = {"room": "arena", "ply": view.get("ply"), "seat": seat, "scores": view.get("scores"), "stars": view.get("stars"),
           "left_in_turn": view.get("left"), "engine_move": engine_move, "top": top, "danger": [], "clock_ms": None}
    rules = json.loads(args.rules) if args.rules else DEFAULT_RULES
    dm = PD.Daemon("/tmp", None, out=lambda s: None)
    try:
        mv, why = dm.decide(dec, rules, view)
    except Exception as e:  # noqa: BLE001
        mv, why = engine_move, f"error {e}"
    if mv not in legal:
        mv, why = engine_move, "illegal pick -> engine"
    print(json.dumps({"move": mv, "why": why}))


if __name__ == "__main__":
    main()
