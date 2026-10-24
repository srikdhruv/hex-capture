#!/usr/bin/env python3
"""Tests for tools/analyze.py on real logs (client/logs) and lab/positions. python3 tools/test_analyze.py"""
import glob
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "client"))
import analyze as A  # noqa: E402
import bprules as P  # noqa: E402

# Min seal matches lab/sealcut.mjs on the start position (26 walls per side).
s0 = P.setup()
assert [A.min_seal(s0["cells"], x) for x in (0, 1)] == [26, 26]

cases = []
for f in glob.glob(os.path.join(REPO, "client", "logs", "game-*.jsonl")):
    sts = [s for s in A._states_from_log(f) if s["view"].get("cells")]
    for st in sts[:: max(1, len(sts) // 6)]:
        cases.append((os.path.basename(f), st))
for f in glob.glob(os.path.join(REPO, "lab", "positions", "*.json")):
    cases.append((os.path.basename(f), A.load(f)))
assert cases, "no real logs/positions to test on"

worst = 0.0
for name, st in cases:
    t0 = time.time()
    lines = A.analyze(st)
    dt = time.time() - t0
    worst = max(worst, dt)
    assert len(lines) <= 30, (name, len(lines))
    state = P.from_view(st["view"])
    seat = (st.get("you") or [st["view"].get("turn", 0)])[0]
    # exact "capturable now" claims really capture the star
    for k, (pts, m) in A.capture_now(state, seat).items():
        i, at = m.split("@")
        _, removed = P.stamp(state["cells"], seat, state["blueprints"][seat][int(i) - 1], P.parse(at))
        assert k in removed, (name, k, m)
    # crack lines are legal and capture the target
    rows, L = A.star_report(state, seat)
    reach = [r for r in rows if r["actions"] is not None]
    if reach:
        line = A.crack_line(state, seat, reach[0]["star"], L, budget_s=0.35)
        if line and line[1]:
            s2, _ = A.apply_place(state, seat, line[0])
            assert line[0] in P.place_moves(state["cells"], sorted(A.frontier(state["cells"], seat)),
                                            state["blueprints"][seat][int(line[0].split("@")[0]) - 1],
                                            int(line[0].split("@")[0]) - 1), (name, line)
            i, at = line[1].split("@")
            _, removed = P.stamp(s2["cells"], seat, s2["blueprints"][seat][int(i) - 1], P.parse(at))
            assert reach[0]["star"] in removed, (name, line)
print(f"OK: analyze.py on {len(cases)} real positions; slowest {worst:.2f}s")
