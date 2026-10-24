# Blueprints: Conclusion

This is the final write-up of our run at the **Fall 2026 Strategy Jam** (game: *Blueprints*; 1179 players; 14 Swiss rounds at 1 min + 15 s; top-16 knockout).

Related docs:

| Doc | What's in it |
|---|---|
| `TERMINOLOGY.md` | Every term used |
| `RETROSPECTIVE.md` | What we did right and wrong |
| `FUTURE_WORK.md` | Next steps and handoff |
| `engine/README.md` | Engine architecture |
| `STRATEGY.md` | Full evidence log |
| `PLAYBOOK.md` | How to play |

## 1. Result

**7.5 / 14, rank 125 of 1179.** We finished on five straight wins by the engine and did not reach the top-16 knockout.

| Rnd | Colour | Opponent | Result | Score | Opponent's style | Who played |
|---|---|---|---|---|---|---|
| 1–7 | — | various | 2.5 pts | — | — | human (tools still being built) |
| 8 | Red | Eris | **L** | 0–84 | wall turtle + immune wall sniper | engine (book edit loop, no captures) |
| 9 | Blue | aryan | **L** | 52–156 | www sealer, late star growth | engine + pilot |
| 10 | Red | wernerolaf | **W** | 5613–1403 | star rusher | engine + pilot (came back from 0–112) |
| 11 | Blue | ctd | **W** (resigned) | 3140–595 | slow www sniper + stacker | engine e9eef9d + Fable pilot |
| 12 | Red | Scrim | **W** (resigned) | 3081–1393 | — | engine 0de5e44 + pilot daemon |
| 13 | Blue | DenizBT | **W** (resigned) | 3089–1182 | — | engine 0de5e44 + pilot daemon |
| 14 | Red | Vakond | **W** (resigned) | 5541–2733 | — | engine 0de5e44 + pilot daemon |

Our board number went from 150 (R8) to 62 (R14).

## 2. Strategies in the field (scout: 607 replayed games, 1214 player-games)

| Style | Share | Win rate | Notes |
|---|---|---|---|
| **Sealer** ("www" wall city) | 26% | **63%** | All of the final top 4 played it: RyanFourSJM, rainbowbutter, NDMath, Finneon 7. |
| Fortress (shielded stars, Fortlite-like) | 12% | 56% | — |
| Blob / star flood | 24% | 52% | Top blob players: carnivorace #5, T #8, Electra #9. |
| Stick / long plain probe | 9% | 32% | — |
| Rusher | 2% | 29% | — |
| Mixed / unclear | 30% | 39% | — |

**Matchups:**
- Sealer beats blob 69% of the time (77% on boards 1–20), fortress 64%, stick 80%, mixed 68%.
- Fortress vs blob is about even (54%).
- 57% of games involving a top-16 player ended by **resignation**: once one side is sealed and ahead, the other side gives up.

### The human team's three archetypes: fortress, blob, stick

**Fortress (turtle up): agree, and it's the strongest family. The details matter, though.**
- Its winning form is the **www sealer**:
  - Edit #2's four stars out, which leaves a bent 3-wall piece.
  - Park the stars in an 11-cell "star bank" that is rarely stamped.
  - Stamp the 3-wall piece everywhere.
  - Seal by about ply 50 and win with small immune wall snipes.
- That hand at ply 20 (`7c:1s0w6p | 3c:0s3w0p | 11c:5s0w6p`) won **82% of 66 games**.
- A passive turtle that never attacks (R8's Eris) is beatable: the lab measured that Eris was never actually sealed. Our engine simply never attacked it.
- The fortress wins only when it is **sealed and ahead**. 90% of sealer losses conceded a capture before ply 40.

**Blob (massive star blobs): agree that it exists and that it's strong against weak players; disagree that it's a winning strategy at the top.**
- Blobs post scores in the thousands and beat rushers, sticks and unsealed fortresses. All five of our live wins were blob-style engine games, by 1,700–4,200 points.
- But a blob is food for a sealer. Every exposed star is a capture the sealer can make immunely, and the blob can't reach a sealed opponent at all.
- Two R11 blob players resigned while ahead on points, because their opponent was sealed.
- The best blob is a **shielded** one (our Fortlite: 4 interior stars per stamp), which narrows the gap. The blob player's job against a sealer is to **crack before ply ~40**.

**Stick (long reach into enemy territory): disagree as a standalone strategy; agree as a tool.**
- Stick-heavy players won only 32%. A long line costs edits, gives the enemy erasable cells, and does nothing against walls.
- The useful versions are small and tactical:
  - a short probe or a 1–3-cell sniper that fits into a hole;
  - the 120° chevron that takes 2 stars from one breach;
  - "edit-then-stamp": reshape a piece into a probe on action 1, stamp it on action 2. This produced our biggest captures (+417 to +536).
- Eris's 6-plain line did eat our starting stars in R8, but only because we spent 20 actions editing.

**Additional archetypes we found:**
1. **Sealer / wall city** is distinct from a passive fortress. It attacks with immune wall pieces and is the real top archetype.
2. **Rusher:** stamps star pieces at the enemy's start flowers from ply 0. It punishes edit-heavy openings (it was 0–112 against our book at ply 17), but it's farmable once the defender starts stamping (we won 5613–1403).
3. **Wall sniper:** an attacker made only of walls, e.g. `www`. Nothing can erase it back.
4. **Sniper-loop builder:** the Fortlite middlegame. It snipes one star per action while keeping its stars sealed by plains.

## 3. The core patterns

1. **A sealed side is untouchable,** since walls can never be erased. Games are decided by *first capture, then seal*.
2. **Points = stars erased × your stars,** so the multiplier only matters if the enemy is reachable. Against a sealed enemy, your stars are just targets.
3. **The opening is a race.**
   - Sealing all 6 starting stars needs 26+ walls (about 9 www stamps), so the median seal lands around ply 50.
   - The **front inner flower** (Blue (-2,0), Red (2,0)) is sealed last, which makes it the crack target.
4. **Two actions per turn** make *breach + snipe* and *edit-then-stamp* the main tactics.
5. **Edits are a tempo tax.** Every edit is an action you don't place. Openings with 5–9 edits are fine; 14 or more lose.
6. **Endgame:** stars are worthless at the end. Blue owns the final ply (119), so Red must leave no hole after ply 118.

## 4. The winning strategy (best current understanding)

**Seal and snipe, with an early crack:**
1. **Opening (plies 0–12):** the www-sealer edits. Use the exact strings from the top players:
   - Blue: `2:1,0>3:-2,1 2:0,1>3:-3,1 2:1,1>2:0,1 2:0,2>3:-1,0 [stamp] 2:-1,1>3:-1,2`
   - Red: `2:0,1>3:2,1 2:0,0>3:3,1 2:-2,1>2:-1,1 2:-2,2>3:4,1 2:0,1>3:5,1`
2. **Race (plies 10–50):**
   - Stamp www around your own start flowers first. That seals them, and every stamp also captures whatever it touches.
   - At the same time, crack the enemy's **front inner flower before ply ~40**.
   - Never put an exposed star within reach of their pieces.
3. **After sealing,** take safe snipes. Grow stars only inside your seal, late, to multiply your final snipes.
4. **Against a rusher:** give up the opening at once and farm their exposed stars.
5. **Against a blob:** seal first; their stars feed you, and yours aren't reachable.

**Our engine's result was more nuanced.** The lab sim and the final arena favoured our shielded-blob engine *against our own bots*:
- the engine beat `tools/bots/sealer.py` 15–1;
- it beat the Eris, aryan and rusher replicas 15–1, 16–0 and 16–0.

The real field says the opposite: sealers beat blobs 69%. Our bot sealers are weaker than human sealers, who plan their wall rings and choose snipes carefully. So **trust the field data**, and treat "build a strong sealer policy" as the top open problem (`FUTURE_WORK.md`).

## 5. What we built

| Component | What it is |
|---|---|
| **Rules** | Exact port of the official game code (`reference/rules.mjs`), plus a Python port (`client/bprules.py`). |
| **Engine** (`engine/`) | C++17 search: 2-action turn widening, opponent capture-reply search, approach and reach terms, Fortlite book with bookYield. Movegen is verified on 4.5M moves. Architecture: `engine/README.md`. |
| **Bot / client** | One-command install for Windows, macOS and Linux, with auto-update. Modes: tournament play, advice-only, logs, and local **play vs the AI** in the terminal or browser. |
| **Pilot system** | An AI co-pilot steering the engine live: `control.json`, a rules daemon, and an analyser that reports reachability, walls-to-seal, opponent style and crack lines. |
| **Lab** (`lab/`) | Fast simulator and bots: 1000+ experiment games on hand designs, geometry and endgame. |
| **Scout** (`tools/scout/`) | Harvested and replayed the tournament's top games and produced the archetype stats above. |
| **Ops** | Post-mortem after every game, regression positions, live game records (`lab/live_games.txt`), keepalive watchdog. |

## 6. Progress over the day

| Time (PDT) | What happened |
|---|---|
| 07:00 | Rules video premiered. |
| 08:00 | Tournament starts. We had the rules extracted and agents fanned out. |
| ~09:00 | Engine v1, the client, the pair-play tool and the first lab results. |
| ~10:00 | One-command release with auto-update. |
| 10:30 | Bot goes live in R8; the Cloudflare UA block is found and fixed. |
| R8–R9 | Losses to wall builders. These produced the book-yield, reach-scaled-multiplier and approach fixes, plus the pilot. |
| R10–R14 | **Five straight wins.** |
| After | Scout harvest, final arena, and the documentation in this repo. |
