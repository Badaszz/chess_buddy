from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)  # for 30-day retention


class Game(Base):
    __tablename__ = "games"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    pgn: Mapped[str] = mapped_column(Text)
    player_color: Mapped[str] = mapped_column(String(5))
    strength: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="ongoing")
    winner: Mapped[str | None] = mapped_column(String(5), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"
    fen_hash: Mapped[str] = mapped_column(String(40), primary_key=True)
    depth: Mapped[int] = mapped_column(Integer, primary_key=True)
    multipv: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChatMessage(Base):          # used in Phase 3; created now so there's no migration later
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    fen: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CoachLog(Base):             # new table, so create_all adds it with no migration
    __tablename__ = "coach_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer)
    fallback: Mapped[bool] = mapped_column(Boolean)
    fallback_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bad_moves: Mapped[list] = mapped_column(JSON)
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)