"use client";

import { useEffect, useRef, useState } from "react";
import { api, describeError } from "@/lib/api";
import { streamChat, type ChatRequest } from "@/lib/sse";
import type { Mood } from "@/lib/avatarPack";
import { CoachAvatar } from "./CoachAvatar";

interface Msg { role: "user" | "assistant"; text: string; mood?: string }
type Action = NonNullable<ChatRequest["action"]>;
const ACTIONS: { id: Action; label: string }[] = [
  { id: "explain_move", label: "Explain this move" },
  { id: "plan", label: "What's the plan?" },
  { id: "why_not_best", label: "Why not the engine's choice?" },
];

export function Chat({ gameId, ply, onMood }: { gameId: string; ply: number; onMood: (m: Mood) => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [level, setLevel] = useState<"beginner" | "intermediate">("intermediate");
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  // the thread is bound to the selected position
  useEffect(() => {
    abort.current?.abort();
    let cancelled = false;
    setMsgs([]); setError(null); setStreaming(false);
    api.thread(gameId, ply)
      .then((rows) => { if (!cancelled) setMsgs(rows.map((r) => ({ role: r.role as Msg["role"], text: r.content }))); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [gameId, ply]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const patchLast = (fn: (m: Msg) => Msg) =>
    setMsgs((all) => { const c = [...all]; c[c.length - 1] = fn(c[c.length - 1]); return c; });

  const ask = async (q: { question?: string; action?: Action }) => {
    if (streaming) return;
    setError(null); setStreaming(true);
    const label = q.question ?? ACTIONS.find((a) => a.id === q.action)!.label;
    setMsgs((m) => [...m, { role: "user", text: label }, { role: "assistant", text: "" }]);
    const ctl = new AbortController();
    abort.current = ctl;
    try {
      await streamChat({ game_id: gameId, ply, level, ...q }, {
        onToken: (t) => patchLast((m) => ({ ...m, text: m.text + t })),
        onReplace: () => patchLast((m) => ({ ...m, text: "" })),
        onDone: (d) => { patchLast((m) => ({ ...m, mood: d.coach_mood })); onMood(d.coach_mood as Mood); },
      }, ctl.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(describeError(e));
        setMsgs((m) => m.slice(0, -1));       // drop the empty assistant bubble
      }
    } finally { setStreaming(false); }
  };

  return (
    <section className="chat-panel flex flex-col gap-3 p-4 text-sm">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-blue-950">Ask your coach</h2>
          <p className="muted-blue text-xs">Position-aware chess guidance</p>
        </div>
        <select aria-label="Coaching level" value={level} onChange={(e) => setLevel(e.target.value as typeof level)} className="blue-control p-1 text-xs">
          <option value="intermediate">Intermediate</option><option value="beginner">Beginner</option>
        </select>
      </div>
      <div className="flex flex-wrap gap-1">
        {ACTIONS.map((a) => (
          <button key={a.id} disabled={streaming} onClick={() => ask({ action: a.id })}
                  className="chat-action px-2 py-1 text-xs disabled:opacity-50">{a.label}</button>
        ))}
      </div>
      <div className="chat-history flex flex-col gap-2 p-3">
        {msgs.length === 0 && <p className="chat-empty p-3">Ask about this position, or try one of the quick prompts.</p>}
        {msgs.map((m, i) => (
          <div key={i} className={`flex gap-2 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" && <CoachAvatar mood={m.mood ?? "normal"} size={28} />}
            <div className={`max-w-[85%] whitespace-pre-wrap rounded-lg p-3 ${m.role === "user" ? "chat-message-user" : "chat-message-coach"}`}>
              {m.text || (streaming && i === msgs.length - 1 ? "…" : "")}
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>
      {error && <p className="text-red-600">{error}</p>}
      <form onSubmit={(e) => { e.preventDefault(); const q = input.trim(); if (q) { setInput(""); void ask({ question: q }); } }}
            className="flex gap-2">
        <input value={input} onChange={(e) => setInput(e.target.value)} maxLength={500} placeholder="Ask the coach…"
               className="chat-input min-w-0 flex-1 px-3 py-2" />
        <button disabled={streaming} className="blue-primary px-4 disabled:opacity-50">Ask</button>
      </form>
    </section>
  );
}