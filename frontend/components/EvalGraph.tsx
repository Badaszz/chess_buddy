export function EvalGraph({ evals, ply, onSelect }: { evals: number[]; ply: number; onSelect: (i: number) => void }) {
  const W = 300, H = 80, n = Math.max(evals.length - 1, 1);
  const y = (cp: number) => H - ((50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1)) / 100) * H;
  const pts = evals.map((cp, i) => `${(i / n) * W},${y(cp)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-20 w-full cursor-pointer rounded bg-blue-50"
         onClick={(e) => {
           const r = e.currentTarget.getBoundingClientRect();
           onSelect(Math.max(0, Math.min(evals.length - 1, Math.round(((e.clientX - r.left) / r.width) * n))));
         }}>
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="#9bb6d2" strokeDasharray="3" />
      <polyline points={pts} fill="none" stroke="#245d97" strokeWidth="2" />
      <line x1={(ply / n) * W} x2={(ply / n) * W} y1="0" y2={H} stroke="#0f3f6b" />
    </svg>
  );
}