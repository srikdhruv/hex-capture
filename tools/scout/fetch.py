#!/usr/bin/env python3
"""Scout: harvest Blueprints games by OTHER players into lab/games/<room>.json.

Sources
  --import-logs          our own bot logs (client/logs/game-<room>.jsonl): full move lists vs real opponents.
  --top N                top-N players of the tournament standings (public), then each player's
                         /api/history -> /api/games/<room>/record.  Needs the BROWSER session cookie.
  --players a,b,c        same, for named players.
  --rooms r1,r2          fetch these 64-hex rooms' records directly (cookie).

Auth
  The web API (history, record, players) only accepts the logged-in browser session cookie; the engine
  Bearer token is NOT accepted there (401).  Put the full "Cookie:" request-header value from DevTools
  (any strategyjam.org/api/me request) into ~/.hexbot/cookie (chmod 600) or env SJ_COOKIE.
  The cookie is only ever placed in request headers; it is never printed or written anywhere.

Politeness: <= 1 request / 1.1 s, honours Retry-After on 429/503, no redirects followed.

Output: lab/games/<room>.json =
  {room, source, game, tournament:{id,round,board}, players:[n0,n1], modes, moves:[...], times:[...],
   result:{winner,reason}, scores:[s0,s1]|null, startedAt, endedAt}
  plus lab/games/_standings.json (rank snapshot used by analyze.py).
"""
import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "lab", "games")
BASE = "https://strategyjam.org"
TID = "f46b70969dee"
UA = "hexscout/1.0 (+https://github.com/srikdhruv/hex-capture)"  # default urllib UA is blocked (CF 1010)
MIN_GAP = 1.1


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # never forward credentials to another location


_opener = urllib.request.build_opener(_NoRedirect)
_last = [0.0]


def load_cookie():
    c = os.environ.get("SJ_COOKIE", "").strip()
    p = os.path.expanduser("~/.hexbot/cookie")
    if not c and os.path.isfile(p):
        with open(p) as f:
            c = f.read().strip()
    if c.lower().startswith("cookie:"):
        c = c[7:].strip()
    return c or None


def get(path, cookie=None, tries=5):
    """GET json; returns (status, body). Rate-limited and 429-aware."""
    for attempt in range(tries):
        wait = _last[0] + MIN_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        hdr = {"User-Agent": UA, "Accept": "application/json"}
        if cookie:
            hdr["Cookie"] = cookie
        req = urllib.request.Request(BASE + path, headers=hdr)
        try:
            _last[0] = time.time()
            with _opener.open(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                ra = e.headers.get("Retry-After")
                delay = float(ra) if ra and ra.replace(".", "").isdigit() else 5 * (attempt + 1)
                print(f"  {e.code} on {path.split('?')[0]}; backing off {delay:.0f}s", file=sys.stderr)
                time.sleep(min(delay, 120))
                continue
            try:
                body = json.loads(e.read().decode())
            except Exception:
                body = None
            return e.code, body
        except Exception as e:  # network hiccup
            print(f"  error on {path.split('?')[0]}: {type(e).__name__}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    return 0, None


def save(game):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, game["room"] + ".json")
    with open(p, "w") as f:
        json.dump(game, f, separators=(",", ":"))
    return p


def have(room):
    return os.path.isfile(os.path.join(OUT, room + ".json"))


# ---------- standings (public)
def standings(top):
    rows, page = [], 0
    while len(rows) < top:
        st, body = get(f"/api/tournaments/{TID}?page={page}")
        if st != 200 or not body:
            break
        s = body.get("standings") or {}
        rows += s.get("rows") or []
        page += 1
        if page >= s.get("pages", 0):
            break
    snap = {"at": int(time.time() * 1000), "round": (body or {}).get("standings", {}).get("round"),
            "rows": rows}
    os.makedirs(OUT, exist_ok=True)
    old = os.path.join(OUT, "_standings.json")
    # keep the largest snapshot of the same round
    try:
        prev = json.load(open(old))
        if prev.get("round") == snap["round"] and len(prev.get("rows", [])) > len(rows):
            snap = prev
    except Exception:
        pass
    with open(old, "w") as f:
        json.dump(snap, f, separators=(",", ":"))
    return rows[:top]


# ---------- round pairings (public): every game's room id, board 1 = top table
def rounds_index(upto=None, max_pages=30):
    """GET /api/tournaments/<tid>/rounds/<n>?page=p for n=1..upto; caches finished rounds in _rounds.json."""
    path = os.path.join(OUT, "_rounds.json")
    try:
        idx = json.load(open(path))
    except Exception:
        idx = {}
    if upto is None:
        st, body = get(f"/api/tournaments/{TID}?page=0")
        upto = (body or {}).get("round") or 1
    for n in range(1, upto + 1):
        cached = idx.get(str(n))
        if cached and cached.get("complete"):
            continue
        games, page, pages = [], 0, 1
        while page < pages and page < max_pages:
            st, body = get(f"/api/tournaments/{TID}/rounds/{n}?page={page}")
            if st != 200 or not body:
                break
            games += body.get("games") or []
            pages = body.get("pages", 1)
            page += 1
        if games:
            idx[str(n)] = {"games": games, "complete": all(g.get("scores") or not g.get("room") for g in games)}
    os.makedirs(OUT, exist_ok=True)
    with open(path, "w") as f:
        json.dump(idx, f, separators=(",", ":"))
    return idx


# ---------- record -> normalized game
def from_record(room, rec, source="record"):
    players = rec.get("players") or []
    t = rec.get("tournament") or {}
    res = rec.get("result")
    return {
        "room": room, "source": source, "game": rec.get("game", "blueprints"),
        "tournament": {k: t.get(k) for k in ("id", "round", "board")} if t else None,
        "players": [p.get("name") for p in players], "modes": [p.get("mode", "human") for p in players],
        "moves": [m["move"] if isinstance(m, dict) else m for m in rec.get("moves", [])],
        "times": [m.get("at") for m in rec.get("moves", []) if isinstance(m, dict)],
        "result": res, "scores": (res or {}).get("scores") if isinstance(res, dict) else None,
        "startedAt": rec.get("startedAt"), "endedAt": rec.get("endedAt"), "version": rec.get("version"),
    }


def fetch_room(room, cookie, meta=None):
    if have(room):
        return "have"
    st, rec = get(f"/api/games/{room}/record", cookie)
    if st != 200 or not rec:
        return f"http {st}"
    g = from_record(room, rec)
    if meta:
        g["history_meta"] = meta
    save(g)
    return "ok"


def history(player, cookie, tid=TID, max_pages=4):
    """All games of a player (newest first), paged by `before`."""
    out, before = [], None
    for _ in range(max_pages):
        q = {"game": "blueprints", "player": player}
        if before:
            q["before"] = str(before)
        st, body = get("/api/history?" + urllib.parse.urlencode(q), cookie)
        if st != 200 or not isinstance(body, list):
            if st == 401:
                raise SystemExit("history: 401 unauthenticated - cookie missing/expired (~/.hexbot/cookie)")
            break
        out += body
        if len(body) < 50:
            break
        before = body[-1].get("startedAt")
    if tid:
        out = [g for g in out if (g.get("tournament") or {}).get("id") == tid]
    return out


def import_logs():
    n = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "client", "logs", "game-*.jsonl"))):
        room = os.path.basename(p)[5:-6]
        if len(room) != 64:
            continue
        last = None
        with open(p) as f:
            for line in f:
                if '"type":"state"' not in line:
                    continue
                try:
                    st = json.loads(line)["state"]
                except Exception:
                    continue
                if st.get("history") is not None:
                    last = st
        if not last or not last.get("history"):
            continue
        v = last.get("view") or {}
        t = last.get("tournament") or {}
        g = {"room": room, "source": "ourlog", "game": "blueprints",
             "tournament": {k: t.get(k) for k in ("id", "round", "board")} if t else None,
             "players": last.get("seats"), "modes": last.get("modes"), "moves": last["history"],
             "times": last.get("times"), "result": v.get("result"), "scores": v.get("scores"),
             "finished": bool(v.get("result")), "startedAt": (last.get("clock") or {}).get("startedAt")}
        save(g)
        n += 1
    print(f"imported {n} games from our logs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--import-logs", action="store_true")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--players", default="")
    ap.add_argument("--rooms", default="")
    ap.add_argument("--rounds", action="store_true", help="index all rounds' pairings (public) and fetch top boards")
    ap.add_argument("--boards", type=int, default=40, help="with --rounds: fetch boards 1..N of each round")
    ap.add_argument("--all-games", action="store_true", help="include non-tournament games from history")
    ap.add_argument("--max-games", type=int, default=400)
    a = ap.parse_args()
    if a.import_logs:
        import_logs()
    names = [x for x in a.players.split(",") if x]
    if a.top:
        rows = standings(a.top)
        print(f"standings: {len(rows)} rows; top: {', '.join(r['name'] for r in rows[:10])}")
        names += [r["name"] for r in rows]
    rooms = [x for x in a.rooms.split(",") if x]
    if a.rounds:
        idx = rounds_index()
        print("rounds indexed:", {k: len(v["games"]) for k, v in idx.items()})
        # newest rounds first (top players are best separated late), top boards first
        for k in sorted(idx, key=int, reverse=True):
            for g in sorted(idx[k]["games"], key=lambda g: g.get("board", 9999)):
                if g.get("room") and g.get("scores") and g.get("board", 9999) <= a.boards and g.get("reason") in ("higher score", "resignation", "tied score", "away"):
                    rooms.append(g["room"])
    if not (names or rooms):
        return
    cookie = load_cookie()
    if not cookie:
        print("no browser cookie (~/.hexbot/cookie or SJ_COOKIE): history/record need it. Standings saved only.")
        return
    got = 0
    for r in rooms:
        if got >= a.max_games:
            break
        s = fetch_room(r, cookie)
        got += s == "ok"
        if s not in ("ok", "have"):
            print(r[:12], s)
            if s == "http 401":
                raise SystemExit("record: 401 unauthenticated - browser cookie missing/expired (~/.hexbot/cookie)")
    seen = set()
    for name in names:
        if got >= a.max_games:
            break
        games = history(name, cookie, tid=None if a.all_games else TID)
        new = [g for g in games if g.get("id") and g["id"] not in seen]
        print(f"{name}: {len(games)} games, {sum(not have(g['id']) for g in new)} new")
        for g in new:
            seen.add(g["id"])
            if have(g["id"]):
                continue
            s = fetch_room(g["id"], cookie, meta=g)
            got += s == "ok"
            if s != "ok":
                print("  ", g["id"][:12], s)
    print(f"fetched {got} new records into {OUT}")


if __name__ == "__main__":
    main()
