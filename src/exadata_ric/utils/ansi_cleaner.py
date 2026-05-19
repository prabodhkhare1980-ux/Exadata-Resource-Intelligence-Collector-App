"""ANSI and prompt cleanup utilities for remote shell output."""

from __future__ import annotations

import re

ANSI_CSI = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ANSI_OSC = re.compile(r"\x1B\][^\a]*\a")
PROMPT_LINE = re.compile(r"^\s*(?:\[[^\]]+@[^\]]+\]|[\w.-]+@[\w.-]+[$#])\s*.*$")


def clean_output(text: str) -> str:
    """Remove terminal control sequences and prompt noise before parsing."""

    decoded = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    cleaned = ANSI_CSI.sub("", decoded)
    cleaned = ANSI_OSC.sub("", cleaned).replace("\r", "")
    lines: list[str] = []
    blank_count = 0
    for line in cleaned.splitlines():
        if PROMPT_LINE.match(line):
            continue
        if line.strip() == "":
            blank_count += 1
            if blank_count > 1:
                continue
        else:
            blank_count = 0
        lines.append(line)
    return "\n".join(lines).strip() + "\n"
