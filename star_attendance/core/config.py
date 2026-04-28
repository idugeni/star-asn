from functools import cache

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
    INTERNAL_API_URL: str = "http://127.0.0.1:11800"
    INTERNAL_API_TOKEN: str | None = None

    # --- BROWSER SETTINGS ---
    WAF_BROWSER_HEADLESS: bool = True
    WAF_BROWSER_MAX_CONCURRENCY: int = 1

    # --- PROXY SETTINGS (Bright Data / Custom) ---
    PROXY_HOST: str | None = None  # e.g. brd.superproxy.io
    PROXY_PORT: int = 33335
    PROXY_USERNAME: str | None = None  # e.g. brd-customer-hl_4d392e9b-zone-residential_proxy-country-id
    PROXY_PASSWORD: str | None = None
    PROXY_ENABLED: bool = False  # Master switch — set to true to activate proxy

    # --- GEOCODING ---
    GOAPI_KEY: str | None = None  # GoAPI.io Places API key (free tier available)

    # --- LOGGING ---
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "console"  # "console" or "json" for Loki/Grafana
    LOG_BROADCAST_ENABLED: bool = True
    LOG_TELEGRAM_ENABLED: bool = True

    # --- BOT WEBHOOK ---
    BOT_WEBHOOK_URL: str | None = None  # e.g. https://star-asn.example.com/bot/webhook
    BOT_WEBHOOK_SECRET: str | None = None  # Optional secret for webhook verification
    BOT_WEBHOOK_LISTEN_HOST: str = "0.0.0.0"
    BOT_WEBHOOK_LISTEN_PORT: int = 11801

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
    def resolved_proxy_url(self) -> str | None:
        """Construct proxy URL from Bright Data or custom proxy settings.

        Returns http://user:pass@host:port format, or None if proxy is disabled.
        """
        if not self.PROXY_ENABLED:
            return None
        if not self.PROXY_HOST:
            return None
        if self.PROXY_USERNAME and self.PROXY_PASSWORD:
            return f"http://{self.PROXY_USERNAME}:{self.PROXY_PASSWORD}@{self.PROXY_HOST}:{self.PROXY_PORT}"
        return f"http://{self.PROXY_HOST}:{self.PROXY_PORT}"

    @property
    def resolved_internal_api_token(self) -> str:
        """Fallback to the master key for backward-compatible internal auth."""
        return self.INTERNAL_API_TOKEN or self.MASTER_SECURITY_KEY


@cache
def get_settings() -> Settings:
    """Get cached Settings instance.

    Uses functools.cache to ensure Settings is only instantiated once
    and reused across the application.

    Returns:
        Settings instance with values loaded from environment
    """
    # Pydantic Settings reads from environment variables
    return Settings()  # type: ignore[call-arg]


# Global instance for backward compatibility
settings: Settings = get_settings()

# --- SHARED IDENTITY CONSTANTS ---
# Used for bypassing WAF/SSO detection with consistent browser fingerprinting
MASTER_IDENTITY_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MASTER_IDENTITY_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1"
}
