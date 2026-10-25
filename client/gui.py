"""Local graphical UI for `hexbot --play --gui`: you against the bundled engine in your web browser.

A small HTTP server (stdlib only) on 127.0.0.1 serves one self-contained page (gui.html, bundled with the
executable) and a JSON API. The server is the authority: every rule goes through bprules, the page only
draws what /state returns and posts moves.

  GET  /        the page
  GET  /state   the whole game for the page (board, hands, scores, legal moves on your turn, log, ...)
  POST /move    {"move": "2@3,-1"}  play one action (placement N@q,r or edit A:k>B:k2)
  POST /hint    the engine's top moves for you
  POST /undo    take back your last turn (as in --play)
  POST /new     {"side": "blue|red|random", "level": "easy|normal|hard"} (both optional) start over
  POST /quit    save and stop the server (Ctrl+C in the terminal does the same)

POST bodies must be JSON (Content-Type: application/json); requests must use the 127.0.0.1/localhost host.
Games are saved like --play (~/.hexbot/games/local-<time>.json) and can be viewed with --replay.
"""
import json
import os
import random
import signal
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import advise as A
import bprules as P
import play

PAGE = "gui.html"
MAX_BODY = 64 * 1024


def page_bytes():
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (getattr(sys, "_MEIPASS", None), here):
        if base and os.path.isfile(os.path.join(base, PAGE)):
            with open(os.path.join(base, PAGE), "rb") as f:
                return f.read()
    raise SystemExit(f"--gui: {PAGE} is missing from this build")


def say(*parts):
    print(*parts, flush=True)


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


class GuiGame:
    """One local game at a time (a new game replaces it). All state changes happen under self.lock;
    the engine thinks in a background thread so the page stays responsive."""

    def __init__(self, engine, human, time_ms, level, build="dev"):
        self.engine = engine
        self.build = build
        self.lock = threading.RLock()
        self.epoch = 0          # bumped by undo/new: a thinking engine thread from an older epoch is discarded
        self.rev = 0            # bumped on every change the page should redraw
        self.game_no = 0
        self.g = None
        self.new(human, time_ms, level)

    # ------------------------------------------------------------------ lifecycle
    def new(self, human, time_ms, level):
        with self.lock:
            self.close()
            self.epoch += 1
            self.game_no += 1
            self.g = play.LocalGame(self.engine, human, time_ms, level=level, out=sys.stdout, color=False,
                                    build=self.build)
            self.rows = []          # move log: one row per ply
            self.saved = None       # path once saved (game over, new game or shutdown)
            self.thinking = False
            self.hint = None
            self._view = (None, None)
            self._threats = (None, None)
            lvl = f"{level}, " if level else ""
            say(f"New game: you play {play.H.SEAT_NAME[human]} ({lvl}{time_ms} ms per engine action).")
            self._bump()
            self._settle()

    def close(self):
        """Save an unfinished game (no-op when it was already saved or nothing was played)."""
        with self.lock:
            if self.g is None or self.saved is not None or not self.g.moves:
                return
            self.epoch += 1
            self.thinking = False
            view = self.view()
            sc = view["scores"]
            say(f"Game stopped at ply {view['ply']}: you {sc[self.g.human]} - engine {sc[self.g.bot]}.")
            self._save("abandoned", view["result"])

    def _save(self, verdict, res):
        path = self.g.save(verdict, res)
        self.saved = path or ""
        if path:
            say(f"Saved game to {path}\nView it again: add  --replay \"{path}\"  to the command you used.")

    # ------------------------------------------------------------------ state helpers
    def _bump(self):
        self.rev += 1

    def view(self):
        st = self.g.state
        if self._view[0] is not st:
            self._view = (st, P.to_view(st))
        return self._view[1]

    def danger(self, view):
        st = self.g.state
        if self._threats[0] is not st:
            self._threats = (st, sorted(A.threats(view, self.g.bot).keys()))
        return self._threats[1]

    def _push(self, move):
        pre = self.g.state
        seat = P.turn_of(pre["ply"])
        what = "pass" if move == "pass" else play.summarize(pre, move)
        self.g.push(move)
        sc = self.g.state["scores"]
        self.rows.append({"ply": pre["ply"], "seat": seat, "move": move, "what": what, "scores": list(sc)})
        who = "You play" if seat == self.g.human else "Engine plays"
        say(f"{who} {move}: {what}   (Blue {sc[0]} - Red {sc[1]})")
        self.hint = None
        self._bump()

    def _settle(self):
        """After any change: pass for a side with no legal moves, finish the game, or start the engine."""
        while True:
            view = self.view()
            if view["result"]:
                if self.saved is None and self.g.moves:
                    sc = view["scores"]
                    w = view["result"].get("winner")
                    verdict = "draw" if w is None else ("won" if w == self.g.human else "lost")
                    text = {"won": "YOU WIN", "lost": "ENGINE WINS", "draw": "DRAW"}[verdict]
                    say(f"GAME OVER: {text}  you ({play.H.SEAT_NAME[self.g.human]}) {sc[self.g.human]}"
                        f" - engine {sc[self.g.bot]}")
                    self._save(verdict, view["result"])
                    self._bump()
                return
            if not view["moves"]:
                self._push("pass")
                continue
            if view["turn"] == self.g.bot and not self.thinking:
                self.thinking = True
                self._bump()
                threading.Thread(target=self._engine_turn, args=(self.epoch,), daemon=True).start()
            return

    def _engine_turn(self, epoch):
        while True:
            with self.lock:
                if epoch != self.epoch:
                    return
                view = self.view()
                if view["result"] or view["turn"] != self.g.bot or not view["moves"]:
                    self.thinking = False
                    self._bump()
                    self._settle()
                    return
                state, time_ms = self.g.state, self.g.time_ms
            try:
                info = self.engine(view, time_ms) or {}
            except Exception as e:  # noqa: BLE001
                say(f"(engine error: {type(e).__name__}: {e}; using the simple fallback)")
                info = {}
            with self.lock:
                if epoch != self.epoch or self.g.state is not state:
                    return
                move = info.get("move")
                if move not in view["moves"]:
                    move = P.best_capture_move(view)
                if move not in view["moves"]:
                    move = random.choice(view["moves"])
                cells = A.describe(view, move)[2] if "@" in move else []
                self.g.last_engine_cells += cells
                self._push(move)

    # ------------------------------------------------------------------ API
    def snapshot(self):
        with self.lock:
            g = self.g
            view = self.view()
            over = bool(view["result"])
            my_turn = not over and view["turn"] == g.human and not self.thinking
            ply = view["ply"]
            can_undo = not over and any(P.turn_of(p) == g.human for p in range(ply))
            return {
                "rev": self.rev, "game": self.game_no, "ply": ply, "total": P.TOTAL_PLIES,
                "turn": view["turn"], "left": view["left"], "cells": view["cells"],
                "blueprints": view["blueprints"], "scores": view["scores"], "stars": view["stars"],
                "result": view["result"], "human": g.human, "bot": g.bot, "thinking": self.thinking,
                "myTurn": my_turn, "moves": view["moves"] if my_turn else [],
                "lastEngine": list(g.last_engine_cells), "danger": self.danger(view) if not over else [],
                "log": list(self.rows), "hint": self.hint, "canUndo": can_undo, "level": g.level,
                "timeMs": g.time_ms, "saved": self.saved, "build": self.build,
            }

    def move(self, move):
        with self.lock:
            view = self.view()
            if view["result"]:
                raise ApiError("The game is over; start a new game.", 409)
            if self.thinking or view["turn"] != self.g.human:
                raise ApiError("Wait for the engine to finish its turn.", 409)
            move = play._norm(str(move or ""))
            if move not in view["moves"]:
                raise ApiError("Not legal: " + play.explain_illegal(self.g.state, move))
            self.g.last_engine_cells = []
            self._push(move)
            self._settle()

    def undo(self):
        with self.lock:
            if self.view()["result"]:
                raise ApiError("The game is over; start a new game.", 409)
            if not self.g.undo():
                raise ApiError("Nothing to undo yet.", 409)
            self.epoch += 1
            self.thinking = False
            self.hint = None
            del self.rows[len(self.g.moves):]
            say(f"Took back your last turn (back to ply {self.g.state['ply']}).")
            self._bump()
            self._settle()

    def get_hint(self):
        with self.lock:
            view = self.view()
            if view["result"] or self.thinking or view["turn"] != self.g.human:
                raise ApiError("Hints are available on your turn.", 409)
            state, time_ms = self.g.state, self.g.time_ms
        info = self.engine(view, time_ms) or {}
        top = A.top_moves(view, dict(info), n=3)
        with self.lock:
            if self.g.state is not state:
                raise ApiError("The position changed while the engine was thinking.", 409)
            self.hint = [{"move": m, "what": play.summarize(state, m),
                          "cells": A.describe(view, m)[2] if "@" in m else []} for m, _ in top]
            self._bump()


def make_handler(game, page, port_ref, stop):
    class Handler(BaseHTTPRequestHandler):
        server_version = "hexbot-gui"
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # keep the terminal for game output
            pass

        def _host_ok(self):
            # Guards against DNS rebinding: only our own loopback origin may talk to the game.
            host = (self.headers.get("Host") or "").lower()
            port = port_ref[0]
            return host in (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")

        def _send(self, status, body, ctype):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj, separators=(",", ":")).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"ok": False, "error": "bad host"})
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/state":
                return self._json(200, game.snapshot())
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            return self._json(404, {"ok": False, "error": "not found"})

        do_HEAD = do_GET

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"ok": False, "error": "bad host"})
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                return self._json(413, {"ok": False, "error": "bad body"})
            raw = self.rfile.read(n) if n else b""
            if ctype != "application/json":   # forces a CORS preflight for any cross-site request
                return self._json(415, {"ok": False, "error": "send JSON (Content-Type: application/json)"})
            try:
                body = json.loads(raw.decode() or "{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"ok": False, "error": "body must be a JSON object"})
            path = self.path.split("?", 1)[0]
            try:
                if path == "/move":
                    game.move(body.get("move"))
                elif path == "/hint":
                    game.get_hint()
                elif path == "/undo":
                    game.undo()
                elif path == "/new":
                    side = str(body.get("side") or play.H.SEAT_NAME[game.g.human]).lower()
                    level = body.get("level")
                    if side not in ("blue", "red", "random") or level not in (None, "easy", "normal", "hard"):
                        raise ApiError("side must be blue/red/random and level easy/normal/hard")
                    human = random.randint(0, 1) if side == "random" else play.SEATS[side]
                    if level:
                        game.new(human, play.LEVELS[level], level)
                    else:
                        game.new(human, game.g.time_ms, game.g.level)
                elif path == "/quit":
                    game.close()
                    self._json(200, {"ok": True, "state": game.snapshot()})
                    stop()
                    return
                else:
                    return self._json(404, {"ok": False, "error": "not found"})
            except ApiError as e:
                return self._json(e.status, {"ok": False, "error": str(e), "state": game.snapshot()})
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            return self._json(200, {"ok": True, "state": game.snapshot()})

    return Handler


def open_browser(url):
    """Best effort; never blocks the terminal with a text-mode browser."""
    try:
        if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            with open("/proc/version") as f:
                wsl = "microsoft" in f.read().lower()
            if not wsl:
                return False
            subprocess.Popen(["cmd.exe", "/c", "start", "", url], cwd="/mnt/c" if os.path.isdir("/mnt/c") else None,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001
        return False


def serve(engine, human, time_ms, level=None, build="dev", port=0, browser=True):
    page = page_bytes()
    port_ref = [0]
    httpd = None

    def stop():
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    game = GuiGame(engine, human, time_ms, level, build=build)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(game, page, port_ref, stop))
    except OSError as e:
        raise SystemExit(f"--gui: cannot listen on 127.0.0.1:{port}: {e}")
    httpd.daemon_threads = True
    port_ref[0] = httpd.server_address[1]
    url = f"http://127.0.0.1:{port_ref[0]}/"
    say(f"Blueprints GUI running at {url}")
    say("Open that address in your browser if it does not open by itself. Ctrl+C here stops the game.")
    if browser and not open_browser(url):
        say("(could not open a browser automatically)")
    def on_term(signum, frame):
        raise KeyboardInterrupt
    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):   # closing the terminal / kill also save the game
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), on_term)
            except (OSError, ValueError):
                pass
    try:
        httpd.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        say("\nStopping the GUI server.")
    finally:
        game.close()
        httpd.server_close()
    say("GUI server stopped.")
