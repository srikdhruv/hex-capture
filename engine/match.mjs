// Match runner: plays games between two CLI engines using reference rules.
// usage: node engine/match.mjs --a "cmd args" --b "cmd args" [--games 32] [--time-ms 100] [--par 16] [--rand 4]
// Each move: spawn `cmd --time-ms T` with the server-style observation on stdin.
// --rand N: first N plies are random legal moves (shared per game pair) for opening diversity.
import { setup, legalMoves, play, turnOf, movesLeftInTurn, starCounts, TOTAL_PLIES } from '../reference/rules.mjs';
import { spawn } from 'node:child_process';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, x, i, arr) => (x.startsWith('--') ? acc.concat([[x.slice(2), arr[i + 1]]]) : acc), []));
const cmdA = args.a, cmdB = args.b;
const games = +(args.games || 32), timeMs = +(args['time-ms'] || 100), par = +(args.par || 16), randPlies = +(args.rand ?? 2);
let seed = +(args.seed || 7);
const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };

function ask(cmd, state) {
  const view = { ...state, turn: turnOf(state.ply), left: movesLeftInTurn(state.ply), moves: legalMoves(state), stars: starCounts(state.cells) };
  const obs = JSON.stringify({ you: [view.turn], turn: view.turn, ply: state.ply, view, clock: null });
  const parts = cmd.split(' ').filter(Boolean);
  return new Promise((resolve) => {
    const p = spawn(parts[0], [...parts.slice(1), '--time-ms', String(timeMs)]);
    let out = '';
    const t0 = Date.now();
    p.stdout.on('data', (d) => (out += d));
    p.stderr.on('data', () => {});
    p.on('close', () => {
      const dt = Date.now() - t0;
      try { const r = JSON.parse(out.trim().split('\n').pop()); resolve({ move: r.move, dt, legal: view.moves.includes(r.move) }); }
      catch { resolve({ move: null, dt, legal: false }); }
    });
    p.stdin.end(obs);
  });
}

const openings = [];
for (let k = 0; k < Math.ceil(games / 2); k++) {
  let st = setup(); const seq = [];
  for (let i = 0; i < randPlies; i++) { const ms = legalMoves(st).filter((m) => m.includes('@')); const m = ms[Math.floor(rnd() * ms.length)]; seq.push(m); st = play(st, m); }
  openings.push(seq);
}

let wA = 0, wB = 0, d = 0, sA = 0, sB = 0, illegal = 0, maxDt = 0, done = 0;
async function runGame(k) {
  const aSeat = k % 2; let st = setup();
  for (const m of openings[k >> 1]) st = play(st, m);
  while (st.ply < TOTAL_PLIES) {
    const seat = turnOf(st.ply);
    const r = await ask(seat === aSeat ? cmdA : cmdB, st);
    maxDt = Math.max(maxDt, r.dt);
    if (!r.legal) { illegal++; console.error(`illegal from ${seat === aSeat ? 'A' : 'B'}: ${r.move}`); st = play(st, 'pass'); continue; }
    st = play(st, r.move);
  }
  const a = st.scores[aSeat], b = st.scores[1 - aSeat];
  if (a > b) wA++; else if (b > a) wB++; else d++;
  sA += a; sB += b; done++;
  console.log(`game ${k} Aseat ${aSeat} A ${a} B ${b}  [${wA}-${wB}-${d}]`);
}
const queue = [...Array(games).keys()];
await Promise.all(Array.from({ length: par }, async () => { while (queue.length) await runGame(queue.shift()); }));
console.log(`RESULT A ${wA} B ${wB} D ${d} winrateA ${((wA + d / 2) / games * 100).toFixed(1)}% avgA ${(sA / games).toFixed(0)} avgB ${(sB / games).toFixed(0)} illegal ${illegal} maxMoveMs ${maxDt}`);
