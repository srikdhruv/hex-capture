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


def wait_for(pred, timeout=10):
    deadline = time.time() + timeout
    while not pred() and time.time() < deadline:
        time.sleep(0.05)
    assert pred(), "timed out waiting"


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
    wait_for(lambda: len(calls) >= 1)
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

    # Stale (out-of-order) snapshot for roomA must be ignored.
    n = len(calls)
    b.on_message(ws, json.dumps({"type": "state", "room": "roomA",
                                 "state": {"you": [1], "turn": 1, "ply": 1, "view": v1, "clock": None}}))
    time.sleep(0.5)
    assert len(calls) == n, calls[n:]

    # Round 2: new board, check in again.
    t2 = dict(t_state, round=2, checkedIn=False, game={"ready": False, "room": None, "round": 2})
    b.on_message(ws, json.dumps({"type": "tournament", "tournament": "tid123", "state": t2}))
    wait_for(lambda: len(calls) > n)
    assert calls[n][0] == "/api/engine/tournaments/tid123/check-in", calls[n]
    t2 = dict(t2, checkedIn=True, game={"ready": True, "room": "roomB", "round": 2})
    b.on_message(ws, json.dumps({"type": "tournament", "tournament": "tid123", "state": t2}))
    assert ws.sent[-1] == {"type": "watch-game", "room": "roomB", "tournament": "tid123"}, ws.sent[-1]
    assert len(calls) == n + 1  # no second check-in

    # Reconnect: close clears subscriptions; ready -> watch-tournament -> push -> re-watch board.
    b.on_close(ws, 1006, "")
    assert not b.stopped.is_set()
    b.on_message(ws, json.dumps({"type": "ready"}))
    assert ws.sent[-1] == {"type": "watch-tournament", "tournament": "tid123"}
    b.on_message(ws, json.dumps({"type": "tournament", "tournament": "tid123", "state": t2}))
    assert ws.sent[-1] == {"type": "watch-game", "room": "roomB", "tournament": "tid123"}, ws.sent[-1]
    # A roomB move after reconnect still goes to the tournament path.
    b.on_message(ws, json.dumps({"type": "state", "room": "roomB",
                                 "state": {"you": [1], "turn": 1, "ply": 1, "view": v1, "clock": [60000, 5000]}}))
    wait_for(lambda: len(calls) > n + 1)
    assert calls[n + 1][0] == "/api/engine/tournaments/tid123/move", calls[n + 1]

    # Fatal close codes stop reconnecting.
    b.on_close(ws, 4003, "revoked")
    assert b.stopped.is_set()

    # Clock parsing shapes.
    bot._clock_unit_ms = None
    assert abs(bot.my_clock_ms({"clock": [61000, 30000], "turn": 1}, 1) - 30000) < 1
    assert bot.think_budget_ms(60000, 9000) == 9000
    assert bot.think_budget_ms(8000, 9000) < 3000
    assert bot.think_budget_ms(None, 9000) == 9000
    assert bot.think_budget_ms(9999, 9000) == 1000          # emergency mode
    assert bot.think_budget_ms(3500, 9000) == 500
    assert bot.think_budget_ms(60000, 9000, 4000) == 4000   # --max-time-ms cap
    print("OK: all offline client tests passed;", len(calls), "HTTP calls:", [c[0] for c in calls])


if __name__ == "__main__":
    main()
