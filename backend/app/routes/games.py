import asyncio
import random
import uuid
from typing import Literal

import chess
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..chess_utils import board_from_pgn, pgn_from_board, san_list, status_of
from ..config import settings
from ..db import get_db
from ..deps import get_engine, get_game, session_id, touch_session
from ..engine import HIGH, LOW, EngineManager
from ..errors import ApiError
from ..models import Game
from ..scoring import classify, pick_mood, pov_wp

router = APIRouter(prefix="/games", tags=["games"])
_bg: set[asyncio.Task] = set()


class CreateGame(BaseModel):
    color: Literal["white", "black", "random"] = "white"
    strength: Literal["beginner", "casual", "club", "advanced", "max"] = "casual"


class MoveIn(BaseModel):
    uci: str = Field(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")


def user_color(g: Game) -> chess.Color:
    return chess.WHITE if g.player_color == "white" else chess.BLACK


def current_status(g: Game, board: chess.Board) -> dict:
    if g.status == "resigned":
        return {"state": "resigned", "winner": g.winner, "reason": "resignation"}
    return status_of(board)


def payload(g: Game, board: chess.Board, **extra) -> dict:
    return {"game_id": g.id, "fen": board.fen(), "player_color": g.player_color,
            "strength": g.strength, "status": current_status(g, board),
            "moves": san_list(board), "pgn": g.pgn, **extra}


def save_board(g: Game, board: chess.Board):
    st = status_of(board)
    g.pgn = pgn_from_board(board, g.player_color)
    g.status, g.winner = st["state"], st["winner"]


async def _warm(em: EngineManager, board: chess.Board):
    """Pre-compute the 'before' eval for the player's next move, at idle priority."""
    try:
        await em.analyse_pos(board, settings.mood_depth, 1, LOW)
    except Exception:
        pass


@router.post("")
async def create_game(body: CreateGame, sid: str = Depends(session_id),
                      db: AsyncSession = Depends(get_db), em: EngineManager = Depends(get_engine)):
    await touch_session(db, sid)
    color = random.choice(["white", "black"]) if body.color == "random" else body.color
    board, engine_move = chess.Board(), None
    if color == "black":                                  # engine opens
        mv = await em.play(board, body.strength)
        engine_move = {"san": board.san(mv), "uci": mv.uci()}
        board.push(mv)
    g = Game(id=uuid.uuid4().hex, session_id=sid, player_color=color, strength=body.strength,
             pgn=pgn_from_board(board, color), status="ongoing")
    db.add(g)
    await db.commit()
    return payload(g, board, engine_move=engine_move)


@router.get("/{game_id}")
async def load_game(game_id: str, sid: str = Depends(session_id), db: AsyncSession = Depends(get_db)):
    g = await get_game(db, game_id, sid)
    return payload(g, board_from_pgn(g.pgn))


@router.post("/{game_id}/move")
async def play_move(game_id: str, body: MoveIn, sid: str = Depends(session_id),
                    db: AsyncSession = Depends(get_db), em: EngineManager = Depends(get_engine)):
    g = await get_game(db, game_id, sid)
    if g.status != "ongoing":
        raise ApiError(409, "game_over", "This game is already over")
    board, uc = board_from_pgn(g.pgn), user_color(g)
    if board.turn != uc:
        raise ApiError(409, "not_your_turn", "It's not your turn")
    move = chess.Move.from_uci(body.uci)
    if move not in board.legal_moves:
        raise ApiError(422, "illegal_move", "Illegal move")

    # --- mood inputs: eval before/after the player's move (full strength, shallow) ---
    before = await em.analyse_pos(board, settings.mood_depth, 1, HIGH)   # usually a cache hit (_warm)
    user_san = board.san(move)
    board.push(move)
    after = await em.analyse_pos(board, settings.mood_depth, 1, HIGH)    # terminal positions skip the engine
    wp_b, wp_a = pov_wp(before["eval_cp"], uc), pov_wp(after["eval_cp"], uc)
    drop = max(0.0, wp_b - wp_a)
    eval_sign = 1 if uc == chess.WHITE else -1
    gain_cp = (after["eval_cp"] - before["eval_cp"]) * eval_sign
    mood = pick_mood(drop, gain_cp, board.is_checkmate())
    user_move = {"san": user_san, "classification": classify(drop), "win_drop": round(drop, 1)}

    # --- engine reply ---
    engine_move = None
    if status_of(board)["state"] == "ongoing":
        mv = await em.play(board, g.strength)
        engine_move = {"san": board.san(mv), "uci": mv.uci()}
        board.push(mv)
        if status_of(board)["state"] == "ongoing":
            t = asyncio.create_task(_warm(em, board.copy()))
            _bg.add(t)
            t.add_done_callback(_bg.discard)

    save_board(g, board)
    await touch_session(db, sid)
    await db.commit()
    return payload(g, board, user_move=user_move, engine_move=engine_move, coach_mood=mood)


@router.post("/{game_id}/resign")
async def resign(game_id: str, sid: str = Depends(session_id), db: AsyncSession = Depends(get_db)):
    g = await get_game(db, game_id, sid)
    if g.status != "ongoing":
        raise ApiError(409, "game_over", "This game is already over")
    board = board_from_pgn(g.pgn)
    g.status = "resigned"
    g.winner = "black" if g.player_color == "white" else "white"
    g.pgn = pgn_from_board(board, g.player_color, result="0-1" if g.winner == "black" else "1-0")
    await db.commit()
    return payload(g, board)


@router.post("/{game_id}/takeback")
async def takeback(game_id: str, sid: str = Depends(session_id), db: AsyncSession = Depends(get_db)):
    g = await get_game(db, game_id, sid)
    if g.status == "resigned":
        raise ApiError(409, "game_over", "Can't take back a resigned game")
    board = board_from_pgn(g.pgn)
    # engine just moved -> undo both plies; game ended on the player's move -> undo one
    n = 2 if board.turn == user_color(g) else 1
    if len(board.move_stack) < n:
        raise ApiError(409, "nothing_to_take_back", "Nothing to take back yet")
    for _ in range(n):
        board.pop()
    save_board(g, board)
    await db.commit()
    return payload(g, board)