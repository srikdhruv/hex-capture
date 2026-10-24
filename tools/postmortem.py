#!/usr/bin/env python3
"""Post-mortem of real games from hexbot logs (bot or --advise): learn from what happened.

  python3 tools/postmortem.py ~/.hexbot/logs/game-<room>.jsonl [--time-ms 10000] [--jobs 4]
  python3 tools/postmortem.py ~/.hexbot/logs/            # every game-*.jsonl in the folder
  python3 tools/postmortem.py hexbot-logs-XXXX.zip       # a zip made by `hexbot --logs`

For each game it replays every logged state, reconstructs both sides' moves, and for each of OUR turns
re-runs engine/bp with a long budget. It flags:
  (a) points conceded on the opponent's very next turn that the long search's line would have avoided
      (opponent's best single-placement capture after our actual turn vs after the engine's line),
  (b) immediate captures we missed (best capture available vs points we took),
  (c) the biggest eval losses (engine eval of its best move vs of the move we played, same budget).
It prints a short ranked report and saves the flagged positions to lab/positions/*.json (full server-style
state + played move + engine move + note) for the engine regression suite.
It also profiles the opponent: edits, Fortlite-likeness, snipers (pieces of 1-3 cells), first 10 moves,
blueprint shapes, and stars over time.
"""
import argparse
import glob
import io
import json
import os
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "client"))
import bprules as P  # noqa: E402
import hexrender as H  # noqa: E402
import advise as A  # noqa: E402

ENGINE = os.path.join(REPO, "engine", "bp" + (".exe" if os.name == "nt" else ""))
POS_DIR = os.path.join(REPO, "lab", "positions")
NAMES = {0: "Blue", 1: "Red"}


# ----------------------------------------------------------------------------- loading

def read_logs(path):
    """Yield (name, [records]) for each game log in a file / folder / zip."""
    def parse(name, text):
        recs = []
        for line in text.splitlines():
            try:
                recs.append(json.loads(line))
            except ValueError:
                pass
        return name, recs
    if os.path.isdir(path):
        for f in sorted(glob.glob(os.path.join(path, "game-*.jsonl"))):
            yield parse(os.path.basename(f), open(f, encoding="utf-8").read())
    elif path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for n in sorted(z.namelist()):
                if os.path.basename(n).startswith("game-") and n.endswith(".jsonl"):
                    yield parse(os.path.basename(n), z.read(n).decode("utf-8", "replace"))
    else:
        yield parse(os.path.basename(path), open(path, encoding="utf-8").read())


def game_from_records(recs, seat_override=None):
    states, decisions = {}, {}
    yous = {}
    for r in recs:
        if r.get("type") == "state" and isinstance(r.get("state"), dict) and r["state"].get("view"):
            st = r["state"]
            ply = st.get("ply", st["view"].get("ply"))
            states[ply] = st
            for y in st.get("you") or []:
                yous[y] = yous.get(y, 0) + 1
        elif r.get("type") in ("decision", "advice") and r.get("move"):
            decisions[r.get("ply")] = r
    if not states:
        return None
    seat = seat_override if seat_override is not None else (max(yous, key=yous.get) if yous else 0)
    return {"states": states, "decisions": decisions, "seat": seat}


def infer_move(view, nxt):
    """Find the move that turns view (ply p) into nxt (ply p+1)."""
    st = P.from_view(view)
    seat = P.turn_of(st["ply"])
    target_cells = {k: [int(v[0]), v[1]] for k, v in nxt["cells"].items()}
    target_hand = nxt["blueprints"][seat]
    moves = view.get("moves") or P.legal_moves(st)
    edited = target_hand != st["blueprints"][seat]
    for m in moves:
        if ("@" in m) == edited:
            continue
        if "@" in m:
            i, at = m.split("@")
            bp = st["blueprints"][seat][int(i) - 1]
            dq, dr = P.parse(at)
            ok = True
            for k, v in bp.items():
                q, r = P.parse(k)
                c = target_cells.get(P.key(q + dq, r + dr))
                if not c or c[0] != seat or c[1] != v:
                    ok = False
                    break
            if not ok:
                continue
        nx = P.play(st, m)
        if nx["cells"] == target_cells and nx["blueprints"] == nxt["blueprints"]:
            return m
    return None


# ----------------------------------------------------------------------------- engine

def run_engine(state, time_ms, threads, only=None):
    st = json.loads(json.dumps(state))
    if only is not None:
        st["view"]["moves"] = [only]
    try:
        p = subprocess.run([ENGINE, "--time-ms", str(time_ms), "--threads", str(threads)], input=json.dumps(st),
                           capture_output=True, text=True, timeout=time_ms / 1000 + 30)
        for line in reversed(p.stdout.splitlines()):
            if line.strip().startswith("{"):
                return json.loads(line)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    return {"error": "no output"}


def best_capture(view):
    st = P.from_view(view)
    seat = P.turn_of(st["ply"])
    mine = P.star_counts(st["cells"])[seat]
    best, bm = 0, None
    for m in view.get("moves") or []:
        if "@" not in m:
            continue
        i, at = m.split("@")
        _, removed = P.stamp(st["cells"], seat, st["blueprints"][seat][int(i) - 1], P.parse(at))
        pts = sum(1 for k in removed if st["cells"][k][1] == P.STAR) * mine
        if pts > best:
            best, bm = pts, m
    return best, bm


def max_threat(rules_state, attacker):
    view = P.to_view(rules_state) if "moves" not in rules_state else rules_state
    t = A.threats(view, attacker)
    if not t:
        return 0, None
    k, (pts, ms) = max(t.items(), key=lambda kv: kv[1][0])
    return pts, ms[0]


# ----------------------------------------------------------------------------- opponent profile

def load_fortlite():
    try:
        return json.load(open(os.path.join(REPO, "engine", "books", "fortlite.json")))
    except (OSError, ValueError):
        return None


def opponent_profile(game, moves):
    seat = game["seat"]
    opp = 1 - seat
    states = game["states"]
    plies = sorted(states)
    opp_moves = [(p, m) for p, m in sorted(moves.items()) if P.turn_of(p) == opp and m]
    edits = [m for _, m in opp_moves if "@" not in m]
    prof = {"seat": NAMES[opp], "moves_seen": len(opp_moves), "edits": len(edits),
            "first10": [m for _, m in opp_moves[:10]]}
    fl = load_fortlite()
    if fl:
        book = fl.get("edits", {}).get(str(opp), [])
        prof["fortlite_edits_matched"] = f"{sum(1 for e in book if e in edits)}/{len(book)}"
        tgt = fl.get("target", {}).get(str(opp))
        if tgt:
            final_hand = states[plies[-1]]["view"]["blueprints"][opp]
            norm = lambda bp: P.normalize(dict(bp))[0]  # noqa: E731
            prof["fortlite_hand_pieces_equal"] = sum(1 for a in final_hand if any(norm(a) == norm(b) for b in tgt))
    snipers = []
    for p in plies:
        for i, bp in enumerate(states[p]["view"]["blueprints"][opp]):
            if 0 < len(bp) <= 3 and not any(s[1] == i + 1 for s in snipers):
                kinds = "".join(H.KIND_CH.get(v, "?") for v in bp.values())
                snipers.append((p, i + 1, len(bp), kinds))
    prof["snipers"] = [f"#{i} ({n} cells '{k}') from ply {p}" for p, i, n, k in snipers]
    prof["stars_over_time"] = [(p, states[p]["view"].get("stars") or P.star_counts(P.from_view(states[p]["view"])["cells"]),
                                states[p]["view"].get("scores")) for p in plies if p % 10 == 0 or p == plies[-1]]
    prof["hands"] = {}
    for label, p in (("ply~20", min(plies, key=lambda x: abs(x - 20))), ("final", plies[-1])):
        prof["hands"][f"{label} (ply {p})"] = H.render_hand(states[p]["view"]["blueprints"][opp], opp, color=False)
    return prof


# ----------------------------------------------------------------------------- analysis

def analyze(name, game, time_ms, jobs, threads, save, quiet=False):
    states, seat = game["states"], game["seat"]
    opp = 1 - seat
    plies = sorted(states)
    moves = {}
    for p in plies:
        d = game["decisions"].get(p)
        if p + 1 in states:
            m = infer_move(states[p]["view"], states[p + 1]["view"])
            moves[p] = m or (d or {}).get("move")
        elif d and P.turn_of(p) == seat:
            moves[p] = d.get("move")
    ours = [p for p in plies if P.turn_of(p) == seat and moves.get(p) and states[p]["view"].get("moves")]

    # Long searches: best (free) and played (restricted) at each of our plies.
    def job(p):
        st = states[p]
        return p, run_engine(st, time_ms, threads), run_engine(st, max(200, time_ms // 10), threads, only=moves[p])
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        results = {p: (b, pl) for p, b, pl in ex.map(job, ours)}

    issues = []
    # (b) missed captures + (c) eval loss per ply
    for p in ours:
        view = states[p]["view"]
        best_pts, best_m = best_capture(view)
        nxt = states.get(p + 1)
        got = (nxt["view"]["scores"][seat] - view["scores"][seat]) if nxt else None
        b, pl = results[p]
        if got is not None and best_pts > got:
            agrees = b.get("move") == moves[p]
            issues.append({"kind": "missed-capture", "ply": p, "sev": best_pts - got, "played": moves[p],
                           "better": best_m, "note": f"took {got} pts, {best_m} took {best_pts}"
                           + ("; long search ALSO skips it (likely deliberate)" if agrees else
                              f"; long search plays {b.get('move')}")})
        if "eval" in b and "eval" in pl and b.get("move") != moves[p]:
            loss = float(b["eval"]) - float(pl["eval"])
            if loss > 0:
                issues.append({"kind": "eval-loss", "ply": p, "sev": round(loss, 1), "played": moves[p],
                               "better": b.get("move"), "note": f"eval {pl['eval']} vs {b['eval']} for {b.get('move')}"})
    # (a) conceded on the opponent's next turn, by our turn
    turn_starts = [p for p in ours if p == 0 or P.turn_of(p - 1) != seat]
    for p0 in turn_starts:
        L = P.moves_left_in_turn(p0)
        end = p0 + L
        opp_end = end + P.moves_left_in_turn(end) if end < P.TOTAL_PLIES else end
        if end not in states or opp_end not in states:
            continue
        conceded = states[opp_end]["view"]["scores"][opp] - states[end]["view"]["scores"][opp]
        if conceded <= 0:
            continue
        actual_threat, _ = max_threat(states[end]["view"], opp)
        b = results.get(p0, ({}, {}))[0]
        s = P.from_view(states[p0]["view"])
        line = []
        for m in (b.get("pv") or [])[:L]:
            if m in P.legal_moves(s):
                s = P.play(s, m)
                line.append(m)
            else:
                break
        if len(line) < L:
            continue
        alt_threat, _ = max_threat(s, opp)
        if alt_threat < min(actual_threat, conceded):
            played = [moves.get(p0 + i) for i in range(L)]
            issues.append({"kind": "conceded", "ply": p0, "sev": min(conceded, actual_threat) - alt_threat,
                           "played": " ".join(m or "?" for m in played), "better": " ".join(line),
                           "note": f"opponent scored {conceded} next turn; engine line leaves max single capture "
                                   f"{alt_threat} vs {actual_threat}"})
    issues.sort(key=lambda i: (i["kind"] == "eval-loss", -i["sev"]))  # point losses first, then eval losses

    # Save positions
    saved = []
    if save:
        os.makedirs(POS_DIR, exist_ok=True)
        base = os.path.splitext(name)[0].replace("game-", "")
        pick = [i for i in issues if i["kind"] != "eval-loss"][:6] + [i for i in issues if i["kind"] == "eval-loss"][:6]
        for it in pick:
            st = states[it["ply"]]
            path = os.path.join(POS_DIR, f"{base}-p{it['ply']:03d}-{it['kind']}.json")
            with open(path, "w") as f:
                json.dump({"source": name, "ply": it["ply"], "seat": seat, "kind": it["kind"], "severity": it["sev"],
                           "played": it["played"], "engine_best": it["better"], "note": it["note"],
                           "state": {"you": [seat], "turn": st.get("turn"), "ply": st.get("ply"), "view": st["view"]}},
                          f, separators=(",", ":"))
            saved.append(os.path.relpath(path, REPO))

    # Report
    last = states[plies[-1]]["view"]
    res = last.get("result")
    out = io.StringIO()
    w = lambda s="": print(s, file=out)  # noqa: E731
    w(f"=== {name}: we were {NAMES[seat]}; plies {plies[0]}..{plies[-1]} logged; "
      f"final Blue {last['scores'][0]} - Red {last['scores'][1]}" + (f"; result {json.dumps(res)}" if res else ""))
    unknown = [p for p in plies[:-1] if p + 1 in states and not moves.get(p)]
    if unknown:
        w(f"  (could not reconstruct moves at plies {unknown[:10]})")
    if not issues:
        w("  No flagged mistakes.")
    pts = [i for i in issues if i["kind"] != "eval-loss"][:6]
    evl = [i for i in issues if i["kind"] == "eval-loss"][:5]
    if pts:
        w("  Point losses (points):")
    for i, it in enumerate(pts):
        w(f"  {i + 1:2d}. [{it['kind']}] ply {it['ply']}: -{it['sev']}  played {it['played']}  "
          f"better {it['better']}  ({it['note']})")
    if evl:
        w("  Biggest eval losses (engine units, long search):")
    for i, it in enumerate(evl):
        w(f"  {i + 1:2d}. ply {it['ply']}: -{it['sev']}  played {it['played']}  better {it['better']}  ({it['note']})")
    prof = opponent_profile(game, moves)
    w(f"  Opponent ({prof['seat']}): {prof['moves_seen']} moves seen, {prof['edits']} edits; "
      f"Fortlite edits matched {prof.get('fortlite_edits_matched', '?')}, "
      f"pieces equal to Fortlite target {prof.get('fortlite_hand_pieces_equal', '?')}/3")
    w(f"  Opponent snipers: {', '.join(prof['snipers']) or 'none'}")
    w(f"  Opponent first 10 moves: {' '.join(prof['first10'])}")
    w("  Stars over time (ply: stars B/R, scores B/R): " +
      "  ".join(f"{p}: {s[0]}/{s[1]} ({sc[0]}/{sc[1]})" for p, s, sc in prof["stars_over_time"]))
    for label, txt in prof["hands"].items():
        w(f"  Opponent hand {label}:")
        w("    " + txt.replace("\n", "\n    "))
    if saved:
        w(f"  Saved {len(saved)} positions: {', '.join(saved[:4])}{' ...' if len(saved) > 4 else ''}")
    return out.getvalue(), issues


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="game-*.jsonl, a folder of them, or a hexbot --logs zip")
    ap.add_argument("--time-ms", type=int, default=10000, help="long search budget per position (default 10000)")
    ap.add_argument("--jobs", type=int, default=4, help="positions searched in parallel")
    ap.add_argument("--seat", type=int, help="our seat if the log is ambiguous (0 Blue, 1 Red)")
    ap.add_argument("--no-save", action="store_true", help="don't write lab/positions/*.json")
    args = ap.parse_args()
    if not os.path.isfile(ENGINE):
        raise SystemExit("build the engine first: engine/build.sh")
    threads = max(1, (os.cpu_count() or 4) // args.jobs)
    total = []
    for name, recs in read_logs(args.path):
        game = game_from_records(recs, args.seat)
        if not game:
            continue
        text, issues = analyze(name, game, args.time_ms, args.jobs, threads, not args.no_save)
        print(text, flush=True)
        total += [(name, i) for i in issues]
    if len(total) > 1:
        print("=== Worst across all games ===")
        for name, it in sorted(total, key=lambda x: (x[1]["kind"] == "eval-loss", -x[1]["sev"]))[:10]:
            print(f"  {name} ply {it['ply']} [{it['kind']}] severity {it['sev']}: {it['note']}")


if __name__ == "__main__":
    main()
