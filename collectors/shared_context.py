"""Shared per-host execution context with command result caching."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ssh_runner import CommandResult, SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig


@dataclass(frozen=True)
class CachedCommand:
    key: str
    command: str


class SharedHostContext:
    """Thread-safe host-scoped command cache for a single run."""

    def __init__(self, runner: SSHRunner, logger: logging.Logger | None = None) -> None:
        self._runner = runner
        self._logger = logger or logging.getLogger(__name__)
        self._cache: dict[tuple[str, str], CommandResult] = {}
        self._lock = threading.Lock()

    def run_cached(self, host: "HostConfig", key: str, command: str) -> CommandResult:
        host_key = f"{host.environment}/{host.name}@{host.address}"
        cache_key = (host_key, key)
        with self._lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            self._logger.debug("cache hit host=%s key=%s", host_key, key)
            return cached

        self._logger.debug("cache miss host=%s key=%s", host_key, key)
        result = self._runner.run_command(host, command)
        with self._lock:
            existing = self._cache.get(cache_key)
            if existing is not None:
                return existing
            self._cache[cache_key] = result
        return result
