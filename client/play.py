"""Local terminal game for `hexbot --play`: you against the bundled engine. No network, no account, no token.

Rules come from bprules (the Python port of the official rules); the engine is called through a function
supplied by bot.py, so tests can plug in a fake one. Finished (or abandoned) games are saved to
~/.hexbot/games/local-<time>.json and can be viewed again with `hexbot --replay FILE`.
"""
import json
import os
import random
import re
import sys
import time

import advise as A
import bprules as P
import hexrender as H

LEVELS = {"easy": 500, "normal": 3000, "hard": 8000}
SEATS = {"blue": 0, "red": 1}

HELP = """\
Blueprints: hex board, 120 plies. Blue opens with 1 action; after that every turn is 2 actions.
An action either PLACES one of your 3 blueprints on the board or EDITS your blueprints.
  Place  N@q,r      stamp blueprint #N so its (0,0) cell lands on hex q,r, e.g. 2@3,-1. Every cell must
                    land on an empty hex and at least one must touch one of your pieces.
  Edit   A:k>B:k2   move the cell at key k of blueprint #A to key k2 of #B, e.g. 1:0,1>2:2,0 (keys are
                    listed under each hand as key=kind). Blueprints must stay connected; keys renumber.
A placement removes every enemy star or plain piece touching the stamped cells (walls are safe). Each
enemy star removed scores as many points as you have stars on the board. Highest score at ply 120 wins.
Board: B/R = Blue/Red, * star, w wall, o plain; empty hexes show q, rows show r; ! = your star in danger.
Commands: <move> | moves [filter] (e.g. moves 2@, moves 1:, moves cap) | hint | undo | help | quit"""

PLACE_RE = re.compile(r"^(\d+)@(-?\d+),(-?\d+)$")
EDIT_RE = re.compile(r"^(\d+):(-?\d+),(-?\d+)>(\d+):(-?\d+),(-?\d+)$")


def games_dir():
    return os.path.join(os.path.expanduser("~"), ".hexbot", "games")


def _norm(s):
    return re.sub(r"\s+", "", s.strip().lower())


def explain_illegal(state, move):
    """Short reason why `move` is not legal for the side to move."""
    seat = P.turn_of(state["ply"])
    hand = state["blueprints"][seat]
    m = PLACE_RE.match(move)
    if m:
        i = int(m.group(1))
        if not 1 <= i <= len(hand) or not hand[i - 1]:
            return f"there is no blueprint #{i} with cells (you have #1..#{len(hand)})"
        at = (int(m.group(2)), int(m.group(3)))
        stamped, _ = P.stamp(state["cells"], seat, hand[i - 1], at)
        busy = [k for k, _ in stamped if k in state["cells"]]
        if busy:
            return f"hex {busy[0]} is already occupied"
        return "none of its cells would touch one of your pieces"
    m = EDIT_RE.match(move)
    if m:
        a, b = int(m.group(1)), int(m.group(4))
        if not (1 <= a <= len(hand) and 1 <= b <= len(hand)):
            return f"blueprints are numbered #1..#{len(hand)}"
        k = f"{int(m.group(2))},{int(m.group(3))}"
        if k not in hand[a - 1]:
            return f"blueprint #{a} has no cell {k} (keys: {H.bp_keys(hand[a - 1]) or 'none'})"
        return f"the target key must be empty and next to #{b}'s cells, and #{a} must stay connected"
    return "unknown command or move; type 'help'"


def summarize(state, move):
    """'+4 pts, captures 1 star(s)' / 'edit blueprint' for a move by the side to move."""
    if "@" not in move:
        return "edit blueprint"
    pts, caught, _ = A.describe(P.to_view(state), move)
    return f"+{pts} pts, captures {caught} star(s)" if caught else "placed, no capture"


class LocalGame:
    def __init__(self, engine, human, time_ms, level=None, inp=None, out=None, color=None, build="dev"):
        self.engine = engine            # engine(view, time_ms) -> {"move", "top", "source", ...}
        self.human = human
        self.bot = 1 - human
        self.time_ms = time_ms
        self.level = level
        self.inp = inp or sys.stdin
        self.out = out or sys.stdout
        self.color = H.use_color(color) if out is None else bool(color)
        self.st = H.Style(self.color)
        self.build = build
        self.states = [P.setup()]
        self.moves = []
        self.last_engine_cells = []
        self.started = time.strftime("%Y%m%d-%H%M%S")

    # ------------------------------------------------------------------ io
    def say(self, *parts):
        print(*parts, file=self.out, flush=True)

    def ask(self, prompt):
        """One line of input; None on EOF/Ctrl+C."""
        try:
            if self.inp is sys.stdin and sys.stdin.isatty():
                return input(prompt)
            self.out.write(prompt)
            self.out.flush()
            line = self.inp.readline()
            if not line:
                self.say()
                return None
            self.say(line.rstrip("\r\n"))   # echo scripted input so logs read like a session
            return line
        except (EOFError, KeyboardInterrupt):
            self.say()
            return None

    # ------------------------------------------------------------------ state
    @property
    def state(self):
        return self.states[-1]

    def push(self, move):
        self.states.append(P.play(self.state, move))
        self.moves.append(move)

    def undo(self):
        """Back to the start of our most recent turn (the current one if we already acted in it)."""
        ply = self.state["ply"]
        starts = [p for p in range(ply) if P.turn_of(p) == self.human and (p == 0 or P.turn_of(p - 1) != self.human)]
        if not starts:
            return False
        p = starts[-1]
        del self.states[p + 1:]
        del self.moves[p:]
        self.last_engine_cells = []
        return True

    # ------------------------------------------------------------------ display
    def name(self, seat):
        return "You" if seat == self.human else "Engine"

    def show(self, view):
        st = self.st
        danger = A.threats(view, self.bot)
        self.say()
        self.say(H.render_board(view["cells"], self.color, danger=danger.keys(), highlight=self.last_engine_cells))
        if self.last_engine_cells:
            self.say(st.dim("  + = cells the engine just placed"))
        sc, stars = view["scores"], view["stars"]
        self.say(st.seat(0, f"Blue ({self.name(0)}) {sc[0]} pts, {stars[0]} stars", True) + "   "
                 + st.seat(1, f"Red ({self.name(1)}) {sc[1]} pts, {stars[1]} stars", True))
        turn = view["turn"]
        self.say(f"Ply {view['ply']}/{P.TOTAL_PLIES} (no clock)   To move: "
                 + st.seat(turn, f"{self.name(turn)} ({H.SEAT_NAME[turn]})", True)
                 + f"   actions left this turn: {view['left']}")
        for s in (self.human, self.bot):
            self.say(H.render_hand(view["blueprints"][s], s, self.color).replace(" hand:", f" hand ({self.name(s).lower()}):", 1))
        if danger:
            worst = sorted(danger.items(), key=lambda kv: -kv[1][0])[:4]
            txt = ", ".join(f"{k} ({p} pts via {ms[0]})" for k, (p, ms) in worst)
            self.say(st.warn("Danger:") + f" the engine can capture your stars at {txt}" + (" ..." if len(danger) > 4 else ""))

    def list_moves(self, view, flt):
        legal = view["moves"]
        if flt in ("cap", "capture", "captures"):
            sel = [m for m in legal if "@" in m]
            flt_desc = "scoring placement"
        else:
            if re.match(r"^\d+[:@]", flt):
                sel = [m for m in legal if m.startswith(flt)]
            else:
                sel = [m for m in legal if flt in m] if flt else list(legal)
            flt_desc = f"matching '{flt}'" if flt else "legal"
        scoring = []
        for m in sel:
            if "@" in m:
                pts, caught, _ = A.describe(view, m)
                if caught:
                    scoring.append((pts, caught, m))
        scoring.sort(key=lambda t: (-t[0], -t[1]))
        if flt in ("cap", "capture", "captures"):
            sel = [m for _, _, m in scoring]
        self.say(f"{len(sel)} {flt_desc} move(s)".replace("placement move(s)", "placement(s)") + ("" if sel else "; try 'moves 1@' or 'moves 2:'"))
        if scoring:
            self.say("  scoring: " + "  ".join(f"{m} (+{p})" for p, _, m in scoring[:20])
                     + (" ..." if len(scoring) > 20 else ""))
        if flt not in ("cap", "capture", "captures"):
            per = 6
            for i in range(0, len(sel), per):
                self.say("  " + "".join(f"{m:<17}" for m in sel[i:i + per]).rstrip())

    def hint(self, view):
        self.say(f"(engine thinking {self.time_ms / 1000:g}s ...)")
        info = self.engine(view, self.time_ms)
        top = A.top_moves(view, dict(info), n=3)
        if not top:
            self.say("No hint available.")
            return
        self.say(self.st.bold("Engine's top moves for you:"))
        for i, (m, _) in enumerate(top):
            self.say(f"  {i + 1}. {m:<16} {summarize(self.state, m)}")

    # ------------------------------------------------------------------ turns
    def human_action(self, view):
        """Returns 'moved', 'undo' or 'quit'."""
        self.show(view)
        legal = set(view["moves"])
        while True:
            line = self.ask(self.st.seat(self.human, "your move> ", True))
            if line is None:
                return "quit"
            raw = line.strip()
            if not raw:
                continue
            word, _, rest = raw.partition(" ")
            cmd = word.lower()
            if cmd in ("quit", "exit", "q"):
                return "quit"
            if cmd in ("help", "h", "?"):
                self.say(HELP)
                continue
            if cmd in ("moves", "m", "list"):
                self.list_moves(view, _norm(rest))
                continue
            if cmd == "hint":
                self.hint(view)
                continue
            if cmd in ("undo", "u", "takeback"):
                if self.undo():
                    self.say("Took back your last turn.")
                    return "undo"
                self.say("Nothing to undo yet.")
                continue
            if cmd in ("board", "show"):
                self.show(view)
                continue
            move = _norm(raw)
            if move in legal:
                pre = self.state
                self.push(move)
                self.last_engine_cells = []
                self.say(f"You play {move}: {summarize(pre, move)}")
                return "moved"
            self.say(self.st.warn("Not legal: ") + explain_illegal(self.state, move))

    def engine_action(self, view):
        self.say(self.st.dim(f"Engine ({H.SEAT_NAME[self.bot]}) thinking ..."))
        info = self.engine(view, self.time_ms)
        move = info.get("move")
        if move not in view["moves"]:
            move = P.best_capture_move(view)
        if move not in view["moves"]:
            move = random.choice(view["moves"])
        pre = self.state
        what = summarize(pre, move)
        cells = A.describe(view, move)[2] if "@" in move else []
        self.last_engine_cells += cells   # reset by our next move, so it shows the engine's whole turn
        self.push(move)
        sc = self.state["scores"]
        self.say(self.st.seat(self.bot, f"Engine plays {move}", True) + f": {what}   (Blue {sc[0]} - Red {sc[1]})")

    # ------------------------------------------------------------------ game
    def run(self):
        st = self.st
        lvl = f"{self.level}, " if self.level else ""
        self.say(st.bold("Blueprints: you vs the hexbot engine") + f"  ({lvl}{self.time_ms} ms per engine action)")
        self.say("You play " + st.seat(self.human, H.SEAT_NAME[self.human], True)
                 + (" and move first." if self.human == 0 else "; the engine (Blue) moves first.")
                 + " Type 'help' for rules and notation, 'quit' to stop.")
        quit_ = False
        try:
            while True:
                view = P.to_view(self.state)
                if view["result"]:
                    break
                if not view["moves"]:
                    self.push("pass")
                    continue
                if view["turn"] == self.human:
                    if self.human_action(view) == "quit":
                        quit_ = True
                        break
                else:
                    self.engine_action(view)
        except KeyboardInterrupt:   # Ctrl+C while the engine thinks
            quit_ = True
        return self.finish(abandoned=quit_)

    def finish(self, abandoned):
        view = P.to_view(self.state)
        sc = view["scores"]
        me, them = sc[self.human], sc[self.bot]
        res = view["result"]
        if abandoned:
            verdict = "abandoned"
            self.say(f"\nGame stopped at ply {view['ply']}: you {me} - engine {them}.")
        else:
            self.say(H.render_board(view["cells"], self.color))
            w = res.get("winner")
            verdict = "draw" if w is None else ("won" if w == self.human else "lost")
            text = {"won": "YOU WIN", "lost": "ENGINE WINS", "draw": "DRAW"}[verdict]
            self.say(self.st.bold(f"\nGAME OVER: {text}  you ({H.SEAT_NAME[self.human]}) {me} - engine {them}"))
        path = None
        if self.moves:
            path = self.save(verdict, res)
            if path:
                self.say(f"Saved game to {path}\nView it again: add  --replay \"{path}\"  to the command you used.")
        return {"verdict": verdict, "scores": sc, "moves": list(self.moves), "path": path}

    def save(self, verdict, res):
        data = {"game": "blueprints", "format": 1, "kind": "local", "build": self.build, "started": self.started,
                "ended": time.strftime("%Y%m%d-%H%M%S"), "human": H.SEAT_NAME[self.human].lower(),
                "engine_time_ms": self.time_ms, "level": self.level, "verdict": verdict, "result": res,
                "plies": len(self.moves), "scores": self.state["scores"], "moves": self.moves}
        d = games_dir()
        try:
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, f"local-{self.started}.json")
            n = 1
            while os.path.exists(path):
                n += 1
                path = os.path.join(d, f"local-{self.started}-{n}.json")
            with open(path, "w") as f:
                json.dump(data, f, indent=1)
            return path
        except OSError as e:
            self.say(f"(could not save the game: {e})")
            return None


def replay(path, inp=None, out=None, color=None):
    """Show a saved game turn by turn. Interactive (Enter = next turn) when stdin is a terminal."""
    out = out or sys.stdout
    inp = inp or sys.stdin
    col = H.use_color(color) if out is sys.stdout else bool(color)
    st = H.Style(col)

    def say(*a):
        print(*a, file=out, flush=True)

    with open(path) as f:
        data = json.load(f)
    moves = data if isinstance(data, list) else data.get("moves") or []
    human = SEATS.get(str(data.get("human", "")).lower()) if isinstance(data, dict) else None
    who = (lambda s: "You" if s == human else "Engine") if human is not None else (lambda s: H.SEAT_NAME[s])
    say(st.bold(f"Replay of {os.path.basename(path)}: {len(moves)} plies")
        + (f", you played {H.SEAT_NAME[human]}" if human is not None else ""))
    step = inp is sys.stdin and sys.stdin.isatty()
    if step:
        say("Enter = next turn, a = show the rest, q = quit")
    state = P.setup()
    turn_cells = []
    for i, mv in enumerate(moves):
        view = P.to_view(state)
        if mv != "pass" and mv not in view["moves"]:
            say(st.warn(f"ply {i}: {mv!r} is not legal here; stopping the replay"))
            break
        seat = view["turn"]
        what = summarize(state, mv) if mv != "pass" else "pass"
        if "@" in mv:
            turn_cells += A.describe(view, mv)[2]
        state = P.play(state, mv)
        sc = state["scores"]
        say(f"ply {i:3d}  {who(seat):6s} ({H.SEAT_NAME[seat]:4s}) {mv:<16} {what:<30} Blue {sc[0]} - Red {sc[1]}")
        end_of_turn = state["ply"] >= P.TOTAL_PLIES or i == len(moves) - 1 or P.turn_of(state["ply"]) != seat
        if end_of_turn:
            say(H.render_board(state["cells"], col, highlight=turn_cells))
            turn_cells = []
            if step and i < len(moves) - 1:
                try:
                    a = input("").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    a = "q"
                if a == "q":
                    return
                if a == "a":
                    step = False
    fin = P.to_view(state)
    sc = fin["scores"]
    res = fin["result"]
    if res:
        w = res.get("winner")
        say(st.bold(f"Final: Blue {sc[0]} - Red {sc[1]}  " + ("draw" if w is None else f"{who(w)} ({H.SEAT_NAME[w]}) won")))
    else:
        say(st.bold(f"Stopped at ply {fin['ply']}: Blue {sc[0]} - Red {sc[1]}"))
