#!/usr/bin/env python3
"""Parallel matches between two Blueprints policies (same CLI contract as engine/bp).

  python3 tools/arena.py --a "engine/versions/bp-abc1234 --time-ms 1000" --b "node tools/greedy.mjs" --games 32 --jobs 16

Each policy is a command that reads the state JSON on stdin and prints one JSON line {"move": ...}.
Games come in color-swapped pairs from the same random opening (--opening-plies random placements,
seeded), so each opening is played once with A as Blue and once with A as Red.
If a command has no --time-ms, --time-ms (default 1000) is appended. For engine/bp-style binaries
without --threads, "--threads max(1, cores // jobs)" is appended so parallel games don't oversubscribe.
A crash, timeout or illegal move by a policy is recorded as a fault and replaced by a random legal move.

Reports W/D/L for A, score % with 95% CI, an Elo estimate, mean score diff (A - B) with 95% CI,
and a per-color breakdown. --out FILE writes one JSON line per game (moves included).
"""
import argparse
import json
import math
import os
import random
import shlex
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
REFEREE = os.path.join(HERE, "referee.mjs")
print_lock = threading.Lock()


def build_cmd(spec, time_ms, threads):
    cmd = shlex.split(spec)
    if os.sep in cmd[0] and not os.path.isabs(cmd[0]) and os.path.exists(os.path.join(REPO, cmd[0])):
        cmd[0] = os.path.join(REPO, cmd[0])
    if "--time-ms" not in cmd:
        cmd += ["--time-ms", str(time_ms)]
    if "--threads" not in cmd and os.path.basename(cmd[0]).startswith("bp"):
        cmd += ["--threads", str(threads)]
    return cmd


def time_of(cmd):
    try:
        return int(cmd[cmd.index("--time-ms") + 1])
    except (ValueError, IndexError):
        return 1000


class Referee:
    def __init__(self):
        self.p = subprocess.Popen(["node", REFEREE], stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=REPO, text=True)

    def ask(self, req):
        self.p.stdin.write(json.dumps(req) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.p.kill()


def ask_policy(cmd, state, hard_timeout):
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, input=json.dumps(state), capture_output=True, text=True, timeout=hard_timeout, cwd=REPO)
    except subprocess.TimeoutExpired:
        return None, "timeout", time.monotonic() - t0
    for line in reversed(p.stdout.splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line).get("move"), None, time.monotonic() - t0
            except ValueError:
                break
    return None, f"exit {p.returncode}: {p.stderr[-200:]}", time.monotonic() - t0


def play_game(idx, opening, a_seat, cmds, verbose):
    """cmds[0] = A, cmds[1] = B. a_seat = seat A plays (0 Blue / 1 Red)."""
    ref = Referee()
    rng = random.Random(idx)
    try:
        view = ref.ask({"cmd": "new", "opening": opening})["view"]
        moves = list(opening)
        faults = [0, 0]
        think = [0.0, 0.0]
        while not view.get("result") and view["moves"]:
            seat = view["turn"]
            who = 0 if seat == a_seat else 1
            cmd = cmds[who]
            state = {"you": [seat], "turn": seat, "ply": view["ply"], "view": view,
                     "clock": {"remaining": [600000, 600000]}, "startsAt": None}
            move, err, dt = ask_policy(cmd, state, time_of(cmd) / 1000 * 3 + 5)
            think[who] += dt
            if move not in view["moves"]:
                faults[who] += 1
                if verbose or faults[who] <= 2:
                    with print_lock:
                        print(f"  game {idx}: {'AB'[who]} fault at ply {view['ply']}: {err or 'illegal move ' + repr(move)}",
                              file=sys.stderr)
                move = rng.choice(view["moves"])
            r = ref.ask({"cmd": "play", "move": move})
            if "error" in r:
                raise RuntimeError(r["error"])
            view = r["view"]
            moves.append(move)
        sc = view["scores"]
        diff = sc[a_seat] - sc[1 - a_seat]
        return {"game": idx, "a_seat": a_seat, "scores": sc, "diff": diff,
                "outcome": 1.0 if diff > 0 else 0.5 if diff == 0 else 0.0,
                "faults": faults, "think_s": [round(t, 1) for t in think], "plies": len(moves),
                "opening": opening, "moves": moves}
    finally:
        ref.close()


def ci95(xs):
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = sum(xs) / n
    if n < 2:
        return m, float("inf")
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def elo(p):
    p = min(max(p, 1e-3), 1 - 1e-3)
    return -400 * math.log10(1 / p - 1)


def report(results, label_a, label_b):
    n = len(results)
    w = sum(r["outcome"] == 1.0 for r in results)
    d = sum(r["outcome"] == 0.5 for r in results)
    l = n - w - d
    sm, sh = ci95([r["outcome"] for r in results])
    # Floor the score CI with a Laplace-smoothed binomial sd so a 4/0/0 sweep doesn't report +-0.
    ps = (sum(r["outcome"] for r in results) + 1) / (n + 2)
    sh = max(sh, 1.96 * math.sqrt(ps * (1 - ps) / max(1, n)))
    dm, dh = ci95([r["diff"] for r in results])
    lines = [f"A = {label_a}", f"B = {label_b}",
             f"games {n}:  A W/D/L = {w}/{d}/{l}   score {100 * sm:.1f}% +- {100 * sh:.1f}%  "
             f"(Elo {elo(sm):+.0f}, 95% CI {elo(sm - sh):+.0f}..{elo(sm + sh):+.0f})",
             f"mean score diff (A-B): {dm:+.1f} +- {dh:.1f} (95% CI)"]
    for seat, name in ((0, "Blue"), (1, "Red")):
        sub = [r for r in results if r["a_seat"] == seat]
        if sub:
            m, h = ci95([r["diff"] for r in sub])
            ws = sum(r["outcome"] == 1.0 for r in sub)
            ds = sum(r["outcome"] == 0.5 for r in sub)
            lines.append(f"  A as {name}: {ws}/{ds}/{len(sub) - ws - ds}  diff {m:+.1f} +- {h:.1f}")
    fa = sum(r["faults"][0] for r in results)
    fb = sum(r["faults"][1] for r in results)
    ta = sum(r["think_s"][0] for r in results) / max(1, n)
    tb = sum(r["think_s"][1] for r in results) / max(1, n)
    lines.append(f"faults A {fa}, B {fb};  avg think per game A {ta:.1f}s, B {tb:.1f}s")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True, help="policy A command")
    ap.add_argument("--b", required=True, help="policy B command")
    ap.add_argument("--games", type=int, default=32, help="number of games (rounded up to even)")
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--time-ms", type=int, default=1000, help="appended when a command has no --time-ms")
    ap.add_argument("--opening-plies", type=int, default=2, help="random placements before the policies take over")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", help="write per-game JSON lines here")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cores = os.cpu_count() or 16
    threads = max(1, cores // args.jobs)
    cmds = [build_cmd(args.a, args.time_ms, threads), build_cmd(args.b, args.time_ms, threads)]
    pairs = (args.games + 1) // 2
    ref = Referee()
    openings = [ref.ask({"cmd": "random_opening", "plies": args.opening_plies, "seed": args.seed * 1000 + i})["moves"]
                if args.opening_plies > 0 else [] for i in range(pairs)]
    ref.close()
    jobs = [(2 * i + s, openings[i], s) for i in range(pairs) for s in (0, 1)]
    print(f"arena: {len(jobs)} games, {args.jobs} parallel, threads/engine {threads}", file=sys.stderr)
    print(f"  A: {' '.join(cmds[0])}\n  B: {' '.join(cmds[1])}", file=sys.stderr)
    results, t0 = [], time.time()
    out = open(args.out, "a") if args.out else None
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(play_game, idx, op, s, cmds, args.verbose): idx for idx, op, s in jobs}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as e:  # noqa: BLE001
                print(f"  game {futs[f]} crashed: {e}", file=sys.stderr)
                continue
            results.append(r)
            if out:
                out.write(json.dumps(r) + "\n")
                out.flush()
            w = sum(x["outcome"] == 1.0 for x in results)
            d = sum(x["outcome"] == 0.5 for x in results)
            with print_lock:
                print(f"  [{len(results)}/{len(jobs)}] game {r['game']} A={'Blue' if r['a_seat'] == 0 else 'Red'} "
                      f"scores {r['scores']} diff {r['diff']:+d}  running A {w}/{d}/{len(results) - w - d} "
                      f"({time.time() - t0:.0f}s)", file=sys.stderr)
    if out:
        out.close()
    print(report(results, args.a, args.b))


if __name__ == "__main__":
    main()
