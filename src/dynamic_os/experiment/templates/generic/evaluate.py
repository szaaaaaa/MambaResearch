"""通用评估脚本 —— 加载最优检查点并在测试集上评估。

复用 train.py 的注册表机制和数据加载逻辑。
"""

import sys
from pathlib import Path

import torch
import torch.nn as nn
import yaml

import registry
import datasets  # noqa: F401
import models    # noqa: F401
import metrics   # noqa: F401


def main() -> None:
    root = Path(__file__).parent
    with open(root / "configs" / "hparams.yaml", "r", encoding="utf-8") as f:
        hparams = yaml.safe_load(f)

    ckpt_path = root / hparams.get("checkpoint_dir", "checkpoints") / "best.pt"
    if not ckpt_path.exists():
        print(f"ERROR: checkpoint not found at {ckpt_path}", file=sys.stderr)
        sys.exit(1)

    device_cfg = hparams.get("device", "auto")
    device = torch.device(
        "cuda" if device_cfg == "auto" and torch.cuda.is_available()
        else device_cfg if device_cfg != "auto" else "cpu"
    )

    model_name = hparams.get("model", "mlp")
    model = registry.create("model", model_name, hparams=hparams).to(device)
    checkpoint = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    dataset_name = hparams.get("dataset", "synthetic")
    _, test_loader = registry.create("dataset", dataset_name, hparams=hparams)
    metric_names = hparams.get("eval_metrics", ["accuracy"])
    criterion = nn.CrossEntropyLoss()

    total_loss, total = 0.0, 0
    all_outputs, all_targets = [], []
    with torch.no_grad():
        for batch in test_loader:
            inputs, targets = batch[0].to(device), batch[1].to(device)
            outputs = model(inputs)
            loss = criterion(outputs, targets)
            total_loss += loss.item() * inputs.size(0)
            total += inputs.size(0)
            all_outputs.append(outputs.cpu())
            all_targets.append(targets.cpu())

    all_outputs = torch.cat(all_outputs, dim=0)
    all_targets = torch.cat(all_targets, dim=0)

    print(f"METRIC test_loss={total_loss / max(total, 1):.6f}")
    for name in metric_names:
        try:
            fn = registry.get("metric", name)
            value = fn(all_outputs, all_targets)
            print(f"METRIC test_{name}={value:.6f}")
        except KeyError:
            pass
    print(f"METRIC test_samples={total}")


if __name__ == "__main__":
    main()
