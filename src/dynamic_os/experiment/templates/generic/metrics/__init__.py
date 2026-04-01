"""指标注册表 —— AI agent 可在此文件中注册新的评估指标。

添加新指标：
    1. 定义指标函数，签名为 (outputs, targets, **kwargs) -> float
    2. 调用 register("metric", "名称", 函数) 注册

AI agent 会根据任务类型添加合适的指标，
例如 NLP 的 BLEU/ROUGE，CV 的 mAP/IoU 等。
"""

import torch
from registry import register


def accuracy(outputs: torch.Tensor, targets: torch.Tensor, **kwargs) -> float:
    """分类准确率。"""
    preds = outputs.argmax(dim=1)
    return preds.eq(targets).float().mean().item()


def mse(outputs: torch.Tensor, targets: torch.Tensor, **kwargs) -> float:
    """均方误差（回归任务）。"""
    return ((outputs.squeeze() - targets.float()) ** 2).mean().item()


register("metric", "accuracy", accuracy)
register("metric", "mse", mse)
