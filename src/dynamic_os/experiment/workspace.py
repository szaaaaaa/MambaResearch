"""实验工作区管理 - 初始化、快照、恢复、读写可变文件。

本模块是实验子系统的核心，提供实验工作区的全生命周期管理。
在 Dynamic Research OS 中，每次实验运行（run）都会创建一个隔离的工作区目录，
其中包含训练脚本、评估脚本、模型定义和超参数配置等文件。

核心概念：
- **工作区（workspace）**：一个独立的目录，包含实验所需的全部代码和配置。
  由模板初始化，每次实验运行拥有独立的工作区副本。
- **可变文件（mutable files）**：工作区中允许 AI agent 在实验迭代间修改的文件
  （如超参数配置、模型定义）。其他文件在运行期间保持不变。
- **快照（snapshot）**：可变文件在某一时刻的完整状态备份，用于在实验失败时
  回滚到已知的良好状态。

典型调用流程：
1. ``parse_workspace_config()`` 解析实验计划中的工作区配置
2. ``init_workspace()`` 从模板创建工作区目录
3. AI agent 通过 ``read_mutable_files()`` / ``write_mutable_files()`` 读写可变文件
4. 每轮迭代前用 ``snapshot_mutable()`` 保存状态，失败时用 ``restore_snapshot()`` 回滚
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

# 内置默认模板目录，包含标准的 CIFAR-10 训练/评估代码
_BUILTIN_TEMPLATE_DIR: Path = Path(__file__).parent / "templates" / "default"


@dataclass(frozen=True)
class WorkspaceConfig:
    """声明实验工作区的结构与约束。

    该配置类定义了工作区的模板来源、允许修改的文件列表以及入口脚本路径。
    使用 frozen=True 确保配置在创建后不可变，避免运行期间的意外修改。

    属性
    ----------
    template : str
        模板类型，``"builtin"`` 使用内置默认模板，``"custom"`` 使用自定义目录。
    custom_path : str
        当 template="custom" 时，指定自定义模板目录的路径。
    mutable_files : list[str]
        允许 AI agent 在实验迭代间修改的文件相对路径列表。
    entry_point : str
        训练入口脚本的文件名，默认为 ``"train.py"``。
    eval_script : str
        评估脚本的文件名，默认为 ``"evaluate.py"``。
    """

    template: str = "builtin"                        # 模板类型：builtin 或 custom
    custom_path: str = ""                            # 自定义模板路径（仅 custom 模式使用）
    mutable_files: list[str] = field(default_factory=list)  # 可变文件列表
    entry_point: str = "train.py"                    # 训练入口脚本
    eval_script: str = "evaluate.py"                 # 评估脚本


def init_workspace(config: WorkspaceConfig, run_dir: str | Path) -> Path:
    """将工作区模板复制到 *run_dir*/experiment_workspace 并返回其路径。

    当 ``template="builtin"`` 时使用内置默认模板。
    当 ``template="custom"`` 时复制 *config.custom_path* 指定的目录；
    该目录必须存在且包含 *entry_point* 和 *eval_script*。

    参数
    ----------
    config : WorkspaceConfig
        工作区配置，指定模板类型和相关路径。
    run_dir : str | Path
        本次实验运行的根目录，工作区将创建在其下的 ``experiment_workspace`` 子目录。

    返回
    -------
    Path
        创建好的工作区目录的绝对路径。

    异常
    ------
    FileNotFoundError
        模板目录不存在，或自定义模板中缺少入口脚本/评估脚本。
    ValueError
        模板类型既不是 ``"builtin"`` 也不是 ``"custom"``。
    """
    run_dir = Path(run_dir)
    dest = run_dir / "experiment_workspace"  # 工作区固定命名，便于后续定位

    if config.template == "builtin":
        # 使用内置模板：包含标准的 CIFAR-10 CNN 训练/评估代码
        source = _BUILTIN_TEMPLATE_DIR
        if not source.is_dir():
            raise FileNotFoundError(
                f"Built-in template directory not found: {source}"
            )
        shutil.copytree(source, dest, dirs_exist_ok=True)
    elif config.template == "custom":
        # 使用自定义模板：需验证目录存在且包含必要的入口文件
        source = Path(config.custom_path)
        if not source.is_dir():
            raise FileNotFoundError(
                f"Custom workspace path does not exist: {source}"
            )
        if not (source / config.entry_point).is_file():
            raise FileNotFoundError(
                f"Entry point '{config.entry_point}' not found in {source}"
            )
        if not (source / config.eval_script).is_file():
            raise FileNotFoundError(
                f"Eval script '{config.eval_script}' not found in {source}"
            )
        shutil.copytree(source, dest, dirs_exist_ok=True)
    else:
        raise ValueError(
            f"Unknown template type '{config.template}'; expected 'builtin' or 'custom'"
        )

    return dest


def read_mutable_files(
    workspace: Path, mutable_files: list[str]
) -> dict[str, str]:
    """返回 *workspace* 中每个可变文件的 ``{relative_path: content}`` 字典。

    不存在的文件以空字符串值包含在内，这样调用方无需额外判断文件是否存在。
    该函数通常在实验迭代开始时调用，让 AI agent 读取当前的代码和配置。

    参数
    ----------
    workspace : Path
        工作区目录路径。
    mutable_files : list[str]
        要读取的可变文件相对路径列表。

    返回
    -------
    dict[str, str]
        以相对路径为键、文件内容为值的字典。文件不存在时值为空字符串。
    """
    result: dict[str, str] = {}
    for rel in mutable_files:
        fp = workspace / rel
        if fp.is_file():
            result[rel] = fp.read_text(encoding="utf-8")
        else:
            result[rel] = ""
    return result


def write_mutable_files(
    workspace: Path, changes: dict[str, str]
) -> None:
    """将 *changes* (``{relative_path: content}``) 写入 *workspace*。

    父目录不存在时会自动创建。该函数是 AI agent 修改实验代码的唯一入口，
    确保所有写操作都经过统一路径。

    参数
    ----------
    workspace : Path
        工作区目录路径。
    changes : dict[str, str]
        以相对路径为键、新文件内容为值的字典。
    """
    for rel, content in changes.items():
        fp = workspace / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")


def snapshot_mutable(
    workspace: Path, mutable_files: list[str]
) -> dict[str, str]:
    """捕获所有可变文件的当前状态作为保存点字典。

    在每轮实验迭代开始前调用，保存当前状态以便失败时回滚。
    返回的字典可直接传给 ``restore_snapshot()`` 进行恢复。

    参数
    ----------
    workspace : Path
        工作区目录路径。
    mutable_files : list[str]
        要快照的可变文件相对路径列表。

    返回
    -------
    dict[str, str]
        可变文件的完整状态快照。
    """
    return read_mutable_files(workspace, mutable_files)


def restore_snapshot(
    workspace: Path, snapshot: dict[str, str]
) -> None:
    """通过写回所有文件来恢复之前捕获的快照。

    当实验迭代失败（如训练崩溃、指标下降）时调用，
    将可变文件回滚到上一次快照的状态。

    参数
    ----------
    workspace : Path
        工作区目录路径。
    snapshot : dict[str, str]
        由 ``snapshot_mutable()`` 返回的状态快照。
    """
    write_mutable_files(workspace, snapshot)


def parse_workspace_config(raw: dict) -> WorkspaceConfig:
    """从原始字典（如实验计划 YAML）构建 :class:`WorkspaceConfig`。

    缺失的键使用 dataclass 默认值。该函数是配置解析的统一入口，
    确保从 YAML 配置到 Python 对象的转换有一致的默认值处理。

    参数
    ----------
    raw : dict
        原始配置字典，通常来自实验计划的 YAML 文件。
        支持的键：template, custom_path, mutable_files, entry_point, eval_script。

    返回
    -------
    WorkspaceConfig
        解析后的工作区配置对象。
    """
    return WorkspaceConfig(
        template=raw.get("template", "builtin"),
        custom_path=raw.get("custom_path", ""),
        mutable_files=list(raw.get("mutable_files", [])),
        entry_point=raw.get("entry_point", "train.py"),
        eval_script=raw.get("eval_script", "evaluate.py"),
    )
