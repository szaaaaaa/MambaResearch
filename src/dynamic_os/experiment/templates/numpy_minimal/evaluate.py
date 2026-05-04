"""轻量 numpy-only 评估脚手架 —— 读 checkpoint + history，输出 METRIC 行。

容错设计：
- checkpoint 缺失/损坏时，输出 ``METRIC checkpoint_missing=1`` 然后正常退出（exit 0），
  让 run_experiment 仍能解析到一个 metric。否则上层会把 evaluate 的非零退出当成
  "实验跑挂"，反复 retry 没有改善。
- history 缺失时，输出 ``METRIC history_missing=1``，照样不崩。
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import yaml


def main() -> None:
    root = Path(__file__).parent
    with open(root / "configs" / "hparams.yaml", "r", encoding="utf-8") as f:
        hp = yaml.safe_load(f)

    ckpt_dir = root / "checkpoints"
    hist_path = ckpt_dir / "history.csv"
    best_path = ckpt_dir / "best.pt.npz"
    # np.savez 默认追加 .npz；做个兼容（agent 可能写 best.pt 或 best.pt.npz）
    if not best_path.exists() and (ckpt_dir / "best.pt").exists():
        best_path = ckpt_dir / "best.pt"

    failed = False
    if not best_path.exists():
        print("METRIC checkpoint_missing=1")
        failed = True
    else:
        try:
            np.load(best_path, allow_pickle=False)
        except Exception:  # noqa: BLE001 - 任何加载错误都 graceful
            print("METRIC checkpoint_corrupt=1")
            failed = True

    if not hist_path.exists():
        print("METRIC history_missing=1")
        if failed:
            return  # 没 history 也没 checkpoint，没有指标可算

    losses: list[float] = []
    if hist_path.exists():
        with open(hist_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    losses.append(float(row["loss"]))
                except (KeyError, ValueError):
                    continue

    if not losses:
        print("METRIC history_empty=1")
        return

    final_loss = losses[-1]
    best_loss = min(losses)
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
