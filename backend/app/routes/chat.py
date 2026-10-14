import json
import logging
import time
from contextlib import aclosing
from typing import Literal

import chess
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openai import OpenAIError
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from ..chess_utils import position_at
from ..coach import (build_messages, correction, display, fallback_text, llm_enabled,
                     pop_sentences, stream_reply, validate)
from ..config import settings
from ..db import SessionLocal
from ..deps import get_engine, get_game, session_id
from ..engine import EngineManager
from ..errors import ApiError
from ..facts import build_facts, extract_whatif, norm
from ..models import ChatMessage, CoachLog

router = APIRouter(tags=["coach"])
logger = logging.getLogger(__name__)

QUICK = {
    "explain_move": "Explain the last move: was it good or bad, and why?",
    "plan": "What's a good plan for the side to move here?",
    "why_not_best": "Why was the engine's preferred move better than the move that was just played?",
}


class ChatIn(BaseModel):
    game_id: str
    ply: int | None = Field(None, ge=0)         # position = this many plies into the game (None = latest)
    question: str | None = Field(None, max_length=500)
    action: Literal["explain_move", "plan", "why_not_best"] | None = None
    level: Literal["beginner", "intermediate"] = "intermediate"

    @model_validator(mode="after")
    def _need_one(self):
        if not (self.question and self.question.strip()) and not self.action:
            raise ValueError("send a question or an action")
        return self


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/games/{game_id}/chat")
async def get_thread(game_id: str, ply: int | None = None, sid: str = Depends(session_id)):
    async with SessionLocal() as db:
        g = await get_game(db, game_id, sid)
        board, *_ = position_at(g.pgn, ply)
        rows = (await db.execute(select(ChatMessage).where(
            ChatMessage.game_id == g.id, ChatMessage.fen == board.epd()).order_by(ChatMessage.id))).scalars().all()
    return [{"role": r.role, "content": r.content} for r in rows]


@router.post("/chat")
async def chat(body: ChatIn, sid: str = Depends(session_id), em: EngineManager = Depends(get_engine)):
    t0 = time.monotonic()
    async with SessionLocal() as db:
        g = await get_game(db, body.game_id, sid)
        board, prev, last, _ = position_at(g.pgn, body.ply)
        epd = board.epd()
        rows = (await db.execute(
            select(ChatMessage).where(ChatMessage.game_id == g.id, ChatMessage.fen == epd)
            .order_by(ChatMessage.id.desc()).limit(settings.chat_history_turns))).scalars().all()
    history = [{"role": r.role, "content": r.content} for r in reversed(rows)]
    user_color = chess.WHITE if g.player_color == "white" else chess.BLACK

    if body.action:
        if body.action != "plan" and last is None:
            raise ApiError(422, "no_last_move", "There's no move to talk about yet")
        question = QUICK[body.action]
    else:
        question = body.question.strip()

    skip = {norm(prev.san(last))} if last is not None and prev is not None else set()
    whatif = extract_whatif(question, board, skip)
    # facts are computed BEFORE streaming starts, so engine-busy surfaces as a proper 429 JSON error
    facts, allowed, mood = await build_facts(em, board, prev, last, user_color, whatif)

    return StreamingResponse(
        _events(g.id, epd, question, facts, allowed, mood, history, body.level, t0),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _events(game_id, epd, question, facts, allowed, mood, history, level, t0):
    msgs = build_messages(facts, history, question, level)
    shown: list[str] = []
    attempts, fallback_reason, bad_moves, first_token_ms = 0, None, [], None

    try:
        if not llm_enabled():
            fallback_reason = "llm_disabled"
        else:
            raw_bad: str = ""
            for attempt in (1, 2):
                attempts = attempt
                m = msgs if attempt == 1 else msgs + [
                    {"role": "assistant", "content": raw_bad},
                    {"role": "user", "content": correction(bad_moves)}]
                shown, buf, raw, bad = [], "", "", []
                async with aclosing(stream_reply(m)) as gen:
                    async for tok in gen:
                        raw += tok
                        buf += tok
                        sents, buf = pop_sentences(buf)
                        for s in sents:
                            bad = validate(s, allowed)
                            if bad:
                                break
                            shown.append(s)
                            first_token_ms = first_token_ms or int((time.monotonic() - t0) * 1000)
                            yield sse("token", {"text": display(s)})
                        if bad:
                            break
                    if not bad and buf.strip():
                        bad = validate(buf, allowed)
                        if not bad:
                            shown.append(buf)
                            yield sse("token", {"text": display(buf)})
                if not bad:
                    break
                bad_moves = sorted(set(bad_moves) | set(bad)) if attempt == 2 else bad
                raw_bad = raw
                if shown:                                  # client already saw validated sentences: wipe them
                    yield sse("replace", {"reason": "invalid_move", "moves": bad})
                    shown = []
            else:
                fallback_reason = "validator"
    except (OpenAIError, TimeoutError):
        logger.exception("Groq chat request failed (model=%s, attempt=%d)", settings.groq_model, attempts)
        fallback_reason = "llm_error"

    if fallback_reason:
        if shown:
            yield sse("replace", {"reason": fallback_reason})
        text = fallback_text(facts, fallback_reason)
        shown = [text]
        yield sse("token", {"text": text})

    final = display("".join(shown)).strip()
    async with SessionLocal() as db:
        am = ChatMessage(game_id=game_id, fen=epd, role="assistant", content=final)
        db.add(ChatMessage(game_id=game_id, fen=epd, role="user", content=question))
        db.add(am)
        db.add(CoachLog(game_id=game_id, model=settings.groq_model or "none", attempts=attempts,
                        fallback=bool(fallback_reason), fallback_reason=fallback_reason,
                        bad_moves=bad_moves, first_token_ms=first_token_ms))
        await db.commit()
        mid = am.id
    yield sse("validated", {"ok": not fallback_reason, "attempts": attempts})
    yield sse("done", {"message_id": mid, "coach_mood": mood, "fallback": bool(fallback_reason),
                       "fallback_reason": fallback_reason, "attempts": attempts})