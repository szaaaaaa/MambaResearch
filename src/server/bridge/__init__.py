"""跨 CLI 桥（Stage 3 Task 5）。

把 Claude Code / Codex 这两个 backend 的会话用 ``continues`` 工具串起来——
当用户在工作台切 backend 时，本包负责：

1. 调 ``continues inspect <session-id> --write-md <path>`` 生成 markdown handoff
2. 把 handoff 文件路径写到 ``conversation_segments`` 行的 ``handoff_prompt_path``
3. 24h 后清理过期 handoff 文件

子模块：
- ``continues_runner`` — subprocess 包装 + 兜底简单 handoff
- ``segment_writer``   — Stage 1 的 conversations 模块已实现 segment CRUD，本包只
                         补"端到端切换流程"的薄编排
"""
