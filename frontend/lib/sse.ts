import { ApiError, BASE, sessionId } from "./api";

export interface ChatRequest {
  game_id: string; ply: number; level: "beginner" | "intermediate";
  question?: string; action?: "explain_move" | "plan" | "why_not_best";
}
export interface ChatHandlers {
  onToken: (text: string) => void;
  onReplace: () => void;
  onDone: (d: { message_id: number; coach_mood: string; fallback: boolean; attempts: number }) => void;
}

export async function streamChat(body: ChatRequest, h: ChatHandlers, signal?: AbortSignal) {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST", signal,
    headers: { "Content-Type": "application/json", "X-Session-Id": sessionId() },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const b = await res.json().catch(() => null);
    throw new ApiError(res.status, b?.code ?? "error", b?.message ?? res.statusText, res.headers.get("Retry-After"));
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const ev = /^event: (.+)$/m.exec(frame)?.[1];
      const data = /^data: (.+)$/m.exec(frame)?.[1];
      if (!ev || !data) continue;
      const d = JSON.parse(data);
      if (ev === "token") h.onToken(d.text);
      else if (ev === "replace") h.onReplace();
      else if (ev === "done") h.onDone(d);
    }
  }
}