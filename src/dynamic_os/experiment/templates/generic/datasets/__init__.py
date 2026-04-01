"""数据集注册表 —— AI agent 可在此文件中注册新的数据集。

添加新数据集：
    1. 在本文件中定义一个构建函数，签名为 (hparams: dict) -> (train_loader, val_loader)
    2. 调用 register("dataset", "名称", 函数) 注册

AI agent 会根据研究课题在此文件中添加新的数据集实现，
例如 NLP 任务的 IMDB、CV 任务的 ImageNet 子集等。
"""

import torch
import torch.utils.data
from registry import register


def build_synthetic(hparams: dict):
    """合成随机数据 —— 用于快速验证训练流程。"""
    input_dim = hparams.get("input_dim", 784)
    num_classes = hparams.get("num_classes", 10)
    n_train = hparams.get("n_train", 1000)
    n_test = hparams.get("n_test", 200)
    bs = hparams.get("batch_size", 64)

    train_set = torch.utils.data.TensorDataset(
        torch.randn(n_train, input_dim),
        torch.randint(0, num_classes, (n_train,)),
    )
    test_set = torch.utils.data.TensorDataset(
        torch.randn(n_test, input_dim),
        torch.randint(0, num_classes, (n_test,)),
    )
    train_loader = torch.utils.data.DataLoader(train_set, batch_size=bs, shuffle=True)
    val_loader = torch.utils.data.DataLoader(test_set, batch_size=bs, shuffle=False)
    return train_loader, val_loader


register("dataset", "synthetic", build_synthetic)
