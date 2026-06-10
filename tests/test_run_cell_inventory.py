"""Tests for the standalone cell-inventory driver script."""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts import run_cell_inventory


_CONFIG = """
environments:
  onprem:
    ssh_user: srcordma
    auth: {method: ssh_key, private_key: .secrets/ssh/k}
    privilege: {enabled: true, method: sudo, sudo_password: none, force_tty: true}
    cell_access:
      method: dcli_or_direct
      users: [root, celladmin]
clusters:
  - name: rac01
    environment: onprem
    hosts:
      - {name: db01, address: 10.0.0.1}
collection:
  output_dir: output
  cell_inventory: {enabled: true, timeout_seconds: 45}
"""


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(_CONFIG, encoding="utf-8")
    return cfg


def test_unknown_cluster_returns_2(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    rc = run_cell_inventory.main(["--config", str(cfg), "--cluster", "nope", "--no-write"])
    assert rc == 2


def test_disabled_short_circuits(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(_CONFIG.replace("enabled: true", "enabled: false"), encoding="utf-8")
    rc = run_cell_inventory.main(["--config", str(cfg), "--no-write"])
    assert rc == 0


def test_runs_collector_with_injected_runner(tmp_path: Path, monkeypatch) -> None:
    """Drive the script end-to-end without real SSH by faking the runner."""

    cfg = _write_config(tmp_path)

    from ssh_runner import CommandResult

    class FakeRunner:
        def __init__(self, *a, **k):
            pass

        def run_command(self, host, command):
            if "command -v dcli" in command:
                return CommandResult(host, [], "/usr/bin/dcli\n", "", 0)
            if "cat /root/cell_group" in command:
                return CommandResult(host, [], "cel01\n", "", 0)
            if "list cell detail" in command:
                return CommandResult(
                    host, [],
                    "cel01: name: cel01\ncel01: cellVersion: OSS_23.1\ncel01: releaseVersion: 23.1.0.0.0\ncel01: status: online\n",
                    "", 0,
                )
            return CommandResult(host, [], "", "", 0)

    monkeypatch.setattr(run_cell_inventory, "SSHRunner", FakeRunner)
    rc = run_cell_inventory.main(["--config", str(cfg), "--no-write"])
    assert rc == 0
