from datetime import datetime, timezone

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .engine import EngineManager
from .errors import ApiError
from .models import Game, SessionRow


async def session_id(x_session_id: str = Header(..., min_length=8, max_length=64,
                                                pattern=r"^[A-Za-z0-9_-]+$")) -> str:
    return x_session_id


def get_engine(request: Request) -> EngineManager:
    return request.app.state.engine


async def get_game(db: AsyncSession, game_id: str, sid: str) -> Game:
    g = await db.get(Game, game_id)
    if g is None or g.session_id != sid:
        raise ApiError(404, "not_found", "Game not found")
    return g


async def touch_session(db: AsyncSession, sid: str):
    await db.merge(SessionRow(id=sid, last_seen_at=datetime.now(timezone.utc)))