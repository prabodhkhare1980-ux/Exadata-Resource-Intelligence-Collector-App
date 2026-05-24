"""Command-line entry point for Exadata Resource Intelligence Collector."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import datetime, timezone
from pathlib import Path

from collectors.db_inventory_collector import DBInventoryCollector, DBInventoryRecord
from collectors.asm_diskgroups_collector import ASMDiskgroupCollector, ASMDiskgroupRecord
from collectors.os_collector import OSCollectionRecord, OSCollector
from collectors.shared_context import SharedHostContext
from inventory import Inventory, load_inventory
from logging_setup import configure_logging, host_logger
from reports.writers import write_asm_diskgroups_csv, write_asm_diskgroups_json, write_db_inventory_csv, write_db_inventory_json, write_os_csv, write_os_json
from ssh_runner import SSHRunner

LOGGER = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Phase 1 OS capacity intelligence from Exadata/RAC nodes.")
    parser.add_argument("--config", default=None, help="Path to YAML inventory file. Default: config/clusters.local.yaml (if present) else config/clusters.example.yaml")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose DEBUG logging.")
    parser.add_argument("--show-inventory", action="store_true", help="Print resolved inventory details for each host and exit.")
    parser.add_argument("--preflight", action="store_true", help="Run SSH key/sudo preflight checks for each host.")
    parser.add_argument("--debug-ssh", action="store_true", help="Print sanitized SSH command plus first 500 chars of stdout/stderr.")
    parser.add_argument("--max-clusters", type=int, help="Override collection.parallel.max_clusters")
    parser.add_argument("--max-hosts-per-cluster", type=int, help="Override collection.parallel.max_hosts_per_cluster")
    parser.add_argument("--collector", choices=["all", "asm"], default="all", help="Run all collectors (default) or a single collector.")
    parser.add_argument("--host", default=None, help="Host name filter, used with --collector asm for standalone ASM test mode.")
    return parser.parse_args(argv)


def show_inventory(inventory: Inventory) -> int:
    print("cluster,environment,host,address,resolved_ssh_user,auth_method,private_key,privilege_method,sudo_password")
    for cluster in inventory.clusters:
        for host in cluster.hosts:
            print(f"{cluster.name},{cluster.environment},{host.name},{host.address},{host.user},{host.auth_method},{host.private_key or ''},{host.privilege_method},{host.sudo_password_mode}")
    return 0


def preflight(inventory: Inventory, debug_ssh: bool = False) -> int:
    runner = SSHRunner(logging.getLogger("ssh_runner"), debug_ssh=debug_ssh)
    inventory.output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    failures = 0
    for cluster in inventory.clusters:
        for host in cluster.hosts:
            key_exists = bool(host.private_key and Path(host.private_key).exists())
            key_readable = bool(host.private_key and Path(host.private_key).is_file() and Path(host.private_key).stat().st_mode)
            ssh_result = runner.run_command(host, "hostname")
            sudo_host = runner.run_command(host, "sudo -n hostname")
            sudo_whoami = runner.run_command(host, "sudo -n whoami")
            if host.sudo_password_mode == "none" and not sudo_host.ok:
                sudo_error = "sudo -n failed; configure NOPASSWD sudo for service account"
            else:
                sudo_error = ""
            status = "PASS" if key_exists and key_readable and ssh_result.ok and sudo_host.ok and sudo_whoami.ok else "FAIL"
            if status != "PASS":
                failures += 1
            rows.append({
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
                "sudo_n_whoami": (sudo_whoami.stdout.strip() if sudo_whoami.ok else ""),
                "status": status,
                "error": sudo_error or ssh_result.error or ssh_result.stderr.strip() or sudo_host.stderr.strip(),
            })
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


def _print_preflight_report(rows: list[dict[str, str]], csv_path: Path, json_path: Path) -> None:
    print("\nPreflight Report")
    print("=" * 110)
    print(f"{'Status':<8} {'Environment':<12} {'Cluster':<20} {'Host':<20} {'SSH':<6} {'sudo -n':<8} Error")
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

def _collect_host(cluster, host, runner, logs_dir, inventory):
    logger = host_logger(logs_dir, f"{cluster.name}_{host.name}")
    context = SharedHostContext(runner, logging.getLogger("collectors.shared_context"))
    os_collector = OSCollector(runner, context=context, logger=logging.getLogger("collectors.os"))
    db_collector = DBInventoryCollector(runner, context=context, logger=logging.getLogger("collectors.db_inventory"))
    os_record = os_collector.collect_host(cluster.name, host, logger)
    db_record = db_collector.collect_host(cluster.name, host, logger)
    asm_collector = ASMDiskgroupCollector(runner, context=context, logger=logging.getLogger("collectors.asm_diskgroups"))
    try:
        asm_records = asm_collector.collect_host(cluster.name, host, logger, enabled=inventory.asm_enabled, timeout_seconds=inventory.asm_timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ASM collection skipped/failed for %s", host.name)
        if inventory.asm_fail_host_on_error:
            raise
        asm_records = [ASMDiskgroupRecord(cluster=cluster.name, host=host.name, address=host.address, asm_collection_status="failed", warning_level="ERROR")]
    return os_record, db_record, asm_records


def run(inventory: Inventory, debug_ssh: bool = False) -> int:
    inventory.output_dir.mkdir(parents=True, exist_ok=True)
    inventory.logs_dir.mkdir(parents=True, exist_ok=True)
    runner = SSHRunner(logging.getLogger("ssh_runner"), debug_ssh=debug_ssh)
    os_records = []
    db_records = []
    asm_records = []
    clusters_total = len(inventory.clusters)
    hosts_total = sum(len(cluster.hosts) for cluster in inventory.clusters)
    hosts_success = 0
    hosts_failed = 0
    start_time = time.perf_counter()

    if not inventory.parallel_enabled:
        for cluster in inventory.clusters:
            LOGGER.info("Starting cluster %s", cluster.name)
            for host in cluster.hosts:
                LOGGER.info("Starting host %s", host.name)
                os_record, db_record, host_asm_records = _collect_host(cluster, host, runner, inventory.logs_dir, inventory)
                os_records.append(os_record)
                db_records.append(db_record)
                asm_records.extend(host_asm_records)
                if os_record.status == "ok" and db_record.status == "ok":
                    hosts_success += 1
                    LOGGER.info("Completed host %s", host.name)
                else:
                    hosts_failed += 1
                    LOGGER.error("Failed host %s", host.name)
    else:
        with ThreadPoolExecutor(max_workers=inventory.max_clusters) as cluster_pool:
            cluster_futures = {}
            for cluster in inventory.clusters:
                LOGGER.info("Starting cluster %s", cluster.name)
                future = cluster_pool.submit(_collect_cluster_parallel, cluster, inventory, runner)
                cluster_futures[future] = cluster.name
            for future in as_completed(cluster_futures):
                cluster_name = cluster_futures[future]
                try:
                    cluster_os, cluster_db, cluster_asm, cluster_success, cluster_failed = future.result()
                    os_records.extend(cluster_os)
                    db_records.extend(cluster_db)
                    asm_records.extend(cluster_asm)
                    hosts_success += cluster_success
                    hosts_failed += cluster_failed
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Cluster execution failed for %s: %s", cluster_name, exc)
    write_os_csv(os_records, inventory.output_dir)
    write_os_json(os_records, inventory.output_dir)
    write_db_inventory_csv(db_records, inventory.output_dir)
    write_db_inventory_json(db_records, inventory.output_dir)
    write_asm_diskgroups_csv(asm_records, inventory.output_dir)
    write_asm_diskgroups_json(asm_records, inventory.output_dir)
    duration_seconds = round(time.perf_counter() - start_time, 2)
    LOGGER.info(
        "Summary: clusters_total=%s hosts_total=%s hosts_success=%s hosts_failed=%s duration_seconds=%s",
        clusters_total,
        hosts_total,
        hosts_success,
        hosts_failed,
        duration_seconds,
    )
    failures = [record for record in os_records if record.status != "ok"] + [record for record in db_records if record.status != "ok"]
    return 2 if failures else 0


def run_asm_only(inventory: Inventory, debug_ssh: bool = False, host_filter: str | None = None) -> int:
    inventory.output_dir.mkdir(parents=True, exist_ok=True)
    inventory.logs_dir.mkdir(parents=True, exist_ok=True)
    runner = SSHRunner(logging.getLogger("ssh_runner"), debug_ssh=debug_ssh)
    asm_records = []
    for cluster in inventory.clusters:
        for host in cluster.hosts:
            if host_filter and host.name != host_filter:
                continue
            logger = host_logger(inventory.logs_dir, f"{cluster.name}_{host.name}")
            context = SharedHostContext(runner, logging.getLogger("collectors.shared_context"))
            asm_collector = ASMDiskgroupCollector(runner, context=context, logger=logging.getLogger("collectors.asm_diskgroups"))
            asm_records.extend(
                asm_collector.collect_host(cluster.name, host, logger, enabled=inventory.asm_enabled, timeout_seconds=inventory.asm_timeout_seconds)
            )
    write_asm_diskgroups_csv(asm_records, inventory.output_dir)
    write_asm_diskgroups_json(asm_records, inventory.output_dir)
    return 0


def _collect_cluster_parallel(cluster, inventory: Inventory, runner: SSHRunner):
    os_records = []
    db_records = []
    asm_records = []
    success = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=inventory.max_hosts_per_cluster) as host_pool:
        host_futures = {}
        for host in cluster.hosts:
            LOGGER.info("Starting host %s", host.name)
            future = host_pool.submit(_collect_host, cluster, host, runner, inventory.logs_dir, inventory)
            host_futures[future] = host
        for future, host in host_futures.items():
            timeout_seconds = max(host.timeout_seconds, 1) * 2
            try:
                os_record, db_record, host_asm_records = future.result(timeout=timeout_seconds)
                os_records.append(os_record)
                db_records.append(db_record)
                asm_records.extend(host_asm_records)
                if os_record.status == "ok" and db_record.status == "ok":
                    success += 1
                    LOGGER.info("Completed host %s", host.name)
                else:
                    failed += 1
                    LOGGER.error("Failed host %s", host.name)
            except TimeoutError:
                failed += 1
                LOGGER.error("Failed host %s", host.name)
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                os_records.append(OSCollectionRecord(cluster=cluster.name, host=host.name, address=host.address, collected_at=now, status="failed", error=f"Host timed out after {timeout_seconds} seconds"))
                db_records.append(DBInventoryRecord(cluster=cluster.name, host=host.name, address=host.address, collected_at=now, status="failed", error=f"Host timed out after {timeout_seconds} seconds"))
            except Exception as exc:  # noqa: BLE001
                failed += 1
                LOGGER.exception("Failed host %s", host.name)
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                os_records.append(OSCollectionRecord(cluster=cluster.name, host=host.name, address=host.address, collected_at=now, status="failed", error=str(exc)))
                db_records.append(DBInventoryRecord(cluster=cluster.name, host=host.name, address=host.address, collected_at=now, status="failed", error=str(exc)))
    return os_records, db_records, asm_records, success, failed



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
            inventory = Inventory(
                clusters=inventory.clusters,
                output_dir=inventory.output_dir,
                logs_dir=inventory.logs_dir,
                parallel_enabled=inventory.parallel_enabled,
                max_clusters=args.max_clusters,
                max_hosts_per_cluster=inventory.max_hosts_per_cluster,
                asm_enabled=inventory.asm_enabled,
                asm_timeout_seconds=inventory.asm_timeout_seconds,
                asm_fail_host_on_error=inventory.asm_fail_host_on_error,
            )
        if args.max_hosts_per_cluster is not None:
            if args.max_hosts_per_cluster < 1:
                raise ValueError("--max-hosts-per-cluster must be >= 1")
            inventory = Inventory(
                clusters=inventory.clusters,
                output_dir=inventory.output_dir,
                logs_dir=inventory.logs_dir,
                parallel_enabled=inventory.parallel_enabled,
                max_clusters=inventory.max_clusters,
                max_hosts_per_cluster=args.max_hosts_per_cluster,
                asm_enabled=inventory.asm_enabled,
                asm_timeout_seconds=inventory.asm_timeout_seconds,
                asm_fail_host_on_error=inventory.asm_fail_host_on_error,
            )
        configure_logging(inventory.logs_dir, args.verbose)
        if args.show_inventory:
            return show_inventory(inventory)
        if args.preflight:
            return preflight(inventory, debug_ssh=args.debug_ssh)
        if args.collector == "asm":
            return run_asm_only(inventory, debug_ssh=args.debug_ssh, host_filter=args.host)
        return run(inventory, debug_ssh=args.debug_ssh)
    except Exception as exc:
        logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")
        logging.getLogger(__name__).exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
