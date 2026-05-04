"""轻量 numpy-only 训练脚手架 —— 实验工作区的最小起点模板。

设计目标：
- **零外部依赖**：只用 numpy + pyyaml，不需要 torch/tf/sklearn/数据集下载
- **始终可跑**：默认配置（线性回归 + SGD）开箱即可生成 checkpoint
- **LLM 可扩展**：把 hparams.yaml / train.py / evaluate.py 当 mutable_files，
  agent 可以替换数据生成、模型、优化器、训练循环

文件契约（非常重要，evaluate.py 依赖这些）：
- 退出前必须 ``np.savez(checkpoints/best.pt, ...)`` 保存权重
- 训练损失曲线写到 ``checkpoints/history.csv``（``epoch,loss`` 格式）
- 如果训练崩溃，要么 ``np.savez`` 一个 nan-filled checkpoint 占位，
  要么直接退出非零（evaluate.py 会输出 METRIC failed=1 而不是崩盘）
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import yaml


def make_synthetic_regression(seed: int, n_samples: int = 256, n_features: int = 8):
    """生成可重现的合成线性回归数据 —— 默认任务，agent 可换成任何数据。"""
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n_samples, n_features))
    true_w = rng.standard_normal(n_features)
    true_b = 0.5
    y = X @ true_w + true_b + 0.05 * rng.standard_normal(n_samples)
    return X, y


def step_sgd(w, b, grad_w, grad_b, lr):
    return w - lr * grad_w, b - lr * grad_b


def step_adam(state, grad_w, grad_b, lr, t, beta1=0.9, beta2=0.999, eps=1e-8):
    state["mw"] = beta1 * state["mw"] + (1 - beta1) * grad_w
    state["mb"] = beta1 * state["mb"] + (1 - beta1) * grad_b
    state["vw"] = beta2 * state["vw"] + (1 - beta2) * (grad_w**2)
    state["vb"] = beta2 * state["vb"] + (1 - beta2) * (grad_b**2)
    bc1 = 1 - beta1**t
    bc2 = 1 - beta2**t
    state["w"] = state["w"] - lr * (state["mw"] / bc1) / (np.sqrt(state["vw"] / bc2) + eps)
    state["b"] = state["b"] - lr * (state["mb"] / bc1) / (np.sqrt(state["vb"] / bc2) + eps)
    return state


def main() -> None:
    root = Path(__file__).parent
    with open(root / "configs" / "hparams.yaml", "r", encoding="utf-8") as f:
        hp = yaml.safe_load(f)

    optimizer = str(hp.get("optimizer", "sgd")).lower()
    lr = float(hp.get("learning_rate", 0.01))
    epochs = int(hp.get("epochs", 100))
    seed = int(hp.get("seed", 42))

    X, y = make_synthetic_regression(seed)
    rng = np.random.default_rng(seed)
    w = rng.standard_normal(X.shape[1]) * 0.01
    b = 0.0
    state = None
    if optimizer == "adam":
        state = {
            "w": w, "b": b,
            "mw": np.zeros_like(w), "mb": 0.0,
            "vw": np.zeros_like(w), "vb": 0.0,
        }

    history: list[tuple[int, float]] = []
    for epoch in range(1, epochs + 1):
        pred = X @ w + b
        residual = pred - y
        loss = float(np.mean(residual**2))
        history.append((epoch, loss))

        grad_w = (2.0 / X.shape[0]) * (X.T @ residual)
        grad_b = (2.0 / X.shape[0]) * float(np.sum(residual))

        if optimizer == "sgd":
            w, b = step_sgd(w, b, grad_w, grad_b, lr)
        elif optimizer == "adam":
            state = step_adam(state, grad_w, grad_b, lr, t=epoch)
            w, b = state["w"], state["b"]
        else:
            print(f"ERROR: unknown optimizer {optimizer!r}", file=sys.stderr)
            sys.exit(2)

    ckpt_dir = root / "checkpoints"
    ckpt_dir.mkdir(exist_ok=True)
    np.savez(ckpt_dir / "best.pt", w=w, b=b)
    with open(ckpt_dir / "history.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["epoch", "loss"])
        writer.writerows(history)

    print(f"trained optimizer={optimizer} lr={lr} epochs={epochs} final_loss={history[-1][1]:.6f}")


if __name__ == "__main__":
    main()
