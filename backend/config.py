"""Backend configuration via pydantic-settings.

database_url has no default on purpose — it must come from the
environment or backend/.env (see .env.example). Keeps credentials
out of the repo.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent / ".env", extra="ignore"
    )

    database_url: str
    session_ttl_hours: int = 48


settings = Settings()
