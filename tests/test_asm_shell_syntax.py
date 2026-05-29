import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.asm_diskgroups_collector import ASM_COLLECTION_SCRIPT


def test_asm_script_has_balanced_shell_syntax() -> None:
    script = ASM_COLLECTION_SCRIPT.replace("__ASM_TIMEOUT_SECONDS__", "30")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "asm_script.sh"
        path.write_text(script, encoding="utf-8")
        proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
