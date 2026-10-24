# Future work and handoff

Read this first if you're picking up the project. The operational setup is in `HANDOFF.md`, and the conclusions are in `CONCLUSION.md`.

## Highest value next steps

1. **Make sealing first-class in the engine.**
   - Add an exact min-cut "walls-to-seal" term for both sides. The code already exists in `lab/sealcut.mjs` and `tools/analyze.py`.
   - Add a "seal when ahead" mode: once ahead, value lowering our walls-to-seal above building stars.
   - Use `www` wall pieces as immune attackers.
   - This is the archetype the top 16 played.
2. **Tune against the real field, not self-play.**
   - Arena opponents: `tools/bots/sealer.py` (top-16 opening book plus min-cut sealing), `engine/replica.mjs --bot eris|aryan|rusher`, and `tools/bots/rusher.py`.
   - Weight the gauntlet by how often each archetype appears in `lab/games/_report.txt`.
3. **A longer horizon.** The 2-turn search can't see multi-turn approaches. Options:
   - a selective 3rd turn for capture lines only;
   - MCTS with sealer- and flood-style rollouts;
   - a learned value function trained on the harvested games (`lab/games/*.json`) plus self-play.
4. **Adapt the opening to the opponent.** Detect the style by ply ~10 (rusher, sealer, Fortlite or flood) and switch: book yields against rushers, crack the front flower against sealers, and so on. The pilot did this by hand; build it in.
5. **Sealer vs flood decision.** If the final arena (`lab/FINAL_ARENA.txt`) shows the sealer policy beating the flood engine, make it the default, or have the engine choose per opponent.

## Loose ends

- **Pilot `star_safe_dist`:** helpful against wall snipers, but it also blocks breach stamps. It needs a smarter rule (allow 0-star breach pieces).
- **Approach rule in the daemon:** it tested negative against a weak turtle proxy. Retest it against `tools/bots/sealer.py`.
- **Engine knobs that are off by default** and should be re-evaluated against replicas: `noEditPly`, `crackW`, `expoB`.
- **Lab bots** use hand injection, which the real rules don't allow, so they can't run in the arena. Port the useful ones to legal edit plans, like `engine/replica.mjs` does.
- **Windows and macOS binaries** passed CI but were never confirmed on a real user's machine during the event.

## How to take over in 5 minutes

1. Clone the repo.
2. To play: run the one-liner from `README.md`.
3. To improve the engine: `bash engine/build.sh`, then `node engine/test_movegen.mjs` (correctness), then `python3 tools/arena.py --a "engine/bp --time-ms 500" --b "python3 tools/bots/sealer.py" --games 16 --jobs 4`.
4. To study games: `python3 tools/scout/analyze.py`. This needs `~/.hexbot/cookie` from a logged-in browser session for fresh fetches; the already-harvested games are in `lab/games/`.
