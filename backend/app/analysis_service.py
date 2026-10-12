import hashlib

import chess

from .db import SessionLocal
from .engine import NORMAL, EngineManager
from .models import AnalysisCache


async def analysis(em: EngineManager, board: chess.Board, depth: int = 14,
                   multipv: int = 3, priority: int = NORMAL) -> dict:
    depth, multipv = em.clamp(depth, multipv)
    if (hit := em.lookup(board, depth, multipv)) is not None:
        return hit
    key = hashlib.sha1(board.epd().encode()).hexdigest()
    async with SessionLocal() as db:
        row = await db.get(AnalysisCache, (key, depth, multipv))
    if row:
        em.store(board, depth, multipv, row.result_json)
        return row.result_json
    res = await em.analyse_pos(board, depth, multipv, priority)
    try:
        async with SessionLocal() as db:
            await db.merge(AnalysisCache(fen_hash=key, depth=depth, multipv=multipv, result_json=res))
            await db.commit()
    except Exception:
        pass            # a concurrent writer beat us to it; harmless
    return res