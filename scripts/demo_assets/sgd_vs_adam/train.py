"""SGD vs Adam 收敛对比的训练脚本（demo fixture）。

合成线性回归数据，按 hparams.optimizer 选择优化器训练，
把每个 epoch 的训练损失写到 history.csv，把最终参数写到 best.npz。
全程仅用 numpy，避免任何外部模型依赖，秒级跑完。

输出（不含 METRIC 行 —— METRIC 由 evaluate.py 输出）：
    history.csv : epoch,loss 全程曲线
    best.npz    : 最终参数 w, b
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import yaml


def make_data(seed: int, n: int = 256, d: int = 8):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, d))
    true_w = rng.standard_normal(d)
    true_b = 0.5
    y = X @ true_w + true_b + 0.05 * rng.standard_normal(n)
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
    mw_hat = state["mw"] / bc1
    mb_hat = state["mb"] / bc1
    vw_hat = state["vw"] / bc2
    vb_hat = state["vb"] / bc2
    state["w"] = state["w"] - lr * mw_hat / (np.sqrt(vw_hat) + eps)
    state["b"] = state["b"] - lr * mb_hat / (np.sqrt(vb_hat) + eps)
    return state


def main() -> None:
    root = Path(__file__).parent
    with open(root / "configs" / "hparams.yaml", "r", encoding="utf-8") as f:
        hp = yaml.safe_load(f)

    optimizer = str(hp.get("optimizer", "sgd")).lower()
    lr = float(hp.get("learning_rate", 0.05))
    epochs = int(hp.get("epochs", 100))
    seed = int(hp.get("seed", 42))

    X, y = make_data(seed)
    rng = np.random.default_rng(seed)
    w = rng.standard_normal(X.shape[1]) * 0.01
    b = 0.0

    if optimizer == "adam":
        state = {
            "w": w, "b": b,
            "mw": np.zeros_like(w), "mb": 0.0,
            "vw": np.zeros_like(w), "vb": 0.0,
        }

    history = []
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

    out_dir = root / "checkpoints"
    out_dir.mkdir(exist_ok=True)
    np.savez(out_dir / "best.npz", w=w, b=b)
    with open(out_dir / "history.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["epoch", "loss"])
        writer.writerows(history)

    print(f"trained optimizer={optimizer} lr={lr} epochs={epochs} final_loss={history[-1][1]:.6f}")


if __name__ == "__main__":
    main()
