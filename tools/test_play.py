#!/usr/bin/env python3
"""Tests for `hexbot --play` / `--replay` (client/play.py) driven by a scripted stdin game.

  python3 tools/test_play.py                 # all tests (the CLI test uses engine/bp when it exists)
  python3 tools/test_play.py --emit-script   # print the scripted stdin game for Blue (used by CI)

The script only uses moves that are legal whatever the engine plays: Blue's opening placement at ply 0
and then blueprint edits, which depend on Blue's own hand only. It also exercises help, moves, hint,
illegal input and both kinds of undo (mid-turn and at the start of the next turn).
"""
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "client"))
import bprules as P  # noqa: E402
import play  # noqa: E402

OPENING = "2@0,-4"


def edit_sequence(seat, n):
    hand = P.setup()["blueprints"][seat]
    out = []
    for _ in range(n):
        m = P.edit_moves(hand)[0]
        out.append(m)
        mm = P._parse_move(m)
        hand = P.apply_edit(hand, mm["from"], mm["to"])
    return out


def script_lines():
    e = edit_sequence(0, 70)
    return (["help", "moves cap", "moves 2@", "9@0,0", "1:9,9>2:0,0", "hint", OPENING,
             e[0], "undo", e[0], e[1],       # mid-turn undo, then finish the turn
             "undo", e[0], e[1]]             # start-of-turn undo takes back the whole previous turn
            + e[2:])


def fake_engine(view, time_ms):
    m = P.best_capture_move(view)
    return {"move": m, "top": [{"move": x} for x in view["moves"][:3]], "source": "fake"}


def test_full_game_fake_engine(home):
    os.environ["HOME"] = home
    out = io.StringIO()
    g = play.LocalGame(fake_engine, 0, 10, inp=io.StringIO("\n".join(script_lines()) + "\n"), out=out)
    res = g.run()
    text = out.getvalue()
    assert res["verdict"] in ("won", "lost", "draw"), res["verdict"]
    assert len(res["moves"]) == P.TOTAL_PLIES, len(res["moves"])
    for needle in ("Commands: <move>", "Not legal: there is no blueprint #9", "Not legal: blueprint #1 has no cell 9,9",
                   "Engine's top moves for you:", "Took back your last turn.", "Engine plays", "GAME OVER:",
                   "Ply 0/120 (no clock)", "Blue hand (you):", "Red hand (engine):", "2@0,-4 "):
        assert needle in text, needle
    assert res["path"] and os.path.dirname(res["path"]) == os.path.join(home, ".hexbot", "games"), res["path"]
    with open(res["path"]) as f:
        saved = json.load(f)
    assert saved["moves"] == res["moves"] and saved["human"] == "blue" and saved["verdict"] == res["verdict"]
    # Moves were replayed through the rules: the saved list must reproduce the final scores.
    st = P.setup()
    for m in saved["moves"]:
        st = P.play(st, m)
    assert st["scores"] == saved["scores"], (st["scores"], saved["scores"])
    rout = io.StringIO()
    play.replay(res["path"], inp=io.StringIO(""), out=rout)
    rtext = rout.getvalue()
    assert "Final: Blue" in rtext and f"ply {P.TOTAL_PLIES - 1:3d}" in rtext, rtext[-500:]
    print("ok full game (fake engine):", res["verdict"], res["scores"], os.path.basename(res["path"]))


def test_undo_and_quit(home):
    os.environ["HOME"] = home
    e = edit_sequence(1, 4)
    out = io.StringIO()
    # Red: the engine opens; undo before any move of ours is refused; EOF counts as quit and saves.
    g = play.LocalGame(fake_engine, 1, 10, inp=io.StringIO("undo\n" + "\n".join([e[0], e[1], e[2], "undo"]) + "\n"),
                       out=out)
    res = g.run()
    text = out.getvalue()
    assert "Nothing to undo yet." in text
    assert res["verdict"] == "abandoned", res
    # engine ply 0, our e0 e1 (plies 1-2), engine plies 3-4, our e2 at ply 5 taken back by the mid-turn undo
    assert len(res["moves"]) == 5 and res["moves"][1:3] == [e[0], e[1]], res["moves"]
    assert res["path"] and os.path.isfile(res["path"])
    print("ok undo/quit:", res["moves"])


def test_cli_real_engine(home):
    eng = os.path.join(REPO, "engine", "bp" + (".exe" if os.name == "nt" else ""))
    if not os.path.isfile(eng):
        print("skip CLI test: no engine/bp (build it with engine/build.sh)")
        return
    env = dict(os.environ, HOME=home, NO_COLOR="1")
    p = subprocess.run([sys.executable, os.path.join(REPO, "client", "bot.py"), "--play", "blue", "--time-ms", "50"],
                       input="\n".join(script_lines()) + "\n", capture_output=True, text=True, env=env, timeout=600)
    assert p.returncode == 0, p.stderr[-1000:]
    assert "GAME OVER:" in p.stdout and "Engine plays" in p.stdout, p.stdout[-2000:]
    assert "engine not found" not in p.stdout and "engine failed" not in p.stdout, p.stdout[-2000:]
    saved = [ln.split("Saved game to ", 1)[1].strip() for ln in p.stdout.splitlines() if ln.startswith("Saved game to ")]
    assert saved and os.path.isfile(saved[0]), p.stdout[-1000:]
    r = subprocess.run([sys.executable, os.path.join(REPO, "client", "bot.py"), "--replay", saved[0]],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0 and "Final: Blue" in r.stdout, (r.stdout[-800:], r.stderr[-800:])
    print("ok CLI vs real engine:", [ln for ln in p.stdout.splitlines() if "GAME OVER" in ln][0].strip())


def main():
    if "--emit-script" in sys.argv:
        print("\n".join(script_lines()))
        return
    with tempfile.TemporaryDirectory() as home:
        old = os.environ.get("HOME")
        try:
            test_full_game_fake_engine(home)
            test_undo_and_quit(home)
            test_cli_real_engine(home)
        finally:
            if old is not None:
                os.environ["HOME"] = old
    print("all play tests passed")


if __name__ == "__main__":
    main()
