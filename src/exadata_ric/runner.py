"""Collection orchestration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .auth import CredentialProvider
from .collectors import CollectionResult, Collector, PHASE1_COLLECTORS
from .config import CollectionConfig, HostConfig
from .ssh import RemoteExecutionError, run_remote_script
from .utils.output_cleaner import clean_output

LOGGER = logging.getLogger(__name__)


def collect(config: CollectionConfig, credential_provider: CredentialProvider | None = None) -> tuple[list[CollectionResult], list[dict[str, Any]]]:
    """Collect all Phase 1 data with per-host error handling."""

    credentials = credential_provider or CredentialProvider()
    all_results: list[CollectionResult] = []
    errors: list[dict[str, Any]] = []
    script = build_phase1_script(PHASE1_COLLECTORS, config)

    for host in config.hosts:
        LOGGER.info("collecting cluster=%s environment=%s host=%s address=%s ssh_user=%s", host.cluster, host.environment, host.name, host.address, host.ssh_user)
        try:
            runtime_credentials = credentials.for_host(host)
            output = run_remote_script(host, script, runtime_credentials)
            sections = parse_sections(clean_output(output))
            for collector in PHASE1_COLLECTORS:
                try:
                    if collector.name == "asm_diskgroups":
                        LOGGER.info("Starting ASM diskgroup collection for %s", host.name)
                    parsed = collector.parse(host, sections)
                    all_results.append(parsed)
                    if collector.name == "asm_diskgroups":
                        status = _asm_status(parsed.rows)
                        if status == "success":
                            LOGGER.info("Completed ASM diskgroup collection for %s", host.name)
                        else:
                            LOGGER.warning("ASM collection skipped/failed for %s", host.name)
                except Exception as exc:  # noqa: BLE001
                    if collector.name == "asm_diskgroups" and not config.asm_fail_host_on_error:
                        LOGGER.warning("ASM collection skipped/failed for %s", host.name)
                        all_results.append(CollectionResult("asm_diskgroups", [{"cluster": host.cluster, "host": host.name, "address": host.address, "asm_collection_status": "failed", "warning_level": "ERROR", "error": str(exc)}]))
                        continue
                    raise
        except (RemoteExecutionError, OSError, ValueError) as exc:
            LOGGER.error("collection failed for host=%s cluster=%s: %s", host.name, host.cluster, exc)
            errors.append(_error_row(host, exc))
    return all_results, errors


def build_phase1_script(collectors: tuple[Collector, ...], config: CollectionConfig) -> str:
    """Build one streamed remote script for all Phase 1 collectors."""

    body = [
        "set +e",
        "export TERM=dumb",
        "export LANG=C",
        "export LC_ALL=C",
        "unset PROMPT_COMMAND",
        "PS1=''",
        "stty -echo 2>/dev/null || true",
        f"export ASM_ENABLED={'true' if config.asm_enabled else 'false'}",
        f"export ASM_TIMEOUT_SECONDS={config.asm_timeout_seconds}",
    ]
    body.extend(collector.shell() for collector in collectors)
    return "\n".join(body) + "\n"


def parse_sections(output: str) -> dict[str, list[list[str]]]:
    """Parse marker-delimited section output from the remote shell."""

    sections: dict[str, list[list[str]]] = {}
    current: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("===BEGIN_SECTION:") and line.endswith("==="):
            current = line[len("===BEGIN_SECTION:") : -3]
            sections.setdefault(current, [])
            continue
        if line.startswith("===END_SECTION:") and line.endswith("==="):
            current = None
            continue
        if current:
            parts = raw_line.split("\t")
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


def _asm_status(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        status = str(row.get("asm_collection_status", "")).strip().lower()
        if status:
            return status
    return "failed"
