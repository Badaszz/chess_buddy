import asyncio
import uuid

import chess
import chess.pgn
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..analysis_service import analysis
from ..chess_utils import parse_fen
from ..config import settings
from ..db import get_db
from ..deps import get_engine, get_game, session_id
from ..engine import LOW, NORMAL, EngineManager
from ..errors import ApiError
from ..scoring import classify, move_accuracy, pov_wp

router = APIRouter(tags=["analysis"])
JOBS: dict[str, dict] = {}        # in-memory: lost on restart (fine for v1)
_tasks: set[asyncio.Task] = set()


class AnalyzeIn(BaseModel):
    fen: str
    depth: int = Field(12, ge=1, le=60)        # server clamps to the hard cap anyway
    multipv: int = Field(3, ge=1, le=10)


@router.post("/analyze")
async def analyze(body: AnalyzeIn, sid: str = Depends(session_id), em: EngineManager = Depends(get_engine)):
    board = parse_fen(body.fen)
    return await analysis(em, board, body.depth, body.multipv, NORMAL)


async def run_review(job_id: str, em: EngineManager, pgn: str):
    job = JOBS[job_id]
    try:
        import io
        game = chess.pgn.read_game(io.StringIO(pgn))
        b = game.board()
        positions, moves = [b.copy()], []
        for mv in game.mainline_moves():
            moves.append(mv)
            b.push(mv)
            positions.append(b.copy(stack=False))

        job.update(status="running", total=len(positions))
        evals = []
        for i, pos in enumerate(positions):
            evals.append(await analysis(em, pos, settings.review_depth, 1, LOW))
            job["progress"] = i + 1

        rows, acc = [], {"white": [], "black": []}
        for i, mv in enumerate(moves):
            pos, color = positions[i], positions[i].turn
            wb, wa = pov_wp(evals[i]["eval_cp"], color), pov_wp(evals[i + 1]["eval_cp"], color)
            drop, accuracy = max(0.0, wb - wa), move_accuracy(wb, wa)
            best_uci = evals[i]["best_uci"]
            rows.append({
                "ply": i + 1, "color": chess.COLOR_NAMES[color], "san": pos.san(mv), "uci": mv.uci(),
                "eval_cp": evals[i + 1]["eval_cp"], "mate_in": evals[i + 1]["mate_in"],
                "win_drop": round(drop, 1), "class": classify(drop), "accuracy": round(accuracy, 1),
                "best_uci": best_uci, "is_best": best_uci == mv.uci(),
                "best_san": pos.san(chess.Move.from_uci(best_uci)) if best_uci else None,
            })
            acc[chess.COLOR_NAMES[color]].append(accuracy)

        mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
        job.update(status="done", result={
            "moves": rows,
            "eval_graph": [e["eval_cp"] for e in evals],     # index i = position after i plies
            "best_uci_by_ply": [e["best_uci"] for e in evals],
            "accuracy": {"white": mean(acc["white"]), "black": mean(acc["black"])},
        })
    except Exception as e:
        job.update(status="error", error=str(e))


@router.post("/games/{game_id}/review", status_code=202)
async def start_review(game_id: str, sid: str = Depends(session_id),
                       db: AsyncSession = Depends(get_db), em: EngineManager = Depends(get_engine)):
    g = await get_game(db, game_id, sid)
    if " 1." not in g.pgn and "1." not in g.pgn:
        raise ApiError(422, "empty_game", "Play a few moves first")
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"sid": sid, "status": "queued", "progress": 0, "total": 0, "result": None, "error": None}
    t = asyncio.create_task(run_review(job_id, em, g.pgn))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, sid: str = Depends(session_id)):
    job = JOBS.get(job_id)
    if job is None or job["sid"] != sid:
        raise ApiError(404, "not_found", "Job not found")
    return {k: v for k, v in job.items() if k != "sid"}