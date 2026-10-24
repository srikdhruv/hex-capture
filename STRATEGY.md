# Blueprints — Strategy Playbook (live doc, updated during the tournament)

> Tournament: Fall 2026 Strategy Jam, 14 Swiss rounds at 1 min + 15 s/move, then top-16 knockout at 1 min + 25 s.
> Rules source: exact port of the official game code in `reference/rules.mjs`.
> Status: v0 (rules + first-principles strategy). Lab results and engine findings will be merged in as they arrive.

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

## 0. TL;DR — play this way (updated with lab data)

1. **Stamp blueprint #2 (the 4-star flower) almost every action.** In strong bot-vs-bot games nearly every action is a #2 stamp:
   it adds +4 to your multiplier *and* it is your main attacker. Final star counts reach ~75–200 per side, so a late star capture is worth 75–200 points.
2. **Before every stamp, run the threat check:** *"After my turn, can the enemy touch any of my edge stars with 1–2 stamps?"*
   A bot that skipped this check lost 27 of 30 games.
3. **If a stamp can also take a star, take it.** Capture-leaning bots beat pure hoarders 73% vs 40% (n=30 each).
   Best case: grow and capture with the same #2 stamp, placed so that one of its cells touches an exposed enemy star.
4. **Blue's first move: don't drop #2 near the middle.** These first moves lose a star to Red's first turn:
   `2@1,-3 2@-1,1 2@-1,-4 2@-4,2 2@-3,-3 2@-3,-4 2@-2,-4 2@-5,1 2@-5,2 2@-6,2`.
5. **Clock: the +15 s increment comes once per 2-action turn, not per action.** Budget about 7 s per action, or you will drain.

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
