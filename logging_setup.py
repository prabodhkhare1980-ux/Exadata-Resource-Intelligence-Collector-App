"""Logging setup utilities."""

from __future__ import annotations

import logging
from pathlib import Path


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(logs_dir: Path, verbose: bool = False) -> None:
    """Configure console and application file logging."""

    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT))

    file_handler = logging.FileHandler(logs_dir / "collector.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root.addHandler(console)
    root.addHandler(file_handler)


def host_logger(logs_dir: Path, host_name: str) -> logging.Logger:
    """Create a per-host logger that writes to logs/<host>.log."""

    safe_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in host_name)
    logger = logging.getLogger(f"host.{safe_name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = True

    log_path = logs_dir / f"{safe_name}.log"
    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_path
        for handler in logger.handlers
    ):
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(file_handler)

    return logger
