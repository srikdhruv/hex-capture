// Wrap the C++ engine (engine/bp CLI) as a lab bot: one action per call.
import { execFileSync } from 'node:child_process';
export default function engineBot(cfg = {}) {
  const bin = cfg.bin || '/tmp/claude-1000/-home-srikd-hex-capture/362302db-4859-47e1-8b23-315eef87deba/scratchpad/bp_lab';
  const args = ['--time-ms', String(cfg.timeMs || 500), '--threads', String(cfg.threads || 1), ...(cfg.extraArgs || [])];
  const bot = (g) => {
    const st = g.toRef(); st.turn = g.seat();
    let out;
    try { out = execFileSync(bin, args, { input: JSON.stringify(st), encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'] }); } catch (e) { return ['pass']; }
    const mv = JSON.parse(out.trim().split('\n').pop()).move;
    if (!mv || mv === 'pass') return ['pass'];
    if (mv.includes('@')) { const [b, at] = mv.split('@'); const [q, r] = at.split(',').map(Number); return [{ b: +b - 1, a: (q + 128) + (r + 128) * 256 }]; }
    return [{ edit: mv }];
  };
  bot.P = {}; bot.label = 'engine';
  return bot;
}
