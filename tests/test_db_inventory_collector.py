from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from collectors.db_inventory_collector import _parse_database_list, _parse_pmon_sids


def test_parse_pmon_sid_from_process_name() -> None:
    output = "oracle   1234  1  0 00:00 ?        00:00:00 ora_pmon_DOFLDVPD1\n"
    assert _parse_pmon_sids(output) == ["DOFLDVPD1"]


def test_srvctl_database_list_is_authoritative_and_sanitized() -> None:
    srvctl_output = "DOFLDVPD\ndlorfspd\ndotst1pd\n/,\"\",$0);\n"
    assert _parse_database_list(srvctl_output) == ["DOFLDVPD", "dlorfspd", "dotst1pd"]
