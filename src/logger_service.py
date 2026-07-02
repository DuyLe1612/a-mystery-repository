"""Structured logging service for OptiBot Clone."""

import logging
import sys
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional


class LoggerService:
    """Singleton logger service with console and file handlers."""

    _instance: Optional["LoggerService"] = None

    def __init__(self, name: str = "optibot", env: str = "development"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        self.logger.handlers = []
        self.logger_name = name
        self.env = env

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Gunicorn integration
        if "gunicorn" in sys.modules:
            gunicorn_logger = logging.getLogger("gunicorn.error")
            self.logger.handlers = gunicorn_logger.handlers
            self.logger.setLevel(gunicorn_logger.level)
            for handler in self.logger.handlers:
                handler.setFormatter(formatter)
        else:
            # Console handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            console_handler.setLevel(logging.DEBUG)
            self.logger.addHandler(console_handler)

        self.logger.propagate = False

    @classmethod
    def get_instance(cls, name: str = "optibot", env: str = "development") -> logging.Logger:
        """Get or create singleton logger instance."""
        if cls._instance is None:
            cls._instance = cls(name, env)
        return cls._instance.logger

    def add_file_handler(self, log_file: Path, max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5):
        """Add file handler with rotation."""
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)


def get_logger(name: str = "optibot", env: str = "development") -> logging.Logger:
    """Convenience function to get logger instance."""
    return LoggerService.get_instance(name, env)


def setup_daily_logging(log_dir: str = "./logs") -> logging.Logger:
    """Setup logging with daily rotating files."""
    logger = get_logger()

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    current_date = datetime.now().strftime("%Y-%m-%d")
    log_file = log_path / f"optibot-{current_date}.log"

    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s: %(message)s")
    )
    logger.addHandler(file_handler)

    return logger
