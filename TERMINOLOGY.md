# Blueprints: Terminology

These are the terms used in this repo, by our agents, and by players and the livestream.
The tag in brackets says where each term comes from:

- **[rules]**: an official game term.
- **[players]**: a word human players or the stream used.
- **[ours]**: a word we made up in this project.

## Board and pieces

| Term | Meaning |
|---|---|
| **Hex / cell** [rules] | One space on the infinite axial hex plane, written `q,r`. Each cell has an owner (Blue = seat 0, Red = seat 1) and a kind. |
| **Star / Wall / Plain** [rules] | The three cell kinds. **Stars** score when the enemy erases them. **Walls** can never be erased or covered. **Plains** are erasable filler. |
| **Blueprint / piece** [rules] | One of each player's 3 reusable shapes. Every player always owns exactly 6 stars, 3 walls and 12 plains, spread across their blueprints. |
| **Hand** [ours] | A player's 3 blueprints at a moment in the game. Written compactly, e.g. `7c:1s0w6p` = 7 cells: 1 star, 0 walls, 6 plains. |
| **Flower** [ours] | A 7-hex blueprint (a centre plus its ring), as in the starting shapes. |
| **Star flower** [ours] | The starting #2: 4 stars + 3 walls. |
| **Start flowers** [ours] | The three flowers each side begins with, centred at q = ±2, ±6, ±10 on r = 0. |
| **Front inner flower** [ours] | The starting flower nearest the enemy: Blue (-2,0), Red (2,0). It is the classic crack target, and sealers usually close it last. |

## Moves

| Term | Meaning |
|---|---|
| **Place / stamp** [rules / ours] | Copy a blueprint onto empty hexes so that it touches one of your cells. Notation: `b@q,r`. |
| **Edit** [rules] | Move one cell within or between your blueprints. It costs a full action. Notation: `b1:q,r>b2:q,r`. |
| **Capture / erase / eat** [rules / players] | Every enemy non-wall cell touching a newly stamped hex is erased. Erasing a star scores (stars erased) × (your star count). |
| **Multiplier** [ours] | Your current star count on the board. Every capture is worth that much per star. |
| **Ply / action** [ours] | One move. A game is 120 plies. Blue plays 1, then the sides alternate turns of 2 actions: R R B B …, and Blue has the final ply, 119. |

## Tactics

| Term | Meaning |
|---|---|
| **Snipe** [ours/players] | Stamp a tiny piece (usually 1 hex) into a hole next to an enemy star to capture it. |
| **Sniper** [ours] | The tiny piece used to snipe. In Fortlite, #3 ends up as a single-star sniper. |
| **Breach** [ours] | Action 1 of a turn: erase the plains shielding an enemy star. |
| **Breach + snipe** [ours] | The core 2-action combo: breach, then snipe into the hole you just opened. |
| **Edit-then-stamp** [ours] | Action 1 reshapes a piece so that it fits; action 2 stamps it. This produced the engine's biggest captures. |
| **Probe** [ours] | A thin or small piece built to reach into gaps. |
| **Chevron** [ours] | A 3-plain probe bent at 120°. Wrapped around a fort's ring wall, it can take 2 stars from one breach. |
| **Hole** [ours] | An empty hex next to a star, which is where a snipe lands. |
| **Crack** [ours] | The first capture against a fortress or sealer, typically on their front inner flower. |
| **Denial / being annoying** [players] | Dropping cells, walls especially, where the enemy's big pieces need to fit, so their stamps and snake paths are blocked. |
| **Immune sniper / wall sniper** [ours] | A wall-only piece, e.g. `www`. It captures what it touches but can never be erased back. |

## Strategies and archetypes

| Term | Meaning |
|---|---|
| **Fortress / turtle** [players] | Wall in your own stars so they can't be reached. |
| **Wall city / sealer** [ours] | The strongest fortress form: `#2` becomes a `www` wall chain, stamped everywhere; only the starting stars are kept, and the side is sealed by ply ~32–72. Most of the final top 16 played this. |
| **Sealed** [ours] | No path of empty hexes from the enemy reaches any hole next to your stars. A sealed side can never be scored on again. |
| **Min-cut / walls-to-seal** [ours] | The exact minimum number of extra walls needed to seal all of your stars. The starting position needs 26 per side. |
| **Blob / star flood** [players / ours] | Stamp huge star-heavy pieces to pump up the multiplier. This produces scores in the thousands. |
| **Stacking** [ours] | Moving all your stars into one blueprint. |
| **Stick / line / slither** [players] | A long thin piece that reaches around into the enemy's territory. "Slither" is the snake-shaped version, often carrying walls. |
| **Rusher** [ours] | Stamps star pieces straight at the enemy's start flowers from ply 0. |
| **Fortlite** [ours] | Our best opening in lab tests. It takes 9 edits to wrap plains around #2's 3 edge stars, so all 4 #2 stars become interior; #3 becomes a 1-star sniper. |
| **Hex19 / Fort18 / D1–D4 / H1** [ours] | Alternative hand designs from the lab. All of them lost to Fortlite. |
| **Run-away colony** [players/ours] | Build stars far from the enemy and use a stick to get there. Never shown to work. |
| **Lead then seal** [ours] | Get ahead, then wall yourself in. True as a principle; it failed as a mid-game switch in the lab. |
| **Sniper loop** [ours] | Fortlite mirror middlegames, where each side snipes 1 star per action. |
| **Book / opening book** [ours] | The engine's scripted opening, e.g. the Fortlite edits. **bookYield** is the rule for abandoning the book under threat. |

## Our infrastructure

| Term | Meaning |
|---|---|
| **Engine / bp** | The C++ search engine (`engine/`). |
| **Pilot** | An AI or human co-pilot steering the engine live through `client/pilot/` (control.json, rules.json, picks). |
| **Pilot daemon** | `tools/pilot_daemon.py`: answers picks instantly from editable rules. |
| **Arena** | `tools/arena.py`: parallel A/B matches between any two policies. |
| **Replica bots** | Bots copying real opponents: `engine/replica.mjs` (Eris, aryan, rusher) and `tools/bots/sealer.py`. |
| **Lab** | `lab/`: fast JS simulator, heuristic bots and tournaments. |
| **Scout** | `tools/scout/`: harvests and analyses real tournament games. |
| **Live ops** | The agent that kept the bot alive and post-mortemed every game. |
