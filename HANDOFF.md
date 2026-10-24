# Handoff: how to keep this running and keep improving it

Anyone with this repo can take over. Everything important is here, in `PLAYBOOK.md` and in `STRATEGY.md`.

## 1. Play right now (any machine)

- **macOS/Linux:** `curl -fsSL https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.sh | bash`
- **Windows (PowerShell):** `powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.ps1 | iex"`

It asks for the strategyjam engine token: profile → select Blueprints → Connect engine. The token lasts 24h.
The bot auto-detects the tournament, checks in every round, plays every move and self-updates between games.
Use `--advise` for suggestions only (you play), and `--logs` to zip the game logs.

## 2. The live setup on the original machine (WSL, `~/hex-capture`)

**Processes.** Both are detached (parent is init), so they survive the Claude session ending:
- `client/.venv/bin/python -u client/bot.py --no-update --pilot client/pilot`
  - Started with `ENGINE_CMD="$HOME/.hexbot/live/bp --threads 8"`.
  - Output goes to `client/logs/live-console.log`.
- `python3 -u tools/pilot_daemon.py --dir client/pilot`: answers pick files instantly from `client/pilot/rules.json`.

**Files:**
- Token: `~/.hexbot/token` (0600). Browser cookie for game-history scraping: `~/.hexbot/cookie` (0600). Never commit either.
- Live engine: `~/.hexbot/live/bp` is a symlink to a pinned build, `bp-<sha>`. The current one is `0de5e44`; older builds are kept for rollback.

**If the bot dies:**
```bash
cd ~/hex-capture
ENGINE_CMD="$HOME/.hexbot/live/bp --threads 8" nohup setsid client/.venv/bin/python -u client/bot.py --no-update --pilot client/pilot >> client/logs/live-console.log 2>&1 &
nohup setsid python3 -u tools/pilot_daemon.py --dir client/pilot >> client/pilot/pilot_daemon.log 2>&1 &
```
To run without the pilot at all, drop `--pilot client/pilot`. The engine plays alone; that is safe.

**To upgrade the engine** (between games only): run `bash engine/build.sh`, then `cp engine/bp ~/.hexbot/live/bp-<sha>`, then `ln -sf ~/.hexbot/live/bp-<sha> ~/.hexbot/live/bp`.
No bot restart is needed, because each move runs the engine fresh.

## 3. Pilot controls (optional human or AI co-pilot)

**`client/pilot/control.json`** is re-read every ply:
- `engine_args`: engine knobs. Examples: `--nobook`; `--p bookYield=1`; `--p alpha=0`; `--p approachW=5`; `--p noEditPly=28`.
- `force`: `{"<ply>":"<move>"}`
- `veto`: `[...]`
- `prefer_wait_ms`: how long the bot waits for a pick.

**`client/pilot/rules.json`** drives the daemon:
- `protect_from` / `protect_pieces`: no edits to #2/#3 after that ply unless capturing.
- `take_capture_min`
- `star_safe_dist`
- `when` rules
- `approach` (off by default; it tested negative)

**Tools:**
- `tools/analyze.py <decision.json>`: reachability, walls needed to seal, opponent style, crack line.
- `tools/approach.py`
- `tools/suggest.py`
- `tools/postmortem.py <game log>`: our mistakes, regression positions, the opponent's profile.

## 4. What we know (read these)

- `PLAYBOOK.md`: per-turn protocol, opponent styles, live lessons.
- `STRATEGY.md`: all lab, engine and scout findings with evidence.
- `lab/live_games.txt`: every live game record. `client/pilot/notes.txt`: the pilot's lessons.
- `lab/games/_report.txt`: analysis of the top players' games (scout).

**Headline:** most top-16 players are **wall sealers**.
- Their #2 becomes a 3-wall bent chain ("www"). They stamp it everywhere, keep only their starting stars, seal by ply 32–72 and win with small www snipes; the opponent then resigns.
- **Star floods lose to them.**
- **To beat a sealer:** crack their front inner flower before ~ply 45–50, never feed them exposed stars, and/or seal faster yourself.
- Sealer openings (verified legal):
  - Blue (NDMath): `2:1,0>3:-2,1 2:0,1>3:-3,1 2:1,1>2:0,1 2:0,2>3:-1,0 [stamp] 2:-1,1>3:-1,2`
  - Red (RyanFourSJM): `2:0,1>3:2,1 2:0,0>3:3,1 2:-2,1>2:-1,1 2:-2,2>3:4,1 2:0,1>3:5,1`

## 5. Open work (pick up here)

1. **Sealer policy bot** (`tools/bots/sealer`, engine CLI contract): play the sealer opening, then min-cut-guided www stamps and www snipes.
   Run it in arena against `engine/bp` and the replicas (`node engine/replica.mjs --bot eris|aryan|rusher`).
   If it wins, make it the live `ENGINE_CMD`.
2. **Engine defaults that don't need a pilot:**
   - take captures ≥50 over builds;
   - no post-book edits that break #2 or the #3 sniper;
   - star-safe distance once the enemy has long probes;
   - sealer detection, followed by an early crack (`crackW`).
3. **Scout** (`tools/scout/fetch.py`, `analyze.py`): keep harvesting the top boards and turn the patterns into playbook rules.
4. **Arena:** `python3 tools/arena.py --a "<cmd>" --b "<cmd>" --games 16 --jobs 4`. Every change must win an A/B before it ships.

## 6. Live results so far (this account)

R1–R7 were played manually (2.5 points).
- R8: lost 0–84 to a turtle.
- R9: lost 52–156 to a www sealer.
- R10: **won** 5613–1403 against a rusher.
- R11: **won** 3140–595 against a slow sealer.
