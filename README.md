# hex-capture: an AI for StrategyJam's *Blueprints*

This repo holds a search engine, a tournament bot and a strategy playbook for **Blueprints**, the hex strategy game from the Fall 2026 Strategy Jam.
In that tournament the bot won its last 5 games in a row and finished 125th of 1179.

**Start here:**

| Doc | What's in it |
|---|---|
| [CONCLUSION.md](CONCLUSION.md) | Results, the strategies in the field, what wins |
| [PLAYBOOK.md](PLAYBOOK.md) | How to play well, turn by turn |
| [TERMINOLOGY.md](TERMINOLOGY.md) | Glossary |
| [engine/README.md](engine/README.md) | How the AI works |
| [RETROSPECTIVE.md](RETROSPECTIVE.md) | What went right and wrong |
| [FUTURE_WORK.md](FUTURE_WORK.md) / [HANDOFF.md](HANDOFF.md) | Continue the project |

## Play against the AI

One command, nothing to install: no account, no token, no Python, no compiler.
The command downloads a prebuilt `hexbot` for your OS into `~/.hexbot/`, keeps it updated, and starts a game.

### In your browser

| System | Run in a terminal |
|---|---|
| **Windows** (PowerShell) | `powershell -ExecutionPolicy Bypass -c "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.ps1))) --play --gui"` |
| **macOS / Linux** | `curl -fsSL https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.sh \| bash -s -- --play --gui` |
| **WSL** | Same as Linux. If no browser opens, open the printed `http://127.0.0.1:<port>` in your Windows browser. |

How it plays:
- A tab opens with a clickable hex board.
- **To place:** pick a blueprint, then click the board. A ghost preview shows where it will land.
- **To edit:** click a cell in one of your blueprints, then click where it should go.
- Buttons: **Hint**, **Undo**, **New game**.
- Stop it with Ctrl+C in the terminal.

### In the terminal

Use the same commands with `--play` instead of `--play --gui`.
Type moves such as `2@3,-1` (place blueprint 2 at q=3, r=-1) or `1:0,1>2:2,0` (move a cell between blueprints).
Commands: `moves`, `hint`, `undo`, `help`, `quit`.

### Options

Add any of these after `--play`:
- `blue`, `red` or `random`: which side you play.
- `--level easy|normal|hard`: the AI thinks for 0.5 s, 3 s or 8 s per action.
- `--time-ms N`: exact think time in milliseconds.

Every game is saved to `~/.hexbot/games/`. To watch one again, use `--replay <file>`.

**Rules in short:**
- Stamp a blueprint onto empty hexes touching your cells.
- Every enemy non-wall cell your stamp touches is erased.
- Each enemy **star** you erase scores your current star count.
- Walls can never be erased.
- 120 actions: Blue plays 1, then turns of 2 actions alternate. Highest score wins.

## Let the AI play for you on strategyjam.org

1. On strategyjam.org, go to your **profile**, select **Blueprints** under supported games, then click **Connect engine** and copy the token. It lasts 24 h.
2. Run the launcher with no arguments:
   - Windows: `powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.ps1 | iex"`
   - macOS / Linux / WSL: `curl -fsSL https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.sh | bash`
3. Paste the token when asked. Input is hidden and never logged. Add `--save-token` to keep it.

It finds the live tournament, checks in every round, plays every move, and updates itself between games. The first engine move tags your entry as "Engine".

Other modes:
- `--advise`: shows suggestions while you play yourself. It never moves.
- `--pilot DIR`: a co-pilot steers the engine; see [HANDOFF.md](HANDOFF.md).
- `--logs`: zips your game logs.
- `--version`, `--no-update`.

Downloads: https://github.com/srikdhruv/hex-capture/releases/tag/latest

## For developers

| Path | What it is |
|---|---|
| `reference/rules.mjs` | Exact rules, ported from the official game code. `client/bprules.py` is the Python port. |
| `engine/` | C++17 search engine. Build with `bash engine/build.sh`; test with `node engine/test_movegen.mjs`. |
| `client/` | Tournament bot, play mode (terminal and browser), pilot interface, auto-updater. |
| `tools/` | `arena.py` (A/B matches), `analyze.py` / `suggest.py` / `postmortem.py`, `pilot_daemon.py`, `bots/` (sealer and rusher), `scout/` (harvest and analyse real games). |
| `lab/` | JS simulator, experiments, harvested tournament games, live game records. |

Typical loop:

```bash
bash engine/build.sh
python3 tools/arena.py --a "engine/bp --time-ms 500" --b "python3 tools/bots/sealer.py" --games 16 --jobs 4
```
