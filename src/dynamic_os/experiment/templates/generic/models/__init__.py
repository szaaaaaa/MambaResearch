"""模型注册表 —— AI agent 可在此文件中注册新的模型架构。

添加新模型：
    1. 在本文件中定义模型类和构建函数
    2. 构建函数签名为 (hparams: dict) -> nn.Module
    3. 调用 register("model", "名称", 函数) 注册

AI agent 会根据研究课题替换或添加模型，
例如 Transformer、ResNet、GAN 等。
"""

import torch.nn as nn
from registry import register


class MLP(nn.Module):
    """通用 MLP 基线 —— 适用于任何向量化输入的分类/回归任务。"""

    def __init__(self, input_dim: int = 784, hidden_dim: int = 256, num_classes: int = 10) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim // 2, num_classes),
        )

    def forward(self, x):
        if x.dim() > 2:
            x = x.view(x.size(0), -1)
        return self.net(x)


def build_mlp(hparams: dict) -> nn.Module:
    return MLP(
        input_dim=hparams.get("input_dim", 784),
        hidden_dim=hparams.get("hidden_dim", 256),
        num_classes=hparams.get("num_classes", 10),
    )


register("model", "mlp", build_mlp)
