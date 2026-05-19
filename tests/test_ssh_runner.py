from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from inventory import HostConfig
from ssh_runner import SSHRunner


def _host(force_tty: bool, environment: str) -> HostConfig:
    return HostConfig(
        name="h1",
        address="h1.example.com",
        user="srcordma",
        environment=environment,
        auth_method="ssh_key",
        private_key=".secrets/ssh/srcordma_id_rsa",
        strict_host_key_checking="accept-new",
        port=22,
        privilege_enabled=True,
        privilege_method="sudo",
        sudo_password_mode="none",
        force_tty=force_tty,
        timeout_seconds=60,
    )


def test_build_ssh_command_uses_force_tty_true() -> None:
    command = SSHRunner._build_ssh_command(_host(True, "onprem"), allocate_tty=True)
    assert "-tt" in command
    assert "-T" not in command


def test_build_ssh_command_uses_force_tty_false() -> None:
    command = SSHRunner._build_ssh_command(_host(False, "oci"), allocate_tty=False)
    assert "-T" in command
    assert "-tt" not in command
