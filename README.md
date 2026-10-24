# hex-capture

Engine and tournament bot for the StrategyJam game **Blueprints**.

## Play with one command

You need nothing installed: no Python, node or compiler. The command downloads a prebuilt `hexbot` for
your OS into `~/.hexbot/`, fetches it again whenever a newer build is released, and runs it. The bot then
plays as you.

**macOS / Linux** (Terminal):

```bash
curl -fsSL https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.sh | bash
```

**Windows** (PowerShell or cmd):

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.ps1 | iex"
```

### Token

On first start the bot asks for your StrategyJam engine token. Input is hidden, and the token is never
logged or stored.

1. Log in at https://strategyjam.org and open your **profile**.
2. Under supported games, select **Blueprints**, then click **Connect engine**.
3. Copy the token. It is shown once and expires after 24h. Paste it into the bot.

To skip the prompt next time, add `--save-token` (macOS/Linux: `... | bash -s -- --save-token`). It writes
`~/.hexbot/token` with 0600 permissions. `--forget-token` deletes it. Alternatively, set
`STRATEGYJAM_TOKEN` in the environment.

> **Engine label:** the first accepted engine move tags your tournament entry as **Engine** for the whole tournament.

What it does:
- Finds the live Blueprints tournament on its own (override with `TOURNAMENT_ID`).
- Checks in every round, plays every move, and also plays "Test your engine" self-test games.
- Prints one line per move: round, colour, ply, move, score.
- Writes logs to `~/.hexbot/logs/`. Stop it with Ctrl+C.
- Keeps itself up to date. Each launch runs the newest build. While running, it checks about every
  2 minutes, between games only and never mid-game. When there is a new build it swaps it in, restarts
  with the same settings and prints `updated to <sha>`. `--no-update` turns this off; `--version`
  prints the build.

Downloads: https://github.com/srikdhruv/hex-capture/releases/tag/latest
(`hexbot-windows-x64.exe`, `hexbot-macos-arm64`, `hexbot-macos-x64`, `hexbot-linux-x64`).

## Developers

- `client/`: the tournament client (`client/README.md` has run options, logs and the protocol notes).
- `engine/`: the C++ engine (`engine/build.sh`).
- `tools/`: pair-play helper (`suggest.py`), arena (`arena.py`), greedy fallback, rules CLI.
- `reference/`: official rules port and protocol example.
