# Blueprints engine (`engine/bp`)

C++17 search engine for StrategyJam "Blueprints". This document describes HEAD (approach term on, bookYield=2,
Fortlite book built in). Rules ground truth: `reference/rules.mjs`.

```
engine/
  bp.cpp            CLI: search / --perft / --dump / --selfplay, book wiring, history-based edit count
  game.hpp          board, blueprints, movegen, apply/undo, JSON load/save (exact port of rules.mjs)
  search.hpp        Params, eval, capture/threat search, turn search, selfplay
  book.hpp          opening books (edit lists / target hands), built-in Fortlite
  json.hpp          minimal JSON parser
  build.sh          portable build (BP_NATIVE=1 adds -march=native; CXX honoured)
  test_movegen.mjs  cross-check vs reference/rules.mjs (move sets + post-move states)
  match.mjs         simple binary-vs-binary match runner (tools/arena.py is the main A/B tool)
  replica.mjs       lab replica bots (eris / aryan / rusher) behind the engine CLI, using legal edit plans
  books/            fortlite (default), hex19, fort18, fortlite-p, chevA/B
  regress/          positions from live rounds R8 (turtle) and R9 (wall city)
```

## 1. CLI contract

```
engine/bp [--time-ms N] [--threads T] [--book FILE | --nobook] [--p key=val ...] < obs.json
  -> {"move":"...","eval":x,"pv":[...],"top":[{"move","score"} x<=8],"nodes":n}
```
* Input: server observation `{you,turn,ply,view,clock,history?}`, a bare view `{ply,cells,blueprints,scores,moves?}`,
  or the postmortem wrapper `{"state":{...}}`.
* If `view.moves` is present the chosen move is always one of them. On any error it prints the first legal move
  (or `pass` only if nothing is known). Logs go to stderr; stdout is always one JSON line.
* Defaults: 8000 ms, threads = hardware_concurrency (cap 16).
* `--perft` prints the legal move list. `--dump` reads JSONL `{state, apply:[moves]}` and prints sorted moves and
  post-move states (used by the test). `--selfplay N --time-ms M [--a k=v] [--b k=v] [--p k=v] [--booka F] [--bookb F] [--seed S]`.

## 2. Data structures

```
 Grid: uint8 g[256*256]   internal coords (q,r) in [-128,127], idx = (r+128)*256 + (q+128)
       cell byte = kind | seat<<2      kind: 0 empty, 1 wall, 2 star, 3 plain
       neighbours: idx + ND[d], ND = {+1, +1-256, -256, -1, -1+256, +256}   (axial DIRS order)
       loaded boards are recentred (external = internal + shift); stamps beyond |q|,|r|>120 are not generated

 BP (blueprint): n<=21 cells (q,r,kind), precomputed idx offsets d[], stars, diam, cover
 Hand: BP b[3] per seat.      Game: grid + hands[2] + score[2] + stars[2] + ply + bbox + scratch "seen" array
 Undo: list of (idx, old byte) + saved scalars + saved hand (for edits)  -> make/unmake, no board copies
```

Movegen (exact rules.mjs semantics):
```
 placements: frontier = empty cells next to own cells (bbox scan)
             for each blueprint, frontier cell f, bp cell j: offset = f - d[j] (deduped); legal if all cells empty
 edits:      for each (from bp, cell k): rest = bp - k; restOk = connected(rest)
             to bp t: spots = neighbours of target (or {0,0} if empty), minus k when t==from
             legal if from!=t ? restOk : (restOk || connected(rest+spot))      -> "fi:kq,kr>ti:sq,sr"
 apply place: stamp cells, erase enemy non-walls adjacent to any stamped cell,
              score += erasedStars * stars[mover] (count before the stamp); stars updated incrementally
 apply edit:  move cell, normalise both blueprints (min r, then min q -> 0,0)
```

## 3. Turn search

```
 root (side S, L = actions left in turn: 1 or 2)
  |
  |-- order all first actions:  static(S) + 0.8*myBestCapture   (L=2)   or   static(S) - 1.0*oppBestCapture (L=1)
  |-- [book move forced to the front if the book has one]
  |-- widening stages (K1 x K2) = (4x4),(8x6),(12x8),...,(1024x64)
  |      second actions per first action ordered by static(S) - oppBestCapture
  |      each combo -> LEAF
  |      a stage starts only before widenStop (85%) of the budget; workers stop at the hard deadline
  |
  LEAF(after our turn):
     opponent reply = replySearch(O, L_O):              (capture-oriented 2-action search)
         - every placement that erases a star or a plain next to a star (breach), then the best capture
         - every edit, then the best capture with the reshaped blueprint (edit-then-stamp)
         - baseline "no capture"
     apply reply, then leafS(S) = static(S)
                               + beta * (our best 2-action capture turn gain)    (third turn)
                               + positional(S)
```
Capture candidate generation only considers "attack cells" (empty cells next to enemy stars, plus those next to
plains touching stars for breaches). A reach filter skips cells farther from our cells than the piece diameter + 1.
Edit-then-stamp fits use 64-bit masks over a radius-4 hex disc (61 bits) with a per-shape cache. Follow-up captures
after a move are computed incrementally: the pre-move capture list is re-validated, then only cells near the
changed area are rescanned.

Threads: each phase (ordering, second-action lists, leaves) is a parallel-for over tasks. Every worker has its own
Game copy, and an atomic index hands out tasks.

## 4. Evaluation

```
 static(S) = score[S]-score[O]
           + alpha * R * (stars[S]*scale[S] - stars[O]*scale[O])          R = plies remaining
           - crackW * max(0,(crackPly-ply)/crackPly) * stars[O]            (off by default)
           + hw / hcov hand terms                                           (off by default)
 scale[X]  = max(minScale, min(1, reachableTargets(X)/vulnK))   computed once per search
             reachableTargets: enemy stars whose empty (or erasable-neighbour) hex is within reachL
             empty hexes of X's frontier by BFS. Wall-sealed opponents give scale -> minScale.
 positional(S) = approachW * (approachCost(O) - approachCost(S))
                 approachCost: BFS from frontier through empty + enemy plains to a hex next to an enemy star
               + expo * (exposed[O]*stars[S] - exposed[S]*stars[O])      exposed = star with an empty neighbour
               + mob  * (frontier[S] - frontier[O])
               + expoB * (BFS-reachable targets both ways)              (off)
```

Book (`book.hpp`): the built-in default is the lab's Fortlite (9 edits: #2 = 4-star flower with all stars shielded by
plains, #1 = star + 3 plains, #3 = single-star sniper). The book move is searched first and played if its value is
within `bookMargin` of the best, unless `bookYield` says otherwise:
* bookYield=2 (default): skip the book if the opponent can capture after the book move, if the best line captures,
  or once the opponent has scored.
* bookYield=1: skip only if the book concedes more stars than the best line, or the best line captures.
* Edit cap: book length + 2, counted from `history`. The built-in book's maxPly is 26.

## 5. Knobs (`--p key=value`)

| knob | default | meaning |
|---|---|---|
| alpha | 0.10 | star value per remaining ply |
| beta | 0.5 | weight of our next capture turn at the leaf |
| ordMy / ordOpp | 0.8 / 1.0 | ordering weights of follow-up captures |
| expo | 0.02 | exposed-star term |
| mob | 0.02 | frontier term |
| approachW | 5 | approach-cost term |
| crackW / crackPly | 0 / 60 | early-crack term |
| expoB | 0 | BFS-reach exposure term |
| reachL / vulnK / minScale | 12 / 4 / 0.3 | reach-scaled star value |
| reachD | 7 | hex-distance reach (used only if reachL=0) |
| hw / hcov | 0 / 0 | hand potential / shield cover |
| editThreat | 1 | edit-then-stamp in replies |
| third | 1 | 2-action own capture turn at the leaf (0 = 1 action) |
| incr | 1 | incremental follow-up captures |
| bookMargin | 100 | book tolerance |
| bookYield | 2 | book tactical override mode |
| noEditPly | 0 | from this ply, edits only if they increase our immediate capture |
| buildBase | 0 | reply baseline credits unused actions as builds |
| widenStop | 0.85 | last fraction of the budget at which a widening stage may start |
| maxK1 / maxK2 | 1024 / 64 | widening caps |
| verify, vK1, vK2, widenFrac | 0, 10, 6, 0.45 | deep verification stage (lost A/B; off) |
| openRand / openPlies / randPlies | 0 | selfplay opening diversity |

## 6. Tooling

* Correctness: `node engine/test_movegen.mjs [games] [seed]`. About 5k positions, 4.5M moves and 120k post-move states
  checked, 0 failures.
* A/B: `python3 tools/arena.py --a "engine/versions/bp-X --threads 1" --b "..." --games 32 --jobs 4 --time-ms 1000`.
  Opponents can be `node tools/greedy.mjs`, `python3 tools/bots/sealer.py`, or `node engine/replica.mjs --bot eris|aryan|rusher`.
* Fast param sweeps: `engine/bp --selfplay 64 --time-ms 300 --threads 4 --p randPlies=2 --b alpha=0.2`.
* Regression: `for f in engine/regress/*.json lab/positions/*.json; do engine/bp --time-ms 2000 < $f; done`.
  Stderr shows book decisions (`book ... played/overridden (book val/lost/pts | best ...)`), starScale and approach costs.
* Debug env: `BP_TRACE=1` (selfplay per-ply trace), `BP_SAVE_PLY=n` (dump state), `BP_BOOKTEST=1` (print the book path).

## 7. A/B history (arena unless noted; 1 thread per engine)

| test | result |
|---|---|
| v1 vs tools/greedy.mjs (200ms) | 16-0 |
| v2 (third-turn threat, positional, widening) vs v1 (200ms) | 19-13 |
| v3 (edit-then-stamp threats, masks, incremental) vs v2 (300ms) | 44-20, Elo +137 |
| selfplay beta 0.5 vs 0 / vs 1 (96 g) | 59-37 / 59-37 |
| selfplay alpha 0.1 vs 0.05 (96 g) | 57-39 |
| editThreat on vs off (1s) | 20-12 |
| verify on vs off (1500ms x4 / 1s+book) | 9-7 / 11-21 -> off |
| Fortlite book vs no book (1s) | 31-1, +1934 |
| hex19 / fort18 / fortlite-p / chevA vs Fortlite | 1-31 / 4-28 / 14-50 / 6-26 |
| selfplay bookMargin 100 vs 40 / vs 250 | 57-7 / 33-31 |
| selfplay alpha (with book) 0.1 vs 0.3 / 0.5 / 0.07 / 0.14 | 56-8 / 62-2 / 51-13 / 27-37 |
| turtle book (alpha=0) vs default | 0-16 |
| selfplay bookYield 2 vs 0 / 1 vs 0 (mirror) | 0-16 / 8-8 |
| selfplay noEditPly=28 vs off (mirror) | 4-12 -> off |
| approachW=5 vs e9eef9d (1s) | 16-8, Elo +120 |
| 0de5e44 vs replicas eris / aryan / rusher (8 g each) | 6-2 / 8-0 / 8-0 |
| 6000ms vs 1000ms (16 g) | 9-7 |
| final arena (HEAD, sealer, replicas) | see lab/FINAL_ARENA.txt |

## 8. Known weaknesses

* **Horizon:** our turn, the opponent's capture reply and our capture threat (about 2.5 turns). Multi-turn plans
  (approach, sealing, cracking a closing seal) come only from heuristic terms (approachW, reach-scaled alpha).
* **Mirror-tuned:** most parameters were tuned in Fortlite-vs-Fortlite selfplay. Live opponents were wall sealers,
  rushers and turtles. Mirror results (e.g. bookYield, noEditPly) do not always transfer.
* **Sealer play:** the engine has no explicit "lead then seal" mode. It keeps stamping stars when ahead (exposure is
  only penalised through expo/approach), and against sealed opponents it does not detect a lost position early.
* **Opponent replies are capture-only:** the opponent's quiet or defensive turns are not searched (verification
  stage tried; lost).
* Post-book edits can still reshape the Fortlite hand when evals are near-equal (noEditPly exists but is off).
* The book's yield rule is binary; strict yield (2) is good against rushers and bad in Fortlite mirrors.
