"""Runtime credential handling.

Passwords are prompted at runtime, cached in memory only, and never logged.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass, field

from .config import HostConfig


@dataclass
class RuntimeCredentials:
    """Secrets needed for one host connection."""

    ssh_password: str | None = None
    sudo_password: str | None = None


@dataclass
class CredentialProvider:
    """Secure prompt-and-cache provider keyed by environment and user."""

    _passwords: dict[tuple[str, str], str] = field(default_factory=dict)

    def for_host(self, host: HostConfig) -> RuntimeCredentials:
        """Return credentials for a host based on its auth model."""

        if host.auth.method == "key":
            return RuntimeCredentials()

        cache_key = (host.environment, host.ssh_user)
        password = self._passwords.get(cache_key)
        if password is None:
            prompt = f"SSH password for {host.ssh_user} ({host.environment}): "
            password = getpass.getpass(prompt)
            self._passwords[cache_key] = password

        sudo_password = password if host.auth.sudo_password == "same_as_ssh" else None
        return RuntimeCredentials(ssh_password=password, sudo_password=sudo_password)
