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
        sudo_pw_ok = None
        if host.auth.sudo:
            try:
                run_remote_script(host, "sudo -n true\n", runtime_credentials)
            except (RemoteExecutionError, OSError, ValueError):
                sudo_n_ok = False
                try:
                    run_remote_script(host, "true\n", runtime_credentials)
                    sudo_pw_ok = True
                except (RemoteExecutionError, OSError, ValueError):
                    sudo_pw_ok = False

        passed = sudo_n_ok or sudo_pw_ok is True or not host.auth.sudo
        return {**base, "status": "PASS" if passed else "FAIL", "ssh_login": True, "hostname_command": True, "sudo_n_true": sudo_n_ok, "sudo_with_password": sudo_pw_ok, "error": ""}
    except (RemoteExecutionError, OSError, ValueError) as exc:
        return {**base, "status": "FAIL", "ssh_login": False, "hostname_command": False, "sudo_n_true": False, "sudo_with_password": False, "error": str(exc)}
