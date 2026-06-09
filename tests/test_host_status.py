"""Tests for host status classification and orchestration in ``main``."""

from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from collectors.asm_diskgroups_collector import ASMDiskgroupRecord
from collectors.db_inventory_collector import DBInventoryRecord
from collectors.hugepages_collector import HugePagesRecord
from collectors.os_collector import OSCollectionRecord
from collectors.version_inventory_collector import VersionInventoryRecord
from inventory import ClusterConfig, HostConfig, Inventory


def _host(name: str = "h1", timeout_seconds: int = 30) -> HostConfig:
    return HostConfig(
        name=name,
        address="10.0.0.1",
        user="srcordma",
        environment="prod",
        auth_method="ssh_key",
        private_key=".secrets/ssh/srcordma_id_rsa",
        strict_host_key_checking="accept-new",
        port=22,
        privilege_enabled=True,
        privilege_method="sudo",
        sudo_password_mode="none",
        force_tty=False,
        timeout_seconds=timeout_seconds,
    )


def _os(status: str = "ok") -> OSCollectionRecord:
    return OSCollectionRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="now",
        status=status,
    )


def _db(status: str = "ok", collection_status: str = "success") -> DBInventoryRecord:
    return DBInventoryRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="now",
        status=status,
        collection_status=collection_status,
    )


def _hp(collection_status: str = "success") -> HugePagesRecord:
    return HugePagesRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="now",
        collection_status=collection_status,
    )


def _ver(collection_status: str = "success") -> VersionInventoryRecord:
    return VersionInventoryRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="now",
        collection_status=collection_status,
    )


def _asm_success() -> list[ASMDiskgroupRecord]:
    return [
        ASMDiskgroupRecord(
            cluster="c1",
            host="h1",
            address="10.0.0.1",
            diskgroup_name="DATA",
            asm_collection_status="success",
        )
    ]


def test_compute_host_status_all_success() -> None:
    status = main._compute_host_status(_os(), _db(), _asm_success(), _hp(), _ver())
    assert status == main.HOST_STATUS_SUCCESS


def test_compute_host_status_db_partial_marks_partial_not_failed() -> None:
    """A DB inventory with srvctl issues should be partial, not failed."""

    db = DBInventoryRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="now",
        status="partial",
        collection_status="partial",
        error="srvctl config database failed",
    )
    status = main._compute_host_status(_os(), db, _asm_success(), _hp(), _ver())
    assert status == main.HOST_STATUS_PARTIAL


def test_compute_host_status_db_row_level_sql_warnings_do_not_fail_host() -> None:
    """ORA-01034/ORA-01219 are row-level warnings inside DB inventory;
    they do not propagate to the host-level record and must not mark the
    host failed when the overall DB inventory still succeeded."""

    db = DBInventoryRecord(
        cluster="c1",
        host="iad3dx02v1-6rdqa1",
        address="10.0.0.1",
        collected_at="now",
        status="ok",
        collection_status="success",
        db_resource_details=[
            {
                "db_unique_name": "PROD1",
                "collection_status": "success",
            },
            {
                "db_unique_name": "PROD2",
                "collection_status": "failed",
                "collection_error": "ORA-01034: ORACLE not available",
            },
            {
                "db_unique_name": "PROD3",
                "collection_status": "failed",
                "collection_error": "ORA-01219: database or pluggable database not open",
            },
        ],
    )
    status = main._compute_host_status(_os(), db, _asm_success(), _hp(), _ver())
    assert status == main.HOST_STATUS_SUCCESS


def test_compute_host_status_os_failed_is_only_path_to_failed() -> None:
    """SSH/sudo failure (OS record failed) is the canonical host-level fail."""

    status = main._compute_host_status(
        _os(status="failed"), _db(), _asm_success(), _hp(), _ver()
    )
    assert status == main.HOST_STATUS_FAILED


def test_compute_host_status_all_subcollectors_failed_marks_failed() -> None:
    """If OS succeeded but every other required collector failed, mark failed."""

    db = _db(status="failed", collection_status="failed")
    hp = _hp(collection_status="failed")
    ver = _ver(collection_status="failed")
    asm = [
        ASMDiskgroupRecord(
            cluster="c1",
            host="h1",
            address="10.0.0.1",
            asm_collection_status="failed",
        )
    ]
    status = main._compute_host_status(_os(), db, asm, hp, ver)
    assert status == main.HOST_STATUS_FAILED


def test_compute_host_status_completed_all_collectors_is_success() -> None:
    """Regression: OS + DB + ASM + HugePages + version all completed -> success."""

    status = main._compute_host_status(
        _os(),
        _db(),
        _asm_success(),
        _hp(collection_status="success"),
        _ver(collection_status="success"),
    )
    assert status == main.HOST_STATUS_SUCCESS


def test_compute_host_status_hugepages_skipped_marks_partial() -> None:
    status = main._compute_host_status(
        _os(),
        _db(),
        _asm_success(),
        _hp(collection_status="skipped"),
        _ver(),
    )
    assert status == main.HOST_STATUS_PARTIAL


def test_host_worker_deadline_seconds_is_generous() -> None:
    host = _host(timeout_seconds=120)
    inventory = Inventory(
        clusters=[ClusterConfig(name="c1", environment="prod", hosts=[host])],
        output_dir=Path("/tmp"),
        logs_dir=Path("/tmp/logs"),
        parallel_enabled=True,
        asm_timeout_seconds=30,
        hugepages_timeout_seconds=15,
        db_performance_timeout_seconds=90,
    )
    deadline = main._host_worker_deadline_seconds(host, inventory)
    # Sum of individual collector timeouts is 120+30+15+90 = 255s. The
    # safety-net deadline must be larger than the sum to avoid timing out
    # a host while its collectors are still legitimately running.
    assert deadline > 120 + 30 + 15 + 90
    assert deadline >= 600


def test_collect_cluster_parallel_does_not_fail_host_due_to_db_row_warnings(
    monkeypatch, tmp_path: Path
) -> None:
    """The host orchestration must not log a failure for a host where DB
    inventory finished successfully despite row-level SQL warnings, and
    where ASM/HugePages/version all completed."""

    host = _host(name="iad3dx02v1-6rdqa1")
    cluster = ClusterConfig(name="c1", environment="prod", hosts=[host])
    inventory = Inventory(
        clusters=[cluster],
        output_dir=tmp_path,
        logs_dir=tmp_path / "logs",
        parallel_enabled=True,
        max_hosts_per_cluster=1,
        max_clusters=1,
    )

    db = DBInventoryRecord(
        cluster=cluster.name,
        host=host.name,
        address=host.address,
        collected_at="now",
        status="ok",
        collection_status="success",
        db_resource_details=[
            {"collection_status": "success"} for _ in range(44)
        ]
        + [{"collection_status": "skipped"}]
        + [
            {"collection_status": "failed", "collection_error": "ORA-01034"},
            {"collection_status": "failed", "collection_error": "ORA-01219"},
        ],
    )

    def fake_collect_host(cluster_arg, host_arg, runner, logs_dir, inventory_arg):
        return main.HostCollectionResult(
            os_record=OSCollectionRecord(
                cluster=cluster_arg.name,
                host=host_arg.name,
                address=host_arg.address,
                collected_at="now",
                status="ok",
            ),
            db_record=db,
            asm_records=[
                ASMDiskgroupRecord(
                    cluster=cluster_arg.name,
                    host=host_arg.name,
                    address=host_arg.address,
                    diskgroup_name="DATA",
                    asm_collection_status="success",
                )
            ],
            hugepages_record=HugePagesRecord(
                cluster=cluster_arg.name,
                host=host_arg.name,
                address=host_arg.address,
                collected_at="now",
                collection_status="success",
            ),
            version_record=VersionInventoryRecord(
                cluster=cluster_arg.name,
                host=host_arg.name,
                address=host_arg.address,
                collected_at="now",
                collection_status="success",
            ),
            db_performance_records=[],
            db_memory_records=[],
        )

    monkeypatch.setattr(main, "_collect_host", fake_collect_host)
    # Don't make a real SSH connection inside collect_cluster_memory_history.
    monkeypatch.setattr(
        "collectors.db_performance_collector.DBPerformanceCollector.collect_cluster_memory_history",
        lambda self, *a, **kw: [],
    )

    result = main._collect_cluster_parallel(cluster, inventory, runner=None)
    (
        os_records,
        db_records,
        asm_records,
        hugepages_records,
        version_records,
        db_performance_records,
        db_memory_records,
        success,
        partial,
        failed,
    ) = result

    assert success == 1
    assert partial == 0
    assert failed == 0
    assert len(os_records) == 1 and os_records[0].status == "ok"
    assert len(asm_records) == 1
    assert hugepages_records[0].collection_status == "success"
    assert version_records[0].collection_status == "success"


def test_collect_cluster_parallel_does_not_double_count_on_late_completion(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    """Future.result(timeout=...) must use a deadline generous enough that
    a slow-but-eventually-successful worker is not marked failed while it
    keeps running. The bug being fixed previously emitted ``Failed host``
    at the orchestrator level even though the worker continued and later
    completed ASM / HugePages / version inventory."""

    host = _host(name="iad3dx02v1-6rdqa1", timeout_seconds=2)
    cluster = ClusterConfig(name="c1", environment="prod", hosts=[host])
    inventory = Inventory(
        clusters=[cluster],
        output_dir=tmp_path,
        logs_dir=tmp_path / "logs",
        parallel_enabled=True,
        max_hosts_per_cluster=1,
        max_clusters=1,
        asm_timeout_seconds=1,
        hugepages_timeout_seconds=1,
        db_performance_timeout_seconds=1,
    )

    def slow_collect_host(cluster_arg, host_arg, runner, logs_dir, inventory_arg):
        # Take a couple of seconds (longer than host.timeout_seconds * 2,
        # which is what the old code used as the Future deadline) before
        # returning a fully-successful result.
        time.sleep(1.5)
        return main.HostCollectionResult(
            os_record=OSCollectionRecord(
                cluster=cluster_arg.name,
                host=host_arg.name,
                address=host_arg.address,
                collected_at="now",
                status="ok",
            ),
            db_record=DBInventoryRecord(
                cluster=cluster_arg.name,
                host=host_arg.name,
                address=host_arg.address,
                collected_at="now",
                status="ok",
                collection_status="success",
            ),
            asm_records=[
                ASMDiskgroupRecord(
                    cluster=cluster_arg.name,
                    host=host_arg.name,
                    address=host_arg.address,
                    diskgroup_name="DATA",
                    asm_collection_status="success",
                )
            ],
            hugepages_record=HugePagesRecord(
                cluster=cluster_arg.name,
                host=host_arg.name,
                address=host_arg.address,
                collected_at="now",
                collection_status="success",
            ),
            version_record=VersionInventoryRecord(
                cluster=cluster_arg.name,
                host=host_arg.name,
                address=host_arg.address,
                collected_at="now",
                collection_status="success",
            ),
            db_performance_records=[],
            db_memory_records=[],
        )

    monkeypatch.setattr(main, "_collect_host", slow_collect_host)
    monkeypatch.setattr(
        "collectors.db_performance_collector.DBPerformanceCollector.collect_cluster_memory_history",
        lambda self, *a, **kw: [],
    )

    caplog.set_level(logging.DEBUG)
    result = main._collect_cluster_parallel(cluster, inventory, runner=None)
    (
        os_records,
        db_records,
        asm_records,
        hugepages_records,
        version_records,
        _db_perf,
        _db_mem,
        success,
        partial,
        failed,
    ) = result

    assert success == 1
    assert failed == 0
    # Ensure the orchestrator did not log a contradictory "Failed host"
    # message while the worker was still running.
    failure_logs = [
        r for r in caplog.records if r.levelno >= logging.ERROR and "Failed host" in r.message
    ]
    assert failure_logs == [], (
        "Orchestrator must not emit 'Failed host' for a worker that "
        "eventually completes successfully"
    )
    # Sanity: all sub-collector results were aggregated from the final
    # worker return value, not from a synthetic failure record.
    assert os_records[0].status == "ok"
    assert hugepages_records[0].collection_status == "success"
    assert version_records[0].collection_status == "success"
    assert len(asm_records) == 1


def test_summarize_collector_outcomes_includes_each_collector() -> None:
    detail = main._summarize_collector_outcomes(
        _os(), _db(), _asm_success(), _hp(), _ver()
    )
    assert "os=ok" in detail
    assert "db=success" in detail
    assert "hugepages=success" in detail
    assert "version=success" in detail
    assert "asm=1/1" in detail
