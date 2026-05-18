from exadata_ric.auth import CredentialProvider
from exadata_ric.config import AuthConfig, HostConfig


def _host(name: str, environment: str, ssh_user: str) -> HostConfig:
    return HostConfig(
        name=name,
        address=f"{name}.example.com",
        cluster="rac01",
        environment=environment,
        ssh_user=ssh_user,
        auth=AuthConfig(method="password", sudo_password="same_as_ssh"),
    )


def test_password_prompt_once_per_environment_and_ssh_user(monkeypatch):
    prompts: list[str] = []

    def fake_getpass(prompt: str) -> str:
        prompts.append(prompt)
        return f"secret-{len(prompts)}"

    monkeypatch.setattr("exadata_ric.auth.getpass.getpass", fake_getpass)
    provider = CredentialProvider()

    first = provider.for_host(_host("db01", "onprem", "alice"))
    second = provider.for_host(_host("db02", "onprem", "alice"))
    different_environment = provider.for_host(_host("db03", "oci", "alice"))
    different_user = provider.for_host(_host("db04", "onprem", "bob"))

    assert first.ssh_password == "secret-1"
    assert first.sudo_password == "secret-1"
    assert second.ssh_password == "secret-1"
    assert different_environment.ssh_password == "secret-2"
    assert different_user.ssh_password == "secret-3"
    assert prompts == [
        "SSH password for alice (environment: onprem): ",
        "SSH password for alice (environment: oci): ",
        "SSH password for bob (environment: onprem): ",
    ]


def test_remote_error_redacts_runtime_password(monkeypatch):
    from subprocess import CompletedProcess

    from exadata_ric.auth import RuntimeCredentials
    from exadata_ric.ssh import RemoteExecutionError, run_remote_script

    host = _host("db05", "onprem", "alice")

    def fake_prepare_askpass(password: str):
        read_fd = 99
        write_fd = 100
        return type("FakePath", (), {"unlink": lambda self: None, "parent": type("FakeParent", (), {"rmdir": lambda self: None})()})(), (read_fd, write_fd)

    def fake_close(fd: int) -> None:
        return None

    def fake_run(*args, **kwargs):
        return CompletedProcess(args=args[0], returncode=1, stdout="", stderr="bad swordfish sudo swordfish")

    monkeypatch.setattr("exadata_ric.ssh._prepare_askpass", fake_prepare_askpass)
    monkeypatch.setattr("exadata_ric.ssh.os.close", fake_close)
    monkeypatch.setattr("exadata_ric.ssh.subprocess.run", fake_run)

    try:
        run_remote_script(host, "echo ok\n", RuntimeCredentials(ssh_password="swordfish", sudo_password="swordfish"))
    except RemoteExecutionError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RemoteExecutionError")

    assert "swordfish" not in message
    assert "[REDACTED]" in message
