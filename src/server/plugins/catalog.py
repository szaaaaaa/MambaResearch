"""仓库内受信任插件的唯一 catalog。"""

from __future__ import annotations

from src.server.kernel.contracts import Plugin
from src.server.plugins.core_http import CoreHttpPlugin
from src.server.plugins.research import builtin_research_plugins
from src.server.plugins.workbench import WorkbenchPlugin


def builtin_plugins() -> tuple[Plugin, ...]:
    return (
        CoreHttpPlugin(),
        WorkbenchPlugin(),
        *builtin_research_plugins(),
    )
