"""通用训练脚本 —— 基于注册表机制驱动，AI agent 可扩展或完全重写。

训练流程：
1. 从 hparams.yaml 读取配置
2. 通过注册表查找 dataset / model / metrics
3. 执行标准训练循环
4. 输出 METRIC 行供实验系统解析

AI agent 扩展方式：
- 在 datasets/__init__.py 注册新数据集
- 在 models/__init__.py 注册新模型
- 在 metrics/__init__.py 注册新指标
- 或直接重写本文件以适配非标准训练流程（如 GAN、RL）
"""

import random
import sys
from pathlib import Path

import torch
import torch.nn as nn
import yaml

# 导入注册表和组件模块（触发注册）
import registry
import datasets  # noqa: F401 — 触发数据集注册
import models    # noqa: F401 — 触发模型注册
import metrics   # noqa: F401 — 触发指标注册


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def resolve_device(cfg: str) -> torch.device:
    if cfg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(cfg)


def build_optimizer(model: nn.Module, hparams: dict):
    name = hparams.get("optimizer", "adam").lower()
    lr = hparams.get("learning_rate", 0.001)
    wd = hparams.get("weight_decay", 0.0)
    if name == "sgd":
        return torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=wd)
    if name == "adamw":
        return torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    return torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)


def build_scheduler(optimizer, hparams: dict):
    name = hparams.get("scheduler", "cosine").lower()
    epochs = hparams.get("epochs", 10)
    if name == "cosine":
        return torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    if name == "step":
        return torch.optim.lr_scheduler.StepLR(optimizer, step_size=max(1, epochs // 3), gamma=0.1)
    return None


def train_one_epoch(model, loader, criterion, optimizer, device):
    model.train()
    total_loss, total = 0.0, 0
    for batch in loader:
        inputs, targets = batch[0].to(device), batch[1].to(device)
        optimizer.zero_grad()
        outputs = model(inputs)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * inputs.size(0)
        total += inputs.size(0)
    return total_loss / max(total, 1)


@torch.no_grad()
def evaluate_epoch(model, loader, criterion, device, metric_names):
    model.eval()
    total_loss, total = 0.0, 0
    all_outputs, all_targets = [], []
    for batch in loader:
        inputs, targets = batch[0].to(device), batch[1].to(device)
        outputs = model(inputs)
        loss = criterion(outputs, targets)
        total_loss += loss.item() * inputs.size(0)
        total += inputs.size(0)
        all_outputs.append(outputs.cpu())
        all_targets.append(targets.cpu())

    avg_loss = total_loss / max(total, 1)
    all_outputs = torch.cat(all_outputs, dim=0)
    all_targets = torch.cat(all_targets, dim=0)

    # 通过注册表计算每个指标
    metric_values = {"loss": avg_loss}
    for name in metric_names:
        try:
            fn = registry.get("metric", name)
            metric_values[name] = fn(all_outputs, all_targets)
        except KeyError:
            pass
    return metric_values


def main() -> None:
    root = Path(__file__).parent
    with open(root / "configs" / "hparams.yaml", "r", encoding="utf-8") as f:
        hparams = yaml.safe_load(f)

    set_seed(hparams.get("seed", 42))
    device = resolve_device(hparams.get("device", "auto"))
    print(f"Using device: {device}")

    # 通过注册表创建数据集和模型
    dataset_name = hparams.get("dataset", "synthetic")
    model_name = hparams.get("model", "mlp")
    metric_names = hparams.get("eval_metrics", ["accuracy"])

    train_loader, val_loader = registry.create("dataset", dataset_name, hparams=hparams)
    model = registry.create("model", model_name, hparams=hparams).to(device)
    optimizer = build_optimizer(model, hparams)
    scheduler = build_scheduler(optimizer, hparams)
    criterion = nn.CrossEntropyLoss()

    ckpt_dir = root / hparams.get("checkpoint_dir", "checkpoints")
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    epochs = hparams.get("epochs", 10)
    best_primary = None  # 追踪主指标最佳值
    primary_metric = metric_names[0] if metric_names else "loss"
    # 从 hparams 中读取 LLM 定义的指标方向，fallback 到名称推断
    metric_dirs = hparams.get("metric_directions", {})
    if primary_metric in metric_dirs:
        higher_is_better = metric_dirs[primary_metric] == "maximize"
    else:
        higher_is_better = primary_metric not in ("loss", "mse", "error", "perplexity")

    for epoch in range(1, epochs + 1):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_metrics = evaluate_epoch(model, val_loader, criterion, device, metric_names)
        if scheduler is not None:
            scheduler.step()

        status = f"Epoch {epoch}/{epochs}  train_loss={train_loss:.4f}"
        for k, v in val_metrics.items():
            status += f"  val_{k}={v:.4f}"
        print(status)

        # 保存最优检查点
        current = val_metrics.get(primary_metric, val_metrics.get("loss", train_loss))
        if best_primary is None:
            is_better = True
        elif higher_is_better:
            is_better = current > best_primary
        else:
            is_better = current < best_primary

        if is_better:
            best_primary = current
            torch.save(
                {"model_state_dict": model.state_dict(), "hparams": hparams, "epoch": epoch},
                ckpt_dir / "best.pt",
            )

    # 最终评估 + 输出 METRIC 行
    final_metrics = evaluate_epoch(model, val_loader, criterion, device, metric_names)
    print(f"METRIC train_loss={train_loss:.6f}")
    for k, v in final_metrics.items():
        print(f"METRIC val_{k}={v:.6f}")
    if best_primary is not None:
        print(f"METRIC best_{primary_metric}={best_primary:.6f}")


if __name__ == "__main__":
    main()
