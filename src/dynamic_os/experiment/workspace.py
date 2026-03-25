"""Experiment workspace management — init, snapshot, restore, read/write mutable files."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

_BUILTIN_TEMPLATE_DIR: Path = Path(__file__).parent / "templates" / "default"


@dataclass(frozen=True)
class WorkspaceConfig:
    """Declares the structure and constraints of an experiment workspace."""

    template: str = "builtin"
    custom_path: str = ""
    mutable_files: list[str] = field(default_factory=list)
    entry_point: str = "train.py"
    eval_script: str = "evaluate.py"


def init_workspace(config: WorkspaceConfig, run_dir: str | Path) -> Path:
    """Copy the workspace template into *run_dir*/experiment_workspace and return its path.

    For ``template="builtin"`` the built-in default template is used.
    For ``template="custom"`` the directory at *config.custom_path* is copied instead;
    it must exist and contain both *entry_point* and *eval_script*.
    """
    run_dir = Path(run_dir)
    dest = run_dir / "experiment_workspace"

    if config.template == "builtin":
        source = _BUILTIN_TEMPLATE_DIR
        if not source.is_dir():
            raise FileNotFoundError(
                f"Built-in template directory not found: {source}"
            )
        shutil.copytree(source, dest, dirs_exist_ok=True)
    elif config.template == "custom":
        source = Path(config.custom_path)
        if not source.is_dir():
            raise FileNotFoundError(
                f"Custom workspace path does not exist: {source}"
            )
        if not (source / config.entry_point).is_file():
            raise FileNotFoundError(
                f"Entry point '{config.entry_point}' not found in {source}"
            )
        if not (source / config.eval_script).is_file():
            raise FileNotFoundError(
                f"Eval script '{config.eval_script}' not found in {source}"
            )
        shutil.copytree(source, dest, dirs_exist_ok=True)
    else:
        raise ValueError(
            f"Unknown template type '{config.template}'; expected 'builtin' or 'custom'"
        )

    return dest


def read_mutable_files(
    workspace: Path, mutable_files: list[str]
) -> dict[str, str]:
    """Return ``{relative_path: content}`` for each mutable file in *workspace*.

    Files that do not exist are included with an empty-string value.
    """
    result: dict[str, str] = {}
    for rel in mutable_files:
        fp = workspace / rel
        if fp.is_file():
            result[rel] = fp.read_text(encoding="utf-8")
        else:
            result[rel] = ""
    return result


def write_mutable_files(
    workspace: Path, changes: dict[str, str]
) -> None:
    """Write *changes* (``{relative_path: content}``) into *workspace*.

    Parent directories are created automatically when they do not exist.
    """
    for rel, content in changes.items():
        fp = workspace / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")


def snapshot_mutable(
    workspace: Path, mutable_files: list[str]
) -> dict[str, str]:
    """Capture the current state of all mutable files as a save-point dict."""
    return read_mutable_files(workspace, mutable_files)


def restore_snapshot(
    workspace: Path, snapshot: dict[str, str]
) -> None:
    """Restore a previously captured snapshot by writing all files back."""
    write_mutable_files(workspace, snapshot)


def parse_workspace_config(raw: dict) -> WorkspaceConfig:
    """Build a :class:`WorkspaceConfig` from a raw dict (e.g. from experiment plan YAML).

    Missing keys receive their dataclass defaults.
    """
    return WorkspaceConfig(
        template=raw.get("template", "builtin"),
        custom_path=raw.get("custom_path", ""),
        mutable_files=list(raw.get("mutable_files", [])),
        entry_point=raw.get("entry_point", "train.py"),
        eval_script=raw.get("eval_script", "evaluate.py"),
    )
