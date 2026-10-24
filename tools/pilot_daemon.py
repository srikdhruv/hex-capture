#!/usr/bin/env python3
"""Pilot daemon: answers every decision.json from the bot (--pilot DIR) instantly with pick-<ply>.json,
applying a rules file the pilot can edit on the fly. It is the single official writer of picks.

  python3 tools/pilot_daemon.py [--dir client/pilot] [--rules DIR/rules.json] [--dry-run] [--once]

Set control.json {"prefer_wait_ms": 3000} so the bot waits for the pick (it arrives in ~50ms, so the wait
costs almost no clock). Only ONE daemon may run per pilot dir: a lock file (DIR/pilot_daemon.lock) refuses
a second instance, and a legacy autopick*.py process also blocks start-up (unless --force).

rules.json (re-read every ply; if it is broken, the last good version stays in force):
{
  "enabled": true,                       # false: always pick the engine move
  "veto": ["3:*", "*>3:*", "2@5,-3"],    # glob patterns; never played
  "force": {"57": "2@1,1", "60": {"move": "1@0,0", "unless_capture": true}},
  "protect_from": 20,                    # from this ply: no edits touching protect_pieces unless a capture is available
  "protect_pieces": [2, 3],
  "star_safe_dist": 3,                   # non-capturing stamps putting a STAR within N hexes of enemy cells are skipped
  "take_capture_min": 0,                 # >0: if the engine move scores < this, play the top move with the most
                                         #     points when it has at least this many
  "approach": {"ply_min": 10, "ply_max": 80, "min_gain": 2, "time_s": 1.0, "depth": 4},
                                         # multi-turn approach planner (tools/approach.py): when no capture is
                                         # available and its plan cuts distance-to-crack by >= min_gain (hex cost)
                                         # within this turn, play its moves instead of the engine's build
  "when": [                              # conditional rules, in order; all listed conditions must hold
    {"if": {"ply_min": 40, "ply_max": 80, "capture_available": false, "engine_move": "*>*",
            "left": 2, "clock_below_ms": 30000, "score_diff_below": 0, "our_stars_above": 50,
            "danger_points_above": 100, "engine_points_below": 50},
     "then": {"veto": ["1:*"], "prefer": ["3@*"], "pick": "best_capture|best_non_edit|engine|<move>",
              "star_safe_dist": 5},                 # gated star_safe_dist (overrides the global one while matched)
     "note": "why"}
  ]
}
Every decision is logged to DIR/pilot_daemon.log: the pick, the reason, top moves and danger.
"""
import argparse
import fnmatch
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "client"))
sys.path.insert(0, HERE)
import bprules as B  # noqa: E402


def rj(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def hexdist(a, b):
    dq, dr = a[0] - b[0], a[1] - b[1]
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def match(move, patterns):
    return any(fnmatch.fnmatchcase(move, p) for p in patterns or [])


def touches_pieces(move, pieces):
    if ">" not in move:
        return False
    a, b = move.split(">")
    return int(a.split(":")[0]) in pieces or int(b.split(":")[0]) in pieces


def star_exposed(view, seat, move, dist):
    """True if `move` stamps one of our stars within `dist` of a surviving enemy cell."""
    if "@" not in move or view is None:
        return False
    st = B.from_view(view)
    cells = st["cells"]
    i, at = move.split("@")
    bp = st["blueprints"][seat][int(i) - 1]
    stamped, removed = B.stamp(cells, seat, bp, B.parse(at))
    enemy = [B.parse(k) for k, c in cells.items() if c[0] != seat and k not in removed]
    for k, kind in stamped:
        if kind == B.STAR:
            p = B.parse(k)
            if any(hexdist(p, e) <= dist for e in enemy):
                return True
    return False


class Daemon:
    def __init__(self, directory, rules_path, dry_run=False, out=lambda s: print(s, flush=True)):
        self.dir = os.path.abspath(directory)
        self.rules_path = rules_path or os.path.join(self.dir, "rules.json")
        self.dry = dry_run
        self.rules = {}
        self.rules_mtime = None
        self.out = out
        self.last_key = None
        self.approach_next = None  # (room, ply, move): 2nd action of the current approach plan

    # --- io
    def log(self, s):
        line = f"{time.strftime('%H:%M:%S')} {s}"
        self.out(line)
        try:
            with open(os.path.join(self.dir, "pilot_daemon.log"), "a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def load_rules(self):
        try:
            mt = os.path.getmtime(self.rules_path)
        except OSError:
            return self.rules
        if mt != self.rules_mtime:
            r = rj(self.rules_path)
            if r is None:
                self.log(f"RULES ERROR: {self.rules_path} is not valid JSON; keeping the previous rules")
            else:
                self.rules = r
                self.log(f"rules loaded: {json.dumps(r, separators=(',', ':'))[:300]}")
            self.rules_mtime = mt
        return self.rules

    def view_for(self, d):
        s = rj(os.path.join(self.dir, "state.json"))
        if s and s.get("room") == d.get("room") and s.get("ply") == d.get("ply"):
            return s["state"]["view"]
        path = os.path.join(REPO, "client", "logs", f"game-{d.get('room')}.jsonl")
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                f.seek(max(0, size - 600000))
                data = f.read().decode(errors="replace")
        except OSError:
            return None
        for line in reversed(data.splitlines()):
            if '"type":"state"' not in line:
                continue
            try:
                st = json.loads(line).get("state") or {}
            except ValueError:
                continue
            if st.get("ply", (st.get("view") or {}).get("ply")) == d.get("ply"):
                return st.get("view")
        return None

    # --- decision
    def decide(self, d, rules, view):
        ply, seat = d["ply"], d.get("seat", 0)
        top = d.get("top") or []
        pts = {t["move"]: (t.get("points") or 0) for t in top}
        caps = any(v > 0 for v in pts.values())
        engine = d.get("engine_move") or (top[0]["move"] if top else None)
        legal = set(view.get("moves") or []) if view else None
        ok = (lambda m: m in legal) if legal is not None else (lambda m: True)
        if rules.get("enabled") is False:
            return engine, "disabled -> engine"

        f = (rules.get("force") or {}).get(str(ply))
        if f:
            f = {"move": f} if isinstance(f, str) else f
            if f.get("unless_capture", True) and caps:
                pass
            elif ok(f.get("move")):
                return f["move"], "force"

        veto = list(rules.get("veto") or [])
        prefer, notes = [], []
        explicit = None
        sd_when = None  # star_safe_dist set by a matching when-rule (gated version of the global knob)
        diff = (d.get("scores") or [0, 0])[seat] - (d.get("scores") or [0, 0])[1 - seat]
        our_stars = (d.get("stars") or [0, 0])[seat]
        danger_pts = max([x.get("points") or 0 for x in d.get("danger") or []], default=0)
        for w in rules.get("when") or []:
            c = w.get("if") or {}
            conds = [
                ("ply_min", lambda v: ply >= v), ("ply_max", lambda v: ply <= v),
                ("capture_available", lambda v: caps == bool(v)),
                ("engine_move", lambda v: engine is not None and match(engine, [v] if isinstance(v, str) else v)),
                ("left", lambda v: d.get("left_in_turn") == v),
                ("clock_below_ms", lambda v: (d.get("clock_ms") or 10 ** 9) < v),
                ("score_diff_below", lambda v: diff < v), ("score_diff_above", lambda v: diff > v),
                ("our_stars_below", lambda v: our_stars < v), ("our_stars_above", lambda v: our_stars > v),
                ("danger_points_above", lambda v: danger_pts > v),
                ("engine_points_below", lambda v: pts.get(engine, 0) < v),
            ]
            if all(fn(c[k]) for k, fn in conds if k in c):
                t = w.get("then") or {}
                veto += t.get("veto") or []
                prefer += t.get("prefer") or []
                notes.append(w.get("note") or "when")
                if t.get("pick") and explicit is None:
                    explicit = t["pick"]
                if t.get("star_safe_dist") is not None:
                    sd_when = t["star_safe_dist"]
        tag = f" [{'; '.join(notes)}]" if notes else ""

        cands = [t["move"] for t in top if not match(t["move"], veto) and ok(t["move"])]
        if not cands and legal:
            rest = sorted(m for m in legal if not match(m, veto))
            if rest:
                cands = [B.best_capture_move(dict(view, moves=rest))]
        if not cands:
            return engine, "everything vetoed -> engine" + tag

        if explicit:
            if explicit == "engine" and engine:
                return engine, "when: engine" + tag
            if explicit == "best_capture":
                best = max(cands, key=lambda m: pts.get(m, 0))
                return best, f"when: best_capture ({pts.get(best, 0)})" + tag
            if explicit == "best_non_edit":
                ne = [m for m in cands if "@" in m]
                if ne:
                    return ne[0], "when: best_non_edit" + tag
            elif explicit not in ("engine", "best_capture", "best_non_edit") and ok(explicit):
                return explicit, "when: pick" + tag

        apr = rules.get("approach")
        if isinstance(apr, dict) and apr.get("enabled", True) and not caps and view is not None \
                and apr.get("ply_min", 0) <= ply <= apr.get("ply_max", 999):
            nxt = self.approach_next
            if nxt and nxt[0] == d.get("room") and nxt[1] == ply and ok(nxt[2]) and not match(nxt[2], veto):
                self.approach_next = None
                return nxt[2], "approach (2nd action of plan)" + tag
            try:
                import approach as AP
                pl = AP.plan(view, seat, apr.get("depth", 4), apr.get("beam", 6), apr.get("time_s", 1.0))
                gain = (pl["D0"] - pl["D_after_turn"]) if pl["D0"] != float("inf") else 0
                first = pl["this_turn"][0] if pl["this_turn"] else None
                if first and gain >= apr.get("min_gain", 2) and ok(first) and not match(first, veto):
                    if len(pl["this_turn"]) > 1:
                        self.approach_next = (d.get("room"), ply + 1, pl["this_turn"][1])
                    return first, (f"approach: D {pl['D0']}->{pl['D_after_turn']} this turn, "
                                   f"capture ~ply {pl['capture_ply']} ({pl['ms']}ms) over engine {engine}") + tag
            except Exception as e:  # noqa: BLE001
                notes.append(f"approach error {type(e).__name__}")
        self.approach_next = None

        tmin = rules.get("take_capture_min") or 0
        if tmin > 0 and caps and pts.get(engine, 0) < tmin:  # never override an engine move that already captures
            best = max(cands, key=lambda m: pts.get(m, 0))
            if pts.get(best, 0) >= tmin:
                return best, f"take capture {pts[best]}" + tag

        why = []
        pf = rules.get("protect_from")
        pieces = set(rules.get("protect_pieces") or [2, 3])
        if pf is not None and ply >= pf and not caps:
            kept = [m for m in cands if not touches_pieces(m, pieces)]
            if kept and len(kept) < len(cands):
                why.append("protect")
                cands = kept
        sd = sd_when if sd_when is not None else rules.get("star_safe_dist")
        if sd and view is not None:
            kept = [m for m in cands if pts.get(m, 0) > 0 or not star_exposed(view, seat, m, sd)]
            if kept and len(kept) < len(cands):
                why.append(f"star-safe({sd})")
                cands = kept
        if prefer:
            for p in prefer:
                hit = [m for m in cands if fnmatch.fnmatchcase(m, p)]
                if hit:
                    cands = hit + [m for m in cands if m not in hit]
                    why.append(f"prefer {p}")
                    break
        mv = cands[0]
        if mv == engine:
            return mv, "engine" + (f" ({', '.join(why)})" if why else "") + tag
        if engine and match(engine, veto):
            why.insert(0, f"veto {engine}")
        return mv, (", ".join(why) or "best allowed") + f" (engine {engine})" + tag

    def step(self):
        d = rj(os.path.join(self.dir, "decision.json"))
        if not d or not d.get("room") or d.get("ply") is None:
            return False
        key = (d.get("room"), d.get("ply"), d.get("written_epoch_ms"))
        if key == self.last_key:
            return False
        self.last_key = key
        rules = self.load_rules()
        view = self.view_for(d)
        try:
            mv, why = self.decide(d, rules, view)
        except Exception as e:  # noqa: BLE001 - never block the bot: fall back to the engine move
            mv, why = d.get("engine_move"), f"daemon error {type(e).__name__}: {e} -> engine"
        ply = d["ply"]
        for old in glob.glob(os.path.join(self.dir, "pick-*.json")):
            if old != os.path.join(self.dir, f"pick-{ply}.json"):
                try:
                    os.remove(old)
                except OSError:
                    pass
        if mv and not self.dry:
            path = os.path.join(self.dir, f"pick-{ply}.json")
            tmp = path + f".tmp{os.getpid()}"
            with open(tmp, "w") as f:
                json.dump({"move": mv, "room": d["room"], "ply": ply, "why": why}, f)
            os.replace(tmp, path)
        tops = " ".join(f"{t['move']}:{t.get('points') or 0}" for t in (d.get("top") or [])[:4])
        dng = " ".join(f"{x['star']}:{x['points']}" for x in (d.get("danger") or [])[:3])
        self.log(f"ply {ply} L{d.get('left_in_turn')} {d.get('colour')} sc={d.get('scores')} st={d.get('stars')} clk={d.get('clock_ms')} "
                 f"pick {mv} ({why}){' [dry-run]' if self.dry else ''} | top {tops} | danger {dng or '-'}")
        return True


def other_writers(directory):
    """PIDs of other pick writers: a live lock holder or legacy autopick*.py processes."""
    found = []
    lock = os.path.join(directory, "pilot_daemon.lock")
    try:
        pid = int(open(lock).read().strip() or 0)
        if pid and pid != os.getpid():
            os.kill(pid, 0)
            found.append((pid, "pilot_daemon (lock)"))
    except (OSError, ValueError):
        pass
    for p in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            argv = open(p, "rb").read().decode(errors="replace").split("\0")
        except OSError:
            continue
        legacy_dir = os.path.join(REPO, "client", "pilot")  # legacy autopick scripts hard-code this dir
        is_py = argv and os.path.basename(argv[0]).startswith("python")
        script = any(fnmatch.fnmatch(os.path.basename(a), "autopick*.py") for a in argv[1:3])
        if is_py and script and os.path.abspath(directory) == legacy_dir:
            found.append((int(p.split("/")[2]), " ".join(argv)[:80]))
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.join(REPO, "client", "pilot"))
    ap.add_argument("--rules", help="rules file (default DIR/rules.json)")
    ap.add_argument("--dry-run", action="store_true", help="log decisions but don't write picks")
    ap.add_argument("--once", action="store_true", help="process the current decision.json once and exit")
    ap.add_argument("--force", action="store_true", help="start even if another pick writer seems to run")
    args = ap.parse_args()
    os.makedirs(args.dir, exist_ok=True)
    dmn = Daemon(args.dir, args.rules, args.dry_run)
    if args.once:
        dmn.step() or print("no new decision.json")
        return
    others = other_writers(dmn.dir)
    if others and not args.force and not args.dry_run:
        for pid, what in others:
            print(f"another pick writer is running: pid {pid} {what}", file=sys.stderr)
        raise SystemExit("refusing to start: only ONE daemon may write picks (stop it, or use --force/--dry-run)")
    lock = os.path.join(dmn.dir, "pilot_daemon.lock")
    if not args.dry_run:
        with open(lock, "w") as f:
            f.write(str(os.getpid()))
    dmn.log(f"pilot_daemon started (pid {os.getpid()}, dir {dmn.dir}, rules {dmn.rules_path}"
            f"{', DRY-RUN' if args.dry_run else ''})")
    dmn.load_rules()
    import signal
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))  # run the finally: release the lock
    try:
        while True:
            dmn.step()
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        if not args.dry_run:
            try:
                if open(lock).read().strip() == str(os.getpid()):
                    os.remove(lock)
            except OSError:
                pass


if __name__ == "__main__":
    main()
