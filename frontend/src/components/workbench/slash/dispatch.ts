import type { ClaudeCodeActivityId, ClaudeCodePanel } from '../../../types';
import { DEFERRED_MESSAGE, SLASH_COMMANDS, buildCommandIndex } from './registry';
import type { SlashCommand } from './types';

/**
 * Dispatch 执行期所需的副作用回调。
 *
 * - ``openPanel`` 打开 modal（对应 store.ccOpenPanel）。
 * - ``submitPrompt`` 像用户手打一条消息一样发给 Claude（/init / /review 用）。
 * - ``runBackendCommand`` 发起 ``POST /api/claude-code/sessions/{id}/command``，
 *   供 /clear /exit /add-dir 调用；由 WorkbenchTab 闭包注入当前 session id 与
 *   本地状态收尾逻辑。``args`` 形如 ``{path: '...'}`` 直接透传为 body.args。
 */
export interface DispatchContext {
  openPanel: (panel: ClaudeCodePanel) => void;
  submitPrompt: (text: string) => void;
  runBackendCommand: (
    command: string,
    args?: Record<string, unknown>,
  ) => Promise<void>;
  /**
   * 切换 WorkbenchShell 的主边栏（/resume 用来聚焦 Sessions 面板）。
   * 传入 null 收起面板，传入具体 activity id 打开。
   */
  openActivity: (activity: ClaudeCodeActivityId) => void;
}

/**
 * dispatch 返回值——告诉 WorkbenchTab 输入框的后续处理逻辑。
 *
 * - ``consumed``: 命令已处理完（打开了面板 / 发出了 prompt），输入框应清空。
 * - ``unknown``: 未识别的命令；dispatch 已经顺手打开了一个"未知命令"的 InfoPanel。
 */
export type DispatchResult = { kind: 'consumed' } | { kind: 'unknown' };

/**
 * /init 的标准 prompt——对齐 Claude Code CLI 行为。
 */
const INIT_PROMPT =
  'Please analyze this codebase and create a CLAUDE.md file containing:\n' +
  '1. Build/lint/test commands - especially for running a single test\n' +
  '2. Code style guidelines including imports, formatting, types, naming conventions, error handling, etc.\n\n' +
  'The file should be concise (~20 lines). If there is already a CLAUDE.md, improve it.';

/**
 * /review 的标准 prompt——让 Claude 审阅当前未提交 diff。
 */
const REVIEW_PROMPT =
  'Please review the pending changes (git diff) for correctness, style, and potential issues. Be concise.';

const COMMAND_INDEX = buildCommandIndex();

/**
 * 按 scope 与 handlerKey 分发命令。
 *
 * 约定：
 * - ``scope === 'frontend'``：按 handlerKey 进入具体 handler；
 * - ``scope === 'cli-only'``：统一弹 InfoPanel，文本来自 command.infoBody；
 * - ``scope === 'deferred'``：统一弹 "实现中" InfoPanel；
 * - 其他情况（含未知命令、未来的 backend scope 占位）：返回 unknown，顶层决定如何提示。
 */
export function dispatchSlashCommand(
  input: string,
  ctx: DispatchContext,
): DispatchResult {
  const { id, args } = parseSlashInput(input);
  if (!id) {
    // 只输入了 "/"：把 /help 当默认
    ctx.openPanel({ kind: 'help' });
    return { kind: 'consumed' };
  }

  const cmd = COMMAND_INDEX.get(id);
  if (!cmd) {
    ctx.openPanel({
      kind: 'info',
      title: `未知命令 /${id}`,
      body: '该命令不在已注册列表中。输入 /help 查看全部命令。',
    });
    return { kind: 'unknown' };
  }

  if (cmd.scope === 'deferred') {
    ctx.openPanel({
      kind: 'info',
      title: `/${cmd.id}`,
      body: DEFERRED_MESSAGE,
    });
    return { kind: 'consumed' };
  }

  if (cmd.scope === 'cli-only') {
    ctx.openPanel({
      kind: 'info',
      title: `/${cmd.id}`,
      body: cmd.infoBody ?? '此命令仅原生 CLI 可用。',
    });
    return { kind: 'consumed' };
  }

  if (cmd.scope === 'frontend') {
    runFrontendHandler(cmd, ctx, args);
    return { kind: 'consumed' };
  }

  if (cmd.scope === 'backend') {
    runBackendHandler(cmd, ctx, args);
    return { kind: 'consumed' };
  }

  // 兜底（理论不可达，所有 SlashScope 分支都已覆盖）
  ctx.openPanel({
    kind: 'info',
    title: `/${cmd.id}`,
    body: '该命令尚未绑定处理逻辑。',
  });
  return { kind: 'unknown' };
}

/**
 * backend scope 的二级分发（Task 6b：/clear /exit /add-dir）。
 *
 * 所有 handler 都把具体 HTTP 通信委托给 ctx.runBackendCommand，由 WorkbenchTab
 * 闭包注入 session id / API_BASE / 本地状态收尾；本函数只负责按命令拆 args。
 */
function runBackendHandler(
  cmd: SlashCommand,
  ctx: DispatchContext,
  args: string,
): void {
  switch (cmd.handlerKey) {
    case 'clear':
      void ctx.runBackendCommand('clear');
      return;
    case 'exit':
      void ctx.runBackendCommand('exit');
      return;
    case 'add-dir': {
      const path = args.trim();
      if (!path) {
        ctx.openPanel({
          kind: 'info',
          title: '/add-dir',
          body: '用法：/add-dir <path>\n\n指定要追加的工作目录，必须位于项目根下。',
        });
        return;
      }
      void ctx.runBackendCommand('add-dir', { path });
      return;
    }
    default:
      ctx.openPanel({
        kind: 'info',
        title: `/${cmd.id}`,
        body: `backend 命令已注册但未绑定 handler（handlerKey=${cmd.handlerKey ?? 'none'}）。`,
      });
  }
}

/**
 * 前端 scope 的二级分发。handler 有三类：
 *
 * 1. 打开某种 panel（help / status / cost / memory / config / agents）；
 * 2. 发送特殊 prompt（init / review）；
 * 3. 通用 info 展示（info / cli-only —— 后者已在上层分流，这里只剩 info）。
 */
function runFrontendHandler(
  cmd: SlashCommand,
  ctx: DispatchContext,
  args: string,
): void {
  switch (cmd.handlerKey) {
    case 'help':
      ctx.openPanel({ kind: 'help' });
      return;
    case 'status':
      ctx.openPanel({ kind: 'status' });
      return;
    case 'cost':
      ctx.openPanel({ kind: 'cost' });
      return;
    case 'memory':
      ctx.openPanel({ kind: 'memory' });
      return;
    case 'config':
      ctx.openPanel({ kind: 'config' });
      return;
    case 'agents':
      ctx.openPanel({ kind: 'agents' });
      return;
    case 'model':
      ctx.openPanel({ kind: 'model' });
      return;
    case 'mcp':
      ctx.openPanel({ kind: 'mcp' });
      return;
    case 'permissions':
      ctx.openPanel({ kind: 'permissions' });
      return;
    case 'init':
      ctx.submitPrompt(INIT_PROMPT);
      return;
    case 'review':
      ctx.submitPrompt(REVIEW_PROMPT);
      return;
    case 'compact': {
      const suffix = args ? ' ' + args : '';
      ctx.submitPrompt('/compact' + suffix);
      return;
    }
    case 'resume':
      ctx.openActivity('sessions');
      return;
    case 'info':
      ctx.openPanel({
        kind: 'info',
        title: `/${cmd.id}`,
        body: cmd.infoBody ?? cmd.description,
        link: cmd.infoLink,
      });
      return;
    case 'cli-only':
      // 理论上走不到——上层已按 scope 分流；留个兜底避免静默漏 case。
      ctx.openPanel({
        kind: 'info',
        title: `/${cmd.id}`,
        body: cmd.infoBody ?? '此命令仅原生 CLI 可用。',
      });
      return;
    default:
      ctx.openPanel({
        kind: 'info',
        title: `/${cmd.id}`,
        body: `命令已注册但未绑定 handler（handlerKey=${cmd.handlerKey ?? 'none'}）。`,
      });
  }
}

/**
 * 解析 "/help" / "/status foo bar" 这种输入。
 *
 * 返回去掉前导 "/" 后的 id 与余下参数；无 id 时 id=''。
 * 大小写在这一步归一化：Claude Code CLI 的 slash 命令全部小写。
 */
function parseSlashInput(input: string): { id: string; args: string } {
  const trimmed = input.trim();
  if (!trimmed.startsWith('/')) return { id: '', args: '' };
  const body = trimmed.slice(1);
  const spaceIdx = body.search(/\s/);
  if (spaceIdx < 0) return { id: body.toLowerCase(), args: '' };
  return {
    id: body.slice(0, spaceIdx).toLowerCase(),
    args: body.slice(spaceIdx + 1).trim(),
  };
}

/**
 * autocomplete 用：按前缀模糊匹配命令列表。
 *
 * 简单前缀 + 描述模糊——命令数只有三十出头，无需上 fuzzy 打分库。
 */
export function matchSlashCommands(query: string, limit = 10): SlashCommand[] {
  const q = query.trim().toLowerCase();
  if (!q) return SLASH_COMMANDS.slice(0, limit);
  const starts: SlashCommand[] = [];
  const contains: SlashCommand[] = [];
  for (const cmd of SLASH_COMMANDS) {
    const id = cmd.id.toLowerCase();
    if (id.startsWith(q)) {
      starts.push(cmd);
      continue;
    }
    if (id.includes(q) || cmd.description.toLowerCase().includes(q)) {
      contains.push(cmd);
    }
  }
  return [...starts, ...contains].slice(0, limit);
}
