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
    def __init__(self, logger: logging.Logger | None = None, debug_ssh: bool = False) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.debug_ssh = debug_ssh

    def run_script(self, host: "HostConfig", script: str) -> CommandResult:
        ssh_command = self._build_ssh_command(host, allocate_tty=False)
        normalized_script = _normalize_remote_script(script)
        remote_shell = "bash -s"
        if host.privilege_enabled and host.privilege_method == "sudo":
            remote_shell = "sudo -n bash -s"
        command = [*ssh_command, remote_shell]
        return self._run(command, host, normalized_script)

    def run_command(self, host: "HostConfig", remote_command: str) -> CommandResult:
        command = [*self._build_ssh_command(host, allocate_tty=host.force_tty), remote_command]
        return self._run(command, host, None)

    def _run(self, command: list[str], host: "HostConfig", script: str | None) -> CommandResult:
        if self.debug_ssh:
            self.logger.debug("SSH command: %s", _sanitize_command(command))

        try:
            completed = subprocess.run(
                command,
                input=script,
                text=True,
                capture_output=True,
                timeout=host.timeout_seconds,
                check=False,
            )
            if self.debug_ssh:
                self.logger.debug("SSH stdout (first 500 chars): %s", _clip(completed.stdout))
                self.logger.debug("SSH stderr (first 500 chars): %s", _clip(completed.stderr))
            return CommandResult(host, command, completed.stdout, completed.stderr, completed.returncode)
        except subprocess.TimeoutExpired as exc:
            stdout = _coerce_text(exc.stdout)
            stderr = _coerce_text(exc.stderr)
            if self.debug_ssh:
                self.logger.debug("SSH stdout before timeout (first 500 chars): %s", _clip(stdout))
                self.logger.debug("SSH stderr before timeout (first 500 chars): %s", _clip(stderr))
            return CommandResult(host, command, stdout, stderr, 124, True, f"Timed out after {host.timeout_seconds} seconds")
        except OSError as exc:
            return CommandResult(host, command, "", "", 127, False, str(exc))

    @staticmethod
    def _build_ssh_command(host: "HostConfig", allocate_tty: bool = False) -> list[str]:
        destination = f"{host.user}@{host.address}"
        command = [
            "ssh",
            "-p",
            str(host.port),
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            "-o",
            f"StrictHostKeyChecking={host.strict_host_key_checking}",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=2",
        ]
        if host.auth_method == "ssh_key" and host.private_key:
            command.extend(["-i", host.private_key])
        command.append("-tt" if allocate_tty else "-T")
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
        rest = _ensure_exit_zero(_ensure_bash_header(rest))
        return f"{shebang}\n{rest}"
    return _ensure_exit_zero(_ensure_bash_header(normalized))


def _ensure_bash_header(script: str) -> str:
    lines = script.splitlines()
    if lines[:2] == ["set -eu", "set -o pipefail"]:
        body = "\n".join(lines[2:])
        return f"set -eu\nset -o pipefail\n{body}\n" if body else "set -eu\nset -o pipefail\n"
    if lines[:1] == ["set -euo pipefail"]:
        body = "\n".join(lines[1:])
        return f"set -euo pipefail\n{body}\n" if body else "set -euo pipefail\n"
    return "set -eu\nset -o pipefail\n" + script.lstrip("\n")


def _sanitize_command(command: list[str]) -> str:
    sanitized: list[str] = []
    skip_next = False
    for idx, part in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if part == "-i" and idx + 1 < len(command):
            sanitized.extend(["-i", "***REDACTED***"])
            skip_next = True
            continue
        sanitized.append(part)
    return " ".join(sanitized)


def _clip(text: str) -> str:
    return text[:500]


def _ensure_exit_zero(script: str) -> str:
    stripped = script.rstrip()
    if stripped.endswith("exit 0"):
        return stripped + "\n"
    return stripped + "\nexit 0\n"
