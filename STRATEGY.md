# Blueprints — Strategy Playbook (live doc, updated during the tournament)

> Tournament: Fall 2026 Strategy Jam, 14 Swiss rounds at 1 min + 15 s/move, then top-16 knockout at 1 min + 25 s.
> Rules source: exact port of the official game code in `reference/rules.mjs`.
> Status: v1 (lab + engine findings merged; read 0a / 0b / 0 first). Lab results and engine findings will be merged in as they arrive.

## 00. BIGGEST RESULT SO FAR — shield your stars ("Fortlite" #2)

- **What it is:** spend about 9 edits moving **plains from #1/#3 into #2**, wrapped around #2's 3 edge stars, so **all 4 stars are interior**. Every neighbour of every star is then one of your own cells or a wall.
- **Result:** won **32–0** against the no-edit baseline (16–0 as each colour), average margin **+6900**, even after paying 9 actions for the edits.
- **A bigger version also went 32–0:** a full radius-2 hex of 19 cells, with 6 stars + 1 wall inside and 2 walls + 10 plains on the rim (14 edits).
- **Why it works:** to reach an interior star, the enemy must first erase a shield plain. That leaves a **1-hex hole that a 7-hex flower can't fit into**, so they need a tiny probe piece. Every stamp you make is +4 stars they can't take.
- **Defensive geometry (Lab #5, exact search):**
  1. **Read the enemy's HAND first.** If none of their pieces is 1–3 hexes, your sealed Fortlite stars **cannot be captured**, even when the enemy is touching them. Just keep the shields intact.
  2. **If they hold a sniper:** they stamp a big piece next to your shield (it erases a whole band of it), then snipe into the hole.
     That reaches up to 6 hexes and takes 1 star per turn. Keep forts **7+ hexes** from their cells, or accept losing 1 star per turn at the front.
  3. **After they snipe in, erase their sniper cell next turn.** If it is a star (Fortlite's #3 is), that's free points for you.
  - An unsealed 4-star flower can lose up to 2 stars to a gap of 7 or less. The 6-star forts leak 2 stars per breach.
- **Weak point:** the enemy cuts a piece down to 1–2 cells (a "sniper"), breaches with action 1 and snipes with action 2.
  Watch their hand for small pieces, and keep the holes next to your stars filled. Sniper-counter tests are running.
- **How it combines with your plan:** shields matter more than stacking (stacking alone lost 19–45).
  Spend your first edits on the **plain shield around #2's stars**, then on the long probe, then on wall placement.
- **Confirmed against the real engine:** with the Fortlite opening, the engine beat itself without it **31–1** (Elo +597, average margin +1934). Fortlite is now the engine's **default** opening.
- The 9 edits take up most of the first ~20 plies, and that is intended. Make a capture or block a threat in between only when it clearly matters.

### Exact Fortlite edit strings (checked against the official rules; play them **in this order**, with no other edits in between — stamps in between are fine)
- **Blue (9):** `3:1,1>2:2,-1` `3:1,0>2:0,1` `3:0,0>2:-1,0` `3:0,0>2:-3,2` `3:-1,1>2:-3,3` `3:0,1>2:-2,1` `1:1,1>2:-1,4` `1:1,0>2:0,3` `1:0,0>2:-2,4`
- **Red (9):** `3:1,1>2:2,1` `3:1,0>2:2,0` `3:0,0>2:1,2` `3:0,0>2:0,-1` `3:-1,1>2:1,0` `3:0,1>2:-1,1` `1:1,1>2:-2,4` `1:1,0>2:-2,3` `1:0,0>2:-1,4`
- **End result:**
  - #2 = 16 cells: 4 interior stars, 3 walls, 9 plains → every stamp is +4 protected stars.
  - #1 = a star + 3 plains.
  - #3 = a **single star, which works as a 1-hex sniper** for edit-free captures into holes.
- **Hex19 extension (+5 edits, 14 in total):** gives #2 = 6 stars + 1 wall inside, 2 walls + 10 plains on the rim → +6 safe stars per stamp.
  It leaves #1 with 2 plains and #3 empty, so **you lose the sniper and the probe**.
  - Blue: `2:0,2>2:1,2` `1:1,0>2:0,2` `2:-1,1>2:-1,0` `3:0,0>2:0,1` `1:1,1>2:-2,4`
  - Red: `2:1,1>2:2,0` `1:1,0>2:1,1` `2:-1,2>2:-2,2` `3:0,0>2:-1,2` `1:1,1>2:0,4`
- **Engine test: Hex19 LOST 1–31 to Fortlite** (mean diff −738). The extra edits and the 19-cell #2 cost more than they give.
- **Recommended:** Fortlite (9 edits), keeping the sniper. Interleave the edits with safe #2 stamps whenever the enemy has no capture threat.

## 0c. Bigger ideas in testing (player + coordinator)

- **The enemy can only score by erasing your STARS.** This leads to two rules:
  - **Seal every star** — interior, behind plains or walls.
  - **Attack only with star-free pieces** (plain probes and snipers). When the enemy erases your attackers, they score 0.
  Do both, and you score your full multiplier while the enemy scores nothing.
- **A complete wall perimeter can never be breached.** Walls are never erased, and a connected stamp can't cross them.
  Plan: build up your multiplier, then close the side facing the enemy with walls, then spend every remaining action attacking.
- **Run away and spam stars.** Use a long thin piece to jump your frontier far from the enemy: a stamp only has to touch your cells when it is placed, so a 6–10 cell line moves your frontier 6–10 hexes in one action.
  Build a star colony beyond their reach (8 + the length of their longest piece). Later, slither a probe into their star mass.
  Counter to watch for: the enemy builds their own long piece to chase you.
- Lab designs being tested: D1 "Fort17" (6 interior stars in #2 + a 3-plain line + a 1-plain sniper), D3 seal-then-attack, D4 run-away colony.

## 0d. Middlegame: the sniper loop (engine Fortlite mirror games)

- **What happens:** after the 9 edits and about 3 #2 stamps (around ply 26), games turn into a **capture loop**.
  Every action stamps the 1-star #3 sniper into a 1-hex hole next to an enemy star.
  Each stamp takes 1 star and gives 1 back (your sniper gets erased next), so star counts stay flat at about 30 each and scores climb by about 30 per action.
- **Keep sniping; don't go back to building stars.** In tests, weighting star-building more heavily **lost 2–62 to 20–44**.
- **Your edge: the last action and tempo.** Blue has the final action of the game (ply 119).
- **Tested and rejected: a plain sniper LOST 4–44 to the star sniper.** Keep Fortlite's #3 as a single **star**.
  Each star-snipe captures a star **and** adds +1 to your multiplier.
  The plain-sniper side captured more stars (58 vs 52) but scored less than half, because its multiplier fell to about 8 against 47.
- **Middlegame routine (lab #9):**
  1. Breach with #2: it erases a band of the enemy's shield plains.
  2. Snipe with #3 into a hole next to one of their sealed stars.
  3. No snipe available? Stamp #2 for +4 safe stars.
  4. An enemy sniper-star sitting in your hole is a free capture — erase it on your next action.
  In mirrors, about 30–35 of each side's ~50 stamps are snipes; #2 is stamped 11–16 times.

- **Lab #6 round robin (320 games, bots that erase then snipe):**
  - Fortlite went **128–0**, beating every other design 32–0.
  - Fort18 (6 sealed stars, 13 edits) went 87–40. Hex19 went 45–82. No edits went 0–128.
  - **Past Fortlite, more edits or more stars LOSE.**
  - Switching to star-free attacks after ply 70 did worse (58–68).
- **Lab and engine disagree on what to do with free actions in the middlegame:**
  - Lab bots say to stamp sealed #2s.
  - Engine-vs-engine says sniping beats building once the loop starts.
  - **Against strong opponents, follow the engine.** Snipe whenever a capture is on the board; stamp #2 only on actions with no capture available.

- **Lab #7, probe shapes (exact search):**
  - **1- or 2-hex probes take only 1 star per breach of a Fortlite.** Each shield hole touches exactly one star.
  - **A 3-plain CHEVRON (a 120° bend) takes 2 stars.** Wrap it around one of the enemy fort's ring walls: each arm lands in the hole on one side of the wall, and the elbow sits on the empty corner outside it.
  - **Shapes that do it**, in blueprint keys:
    - vs Blue's Fortlite: `{0,0 0,1 -1,2}`, `{0,0 1,0 -1,1}` or `{0,0 0,1 1,1}`;
    - vs Red's Fortlite: the mirror images.
  - **Defend against it:** the danger points are the 3 empty corners just outside your #2's ring walls.
    Don't let an enemy piece touch both shield plains at a corner. If one does, refill the hole next turn or erase their piece.
  - Compact 6-star forts leak 2 stars even to a 1-hex sniper. Fortlite, with its stars separated by walls, is the most leak-resistant layout tested.

- **Lab #8:** sealing a 5th star inside #2, to free #3 up as a plain sniper, **lost 0–48** to Fortlite: with 5 stars packed together, every hole touches 2 stars.
  **Never put a 5th or 6th star into #2.** Fortlite's 4 stars with walls between them is the sweet spot.
  The last 5 plies hold only about 10% of the score: points come in steadily from ply 20 onward.

- **Lab #10:**
  - **Stamp #2 at least 7 hexes from every enemy cell unless the stamp captures.** Use the front line only for breach+snipe. Overall win rate 77% vs 56%.
  - A 2-star domino sniper with a chevron #1 lost 11–53. **Keep Fortlite exactly as booked** (#3 = 1 star).

- **Engine book tests:** the plain sniper lost 14–50 and the chevron #1 hands lost 6–26 and 6–18. **Fortlite exactly as booked stays best.**
  The chevron is a tactic: reshape into it only when a 2-star capture is right there.

## 0a. Player-discovered hand plan (from live games — being validated by lab + engine)

- **Opening, first few actions:** pull the centre stars out of #1 and #3 and stack **all 6 stars into ONE blueprint**.
- **Restructure the other two blueprints:**
  - one **long piece** for infiltration and reach;
  - one **defensive "slither"** (a snake shape) that **carries the 3 walls** as shields.
- Between them the two non-star pieces should cover **short and long, vertical and horizontal** shapes, so something always fits the hole you need.
- **Lab #4 result, with realistic edit timing (n=32 per design):**
  - This plan as stated (6 unshielded stars + a 6-plain line + a wall tail, 9 edits) **lost 5–27**.
  - STACK5 (6 stars in #2 with the walls moved out) **lost 2–30**.
  - **Fortlite (9 real edits) won 32–0, average margin +7200 — confirmed.**
- **Verdict: shield the stars first.** Only stack 6 stars if you also wrap them all, which is what Hex19 does (14 edits).
- **Caution from Lab #2 (n=64 bot games):** stacking only the stars (6 stars + 3 walls in #2, nothing else changed) **lost 19–45** to the no-edit baseline.
  The stacking side finished with more stars (237 vs 166) but lost 99 stars to captures, against 59.
  The reason: a 6-star stamp leaves 5 stars on its edge, while the standard flower leaves 3 on the edge and 1 safe in the centre. More edge stars means more targets.
  **So stacking only pays if those stamps are protected** — by distance, by the wall slither, or with plains as a buffer. Your full plan, with the slither and the probe, is being tested now.

## 0. TL;DR — play this way (updated with lab data)

1. **Stamp blueprint #2 (the 4-star flower) almost every action.** In strong bot-vs-bot games nearly every action is a #2 stamp:
   it adds +4 to your multiplier *and* it is your main attacker. Final star counts reach ~75–200 per side, so a late star capture is worth 75–200 points.
2. **Before every stamp, run the threat check:** *"After my turn, can the enemy touch any of my edge stars with 1–2 stamps?"*
   A bot that skipped this check lost 27 of 30 games.
3. **If a stamp can also take a star, take it.** Capture-leaning bots beat pure hoarders 73% vs 40% (n=30 each).
   Best case: grow and capture with the same #2 stamp, placed so that one of its cells touches an exposed enemy star.
4. **Blue's first move: don't drop #2 near the middle.** These first moves lose a star to Red's first turn:
   `2@1,-3 2@-1,1 2@-1,-4 2@-4,2 2@-3,-3 2@-3,-4 2@-2,-4 2@-5,1 2@-5,2 2@-6,2`.
5. **Stacking all 6 stars in #2 LOST 19–45 in bot tests when nothing else changes (see 0a). Only stack if the stamps are protected.** The original idea: On a quiet turn, spend 2 edits moving the centre stars of #1 and #3 into #2.
   #1 and #3 stay connected as plain rings. #2 then gives +6 stars per stamp instead of +4: about +100 multiplier over a game for 2 actions.
   Attach each new star where it touches the most of #2's own walls and stars, so it is not exposed.
6. **Clock: the +15 s increment comes once per 2-action turn, not per action.** Budget about 7 s per action, or you will drain.

## 0b. Reach rule (exact lab test, against the standard 7-hex flowers)

- An edge star **within 4 hexes** of an enemy cell can be captured by **one** enemy action.
- **Within 7 hexes**, it can be captured by a **2-action turn**.
- **8 or more hexes from every enemy cell = safe for one turn.**
- Long probe pieces add their length to these numbers, so always check the enemy's longest blueprint.

## 1. Rules in 30 seconds (the parts that decide games)

- Hex plane with no edges. Each side owns 3 **blueprints** (shapes). They are **reused**, never used up.
- **Place**: copy a blueprint onto *empty* hexes so that at least one copied hex touches one of your cells.
- **Capture**: every enemy cell **touching any hex you just placed is erased**, *except Walls*. Walls are permanent.
- **Points**: each enemy **Star** you erase = **your current Star count** on the board (counted *before* this placement).
  Erasing plains scores 0, but it opens holes.
- **Edit**: move one cell inside or between your blueprints. Blueprints must stay connected (one can even be emptied). **An edit costs a full action.**
- Turn order: Blue 1 action, then **2 actions per turn** alternating (R R B B R R …). 120 actions total, 60 each.
  **Blue has the very last action (ply 119)**; Red's last turn is plies 117–118.
- Running out of clock does not lose: it just **passes** that action. Don't flag, but don't panic either.
- Your blueprint set has **6 Stars, 3 Walls, 12 Plains** forever (edits only rearrange them).
  Start: #1 and #3 = 1 Star + 6 Plains ("plain flowers"); #2 = 4 Stars + 3 Walls ("star flower").

Notation (copy it from the move list): `2@-1,3` = place blueprint 2 at offset (q=-1, r=3). Axial coords: `q` goes right,
`r` goes down-right; neighbours of (q,r): (q±1,r), (q,r±1), (q+1,r-1), (q-1,r+1).

## 2. The core equation

**Points for a capture = (enemy stars erased) × (your stars on the board).**

- Your Star count is your **multiplier**. A star placed early pays for every capture you make later.
- Capturing one enemy star is worth *twice*: you score your multiplier now, and their multiplier drops by 1 for the rest of the game.
- Losing a star is the mirror image. **A star you can't defend is a gift to the opponent.**
- Captures late in the game are worth the most (multipliers are big), and there is no time left to retaliate.

## 3. Principles (v0, first-principles — refined below as data comes in)

1. **Build the multiplier where they can't reach.** The board is infinite. Stamp star-rich blueprints (#2 adds 4 stars) on
   your *back side* (Blue: far left, Red: far right). The enemy can only place touching their own cells, so a star is safe
   if no enemy blueprint can be placed adjacent to it. Rough rule: with the starting 7-hex flowers, enemy reach is
   ~4 hexes from their nearest cell. Longer / reshaped blueprints reach further — check their hand.
2. **Two actions = breach + capture.** Action 1 erases the plains around a star; action 2 lands next to the now-exposed
   star and takes it. So a star is only safe if it is protected by **two layers** or by **Walls**.
   Before ending your turn ask: *"Is any of my stars adjacent to an empty hex, or to a plain that touches an empty hex,
   that the enemy can reach with a blueprint that fits?"*
3. **Walls are the only permanent armour.** You can't capture walls and nobody can place on them. Put walls between your
   stars and the enemy front. The star flower (#2) already has a fully protected centre (3 walls + 3 stars).
4. **Fit is the real constraint.** A placement needs *every* hex empty. Big compact flowers often cannot fit into the
   gaps at the front. A small/thin probe blueprint (built with edits) fits where flowers can't — but each edit costs an action.
   Think "what can actually fit there?" both for attack and for defence (filling holes so nothing fits next to your stars).
5. **Erase plains to open lines**, but notice that your newly placed cells are now touching the enemy too:
   they can counter-erase your non-wall cells next turn. Lead with walls toward the enemy when you can.
6. **Endgame:** the last 2–3 turns are pure cash-in — capture with your biggest multiplier, ignore building.
   Blue moves last (single action at ply 119): Red must make sure no Blue capture is available after ply 118.

## 4. Opening notes (starting position)

- Board: Blue flowers centred (-10,0) [star flower], (-6,0), (-2,0); Red mirror at (2,0), (6,0), (10,0) [star flower].
  Front gap is the column q=0 between Blue's (-1,0) and Red's (1,0).
- Inner flowers have 1 star each, protected by a single ring of plains → each is a "breach + capture" target.
- Example Blue first move: `1@1,-3` (plain flower centred (1,-2)) erases Red plains (1,0) and (2,-1), exposing Red's star (2,0).
  Lab is computing which opening moves are actually best and what Red's best reply is.

## 5. Pair-play / tools

- `tools/suggest.py` (in progress): give it the move list or a state JSON → board render, danger list, engine suggestions.
- Engine: `engine/bp` (C++, in progress). Client: `client/bot.py` (in progress). See `client/README.md` once it exists.

## 6. Findings log (lab + engine)

- **Lab #1** (90 heuristic-bot games, fast engine verified against the rules): strong play is mostly #2 stamps.
  The threat-aware bot beat the threat-blind one 27–3. Weighting captures higher won 73%; heavy star hoarding won 40%.
  10 of 105 Blue first moves lose a star immediately (listed in TL;DR).
- **Engine v1 selfplay:** scores of 3–5k, ~75 stars per side at the end.
- **Engine v3** (beat v2 by +137 Elo):
  - Games are capture-heavy. Each side captures about 60 stars and ends with 70–90.
  - **A single placement often erases 4–6 stars of a freshly stamped #2.** Don't stamp #2 where enemy cells can reach it.
  - **Edit-then-stamp is a key attack.** Spend action 1 reshaping a probe blueprint so it fits into a hole, then stamp it with action 2 to capture.
    Example: `1:0,0>1:0,1` then `1@0,-11` scored 240 and 288.
    When you defend, assume the enemy can reshape one cell before stamping.
  - Given a term for blueprint star content, the engine plays the 6-star #2 edits by itself: ply 0 `1:0,1>2:…`, then `3:0,1>2:…`.
    A/B tests of how much weight that term gets were inconclusive.
