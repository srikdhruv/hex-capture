import { Game, qr } from './fast.mjs';
import { bestCapture } from './bots.mjs';
const g = Game.start();
console.log('Red best 2-action capture if Blue passes:', (()=>{g.pass(); const r=bestCapture(g,1,2); g.ply--; return r;})());
console.log('Blue best 2-action capture at start (hypothetical):', bestCapture(g,0,2));
const pl = g.placements(0); console.log('blue first placements', pl.length/2);
const rows=[];
for (let j=0;j<pl.length;j+=2){ const [st,ce]=g.peek(0,pl[j],pl[j+1]); const u=g.place(pl[j],pl[j+1]); const [rp,rs]=bestCapture(g,1,2); rows.push([g.moveString(pl[j],pl[j+1]), ce, rp, rs]); g.undo(u);}
rows.sort((a,b)=>a[2]-b[2]||b[1]-a[1]);
const safe = rows.filter(r=>r[2]===0); console.log('safe first moves (red cannot capture next turn):', safe.length, 'of', rows.length);
console.log('safe & erasing red cells:', safe.filter(r=>r[1]>0).map(r=>r.join(' ')).join(' | '));
console.log('unsafe:', rows.filter(r=>r[2]>0).map(r=>r.join(' ')).join(' | '));
