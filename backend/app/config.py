from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    stockfish_path: str = "/usr/games/stockfish"
    engine_count: int = 1          # = CPUs you pay for
    hash_mb: int = 16              # 64 on Standard
    max_queue: int = 12            # pending non-review jobs before 429

    database_url: str = "sqlite+aiosqlite:///./chessbuddy.db"
    allowed_origins: str = "http://localhost:3000"
    allowed_origin_regex: str | None = None   # e.g. https://chess-buddy-.*\.vercel\.app

    play_movetime_cap: float = 1.0
    analysis_depth_cap: int = 18
    multipv_cap: int = 3
    review_depth: int = 14
    mood_depth: int = 10

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()