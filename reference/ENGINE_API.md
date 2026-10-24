# StrategyJam engine API (summarised from https://strategyjam.org/engines?guide)

- Token: profile -> select supported games (Blueprints) -> "Connect engine". Shown once, expires after 24h.
- WebSocket `wss://strategyjam.org/api/engine/ws` with `Authorization: Bearer <token>`.
  - Server sends `ready`, `inbox` ({games:[{room}]}), `challenge` ({room}), `state` ({room, state}), `tournament` ({tournament, state}), `pong`, `error`.
  - Client sends `{"type":"ping"}` every 25s (expect pong; reconnect if none in 45s),
    `{"type":"watch-game","room":..., "tournament":...?}`, `{"type":"watch-tournament","tournament":...}`.
- HTTP (Bearer): `/api/engine/tournaments/<tid>/you` (GET), `/check-in` (POST {}), `/game` (GET), `/move` (POST {"ply":n,"move":"..."}).
  Standalone/self-test games: POST `/api/engine/games/<room>/move`.
- `state` = {you:[seat...], turn, ply, view:{moves, result, turn, ply, left, cells, blueprints, scores, stars}, clock, startsAt}.
- After timeout / lost response / 409: re-read the board, never replay. 401 = renew token, 403 = enrollment/supported games.
  Respect Retry-After on 429/503. Stop reconnecting on close codes 4001/4003/4004.
- Clock-out plays the game's `timeoutMove` = `pass` (you lose the action, not the game).
- Tournament f46b70969dee "Fall 2026 Strategy Jam": 14 Swiss rounds, 1min + 15s increment, check-in window 3 min each round;
  top 16 knockout at 1min + 25s. A first accepted engine move tags the entry with the Engine label for the whole tournament.
- Self-test: "Test your engine" on the game's Play tab (you play seat 0 in browser, engine seat 1; unrated).

See example_client.py (official random-move client) for the reference protocol handling.
