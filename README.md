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
6. `output/preflight_report.csv`
7. `output/preflight_report.json`

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

Available dashboard tabs:

1. Executive Health
2. Host Inventory
3. ASM Capacity
4. HugePages
5. DB Inventory
6. Version Inventory
7. Raw Data Explorer

Generate collector output first with `python main.py` so the dashboard can load files such as `health_summary.json`, `asm_diskgroups.json`, `hugepages.json`, `os_inventory.json`, `db_inventory.json`, and `version_inventory.json` from `output/`.

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
