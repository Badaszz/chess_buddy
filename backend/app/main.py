from contextlib import asynccontextmanager

import chess.engine
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import init_db
from .engine import EngineBusy, EngineManager
from .errors import ApiError
from .routes import analysis, games, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    em = EngineManager()
    await em.start()
    app.state.engine = em
    yield
    await em.stop()


app = FastAPI(title="Chess Buddy API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_origin_regex=settings.allowed_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)
app.include_router(games.router)
app.include_router(analysis.router)
app.include_router(chat.router)


def _err(status: int, code: str, message: str, headers: dict | None = None):
    return JSONResponse(status_code=status, content={"code": code, "message": message}, headers=headers)


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError):
    return _err(e.status, e.code, e.message, e.headers)


@app.exception_handler(EngineBusy)
async def _busy(_: Request, e: EngineBusy):
    return _err(429, "engine_busy", "The engine is busy, try again in a moment", {"Retry-After": "2"})


@app.exception_handler(chess.engine.EngineError)
async def _engine_down(_: Request, e: Exception):
    return _err(503, "engine_unavailable", "The engine is restarting, try again shortly")


@app.get("/health")
async def health(request: Request):
    ready = request.app.state.engine.ready
    return JSONResponse(status_code=200 if ready else 503, content={"ok": bool(ready), "engines": ready})