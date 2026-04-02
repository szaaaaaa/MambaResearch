"""用于 CIFAR-10 分类的默认 CNN 模型。

本模块定义了实验工作区默认模板中使用的神经网络模型。
在 Dynamic Research OS 的实验循环中，AI agent 可以修改本文件来改进模型架构，
例如增加网络深度、调整通道数、添加正则化层等。

本文件是实验工作区中的"可变文件"之一，AI agent 在每轮迭代中
可以通过 ``write_mutable_files()`` 重写本文件的内容来尝试不同的模型结构。

当前默认实现：三层卷积 + 两层全连接的简单 CNN，适用于 CIFAR-10 基线实验。
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class SimpleCNN(nn.Module):
    """适用于 CIFAR-10（32x32x3 图像）的简单三层 CNN。

    网络结构：
    - 三个卷积块，每块包含：Conv2d -> BatchNorm2d -> ReLU -> MaxPool2d
    - 通道数逐层递增：3 -> 32 -> 64 -> 128
    - 每次池化将空间分辨率减半：32x32 -> 16x16 -> 8x8 -> 4x4
    - 两层全连接层：2048 -> 256 -> num_classes

    该模型作为基线，AI agent 可在实验迭代中替换为更复杂的架构。
    """

    def __init__(self, num_classes: int = 10) -> None:
        """初始化 SimpleCNN 模型。

        参数
        ----------
        num_classes : int, optional
            分类类别数，默认 10（CIFAR-10 数据集）。
        """
        super().__init__()
        # 第一卷积块：3通道 -> 32通道，保持空间尺寸（padding=1）
        self.conv1 = nn.Conv2d(3, 32, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(32)
        # 第二卷积块：32通道 -> 64通道
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm2d(64)
        # 第三卷积块：64通道 -> 128通道
        self.conv3 = nn.Conv2d(64, 128, kernel_size=3, padding=1)
        self.bn3 = nn.BatchNorm2d(128)
        # 最大池化层，2x2 窗口，步长 2，将空间尺寸减半
        self.pool = nn.MaxPool2d(2, 2)
        # 全连接层：展平后的特征维度 = 128通道 * 4 * 4 空间尺寸 = 2048
        self.fc1 = nn.Linear(128 * 4 * 4, 256)
        self.fc2 = nn.Linear(256, num_classes)  # 输出层，维度等于类别数

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """前向传播。

        参数
        ----------
        x : torch.Tensor
            输入图像张量，形状为 (batch_size, 3, 32, 32)。

        返回
        -------
        torch.Tensor
            未归一化的分类 logits，形状为 (batch_size, num_classes)。
        """
        x = self.pool(F.relu(self.bn1(self.conv1(x))))  # 32x32 -> 16x16 特征图下采样
        x = self.pool(F.relu(self.bn2(self.conv2(x))))  # 16x16 -> 8x8 特征图下采样
        x = self.pool(F.relu(self.bn3(self.conv3(x))))  # 8x8 -> 4x4 特征图下采样
        x = x.view(x.size(0), -1)                       # 展平为一维向量
        x = F.relu(self.fc1(x))                          # 隐藏层 + ReLU 激活
        x = self.fc2(x)                                  # 输出层（原始 logits，不加 softmax）
        return x


def build_model(hparams: dict) -> nn.Module:
    """根据超参数构建并返回模型。

    这是模型构建的统一工厂函数，被 train.py 和 evaluate.py 共同调用。
    AI agent 修改模型架构时，只需修改本函数和相关类定义即可。

    参数
    ----------
    hparams : dict
        超参数字典，可选键 ``num_classes``（默认 10）。

    返回
    -------
    nn.Module
        构建好的模型实例（未移动到设备，未加载权重）。
    """
    num_classes = hparams.get("num_classes", 10)
    return SimpleCNN(num_classes=num_classes)
