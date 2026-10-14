export type Strength = "beginner" | "casual" | "club" | "advanced" | "max";
export type Mood = "normal" | "impressed" | "inaccuracy" | "blunder";
export interface GameStatus { state: "ongoing" | "checkmate" | "stalemate" | "draw" | "resigned"; winner: "white" | "black" | null; reason: string | null }
export interface GamePayload {
  game_id: string; fen: string; player_color: "white" | "black"; strength: Strength;
  status: GameStatus; moves: string[]; pgn: string;
  engine_move?: { san: string; uci: string } | null;
  user_move?: { san: string; classification: string; win_drop: number };
  coach_mood?: Mood;
}
export interface Line { rank: number; eval_cp: number; mate_in: number | null; san: string[]; uci: string[] }
export interface Analysis { eval_cp: number; mate_in: number | null; best_uci: string | null; lines: Line[] }
export interface ReviewRow { ply: number; color: "white" | "black"; san: string; eval_cp: number; mate_in: number | null; win_drop: number; class: string; accuracy: number; best_uci: string | null; best_san: string | null; is_best: boolean }
export interface ReviewResult { moves: ReviewRow[]; eval_graph: number[]; best_uci_by_ply: (string | null)[]; accuracy: { white: number | null; black: number | null } }
export interface Job { status: "queued" | "running" | "done" | "error"; progress: number; total: number; result: ReviewResult | null; error: string | null }

export const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public retryAfter: string | null) { super(message); }
}

export function sessionId(): string {
  let id = localStorage.getItem("cb_sid");
  if (!id) { id = crypto.randomUUID(); localStorage.setItem("cb_sid", id); }
  return id;
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", "X-Session-Id": sessionId(), ...init.headers },
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the server. It may be restarting, try again shortly.", null);
  }
  if (!res.ok) {
    const b = await res.json().catch(() => null);
    throw new ApiError(res.status, b?.code ?? "error", b?.message ?? res.statusText, res.headers.get("Retry-After"));
  }
  return res.json();
}

const post = <T,>(p: string, body?: unknown) => req<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined });

export const api = {
  createGame: (color: string, strength: Strength) => post<GamePayload>("/games", { color, strength }),
  move: (id: string, uci: string) => post<GamePayload>(`/games/${id}/move`, { uci }),
  resign: (id: string) => post<GamePayload>(`/games/${id}/resign`),
  takeback: (id: string) => post<GamePayload>(`/games/${id}/takeback`),
  analyze: (fen: string, depth: number, multipv: number) => post<Analysis>("/analyze", { fen, depth, multipv }),
  review: (id: string) => post<{ job_id: string }>(`/games/${id}/review`),
  job: (jobId: string) => req<Job>(`/jobs/${jobId}`),
  thread: (id: string, ply: number) => req<{ role: string; content: string }[]>(`/games/${id}/chat?ply=${ply}`),
};

export const describeError = (e: unknown) =>
  e instanceof ApiError ? (e.code === "engine_busy" ? "Engine is busy, try again in a moment." : e.message) : "Something went wrong.";