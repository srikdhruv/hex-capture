#!/usr/bin/env python3
"""Tests for tools/pilot_daemon.py. python3 tools/test_pilot_daemon.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "client"))
import bprules as B  # noqa: E402
import pilot_daemon as PD  # noqa: E402

# A real position: Blue's turn at ply 3 (after 2@-3,-3 | 2@9,-3 2@7,1).
g = B.setup()
for m in ["2@-3,-3", "2@9,-3", "2@7,1"]:
    g = B.play(g, m)
view = B.to_view(g)
places = [m for m in view["moves"] if "@" in m]
edits = [m for m in view["moves"] if ">" in m]
E1, P1, P2 = edits[0], places[0], places[1]
EDIT3 = next(m for m in edits if m.startswith("3:"))


def decision(top, ply=3, caps=None):
    return {"room": "R", "ply": ply, "seat": 0, "colour": "Blue", "scores": [10, 20], "stars": [14, 10],
            "clock_ms": 50000, "left_in_turn": 2, "engine_move": top[0],
            "top": [{"move": m, "points": (caps or {}).get(m, 0)} for m in top], "danger": [], "written_epoch_ms": 1}


d = tempfile.mkdtemp()
dm = PD.Daemon(d, None, out=lambda s: None)
dec = lambda top, rules, **kw: dm.decide(decision(top, **kw), rules, view)  # noqa: E731

assert dec([P1, P2], {})[0] == P1
assert dec([P1, P2], {"enabled": False})[0] == P1
assert dec([P1, P2], {"veto": [P1]})[0] == P2
assert dec([P1, P2], {"veto": ["2@*", "1@*", "3@*"]})[0] in edits  # pattern veto falls back to legal non-vetoed
assert dec([P1, P2], {"force": {"3": P2}})[0] == P2
assert dec([P1, P2], {"force": {"3": {"move": P2, "unless_capture": True}}}, caps={P1: 30})[0] == P1
assert dec([P1, P2], {"force": {"3": "9@99,99"}})[0] == P1  # illegal force ignored
assert dec([EDIT3, P1], {"protect_from": 2})[0] == P1
assert dec([EDIT3, P1], {"protect_from": 2}, caps={P1: 5})[0] == EDIT3  # capture on board: edits allowed
assert dec([EDIT3, P1], {"protect_from": 10})[0] == EDIT3
assert dec([P1, P2], {"take_capture_min": 5}, caps={P2: 30})[0] == P2
assert dec([P1, P2], {"take_capture_min": 5}, caps={P1: 20, P2: 30})[0] == P1  # engine already captures: keep it
w = {"when": [{"if": {"engine_points_below": 10}, "then": {"pick": "best_capture"}}]}
assert dec([P1, P2], w, caps={P2: 30})[0] == P2 and dec([P1, P2], w, caps={P1: 20, P2: 30})[0] == P1
w = {"when": [{"if": {"ply_min": 1, "capture_available": False, "left": 2}, "then": {"prefer": [P2]}, "note": "t"}]}
mv, why = dec([P1, P2], w)
assert mv == P2 and "[t]" in why, why
w = {"when": [{"if": {"score_diff_below": 0}, "then": {"pick": P2}}]}
assert dec([P1, P2], w)[0] == P2
w = {"when": [{"if": {"score_diff_above": 0}, "then": {"pick": P2}}]}
assert dec([P1, P2], w)[0] == P1
w = {"when": [{"if": {"engine_move": "2@*"}, "then": {"veto": ["2@*"]}}]}
assert not dec([P1, P2] + edits[:1], w)[0].startswith("2@")
# star_safe_dist: with a huge distance every non-capturing star stamp is "exposed" -> prefers star-free moves
stars_in = lambda m: any(v == "star" for v in g["blueprints"][0][int(m.split("@")[0]) - 1].values())  # noqa: E731
star_m = next(m for m in places if stars_in(m))
assert dec([star_m, E1], {"star_safe_dist": 99})[0] == E1
w = {"when": [{"if": {"ply_min": 3}, "then": {"star_safe_dist": 99}}]}
assert dec([star_m, E1], w)[0] == E1                                   # gated star_safe_dist applies
assert dec([star_m, E1], {"when": [{"if": {"ply_min": 50}, "then": {"star_safe_dist": 99}}]})[0] == star_m

# step(): writes pick with room/ply, removes stale picks, survives broken rules
json.dump({"move": "x"}, open(os.path.join(d, "pick-1.json"), "w"))
json.dump(decision([P1, P2]), open(os.path.join(d, "decision.json"), "w"))
json.dump({"room": "R", "ply": 3, "state": {"view": view}}, open(os.path.join(d, "state.json"), "w"))
open(os.path.join(d, "rules.json"), "w").write(json.dumps({"veto": [P1]}))
assert dm.step()
pk = json.load(open(os.path.join(d, "pick-3.json")))
assert pk == {"move": P2, "room": "R", "ply": 3, "why": pk["why"]}, pk
assert not os.path.exists(os.path.join(d, "pick-1.json"))
assert not dm.step()  # same decision: nothing new
open(os.path.join(d, "rules.json"), "w").write("{broken")
os.utime(os.path.join(d, "rules.json"), (1, 1))
dec2 = decision([P1, P2]); dec2["written_epoch_ms"] = 2
json.dump(dec2, open(os.path.join(d, "decision.json"), "w"))
assert dm.step() and json.load(open(os.path.join(d, "pick-3.json")))["move"] == P2  # previous rules kept
print("OK: pilot_daemon tests passed")
