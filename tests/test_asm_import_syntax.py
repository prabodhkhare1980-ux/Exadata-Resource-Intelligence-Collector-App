import py_compile
import subprocess
import sys
from pathlib import Path


def test_asm_collector_and_main_compile() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    py_compile.compile(str(repo_root / "collectors" / "asm_diskgroups.py"), doraise=True)
    py_compile.compile(str(repo_root / "collectors" / "asm_diskgroups_collector.py"), doraise=True)
    py_compile.compile(str(repo_root / "main.py"), doraise=True)


def test_main_help_imports_asm_collector_without_syntax_error() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(repo_root / "main.py"), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "IndentationError" not in proc.stderr
    assert "Collect Phase 1 OS capacity intelligence" in proc.stdout
