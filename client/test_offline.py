#!/usr/bin/env python3
"""Offline test of bot.py message handling (no network): fake websocket + captured HTTP calls.

python3 client/test_offline.py
"""
import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot  # noqa: E402


class FakeSock:
    connected = True


class FakeWS:
    def __init__(self):
        self.sock = FakeSock()
        self.sent = []

    def send(self, s):
        self.sent.append(json.loads(s))

    def close(self):
        pass


def view_after(moves):
    return bot.bpcli({"op": "replay", "moves": moves})["view"]


def main():
    import tempfile
    bot.LOG_DIR = os.path.join(tempfile.gettempdir(), "bp-test-logs")  # keep test noise out of client/logs
    chooser = bot.Chooser(os.environ.get("ENGINE_CMD"), 1500)
    b = bot.Bot("https://example.invalid", "x" * 20, "tid123", chooser)
    calls = []
    responses = {}

    def fake_call(path, body, method="POST"):
        calls.append((path, body))
        return responses.get(path, {"ok": True})

    b.call = fake_call
    ws = FakeWS()
    b.ws = ws

    b.on_message(ws, json.dumps({"type": "ready"}))
    assert ws.sent[-1] == {"type": "watch-tournament", "tournament": "tid123"}, ws.sent
    now = time.time() * 1000
    t_state = {"round": 1, "status": "playing", "active": True, "withdrawn": False, "checkedIn": False,
               "closesAt": now + 60000, "game": {"ready": True, "room": "roomA", "round": 1}}
    b.on_message(ws, json.dumps({"type": "tournament", "tournament": "tid123", "state": t_state}))
    assert calls[0][0] == "/api/engine/tournaments/tid123/check-in", calls
    assert ws.sent[-1] == {"type": "watch-game", "room": "roomA", "tournament": "tid123"}, ws.sent

    # Not our turn: no move.
    v0 = view_after([])
    b.on_message(ws, json.dumps({"type": "state", "room": "roomA",
                                 "state": {"you": [1], "turn": 0, "ply": 0, "view": v0, "clock": None}}))
    time.sleep(0.5)
    assert len(calls) == 1, calls

    # Our turn (seat 1 at ply 1, two actions).
    v1 = view_after(["2@-3,-3"])
    st = {"you": [1], "turn": 1, "ply": 1, "view": v1, "clock": {"remaining": [70000, 60000]}}
    b.on_message(ws, json.dumps({"type": "state", "room": "roomA", "state": st}))
    deadline = time.time() + 10
    while len(calls) < 2 and time.time() < deadline:
        time.sleep(0.05)
    path, body = calls[1]
    assert path == "/api/engine/tournaments/tid123/move", path
    assert body["ply"] == 1 and body["move"] in v1["moves"], body
    # Duplicate push of the same state must not re-POST.
    b.on_message(ws, json.dumps({"type": "state", "room": "roomA", "state": st}))
    time.sleep(0.5)
    assert len(calls) == 2, calls

    # Second action of the turn; simulate a 409 -> None -> re-watch, no replay.
    v2 = view_after(["2@-3,-3", body["move"]])
    responses["/api/engine/tournaments/tid123/move"] = None
    n_sent = len(ws.sent)
    b.on_message(ws, json.dumps({"type": "state", "room": "roomA",
                                 "state": {"you": [1], "turn": 1, "ply": 2, "view": v2, "clock": {"remaining": [70000, 58000]}}}))
    deadline = time.time() + 10
    while len(calls) < 3 and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.2)
    assert calls[2][1]["ply"] == 2 and calls[2][1]["move"] in v2["moves"], calls[2]
    assert ws.sent[n_sent:] == [{"type": "watch-game", "room": "roomA", "tournament": "tid123"}], ws.sent[n_sent:]
    assert b.pending.get("roomA") is None

    # Standalone challenge / self-test: posts to /api/engine/games/<room>/move.
    b.on_message(ws, json.dumps({"type": "challenge", "room": "selfR"}))
    b.on_message(ws, json.dumps({"type": "state", "room": "selfR",
                                 "state": {"you": [1], "turn": 1, "ply": 1, "view": v1, "clock": None}}))
    deadline = time.time() + 10
    while len(calls) < 4 and time.time() < deadline:
        time.sleep(0.05)
    assert calls[3][0] == "/api/engine/games/selfR/move", calls[3]

    # Clock parsing shapes.
    bot._clock_unit_ms = None
    assert abs(bot.my_clock_ms({"clock": [61000, 30000], "turn": 1}, 1) - 30000) < 1
    assert bot.think_budget_ms(60000, 9000) == 9000
    assert bot.think_budget_ms(8000, 9000) < 3000
    assert bot.think_budget_ms(None, 9000) == 9000
    print("OK: all offline client tests passed;", len(calls), "HTTP calls:", [c[0] for c in calls])


if __name__ == "__main__":
    main()
