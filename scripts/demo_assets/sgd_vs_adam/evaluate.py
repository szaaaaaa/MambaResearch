"""读取训练历史和最终参数，输出标准化 METRIC 行供实验循环解析。"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import yaml


def main() -> None:
    root = Path(__file__).parent
    with open(root / "configs" / "hparams.yaml", "r", encoding="utf-8") as f:
        hp = yaml.safe_load(f)

    ckpt_dir = root / "checkpoints"
    hist_path = ckpt_dir / "history.csv"
    best_path = ckpt_dir / "best.npz"

    if not hist_path.exists() or not best_path.exists():
        print(f"ERROR: missing artifacts in {ckpt_dir}", file=sys.stderr)
        sys.exit(1)

    losses: list[float] = []
    with open(hist_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            losses.append(float(row["loss"]))

    final_loss = losses[-1]
    best_loss = min(losses)
    # 收敛速度：第一次低于初始 1/10 的 epoch，找不到则 = 总 epoch
    threshold = losses[0] / 10.0
    epochs_to_converge = next(
        (i + 1 for i, v in enumerate(losses) if v <= threshold),
        len(losses),
    )

    print(f"METRIC final_loss={final_loss:.6f}")
    print(f"METRIC best_loss={best_loss:.6f}")
    print(f"METRIC epochs_to_converge={epochs_to_converge}")
    print(f"# optimizer={hp.get('optimizer')} lr={hp.get('learning_rate')}")


if __name__ == "__main__":
    main()
