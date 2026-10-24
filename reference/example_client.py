"""Random legal-move engine using one hibernating event stream, with no HTTP polling.

pip install websocket-client
Set STRATEGYJAM_URL, STRATEGYJAM_TOKEN, optionally TOURNAMENT_ID.
Staging additionally needs CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET.
"""
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import websocket

base = os.environ["STRATEGYJAM_URL"].rstrip("/")
parsed = urlparse(base)
if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
    raise SystemExit("Use a plain HTTPS StrategyJam origin")
headers = {"Authorization": "Bearer " + os.environ["STRATEGYJAM_TOKEN"]}
for variable, header in [("CF_ACCESS_CLIENT_ID", "CF-Access-Client-Id"), ("CF_ACCESS_CLIENT_SECRET", "CF-Access-Client-Secret")]:
    if os.environ.get(variable):
        headers[header] = os.environ[variable]
tournament = os.environ.get("TOURNAMENT_ID")
stopped = threading.Event()
lock = threading.RLock()
rooms = {}
timers = {}
pending = {}
checked_in = set()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, response_headers, newurl):
        return None  # Never forward a Bearer token to a login page or another origin.


http = urllib.request.build_opener(NoRedirect)


def call(path, body):
    request = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"})
    try:
        with http.open(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            stopped.set()
            raise RuntimeError("Connection expired, revoked or unsupported; check account and entry") from None
        if error.code in (429, 503):
            raw = error.headers.get("Retry-After", "2")
            try:
                seconds = max(2, float(raw))
            except ValueError:
                from email.utils import parsedate_to_datetime
                seconds = max(2, parsedate_to_datetime(raw).timestamp() - time.time())
            if stopped.wait(seconds):
                return None
        if error.code not in (409, 429, 503):
            raise RuntimeError(f"Engine request returned HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError):
        pass
    return None  # May already have committed: request a new pushed snapshot, never replay a move.


def send(ws, message):
    if not stopped.is_set() and ws.sock and ws.sock.connected:
        ws.send(json.dumps(message, separators=(",", ":")))


def watch(ws, room, tournament_id=None):
    with lock:
        rooms[room] = tournament_id
    send(ws, {"type": "watch-game", "room": room, **({"tournament": tournament_id} if tournament_id else {})})


def play(ws, room, state):
    with lock:
        timers.pop(room, None)
        if state["view"].get("result") or state["turn"] not in state["you"] or not state["view"].get("moves"):
            return
        if pending.get(room) == state["ply"]:
            return
        delay = max(0, ((state.get("startsAt") or 0) - time.time() * 1000) / 1000)
        if delay:
            timer = threading.Timer(delay + 0.1, play, args=(ws, room, state))
            timer.daemon = True
            timers[room] = timer
            timer.start()
            return
        pending[room] = state["ply"]
        tournament_id = rooms.get(room)
    path = f"/api/engine/tournaments/{tournament_id}" if tournament_id else f"/api/engine/games/{room}"
    result = call(path + "/move", {"ply": state["ply"], "move": random.choice(state["view"]["moves"])})
    if result is None:
        with lock:
            pending.pop(room, None)
        watch(ws, room, tournament_id)


def message(ws, raw):
    data = json.loads(raw)
    kind = data.get("type")
    if kind == "pong":
        ws.last_pong = time.monotonic()
        return
    if kind == "ready":
        if tournament:
            send(ws, {"type": "watch-tournament", "tournament": tournament})
    elif kind == "inbox":
        for job in data["games"]:
            watch(ws, job["room"])
    elif kind == "challenge":
        watch(ws, data["room"])
    elif kind == "tournament":
        state = data["state"]
        key = (data["tournament"], state["round"])
        if state["status"] == "playing" and state["active"] and not state["withdrawn"]:
            if not state["checkedIn"] and key not in checked_in and (state.get("closesAt") or 0) > time.time() * 1000:
                checked_in.add(key)
                if call(f"/api/engine/tournaments/{key[0]}/check-in", {}) is None:
                    checked_in.discard(key)
                    send(ws, {"type": "watch-tournament", "tournament": key[0]})
            job = state.get("game")
            if job and job["ready"] and job["room"] and job["round"] == state["round"]:
                with lock:
                    already = job["room"] in rooms
                if not already:
                    watch(ws, job["room"], data["tournament"])
    elif kind == "state":
        room, state = data["room"], data["state"]
        with lock:
            old = timers.pop(room, None)
            if old:
                old.cancel()
        play(ws, room, state)
    elif kind == "error":
        print("Subscription refused; check tournament enrollment and supported games.")


def opened(ws):
    print("Engine connected. Waiting for pushed challenges/positions.")
    ws.last_pong = time.monotonic()
    def heartbeat():
        while not stopped.wait(25) and ws.sock and ws.sock.connected:
            try:
                if time.monotonic() - ws.last_pong > 45:
                    ws.close()
                    return
                send(ws, {"type": "ping"})  # Exact JSON matches the runtime auto-response; no DO wake or D1 write.
            except websocket.WebSocketException:
                return
    threading.Thread(target=heartbeat, daemon=True).start()


def closed(ws, code, reason):
    with lock:
        for timer in timers.values():
            timer.cancel()
        timers.clear()
        pending.clear()
        rooms.clear()
        checked_in.clear()
    if code in (4001, 4003, 4004):
        stopped.set()  # Replaced, expired/revoked or banned: do not reconnect-loop.


def failed(ws, error):
    if stopped.is_set():
        ws.close()
        return
    if isinstance(error, websocket.WebSocketBadStatusException) and error.status_code in (301, 302, 303, 307, 308, 401, 403):
        print("Engine authentication refused; check the token and Access credentials.")
        stopped.set()
    else:
        print("Engine stream interrupted; reconnecting with backoff.")


try:
    backoff = 1
    while not stopped.is_set():
        client = websocket.WebSocketApp(base.replace("https:", "wss:", 1) + "/api/engine/ws", header=headers,
                                        on_open=opened, on_message=message, on_close=closed,
                                        on_error=failed)
        connected_at = time.monotonic()
        client.run_forever()  # No protocol ping timer; the application ping is answered without a DO wake.
        if time.monotonic() - connected_at > 60:
            backoff = 1
        stopped.wait(random.uniform(backoff / 2, backoff))
        backoff = min(30, backoff * 2)
except KeyboardInterrupt:
    stopped.set()
finally:
    stopped.set()
    if "client" in globals():
        client.close()
