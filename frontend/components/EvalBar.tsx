export function EvalBar({ cp, mate, flip }: { cp: number | null; mate: number | null; flip: boolean }) {
  if (cp === null) return <div className="w-6 rounded bg-blue-200" />;
  const whiteWins = mate !== null ? mate > 0 || (mate === 0 && cp > 0) : null;
  const wp = whiteWins !== null ? (whiteWins ? 100 : 0) : 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1);
  const label = mate !== null ? (mate === 0 ? "#" : `M${Math.abs(mate)}`) : (Math.abs(cp) / 100).toFixed(1);
  return (
    <div className="flex flex-col items-center gap-1">
      <div className={`flex w-6 flex-1 overflow-hidden rounded bg-blue-900 ${flip ? "flex-col" : "flex-col-reverse"}`}>
        <div className="bg-blue-100 transition-all duration-300" style={{ height: `${wp}%` }} />
      </div>
      <span className="text-[11px] font-semibold tabular-nums text-blue-950">{cp < 0 && mate === null ? "-" : ""}{label}</span>
    </div>
  );
}