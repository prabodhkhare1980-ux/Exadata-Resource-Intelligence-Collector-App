from types import SimpleNamespace

from collectors.asm_diskgroups_collector import ASMDiskgroupCollector


class _Runner:
    def __init__(self, stdout: str, ok: bool = True):
        self._stdout = stdout
        self._ok = ok

    def run_script(self, host, script):
        return SimpleNamespace(ok=self._ok, stdout=self._stdout, stderr="", error=None, returncode=0)


def _host():
    return SimpleNamespace(name="h1", address="1.1.1.1")


def test_failed_status_from_sections() -> None:
    out = "\n__ERIC_SECTION__:asm_lsdg\nORA-01017\n__ERIC_SECTION__:asm_collection_status\nfailed\n__ERIC_SECTION__:asm_error\nORA-01017\n"
    collector = ASMDiskgroupCollector(_Runner(out))
    rows = collector.collect_host("c1", _host(), __import__('logging').getLogger('t'))
    assert rows[-1].asm_collection_status == "failed"
