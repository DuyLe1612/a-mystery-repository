"""Configuration module for OptiBot Clone.

Loads environment variables from .env file and provides configuration settings.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # OpenAI Configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Scraping Configuration
    COUNT_ARTICLES: int = int(os.getenv("COUNT_ARTICLES", "30"))
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "./articles")

    # Flask Configuration
    PORT: int = int(os.getenv("PORT", "8080"))
    FLASK_ENV: str = os.getenv("FLASK_ENV", "production")

    # Schedule Configuration (UTC)
    SCHEDULE_HOUR: int = int(os.getenv("SCHEDULE_HOUR", "0"))
    SCHEDULE_MINUTE: int = int(os.getenv("SCHEDULE_MINUTE", "0"))

    # Logging Configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")


class ScheduleConfig:
    """Flask-APScheduler configuration."""
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = "UTC"


SCHEDULE_CONFIG = ScheduleConfig
