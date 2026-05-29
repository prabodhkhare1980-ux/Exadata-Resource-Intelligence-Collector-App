import py_compile
from pathlib import Path


def test_asm_collector_and_main_compile() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    py_compile.compile(str(repo_root / "collectors" / "asm_diskgroups_collector.py"), doraise=True)
    py_compile.compile(str(repo_root / "main.py"), doraise=True)
