"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Chess, type Square } from "chess.js";
import { Chessboard } from "react-chessboard";
import { api, describeError, type Analysis, type GamePayload, type Mood, type ReviewResult, type Strength } from "@/lib/api";
import { CoachAvatar } from "@/components/CoachAvatar";
import { Chat } from "@/components/Chat";
import { EvalBar } from "@/components/EvalBar";
import { EvalGraph } from "@/components/EvalGraph";

const STRENGTHS: Strength[] = ["beginner", "casual", "club", "advanced", "max"];
const CLASS_COLOR: Record<string, string> = {
  ok: "text-neutral-500", inaccuracy: "text-yellow-600", mistake: "text-orange-600", blunder: "text-red-600",
};

export default function Home() {
  const [game, setGame] = useState<GamePayload | null>(null);
  const [fen, setFen] = useState(new Chess().fen());
  const [color, setColor] = useState<"white" | "black" | "random">("white");
  const [strength, setStrength] = useState<Strength>("casual");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mood, setMood] = useState<Mood>("normal");
  const [lastMove, setLastMove] = useState<GamePayload["user_move"] | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [showEngineLines, setShowEngineLines] = useState(true);
  const [dots, setDots] = useState<Record<string, CSSProperties>>({});
  const [promo, setPromo] = useState<{ from: string; to: string } | null>(null);
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [reviewPly, setReviewPly] = useState(0);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const reqId = useRef(0);

  const orientation = game?.player_color ?? "white";
  const over = !!game && game.status.state !== "ongoing";

  // positions for review mode (index = plies played)
  const reviewFens = useMemo(() => {
    const c = new Chess();
    const out = [c.fen()];
    for (const san of game?.moves ?? []) { c.move(san); out.push(c.fen()); }
    return out;
  }, [game?.moves]);
  const shownFen = review ? reviewFens[Math.min(reviewPly, reviewFens.length - 1)] : fen;

  const movePairs = useMemo(() => {
    const out: [string, string?][] = [];
    (game?.moves ?? []).forEach((m, i) => (i % 2 === 0 ? out.push([m]) : (out[out.length - 1][1] = m)));
    return out;
  }, [game?.moves]);

  // avatar returns to normal after ~4s
  useEffect(() => {
    if (mood === "normal") return;
    const t = setTimeout(() => setMood("normal"), 4000);
    return () => clearTimeout(t);
  }, [mood]);

  // eval bar + top lines. Live: depth 12 x3 lines. Review: depth 14 x1 line (hits the review cache).
  useEffect(() => {
    if (!game || busy) return;
    const id = ++reqId.current;
    const t = setTimeout(async () => {
      try {
        const a = review ? await api.analyze(shownFen, 14, 1) : await api.analyze(shownFen, 12, 3);
        if (id === reqId.current) setAnalysis(a);
      } catch { /* eval bar is non-critical */ }
    }, 150);
    return () => clearTimeout(t);
  }, [shownFen, busy, game?.game_id, review]);

  // arrow keys step through the review
  useEffect(() => {
    if (!review) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") setReviewPly((p) => Math.max(0, p - 1));
      if (e.key === "ArrowRight") setReviewPly((p) => Math.min(reviewFens.length - 1, p + 1));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [review, reviewFens.length]);

  const guard = async (fn: () => Promise<void>) => {
    setError(null);
    try { await fn(); } catch (e) { setError(describeError(e)); }
  };

  const newGame = () => guard(async () => {
    setBusy(true);
    try {
      const g = await api.createGame(color, strength);
      setGame(g); setFen(g.fen); setMood("normal"); setLastMove(null); setReview(null); setAnalysis(null);
    } finally { setBusy(false); }
  });

  const submit = async (from: string, to: string, promotion?: string) => {
    if (!game) return;
    const c = new Chess(fen);
    try { c.move({ from, to, promotion }); } catch { return; }
    const prev = fen;
    setFen(c.fen()); setBusy(true); setError(null);          // optimistic
    try {
      const res = await api.move(game.game_id, from + to + (promotion ?? ""));
      setGame(res); setFen(res.fen); setMood(res.coach_mood ?? "normal"); setLastMove(res.user_move ?? null);
    } catch (e) { setFen(prev); setError(describeError(e)); }
    finally { setBusy(false); }
  };

  const onDrop = (from: string, to: string, piece: string) => {
    setDots({});
    if (!game || busy || review || over) return false;
    const c = new Chess(fen);
    if (c.turn() !== (game.player_color === "white" ? "w" : "b")) return false;
    const isPromo = piece[1] === "P" && ((piece[0] === "w" && to[1] === "8") || (piece[0] === "b" && to[1] === "1"));
    if (isPromo) {
      try { c.move({ from, to, promotion: "q" }); } catch { return false; }   // geometry check
      setPromo({ from, to });
      return false;                                                            // apply after the picker
    }
    try { c.move({ from, to }); } catch { return false; }
    void submit(from, to);
    return true;
  };

  const resign = () => guard(async () => { if (game) { const g = await api.resign(game.game_id); setGame(g); } });
  const takeback = () => guard(async () => {
    if (!game) return;
    const g = await api.takeback(game.game_id);
    setGame(g); setFen(g.fen); setLastMove(null);
  });

  const exportPgn = () => {
    if (!game) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([game.pgn], { type: "text/plain" }));
    a.download = "chess-buddy-game.pgn";
    a.click();
  };

  const startReview = () => guard(async () => {
    if (!game) return;
    setProgress({ done: 0, total: 0 });
    const { job_id } = await api.review(game.game_id);
    const poll = setInterval(async () => {
      try {
        const j = await api.job(job_id);
        setProgress({ done: j.progress, total: j.total });
        if (j.status === "done" && j.result) {
          clearInterval(poll); setProgress(null); setReview(j.result); setReviewPly(game.moves.length);
        } else if (j.status === "error") {
          clearInterval(poll); setProgress(null); setError(j.error ?? "Review failed");
        }
      } catch (e) { clearInterval(poll); setProgress(null); setError(describeError(e)); }
    }, 1000);
  });

  const reviewRow = review && reviewPly > 0 ? review.moves[reviewPly - 1] : null;
  const bestArrow = review?.best_uci_by_ply[reviewPly];
  const arrows = (bestArrow ? [[bestArrow.slice(0, 2), bestArrow.slice(2, 4), "rgb(0,160,0)"]] : []) as [Square, Square, string][];

  return (
    <main className="app-shell mx-auto flex min-h-screen max-w-5xl flex-col gap-4 p-4 md:flex-row">
      {/* board column */}
      <div className="flex w-full flex-col gap-2 md:w-[520px]">
        <div className="flex items-center gap-2">
          <CoachAvatar mood={mood} />
          <span className="text-sm text-neutral-600">
            {lastMove ? <>Your move <b>{lastMove.san}</b>: <span className={CLASS_COLOR[lastMove.classification]}>{lastMove.classification}</span></> : "Coach"}
          </span>
        </div>
        <div className="flex gap-2">
          <EvalBar cp={analysis?.eval_cp ?? null} mate={analysis?.mate_in ?? null} flip={orientation === "black"} />
          <div className="relative flex-1">
            <Chessboard
              position={shownFen}
              boardOrientation={orientation}
              arePiecesDraggable={!!game && !busy && !over && !review}
              onPieceDrop={(from, to, piece) => onDrop(from, to, piece)}
              onPromotionCheck={() => false}  // we run our own picker
              onPieceDragBegin={(_p, sq) => {
                const styles: Record<string, CSSProperties> = {};
                for (const m of new Chess(fen).moves({ square: sq as Square, verbose: true }))
                  styles[m.to] = { background: "radial-gradient(circle, rgba(0,0,0,.25) 25%, transparent 26%)" };
                setDots(styles);
              }}
              onPieceDragEnd={() => setDots({})}
              customSquareStyles={dots}
              customArrows={arrows}
            />
            {promo && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40">
                <div className="flex gap-2 rounded bg-white p-3">
                  {["q", "r", "b", "n"].map((p) => (
                    <button key={p} className="h-12 w-12 rounded border text-xl uppercase hover:bg-neutral-100"
                            onClick={() => { const m = promo; setPromo(null); void submit(m.from, m.to, p); }}>{p}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        {busy && <p className="text-sm text-neutral-500">Engine thinking…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {game && over && (
          <p className="rounded bg-neutral-100 p-2 text-sm font-medium">
            {game.status.state === "checkmate" && `Checkmate, ${game.status.winner} wins`}
            {game.status.state === "stalemate" && "Stalemate"}
            {game.status.state === "draw" && `Draw (${game.status.reason?.replaceAll("_", " ")})`}
            {game.status.state === "resigned" && `You resigned, ${game.status.winner} wins`}
          </p>
        )}
      </div>

      {/* side panel */}
      <div className="flex flex-1 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <select value={color} onChange={(e) => setColor(e.target.value as typeof color)} className="blue-control p-1">
            <option value="white">White</option><option value="black">Black</option><option value="random">Random</option>
          </select>
          <select value={strength} onChange={(e) => setStrength(e.target.value as Strength)} className="blue-control p-1">
            {STRENGTHS.map((s) => <option key={s}>{s}</option>)}
          </select>
          <button onClick={newGame} disabled={busy} className="blue-primary px-3 py-1 disabled:opacity-50">New game</button>
        </div>

        {game && (
          <div className="flex flex-wrap gap-2 text-sm">
            <button onClick={takeback} disabled={busy || !!review} className="blue-control px-2 py-1">Take back</button>
            <button onClick={resign} disabled={busy || over} className="blue-control px-2 py-1">Resign</button>
            <button onClick={exportPgn} className="blue-control px-2 py-1">Export PGN</button>
            {!review
              ? <button onClick={startReview} disabled={!!progress || game.moves.length === 0} className="blue-control px-2 py-1">
                  {progress ? `Reviewing ${progress.done}/${progress.total || "…"}` : "Review game"}
                </button>
              : <button onClick={() => setReview(null)} className="blue-control px-2 py-1">Exit review</button>}
          </div>
        )}

        {game && (
          <Chat gameId={game.game_id} ply={review ? reviewPly : game.moves.length} onMood={setMood} />
        )}

        {/* top engine lines */}
        {analysis && (
          <div className="app-panel p-3 text-sm">
            <div className="mb-1 flex items-center justify-between font-medium">
              <span>Engine lines</span>
              <button
                type="button"
                aria-expanded={showEngineLines}
                aria-controls="engine-lines-content"
                onClick={() => setShowEngineLines((visible) => !visible)}
                className="rounded border px-2 py-0.5 text-xs font-normal"
              >
                {showEngineLines ? "Hide" : "Show"}
              </button>
            </div>
            {showEngineLines && (
              <div id="engine-lines-content">
                {analysis.lines.map((l) => (
                  <div key={l.rank} className="flex gap-2 font-mono text-xs">
                    <span className="w-12 shrink-0 tabular-nums">{l.mate_in !== null ? `M${l.mate_in}` : (l.eval_cp / 100).toFixed(2)}</span>
                    <span className="truncate">{l.san.slice(0, 6).join(" ")}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* review */}
        {review && (
          <div className="rounded border p-2 text-sm">
            <div className="mb-2 flex justify-between">
              <span>Accuracy: White {review.accuracy.white ?? "–"}% · Black {review.accuracy.black ?? "–"}%</span>
              <span className="text-neutral-500">← → to step</span>
            </div>
            <EvalGraph evals={review.eval_graph} ply={reviewPly} onSelect={setReviewPly} />
            {reviewRow && (
              <p className="mt-2">
                {reviewRow.san}: <span className={CLASS_COLOR[reviewRow.class]}>{reviewRow.class}</span>
                {!reviewRow.is_best && reviewRow.best_san && <> · best was <b>{reviewRow.best_san}</b></>}
              </p>
            )}
          </div>
        )}

        {/* move list */}
        <div className="app-panel max-h-64 overflow-y-auto p-3 font-mono text-sm">
          {movePairs.map(([w, b], i) => {
            const cls = (ply: number) => (review ? `cursor-pointer hover:underline ${review.moves[ply - 1] ? CLASS_COLOR[review.moves[ply - 1].class] : ""}` : "");
            return (
              <div key={i} className="flex gap-3">
                <span className="w-6 text-neutral-400">{i + 1}.</span>
                <span className={`w-16 ${cls(i * 2 + 1)}`} onClick={() => review && setReviewPly(i * 2 + 1)}>{w}</span>
                {b && <span className={`w-16 ${cls(i * 2 + 2)}`} onClick={() => review && setReviewPly(i * 2 + 2)}>{b}</span>}
              </div>
            );
          })}
        </div>
      </div>
    </main>
  );
}