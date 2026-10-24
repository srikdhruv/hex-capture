#!/usr/bin/env python3
"""StrategyJam "Blueprints" engine client (tournament + standalone challenges + self-test games).

Based on reference/example_client.py (official protocol example). Safety behaviours kept:
no redirects (token never forwarded), app-level ping every 25s (reconnect if no pong in 45s),
reconnect with jittered exponential backoff, ply-guarded moves, re-read (re-watch) after
409/timeout/lost response instead of replaying, stop on close codes 4001/4003/4004 and on 401/403.

Env:
  STRATEGYJAM_TOKEN  (required, never logged)
  STRATEGYJAM_URL    (default https://strategyjam.org)
  TOURNAMENT_ID      (default f46b70969dee; set to "" or pass --no-tournament for challenges only)
  ENGINE_CMD         (default <repo>/engine/bp; falls back to node tools/greedy.mjs)
  MOVE_TIME_MS       (default 6500: target think time per action; increment is +15s per 2-action TURN)
  MAX_TIME_MS        (optional hard cap per action; same as --max-time-ms)
Emergency mode: with < 10s on our clock, think at most 1000ms; with < 2.5s, move instantly.

Usage:
  python3 client/bot.py [--dry-run] [--move-time-ms N] [--engine CMD] [--tournament ID | --no-tournament]
  python3 client/bot.py --selftest [N]      # offline: plays N plies locally through the same move pipeline
"""
import argparse
import json
import os
import random
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bprules  # noqa: E402  (pure-Python rules: offline self-test + no-dependency fallback policy)
import updater  # noqa: E402  (in-session auto-update of the packaged executable)
from updater import BUILD_SHA  # noqa: E402

FROZEN = getattr(sys, "frozen", False)          # running as the PyInstaller "hexbot" executable
BUNDLE = getattr(sys, "_MEIPASS", None)
HOME_DIR = os.path.join(os.path.expanduser("~"), ".hexbot")
TOKEN_FILE = os.path.join(HOME_DIR, "token")
EXE = ".exe" if os.name == "nt" else ""
GREEDY = os.path.join(REPO, "tools", "greedy.mjs")
BPCLI = os.path.join(REPO, "tools", "bpcli.mjs")
LOG_DIR = os.path.join(HOME_DIR, "logs") if FROZEN else os.path.join(HERE, "logs")
if FROZEN and not os.environ.get("SSL_CERT_FILE"):
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()  # bundled CA roots (python.org/macOS builds lack system certs)
    except ImportError:
        pass


def default_engine_path():
    cands = []
    if BUNDLE:
        cands.append(os.path.join(BUNDLE, "engine", "bp" + EXE))
    if FROZEN:
        cands.append(os.path.join(os.path.dirname(sys.executable), "bp" + EXE))
    cands.append(os.path.join(REPO, "engine", "bp" + EXE))
    for c in cands:
        if os.path.isfile(c):
            return c
    return cands[-1]


def node_available():
    from shutil import which
    return which("node") is not None and os.path.isfile(GREEDY)
DEFAULT_TOURNAMENT = "f46b70969dee"
CLOSE_STOP_CODES = (4001, 4003, 4004)

# ----------------------------------------------------------------------------- logging

_log_lock = threading.Lock()
_session = time.strftime("%Y%m%d-%H%M%S")


def log(*parts):
    line = time.strftime("%H:%M:%S ") + " ".join(str(p) for p in parts)
    with _log_lock:
        print(line, file=sys.stderr, flush=True)
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(os.path.join(LOG_DIR, f"bot-{_session}.log"), "a") as f:
                f.write(line + "\n")
        except OSError:
            pass


def jlog(room, record):
    """Append a JSON record to client/logs/<room>.jsonl (states, decisions, posts)."""
    record = {"t": round(time.time(), 3), "room": room, **record}
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(room or "none"))
        with _log_lock, open(os.path.join(LOG_DIR, f"game-{safe}.jsonl"), "a") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError:
        pass


# ----------------------------------------------------------------------------- clock / time management

_clock_logged = False
_clock_unit_ms = None  # decided from the first clock values seen


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _seat_value(obj, seat):
    """Pick a seat's value from list/dict shapes."""
    if isinstance(obj, list) and len(obj) > seat:
        v = obj[seat]
        if _num(v):
            return v
        if isinstance(v, dict):
            for k in ("remaining", "remainingMs", "left", "ms", "time", "timeLeft", "clock"):
                if _num(v.get(k)):
                    return v[k]
    if isinstance(obj, dict):
        for k in (str(seat), seat):
            if k in obj:
                return _seat_value([obj[k]], 0)
    return None


def my_clock_ms(state, seat):
    """Best-effort remaining time (ms) for `seat` at the moment the state was received; None if unknown."""
    global _clock_logged, _clock_unit_ms
    clock = state.get("clock")
    if not _clock_logged:
        _clock_logged = True
        log("clock shape (first seen):", json.dumps(clock)[:400])
    if clock is None:
        return None
    now_ms = time.time() * 1000
    # Absolute deadline for the side to move (epoch ms).
    if isinstance(clock, dict):
        for k in ("deadline", "deadlineAt", "endsAt", "expiresAt", "flagAt", "timeoutAt"):
            v = clock.get(k)
            if _num(v) and v > 1e12:
                return v - now_ms
            if isinstance(v, (list, dict)):
                sv = _seat_value(v, seat)
                if _num(sv) and sv > 1e12:
                    return sv - now_ms
    raw = None
    if isinstance(clock, (list, dict)):
        raw = _seat_value(clock, seat)
        if raw is None and isinstance(clock, dict):
            for k in ("remaining", "remainingMs", "left", "times", "ms", "time", "clocks", "seats", "players"):
                if k in clock:
                    raw = _seat_value(clock[k], seat)
                    if raw is not None:
                        break
    if raw is None:
        return None
    if _clock_unit_ms is None:
        _clock_unit_ms = raw > 1000
        log("clock unit decided:", "ms" if _clock_unit_ms else "s", "(raw", raw, ")")
    ms = raw if _clock_unit_ms else raw * 1000
    # If the clock is running for the side to move since a timestamp, subtract elapsed.
    if isinstance(clock, dict):
        for k in ("since", "startedAt", "turnStartedAt", "runningSince", "updatedAt", "at", "stamp"):
            v = clock.get(k)
            if _num(v) and 1e12 < v <= now_ms + 5000 and state.get("turn") == seat:
                ms -= max(0, now_ms - v)
                break
    return ms


EMERGENCY_CLOCK_MS = 10000  # below this remaining clock, think at most EMERGENCY_THINK_MS
EMERGENCY_THINK_MS = 1000


def think_budget_ms(remaining_ms, cap_ms, max_ms=None):
    """Time to give the engine for this action. Never risks a flag (timeout = pass)."""
    if max_ms:
        cap_ms = min(cap_ms, max_ms)
    if remaining_ms is None:
        return cap_ms
    if remaining_ms < EMERGENCY_CLOCK_MS:  # emergency mode
        return int(max(100, min(cap_ms, EMERGENCY_THINK_MS, remaining_ms - 3000)))
    usable = remaining_ms - 3000  # network + process startup + grace margin
    return int(max(100, min(cap_ms, usable * 0.45)))


# ----------------------------------------------------------------------------- move selection

def _engine_cmd(spec):
    cmd = shlex.split(spec) if spec else [default_engine_path()]
    if os.path.basename(cmd[0]).startswith("bp") and "--threads" not in cmd:
        cmd += ["--threads", str(max(1, (os.cpu_count() or 2) - 1))]
    return cmd


def _run_policy(cmd, state, time_ms, hard_timeout_s):
    t0 = time.monotonic()
    env = {k: v for k, v in os.environ.items() if k != "STRATEGYJAM_TOKEN"}  # the engine never sees the token
    proc = subprocess.run(cmd + ["--time-ms", str(int(time_ms))], input=json.dumps(state).encode(),
                          capture_output=True, timeout=hard_timeout_s, cwd=REPO if os.path.isdir(REPO) else None, env=env)
    out = proc.stdout.decode(errors="replace").strip().splitlines()
    if proc.returncode != 0 and not out:
        raise RuntimeError(f"exit {proc.returncode}: {proc.stderr.decode(errors='replace')[-300:]}")
    for line in reversed(out):
        line = line.strip()
        if line.startswith("{"):
            res = json.loads(line)
            res["_ms"] = int((time.monotonic() - t0) * 1000)
            return res
    raise RuntimeError("no JSON output; stderr: " + proc.stderr.decode(errors="replace")[-300:])


class Chooser:
    def __init__(self, engine_spec, cap_ms, max_ms=None):
        self.cmd = _engine_cmd(engine_spec)
        self.cap_ms = cap_ms
        self.max_ms = max_ms
        exe = self.cmd[0]
        if FROZEN and os.path.isfile(exe) and not os.access(exe, os.X_OK):
            try:
                os.chmod(exe, 0o755)
            except OSError:
                pass
        self.pv_cache = {}  # (room, ply) -> move predicted by the engine's PV for our next action
        self._warned = set()

    def engine_available(self):
        exe = self.cmd[0]
        if os.sep in exe:
            return os.path.isfile(exe) and os.access(exe, os.X_OK)
        from shutil import which
        return which(exe) is not None

    def choose(self, room, state, seat):
        """Returns (move, info dict). Always returns a legal move if any exist."""
        view = state["view"]
        moves = view.get("moves") or []
        legal = set(moves)
        ply = state.get("ply", view.get("ply"))
        remaining = my_clock_ms(state, seat)
        budget = think_budget_ms(remaining, self.cap_ms, self.max_ms)
        info = {"ply": ply, "clock_ms": None if remaining is None else int(remaining), "budget_ms": budget,
                "emergency": remaining is not None and remaining < EMERGENCY_CLOCK_MS}
        cached = self.pv_cache.pop((room, ply), None)
        if cached not in legal:
            cached = None

        # Panic: almost flagged. Play the cached PV move or anything legal instantly.
        if remaining is not None and remaining < 2500:
            move = cached or random.choice(moves)
            info.update(source="panic-pv" if cached else "panic-random")
            return move, info

        attempts = []
        if self.engine_available():
            attempts.append(("engine", self.cmd, budget, budget / 1000 + 1.5))
        elif "noengine" not in self._warned:
            self._warned.add("noengine")
            log("engine not found at", self.cmd[0], "- using fallback policy")
        if node_available():
            g_ms = max(100, min(1500, budget))
            attempts.append(("greedy", ["node", GREEDY], g_ms, g_ms / 1000 + 2.5))
        for name, cmd, t_ms, hard in attempts:
            if remaining is not None and hard * 1000 > remaining - 1500:
                hard = max(0.5, (remaining - 1500) / 1000)
            try:
                res = _run_policy(cmd, state, t_ms, hard)
            except subprocess.TimeoutExpired:
                log(f"[{room}] {name} timed out after {hard:.1f}s")
                continue
            except Exception as e:  # noqa: BLE001 - any policy failure falls through to the next one
                log(f"[{room}] {name} failed: {e}")
                continue
            move = res.get("move")
            if move in legal:
                pv = res.get("pv") or []
                if len(pv) >= 2 and pv[0] == move and view.get("left", 1) >= 2:
                    self.pv_cache[(room, ply + 1)] = pv[1]
                info.update(source=name, eval=res.get("eval"), pv=pv[:6], top=(res.get("top") or [])[:5],
                            policy_ms=res.get("_ms"))
                return move, info
            log(f"[{room}] {name} returned illegal/missing move {move!r}; trying fallback")
            for alt in res.get("top") or []:
                alt_move = alt.get("move") if isinstance(alt, dict) else (alt[0] if isinstance(alt, list) and alt else alt)
                if alt_move in legal:
                    info.update(source=name + "-top", eval=None)
                    return alt_move, info
        if cached:
            info.update(source="pv-cache")
            return cached, info
        move = bprules.best_capture_move(view)
        if move not in legal:
            move = random.choice(moves)
        info.update(source="py-fallback")
        return move, info


# ----------------------------------------------------------------------------- network client

class Bot:
    def __init__(self, base, token, tournament, chooser, dry_run=False, advise=False):
        self.base = base
        self.headers = {"Authorization": "Bearer " + token}
        for variable, header in [("CF_ACCESS_CLIENT_ID", "CF-Access-Client-Id"),
                                 ("CF_ACCESS_CLIENT_SECRET", "CF-Access-Client-Secret")]:
            if os.environ.get(variable):
                self.headers[header] = os.environ[variable]
        self.tournament = tournament
        self.chooser = chooser
        self.dry_run = dry_run or advise
        self.advise = advise     # human plays; we only print advice. Never POSTs anything.
        self.reminded = set()
        self.stopped = threading.Event()
        self.lock = threading.RLock()
        self.rooms = {}          # room -> tournament id (None for standalone); cleared on reconnect
        self.room_tid = {}       # persistent room -> tournament id (survives reconnects)
        self.latest = {}         # room -> latest pushed state
        self.events = {}         # room -> threading.Event (new state for worker)
        self.workers = {}        # room -> Thread
        self.pending = {}        # room -> ply we already POSTed (or are computing) for
        self.checked_in = set()
        self.logged_tournament_shape = False
        self.finished = set()
        self.room_round = {}     # room -> tournament round (for status lines)
        self.last_seen = {}      # room -> time of the last pushed state
        self.last_tstate = None  # last tournament state
        self.token = token       # kept only to hand to an updated process via env
        self.updater = updater.Updater(log)
        self.reexec_target = None
        self.watchdog_grace_s = 11.5  # engine hard-kill grace (1.5s) + 10s
        self.busy = set()        # rooms whose worker is computing/posting right now
        self.posted = {}         # room -> last ply we POSTed successfully
        self.turn_seen = {}      # (room, ply) -> first time we saw it was our turn (watchdog)
        self.fail_count = {}     # (room, ply) -> failed POSTs (switch move after repeated failures)
        self.ws = None

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, response_headers, newurl):
                return None  # Never forward a Bearer token to a login page or another origin.

        self.http = urllib.request.build_opener(NoRedirect)

    # --- HTTP (same semantics as the example: None => re-read, never replay)
    def call(self, path, body, method="POST"):
        if self.advise and method != "GET":
            log(f"advise mode: refusing to send {method} {path}")
            return None
        data = None if method == "GET" else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={**self.headers, "Content-Type": "application/json"})
        try:
            with self.http.open(request, timeout=15) as response:
                raw = response.read()
                try:
                    return json.loads(raw) if raw else {}
                except ValueError:
                    return {}
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                self.stopped.set()
                log(f"HTTP {error.code} on {path}: token expired/revoked or enrollment/supported-games problem. Stopping."
                    + (" (saved token: run with --forget-token, then paste a new one)" if os.path.isfile(TOKEN_FILE) else ""))
                if self.ws:
                    try:
                        self.ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                return None
            if error.code in (429, 503):
                raw = error.headers.get("Retry-After", "2")
                try:
                    seconds = max(2, float(raw))
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    seconds = max(2, parsedate_to_datetime(raw).timestamp() - time.time())
                log(f"HTTP {error.code} on {path}; waiting {seconds:.1f}s")
                if self.stopped.wait(seconds):
                    return None
            elif error.code == 409:
                log(f"HTTP 409 on {path} (stale ply / already moved); re-reading board")
            else:
                try:
                    detail = error.read()[:200].decode(errors="replace")
                except Exception:  # noqa: BLE001
                    detail = ""
                log(f"HTTP {error.code} on {path}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log(f"request error on {path}: {type(e).__name__}; re-reading board")
        return None  # May already have committed: request a new pushed snapshot, never replay a move.

    # --- websocket helpers
    def send(self, message):
        ws = self.ws
        if not self.stopped.is_set() and ws is not None and ws.sock and ws.sock.connected:
            try:
                ws.send(json.dumps(message, separators=(",", ":")))
            except Exception as e:  # noqa: BLE001
                log("send failed:", type(e).__name__)

    def watch(self, room, tournament_id=None):
        with self.lock:
            self.rooms[room] = tournament_id
            if tournament_id or room not in self.room_tid:
                self.room_tid[room] = tournament_id
        self.send({"type": "watch-game", "room": room, **({"tournament": tournament_id} if tournament_id else {})})

    # --- per-room worker: computes off the websocket thread so pings/pongs keep flowing
    def on_state(self, room, state):
        jlog(room, {"type": "state", "state": state})
        view = state.get("view") or {}
        self.last_seen[room] = time.time()
        if view.get("result") and room not in self.finished:
            self.finished.add(room)
            log(self.game_summary(room, state))
        with self.lock:
            old = self.latest.get(room)
            if old is not None and (old.get("ply") or 0) > (state.get("ply") or 0) and not view.get("result"):
                return  # stale snapshot delivered out of order; keep the newer one
            self.latest[room] = state
            ev = self.events.get(room)
            if ev is None:
                ev = self.events[room] = threading.Event()
                t = threading.Thread(target=self.worker, args=(room,), daemon=True, name=f"room-{room}")
                self.workers[room] = t
                t.start()
            ev.set()

    def _advise(self, room, state):
        import advise
        view = state.get("view") or {}
        you = state.get("you") or []
        turn = state.get("turn", view.get("turn"))
        ply = state.get("ply", view.get("ply"))
        if view.get("result") or not view.get("moves"):
            return
        rnd = self.room_round.get(room)
        where = f"Round {rnd}" if rnd is not None else f"Game {str(room)[:8]}"
        with self.lock:
            if self.pending.get(room) == ply:
                return
            self.pending[room] = ply
        sc = view.get("scores") or [0, 0]
        if turn not in you:
            print(f"\n{where} | ply {ply}/120 | opponent ({'Blue' if turn == 0 else 'Red'}) to move | "
                  f"Blue {sc[0]} - Red {sc[1]}", flush=True)
            return
        move, info = self.chooser.choose(room, state, turn)
        with self.lock:
            newest = self.latest.get(room)
        if (newest or {}).get("ply") != ply:
            return  # you already moved; the next state brings fresh advice
        try:
            text = advise.render(view, turn, dict(info, move=move),
                                 header=f"===== {where} | YOUR TURN ({'Blue' if turn == 0 else 'Red'}) | ply {ply}/120 =====",
                                 clock_ms=info.get("clock_ms"))
        except Exception as e:  # noqa: BLE001
            text = f"{where} ply {ply}: suggested move {move} (render error {type(e).__name__})"
        print("\n" + text + "\n(advice only: play your move on strategyjam.org)", flush=True)
        jlog(room, {"type": "advice", "ply": ply, "move": move, **info})

    def game_summary(self, room, state):
        view = state.get("view") or {}
        res = view.get("result") or {}
        sc = view.get("scores") or [0, 0]
        you = state.get("you") or []
        rnd = self.room_round.get(room)
        where = f"Round {rnd}" if rnd is not None else f"Game {str(room)[:8]}"
        if len(you) != 1:
            return f"GAME OVER {where}: Blue {sc[0]} - Red {sc[1]} ({res.get('reason', '')})"
        me = you[0]
        colour = "Blue" if me == 0 else "Red"
        winner = res.get("winner") if isinstance(res, dict) else None
        verdict = "DRAW" if winner is None else ("WON" if winner == me else "LOST")
        return (f"GAME OVER {where}: we played {colour} and {verdict} {sc[me]}-{sc[1 - me]} "
                f"({res.get('reason', '') if isinstance(res, dict) else res})")

    def watchdog(self):
        """If it's our turn on a live board and nothing was POSTed within budget + 10s, re-read and act."""
        while not self.stopped.wait(2):
            now = time.time()
            limit = (min(self.chooser.cap_ms, self.chooser.max_ms or 10 ** 9) / 1000) + self.watchdog_grace_s
            stuck = []
            with self.lock:
                for room, st in self.latest.items():
                    view = st.get("view") or {}
                    ply = st.get("ply", view.get("ply"))
                    if view.get("result") or st.get("turn") not in (st.get("you") or []) or not view.get("moves"):
                        continue
                    if self.posted.get(room) == ply or room in self.busy:
                        continue
                    start = max(now, (st.get("startsAt") or 0) / 1000)
                    seen = self.turn_seen.setdefault((room, ply), start)
                    if now - seen > limit:
                        stuck.append((room, ply))
                        self.turn_seen[(room, ply)] = now  # re-arm
            for room, ply in stuck:
                self.rescue(room, ply)

    def rescue(self, room, ply):
        tid = self.room_tid.get(room)
        log(f"[{room}] watchdog: our turn at ply {ply} but no move sent; re-reading the board")
        jlog(room, {"type": "watchdog", "ply": ply})
        with self.lock:
            if self.pending.get(room) == ply:
                self.pending.pop(room, None)
        fresh = None
        if tid and not self.dry_run:
            data = self.call(f"/api/engine/tournaments/{tid}/game", None, method="GET")
            if isinstance(data, dict):
                if data.get("view"):
                    fresh = data
                elif isinstance(data.get("state"), dict) and data["state"].get("view"):
                    fresh = data["state"]
                    room = data.get("room") or room
                elif isinstance(data.get("game"), dict) and data["game"].get("view"):
                    fresh = data["game"]
        if fresh:
            self.on_state(room, fresh)
        else:
            self.watch(room, tid)
            with self.lock:
                ev = self.events.get(room)
            if ev:
                ev.set()

    def worker(self, room):
        ev = self.events[room]
        while not self.stopped.is_set():
            ev.wait(30)
            if self.stopped.is_set():
                return
            if not ev.is_set():
                continue
            ev.clear()
            with self.lock:
                state = self.latest.get(room)
            if state:
                try:
                    self.play(room, state)
                except Exception as e:  # noqa: BLE001 - never kill the worker
                    log(f"[{room}] play error: {type(e).__name__}: {e}")
                    with self.lock:
                        self.pending.pop(room, None)

    def play(self, room, state):
        with self.lock:
            self.busy.add(room)
        try:
            self._play(room, state)
        finally:
            with self.lock:
                self.busy.discard(room)

    def _play(self, room, state):
        if self.advise:
            return self._advise(room, state)
        view = state.get("view") or {}
        you = state.get("you") or []
        turn = state.get("turn", view.get("turn"))
        ply = state.get("ply", view.get("ply"))
        if view.get("result") or turn not in you or not view.get("moves"):
            return
        with self.lock:
            if self.pending.get(room) == ply:
                return
            self.pending[room] = ply
        delay = max(0.0, ((state.get("startsAt") or 0) - time.time() * 1000) / 1000)
        if delay:
            log(f"[{room}] game starts in {delay:.1f}s; waiting")
            if self.stopped.wait(delay + 0.1):
                return
        move, info = self.chooser.choose(room, state, turn)
        fails = self.fail_count.get((room, ply), 0)
        if fails >= 2:  # same ply rejected twice: don't loop on one move, try a different legal move
            alts = [m for m in view["moves"] if m != move]
            if alts:
                move = bprules.best_capture_move(dict(view, moves=alts))
                info.update(source=f"retry-{fails}")
        with self.lock:
            newest = self.latest.get(room)
        if newest is not state and (newest or {}).get("ply") != ply:
            log(f"[{room}] state moved on (ply {ply} -> {(newest or {}).get('ply')}); discarding computed move")
            with self.lock:
                if self.pending.get(room) == ply:
                    self.pending.pop(room, None)
            self.events[room].set()
            return
        tid = self.room_tid.get(room)
        jlog(room, {"type": "decision", "ply": ply, "seat": turn, "move": move, **info, "dry_run": self.dry_run})
        sc = view.get("scores") or [0, 0]
        rnd = self.room_round.get(room)
        where = f"Round {rnd}" if rnd is not None else ("Game " + str(room)[:8])
        colour = "Blue" if turn == 0 else "Red"
        log(f"{where} | {colour} | ply {ply}/120 (action {3 - (view.get('left') or 1) if ply else 1}) | move {move} | "
            f"score Blue {sc[0]} - Red {sc[1]} | via {info.get('source')} eval={info.get('eval')} "
            f"clock={info.get('clock_ms')}ms think={info.get('budget_ms')}ms")
        if self.dry_run:
            with self.lock:
                self.posted[room] = ply  # nothing is sent in dry-run; keep the watchdog quiet
            return
        path = f"/api/engine/tournaments/{tid}" if tid else f"/api/engine/games/{room}"
        result = self.call(path + "/move", {"ply": ply, "move": move})
        jlog(room, {"type": "post", "ply": ply, "move": move, "ok": result is not None})
        if result is not None:
            with self.lock:
                self.pending[room] = ply  # keep the guard even if a reconnect cleared it mid-move
                self.posted[room] = ply
        else:
            with self.lock:
                self.fail_count[(room, ply)] = fails + 1
                if self.pending.get(room) == ply:
                    self.pending.pop(room, None)
            self.watch(room, tid)  # re-read the board via a fresh pushed snapshot

    # --- websocket callbacks
    def on_message(self, ws, raw):
        try:
            data = json.loads(raw)
        except ValueError:
            return
        kind = data.get("type")
        if kind == "pong":
            ws.last_pong = time.monotonic()
            return
        if kind == "ready":
            log("stream ready")
            if self.tournament:
                self.send({"type": "watch-tournament", "tournament": self.tournament})
        elif kind == "inbox":
            for job in data.get("games") or []:
                log("inbox game:", job.get("room"))
                self.watch(job["room"], job.get("tournament"))
        elif kind == "challenge":
            log("challenge / self-test game:", data.get("room"))
            self.watch(data["room"])
        elif kind == "tournament":
            self.on_tournament(data)
        elif kind == "state":
            self.on_state(data["room"], data["state"])
        elif kind == "error":
            log("server error message:", json.dumps(data)[:300],
                "- check tournament enrollment and supported games (Blueprints)")
        else:
            log("unknown message type:", kind)

    def on_tournament(self, data):
        state = data.get("state") or {}
        tid = data.get("tournament")
        if not self.logged_tournament_shape:
            self.logged_tournament_shape = True
            log("tournament state:", json.dumps({k: v for k, v in state.items() if k != "standings"})[:600])
        jlog(f"tournament-{tid}", {"type": "tournament", "state": state})
        self.last_tstate = state
        key = (tid, state.get("round"))
        if state.get("status") == "playing" and state.get("active") and not state.get("withdrawn"):
            closes = state.get("closesAt")
            window_open = (closes or 0) > time.time() * 1000  # same rule as the official example
            if not state.get("checkedIn") and key not in self.checked_in and window_open:
                self.checked_in.add(key)
                if self.advise:
                    if key not in self.reminded:
                        self.reminded.add(key)
                        log(f">>> Round {key[1]} check-in is OPEN: check in yourself on strategyjam.org "
                            f"(advise mode never checks in or moves for you) <<<")
                elif self.dry_run:
                    log(f"[dry-run] would check in for round {key[1]}")
                else:
                    threading.Thread(target=self.check_in, args=(tid, key, closes), daemon=True).start()
            job = state.get("game")
            if job and job.get("ready") and job.get("room") and job.get("round") == state.get("round"):
                with self.lock:
                    already = job["room"] in self.rooms
                if not already:
                    log(f"round {state.get('round')}: watching board {job['room']}")
                    self.room_round[job["room"]] = state.get("round")
                    self.watch(job["room"], tid)
        elif state.get("status") and state.get("status") != "playing":
            log("tournament status:", state.get("status"))

    def check_in(self, tid, key, closes):
        """Check in for a round off the websocket thread; retry while the window is open, then re-read."""
        for attempt in range(1, 7):
            log(f"checking in for round {key[1]} (attempt {attempt})")
            if self.call(f"/api/engine/tournaments/{tid}/check-in", {}) is not None:
                log(f"checked in for round {key[1]}")
                return
            if self.stopped.is_set() or (closes is not None and closes - time.time() * 1000 < 3000):
                break
            if self.stopped.wait(min(5, 1.5 * attempt)):
                return
        self.checked_in.discard(key)
        self.send({"type": "watch-tournament", "tournament": tid})  # re-read; a new push retries

    def on_open(self, ws):
        log("engine connected; waiting for pushed challenges/positions",
            f"(tournament={self.tournament or '-'}, dry_run={self.dry_run})")
        ws.last_pong = time.monotonic()

        def heartbeat():
            import websocket
            while not self.stopped.wait(25) and ws.sock and ws.sock.connected:
                try:
                    if time.monotonic() - ws.last_pong > 45:
                        log("no pong for 45s; reconnecting")
                        ws.close()
                        return
                    self.send({"type": "ping"})
                except websocket.WebSocketException:
                    return
        threading.Thread(target=heartbeat, daemon=True).start()

    def on_close(self, ws, code, reason):
        log(f"stream closed code={code} reason={reason!r}")
        with self.lock:
            self.pending.clear()
            self.rooms.clear()
            self.checked_in.clear()
        if code in CLOSE_STOP_CODES:
            log("closed with", code, "(replaced / expired-revoked / banned): not reconnecting")
            self.stopped.set()

    def on_error(self, ws, error):
        import websocket
        if self.stopped.is_set():
            ws.close()
            return
        if isinstance(error, websocket.WebSocketBadStatusException) and error.status_code in (301, 302, 303, 307, 308, 401, 403):
            log("engine authentication refused (HTTP", error.status_code, "); check the token. Stopping.")
            self.stopped.set()
        else:
            log("engine stream interrupted:", type(error).__name__, "- reconnecting with backoff")

    def game_in_progress(self):
        """True while any of our games is unfinished (or our next board is ready but not yet seen)."""
        now = time.time()
        with self.lock:
            for room, st in self.latest.items():
                if not (st.get("view") or {}).get("result") and st.get("you") and now - self.last_seen.get(room, 0) < 900:
                    return True
            t = self.last_tstate or {}
            job = t.get("game") or {}
            if job.get("ready") and job.get("room") and job.get("round") == t.get("round") and job["room"] not in self.finished:
                seen = self.latest.get(job["room"])
                if seen is None or not (seen.get("view") or {}).get("result"):
                    return True
        return False

    def update_loop(self):
        """Poll for a newer release every ~2 minutes, only between games; never update mid-game."""
        if self.stopped.wait(15):
            return
        installed = None
        while not self.stopped.is_set():
            try:
                if not self.game_in_progress():
                    if installed is None:
                        sha = self.updater.newer_available()
                        if sha and not self.game_in_progress():
                            exe = self.updater.install(sha)
                            if exe:
                                installed = (exe, sha)
                    if installed and not self.game_in_progress():
                        log(f"updated to {installed[1]}; restarting with the same settings")
                        self.reexec_target = installed[0]
                        self.stopped.set()
                        if self.ws is not None:
                            self.ws.close()
                        return
            except Exception as e:  # noqa: BLE001 - the updater must never take the bot down
                log("update loop error:", type(e).__name__, e)
            self.stopped.wait(120)

    def run(self):
        import websocket
        if self.updater.enabled():
            threading.Thread(target=self.update_loop, daemon=True, name="updater").start()
        if not self.advise:
            threading.Thread(target=self.watchdog, daemon=True, name="watchdog").start()
        backoff = 1
        try:
            while not self.stopped.is_set():
                self.ws = websocket.WebSocketApp(self.base.replace("https:", "wss:", 1) + "/api/engine/ws",
                                                 header=self.headers, on_open=self.on_open,
                                                 on_message=self.on_message, on_close=self.on_close,
                                                 on_error=self.on_error)
                connected_at = time.monotonic()
                self.ws.run_forever()
                if time.monotonic() - connected_at > 60:
                    backoff = 1
                self.stopped.wait(random.uniform(backoff / 2, backoff))
                backoff = min(30, backoff * 2)
        except KeyboardInterrupt:
            log("interrupted")
        finally:
            self.stopped.set()
            if self.ws is not None:
                self.ws.close()


# ----------------------------------------------------------------------------- offline self-test

def bpcli(req):
    out = subprocess.run(["node", BPCLI], input=json.dumps(req).encode(), capture_output=True, timeout=60, cwd=REPO)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode()[-500:])
    return json.loads(out.stdout)


def selftest(chooser, plies, show_advice=False):
    """Play `plies` plies locally (both seats) through Chooser with a simulated server state + clock."""
    moves, clock = [], [60000, 60000]
    game = bprules.setup()
    for _ in range(plies):
        view = bprules.to_view(game)
        if view.get("result") or not view["moves"]:
            break
        seat = view["turn"]
        state = {"you": [seat], "turn": seat, "ply": view["ply"], "view": view,
                 "clock": {"remaining": list(clock), "increment": 15000}, "startsAt": None}
        jlog("selftest", {"type": "state", "state": state})
        t0 = time.monotonic()
        move, info = chooser.choose("selftest", state, seat)
        used = int((time.monotonic() - t0) * 1000)
        clock[seat] = clock[seat] - used + 15000
        assert move in view["moves"], move
        jlog("selftest", {"type": "decision", "ply": view["ply"], "move": move, **info})
        if show_advice:
            import advise
            print(advise.render(view, seat, dict(info, move=move), header=f"== selftest advice ply {view['ply']} =="), flush=True)
        log(f"ply {view['ply']:3d} seat {seat} -> {move:14s} via {info.get('source'):8s} eval={info.get('eval')} "
            f"used={used}ms clock={clock[seat]}ms scores={view['scores']} stars={view['stars']}")
        moves.append(move)
        game = bprules.play(game, move)
    final = bprules.to_view(game)
    log("selftest done:", len(moves), "plies; scores", final["scores"], "stars", final["stars"], "result", final["result"])
    log("moves:", " ".join(moves))


def get_token(args):
    """Token from STRATEGYJAM_TOKEN, else ~/.hexbot/token (only if saved with --save-token), else a hidden prompt."""
    token = os.environ.get("STRATEGYJAM_TOKEN", "").strip()
    saved = False
    if not token and os.path.isfile(TOKEN_FILE):
        try:
            with open(TOKEN_FILE) as f:
                token = f.read().strip()
            saved = bool(token)
            if saved:
                log("using saved token from ~/.hexbot/token (run with --forget-token to delete it)")
        except OSError:
            token = ""
    if not token:
        import getpass
        print("\nStrategyJam engine token needed. Get one at https://strategyjam.org: profile -> supported games ->\n"
              "select Blueprints -> Connect engine. It is shown once and lasts 24h.", file=sys.stderr, flush=True)
        while not token:
            try:
                token = getpass.getpass("Paste token (input hidden), then Enter: ").strip()  # reads the TTY, not stdin
            except (EOFError, KeyboardInterrupt):
                raise SystemExit("\nNo token given.")
    if args.save_token and not saved:
        os.makedirs(HOME_DIR, exist_ok=True)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token)
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError:
            pass
        log("token saved to ~/.hexbot/token (permissions 0600)")
    return token


def detect_tournament(base):
    """Find the live/upcoming Blueprints tournament from the public list; None if not found."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        req = urllib.request.Request(base + "/api/tournaments", headers={"Accept": "application/json", "User-Agent": "hexbot"})
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            data = json.load(r)
    except Exception as e:  # noqa: BLE001
        log("tournament auto-detect failed:", type(e).__name__)
        return None
    items = data if isinstance(data, list) else next((data[k] for k in ("tournaments", "items", "data", "results")
                                                       if isinstance(data, dict) and isinstance(data.get(k), list)), [])
    rank = {"playing": 0, "running": 0, "active": 0, "live": 0, "checkin": 1, "check-in": 1,
            "upcoming": 2, "registration": 2, "open": 2, "scheduled": 2, "pending": 2}
    best = None
    for t in items:
        if not isinstance(t, dict):
            continue
        game = t.get("game") or t.get("gameId") or t.get("slug") or ""
        if isinstance(game, dict):
            game = game.get("slug") or game.get("id") or game.get("name") or ""
        if "blueprints" not in str(game).lower():
            continue
        r = rank.get(str(t.get("status", "")).lower())
        tid = t.get("id") or t.get("tournament") or t.get("slug")
        if r is None or not tid:
            continue
        if best is None or r < best[0]:
            best = (r, str(tid), t.get("name") or t.get("title") or "", t.get("status"))
    if best:
        log(f"tournament auto-detected: {best[1]} {best[2]!r} ({best[3]})")
        return best[1]
    log("no playing/upcoming Blueprints tournament found in /api/tournaments")
    return None


def main():
    if "--version" in sys.argv[1:]:
        print(BUILD_SHA)
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--advise", action="store_true",
                    help="advice only: you play manually (no Engine label); never checks in or posts moves")
    ap.add_argument("--dry-run", action="store_true", help="compute and log moves but never POST (no check-in, no moves)")
    ap.add_argument("--move-time-ms", type=int, default=int(os.environ.get("MOVE_TIME_MS", "6500")),
                    help="target think time per action (default 6500)")
    ap.add_argument("--max-time-ms", type=int, default=int(os.environ.get("MAX_TIME_MS", "0")) or None,
                    help="hard cap on think time per action, overrides everything else")
    ap.add_argument("--engine", default=os.environ.get("ENGINE_CMD"), help="engine command (default <repo>/engine/bp)")
    ap.add_argument("--tournament", default=os.environ.get("TOURNAMENT_ID"),
                    help="tournament id (default: auto-detect the live Blueprints tournament)")
    ap.add_argument("--save-token", action="store_true", help="store the token in ~/.hexbot/token (0600) for next time")
    ap.add_argument("--forget-token", action="store_true", help="delete ~/.hexbot/token and exit")
    ap.add_argument("--version", action="store_true", help="print the build sha and exit")
    ap.add_argument("--no-update", action="store_true", help="disable in-session auto-update (env HEXBOT_NO_UPDATE=1)")
    ap.add_argument("--self-update", action="store_true", help="update the packaged executable now (if newer) and exit")
    ap.add_argument("--no-tournament", action="store_true", help="only standalone challenges / self-test games")
    ap.add_argument("--selftest", type=int, nargs="?", const=12, default=None, metavar="PLIES",
                    help="offline: play PLIES plies locally through the move pipeline (no network)")
    args = ap.parse_args()
    if args.no_update:
        os.environ["HEXBOT_NO_UPDATE"] = "1"
    updater.cleanup_old()
    if os.environ.get("HEXBOT_UPDATED_FROM"):
        log(f"updated to {BUILD_SHA} (from {os.environ.pop('HEXBOT_UPDATED_FROM')[:12]})")
    else:
        log(f"hexbot build {BUILD_SHA[:12]}")
    if args.self_update:
        up = updater.Updater(log)
        sha = up.newer_available() if updater.FROZEN else None
        if not sha:
            print(f"up to date ({BUILD_SHA[:12]})" if updater.FROZEN else "not a packaged build; nothing to update")
            return
        exe = up.install(sha)
        if exe:
            print(f"updated to {sha}")
            updater.reexec(exe, ["--version"], None, BUILD_SHA)
        raise SystemExit(1)
    if args.forget_token:
        try:
            os.remove(TOKEN_FILE)
            print("deleted ~/.hexbot/token")
        except FileNotFoundError:
            print("no saved token")
        return

    chooser = Chooser(args.engine, args.move_time_ms, args.max_time_ms)
    log(f"engine: {' '.join(chooser.cmd)} ({'found' if chooser.engine_available() else 'MISSING -> greedy fallback'}); "
        f"think {args.move_time_ms}ms/action, hard cap {args.max_time_ms or '-'}ms, "
        f"emergency {EMERGENCY_THINK_MS}ms below {EMERGENCY_CLOCK_MS // 1000}s")
    if args.selftest is not None:
        selftest(chooser, args.selftest, show_advice=args.advise)
        return

    base = os.environ.get("STRATEGYJAM_URL", "https://strategyjam.org").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise SystemExit("Use a plain HTTPS StrategyJam origin in STRATEGYJAM_URL")
    try:
        import websocket  # noqa: F401
    except ImportError:
        raise SystemExit("pip install websocket-client  (or use client/.venv/bin/python)")
    token = get_token(args)
    tournament = None
    if not args.no_tournament:
        tournament = args.tournament or detect_tournament(base) or DEFAULT_TOURNAMENT
        log("tournament:", tournament, "(override with TOURNAMENT_ID or --tournament; --no-tournament for challenges only)")
    if args.advise:
        if os.name == "nt":
            os.system("")  # enable ANSI colours in the Windows console
        chooser.cap_ms = int(os.environ.get("ADVISE_TIME_MS", "5000"))
        print("ADVICE ONLY: hexbot will never check in or send moves, so your entry keeps no Engine label.\n"
              "Check in yourself on strategyjam.org every round and play the moves you choose.", flush=True)
    bot = Bot(base, token, tournament, chooser, dry_run=args.dry_run, advise=args.advise)
    bot.run()
    if bot.reexec_target:
        updater.reexec(bot.reexec_target, sys.argv[1:], token, BUILD_SHA)


if __name__ == "__main__":
    main()
