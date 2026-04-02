"""用于深度学习实验的标准 PyTorch 训练脚本。

本模块是实验工作区默认模板的训练入口脚本，负责完整的模型训练流程。
在 Dynamic Research OS 的实验循环中，该脚本作为子进程被执行，
AI agent 通过修改超参数配置（hparams.yaml）和模型定义（models/model.py）
来迭代优化实验结果。

训练流程：
1. 从 configs/hparams.yaml 加载超参数
2. 构建模型、数据加载器、优化器和学习率调度器
3. 逐 epoch 训练，每轮结束后在验证集上评估
4. 保存最优模型检查点到 checkpoints/best.pt
5. 训练结束后输出标准化的 METRIC 行，供上层系统解析

输出格式约定：
    以 ``METRIC key=value`` 格式输出的行会被实验循环解析为结构化指标，
    用于判断实验是否改进以及指导下一轮迭代。
"""

import os
import random
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torchvision
import torchvision.transforms as T
import yaml

from models.model import build_model


def resolve_device(device_cfg: str) -> torch.device:
    """根据配置字符串解析计算设备。

    参数
    ----------
    device_cfg : str
        设备配置，``"auto"`` 时自动检测 CUDA 可用性，
        否则直接使用指定的设备名（如 ``"cpu"``、``"cuda:0"``）。

    返回
    -------
    torch.device
        解析后的 PyTorch 设备对象。
    """
    if device_cfg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device_cfg)


def set_seed(seed: int) -> None:
    """设置全局随机种子以确保实验可复现。

    同时设置 Python random、PyTorch CPU 和 CUDA 的随机种子。

    参数
    ----------
    seed : int
        随机种子值。
    """
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def get_dataloaders(hparams: dict):
    """构建 CIFAR-10 的训练和验证数据加载器。

    训练集使用数据增强（随机裁剪 + 水平翻转），验证集仅做标准化。
    CIFAR-10 的均值和标准差为预计算的固定值。

    参数
    ----------
    hparams : dict
        超参数字典，需包含 ``batch_size`` 键。

    返回
    -------
    tuple[DataLoader, DataLoader]
        训练数据加载器和验证数据加载器。
    """
    # 训练集数据增强：随机裁剪 + 水平翻转 + 标准化
    transform_train = T.Compose([
        T.RandomCrop(32, padding=4),
        T.RandomHorizontalFlip(),
        T.ToTensor(),
        T.Normalize((0.4914, 0.4822, 0.4465), (0.2470, 0.2435, 0.2616)),
    ])
    # 验证集仅做标准化，不做数据增强
    transform_test = T.Compose([
        T.ToTensor(),
        T.Normalize((0.4914, 0.4822, 0.4465), (0.2470, 0.2435, 0.2616)),
    ])
    data_dir = str(Path(__file__).parent / "data")
    train_set = torchvision.datasets.CIFAR10(root=data_dir, train=True, download=True, transform=transform_train)
    test_set = torchvision.datasets.CIFAR10(root=data_dir, train=False, download=True, transform=transform_test)

    bs = hparams["batch_size"]
    train_loader = torch.utils.data.DataLoader(train_set, batch_size=bs, shuffle=True, num_workers=2)
    val_loader = torch.utils.data.DataLoader(test_set, batch_size=bs, shuffle=False, num_workers=2)
    return train_loader, val_loader


def build_optimizer(model: nn.Module, hparams: dict):
    """根据超参数构建优化器。

    支持 Adam 和 SGD 两种优化器，未识别的名称默认使用 Adam。

    参数
    ----------
    model : nn.Module
        待优化的模型。
    hparams : dict
        超参数字典，需包含 ``learning_rate``，
        可选 ``optimizer``（默认 ``"adam"``）和 ``weight_decay``（默认 0.0）。

    返回
    -------
    torch.optim.Optimizer
        构建好的优化器实例。
    """
    name = hparams.get("optimizer", "adam").lower()
    lr = hparams["learning_rate"]
    wd = hparams.get("weight_decay", 0.0)
    if name == "adam":
        return torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)
    if name == "sgd":
        return torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=wd)
    # 未识别的优化器名称，回退到 Adam
    return torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)


def build_scheduler(optimizer, hparams: dict):
    """根据超参数构建学习率调度器。

    支持 cosine（余弦退火）和 step（阶梯衰减）两种策略，
    未识别的名称返回 None（即不使用调度器）。

    参数
    ----------
    optimizer : torch.optim.Optimizer
        关联的优化器。
    hparams : dict
        超参数字典，需包含 ``epochs``，可选 ``scheduler``（默认 ``"cosine"``）。

    返回
    -------
    torch.optim.lr_scheduler._LRScheduler | None
        学习率调度器实例，或 None 表示不使用调度。
    """
    name = hparams.get("scheduler", "cosine").lower()
    epochs = hparams["epochs"]
    if name == "cosine":
        return torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    if name == "step":
        # 阶梯衰减：每 1/3 总 epoch 数衰减一次，衰减因子 0.1
        return torch.optim.lr_scheduler.StepLR(optimizer, step_size=max(1, epochs // 3), gamma=0.1)
    return None


def train_one_epoch(model, loader, criterion, optimizer, device):
    """执行一个 epoch 的训练。

    参数
    ----------
    model : nn.Module
        待训练的模型。
    loader : DataLoader
        训练数据加载器。
    criterion : nn.Module
        损失函数。
    optimizer : torch.optim.Optimizer
        优化器。
    device : torch.device
        计算设备。

    返回
    -------
    tuple[float, float]
        (平均损失, 准确率) 的元组。
    """
    model.train()
    total_loss, correct, total = 0.0, 0, 0
    for inputs, targets in loader:
        inputs, targets = inputs.to(device), targets.to(device)
        optimizer.zero_grad()
        outputs = model(inputs)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()
        # 累计损失按样本数加权，最终除以总样本数得到平均损失
        total_loss += loss.item() * inputs.size(0)
        correct += outputs.argmax(dim=1).eq(targets).sum().item()
        total += inputs.size(0)
    return total_loss / total, correct / total


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    """在给定数据集上评估模型（不计算梯度）。

    参数
    ----------
    model : nn.Module
        待评估的模型。
    loader : DataLoader
        评估数据加载器。
    criterion : nn.Module
        损失函数。
    device : torch.device
        计算设备。

    返回
    -------
    tuple[float, float]
        (平均损失, 准确率) 的元组。
    """
    model.eval()
    total_loss, correct, total = 0.0, 0, 0
    for inputs, targets in loader:
        inputs, targets = inputs.to(device), targets.to(device)
        outputs = model(inputs)
        loss = criterion(outputs, targets)
        total_loss += loss.item() * inputs.size(0)
        correct += outputs.argmax(dim=1).eq(targets).sum().item()
        total += inputs.size(0)
    return total_loss / total, correct / total


def main() -> None:
    """训练主流程入口。

    读取超参数配置 -> 构建模型和训练组件 -> 逐 epoch 训练并验证 ->
    保存最优检查点 -> 输出标准化指标行。
    """
    # 从工作区的 configs 目录加载超参数
    cfg_path = Path(__file__).parent / "configs" / "hparams.yaml"
    with open(cfg_path, "r") as f:
        hparams = yaml.safe_load(f)

    set_seed(hparams.get("seed", 42))
    device = resolve_device(hparams.get("device", "auto"))
    print(f"Using device: {device}")

    # 构建训练所需的全部组件
    model = build_model(hparams).to(device)
    train_loader, val_loader = get_dataloaders(hparams)
    optimizer = build_optimizer(model, hparams)
    scheduler = build_scheduler(optimizer, hparams)
    criterion = nn.CrossEntropyLoss()

    # 检查点保存目录
    ckpt_dir = Path(__file__).parent / hparams.get("checkpoint_dir", "checkpoints")
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    # 训练循环：逐 epoch 训练，保存验证集上最优的模型
    best_val_acc = 0.0
    for epoch in range(1, hparams["epochs"] + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = evaluate(model, val_loader, criterion, device)
        if scheduler is not None:
            scheduler.step()
        print(f"Epoch {epoch}/{hparams['epochs']}  "
              f"train_loss={train_loss:.4f}  train_acc={train_acc:.4f}  "
              f"val_loss={val_loss:.4f}  val_acc={val_acc:.4f}")
        # 当验证准确率创新高时保存检查点
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save({"model_state_dict": model.state_dict(), "hparams": hparams, "epoch": epoch},
                       ckpt_dir / "best.pt")

    # 在验证集上进行最终评估以报告指标
    final_val_loss, final_val_acc = evaluate(model, val_loader, criterion, device)
    # 输出标准化 METRIC 行，供实验循环系统解析
    print(f"METRIC train_loss={train_loss:.6f}")
    print(f"METRIC val_loss={final_val_loss:.6f}")
    print(f"METRIC accuracy={final_val_acc:.6f}")
    print(f"METRIC best_accuracy={best_val_acc:.6f}")


if __name__ == "__main__":
    main()
