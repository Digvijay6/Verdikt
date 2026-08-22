"""Environment configuration, shared by the API and the voice worker."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_service_key: str  # server-side only, never sent to the browser
    # Legacy HS256 shared secret. Optional: new projects sign with ES256 and
    # are verified against the JWKS endpoint instead. Only set this if the
    # project still issues HS256 tokens. See api/deps.py.
    supabase_jwt_secret: str | None = None

    # Gemini
    gemini_api_key: str

    # LiveKit
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # Email
    resend_api_key: str
    from_email: str = "interviews@verdikt.app"

    # Invite links
    app_base_url: str = "http://localhost:5173"
    invite_ttl_hours: int = 168  # 7 days
    interview_rejoin_window_minutes: int = 60

    # CORS
    frontend_origin: str = "http://localhost:5173"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Resolved on first use, not at import.

    Importing a module must never require a fully populated .env — otherwise
    tests, tooling, and `--help` all need production secrets to exist.
    """
    return Settings()  # type: ignore[call-arg]
