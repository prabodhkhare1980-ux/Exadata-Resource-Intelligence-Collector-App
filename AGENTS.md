# Exadata Resource Intelligence Collector

## Project Goals

Build a Python-based Exadata infrastructure intelligence and capacity collection system.

Phase 1 foundation remains limited to SSH runner, YAML config, OS/filesystem/CPU/memory collectors, and CSV/JSON output.

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

## Initial Scope

No ASM/IORM/SQL/licensing/dashboard work in this phase.
