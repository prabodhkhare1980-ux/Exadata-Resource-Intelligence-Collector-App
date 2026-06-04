from pathlib import Path
import csv
import json
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from collectors.db_inventory_collector import DBInventoryRecord
from reports.writers import (
    write_db_resource_details_csv,
    write_db_resource_details_errors_csv,
    write_db_resource_details_errors_json,
    write_db_resource_details_json,
)


def _record() -> DBInventoryRecord:
    return DBInventoryRecord(
        cluster="c1",
        host="node1",
        address="10.0.0.1",
        collected_at="now",
        status="ok",
        db_resource_details=[
            {
                "Cluster": "c1",
                "cluster": "c1",
                "host": "node1",
                "address": "10.0.0.1",
                "HOST_NAME": "node1.example.com",
                "DB_NAME": "DB1",
                "DB_ROLE": "PRIMARY",
                "OPEN_MODE": "READ WRITE",
                "VERSION": "19.0.0.0.0",
                "RAC_ENABLED": "TRUE",
                "INST_COUNT": "2",
                "SGA_TARGET_GB": "16",
                "PGA_AGGR_TARGET_GB": "4",
                "SGA_MAX_SIZE_GB": "20",
                "PGA_AGGR_LIMIT_GB": "8",
                "PROCESSES": "800",
                "CPU_COUNT": "32",
                "DB_SIZE_GB": "200",
                "USED_DB_SIZE_GB": "171",
                "db_unique_name": "DB1_UNQ",
                "oracle_home": "/u01/dbhome",
                "oracle_sid": "DB11",
                "size_source": "cdb",
                "collection_status": "success",
                "collection_error": "",
                "Collected_At": "now",
                "mapping_source": "srvctl_node_match",
            },
            {
                "cluster": "c1",
                "host": "node1",
                "address": "10.0.0.1",
                "db_unique_name": "DB2_UNQ",
                "oracle_home": "/u01/dbhome",
                "oracle_sid": "",
                "collection_status": "skipped",
                "collection_error": "no_local_running_instance",
                "error_category": "NO_LOCAL_INSTANCE",
                "Collected_At": "now",
                "mapping_source": "",
            },
            {
                "cluster": "c1",
                "host": "node1",
                "address": "10.0.0.1",
                "db_unique_name": "DB3_UNQ",
                "oracle_home": "/u01/dbhome",
                "oracle_sid": "DB31",
                "collection_status": "failed",
                "collection_error": "ORA-01031: insufficient privileges",
                "error_category": "ORACLE_ERROR",
                "sql_returncode": 1031,
                "sql_stdout": "ORA-01031: insufficient privileges",
                "sql_stderr": "Connection to node1 closed.",
                "Collected_At": "now",
                "mapping_source": "srvctl_node_match",
            },
        ],
    )


def test_db_resource_success_outputs_are_normalized_and_success_only(tmp_path: Path) -> None:
    write_db_resource_details_csv([_record()], tmp_path)
    write_db_resource_details_json([_record()], tmp_path)

    with (tmp_path / "db_resource_details.csv").open(encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == 1
    assert rows[0]["Cluster"] == "c1"
    assert "cluster" not in rows[0]
    assert rows[0]["DB_USED_PCT"] == "85.5"

    payload = json.loads((tmp_path / "db_resource_details.json").read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert set(payload[0]) == {
        "cluster",
        "host",
        "address",
        "host_name",
        "db_name",
        "db_role",
        "open_mode",
        "version",
        "rac_enabled",
        "inst_count",
        "sga_target_gb",
        "pga_aggr_target_gb",
        "sga_max_size_gb",
        "pga_aggr_limit_gb",
        "processes",
        "cpu_count",
        "db_size_gb",
        "used_db_size_gb",
        "db_used_pct",
        "db_unique_name",
        "oracle_home",
        "oracle_sid",
        "size_source",
        "collection_status",
        "collection_error",
        "collected_at",
        "mapping_source",
    }
    assert payload[0]["db_used_pct"] == 85.5
    assert payload[0]["collection_status"] == "success"


def test_db_resource_error_outputs_route_skipped_and_failed(tmp_path: Path) -> None:
    write_db_resource_details_errors_csv([_record()], tmp_path)
    write_db_resource_details_errors_json([_record()], tmp_path)

    with (tmp_path / "db_resource_details_errors.csv").open(encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert [row["collection_status"] for row in rows] == ["skipped", "failed"]
    assert rows[0]["error_category"] == "NO_LOCAL_INSTANCE"
    assert rows[1]["collection_error"] == "ORA-01031: insufficient privileges"

    payload = json.loads((tmp_path / "db_resource_details_errors.json").read_text(encoding="utf-8"))
    assert [row["db_unique_name"] for row in payload] == ["DB2_UNQ", "DB3_UNQ"]
    assert payload[1]["sql_stdout"] == "ORA-01031: insufficient privileges"
