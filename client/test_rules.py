#!/usr/bin/env python3
"""Check client/bprules.py against reference/rules.mjs on random full games (needs node)."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bprules as P  # noqa: E402

REPO = os.path.dirname(HERE)
for seed in (1, 2, 3):
    out = subprocess.run(["node", os.path.join(REPO, "tools", "bpcli.mjs")], input=json.dumps({"op": "selfplay", "plies": 120, "seed": seed}),
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s = P.setup()
    for i, m in enumerate(d["moves"] + [None]):
        js = d["states"][i]
        pv = P.to_view(s)
        assert set(pv["moves"]) == set(js["moves"]), (seed, i, len(pv["moves"]), len(js["moves"]))
        assert len(pv["moves"]) == len(js["moves"]), (seed, i)
        assert pv["cells"] == js["cells"] and pv["scores"] == js["scores"] and pv["blueprints"] == js["blueprints"], (seed, i)
        assert pv["turn"] == js["turn"] and pv["left"] == js["left"] and pv["result"] == js["result"], (seed, i)
        if m:
            s = P.play(s, m)
    print(f"seed {seed}: {len(d['moves'])} plies match, final scores {s['scores']}")
print("OK bprules matches reference")
