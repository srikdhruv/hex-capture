// ASCII hex renderer: Blue = B/b/# (star/plain/wall), Red = R/r/%. Rows by r, offset by r/2.
import { idx, qr, STAR, WALL, PLAIN } from './fast.mjs';
export function show(g, marks = new Map()) {
  let qmin = 1e9, qmax = -1e9, rmin = 1e9, rmax = -1e9;
  for (const s of [0, 1]) for (const i of g.occupied(s)) { const [q, r] = qr(i); const x = 2 * q + r; qmin = Math.min(qmin, x); qmax = Math.max(qmax, x); rmin = Math.min(rmin, r); rmax = Math.max(rmax, r); }
  rmin -= 1; rmax += 1; qmin -= 2; qmax += 2;
  const lines = [];
  for (let r = rmin; r <= rmax; r++) {
    let line = (r >= 0 ? ' ' : '') + r + ' '.repeat(4 - String(r).length);
    for (let x = qmin; x <= qmax; x++) {
      if ((x - r) % 2 !== 0) { line += ' '; continue; }
      const q = (x - r) / 2, i = idx(q, r);
      if (marks.has(i)) { line += marks.get(i); continue; }
      const o = g.own[i];
      if (o < 0) line += (q === 0 && r === 0) ? '+' : '.';
      else line += o === 0 ? { [STAR]: 'B', [PLAIN]: 'b', [WALL]: '#' }[g.kind[i]] : { [STAR]: 'R', [PLAIN]: 'r', [WALL]: '%' }[g.kind[i]];
    }
    lines.push(line);
  }
  return lines.join('\n');
}
