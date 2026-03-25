"""Standard PyTorch training script for deep learning experiments."""

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
    if device_cfg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device_cfg)


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def get_dataloaders(hparams: dict):
    transform_train = T.Compose([
        T.RandomCrop(32, padding=4),
        T.RandomHorizontalFlip(),
        T.ToTensor(),
        T.Normalize((0.4914, 0.4822, 0.4465), (0.2470, 0.2435, 0.2616)),
    ])
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
    name = hparams.get("optimizer", "adam").lower()
    lr = hparams["learning_rate"]
    wd = hparams.get("weight_decay", 0.0)
    if name == "adam":
        return torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)
    if name == "sgd":
        return torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=wd)
    return torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)


def build_scheduler(optimizer, hparams: dict):
    name = hparams.get("scheduler", "cosine").lower()
    epochs = hparams["epochs"]
    if name == "cosine":
        return torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    if name == "step":
        return torch.optim.lr_scheduler.StepLR(optimizer, step_size=max(1, epochs // 3), gamma=0.1)
    return None


def train_one_epoch(model, loader, criterion, optimizer, device):
    model.train()
    total_loss, correct, total = 0.0, 0, 0
    for inputs, targets in loader:
        inputs, targets = inputs.to(device), targets.to(device)
        optimizer.zero_grad()
        outputs = model(inputs)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * inputs.size(0)
        correct += outputs.argmax(dim=1).eq(targets).sum().item()
        total += inputs.size(0)
    return total_loss / total, correct / total


@torch.no_grad()
def evaluate(model, loader, criterion, device):
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
    cfg_path = Path(__file__).parent / "configs" / "hparams.yaml"
    with open(cfg_path, "r") as f:
        hparams = yaml.safe_load(f)

    set_seed(hparams.get("seed", 42))
    device = resolve_device(hparams.get("device", "auto"))
    print(f"Using device: {device}")

    model = build_model(hparams).to(device)
    train_loader, val_loader = get_dataloaders(hparams)
    optimizer = build_optimizer(model, hparams)
    scheduler = build_scheduler(optimizer, hparams)
    criterion = nn.CrossEntropyLoss()

    ckpt_dir = Path(__file__).parent / hparams.get("checkpoint_dir", "checkpoints")
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    best_val_acc = 0.0
    for epoch in range(1, hparams["epochs"] + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = evaluate(model, val_loader, criterion, device)
        if scheduler is not None:
            scheduler.step()
        print(f"Epoch {epoch}/{hparams['epochs']}  "
              f"train_loss={train_loss:.4f}  train_acc={train_acc:.4f}  "
              f"val_loss={val_loss:.4f}  val_acc={val_acc:.4f}")
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save({"model_state_dict": model.state_dict(), "hparams": hparams, "epoch": epoch},
                       ckpt_dir / "best.pt")

    # Final evaluation on validation set for metric reporting
    final_val_loss, final_val_acc = evaluate(model, val_loader, criterion, device)
    print(f"METRIC train_loss={train_loss:.6f}")
    print(f"METRIC val_loss={final_val_loss:.6f}")
    print(f"METRIC accuracy={final_val_acc:.6f}")
    print(f"METRIC best_accuracy={best_val_acc:.6f}")


if __name__ == "__main__":
    main()
