"""本地实验执行集成。

不复用 dynamic_os 的 DAG runtime（那是 Stage 5 的事）；这里只做"单脚本本地
跑 + 进度回报 + 取消"的 thin wrapper：

* ``runner.py`` 管理 subprocess + 内存中的 metrics/log buffer
* ``mcp_server.py`` 暴露 5 个 MCP tools（run_local / status / logs / cancel / metrics）

子进程协议：
* stdout 任何行包含 ``[[METRIC]] {"name":...,"value":...,"step":...}``
  会被解析为 metric 入 buffer
* 其他行原样进 log buffer
* 退出码 0 → done；非 0 → error；外部 cancel → cancelled
"""
