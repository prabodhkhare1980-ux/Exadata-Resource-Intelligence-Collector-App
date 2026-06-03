from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from inventory import HostConfig
from ssh_runner import SSHRunner


class _FakeStdin:
    closed = True


class _FakePopen:
    def __init__(self, command, **kwargs):  # noqa: ANN001
        self.command = command
        self.kwargs = kwargs
        self.stdin = _FakeStdin() if kwargs.get("stdin") is not None else None
        self.returncode = 0
        _FakePopen.captured["command"] = command
        _FakePopen.captured["kwargs"] = kwargs

    captured: dict[str, object] = {}

    def communicate(self, input=None, timeout=None):  # noqa: ANN001
        _FakePopen.captured["input"] = input
        _FakePopen.captured["timeout"] = timeout
        return b"", b""


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


def test_run_script_streams_stdin_to_non_interactive_sudo_bash_with_tty(monkeypatch) -> None:
    _FakePopen.captured = {}
    monkeypatch.setattr("subprocess.Popen", _FakePopen)

    runner = SSHRunner()
    runner.run_script(_host(True, "onprem"), "echo hello\n")

    command = _FakePopen.captured["command"]
    assert isinstance(command, list)
    assert command[-1] == "sudo -n bash --noprofile --norc -s"
    assert "bash -i" not in command[-1]
    assert "su -" not in command[-1]
    assert _FakePopen.captured["input"] is not None
    assert b"echo hello" in _FakePopen.captured["input"]


def test_run_script_normalizes_crlf_before_communicate(monkeypatch) -> None:
    _FakePopen.captured = {}
    monkeypatch.setattr("subprocess.Popen", _FakePopen)

    runner = SSHRunner()
    runner.run_script(_host(True, "onprem"), "echo one\r\necho two\r")

    streamed = _FakePopen.captured["input"]
    assert isinstance(streamed, bytes)
    assert b"\r" not in streamed
    assert b"echo one\necho two\n" in streamed
