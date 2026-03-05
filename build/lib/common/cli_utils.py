from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Tuple
import argparse

from src.common.config_utils import load_yaml, project_root


def load_root_and_cfg(from_file: str, config_path: str) -> Tuple[Path, Dict[str, Any]]:
    root = project_root(from_file)
    cfg = load_yaml(Path(config_path))
    return root, cfg


def default_config_path(from_file: str) -> Path:
    return project_root(from_file) / "configs" / "rag.yaml"


def add_config_arg(parser: argparse.ArgumentParser, from_file: str) -> None:
    parser.add_argument("--config", default=str(default_config_path(from_file)), help="Path to configs/rag.yaml")


def parse_args_and_cfg(
    parser: argparse.ArgumentParser,
    from_file: str,
) -> Tuple[argparse.Namespace, Path, Dict[str, Any]]:
    args = parser.parse_args()
    root, cfg = load_root_and_cfg(from_file, args.config)
    return args, root, cfg


def run_cli(task_name: str, fn: Callable[[], int]) -> int:
    try:
        return fn()
    except Exception:
        print(f"[ERROR] {task_name} failed")
        traceback.print_exc()
        return 1
