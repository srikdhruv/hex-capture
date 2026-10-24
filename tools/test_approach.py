#!/usr/bin/env python3
"""Tests for tools/approach.py and the pilot_daemon "approach" rule on R8 (vs Eris) positions."""
import glob
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "client"))
import analyze as A  # noqa: E402
import approach as AP  # noqa: E402
import bprules as P  # noqa: E402
import pilot_daemon as PD  # noqa: E402

R8 = "2fe8dfc5610291e98e0f97147b6ae2d7b7c0b7c063d9295c43f4c69a81e30c6d"
files = sorted(glob.glob(os.path.join(REPO, "lab", "positions", f"{R8}-p*.json")))
assert files, "R8 positions missing"
walked = 0
for f in files:
    st = A.load(f)
    view, seat = st["view"], st["you"][0]
    r = AP.plan(view, seat, depth=4, beam=6, time_s=3.0)
    # the plan is a legal sequence of OUR moves (opponent ignored)
    s = P.from_view(view)
    for m in r["moves"]:
        hand = s["blueprints"][seat]
        if "@" in m:
            i = int(m.split("@")[0]) - 1
            assert m in P.place_moves(s["cells"], sorted(A.frontier(s["cells"], seat)), hand[i], i), (f, m)
            s, _ = A.apply_place(s, seat, m)
        else:
            assert m in P.edit_moves(hand), (f, m)
            fr, to = m.split(">")
            new = P.apply_edit(hand, (int(fr.split(":")[0]) - 1, fr.split(":")[1]), (int(to.split(":")[0]) - 1, to.split(":")[1]))
            bps = list(s["blueprints"]); bps[seat] = new; s = {**s, "blueprints": bps}
    if r["D0"] != float("inf") and r["D_end"] < r["D0"]:
        walked += 1
    assert r["ms"] < 3500
    print(f"{os.path.basename(f)[-22:]}: D {r['D0']} -> {r['D_after_turn']} (turn) -> {r['D_end']} (plan); "
          f"plan {' '.join(r['moves'])}; capture ply {r['capture_ply']} [{r['ms']}ms]")
assert walked >= len([f for f in files]) // 2, f"planner walked toward Eris in only {walked}/{len(files)} positions"

# Daemon approach rule: R8 ply 25 (no capture available, D 16 -> 9 this turn) picks the plan, then its 2nd move.
st = A.load(os.path.join(REPO, "lab", "positions", f"{R8}-p025-star-loss.json"))
view = st["view"]
d = tempfile.mkdtemp()
dm = PD.Daemon(d, None, out=lambda s: None)
eng = sorted(m for m in view["moves"] if "@" in m)[0]
dec = {"room": R8, "ply": 25, "seat": 1, "colour": "Red", "scores": [30, 0], "stars": [6, 1], "clock_ms": 60000,
       "left_in_turn": 2, "engine_move": eng, "top": [{"move": eng, "points": 0}], "danger": []}
rules = {"approach": {"ply_min": 10, "ply_max": 80, "min_gain": 2, "time_s": 1.5}}
mv, why = dm.decide(dec, rules, view)
assert why.startswith("approach:"), why
second = dm.approach_next
assert second and second[1] == 26, second
v2 = P.to_view(A.apply_place(P.from_view(view), 1, mv)[0] | {"ply": 26})
dec2 = dict(dec, ply=26, left_in_turn=1, engine_move=sorted(m for m in v2["moves"] if "@" in m)[0])
dec2["top"] = [{"move": dec2["engine_move"], "points": 0}]
mv2, why2 = dm.decide(dec2, rules, v2)
assert mv2 == second[2] and "2nd action" in why2, (mv2, why2)
# out of ply range -> engine
assert dm.decide(dec, {"approach": {"ply_min": 30}}, view)[0] == eng
# capture available -> no approach
dec3 = dict(dec, top=[{"move": eng, "points": 6}])
assert dm.decide(dec3, rules, view)[0] == eng
print(f"OK: approach planner walked toward the enemy in {walked}/{len(files)} R8 positions; daemon rule OK ({why})")
