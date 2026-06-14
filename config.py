import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Settings:
    """Application settings loaded from environment variables."""

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    QUALIFICATION_MODEL: str = os.getenv("QUALIFICATION_MODEL", "claude-sonnet-4-6")
    EMAIL_MODEL: str = os.getenv("EMAIL_MODEL", "claude-sonnet-4-6")
    DB_PATH: str = os.getenv("DB_PATH", "amorce.db")
    MAX_CONCURRENT_SCRAPES: int = int(os.getenv("MAX_CONCURRENT_SCRAPES", "3"))
    SCRAPE_TIMEOUT: int = int(os.getenv("SCRAPE_TIMEOUT", "20"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
