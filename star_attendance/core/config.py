from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Type-Safe Centralized Configuration for Star ASN.
    Validates environment variables at start-up.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- TELEGRAM BOT CONFIGURATION ---
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_ADMIN_ID: int | None = None
    TELEGRAM_LOG_GROUP_ID: str | None = None
    MINI_APP_URL: str | None = None

    # --- SUPABASE DATABASE CONFIGURATION ---
    POSTGRES_URL: str
    MASTER_SECURITY_KEY: str

    # --- CLUSTER PERFORMANCE ---
    MASS_RETRY_MAX: int = 3
    MASS_RETRY_DELAY: int = 3
    SETTINGS_CACHE_TTL_SECONDS: int = 10
    USER_CACHE_TTL_SECONDS: int = 10
    IDEMPOTENCY_LOCK_TTL_SECONDS: int = 300

    # --- ENGINE SETTINGS ---
    OCR_ENGINE: str = "ddddocr"
    CAPTCHA_MODE: str = "adaptive"
    CAPTCHA_ATTEMPTS: int = 2
    CAPTCHA_MIN_CONF: float = 0.28
    ALERT_FAILURE_RATE_THRESHOLD: float = 0.35
    PORTAL_CIRCUIT_BREAKER_THRESHOLD: int = 5
    PORTAL_CIRCUIT_BREAKER_COOLDOWN_SECONDS: int = 90

    # --- API CONFIGURATION ---
    INTERNAL_API_URL: str = "http://127.0.0.1:8000"
    INTERNAL_API_TOKEN: str | None = None

    # --- BROWSER SETTINGS ---
    WAF_BROWSER_HEADLESS: bool = True
    WAF_BROWSER_MAX_CONCURRENCY: int = 1

    # --- LOGGING ---
    LOG_LEVEL: str = "INFO"
    LOG_BROADCAST_ENABLED: bool = True
    LOG_TELEGRAM_ENABLED: bool = True

    # --- BOT INTERFACE & BRANDING ---
    BOT_NAME: str = "STAR-ASN"
    BOT_EDITION: str = "ENTERPRISE PREMIUM"
    BOT_VERSION: str = "2.0"
    BOT_BANNER_PATH: str | None = "assets/banner.png"
    BOT_BROADCAST_DELAY: float = 0.05
    UPT_EXAMPLE_FALLBACK: str = "KANWIL_SUMUT, KANIM_MEDAN"

    @property
    def database_url(self) -> str:
        """Helper to ensure postgresql+asyncpg scheme for SQLAlchemy."""
        if self.POSTGRES_URL.startswith("postgresql://"):
            return self.POSTGRES_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.POSTGRES_URL

    @property
    def resolved_internal_api_token(self) -> str:
        """Fallback to the master key for backward-compatible internal auth."""
        return self.INTERNAL_API_TOKEN or self.MASTER_SECURITY_KEY


# Global instance
settings = Settings()  # type: ignore[call-arg]
