# Retrospective: what we did right and wrong

This is the inference doc: what the tournament taught us about the game, about our methods, and about running a team of AI agents on a live clock.

## Outcome

- **Final standing:** 7.5 / 14, rank 125 of 1179. We did not make the top-16 knockout.
- **R1–R7:** played by hand while the tools were being built. 2.5 points.
- **R8–R9:** engine, 0–2. Both losses were to wall builders.
- **R10–R14:** engine (+ pilot), **5–0**. Four of those five opponents resigned. Board number climbed from 150 to 62.

## What we did right

1. **We extracted the exact rules from the game's JS bundle within minutes** (`reference/rules.mjs`).
   Everything downstream checked itself against that ground truth: the engine's move generation matched it on 4.5M moves.
2. **We parallelised from minute one.** Separate agents built the engine, the client, the lab, live ops, the scout and the pilot.
   The coordinator stayed free to think and to talk to the human.
3. **A/B testing before anything shipped.** The arena reported confidence intervals, so no engine change went live without winning first.
4. **The one-command install shipped fast**, with auto-update between games and builds gated on a smoke test (Windows, macOS, Linux).
5. **We learned from real games.** Live ops ran a post-mortem after every game, built regression positions from it, and recorded the opponent's profile in `lab/live_games.txt`.
   That loop turned three losses into three engine fixes:
   - the book yields under threat;
   - the multiplier only counts when enemy stars are reachable;
   - an approach term pulls the engine toward distant stars.
   The bot then won five straight.
6. **The pilot interface.** A slow AI could steer the fast engine with knobs, vetoes, forces and a rules daemon, without ever costing clock time.
   The R10 comeback (0–112 down at ply 17, won 5613–1403) came from a single pilot knob.
7. **The human's insights were right, and we tested them.** Walls, fortress play, 2-cell pieces, denial, the fact that a sealed side can't be scored on.
   The scout later confirmed them on the top players' games.

## What we did wrong

1. **We tuned against ourselves.**
   - The engine and lab results came from engine-vs-engine or bot-vs-bot games. "Fortlite won 128–0" was true in that world and misleading in the real one.
   - Real players rushed, turtled and wall-sniped, and our edit-heavy opening was exposed.
   - **Lesson:** model the real field early (replicas of real opponents) before trusting self-play.
2. **We undervalued walls and sealing for too long.**
   The insight that a fully sealed side can never be scored on decides most games. The human saw it before our tooling did. We should have measured "walls needed to seal" from the start.
3. **The multiplier tunnel vision.**
   Our evaluation treated star count as an asset even when nothing was capturable. In R8 the engine built 157 stars and scored 0, while its eval read +690.
4. **The live bot started late.**
   R1–R7 were manual. A Cloudflare User-Agent block (403, error 1010) and a human playing moves alongside the bot cost R8's opening.
   A live dry run against a self-test game would have caught both before the tournament.
5. **Some of our analysis was overconfident.**
   I first told the human that R8 was unwinnable; the lab's exact min-cut later showed it was never sealed. In R9 I pointed at targets that turned out to be unreachable.
   **Lesson:** compute reachability exactly before advising.
6. **We hit credit and rate limits.** Several agents died mid-task twice. Committing small steps and writing a handoff earlier would have lost less work.
7. **Process friction:**
   - One accidental `git commit -a` swept up another agent's work-in-progress.
   - Concurrent CPU use by experiments and the live bot had to be capped by hand.

## What we believe about the game now

1. **A sealed side is untouchable, so the real game is "first capture, then seal".** Top players won 36–31 and 58–13, and opponents resigned.
2. **Walls are the most valuable cells:** they seal, block, deny, and as `www` pieces they capture immune.
3. **Star floods win against weak or unsealed opponents, often by thousands, but lose to sealers.**
   Our live wins were against rushers, slow sealers and stackers, which a flood engine beats when it cracks early.
4. **The front inner flower is the crack target.** Sealing all 6 starting stars needs 26+ walls, which is roughly ply 50 or later. After that, a wall builder is closed.
5. **Edits are a tempo tax.** Fortlite's 9 edits pay off against slow opponents, but against rushers the book must yield at once.
