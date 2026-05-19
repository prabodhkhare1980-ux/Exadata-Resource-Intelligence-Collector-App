"""Command-line entry point for Exadata Resource Intelligence Collector."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from collectors.db_inventory_collector import DBInventoryCollector
from collectors.os_collector import OSCollector
from inventory import Inventory, load_inventory
from logging_setup import configure_logging, host_logger
from reports.writers import write_db_inventory_csv, write_db_inventory_json, write_os_csv, write_os_json
from ssh_runner import SSHRunner

LOGGER = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Phase 1 OS capacity intelligence from Exadata/RAC nodes.")
    parser.add_argument("--config", default="config/clusters.yaml", help="Path to YAML inventory file. Default: config/clusters.yaml")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose DEBUG logging.")
    parser.add_argument("--show-inventory", action="store_true", help="Print resolved inventory details for each host and exit.")
    parser.add_argument("--preflight", action="store_true", help="Run SSH key/sudo preflight checks for each host.")
    parser.add_argument("--debug-ssh", action="store_true", help="Print sanitized SSH command plus first 500 chars of stdout/stderr.")
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

def run(inventory: Inventory, debug_ssh: bool = False) -> int:
    inventory.output_dir.mkdir(parents=True, exist_ok=True)
    inventory.logs_dir.mkdir(parents=True, exist_ok=True)
    runner = SSHRunner(logging.getLogger("ssh_runner"), debug_ssh=debug_ssh)
    os_collector = OSCollector(runner, logging.getLogger("collectors.os"))
    db_collector = DBInventoryCollector(runner, logging.getLogger("collectors.db_inventory"))
    os_records = []
    db_records = []
    for cluster in inventory.clusters:
        host_loggers = {host.name: host_logger(inventory.logs_dir, f"{cluster.name}_{host.name}") for host in cluster.hosts}
        os_records.extend(os_collector.collect_cluster(cluster, host_loggers))
        db_records.extend(db_collector.collect_cluster(cluster, host_loggers))
    write_os_csv(os_records, inventory.output_dir)
    write_os_json(os_records, inventory.output_dir)
    write_db_inventory_csv(db_records, inventory.output_dir)
    write_db_inventory_json(db_records, inventory.output_dir)
    failures = [record for record in os_records if record.status != "ok"] + [record for record in db_records if record.status != "ok"]
    return 2 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        inventory = load_inventory(args.config)
        configure_logging(inventory.logs_dir, args.verbose)
        if args.show_inventory:
            return show_inventory(inventory)
        if args.preflight:
            return preflight(inventory, debug_ssh=args.debug_ssh)
        return run(inventory, debug_ssh=args.debug_ssh)
    except Exception as exc:
        logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")
        logging.getLogger(__name__).exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
