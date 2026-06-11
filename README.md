# Exadata Resource Intelligence Collector

Phase 1 collector for Exadata/RAC using SSH stdin execution only.

## Authentication model (updated)

- Service account: `srcordma`
- SSH key auth: `auth.method: ssh_key`
- Key path: `.secrets/ssh/srcordma_id_rsa`
- No SSH password prompt when using SSH key auth.
- Privilege escalation uses `sudo -n` when `sudo_password: none`.
- If `sudo -n` fails, preflight reports a clear NOPASSWD sudo error.

## Security

- Private keys can exist locally under project folder.
- Private keys must never be committed.
- `.gitignore` includes:
  - `.secrets/`
  - `*.pem`
  - `*_id_rsa`
  - `*_id_ed25519`
- Key contents are never printed.

## Setup

1. Copy the template inventory to a local-only file:
   ```bash
   cp config/clusters.example.yaml config/clusters.local.yaml
   ```
2. Edit `config/clusters.local.yaml` with your real cluster/host inventory.
3. Keep private keys under `.secrets/` (for example: `.secrets/ssh/srcordma_id_rsa`).
4. Run the collector (it loads `config/clusters.local.yaml` automatically when present, otherwise it falls back to `config/clusters.example.yaml`).

## Usage

```bash
python main.py --show-inventory
python main.py --preflight
python main.py
```

## Preflight checks

Per host preflight validates:
1. SSH key exists
2. SSH key is readable
3. SSH login (`ssh -i <key> srcordma@host hostname`)
4. sudo non-interactive (`ssh -i <key> srcordma@host "sudo -n hostname"`)
5. Effective user (`ssh -i <key> srcordma@host "sudo -n whoami"`)

Preflight writes:

- `output/preflight_report.csv`
- `output/preflight_report.json`

No scripts are copied to targets and no remote temp files are created.

## Phase 2 Output Normalization

- SSH collection uses non-interactive mode (`ssh -T`) and `sudo -n bash -s` for remote execution.
- Remote script bootstrap sets `TERM=dumb`, `LANG=C`, `LC_ALL=C`, unsets prompt command, blanks `PS1`, and disables echo where possible.
- Section markers are normalized to `===SECTION:<name>===` and parsing reads only content under active section markers.
- ANSI cleanup removes control sequences (`CSI` and `OSC`), shell prompt lines, carriage returns, and repeated blank lines before parsing.
- Grid environment auto-detection reads `/etc/oratab` (`+ASM`/`-MGMTDB`) to infer `grid_home`, then exports `ORACLE_HOME` and `PATH` before checking `crsctl`/`srvctl`.
- Normalized host JSON output is written to `output/json/normalized_hosts.json`.
- Additional CSV outputs are written: `filesystem_usage.csv`, `hugepages.csv`, `cpu_inventory.csv`, and `db_inventory.csv`.

## TTY-aware sudo execution

- OCI mode should keep `privilege.force_tty: false` so SSH runs with `-T` and retains clean non-interactive output.
- On-prem mode can set `privilege.force_tty: true` so SSH runs with `-tt` for sudo policies that require a TTY.
- In TTY mode, shell prompt/echo/control noise is cleaned before parsing, and parser accepts only content between `===BEGIN_SECTION:<name>===` and `===END_SECTION:<name>===` markers.

## License & capacity collectors (Tier 2)

These deepen inventory, license posture, and capacity assessment. Each runs as
a post-pass over the DB inventory (or once per cluster for cell inventory) and
writes both `.csv` and `.json` under `output/`.

| Output | Source | Diagnostics Pack? | Purpose |
| --- | --- | --- | --- |
| `pdb_inventory` | `v$pdbs` + `cdb_data_files` | No | Per-PDB open mode, restricted, size — Multitenant license posture |
| `db_feature_usage` | `dba_feature_usage_statistics` | No | Currently-used options/features (Partitioning, ACO, RAT, In-Memory, ADG) |
| `db_patch_inventory` | `opatch lspatches` per Oracle home | No | DB-home + Grid-home patch level; catches homes drifting from baseline |
| `db_workload` | `dba_hist_sys_time_model`, `dba_hist_sysstat` | Yes | Per-snapshot DB Time, DB CPU, AAS, redo MB/s — workload intensity |
| `db_tablespace_growth` | `dba_hist_tbspc_space_usage` | Yes | Per-tablespace allocated/used GB over time — days-to-full substrate |
| `cell_inventory` (+ `cell_inventory_errors`) | dcli / direct-SSH / ExaCLI → `cellcli`/`exacli ... list ... detail` | No | Per-cell image, release, model, status, flash cache, hard/flash disk capacity & counts |

Configure under `collection.` with these blocks (all default-enabled): `db_capacity`,
`db_patch`, `db_workload`, `cell_inventory`. AWR-based collectors honour the existing
`db_performance.use_awr` / `days_back` settings.

### Cell inventory access models

Storage cells are reached differently per estate, selected by each environment's
`cell_access.method`:

| Method | Where | How |
| --- | --- | --- |
| `dcli_or_direct` | On-prem | Use `dcli -g <cell_group> -l <user>` **only** with a proper one-host-per-line group file; `cellip.ora` (lines of `cell="ip;ip"`) is parsed into one cell per line and each is reached by direct SSH (`sudo -n ssh <user>@<cell>`) to one of its two redundant IPs |
| `direct_ssh` | On-prem | Always SSH to each discovered cell and run `cellcli` |
| `exacli` | OCI ExaCS | From the DB VM, resolve the cluster name via `crsctl get cluster name`, build the `cloud_user_<clustername>` storage user, read cell IPs from `cellip.ora`, and run `exacli -l <user> -c <ip> --cookie-jar -n -e "..."` |

The cell access **method is inferred from the environment name** when not
explicitly set: environments named/described with `oci`, `exacs`, or
`exadata cloud` default to `exacli`; everything else defaults to
`dcli_or_direct`. `cell_access.method:` still wins when present.

### OCI ExaCS prerequisites

Per Oracle's documented flow ([Using ExaCLI](https://docs.oracle.com/en-us/iaas/exadatacloud/doc/ecs-using-excli.html)),
the collector never stores or prompts for a password. Before the first run:

1. On each OCI DB VM, confirm `exacli` is on `PATH` (`command -v exacli`).
2. Confirm `/etc/oracle/cell/network-config/cellip.ora` exists and is readable
   by the SSH service account.
3. **Run an initial exacli login once** as that service account so the
   per-user cookie jar is created — pick any cell IP from `cellip.ora` and the
   cluster's `cloud_user_<clustername>`:

   ```bash
   exacli -l cloud_user_$(crsctl get cluster name | awk -F'is ' '{print $2}') \
          -c <one_cell_ip> --cookie-jar
   ```
   The collector then runs the same `exacli ... --cookie-jar -n -e "..."`
   non-interactively, reusing that cookie. Until the cookie exists you will
   see `error_category=EXACLI_AUTH_REQUIRED` and no cell is queried.

For the on-prem methods each cell/command is retried across `cell_access.users`
(e.g. `root` then `celladmin`) until one succeeds. ExaCLI uses an existing cookie
jar — when none exists the row is flagged `EXACLI_AUTH_REQUIRED` with guidance to run
the initial `exacli` login manually (no passwords are stored or prompted). Successful
cells go to `cell_inventory.{csv,json}`; unreachable cells go to
`cell_inventory_errors.{csv,json}` with the actual stderr captured and a precise
`error_category` (`DCLI_NOT_FOUND`, `CELL_AUTH`, `EXACLI_NOT_FOUND`,
`EXACLI_AUTH_REQUIRED`, `CELL_IP_FILE_NOT_FOUND`, `CELL_COMMAND_FAILED`, `PARSE_ERROR`).
The dashboard's **Cell Inventory** page summarises cells/version/capacity by cluster
and lists failed access. No scripts are copied to targets and no credentials are stored.

To test cell collection on its own (without running the full pipeline), use the
diagnostic driver — it prints a per-cell summary (target / method / user / status /
error category / captured stderr) and writes the same `cell_inventory*.{csv,json}`:

```bash
python -m scripts.run_cell_inventory --config config/clusters.local.yaml
python -m scripts.run_cell_inventory --config config/clusters.local.yaml --cluster onprem-rac01 --verbose
python -m scripts.run_cell_inventory --config config/clusters.local.yaml --no-write   # print only
```

Note: `output/cell_inventory.{csv,json}` contains **successful cells only** — if it is
empty (header row only), every cell failed and the reason is in
`output/cell_inventory_errors.{csv,json}` (and in the driver's summary).

## Oracle inventory mapping rules

- Use `srvctl config database` as authoritative input for database names (`db_unique_name`).
- Use PMON only as runtime instance evidence from `ps -eo user,pid,ppid,lstart,cmd | awk '/[o]ra_pmon_/ {print $0}'`.
- Never pass raw PMON SID values directly to `srvctl ... -d`.
- Optional fallback is controlled by `oracle_inventory.allow_pmon_sid_fallback`.

## Dashboard usage

The Phase 1 dashboard is a local-only Streamlit app that reads existing collector output files from `output/`. It does not connect to Exadata hosts, run SSH commands, or change collector behavior.

Install the dashboard dependencies:

```bash
pip install -r requirements.txt
```

Run the dashboard from the repository root:

```bash
streamlit run app.py
```

Available dashboard pages, grouped in the sidebar:

**Overview**
1. Executive Cockpit — cluster/host KPIs, action-required items, data freshness

**Capacity**
2. ASM Capacity
3. HugePages

**Inventory**
4. Host Inventory
5. Version Inventory
6. DB Inventory

**Performance**
7. DB Performance
8. CPU Analytics
9. IOPS Analytics

**Memory**
10. DB Memory History
11. Memory Analytics

**Explore**
12. Raw Data Explorer — browse any JSON/CSV in `output/`

Generate collector output first with `python main.py` so the dashboard can load files such as `health_summary.json`, `asm_diskgroups.json`, `hugepages.json`, `os_inventory.json`, `db_inventory.json`, `version_inventory.json`, `db_performance.json`, and `db_memory_history.json` from `output/`.


## DB Performance and Memory History outputs

The DB performance collector uses AWR views (`DBA_HIST_SYSMETRIC_SUMMARY`, `DBA_HIST_SNAPSHOT`, `DBA_HIST_PARAMETER`, `DBA_HIST_SGASTAT`, and `DBA_HIST_PGASTAT`). Enabling this collector requires Oracle Diagnostics Pack/AWR licensing for the databases being queried. Review licensing before setting `collection.db_performance.enabled: true` and `collection.db_performance.use_awr: true`.

Example configuration:

```yaml
collection:
  db_performance:
    enabled: true
    use_awr: true
    days_back: 7
    timeout_seconds: 90
    collect_cpu_iops: true
    collect_memory_history: true
  db_memory_history:
    warning_thresholds:
      sga_near_max_severity: info
      sga_near_max_pct: 98
      pga_used_pct_target: 80
      pga_alloc_pct_target: 100
```

Outputs:

- `output/db_performance.csv` and `output/db_performance.json` contain successful AWR CPU, IOPS, and throughput history rows only.
- `output/db_performance_errors.csv` and `output/db_performance_errors.json` contain failed DB performance collection attempts with SQL stdout/stderr diagnostics.
- `output/db_memory_history.csv` and `output/db_memory_history.json` contain successful AWR SGA/PGA memory history rows only.
- `output/db_memory_history_errors.csv` and `output/db_memory_history_errors.json` contain failed DB memory history collection attempts with SQL stdout/stderr diagnostics.
- `output/db_memory_history_summary.csv` and `output/db_memory_history_summary.json` roll history up per database instance and use a non-overlapping warning model. `info_warnings`, `warning_warnings`, and `critical_warnings` contain unique, sorted, semicolon-separated codes assigned to exactly one severity. The backward-compatible `warnings` field is the unique, sorted union of those three fields; `warning_count` counts that union, and `warning_severity` reports the highest populated severity (`CRITICAL`, `WARNING`, `INFO`, or `OK`).

DB memory summary warning mapping:

| Severity | Warning codes |
| --- | --- |
| INFO | `AMM_OR_MANUAL_SGA`, `SGA_TARGET_ZERO`, `PGA_LIMIT_ZERO`, `SGA_USED_OVER_90_PCT`, and normally `SGA_NEAR_MAX` |
| WARNING | `PGA_USED_OVER_TARGET`; `SGA_NEAR_MAX` only with limited growth headroom |
| CRITICAL | `PGA_ALLOC_OVER_TARGET`, `SGA_USED_OVER_MAX_SIZE` |

`PGA_USED_OVER_TARGET` uses `pga_used_pct_target` (inclusive), and `PGA_ALLOC_OVER_TARGET` requires allocation above both the target and configured percentage threshold. `SGA_NEAR_MAX` uses `sga_near_max_pct` (inclusive) and defaults to `sga_near_max_severity: info`; it escalates to WARNING only when `sga_target_gb_max` is below `sga_max_size_gb_max` and `sga_growth_headroom_gb` is at most 1 GB. The former overlapping `capacity_warnings`, `configuration_warnings`, `operational_warnings`, and `informational_warnings` columns are no longer generated.

SQL is streamed inline through the existing SSH runner to `sqlplus -s / as sysdba`; no SQL files are copied and no remote temp SQL files are created. The collector reuses DB inventory/resource-detail discovery to select each local running `oracle_sid` and `oracle_home`.

## DB Resource Details output

The DB resource details collector writes dashboard-ready SQL collection output to separate success and diagnostic files:

- `output/db_resource_details.csv` and `output/db_resource_details.json` contain only rows where `collection_status=success`.
- `output/db_resource_details_errors.csv` and `output/db_resource_details_errors.json` contain skipped and failed rows, including SQL diagnostics such as `error_category`, `sql_returncode`, `sql_stdout`, and `sql_stderr`.
- Successful CSV rows use clean dashboard columns and do not include duplicate `Cluster`/`cluster` fields.
- Successful JSON rows use lowercase canonical field names such as `cluster`, `db_unique_name`, `db_size_gb`, `used_db_size_gb`, and `db_used_pct`.
- `DB_USED_PCT` / `db_used_pct` is calculated as `USED_DB_SIZE_GB / DB_SIZE_GB * 100` and rounded to two decimals. It is blank when `DB_SIZE_GB` is blank or zero.

SQL collection is streamed inline over SSH through stdin execution. No SQL files or scripts are copied to target servers, and no remote temp scripts are created.

Database size source values:

- `cdb` uses `cdb_data_files` and `cdb_segments`.
- `dba_fallback` uses `dba_data_files` and `dba_segments` after CDB-view fallback.
