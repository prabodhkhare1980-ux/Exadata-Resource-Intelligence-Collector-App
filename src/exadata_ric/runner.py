"""Collection orchestration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .auth import CredentialProvider
from .collectors import CollectionResult, Collector, PHASE1_COLLECTORS
from .config import CollectionConfig, HostConfig
from .ssh import RemoteExecutionError, run_remote_script

LOGGER = logging.getLogger(__name__)


def collect(config: CollectionConfig, credential_provider: CredentialProvider | None = None) -> tuple[list[CollectionResult], list[dict[str, Any]]]:
    """Collect all Phase 1 data with per-host error handling."""

    credentials = credential_provider or CredentialProvider()
    all_results: list[CollectionResult] = []
    errors: list[dict[str, Any]] = []
    script = build_phase1_script(PHASE1_COLLECTORS)

    for host in config.hosts:
        LOGGER.info("collecting host=%s cluster=%s environment=%s user=%s", host.name, host.cluster, host.environment, host.ssh_user)
        try:
            runtime_credentials = credentials.for_host(host)
            output = run_remote_script(host, script, runtime_credentials)
            sections = parse_sections(output)
            for collector in PHASE1_COLLECTORS:
                all_results.append(collector.parse(host, sections))
        except (RemoteExecutionError, OSError, ValueError) as exc:
            LOGGER.error("collection failed for host=%s cluster=%s: %s", host.name, host.cluster, exc)
            errors.append(_error_row(host, exc))
    return all_results, errors


def build_phase1_script(collectors: tuple[Collector, ...]) -> str:
    """Build one streamed remote script for all Phase 1 collectors."""

    body = ["set +e", "export LC_ALL=C"]
    body.extend(collector.shell() for collector in collectors)
    return "\n".join(body) + "\n"


def parse_sections(output: str) -> dict[str, list[list[str]]]:
    """Parse tab-delimited SECTION/END output from the remote shell."""

    sections: dict[str, list[list[str]]] = {}
    current: str | None = None
    for raw_line in output.splitlines():
        parts = raw_line.split("\t")
        if len(parts) >= 2 and parts[0] == "SECTION":
            current = parts[1]
            sections.setdefault(current, [])
            continue
        if len(parts) >= 2 and parts[0] == "END":
            current = None
            continue
        if current:
            sections.setdefault(current, []).append(parts)
    return sections


def _error_row(host: HostConfig, exc: BaseException) -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "environment": host.environment,
        "cluster": host.cluster,
        "host": host.name,
        "address": host.address,
        "ssh_user": host.ssh_user,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }
