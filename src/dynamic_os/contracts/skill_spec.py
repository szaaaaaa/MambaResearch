"""技能规格模块 —— 定义技能的元数据、权限和输入输出契约。

每个技能目录下的 skill.yaml 会被解析为 SkillSpec 实例。
SkillSpec 告诉系统：
- 这个技能叫什么、做什么
- 哪些角色可以使用它
- 它需要什么输入产物、产出什么类型的产物
- 它需要哪些系统权限（网络、文件系统等）
- 它可以调用哪些工具
- 执行超时限制

系统自动发现并注册技能，不需要手动配置。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.dynamic_os.contracts.route_plan import RoleId


class SkillPermissions(BaseModel):
    """技能权限声明 —— 技能运行时需要的系统能力。

    策略引擎会将技能声明的权限与 PermissionPolicy 进行交叉验证，
    确保技能不会获得超出策略允许范围的权限。
    默认所有权限关闭，需要在 skill.yaml 中显式开启。
    """

    model_config = {"frozen": True}

    # 是否需要网络访问
    network: bool = False
    # 是否需要读取文件系统
    filesystem_read: bool = False
    # 是否需要写入文件系统
    filesystem_write: bool = False
    # 是否需要远程执行能力
    remote_exec: bool = False
    # 是否需要沙箱代码执行能力
    sandbox_exec: bool = False


class SkillInputContract(BaseModel):
    """技能输入契约 —— 声明技能对输入产物的要求。

    Runtime 在执行技能前检查输入契约，确保所需产物已就绪。
    """

    model_config = {"frozen": True}

    # 必须提供的产物类型列表（全部满足才能执行）
    required: list[str] = Field(default_factory=list)
    # 至少提供其中一个的产物类型列表（满足任一即可）
    requires_any: list[str] = Field(default_factory=list)
    # 可选的产物类型列表（有则使用，无则忽略）
    optional: list[str] = Field(default_factory=list)


class SkillSpec(BaseModel):
    """技能规格 —— 技能的完整元数据定义。

    对应 skill.yaml 文件的结构。系统启动时自动扫描
    skills/builtins/ 目录下的所有 skill.yaml 并注册。
    """

    model_config = {"frozen": True}

    # 技能唯一标识符，只允许小写字母、数字和下划线
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    # 技能显示名称
    name: str
    # 技能版本号（语义化版本）
    version: str = "1.0.0"
    # 可以使用该技能的角色列表，至少一个
    applicable_roles: list[RoleId] = Field(..., min_length=1)
    # 技能功能描述
    description: str
    # 输入产物契约
    input_contract: SkillInputContract = Field(default_factory=SkillInputContract)
    # 输出产物类型列表
    output_artifacts: list[str] = Field(default_factory=list)
    # 允许调用的工具 ID 列表
    allowed_tools: list[str] = Field(default_factory=list)
    # 技能所需的系统权限
    permissions: SkillPermissions = Field(default_factory=SkillPermissions)
    # 执行超时时间（秒），范围 1~600
    timeout_sec: int = Field(120, ge=1, le=600)
