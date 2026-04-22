import type { SlashCommand } from './types';

/**
 * Claude Code CLI 的全部 slash 命令元数据。
 *
 * - ``frontend`` 命令的实际行为由 ``dispatch.ts`` 中同名 handler 实现。
 * - ``deferred`` 命令在本 Task（6a）中只占位，点击后弹 InfoPanel 说明尚未实现，
 *   真实逻辑由 6b（会话生命周期）/ 6c（model / mcp / permissions）/ 6d（compact / resume）落地。
 * - ``cli-only`` 命令 Web 下无意义，infoBody 直接给出 CLI 等价操作提示。
 *
 * handlerKey 与 dispatch 表里的键一一对应；cli-only / deferred 可省略。
 */
const CLI_ONLY_HINT = '此命令仅原生 CLI 可用，请在终端运行 `claude` 后使用。';

const DEFERRED_HINT =
  '此命令正在实现中，将在 Task 6b / 6c / 6d 落地——届时会连上真实的后端会话控制。';

export const SLASH_COMMANDS: SlashCommand[] = [
  // ── 展示 / 信息面板 ──────────────────────────────────────────────
  {
    id: 'help',
    description: '列出全部 slash 命令及说明',
    scope: 'frontend',
    handlerKey: 'help',
  },
  {
    id: 'status',
    description: '查看当前会话状态（session / model / tokens / cost）',
    scope: 'frontend',
    handlerKey: 'status',
  },
  {
    id: 'cost',
    description: '查看累计 token 与费用',
    scope: 'frontend',
    handlerKey: 'cost',
  },
  {
    id: 'memory',
    description: '编辑项目 CLAUDE.md（UI 就位，读写端点由 6b 实现）',
    scope: 'frontend',
    handlerKey: 'memory',
  },
  {
    id: 'config',
    description: '调整前端显示设置（Markdown / 思考折叠 / 原始事件）',
    scope: 'frontend',
    handlerKey: 'config',
  },
  {
    id: 'agents',
    description: '查看已注册的 Skill 列表',
    scope: 'frontend',
    handlerKey: 'agents',
  },

  // ── 发送特殊 prompt ─────────────────────────────────────────────
  {
    id: 'init',
    description: '让 Claude 分析代码库并写入 CLAUDE.md',
    scope: 'frontend',
    handlerKey: 'init',
  },
  {
    id: 'review',
    description: '让 Claude 审阅当前未提交 diff',
    scope: 'frontend',
    handlerKey: 'review',
  },

  // ── Info 类（外链说明） ─────────────────────────────────────────
  {
    id: 'bug',
    description: '反馈 bug',
    scope: 'frontend',
    handlerKey: 'info',
    infoBody:
      '遇到问题？可在 GitHub Issues 提交报告，附上 session id、复现步骤、完整错误栈。',
    infoLink: { text: 'Claude Code Issues', url: 'https://github.com/anthropics/claude-code/issues' },
  },
  {
    id: 'release-notes',
    description: '查看版本更新说明',
    scope: 'frontend',
    handlerKey: 'info',
    infoBody: 'Web 工作台目前与本地 Claude Agent SDK 共用版本；最新发布说明请参考官方仓库。',
    infoLink: { text: 'Claude Code Releases', url: 'https://github.com/anthropics/claude-code/releases' },
  },
  {
    id: 'upgrade',
    description: '检查 / 升级 CLI 版本',
    scope: 'frontend',
    handlerKey: 'info',
    infoBody:
      '升级需要在原生 CLI 终端执行 `claude upgrade`；Web 工作台跟随本机 SDK 版本，重启后端即可生效。',
  },
  {
    id: 'doctor',
    description: '运行环境诊断',
    scope: 'frontend',
    handlerKey: 'info',
    infoBody:
      '诊断命令需要访问 shell，请在原生 CLI 终端执行 `claude doctor`；Web 下可用 /status 查看当前会话关键字段。',
  },
  {
    id: 'feedback',
    description: '提交使用反馈',
    scope: 'frontend',
    handlerKey: 'info',
    infoBody: '欢迎通过 GitHub Issues 留下使用反馈，帮助我们改进 Claude Code。',
    infoLink: { text: 'Claude Code Issues', url: 'https://github.com/anthropics/claude-code/issues' },
  },
  {
    id: 'hooks',
    description: '查看 hooks 机制说明',
    scope: 'frontend',
    handlerKey: 'info',
    infoBody:
      'Hooks 是原生 CLI 的 shell 事件钩子；Web 工作台不执行 shell 钩子，相关集成请在原生 CLI 下配置。',
  },

  // ── 待实现（6b / 6c / 6d） ──────────────────────────────────────
  {
    id: 'clear',
    description: '清空会话上下文（6b 实现）',
    scope: 'deferred',
  },
  {
    id: 'exit',
    description: '结束当前会话（6b 实现）',
    scope: 'deferred',
  },
  {
    id: 'add-dir',
    description: '为会话追加允许的工作目录（6b 实现）',
    scope: 'deferred',
  },
  {
    id: 'model',
    description: '切换会话使用的模型（6c 实现）',
    scope: 'deferred',
  },
  {
    id: 'mcp',
    description: '查看已挂载的 MCP server（6c 实现）',
    scope: 'deferred',
  },
  {
    id: 'permissions',
    description: '切换权限模式（6c 实现）',
    scope: 'deferred',
  },
  {
    id: 'compact',
    description: '压缩会话上下文（6d 实现）',
    scope: 'deferred',
  },
  {
    id: 'resume',
    description: '恢复历史会话（依赖 Task 9 Sessions 面板）',
    scope: 'deferred',
  },

  // ── 仅原生 CLI 可用 ─────────────────────────────────────────────
  {
    id: 'ide',
    description: 'IDE 集成（仅 CLI）',
    scope: 'cli-only',
    handlerKey: 'cli-only',
    infoBody: CLI_ONLY_HINT,
  },
  {
    id: 'vim',
    description: 'Vim 模式（仅 CLI）',
    scope: 'cli-only',
    handlerKey: 'cli-only',
    infoBody: CLI_ONLY_HINT,
  },
  {
    id: 'terminal-setup',
    description: '配置终端 keybind（仅 CLI）',
    scope: 'cli-only',
    handlerKey: 'cli-only',
    infoBody: CLI_ONLY_HINT,
  },
  {
    id: 'install-github-app',
    description: '安装 GitHub App（仅 CLI）',
    scope: 'cli-only',
    handlerKey: 'cli-only',
    infoBody: CLI_ONLY_HINT,
  },
  {
    id: 'migrate-installer',
    description: '迁移 installer（仅 CLI）',
    scope: 'cli-only',
    handlerKey: 'cli-only',
    infoBody: CLI_ONLY_HINT,
  },
  {
    id: 'login',
    description: '账户登录（仅 CLI）',
    scope: 'cli-only',
    handlerKey: 'cli-only',
    infoBody: CLI_ONLY_HINT,
  },
  {
    id: 'logout',
    description: '账户登出（仅 CLI）',
    scope: 'cli-only',
    handlerKey: 'cli-only',
    infoBody: CLI_ONLY_HINT,
  },
  {
    id: 'pr-comments',
    description: '查看 PR 评论（仅 CLI）',
    scope: 'cli-only',
    handlerKey: 'cli-only',
    infoBody: CLI_ONLY_HINT,
  },
];

export const DEFERRED_MESSAGE = DEFERRED_HINT;

/**
 * 构建 id → SlashCommand 的 O(1) 查表字典。
 * autocomplete 用，不暴露 handler 细节。
 */
export function buildCommandIndex(): Map<string, SlashCommand> {
  const map = new Map<string, SlashCommand>();
  for (const cmd of SLASH_COMMANDS) {
    map.set(cmd.id, cmd);
    for (const alias of cmd.aliases ?? []) {
      map.set(alias, cmd);
    }
  }
  return map;
}
