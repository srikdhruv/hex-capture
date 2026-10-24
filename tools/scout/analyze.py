#!/usr/bin/env python3
"""Scout analysis: replay every lab/games/<room>.json with the reference rules (tools/scout/replay.mjs)
and summarise what each player does, joined with the tournament standings snapshot.

  python3 tools/scout/analyze.py [--jobs 2] [--seal-every 4] [--player NAME] [--out lab/games/_report.txt]

Per player-game: opening edit sequence (first 20 plies), hand at ply 20, walls over time, seal curve
(min walls still needed to seal all own stars; 0 = sealed), first capture ply, points by phase,
stamp usage (which blueprint, its composition, wall-only stamps, snipes), stars.
Replays are cached in lab/games/.cache/<room>.json (keyed by move count).
"""
import argparse
import collections
import glob
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAMES = os.path.join(ROOT, "lab", "games")
CACHE = os.path.join(GAMES, ".cache")
REPLAY = os.path.join(ROOT, "tools", "scout", "replay.mjs")
PHASES = [(0, 20, "open"), (20, 60, "race"), (60, 100, "mid"), (100, 120, "end")]
US = {"srik"}


def replay(path, seal_every):
    g = json.load(open(path))
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, os.path.basename(path))
    if os.path.isfile(cp):
        c = json.load(open(cp))
        if len(c.get("plies", [])) == len(g["moves"]) or c.get("err"):
            return c
    out = subprocess.run(["nice", "-n", "10", "node", REPLAY, path], capture_output=True, text=True,
                         env={**os.environ, "SEAL_EVERY": str(seal_every)}, timeout=600)
    line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else None
    if not line:
        return {"room": g["room"], "err": out.stderr[-300:]}
    c = json.loads(line)
    with open(cp, "w") as f:
        f.write(line)
    return c


def ranks():
    try:
        s = json.load(open(os.path.join(GAMES, "_standings.json")))
        return {r["name"]: r for r in s["rows"]}, s.get("round")
    except Exception:
        return {}, None


def at(plies, ply, field, seat):
    """value of field[seat] after the last action with index < ply (state at ply)."""
    v = None
    for p in plies:
        if p["ply"] >= ply:
            break
        if field in p:
            v = p[field][seat]
    return v


def player_game(r, seat):
    pl = r["plies"]
    me = [p for p in pl if p["seat"] == seat]
    opp = 1 - seat
    res = r.get("result") or {}
    sc = r["scores"]
    d = {
        "room": r["room"], "name": r["players"][seat], "opp": r["players"][opp], "seat": "BR"[seat],
        "round": (r.get("tournament") or {}).get("round"),
        "score": sc[seat], "oppScore": sc[opp], "plies": r["ply"],
        "won": None if not res else (res.get("winner") == seat),
    }
    op = [p for p in me if p["ply"] < 20]
    d["opening"] = " ".join(p["move"] for p in op)
    d["openEdits"] = sum(p["kind"] == "edit" for p in op)
    first_place = next((p["ply"] for p in me if p["kind"] == "place"), None)
    d["firstPlace"] = first_place
    d["edits"] = sum(p["kind"] == "edit" for p in me)
    d["places"] = sum(p["kind"] == "place" for p in me)
    d["passes"] = sum(p["kind"] == "pass" for p in me)
    d["hand20"] = (r.get("hands") or {}).get("20", ["?", "?"])[seat]
    d["handFinal"] = (r.get("hands") or {}).get("final", ["?", "?"])[seat]
    d["walls"] = {k: at(pl, k, "walls", seat) for k in (20, 40, 60, 80, 120)}
    d["stars"] = {k: at(pl, k, "stars", seat) for k in (20, 40, 60, 120)}
    d["oppStars"] = {k: at(pl, k, "stars", opp) for k in (20, 40, 60, 120)}
    seal = [(p["ply"] + 1, p["seal"][seat] if p["stars"][seat] else None) for p in pl if "seal" in p]
    d["seal"] = {k: next((v for q, v in reversed(seal) if q <= k), None) for k in (20, 40, 60, 80, 120)}
    d["sealedPly"] = next((q for q, v in seal if v == 0), None)
    d["oppSealedPly"] = next((p["ply"] + 1 for p in pl if "seal" in p and p["stars"][opp] and p["seal"][opp] == 0), None)
    d["open"] = {k: at(pl, k, "open", seat) for k in (20, 40, 60, 120)}
    caps = [p for p in me if p.get("pts", 0) > 0]
    d["firstCapture"] = caps[0]["ply"] if caps else None
    d["firstCaptureMove"] = caps[0]["move"] if caps else None
    lost = [p for p in pl if p["seat"] == opp and p.get("pts", 0) > 0]
    d["firstConceded"] = lost[0]["ply"] if lost else None
    d["captures"] = len(caps)
    d["phasePts"] = {n: sum(p.get("pts", 0) for p in me if a <= p["ply"] < b) for a, b, n in PHASES}
    d["oppPhasePts"] = {n: sum(p.get("pts", 0) for p in pl if p["seat"] == opp and a <= p["ply"] < b)
                        for a, b, n in PHASES}
    stamps = [p for p in me if p["kind"] == "place"]
    d["stampComps"] = collections.Counter(p["comp"] for p in stamps).most_common(4)
    d["wallOnlyStamps"] = sum(1 for p in stamps if p["comp"].split(":")[1].startswith("0s") and "0p" in p["comp"])
    d["snipes"] = sum(1 for p in stamps if int(p["comp"].split("c")[0]) <= 3 and p.get("starsRemoved", 0) > 0)
    d["starsTaken"] = sum(p.get("starsRemoved", 0) for p in stamps)
    d["bigCaps"] = sorted(((p.get("pts", 0), p["ply"], p["move"]) for p in caps), reverse=True)[:3]
    d["editCells"] = collections.Counter(f'{p.get("cell")}:{p.get("from")}>{p.get("to")}' for p in me
                                         if p["kind"] == "edit").most_common(5)
    d["arch"], d["rusher"] = classify(d, stamps)
    d["wwwStamps"] = [f'{p["ply"]}:{p["move"]}' for p in stamps if _comp(p["comp"])[1] == 0 and _comp(p["comp"])[3] == 0]
    d["board"] = (r.get("tournament") or {}).get("board")
    d["editSeq"] = " ".join(p["move"] for p in me if p["kind"] == "edit")
    return d


def _comp(c):
    n, rest = c.split("c:")
    st, rest = rest.split("s")
    w, rest = rest.split("w")
    return int(n), int(st), int(w), int(rest.rstrip("p"))


ARCHS = ["sealer", "fortress", "blob", "stick", "mixed"]


def classify(d, stamps):
    """Archetype from what a player STAMPS (see lab/games/_terms.txt):
    sealer   : >=50% wall-only stamps (www/ww/w) and <=15 stars on board at ply 40
    fortress : dominant stamp >=12 cells with 4-6 stars wrapped in >= as many plains (Fortlite-like)
    blob     : >=40% of stamps carry >=3 stars (compact star flowers, star-flood)
    stick    : >=30% of stamps are plain-only pieces of >=4 cells (long probes/lines)
    mixed    : anything else.  rusher = first stamp by ply 2 with <=1 edit before it (opening tag)."""
    rusher = (d["firstPlace"] is not None and d["firstPlace"] <= 2 and d["openEdits"] <= 1)
    if not stamps:
        return "mixed", rusher
    cs = [_comp(p["comp"]) for p in stamps]
    n = len(cs)
    wall_only = sum(1 for c in cs if c[1] == 0 and c[3] == 0)
    if wall_only >= 0.5 * n and (d["stars"][40] or 0) <= 15:
        return "sealer", rusher
    dom = collections.Counter(p["comp"] for p in stamps).most_common(1)[0][0]
    c = _comp(dom)
    if c[0] >= 12 and 4 <= c[1] <= 6 and c[3] >= c[1]:
        return "fortress", rusher
    if sum(1 for c in cs if c[1] >= 3) >= 0.4 * n:
        return "blob", rusher
    if sum(1 for c in cs if c[1] == 0 and c[2] == 0 and c[0] >= 4) >= 0.3 * n:
        return "stick", rusher
    return "mixed", rusher


def pairs(rows, maxboard=None):
    games = collections.defaultdict(dict)
    for d in rows:
        games[d["room"]][d["seat"]] = d
    for g in games.values():
        if len(g) == 2 and g["B"]["won"] is not None and (not maxboard or (g["B"]["board"] or 999) <= maxboard):
            yield g["B"], g["R"]


def deep(rows):
    out = []
    # (1) how sealers lose
    ls = [(x, y) for a, b in pairs(rows) for x, y in ((a, b), (b, a)) if x["arch"] == "sealer"]
    lost = [(x, y) for x, y in ls if not x["won"]]
    won = [(x, y) for x, y in ls if x["won"]]
    out.append(f"SEALER RESULTS: {len(won)}W / {len(lost)}L")
    out.append("  sealer losses by opponent archetype: " + str(collections.Counter(y["arch"] for x, y in lost).most_common()))
    out.append("  sealer wins by opponent archetype:   " + str(collections.Counter(y["arch"] for x, y in won).most_common()))
    def stat(L, f):
        v = [f(x, y) for x, y in L]
        v = [t for t in v if t is not None]
        return f"{round(100 * sum(v) / len(v))}% of {len(v)}" if v else "-"
    for lab, L in (("won", won), ("lost", lost)):
        out.append(f"  sealer {lab}: sealed itself {stat(L, lambda x, y: x['sealedPly'] is not None)}, "
                   f"conceded a capture before ply 40 {stat(L, lambda x, y: (x['firstConceded'] or 999) < 40)}, "
                   f"captured first {stat(L, lambda x, y: (x['firstCapture'] or 999) < (y['firstCapture'] or 999))}, "
                   f"opp sealed {stat(L, lambda x, y: y['sealedPly'] is not None)}; "
                   f"mean walls@40 {mean([x['walls'][40] for x, y in L])} vs opp {mean([y['walls'][40] for x, y in L])}; "
                   f"mean seal-need@40 {mean([x['seal'][40] for x, y in L])}")
    # (2) sealer vs sealer determinants
    ss = [(a, b) for a, b in pairs(rows) if a["arch"] == "sealer" and b["arch"] == "sealer"]
    out.append(f"SEALER vs SEALER: {len(ss)} games")
    def det(name, f):
        n = k = 0
        for a, b in ss:
            fa, fb = f(a), f(b)
            if fa is None and fb is None or fa == fb:
                continue
            better = a if (fb is None or (fa is not None and fa < fb)) else b
            n += 1
            k += better["won"]
        return f"  side with earlier {name} wins {k}/{n}" + (f" ({round(100 * k / n)}%)" if n else "")
    out.append(det("first capture", lambda d: d["firstCapture"]))
    out.append(det("seal (sealedPly)", lambda d: d["sealedPly"]))
    out.append(det("seal-need@40 (lower)", lambda d: d["seal"][40]))
    out.append(det("FEWER stars@40 (lower)", lambda d: d["stars"][40]))
    out.append(det("MORE walls@40", lambda d: -(d["walls"][40] or 0)))
    bw = sum(a["won"] for a, b in ss)
    out.append(f"  Blue wins {bw}/{len(ss)}")
    return "\n".join(out)


def www_patterns(rows, rk, top=16, n=8):
    out = [f"FIRST {n} WALL-ONLY STAMPS OF TOP-{top} SEALERS (move strings, with ply):"]
    for d in rows:
        if d["arch"] != "sealer" or rk.get(d["name"], {}).get("rank", 10 ** 6) > top:
            continue
        out.append(f"  #{rk[d['name']]['rank']} {d['name']} ({d['seat']}, R{d['round']}, {'W' if d['won'] else 'L'}): "
                   + " ".join(d.get("wwwStamps", [])[:n]))
    return "\n".join(out)


def matchups(rows, rk, maxboard=None):
    by = collections.defaultdict(lambda: [0, 0])
    games = collections.defaultdict(dict)
    for d in rows:
        games[d["room"]][d["seat"]] = d
    for room, g in games.items():
        if len(g) != 2:
            continue
        a, b = g["B"], g["R"]
        if a["won"] is None or (maxboard and (a["board"] or 999) > maxboard):
            continue
        for x, y in ((a, b), (b, a)):
            k = (x["arch"], y["arch"])
            by[k][0] += x["won"]
            by[k][1] += 1
    out = [f"archetype matchups{' (boards <= %d)' % maxboard if maxboard else ''}: row vs col = wins/games"]
    archs = ARCHS
    out.append("          " + "".join(f"{c:>12}" for c in archs))
    for r_ in archs:
        out.append(f"{r_:10}" + "".join(f'{"%d/%d" % tuple(by[(r_, c)]) if by[(r_, c)][1] else "-":>12}' for c in archs))
    return "\n".join(out)


def openings(rows, rk, top=64):
    good = [d for d in rows if rk.get(d["name"], {}).get("rank", 10 ** 6) <= top]
    out = [f"hand@20 among top-{top} player-games (count, win%):"]
    c = collections.defaultdict(list)
    for d in good:
        c[d["hand20"]].append(d["won"])
    for h, ws in sorted(c.items(), key=lambda kv: -len(kv[1]))[:12]:
        w = [x for x in ws if x is not None]
        out.append(f"  {len(ws):3} {round(100 * sum(w) / len(w)) if w else '-':>4}%  {h}")
    out.append(f"archetype share among top-{top}: " + str(collections.Counter(d["arch"] for d in good).most_common()))
    out.append("archetype by player (top 16):")
    pa = collections.defaultdict(collections.Counter)
    for d in rows:
        if rk.get(d["name"], {}).get("rank", 10 ** 6) <= 16:
            pa[d["name"]][d["arch"]] += 1
    for n, cnt in sorted(pa.items(), key=lambda kv: rk[kv[0]]["rank"]):
        out.append(f"  #{rk[n]['rank']} {n}: {dict(cnt)}")
    return "\n".join(out)


def fmt(d, rk):
    r = rk.get(d["name"], {})
    w = {True: "W", False: "L", None: "?"}[d["won"]]
    return (f'#{r.get("rank", "-")} {d["name"]} ({d["seat"]}, R{d["round"]}) {w} {d["score"]}-{d["oppScore"]} vs '
            f'{d["opp"]} (#{rk.get(d["opp"], {}).get("rank", "-")})\n'
            f'   [{d["arch"]}] opening[{d["openEdits"]} edits, 1st stamp ply {d["firstPlace"]}]: {d["opening"]}\n'
            f'   hand@20: {d["hand20"]}   final: {d["handFinal"]}\n'
            f'   walls@20/40/60/80/end: {list(d["walls"].values())}  seal-need@20/40/60/80/end: {list(d["seal"].values())}'
            f'  sealed@{d["sealedPly"]} (opp sealed@{d["oppSealedPly"]})\n'
            f'   stars@20/40/60/end: {list(d["stars"].values())} (open {list(d["open"].values())}) opp {list(d["oppStars"].values())}\n'
            f'   1st capture ply {d["firstCapture"]} ({d["firstCaptureMove"]}), 1st conceded {d["firstConceded"]}; '
            f'caps {d["captures"]}, snipes {d["snipes"]}, stars taken {d["starsTaken"]}; pts/phase {d["phasePts"]} '
            f'opp {d["oppPhasePts"]}\n'
            f'   stamps {d["places"]} edits {d["edits"]} passes {d["passes"]} wall-only {d["wallOnlyStamps"]}; '
            f'comps {d["stampComps"]}; big caps {d["bigCaps"]}\n')


def tier(rank):
    if rank is None:
        return "unranked"
    return "top16" if rank <= 16 else "17-64" if rank <= 64 else "65-200" if rank <= 200 else "200+"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def aggregate(rows, rk):
    groups = collections.defaultdict(list)
    for d in rows:
        if d["name"] in US:
            groups["US(srik)"].append(d)
            continue
        groups[tier(rk.get(d["name"], {}).get("rank"))].append(d)
        if d["won"] is not None:
            groups["winners" if d["won"] else "losers"].append(d)
    out = ["group      n  win%  openEdits 1stStamp walls@40 walls@end seal@40 seal@60 sealedPly(%sealed) "
           "1stCap snipes wallOnly pts(open/race/mid/end)"]
    for d in rows:
        groups["A:" + d["arch"]].append(d)
        if d["rusher"]:
            groups["A:rusher"].append(d)
    for g in ("top16", "17-64", "65-200", "200+", "unranked", "winners", "losers", "US(srik)",
              "A:sealer", "A:fortress", "A:blob", "A:stick", "A:mixed", "A:rusher"):
        L = groups.get(g)
        if not L:
            continue
        won = [d["won"] for d in L if d["won"] is not None]
        sealed = [d["sealedPly"] for d in L if d["sealedPly"] is not None]
        out.append(
            f'{g:9} {len(L):3} {round(100 * sum(won) / len(won)) if won else "-":>4}  '
            f'{mean([d["openEdits"] for d in L]):>8} {mean([d["firstPlace"] for d in L]):>8} '
            f'{mean([d["walls"][40] for d in L]):>8} {mean([d["walls"][120] for d in L]):>8} '
            f'{mean([d["seal"][40] for d in L]):>7} {mean([d["seal"][60] for d in L]):>7} '
            f'{mean(sealed)!s:>9}({round(100 * len(sealed) / len(L))}%) '
            f'{mean([d["firstCapture"] for d in L])!s:>6} {mean([d["snipes"] for d in L]):>6} '
            f'{mean([d["wallOnlyStamps"] for d in L]):>8} '
            + "/".join(str(mean([d["phasePts"][n] for d in L])) for _, _, n in PHASES))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--seal-every", type=int, default=4)
    ap.add_argument("--player", default="")
    ap.add_argument("--out", default=os.path.join(GAMES, "_report.txt"))
    a = ap.parse_args()
    paths = sorted(p for p in glob.glob(os.path.join(GAMES, "*.json")) if not os.path.basename(p).startswith("_"))
    with ThreadPoolExecutor(max_workers=max(1, min(a.jobs, 2))) as ex:
        reps = list(ex.map(lambda p: replay(p, a.seal_every), paths))
    rk, rnd = ranks()
    rows = []
    for r in reps:
        if r.get("err") or not r.get("plies"):
            print("skip", r.get("room", "?")[:12], r.get("err"), file=sys.stderr)
            continue
        if r.get("claimedScores") and r["claimedScores"] != r["scores"]:
            print("WARN score mismatch", r["room"][:12], r["claimedScores"], r["scores"], file=sys.stderr)
        for s in (0, 1):
            rows.append(player_game(r, s))
    rows.sort(key=lambda d: (rk.get(d["name"], {}).get("rank", 10 ** 6), d["round"] or 0))
    if a.player:
        rows = [d for d in rows if d["name"] == a.player]
    txt = [f"SCOUT REPORT: {len(reps)} games, {len(rows)} player-games; standings snapshot after round {rnd}", "",
           aggregate(rows, rk), "", matchups(rows, rk), "", matchups(rows, rk, 20), "", openings(rows, rk), "",
           deep(rows), "", www_patterns(rows, rk), "",
           "PER PLAYER-GAME (sorted by standing):", ""]
    txt += [fmt(d, rk) for d in rows]
    s = "\n".join(txt)
    with open(a.out, "w") as f:
        f.write(s)
    with open(os.path.join(GAMES, "_playergames.json"), "w") as f:
        json.dump(rows, f, separators=(",", ":"))
    print(s)


if __name__ == "__main__":
    main()
