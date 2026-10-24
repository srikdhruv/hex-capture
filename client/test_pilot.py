#!/usr/bin/env python3
"""Offline tests for the pilot control interface (client/pilot.py). python3 client/test_pilot.py"""
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot  # noqa: E402
import bprules  # noqa: E402
import pilot as P  # noqa: E402

bot.LOG_DIR = os.path.join(tempfile.gettempdir(), "bp-test-logs")
g = bprules.play(bprules.setup(), "2@-3,-3")
VIEW = bprules.to_view(g)
A, B, C = VIEW["moves"][:3]


class FakeChooser:
    def __init__(self, clock=60000):
        self.calls = 0
        self.extra_args = []
        self.clock = clock

    def choose(self, room, state, seat):
        self.calls += 1
        return A, {"ply": state["ply"], "clock_ms": self.clock, "budget_ms": 100, "source": "engine", "eval": 1.0,
                   "pv": [A], "top": [{"move": A, "score": 1.0}, {"move": B, "score": 0.5}, {"move": C, "score": 0.1}]}


def state():
    return {"you": [1], "turn": 1, "ply": 1, "view": VIEW, "clock": None}


def ctl(d, obj):
    with open(os.path.join(d, "control.json"), "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def main():
    d = tempfile.mkdtemp(prefix="pilot-")
    pl = P.Pilot(d, bot.log)
    # no control file -> engine move, decision.json written with the contract fields
    ch = FakeChooser()
    m, info = pl.decide(ch, "r", state(), 1)
    assert m == A and info["source"] == "engine", (m, info)
    dec = json.load(open(os.path.join(d, "decision.json")))
    for k in ("room", "ply", "seat", "colour", "scores", "stars", "clock_ms", "left_in_turn", "top", "engine_move",
              "board_text", "danger", "opp_hand_summary", "our_hand_summary", "deadline_epoch_ms"):
        assert k in dec, k
    assert dec["top"][0]["move"] == A and "points" in dec["top"][0] and "captures" in dec["top"][0]
    # malformed control -> engine move
    ctl(d, "{not json")
    assert pl.decide(FakeChooser(), "r", state(), 1)[0] == A
    # veto
    ctl(d, {"veto": [A]})
    m, info = pl.decide(FakeChooser(), "r", state(), 1)
    assert m == B and info["source"] == "veto", (m, info)
    # force (no engine call), engine_args applied
    ch = FakeChooser()
    ctl(d, {"force": {"1": C}, "engine_args": "--p alpha=0"})
    m, info = pl.decide(ch, "r", state(), 1)
    assert m == C and info["source"] == "pilot-force" and ch.calls == 0 and ch.extra_args == ["--p", "alpha=0"]
    # illegal force is ignored
    ctl(d, {"force": {"1": "9@99,99"}})
    assert pl.decide(FakeChooser(), "r", state(), 1)[0] == A
    # pick arrives within prefer_wait_ms
    ctl(d, {"prefer_wait_ms": 3000})
    threading.Timer(0.5, lambda: open(os.path.join(d, "pick-1.json"), "w").write(json.dumps({"move": C}))).start()
    t0 = time.time()
    m, info = pl.decide(FakeChooser(), "r", state(), 1)
    assert m == C and info["source"] == "pilot-pick" and time.time() - t0 < 2.5, (m, info)
    os.remove(os.path.join(d, "pick-1.json"))
    # no pick -> waits, then engine move
    ctl(d, {"prefer_wait_ms": 800})
    t0 = time.time()
    m, info = pl.decide(FakeChooser(), "r", state(), 1)
    assert m == A and 0.7 < time.time() - t0 < 2.0
    # low clock: never wait under 25s
    ctl(d, {"prefer_wait_ms": 5000})
    t0 = time.time()
    assert pl.decide(FakeChooser(clock=24000), "r", state(), 1)[0] == A and time.time() - t0 < 0.7
    # wait capped so the clock stays >= 20s: 25.1s left, prefer 9s -> ~5.1s wait
    ctl(d, {"prefer_wait_ms": 9000})
    t0 = time.time()
    pl.decide(FakeChooser(clock=25100), "r", state(), 1)
    assert 4.5 < time.time() - t0 < 5.8, time.time() - t0
    # last_result.json
    pl.write_result("r", {"view": {"result": {"winner": 1}, "scores": [1, 2]}, "you": [1]}, "GAME OVER test")
    assert json.load(open(os.path.join(d, "last_result.json")))["summary"] == "GAME OVER test"

    # End-to-end: real engine selftest with a fake pilot that always picks the engine's 2nd choice.
    d2 = tempfile.mkdtemp(prefix="pilot-e2e-")
    pl2 = P.Pilot(d2, bot.log)
    ctl(d2, {"prefer_wait_ms": 4000, "note": "fake pilot"})
    stop = threading.Event()
    picks = {}

    def fake_pilot():
        seen = None
        while not stop.is_set():
            try:
                dec = json.load(open(os.path.join(d2, "decision.json")))
            except (OSError, ValueError):
                time.sleep(0.05)
                continue
            if dec["ply"] != seen and len(dec["top"]) > 1:
                seen = dec["ply"]
                picks[seen] = dec["top"][1]["move"]
                with open(os.path.join(d2, f"pick-{seen}.json"), "w") as f:
                    json.dump({"move": picks[seen]}, f)
            time.sleep(0.05)
    threading.Thread(target=fake_pilot, daemon=True).start()
    chooser = bot.Chooser(os.environ.get("ENGINE_CMD"), 500)
    bot.selftest(chooser, 4, pilot=pl2)
    stop.set()
    assert picks, "fake pilot never saw a decision"
    print("OK: pilot tests passed; e2e picks:", picks)


if __name__ == "__main__":
    main()
