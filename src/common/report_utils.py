from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Tuple


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_markdown(
    path: Path,
    *,
    title: str,
    sections: Iterable[Tuple[str, str]],
    prompt: str | None = None,
) -> None:
    lines: list[str] = [f"# {title}", ""]
    for name, content in sections:
        lines.append(f"## {name}\n{content}")
        lines.append("")
    if prompt is not None:
        lines.append("## Prompt\n```text")
        lines.append(prompt)
        lines.append("```")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")

