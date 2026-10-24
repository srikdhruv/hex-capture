# Blueprints Pilot Playbook

How we play to WIN. The live pilot follows this; humans can too. Evidence lives in `STRATEGY.md`, and the per-game record is in `lab/live_games.txt`.

## 0. The truths that decide games

1. **Score comes only from erasing enemy STARS:** (stars erased) × (your star count before placing).
2. **Sealed means safe forever.** If no empty path from the enemy reaches any hex next to your star, that star can never be taken. Walls never die.
   Once a side is sealed *and* ahead, the game is over.
3. **Walls are the best cells.** A stamp made only of walls attacks, seals and denies, and nothing can erase it.
4. **The opening is a race.** The first capture plus the first seal usually wins.
   Sealing all 6 starting stars takes at least 26 walls (~9 three-wall stamps), so a determined sealer finishes around ply 50–65.
   The front inner flower (Blue (-2,0), Red (2,0)) is sealed last. It is the target.
5. **The multiplier only matters if you can still reach enemy stars.** Against a sealed enemy, your stars are only targets.
6. **The clock is 120 plies.** Blue moves 0, then turns go R R B B …; Red's last turn is 117–118 and Blue has the final action at 119.
   Count the turns you have left.

## 1. Per-turn thinking protocol (do it EVERY turn, in this order, briefly)

Write a 4-line plan into `control.json` `note` and keep it updated:
```
PHASE: opening(0-20) / race(20-60) / middlegame(60-100) / endgame(100-119); turns left for us: N
THEM  short: their capture threats next turn, as hexes next to our stars that they can reach
      long:  their style (rusher / wall-sealer / Fortlite / stacker), how close they are to sealed (open holes per star), their multiplier
US    short: captures available now (snipe, or breach+snipe); holes to plug
      long:  are we ahead? Are we sealed? Which enemy star is the crack target, and how many turns until we reach it?
```
Then decide, in priority order:
1. **Take a capture** if one is available (biggest points). A breach+snipe in one turn counts.
2. **Stop their capture**: plug the hole next to our star, or erase their attacking cell.
   If a 2-cell piece can block it, use action 1 to reorient it and action 2 to place it.
3. **Race:** if they are not sealed yet, move toward their least-sealed star (the front inner flower first). Erase their shield plains and get adjacent.
4. **Seal:** if we are ahead, or their attack is coming, close our own holes with walls first.
5. **Build:** only add stars where they can't reach (count their longest piece). Never build next to their walls.
6. **Deny:** drop cells, ideally walls, where their big pieces want to land, and cut their snake paths to us.

## 2. Reading the opponent in the first 12 plies

| Sign | Style | Our plan |
|---|---|---|
| Stamps star-heavy pieces at us from ply 0 | **Rusher** | **Abandon the book now.** Recapture and plug; their stamped stars are exposed, so snipe them. Our multiplier is low early, but their flowers are juicy. |
| Edits that move walls together (3-wall line), then wall stamps | **Wall-sealer / turtle** | Crack their front inner flower **before ply ~50**. Never feed them exposed stars. After they seal: seal ourselves and protect the lead. |
| Fortlite-like edits (plains into #2) | **Fortlite** | Mirror: finish our book, then breach+snipe. #2 builds only when quiet. |
| Stacks stars into one blueprint with no shield | **Stacker** | Their stamps leave exposed stars. Snipe each one. |

## 3. Engine knobs (via `control.json` `engine_args`)

| Knob | What it does | When to set it |
|---|---|---|
| `--p bookMargin=N` | Lower = the opening book yields sooner. | Use 10–30 under fire, 100 when quiet. |
| `--nobook` | Turns the opening book off. | Against rushers. |
| `--p alpha=X` | Value of a star per remaining ply (default 0.1). | 0 when the enemy is sealed or wall-sniping; 0.02 when racing. |
| `--p beta=X` | Weight of our follow-up capture threat. | Raise it (~1.0) when attacking. |

- **Veto** engine edits that break #2's shield or delete the #3 sniper, unless that edit is what makes a capture possible.
- **Force** any capture you have verified that the engine misses.

## 4. Endgame (from ply ~100)

- **Captures over everything.** Stars are worth 0 at the end; only score counts.
- **Blue at 119:** make the single biggest capture.
- **Red at 117–118:** two captures, or breach + snipe. After 118, leave **no** hex that touches both a Red star and a Blue cell.
- If ahead and sealed: just plug holes. If behind: every action goes to the highest capture chance, even at a risk.

## 5. Live lessons (pilot)

- **R10, won 5613–1403 against a rusher, from 0–112 down.** Drop the book at once (bookMargin 10, or `--nobook`).
  A sealed #2 plus the star sniper beats exposed rush stars.
- **R11, won 3140–595 against a slow wall-sniper stacker.**
  - Crack early. Their 6 opening edits gave us the front star at ply 8 and two more at ply 20, before any wall went up.
  - **Edit-then-stamp is our big weapon:** reshaping #1 or #3 into a probe, then stamping it, scored +492, +417 and +536.
  - Use `take_capture_min≈50`. The engine sometimes passes up cheap snipes to build instead; force the capture.
  - Once a long enemy probe appears, set `star_safe_dist=7`. Against stackers, the danger is their late multiplier, so take every capture early.
