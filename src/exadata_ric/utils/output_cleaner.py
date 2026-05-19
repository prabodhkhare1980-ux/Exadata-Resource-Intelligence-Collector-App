"""Output cleanup utilities for remote shell output normalization."""

from __future__ import annotations

import re

ANSI_CSI = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ANSI_OSC = re.compile(r"\x1B\][^\a]*\a")
PROMPT_LINE = re.compile(r"^\[[^\]]+@[^\]]+\].*$")


def clean_output(text: str) -> str:
    decoded = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    cleaned = ANSI_CSI.sub("", ANSI_OSC.sub("", decoded)).replace("\r", "")
    lines: list[str] = []
    blank = 0
    for line in cleaned.splitlines():
        if PROMPT_LINE.match(line.strip()):
            continue
        if not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        lines.append(line)
    return "\n".join(lines).strip() + "\n"
