#!/usr/bin/env python3
"""Replay the logged R8 (Eris), R9 (aryan) and R10 (wernerolaf) openings and compare the bots' choices with the
humans' actual moves at each of their first N actions (same logged position). python3 tools/bots/validate.py"""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "client"))
import bprules as P  # noqa: E402

GAMES = {"2fe8dfc56102": ("sealer", "Eris R8"), "2fc42312c3cd": ("sealer", "aryan R9"), "858223c7655d": ("rusher", "wernerolaf R10")}
N = int(sys.argv[1]) if len(sys.argv) > 1 else 30


def history(prefix):
    for f in glob.glob(os.path.join(REPO, "client", "logs", f"game-{prefix}*.jsonl")):
        st = None
        for line in open(f):
            r = json.loads(line)
            if r.get("type") == "state" and r["state"].get("history") is not None:
                st = r["state"]
        return st
    return None


for prefix, (bot, label) in GAMES.items():
    st = history(prefix)
    if not st:
        print(f"{label}: log missing")
        continue
    opp = 1 - st["you"][0]
    g = P.setup()
    n = edits = edit_ok = stamps = piece_ok = 0
    dists = []
    for m in st["history"]:
        if P.turn_of(g["ply"]) == opp and n < N:
            view = P.to_view(g)
            state = {"you": [opp], "turn": opp, "ply": g["ply"], "view": view}
            p = subprocess.run([sys.executable, os.path.join(HERE, f"{bot}.py"), "--time-ms", "600"],
                               input=json.dumps(state), capture_output=True, text=True, timeout=60)
            mine = json.loads(p.stdout.strip().splitlines()[-1])["move"]
            n += 1
            if ">" in m:
                edits += 1
                edit_ok += mine == m
            else:
                stamps += 1
                if "@" in mine:
                    piece_ok += mine.split("@")[0] == m.split("@")[0]
                    a, b = P.parse(mine.split("@")[1]), P.parse(m.split("@")[1])
                    dists.append((abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[0] - b[0] + a[1] - b[1])) // 2)
        g = P.play(g, m)
    md = sorted(dists)[len(dists) // 2] if dists else None
    print(f"{label} ({bot}, seat {opp}): first {n} actions; edits matched {edit_ok}/{edits}; "
          f"stamps with the same piece {piece_ok}/{stamps}; median anchor distance {md}")
