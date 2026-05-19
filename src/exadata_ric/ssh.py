"""SSH execution helpers that stream scripts over stdin."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .auth import RuntimeCredentials
from .config import HostConfig


class RemoteExecutionError(RuntimeError):
    """Raised when a remote command fails."""


def run_remote_script(host: HostConfig, script: str, credentials: RuntimeCredentials) -> str:
    """Run a shell script remotely by streaming it to SSH stdin.

    No files are copied to or created on the remote server. When password SSH is
    used, OpenSSH receives the password through an SSH_ASKPASS helper reading an
    inherited local file descriptor, avoiding passwords in command arguments or
    logs. Sudo receives the password over the already-encrypted SSH stdin before
    the streamed script body.
    """

    command = _ssh_command(host)
    if host.auth.sudo:
        remote = "sudo -n bash -s"
        stdin_text = script
    else:
        remote = "/bin/sh -s"
        stdin_text = script
    command.append(remote)

    env = os.environ.copy()
    pass_fds: tuple[int, ...] = ()
    askpass_path: Path | None = None
    password_pipe: tuple[int, int] | None = None

    try:
        if host.auth.method == "password":
            if not credentials.ssh_password:
                raise RemoteExecutionError("password authentication selected but no password was provided")
            askpass_path, password_pipe = _prepare_askpass(credentials.ssh_password)
            read_fd, write_fd = password_pipe
            os.close(write_fd)
            password_pipe = (read_fd, -1)
            env.update(
                {
                    "SSH_ASKPASS": str(askpass_path),
                    "SSH_ASKPASS_REQUIRE": "force",
                    "DISPLAY": env.get("DISPLAY", "localhost:0"),
                    "EXADATA_RIC_ASKPASS_FD": str(read_fd),
                }
            )
            pass_fds = (read_fd,)

        completed = subprocess.run(
            command,
            input=stdin_text,
            text=True,
            capture_output=True,
            timeout=host.timeout_seconds,
            env=env,
            pass_fds=pass_fds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RemoteExecutionError(f"timed out after {host.timeout_seconds} seconds") from exc
    finally:
        if password_pipe:
            for fd in password_pipe:
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        if askpass_path:
            try:
                askpass_path.unlink()
                askpass_path.parent.rmdir()
            except OSError:
                pass

    if completed.returncode != 0:
        stderr = _redact(
            completed.stderr.strip(),
            credentials.ssh_password,
            credentials.sudo_password,
        )
        message = f"ssh exited {completed.returncode}: {stderr}"
        if "Permission denied" in stderr:
            message += (
                f". Authentication failed for {host.ssh_user}@{host.address}. "
                f"Try manually: ssh {host.ssh_user}@{host.address} hostname"
            )
        if "Host key verification failed" in stderr:
            message += (
                f". Host key verification failed for {host.ssh_user}@{host.address}. "
                f"Try manually: ssh {host.ssh_user}@{host.address} hostname and type yes once to trust the key"
            )
        raise RemoteExecutionError(message)
    return completed.stdout


def _ssh_command(host: HostConfig) -> list[str]:
    command = [
        "ssh",
        "-T",
        "-p",
        str(host.port),
        "-o",
        "BatchMode=no",
        "-o",
        f"ConnectTimeout={host.timeout_seconds}",
        "-o",
        f"StrictHostKeyChecking={host.strict_host_key_checking}",
    ]
    if host.auth.method == "password":
        command.extend(["-o", "PreferredAuthentications=password,keyboard-interactive"])
    if host.auth.method == "key" and host.auth.key_file:
        command.extend(["-i", host.auth.key_file, "-o", "BatchMode=yes"])
    command.append(f"{host.ssh_user}@{host.address}")
    return command


def _prepare_askpass(password: str) -> tuple[Path, tuple[int, int]]:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, password.encode("utf-8") + b"\n")
    temp_dir = Path(tempfile.mkdtemp(prefix="exadata-ric-askpass-"))
    askpass = temp_dir / "askpass.py"
    askpass.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "fd = int(os.environ['EXADATA_RIC_ASKPASS_FD'])\n"
        "data = os.read(fd, 1048576)\n"
        "print(data.decode('utf-8').rstrip('\\n'))\n",
        encoding="utf-8",
    )
    askpass.chmod(0o700)
    return askpass, (read_fd, write_fd)


def _redact(text: str, *secrets: str | None) -> str:
    """Remove runtime secrets from text before including it in exceptions."""

    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted
