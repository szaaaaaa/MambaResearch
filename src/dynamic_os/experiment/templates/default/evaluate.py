"""Evaluate a trained model checkpoint on the test set."""

import sys
from pathlib import Path

import torch
import torch.nn as nn
import torchvision
import torchvision.transforms as T
import yaml

from models.model import build_model


def main() -> None:
    root = Path(__file__).parent
    cfg_path = root / "configs" / "hparams.yaml"
    with open(cfg_path, "r") as f:
        hparams = yaml.safe_load(f)

    ckpt_path = root / hparams.get("checkpoint_dir", "checkpoints") / "best.pt"
    if not ckpt_path.exists():
        print(f"ERROR: checkpoint not found at {ckpt_path}", file=sys.stderr)
        sys.exit(1)

    device_cfg = hparams.get("device", "auto")
    if device_cfg == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(device_cfg)

    model = build_model(hparams).to(device)
    checkpoint = torch.load(ckpt_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    transform = T.Compose([
        T.ToTensor(),
        T.Normalize((0.4914, 0.4822, 0.4465), (0.2470, 0.2435, 0.2616)),
    ])
    data_dir = str(root / "data")
    test_set = torchvision.datasets.CIFAR10(root=data_dir, train=False, download=True, transform=transform)
    test_loader = torch.utils.data.DataLoader(test_set, batch_size=hparams["batch_size"], shuffle=False, num_workers=2)

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

    print(f"METRIC test_loss={test_loss:.6f}")
    print(f"METRIC test_accuracy={test_acc:.6f}")
    print(f"METRIC test_samples={total}")


if __name__ == "__main__":
    main()
