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
