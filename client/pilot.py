"""Pilot control interface: lets an outside "pilot" (e.g. an LLM) co-play live games through files.

Opt-in with `bot.py --pilot DIR`. On each of our plies, before posting:
  1. DIR/decision.json is written atomically: position summary, engine top moves, board, danger, deadline.
  2. DIR/control.json is read (missing/malformed is fine):
       {"engine_args": "--p alpha=0", "force": {"<ply>": "<move>"}, "veto": ["move", ...],
        "prefer_wait_ms": 3000, "note": "..."}
     - engine_args: appended to the engine command for this and later moves
     - force[ply]: played immediately (if legal), no engine
     - veto: those moves are never played (best non-vetoed engine top move instead)
     - prefer_wait_ms: after the engine finishes, wait up to this long for DIR/pick-<ply>.json {"move": "..."}.
       Never lets our clock drop below 20s, and never waits when the clock is under 25s.
  3. One log line per ply says whether the move was the engine's, a pilot pick, forced, or a veto replacement.
At game end DIR/last_result.json is written.
"""
import json
import os
import shlex
import time

import bprules
import hexrender as H

MIN_CLOCK_AFTER_WAIT_MS = 20000
NO_WAIT_BELOW_MS = 25000
MAX_WAIT_UNKNOWN_CLOCK_MS = 8000


def _atomic_write(path, obj):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def hand_summary(hand):
    out = []
    for i, bp in enumerate(hand):
        stars = sum(1 for v in bp.values() if v == "star")
        out.append(f"#{i + 1} {len(bp)} cells {stars}*: {H.bp_keys(bp)}")
    return out


class Pilot:
    def __init__(self, directory, log):
        self.dir = os.path.abspath(directory)
        os.makedirs(self.dir, exist_ok=True)
        self.log = log
        self.engine_args = []

    def control(self):
        return _read_json(os.path.join(self.dir, "control.json"))

    def apply_engine_args(self, ctrl, chooser):
        raw = ctrl.get("engine_args")
        if isinstance(raw, str):
            try:
                args = shlex.split(raw)
            except ValueError:
                args = self.engine_args
            if args != self.engine_args:
                self.log(f"PILOT engine_args -> {' '.join(args) or '(none)'}")
            self.engine_args = args
        chooser.extra_args = list(self.engine_args)

    def decide(self, chooser, room, state, seat, extra=None):
        """Full pilot flow for one ply. Returns (move, info)."""
        import advise
        t0 = time.time()
        view = state["view"]
        legal = view.get("moves") or []
        legal_set = set(legal)
        ply = state.get("ply", view.get("ply"))
        ctrl = self.control()
        self.apply_engine_args(ctrl, chooser)
        forced = (ctrl.get("force") or {}).get(str(ply)) if isinstance(ctrl.get("force"), dict) else None
        if forced in legal_set:
            info = {"ply": ply, "source": "pilot-force", "engine_move": None}
            self._write_decision(room, state, seat, info, [], None, t0, 0, advise)
            self.log(f"PILOT ply {ply}: FORCED {forced}")
            return forced, info
        if forced:
            self.log(f"PILOT ply {ply}: ignoring illegal forced move {forced!r}")

        move, info = chooser.choose(room, state, seat)
        engine_move = move
        veto = set(m for m in (ctrl.get("veto") or []) if isinstance(m, str))
        top = []
        for it in [{"move": move, "score": info.get("eval")}] + list(info.get("top") or []):
            m = it.get("move") if isinstance(it, dict) else None
            if m in legal_set and m not in [t["move"] for t in top]:
                top.append({"move": m, "score": it.get("score", it.get("eval"))})
        top = top[:8]
        source = info.get("source", "engine")
        if move in veto:
            alts = [t["move"] for t in top if t["move"] not in veto]
            if not alts:
                rest = [m for m in legal if m not in veto]
                alts = [bprules.best_capture_move(dict(view, moves=rest))] if rest else [move]
            move = alts[0]
            source = "veto"
        # How long may we wait for a pick?
        wait_ms = int(ctrl.get("prefer_wait_ms") or 0) if isinstance(ctrl.get("prefer_wait_ms"), (int, float)) else 0
        clock = info.get("clock_ms")
        if clock is not None:
            now_clock = clock - (time.time() - t0) * 1000
            wait_ms = 0 if now_clock < NO_WAIT_BELOW_MS else max(0, min(wait_ms, now_clock - MIN_CLOCK_AFTER_WAIT_MS))
        else:
            wait_ms = min(wait_ms, MAX_WAIT_UNKNOWN_CLOCK_MS)
        for t in top:
            try:
                pts, caught, _ = advise.describe(view, t["move"])
            except Exception:  # noqa: BLE001
                pts, caught = None, None
            t["points"], t["captures"] = pts, caught
        self._write_decision(room, state, seat, dict(info, engine_move=engine_move, chosen=move), top, engine_move,
                             t0, wait_ms, advise)
        picked = None
        if wait_ms > 0:
            pick_path = os.path.join(self.dir, f"pick-{ply}.json")
            end = time.time() + wait_ms / 1000
            while time.time() < end:
                p = _read_json(pick_path).get("move")
                if p is None:
                    p = (self.control().get("force") or {}).get(str(ply))
                if p in legal_set:
                    picked = p
                    break
                if p:
                    self.log(f"PILOT ply {ply}: ignoring illegal pick {p!r}")
                    break
                time.sleep(0.1)
        if picked:
            move = picked
            source = "pilot-pick" if picked != engine_move else "pilot-pick(=engine)"
        info = dict(info, source=source, engine_move=engine_move, waited_ms=int((time.time() - t0) * 1000))
        label = {"veto": "VETO -> best non-vetoed", "pilot-pick": "PILOT PICK"}.get(source, source.upper())
        self.log(f"PILOT ply {ply}: {label} {move} (engine {engine_move}"
                 + (f", veto {sorted(veto)}" if veto else "") + (f", note: {ctrl.get('note')}" if ctrl.get("note") else "") + ")")
        return move, info

    def _write_decision(self, room, state, seat, info, top, engine_move, t0, wait_ms, advise):
        view = state["view"]
        try:
            danger = advise.threats(view, 1 - seat)
            danger_list = [{"star": k, "points": p, "via": ms[:3]} for k, (p, ms) in
                           sorted(danger.items(), key=lambda kv: -kv[1][0])[:6]]
            board = H.render_board(view["cells"], color=False, danger=danger.keys())
        except Exception as e:  # noqa: BLE001
            danger_list, board = [], f"(render error {e})"
        bps = view.get("blueprints") or [[], []]
        dec = {
            "room": room, "ply": state.get("ply", view.get("ply")), "seat": seat,
            "colour": "Blue" if seat == 0 else "Red", "scores": view.get("scores"), "stars": view.get("stars"),
            "clock_ms": info.get("clock_ms"), "left_in_turn": view.get("left"),
            "top": top, "engine_move": engine_move, "engine_eval": info.get("eval"), "pv": info.get("pv"),
            "board_text": board, "danger": danger_list,
            "our_hand_summary": hand_summary(bps[seat]) if len(bps) > seat else [],
            "opp_hand_summary": hand_summary(bps[1 - seat]) if len(bps) > 1 - seat else [],
            "deadline_epoch_ms": int(time.time() * 1000 + wait_ms),
            "pick_file": os.path.join(self.dir, f"pick-{state.get('ply', view.get('ply'))}.json"),
            "written_epoch_ms": int(time.time() * 1000),
        }
        try:
            _atomic_write(os.path.join(self.dir, "decision.json"), dec)
        except OSError as e:
            self.log(f"PILOT could not write decision.json: {e}")

    def write_result(self, room, state, summary):
        view = state.get("view") or {}
        try:
            _atomic_write(os.path.join(self.dir, "last_result.json"),
                          {"room": room, "result": view.get("result"), "scores": view.get("scores"),
                           "you": state.get("you"), "summary": summary, "epoch_ms": int(time.time() * 1000)})
        except OSError as e:
            self.log(f"PILOT could not write last_result.json: {e}")
