"""Command-line entry point for Exadata Resource Intelligence Collector."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from collectors.db_inventory_collector import DBInventoryCollector, DBInventoryRecord
from collectors.db_performance_collector import (
    DBMemoryHistoryRecord,
    DBPerformanceCollector,
    DBPerformanceRecord,
)
from collectors.asm_diskgroups_collector import (
    ASMDiskgroupCollector,
    ASMDiskgroupRecord,
)
from collectors.os_collector import OSCollectionRecord, OSCollector
from collectors.hugepages_collector import HugePagesCollector, HugePagesRecord
from collectors.version_inventory_collector import (
    VersionInventoryCollector,
    VersionInventoryRecord,
)
from collectors.db_capacity_collector import DBCapacityCollector
from collectors.db_patch_collector import DBPatchCollector
from collectors.db_workload_collector import DBWorkloadCollector
from collectors.shared_context import SharedHostContext
from inventory import Inventory, load_inventory
from logging_setup import configure_logging, host_logger
from reports.writers import (
    write_asm_diskgroups_csv,
    write_asm_diskgroups_json,
    write_asm_metadata_csv,
    write_asm_metadata_json,
    write_asm_summary_csv,
    write_asm_summary_json,
    write_db_inventory_csv,
    write_db_inventory_json,
    write_db_memory_cluster_summary_csv,
    write_db_memory_cluster_summary_json,
    write_db_memory_history_csv,
    write_db_memory_history_errors_csv,
    write_db_memory_history_errors_json,
    write_db_memory_history_json,
    write_db_memory_history_summary_csv,
    write_db_memory_history_summary_json,
    write_db_performance_csv,
    write_db_performance_errors_csv,
    write_db_performance_errors_json,
    write_db_performance_json,
    write_db_resource_details_csv,
    write_db_resource_details_errors_csv,
    write_db_resource_details_errors_json,
    write_db_resource_details_json,
    write_os_csv,
    write_os_json,
    write_hugepages_csv,
    write_hugepages_json,
    write_version_inventory_csv,
    write_version_inventory_json,
    write_version_summary_csv,
    write_version_summary_json,
    write_pdb_inventory_csv,
    write_pdb_inventory_json,
    write_feature_usage_csv,
    write_feature_usage_json,
    write_db_patch_inventory_csv,
    write_db_patch_inventory_json,
    write_db_workload_csv,
    write_db_workload_json,
    write_db_tablespace_growth_csv,
    write_db_tablespace_growth_json,
    build_health_summary_rows,
    health_summary_counts,
    write_health_summary_csv,
    write_health_summary_html,
    write_health_summary_json,
)
from ssh_runner import SSHRunner

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostCollectionResult:
    """Typed result returned by the canonical per-host collection pipeline."""

    os_record: OSCollectionRecord
    db_record: DBInventoryRecord
    asm_records: list[ASMDiskgroupRecord]
    hugepages_record: HugePagesRecord
    version_record: VersionInventoryRecord
    db_performance_records: list[DBPerformanceRecord]
    db_memory_records: list[DBMemoryHistoryRecord]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Phase 1 OS capacity intelligence from Exadata/RAC nodes."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML inventory file. Default: config/clusters.local.yaml (if present) else config/clusters.example.yaml",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose DEBUG logging."
    )
    parser.add_argument(
        "--show-inventory",
        action="store_true",
        help="Print resolved inventory details for each host and exit.",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Run SSH key/sudo preflight checks for each host.",
    )
    parser.add_argument(
        "--debug-ssh",
        action="store_true",
        help="Print sanitized SSH command plus first 500 chars of stdout/stderr.",
    )
    parser.add_argument(
        "--max-clusters", type=int, help="Override collection.parallel.max_clusters"
    )
    parser.add_argument(
        "--max-hosts-per-cluster",
        type=int,
        help="Override collection.parallel.max_hosts_per_cluster",
    )
    parser.add_argument(
        "--collector",
        choices=["all", "asm"],
        default="all",
        help="Run all collectors (default) or a single collector.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host name filter, used with --collector asm for standalone ASM test mode.",
    )
    return parser.parse_args(argv)


def show_inventory(inventory: Inventory) -> int:
    print(
        "cluster,environment,host,address,resolved_ssh_user,auth_method,private_key,privilege_method,sudo_password"
    )
    for cluster in inventory.clusters:
        for host in cluster.hosts:
            print(
                f"{cluster.name},{cluster.environment},{host.name},{host.address},{host.user},{host.auth_method},{host.private_key or ''},{host.privilege_method},{host.sudo_password_mode}"
            )
    return 0


def preflight(inventory: Inventory, debug_ssh: bool = False) -> int:
    runner = SSHRunner(logging.getLogger("ssh_runner"), debug_ssh=debug_ssh)
    inventory.output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    failures = 0
    for cluster in inventory.clusters:
        for host in cluster.hosts:
            key_exists = bool(host.private_key and Path(host.private_key).exists())
            key_readable = bool(
                host.private_key
                and Path(host.private_key).is_file()
                and os.access(host.private_key, os.R_OK)
            )
            ssh_result = runner.run_command(host, "hostname")
            sudo_host = runner.run_command(host, "sudo -n hostname")
            sudo_whoami = runner.run_command(host, "sudo -n whoami")
            if host.sudo_password_mode == "none" and not sudo_host.ok:
                sudo_error = (
                    "sudo -n failed; configure NOPASSWD sudo for service account"
                )
            else:
                sudo_error = ""
            status = (
                "PASS"
                if key_exists
                and key_readable
                and ssh_result.ok
                and sudo_host.ok
                and sudo_whoami.ok
                else "FAIL"
            )
            if status != "PASS":
                failures += 1
            rows.append(
                {
                    "cluster": cluster.name,
                    "environment": cluster.environment,
                    "host": host.name,
                    "address": host.address,
                    "ssh_user": host.user,
                    "auth_method": host.auth_method,
                    "private_key": host.private_key or "",
                    "key_exists": str(key_exists),
                    "key_readable": str(key_readable),
                    "ssh_login_works": str(ssh_result.ok),
                    "sudo_n_hostname": str(sudo_host.ok),
                    "sudo_n_whoami": (
                        sudo_whoami.stdout.strip() if sudo_whoami.ok else ""
                    ),
                    "status": status,
                    "error": sudo_error
                    or ssh_result.error
                    or ssh_result.stderr.strip()
                    or sudo_host.stderr.strip(),
                }
            )
    json_path = inventory.output_dir / "preflight_report.json"
    csv_path = inventory.output_dir / "preflight_report.csv"
    json_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    fields = list(rows[0].keys()) if rows else []
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    _print_preflight_report(rows, csv_path, json_path)
    return 2 if failures else 0


def _print_preflight_report(
    rows: list[dict[str, str]], csv_path: Path, json_path: Path
) -> None:
    print("\nPreflight Report")
    print("=" * 110)
    print(
        f"{'Status':<8} {'Environment':<12} {'Cluster':<20} {'Host':<20} {'SSH':<6} {'sudo -n':<8} Error"
    )
    print("-" * 110)
    for row in rows:
        print(
            f"{row['status']:<8} {row['environment']:<12} {row['cluster']:<20} {row['host']:<20} "
            f"{row['ssh_login_works']:<6} {row['sudo_n_hostname']:<8} {row['error']}"
        )
    passed = sum(1 for row in rows if row["status"] == "PASS")
    failed = len(rows) - passed
    print("-" * 110)
    print(f"Summary: PASS={passed} FAIL={failed} TOTAL={len(rows)}")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}\n")


# run() and main unchanged-ish


def _collect_db_capacity(db_records, inventory, runner):
    """Collect PDB inventory and feature usage across all collected databases.

    Post-pass over ``db_records`` (the DB inventory already gathered by both
    the sequential and parallel pipelines), so it does not need to thread new
    fields through the per-host result type. Returns (pdb_records,
    feature_records). Failures are logged and never abort the run.
    """

    if not inventory.db_capacity_enabled:
        return [], []

    hosts_by_name = {
        host.name: host
        for cluster in inventory.clusters
        for host in cluster.hosts
    }
    collector = DBCapacityCollector(
        runner, logger=logging.getLogger("collectors.db_capacity")
    )
    pdb_records = []
    feature_records = []
    for db_record in db_records:
        host = hosts_by_name.get(db_record.host)
        if host is None:
            continue
        try:
            pdbs, features = collector.collect_host(
                db_record,
                host,
                enabled=True,
                collect_pdb_inventory=inventory.db_capacity_collect_pdb_inventory,
                collect_feature_usage=inventory.db_capacity_collect_feature_usage,
                timeout_seconds=inventory.db_capacity_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "DB capacity collection skipped/failed for %s: %s",
                db_record.host,
                exc,
            )
            continue
        pdb_records.extend(pdbs)
        feature_records.extend(features)
    return pdb_records, feature_records


def _collect_db_patches(db_records, inventory, runner):
    """Collect opatch lspatches per Oracle home across all collected databases.

    Post-pass over ``db_records``, same shape as ``_collect_db_capacity``.
    Returns a flat list of DBPatchRecord. Failures are logged, never fatal.
    """

    if not inventory.db_patch_enabled:
        return []

    hosts_by_name = {
        host.name: host
        for cluster in inventory.clusters
        for host in cluster.hosts
    }
    collector = DBPatchCollector(
        runner, logger=logging.getLogger("collectors.db_patch")
    )
    patch_records = []
    for db_record in db_records:
        host = hosts_by_name.get(db_record.host)
        if host is None:
            continue
        try:
            patch_records.extend(
                collector.collect_host(
                    db_record,
                    host,
                    enabled=True,
                    timeout_seconds=inventory.db_patch_timeout_seconds,
                    include_grid_home=inventory.db_patch_include_grid_home,
                )
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "DB patch collection skipped/failed for %s: %s", db_record.host, exc
            )
    return patch_records


def _collect_db_workload(db_records, inventory, runner):
    """Collect AWR workload intensity and tablespace growth across databases.

    Post-pass over ``db_records``. Returns (workload_records,
    tablespace_records). Honours the same AWR/days_back settings as the
    db_performance collector. Failures are logged, never fatal.
    """

    if not inventory.db_workload_enabled:
        return [], []

    hosts_by_name = {
        host.name: host
        for cluster in inventory.clusters
        for host in cluster.hosts
    }
    collector = DBWorkloadCollector(
        runner, logger=logging.getLogger("collectors.db_workload")
    )
    workload_records = []
    tablespace_records = []
    for db_record in db_records:
        host = hosts_by_name.get(db_record.host)
        if host is None:
            continue
        try:
            workload, tablespaces = collector.collect_host(
                db_record,
                host,
                enabled=True,
                use_awr=inventory.db_performance_use_awr,
                days_back=inventory.db_performance_days_back,
                timeout_seconds=inventory.db_workload_timeout_seconds,
                collect_workload=inventory.db_workload_collect_workload,
                collect_tablespace_growth=inventory.db_workload_collect_tablespace_growth,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "DB workload collection skipped/failed for %s: %s",
                db_record.host,
                exc,
            )
            continue
        workload_records.extend(workload)
        tablespace_records.extend(tablespaces)
    return workload_records, tablespace_records


def _collect_host(cluster, host, runner, logs_dir, inventory):
    logger = host_logger(logs_dir, f"{cluster.name}_{host.name}")
    context = SharedHostContext(runner, logging.getLogger("collectors.shared_context"))
    os_collector = OSCollector(
        runner, context=context, logger=logging.getLogger("collectors.os")
    )
    db_collector = DBInventoryCollector(
        runner, context=context, logger=logging.getLogger("collectors.db_inventory")
    )
    os_record = os_collector.collect_host(cluster.name, host, logger)
    db_record = db_collector.collect_host(cluster.name, host, logger)
    db_perf_collector = DBPerformanceCollector(
        runner, logger=logging.getLogger("collectors.db_performance")
    )
    try:
        db_performance_records, db_memory_records = db_perf_collector.collect_host(
            db_record,
            host,
            enabled=inventory.db_performance_enabled,
            use_awr=inventory.db_performance_use_awr,
            days_back=inventory.db_performance_days_back,
            timeout_seconds=inventory.db_performance_timeout_seconds,
            collect_cpu_iops=inventory.db_performance_collect_cpu_iops,
            # Memory history is cluster-scoped and deduplicated by db_unique_name below.
            collect_memory_history=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "DB performance collection skipped/failed for %s: %s", host.name, exc
        )
        db_performance_records, db_memory_records = [], []
    asm_collector = ASMDiskgroupCollector(
        runner, context=context, logger=logging.getLogger("collectors.asm_diskgroups")
    )
    try:
        asm_records = asm_collector.collect_host(
            cluster.name,
            host,
            logger,
            enabled=inventory.asm_enabled,
            timeout_seconds=inventory.asm_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ASM diskgroup collection failed: error=%s", exc)
        if inventory.asm_fail_host_on_error:
            raise
        asm_records = [
            ASMDiskgroupRecord(
                cluster=cluster.name,
                host=host.name,
                address=host.address,
                collected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                asm_collection_status="failed",
                warning_level="ERROR",
                asm_collection_error=str(exc),
                asm_error=str(exc),
            )
        ]

    hugepages_collector = HugePagesCollector(
        runner, context=context, logger=logging.getLogger("collectors.hugepages")
    )
    try:
        hugepages_record = hugepages_collector.collect_host(
            cluster.name,
            host,
            logger,
            enabled=inventory.hugepages_enabled,
            timeout_seconds=inventory.hugepages_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("HugePages collection skipped/failed for %s", host.name)
        hugepages_record = HugePagesRecord(
            cluster=cluster.name,
            host=host.name,
            address=host.address,
            collected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            warning_level="ERROR",
            collection_status="failed",
            collection_error=str(exc),
        )

    version_collector = VersionInventoryCollector(
        runner,
        context=context,
        logger=logging.getLogger("collectors.version_inventory"),
    )
    try:
        version_record = version_collector.collect_host(cluster.name, host, logger)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Version inventory collection skipped/failed for %s", host.name)
        version_record = VersionInventoryRecord(
            cluster=cluster.name,
            host=host.name,
            address=host.address,
            collected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            collection_status="failed",
            collection_error=str(exc),
        )
    return HostCollectionResult(
        os_record=os_record,
        db_record=db_record,
        asm_records=asm_records,
        hugepages_record=hugepages_record,
        version_record=version_record,
        db_performance_records=db_performance_records,
        db_memory_records=db_memory_records,
    )


def _failure_records_for(
    cluster_name: str,
    host,
    error: str,
    when: str | None = None,
) -> tuple[
    OSCollectionRecord,
    DBInventoryRecord,
    HugePagesRecord,
    VersionInventoryRecord,
]:
    """Build matching failure records across collectors for a single host.

    Used when a host (or its entire cluster) never produced real collector
    output — e.g. host timed out, host raised, or the cluster future itself
    failed. Keeps every collector's downstream output consistent.
    """

    timestamp = when or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        OSCollectionRecord(
            cluster=cluster_name,
            host=host.name,
            address=host.address,
            collected_at=timestamp,
            status="failed",
            error=error,
        ),
        DBInventoryRecord(
            cluster=cluster_name,
            host=host.name,
            address=host.address,
            collected_at=timestamp,
            status="failed",
            error=error,
        ),
        HugePagesRecord(
            cluster=cluster_name,
            host=host.name,
            address=host.address,
            collected_at=timestamp,
            warning_level="ERROR",
            collection_status="failed",
            collection_error=error,
        ),
        VersionInventoryRecord(
            cluster=cluster_name,
            host=host.name,
            address=host.address,
            collected_at=timestamp,
            collection_status="failed",
            collection_error=error,
        ),
    )


def _partition_asm_records(
    records: list[ASMDiskgroupRecord],
) -> tuple[list[ASMDiskgroupRecord], list[ASMDiskgroupRecord], list[ASMDiskgroupRecord]]:
    diskgroup_records = [
        record
        for record in records
        if record.record_type != "host_metadata"
        and record.asm_collection_status == "success"
        and bool(record.diskgroup_name)
    ]
    metadata_records = [
        record for record in records if record.record_type == "host_metadata"
    ]
    failure_records = [
        record
        for record in records
        if record.record_type != "host_metadata"
        and (record.asm_collection_status != "success" or not record.diskgroup_name)
    ]
    return diskgroup_records, metadata_records, failure_records


HOST_STATUS_SUCCESS = "success"
HOST_STATUS_PARTIAL = "partial_success"
HOST_STATUS_FAILED = "failed"


def _compute_host_status(
    os_record: OSCollectionRecord,
    db_record: DBInventoryRecord,
    asm_records: list[ASMDiskgroupRecord],
    hugepages_record: HugePagesRecord,
    version_record: VersionInventoryRecord,
) -> str:
    """Classify host outcome as success / partial_success / failed.

    Failure is reserved for situations where the host is effectively
    unreachable or unusable for collection (SSH/sudo failure, or every
    required host-level collector failed). DB-level SQL warnings (e.g.,
    ORA-01034 / ORA-01219 on individual databases) are row-level
    warnings, not host-level failures.
    """

    os_failed = str(os_record.status).lower() == "failed"
    if os_failed:
        return HOST_STATUS_FAILED

    db_status = str(getattr(db_record, "collection_status", "") or "").lower()
    db_failed = db_status == "failed" or str(db_record.status).lower() == "failed"
    db_partial = db_status == "partial"

    hp_status = str(getattr(hugepages_record, "collection_status", "") or "").lower()
    hp_failed = hp_status in {"failed", "skipped"}

    version_status = str(getattr(version_record, "collection_status", "") or "").lower()
    version_failed = version_status in {"failed", "skipped"}

    if asm_records:
        non_metadata = [r for r in asm_records if r.record_type != "host_metadata"]
        if non_metadata:
            asm_failed = all(
                str(r.asm_collection_status).lower() != "success"
                for r in non_metadata
            )
            asm_partial = (
                not asm_failed
                and any(
                    str(r.asm_collection_status).lower() != "success"
                    for r in non_metadata
                )
            )
        else:
            asm_failed = False
            asm_partial = False
    else:
        asm_failed = False
        asm_partial = False

    if db_failed and hp_failed and version_failed and asm_failed:
        # OS succeeded but every other required collector failed -> still failed.
        return HOST_STATUS_FAILED

    if db_failed or db_partial or hp_failed or version_failed or asm_failed or asm_partial:
        return HOST_STATUS_PARTIAL
    return HOST_STATUS_SUCCESS


def _host_worker_deadline_seconds(host, inventory: Inventory) -> int:
    """Generous safety-net timeout for waiting on a host worker future.

    Each collector enforces its own per-command timeout (OS/DB inventory
    use ``host.timeout_seconds``; ASM/HugePages/DB-performance use their
    configured ``*_timeout_seconds``). This orchestrator-level deadline is
    sized larger than the sum of all per-collector timeouts so it only
    fires as a last-resort safety net when a collector hangs past its
    internal timeout. It should not fire just because a host happens to
    have many databases or large collection footprints.
    """

    components = [
        max(int(getattr(host, "timeout_seconds", 0) or 0), 1),
        max(int(getattr(inventory, "asm_timeout_seconds", 0) or 0), 1),
        max(int(getattr(inventory, "hugepages_timeout_seconds", 0) or 0), 1),
        max(int(getattr(inventory, "db_performance_timeout_seconds", 0) or 0), 1),
    ]
    return max(sum(components) * 3, 600)


def _summarize_collector_outcomes(
    os_record: OSCollectionRecord,
    db_record: DBInventoryRecord,
    asm_records: list[ASMDiskgroupRecord],
    hugepages_record: HugePagesRecord,
    version_record: VersionInventoryRecord,
) -> str:
    """Return a short string describing each collector's outcome."""

    parts = [
        f"os={os_record.status}",
        f"db={getattr(db_record, 'collection_status', '') or db_record.status}",
        f"hugepages={getattr(hugepages_record, 'collection_status', '') or 'unknown'}",
        f"version={getattr(version_record, 'collection_status', '') or 'unknown'}",
    ]
    if asm_records:
        non_metadata = [r for r in asm_records if r.record_type != "host_metadata"]
        if non_metadata:
            successes = sum(
                1
                for r in non_metadata
                if str(r.asm_collection_status).lower() == "success"
            )
            parts.append(f"asm={successes}/{len(non_metadata)}")
        else:
            parts.append("asm=metadata_only")
    else:
        parts.append("asm=none")
    return " ".join(parts)


def run(inventory: Inventory, debug_ssh: bool = False) -> int:
    inventory.output_dir.mkdir(parents=True, exist_ok=True)
    inventory.logs_dir.mkdir(parents=True, exist_ok=True)
    runner = SSHRunner(logging.getLogger("ssh_runner"), debug_ssh=debug_ssh)
    os_records = []
    db_records = []
    asm_records = []
    hugepages_records = []
    version_records = []
    db_performance_records = []
    db_memory_records = []
    clusters_total = len(inventory.clusters)
    hosts_total = sum(len(cluster.hosts) for cluster in inventory.clusters)
    hosts_success = 0
    hosts_partial = 0
    hosts_failed = 0
    start_time = time.perf_counter()

    if not inventory.parallel_enabled:
        for cluster in inventory.clusters:
            LOGGER.info("Starting cluster %s", cluster.name)
            for host in cluster.hosts:
                LOGGER.info("Starting host %s", host.name)
                collected = _collect_host(
                    cluster, host, runner, inventory.logs_dir, inventory
                )
                os_record = collected.os_record
                db_record = collected.db_record
                host_asm_records = collected.asm_records
                hugepages_record = collected.hugepages_record
                version_record = collected.version_record
                host_db_performance = collected.db_performance_records
                host_db_memory = collected.db_memory_records
                os_records.append(os_record)
                db_records.append(db_record)
                asm_records.extend(host_asm_records)
                hugepages_records.append(hugepages_record)
                version_records.append(version_record)
                db_performance_records.extend(host_db_performance)
                db_memory_records.extend(host_db_memory)
                host_status = _compute_host_status(
                    os_record,
                    db_record,
                    host_asm_records,
                    hugepages_record,
                    version_record,
                )
                outcome_detail = _summarize_collector_outcomes(
                    os_record,
                    db_record,
                    host_asm_records,
                    hugepages_record,
                    version_record,
                )
                if host_status == HOST_STATUS_SUCCESS:
                    hosts_success += 1
                    LOGGER.info("Completed host %s status=success %s", host.name, outcome_detail)
                elif host_status == HOST_STATUS_PARTIAL:
                    hosts_partial += 1
                    LOGGER.warning(
                        "Completed host %s status=partial_success %s",
                        host.name,
                        outcome_detail,
                    )
                else:
                    hosts_failed += 1
                    LOGGER.error("Failed host %s status=failed %s", host.name, outcome_detail)
            # Collect memory once per db_unique_name across this cluster, not per host.
            db_memory_records.extend(
                DBPerformanceCollector(
                    runner, logger=logging.getLogger("collectors.db_performance")
                ).collect_cluster_memory_history(
                    [record for record in db_records if record.cluster == cluster.name],
                    {host.name: host for host in cluster.hosts},
                    enabled=inventory.db_performance_enabled
                    and inventory.db_performance_collect_memory_history,
                    use_awr=inventory.db_performance_use_awr,
                    days_back=inventory.db_performance_days_back,
                    timeout_seconds=inventory.db_performance_timeout_seconds,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=inventory.max_clusters) as cluster_pool:
            cluster_futures = {}
            for cluster in inventory.clusters:
                LOGGER.info("Starting cluster %s", cluster.name)
                future = cluster_pool.submit(
                    _collect_cluster_parallel, cluster, inventory, runner
                )
                cluster_futures[future] = cluster.name
            cluster_by_name = {cluster.name: cluster for cluster in inventory.clusters}
            for future in as_completed(cluster_futures):
                cluster_name = cluster_futures[future]
                try:
                    (
                        cluster_os,
                        cluster_db,
                        cluster_asm,
                        cluster_hugepages,
                        cluster_versions,
                        cluster_db_performance,
                        cluster_db_memory,
                        cluster_success,
                        cluster_partial,
                        cluster_failed,
                    ) = future.result()
                    os_records.extend(cluster_os)
                    db_records.extend(cluster_db)
                    asm_records.extend(cluster_asm)
                    hugepages_records.extend(cluster_hugepages)
                    version_records.extend(cluster_versions)
                    db_performance_records.extend(cluster_db_performance)
                    db_memory_records.extend(cluster_db_memory)
                    hosts_success += cluster_success
                    hosts_partial += cluster_partial
                    hosts_failed += cluster_failed
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception(
                        "Cluster execution failed for %s: %s", cluster_name, exc
                    )
                    # Emit a per-host failure record for every host in the
                    # failed cluster so the summary, dashboards, and downstream
                    # writers don't silently drop those hosts.
                    failed_cluster = cluster_by_name.get(cluster_name)
                    if failed_cluster is not None:
                        error_message = f"Cluster execution failed: {exc}"
                        for host in failed_cluster.hosts:
                            os_rec, db_rec, hp_rec, ver_rec = _failure_records_for(
                                cluster_name, host, error_message
                            )
                            os_records.append(os_rec)
                            db_records.append(db_rec)
                            hugepages_records.append(hp_rec)
                            version_records.append(ver_rec)
                            hosts_failed += 1

    # Tier 2: license/capacity DB collection (PDB inventory + feature usage).
    # Runs as a post-pass over the DB inventory we already collected, mirroring
    # the cluster-scoped memory-history pass. Uses base views only (no
    # Diagnostics Pack), so it is independent of db_performance/AWR settings.
    pdb_records, feature_records = _collect_db_capacity(
        db_records, inventory, runner
    )
    # Tier 2: per-Oracle-home patch inventory (opatch lspatches).
    patch_records = _collect_db_patches(db_records, inventory, runner)
    # Tier 2: AWR workload intensity (DB Time/CPU/AAS/redo) + tablespace growth.
    workload_records, tablespace_records = _collect_db_workload(
        db_records, inventory, runner
    )

    write_os_csv(os_records, inventory.output_dir)
    write_os_json(os_records, inventory.output_dir)
    write_db_inventory_csv(db_records, inventory.output_dir)
    write_db_inventory_json(db_records, inventory.output_dir)
    write_db_resource_details_csv(db_records, inventory.output_dir)
    write_db_resource_details_json(db_records, inventory.output_dir)
    write_db_resource_details_errors_csv(db_records, inventory.output_dir)
    write_db_resource_details_errors_json(db_records, inventory.output_dir)
    diskgroup_records, metadata_records, failure_records = _partition_asm_records(
        asm_records
    )
    diskgroup_output_records = [*diskgroup_records, *failure_records]
    write_asm_diskgroups_csv(
        diskgroup_output_records,
        inventory.output_dir,
        include_debug=inventory.asm_include_debug,
    )
    write_asm_diskgroups_json(
        diskgroup_output_records,
        inventory.output_dir,
        include_debug=inventory.asm_include_debug,
    )
    write_asm_metadata_csv(metadata_records, inventory.output_dir)
    write_asm_metadata_json(metadata_records, inventory.output_dir)
    write_asm_summary_csv(diskgroup_records, inventory.output_dir)
    write_asm_summary_json(diskgroup_records, inventory.output_dir)
    write_hugepages_csv(hugepages_records, inventory.output_dir)
    write_hugepages_json(hugepages_records, inventory.output_dir)
    write_version_inventory_csv(version_records, inventory.output_dir)
    write_version_inventory_json(
        version_records, inventory.output_dir, include_debug=inventory.debug_enabled
    )
    write_version_summary_csv(version_records, inventory.output_dir)
    write_version_summary_json(version_records, inventory.output_dir)
    write_pdb_inventory_csv(pdb_records, inventory.output_dir)
    write_pdb_inventory_json(pdb_records, inventory.output_dir)
    write_feature_usage_csv(feature_records, inventory.output_dir)
    write_feature_usage_json(feature_records, inventory.output_dir)
    write_db_patch_inventory_csv(patch_records, inventory.output_dir)
    write_db_patch_inventory_json(patch_records, inventory.output_dir)
    write_db_workload_csv(workload_records, inventory.output_dir)
    write_db_workload_json(workload_records, inventory.output_dir)
    write_db_tablespace_growth_csv(tablespace_records, inventory.output_dir)
    write_db_tablespace_growth_json(tablespace_records, inventory.output_dir)
    write_db_performance_csv(db_performance_records, inventory.output_dir)
    write_db_performance_json(db_performance_records, inventory.output_dir)
    write_db_performance_errors_csv(db_performance_records, inventory.output_dir)
    write_db_performance_errors_json(db_performance_records, inventory.output_dir)
    write_db_memory_history_csv(db_memory_records, inventory.output_dir)
    write_db_memory_history_json(db_memory_records, inventory.output_dir)
    db_memory_warning_thresholds = {
        "sga_near_max_severity": inventory.db_memory_sga_near_max_severity,
        "sga_near_max_pct": inventory.db_memory_sga_near_max_pct,
        "pga_used_pct_target": inventory.db_memory_pga_used_pct_target,
        "pga_alloc_pct_target": inventory.db_memory_pga_alloc_pct_target,
    }
    write_db_memory_history_summary_csv(
        db_memory_records,
        inventory.output_dir,
        **db_memory_warning_thresholds,
    )
    write_db_memory_history_summary_json(
        db_memory_records,
        inventory.output_dir,
        **db_memory_warning_thresholds,
    )
    write_db_memory_cluster_summary_csv(db_memory_records, inventory.output_dir)
    write_db_memory_cluster_summary_json(db_memory_records, inventory.output_dir)
    write_db_memory_history_errors_csv(db_memory_records, inventory.output_dir)
    write_db_memory_history_errors_json(db_memory_records, inventory.output_dir)
    health_asm_records = [*diskgroup_records, *failure_records]
    health_rows = build_health_summary_rows(
        os_records,
        health_asm_records,
        hugepages_records,
        db_records,
        version_records,
        db_performance_records,
        db_memory_records,
    )
    write_health_summary_csv(
        os_records,
        health_asm_records,
        hugepages_records,
        db_records,
        inventory.output_dir,
        version_records,
        db_performance_records,
        db_memory_records,
    )
    write_health_summary_json(
        os_records,
        health_asm_records,
        hugepages_records,
        db_records,
        inventory.output_dir,
        version_records,
        db_performance_records,
        db_memory_records,
    )
    write_health_summary_html(
        os_records,
        health_asm_records,
        hugepages_records,
        db_records,
        inventory.output_dir,
        version_records,
        db_performance_records,
        db_memory_records,
    )
    _print_health_summary(health_rows)
    duration_seconds = round(time.perf_counter() - start_time, 2)
    LOGGER.info(
        "Summary: clusters_total=%s hosts_total=%s hosts_success=%s hosts_partial=%s hosts_failed=%s duration_seconds=%s",
        clusters_total,
        hosts_total,
        hosts_success,
        hosts_partial,
        hosts_failed,
        duration_seconds,
    )
    # Exit non-zero only when at least one host is truly unreachable (OS
    # collection failed). DB-level SQL warnings on individual databases are
    # surfaced via the health summary and do not fail the run as a whole.
    failures = [record for record in os_records if str(record.status).lower() == "failed"]
    return 2 if failures else 0


def _print_health_summary(rows: list[dict[str, object]]) -> None:
    counts = health_summary_counts(rows)
    print("Health Summary")
    print(f"CRITICAL count: {counts['CRITICAL']}")
    print(f"WARNING count: {counts['WARNING']}")
    print(f"OK count: {counts['OK']}")


def run_asm_only(
    inventory: Inventory, debug_ssh: bool = False, host_filter: str | None = None
) -> int:
    inventory.output_dir.mkdir(parents=True, exist_ok=True)
    inventory.logs_dir.mkdir(parents=True, exist_ok=True)
    runner = SSHRunner(logging.getLogger("ssh_runner"), debug_ssh=debug_ssh)
    asm_records = []
    for cluster in inventory.clusters:
        for host in cluster.hosts:
            if host_filter and host.name != host_filter:
                continue
            logger = host_logger(inventory.logs_dir, f"{cluster.name}_{host.name}")
            context = SharedHostContext(
                runner, logging.getLogger("collectors.shared_context")
            )
            asm_collector = ASMDiskgroupCollector(
                runner,
                context=context,
                logger=logging.getLogger("collectors.asm_diskgroups"),
            )
            host_rows = asm_collector.collect_host(
                cluster.name,
                host,
                logger,
                enabled=inventory.asm_enabled,
                timeout_seconds=inventory.asm_timeout_seconds,
            )
            asm_records.extend(host_rows)
            summary = host_rows[-1] if host_rows else None
            if summary:
                print(
                    f"[ASM-DEBUG] host={host.name} status={summary.asm_collection_status} "
                    f"grid_owner={summary.grid_owner} grid_home={summary.grid_home} asm_sid={summary.asm_sid} "
                    f"asmcmd_path={summary.asmcmd_path} asm_returncode={summary.asm_returncode} sqlplus_returncode={summary.sqlplus_returncode}"
                )
                print(f"[ASM-DEBUG] asm_command={summary.asm_command}")
                if summary.asm_collection_error:
                    print(
                        f"[ASM-DEBUG] asm_collection_error={summary.asm_collection_error}"
                    )
                if summary.asmcmd_stdout:
                    print(f"[ASM-DEBUG] asmcmd_stdout={summary.asmcmd_stdout}")
                if summary.asmcmd_stderr:
                    print(f"[ASM-DEBUG] asmcmd_stderr={summary.asmcmd_stderr}")
                if summary.sqlplus_stdout:
                    print(f"[ASM-DEBUG] sqlplus_stdout={summary.sqlplus_stdout}")
                if summary.sqlplus_stderr:
                    print(f"[ASM-DEBUG] sqlplus_stderr={summary.sqlplus_stderr}")
    diskgroup_records, metadata_records, failure_records = _partition_asm_records(
        asm_records
    )
    diskgroup_output_records = [*diskgroup_records, *failure_records]
    write_asm_diskgroups_csv(
        diskgroup_output_records,
        inventory.output_dir,
        include_debug=inventory.asm_include_debug,
    )
    write_asm_diskgroups_json(
        diskgroup_output_records,
        inventory.output_dir,
        include_debug=inventory.asm_include_debug,
    )
    write_asm_metadata_csv(metadata_records, inventory.output_dir)
    write_asm_metadata_json(metadata_records, inventory.output_dir)
    write_asm_summary_csv(diskgroup_records, inventory.output_dir)
    write_asm_summary_json(diskgroup_records, inventory.output_dir)
    return 0


def _collect_cluster_parallel(cluster, inventory: Inventory, runner: SSHRunner):
    os_records = []
    db_records = []
    asm_records = []
    hugepages_records = []
    version_records = []
    db_performance_records = []
    db_memory_records = []
    success = 0
    partial = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=inventory.max_hosts_per_cluster) as host_pool:
        host_futures = {}
        for host in cluster.hosts:
            LOGGER.info("Starting host %s", host.name)
            future = host_pool.submit(
                _collect_host, cluster, host, runner, inventory.logs_dir, inventory
            )
            host_futures[future] = host
        for future, host in host_futures.items():
            # Each collector enforces its own per-command timeout. This
            # orchestrator-level deadline is sized generously over the sum of
            # the per-collector timeouts so it only fires as a last-resort
            # safety net. This prevents the host being marked failed at the
            # orchestrator while the worker thread is still running and the
            # underlying collectors continue to complete.
            worker_deadline = _host_worker_deadline_seconds(host, inventory)
            try:
                collected = future.result(timeout=worker_deadline)
                os_record = collected.os_record
                db_record = collected.db_record
                host_asm_records = collected.asm_records
                hugepages_record = collected.hugepages_record
                version_record = collected.version_record
                host_db_performance = collected.db_performance_records
                host_db_memory = collected.db_memory_records
                os_records.append(os_record)
                db_records.append(db_record)
                asm_records.extend(host_asm_records)
                hugepages_records.append(hugepages_record)
                version_records.append(version_record)
                db_performance_records.extend(host_db_performance)
                db_memory_records.extend(host_db_memory)
                host_status = _compute_host_status(
                    os_record,
                    db_record,
                    host_asm_records,
                    hugepages_record,
                    version_record,
                )
                outcome_detail = _summarize_collector_outcomes(
                    os_record,
                    db_record,
                    host_asm_records,
                    hugepages_record,
                    version_record,
                )
                if host_status == HOST_STATUS_SUCCESS:
                    success += 1
                    LOGGER.info(
                        "Completed host %s status=success %s",
                        host.name,
                        outcome_detail,
                    )
                elif host_status == HOST_STATUS_PARTIAL:
                    partial += 1
                    LOGGER.warning(
                        "Completed host %s status=partial_success %s",
                        host.name,
                        outcome_detail,
                    )
                else:
                    failed += 1
                    LOGGER.error(
                        "Failed host %s status=failed %s",
                        host.name,
                        outcome_detail,
                    )
            except TimeoutError:
                failed += 1
                LOGGER.error(
                    "Failed host %s status=failed reason=worker_timeout deadline_seconds=%s; remaining collector results may exist in the per-host log but were not aggregated",
                    host.name,
                    worker_deadline,
                )
                os_rec, db_rec, hp_rec, ver_rec = _failure_records_for(
                    cluster.name,
                    host,
                    f"Host worker timed out after {worker_deadline} seconds",
                )
                os_records.append(os_rec)
                db_records.append(db_rec)
                hugepages_records.append(hp_rec)
                version_records.append(ver_rec)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                LOGGER.exception("Failed host %s status=failed", host.name)
                os_rec, db_rec, hp_rec, ver_rec = _failure_records_for(
                    cluster.name, host, str(exc)
                )
                os_records.append(os_rec)
                db_records.append(db_rec)
                hugepages_records.append(hp_rec)
                version_records.append(ver_rec)
    # Collect memory once per db_unique_name across this cluster, not per host.
    db_memory_records.extend(
        DBPerformanceCollector(
            runner, logger=logging.getLogger("collectors.db_performance")
        ).collect_cluster_memory_history(
            db_records,
            {host.name: host for host in cluster.hosts},
            enabled=inventory.db_performance_enabled
            and inventory.db_performance_collect_memory_history,
            use_awr=inventory.db_performance_use_awr,
            days_back=inventory.db_performance_days_back,
            timeout_seconds=inventory.db_performance_timeout_seconds,
        )
    )
    return (
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
    )


def resolve_default_config_path() -> str:
    local_path = Path("config/clusters.local.yaml")
    if local_path.exists():
        return str(local_path)
    return "config/clusters.example.yaml"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = args.config or resolve_default_config_path()
    try:
        inventory = load_inventory(config_path)
        if args.max_clusters is not None:
            if args.max_clusters < 1:
                raise ValueError("--max-clusters must be >= 1")
            inventory = replace(inventory, max_clusters=args.max_clusters)
        if args.max_hosts_per_cluster is not None:
            if args.max_hosts_per_cluster < 1:
                raise ValueError("--max-hosts-per-cluster must be >= 1")
            inventory = replace(
                inventory, max_hosts_per_cluster=args.max_hosts_per_cluster
            )
        configure_logging(inventory.logs_dir, args.verbose)
        if args.show_inventory:
            return show_inventory(inventory)
        if args.preflight:
            return preflight(inventory, debug_ssh=args.debug_ssh)
        if args.collector == "asm":
            return run_asm_only(
                inventory, debug_ssh=args.debug_ssh, host_filter=args.host
            )
        return run(inventory, debug_ssh=args.debug_ssh)
    except Exception as exc:
        logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")
        logging.getLogger(__name__).exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
