"""在测试集上评估训练好的模型检查点。

本模块是实验工作区默认模板的评估脚本，负责加载训练阶段保存的最优检查点，
在 CIFAR-10 测试集上进行推理评估，并输出标准化的测试指标。

在 Dynamic Research OS 的实验循环中，该脚本在每轮训练完成后被调用，
其输出的 METRIC 行被上层系统解析，用于判断本轮实验是否带来了改进。

与 train.py 的关系：
- train.py 负责训练并保存 best.pt 检查点
- 本脚本加载该检查点并在独立的测试集上评估，提供无偏的性能估计

输出格式约定：
    ``METRIC test_loss=...`` — 测试集平均损失
    ``METRIC test_accuracy=...`` — 测试集准确率
    ``METRIC test_samples=...`` — 测试样本总数
"""

import sys
from pathlib import Path

import torch
import torch.nn as nn
import torchvision
import torchvision.transforms as T
import yaml

from models.model import build_model


def main() -> None:
    """评估主流程入口。

    加载最优检查点 -> 在测试集上推理 -> 输出标准化指标行。
    若检查点文件不存在则报错退出（退出码 1）。
    """
    root = Path(__file__).parent

    # 加载超参数配置
    cfg_path = root / "configs" / "hparams.yaml"
    with open(cfg_path, "r") as f:
        hparams = yaml.safe_load(f)

    # 定位训练阶段保存的最优检查点
    ckpt_path = root / hparams.get("checkpoint_dir", "checkpoints") / "best.pt"
    if not ckpt_path.exists():
        print(f"ERROR: checkpoint not found at {ckpt_path}", file=sys.stderr)
        sys.exit(1)

    # 解析计算设备
    device_cfg = hparams.get("device", "auto")
    if device_cfg == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(device_cfg)

    # 重建模型并加载检查点权重
    model = build_model(hparams).to(device)
    checkpoint = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    # 构建测试集数据加载器（仅标准化，不做数据增强）
    transform = T.Compose([
        T.ToTensor(),
        T.Normalize((0.4914, 0.4822, 0.4465), (0.2470, 0.2435, 0.2616)),
    ])
    data_dir = str(root / "data")
    test_set = torchvision.datasets.CIFAR10(root=data_dir, train=False, download=True, transform=transform)
    test_loader = torch.utils.data.DataLoader(test_set, batch_size=hparams["batch_size"], shuffle=False, num_workers=2)

    # 在测试集上进行无梯度推理评估
    criterion = nn.CrossEntropyLoss()
    total_loss, correct, total = 0.0, 0, 0
    with torch.no_grad():
        for inputs, targets in test_loader:
            inputs, targets = inputs.to(device), targets.to(device)
            outputs = model(inputs)
            loss = criterion(outputs, targets)
            total_loss += loss.item() * inputs.size(0)
            correct += outputs.argmax(dim=1).eq(targets).sum().item()
            total += inputs.size(0)

    test_loss = total_loss / total
    test_acc = correct / total

    # 输出标准化 METRIC 行，供实验循环系统解析
    print(f"METRIC test_loss={test_loss:.6f}")
    print(f"METRIC test_accuracy={test_acc:.6f}")
    print(f"METRIC test_samples={total}")


if __name__ == "__main__":
    main()
