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
