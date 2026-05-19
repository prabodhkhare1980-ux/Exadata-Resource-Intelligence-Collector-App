"""SSH/sudo preflight checks."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .auth import CredentialProvider
from .config import CollectionConfig, HostConfig
from .ssh import RemoteExecutionError, run_remote_script

LOGGER = logging.getLogger(__name__)


def run_preflight(config: CollectionConfig, credential_provider: CredentialProvider | None = None) -> list[dict[str, Any]]:
    credentials = credential_provider or CredentialProvider()
    rows: list[dict[str, Any]] = []
    for host in config.hosts:
        LOGGER.info(
            "preflight cluster=%s environment=%s host=%s address=%s ssh_user=%s",
            host.cluster,
            host.environment,
            host.name,
            host.address,
            host.ssh_user,
        )
        rows.append(_check_host(host, credentials))
    return rows


def _check_host(host: HostConfig, provider: CredentialProvider) -> dict[str, Any]:
    base = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "cluster": host.cluster,
        "environment": host.environment,
        "host": host.name,
        "address": host.address,
        "ssh_user": host.ssh_user,
    }
    try:
        runtime_credentials = provider.for_host(host)
        run_remote_script(host, "hostname\n", runtime_credentials)

        sudo_n_ok = True
        effective_user = ""
        if host.privilege.enabled and host.privilege.method == "sudo":
            try:
                run_remote_script(host, "sudo -n true\n", runtime_credentials)
                effective_user = run_remote_script(host, "whoami\n", runtime_credentials).strip()
            except (RemoteExecutionError, OSError, ValueError):
                sudo_n_ok = False

        passed = sudo_n_ok or not host.privilege.enabled
        return {**base, "status": "PASS" if passed else "FAIL", "ssh_ok": True, "sudo_ok": sudo_n_ok, "force_tty_used": host.privilege.force_tty, "effective_user": effective_user, "error": ""}
    except (RemoteExecutionError, OSError, ValueError) as exc:
        return {**base, "status": "FAIL", "ssh_ok": False, "sudo_ok": False, "force_tty_used": host.privilege.force_tty, "effective_user": "", "error": str(exc)}
