# Exadata Resource Intelligence Collector

## Project Goals

Build a Python-based Exadata infrastructure intelligence and capacity collection system.

The root tree is the canonical implementation for now:

- `main.py`
- `inventory.py`
- `ssh_runner.py`
- `collectors/`
- `reports/writers.py`
- `app.py`

The previous Phase 1 implementation under `src/exadata_ric/` has been retired. A future
migration of the canonical modules into a package layout may happen later, but must not be
combined with current collector or dashboard stabilization work.

## Authentication Design (Current)

- Service account authentication uses `srcordma`.
- SSH key authentication is required and supported with `auth.method: ssh_key`.
- SSH private key path is configured with `auth.private_key` (recommended local-only path: `.secrets/ssh/srcordma_id_rsa`).
- Password prompts are not used when `auth.method=ssh_key`.
- `ssh_user` remains overridable at environment, cluster, and host scope with most-specific precedence.

## Security Rules

- SSH private keys may exist locally under the project folder.
- SSH private keys must NEVER be committed to GitHub.
- `.gitignore` must include `.secrets/`, `*.pem`, `*_id_rsa`, and `*_id_ed25519`.
- Never print private key contents.
- Never log secrets.

## Privilege Model

- For `privilege.method: sudo` and `sudo_password: none`, execute commands with `sudo -n`.
- Do not use `sudo -S` in `sudo_password: none` mode.
- If `sudo -n` fails, surface a clear error indicating NOPASSWD sudo must be configured.

## Remote Execution Rules

DO:
- Stream commands over SSH
- Use subprocess
- Use stdin-based execution

DO NOT:
- SCP scripts
- Create temp scripts on remote servers
- Install packages on remote servers

## Current Scope

Keep changes focused on the canonical root implementation. Do not perform the future
`src/exadata_ric/` package migration as part of unrelated cleanup or bug-fix work.
