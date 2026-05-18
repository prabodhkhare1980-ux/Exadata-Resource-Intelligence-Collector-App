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
    """Result from executing a remote stdin-fed shell script."""

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
    """Run remote shell through SSH by streaming script content over stdin.

    This runner intentionally does not use SCP, does not create remote files, and does
    not install anything remotely. The only remote payload is shell content supplied to
    the SSH process via subprocess stdin.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    def run_script(self, host: "HostConfig", script: str) -> CommandResult:
        """Execute a shell script on a remote host using SSH stdin."""

        ssh_command = self._build_ssh_command(host)
        remote_shell = "sudo -n bash -s" if host.sudo else "bash -s"
        command = [*ssh_command, remote_shell]

        self.logger.info(
            "SSH execution settings: ssh_user=%s, address=%s, strict_host_key_checking=%s",
            host.user or "",
            host.address,
            host.strict_host_key_checking,
        )
        self.logger.debug("Running remote stdin command on %s: %s", host.name, command)
        try:
            completed = subprocess.run(
                command,
                input=script,
                text=True,
                capture_output=True,
                timeout=host.timeout_seconds,
                check=False,
            )
            return CommandResult(
                host=host,
                command=command,
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
            )
        except subprocess.TimeoutExpired as exc:
            self.logger.error(
                "Timed out after %s seconds while collecting from %s",
                host.timeout_seconds,
                host.name,
            )
            return CommandResult(
                host=host,
                command=command,
                stdout=_coerce_text(exc.stdout),
                stderr=_coerce_text(exc.stderr),
                returncode=124,
                timed_out=True,
                error=f"Timed out after {host.timeout_seconds} seconds",
            )
        except OSError as exc:
            self.logger.exception("Failed to start SSH for host %s", host.name)
            return CommandResult(
                host=host,
                command=command,
                stdout="",
                stderr="",
                returncode=127,
                error=str(exc),
            )

    @staticmethod
    def _build_ssh_command(host: "HostConfig") -> list[str]:
        destination = f"{host.user}@{host.address}" if host.user else host.address
        command = [
            "ssh",
            "-p",
            str(host.port),
            "-o",
            "BatchMode=no",
            "-o",
            "ConnectTimeout=10",
            "-o",
            f"StrictHostKeyChecking={host.strict_host_key_checking}",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive,publickey",
        ]
        for option in host.ssh_options:
            command.extend(["-o", option])
        command.append(destination)
        return command


def _coerce_text(value: str | bytes | None) -> str:
    """Normalize subprocess output to text."""

    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
