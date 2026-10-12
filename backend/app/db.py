from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import settings
from .models import Base


def _prepare(url: str) -> tuple[str, dict]:
    """Render/Neon hand out postgres:// URLs; asyncpg wants its own scheme and ssl arg."""
    args: dict = {}
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        parts = urlsplit(url)
        q = dict(parse_qsl(parts.query))
        sslmode = q.pop("sslmode", None)
        q.pop("channel_binding", None)
        if sslmode and sslmode != "disable":
            args["ssl"] = sslmode
        url = urlunsplit(parts._replace(query=urlencode(q)))
    return url, args


_url, _args = _prepare(settings.database_url)
engine = create_async_engine(_url, connect_args=_args, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with SessionLocal() as s:
        yield s