"""SSH stdin execution framework."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inventory import HostConfig


@dataclass(frozen=True)
class CommandResult:
    host: "HostConfig"
    command: list[str]
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None


class SSHRunner:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    def run_script(self, host: "HostConfig", script: str) -> CommandResult:
        ssh_command = self._build_ssh_command(host)
        normalized_script = _normalize_remote_script(script)
        remote_shell = "bash -s"
        if host.privilege_enabled and host.privilege_method == "sudo":
            remote_shell = "sudo -n bash -s"
        command = [*ssh_command, remote_shell]
        return self._run(command, host, normalized_script)

    def run_command(self, host: "HostConfig", remote_command: str) -> CommandResult:
        command = [*self._build_ssh_command(host), remote_command]
        return self._run(command, host, None)

    def _run(self, command: list[str], host: "HostConfig", script: str | None) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                input=script,
                text=True,
                capture_output=True,
                timeout=host.timeout_seconds,
                check=False,
            )
            return CommandResult(host, command, completed.stdout, completed.stderr, completed.returncode)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(host, command, _coerce_text(exc.stdout), _coerce_text(exc.stderr), 124, True, f"Timed out after {host.timeout_seconds} seconds")
        except OSError as exc:
            return CommandResult(host, command, "", "", 127, False, str(exc))

    @staticmethod
    def _build_ssh_command(host: "HostConfig") -> list[str]:
        destination = f"{host.user}@{host.address}"
        command = [
            "ssh",
            "-p",
            str(host.port),
            "-o",
            "ConnectTimeout=10",
            "-o",
            f"StrictHostKeyChecking={host.strict_host_key_checking}",
        ]
        if host.auth_method == "ssh_key" and host.private_key:
            command.extend(["-i", host.private_key, "-o", "BatchMode=yes"])
        if host.force_tty and host.privilege_enabled and host.privilege_method == "sudo":
            command.append("-tt")
        command.append(destination)
        return command


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _normalize_remote_script(script: str) -> str:
    normalized = script.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("#!"):
        shebang, _, rest = normalized.partition("\n")
        rest = _ensure_bash_header(rest)
        return f"{shebang}\n{rest}"
    return _ensure_bash_header(normalized)


def _ensure_bash_header(script: str) -> str:
    lines = script.splitlines()
    if lines[:2] == ["set -eu", "set -o pipefail"]:
        body = "\n".join(lines[2:])
        return f"set -eu\nset -o pipefail\n{body}\n" if body else "set -eu\nset -o pipefail\n"
    if lines[:1] == ["set -euo pipefail"]:
        body = "\n".join(lines[1:])
        return f"set -euo pipefail\n{body}\n" if body else "set -euo pipefail\n"
    return "set -eu\nset -o pipefail\n" + script.lstrip("\n")
