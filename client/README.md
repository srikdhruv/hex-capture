# Blueprints tournament client

`client/bot.py` connects to StrategyJam, checks in every round of the tournament, watches the
assigned board, and plays a move whenever it is our turn. It also plays standalone challenges and
"Test your engine" self-test games.

> **Engine label warning:** the first accepted engine move permanently tags your tournament entry as **Engine** for the whole tournament.

## 1. Get a token

1. Log in at https://strategyjam.org, open your **profile**.
2. Under supported games, select **Blueprints**, then click **Connect engine**.
3. Copy the token. It is shown **once** and expires after **24h**. Don't paste it anywhere public.

## 2. Install (once)

```bash
cd ~/hex-capture
python3 -m venv client/.venv
client/.venv/bin/pip install -r client/requirements.txt
```

You also need `node` (v18+) for the fallback policy and tools.

## 3. Run

```bash
cd ~/hex-capture
export STRATEGYJAM_TOKEN='paste-token-here'   # never logged by the bot
client/.venv/bin/python client/bot.py
```

Defaults: `STRATEGYJAM_URL=https://strategyjam.org`, `TOURNAMENT_ID=f46b70969dee`,
engine `engine/bp` (falls back to `node tools/greedy.mjs` if the engine is missing or fails),
`MOVE_TIME_MS=9000` (max think time per action).

Useful options:

| Command | What it does |
|---|---|
| `client/.venv/bin/python client/bot.py --dry-run` | Connects and computes moves but never POSTs (no check-in, no moves). |
| `... bot.py --no-tournament` | Only standalone challenges / "Test your engine" games. |
| `... bot.py --move-time-ms 6000` | Target think time per action (default 9000). |
| `... bot.py --max-time-ms 4000` | Hard cap on think time per action, overrides everything. |
| `ENGINE_CMD="node tools/greedy.mjs" ... bot.py` | Force a specific engine command. |
| `python3 client/bot.py --selftest 20` | Offline: plays 20 plies locally through the full move pipeline. |
| `client/.venv/bin/python client/test_offline.py` | Offline tests of the protocol handling (fake websocket). |

Self-test game: on the Blueprints page, Play tab, click "Test your engine" while the bot runs
(you are seat 0 in the browser, the engine is seat 1; unrated).

## What it does

- One websocket (`/api/engine/ws`), app ping every 25s, reconnects with backoff if no pong in 45s.
  Stops for good on close codes 4001/4003/4004 and on HTTP 401/403 (renew the token and restart).
- Auto check-in on every round while the check-in window is open, then `watch-game` on our board.
- Each action is one POST `{"ply", "move"}`. With two actions in a turn, the server pushes a new
  state after the first POST and the bot computes again. After a 409, a timeout or a lost response
  it re-watches the board (re-read), never replays.
- Time: reads our remaining time from `state.clock` (raw shape logged once to stderr), thinks
  `min(MOVE_TIME_MS, MAX_TIME_MS, 0.45 * (remaining - 3s))`, hard-kills the engine past budget + 1.5s.
  Emergency mode: below 10s left it thinks at most 1000ms; below 2.5s it plays instantly (cached PV
  move or any legal move). A clock-out means a pass.
- Check-in runs in the background with retries while the window is open; each round's new board is
  watched as soon as the tournament push says it is ready. Out-of-order (older ply) snapshots are ignored.
- The engine's move is always checked against `view.moves`. Fallback chain: engine, then greedy,
  then the engine's `top` list, then the cached PV move, then a random legal move.

## Logs

- `client/logs/bot-<session>.log`: the stderr log.
- `client/logs/game-<room>.jsonl`: every pushed state, every decision (move, source, eval, pv, clock,
  budget) and every POST result. The token is never written.

## A/B testing engines (arena)

```bash
engine/snapshot.sh            # copies engine/bp to engine/versions/bp-<shortsha> (gitignored); --build rebuilds first
python3 tools/arena.py --a "engine/versions/bp-<sha> --time-ms 1000" --b "node tools/greedy.mjs" --games 32 --jobs 16
```

Color-swapped pairs from random openings, W/D/L, score % and Elo with 95% CI, mean score diff with
95% CI, per-color breakdown, faults. `--out results.jsonl` keeps every game's moves.

## Pilot interface (outside co-player, e.g. an LLM)

```bash
client/.venv/bin/python client/bot.py --pilot              # files in client/pilot/
client/.venv/bin/python client/bot.py --pilot /some/dir    # or another folder
~/.hexbot/hexbot-linux-x64 --pilot                         # packaged build: ~/.hexbot/pilot/
```

On each of our plies, before the move is sent:
- The bot writes `decision.json` atomically. It contains room, ply, seat, colour, scores, stars, clock_ms,
  left_in_turn, the engine's top 8 (move, score, points, captures), engine_move, board_text, danger, both
  hands, deadline_epoch_ms and pick_file.
- It then reads `control.json`. A missing or malformed file is ignored. Format:
  `{"engine_args": "--p alpha=0", "force": {"<ply>": "<move>"}, "veto": [...], "prefer_wait_ms": 3000, "note": "..."}`
  - `force` plays that move immediately, if legal, without running the engine.
  - `veto` makes the bot play the best non-vetoed engine move instead.
  - `engine_args` are added to the engine command from now on.
  - `prefer_wait_ms` makes the bot wait for `pick-<ply>.json` (`{"move": "..."}`). If no legal pick
    arrives in time, it plays the engine move. The wait never lets our clock go below 20s, and there is no
    wait at all under 25s.
- One `PILOT ply N: ENGINE/PILOT PICK/FORCED/VETO ...` line is logged per ply.

At game end the bot writes `last_result.json`. Tests: `python3 client/test_pilot.py`.

## Post-mortem of real games

```bash
python3 tools/postmortem.py ~/.hexbot/logs/                 # or one game-*.jsonl, or a `hexbot --logs` zip
python3 tools/postmortem.py logs.zip --time-ms 10000 --jobs 4
```

For each of our turns it re-runs `engine/bp` with a long budget and ranks:
- points conceded on the opponent's next turn that the engine's line would have avoided
- immediate captures we missed (with a note when the long search also skips them)
- the biggest eval losses

It also profiles the opponent: edits, how far they follow Fortlite, snipers, their first 10 moves, stars over
time and their hands. Flagged positions go to `lab/positions/*.json` (state, played move, engine move,
note) for the regression suite. `--no-save` skips that, and `--seat` fixes our seat if the log is ambiguous.

## Pair-play helper (manual play)

```bash
python3 tools/suggest.py --moves "2@-3,-3 2@9,-3 2@7,1"   # replay from setup
python3 tools/suggest.py state.json                       # server state / view JSON
python3 tools/suggest.py client/logs/game-<room>.jsonl    # latest state in a game log
```

It prints the board, scores, stars, whose turn it is and actions left, both hands, the top engine
suggestions with their capture/points, and the danger list (our stars the opponent can capture next).
