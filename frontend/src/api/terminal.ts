/**
 * 聊天终端 WebSocket 协议封装（plan 2026-05-01-cli-pty-pivot Task 4）。
 *
 * 与后端 ``src/server/routes/terminal.py`` 对偶：
 * - 数据帧：binary frame，xterm 输入字节直接 send；后端 read 字节再 decode-utf8。
 * - 控制帧：text frame，JSON 体 ``{type: "resize", cols, rows}`` /
 *   ``{type: "signal", name: "SIGINT"}``。
 * - 服务端 fatal：text frame，``{"type":"fatal","message":string}``——前端展示后断开。
 *
 * 不在本模块的职责
 * --------------
 * - xterm 实例创建 / fit / IME ——见 ``components/workbench/TerminalPane.tsx``。
 * - 重连策略 / onClose 触发 —— TerminalPane 持有重连 counter；本模块只暴露
 *   纯函数的 URL 构造和帧编解码，便于单测。
 */

import { API_BASE } from '../store';

export type TerminalBackend = 'claude' | 'codex';

export interface TerminalWsParams {
  backend: TerminalBackend;
  /** PTY 子进程的 cwd；不传时由后端用 active project 路径兜底。 */
  cwd?: string;
  /** provider registry 键名；不传走 Anthropic 默认（继承父进程 env）。 */
  provider?: string;
  /** 已有的 CLI session id（CLI 自带 ``~/.claude/projects/.../*.jsonl``）→ 后端
   *  spawn ``claude --resume <id>`` 接续上下文。 */
  resume?: string;
  /** 给 ``TurnTeer`` 用的 conversation id；不传则后端不写 messages 表 mirror。 */
  conversationId?: string;
}

/**
 * 把参数拼成 ``ws://.../api/terminal/{backend}?...`` URL。
 *
 * 走与 store.tsx 同样的 API_BASE 推断：dev server (port 3000) 时连 backend 8000；
 * production 同源时 host 留空。
 */
export function buildTerminalWsUrl(params: TerminalWsParams): string {
  const wsBase = httpToWs(API_BASE) || (typeof window !== 'undefined' ? deriveWsOrigin() : '');
  const search = new URLSearchParams();
  if (params.cwd) search.set('cwd', params.cwd);
  if (params.provider) search.set('provider', params.provider);
  if (params.resume) search.set('resume', params.resume);
  if (params.conversationId) search.set('conversation_id', params.conversationId);
  const qs = search.toString();
  return `${wsBase}/api/terminal/${encodeURIComponent(params.backend)}${qs ? `?${qs}` : ''}`;
}

function httpToWs(httpBase: string): string {
  if (!httpBase) return '';
  if (httpBase.startsWith('https://')) return 'wss://' + httpBase.slice('https://'.length);
  if (httpBase.startsWith('http://')) return 'ws://' + httpBase.slice('http://'.length);
  return httpBase;
}

function deriveWsOrigin(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

/** 控制帧——发给后端的 JSON 文本。 */
export type ControlFrame =
  | { type: 'resize'; cols: number; rows: number }
  | { type: 'signal'; name: 'SIGINT' };

/** 服务器发来的 fatal 帧。其余 server → client 都是裸 text（PTY str）。 */
export interface ServerFatalFrame {
  type: 'fatal';
  message: string;
}

/** 把 ControlFrame 序列化成 JSON 字符串发给后端。 */
export function encodeControl(frame: ControlFrame): string {
  return JSON.stringify(frame);
}

/**
 * 服务器 → 客户端方向：判断一段 text 是不是 fatal 控制帧。
 *
 * 普通 PTY 输出几乎不会以 ``{`` 开头（claude banner 第一字节是 ESC），所以"以 {
 * 开头并能解析成 ``{type:"fatal",message:string}``"作为识别条件足够稳。
 *
 * @returns 解析成功的 ``ServerFatalFrame`` 或 ``null``（当作普通文本写到 xterm）。
 */
export function tryParseServerFatal(text: string): ServerFatalFrame | null {
  if (!text || text[0] !== '{') return null;
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    if (parsed.type === 'fatal' && typeof parsed.message === 'string') {
      return { type: 'fatal', message: parsed.message };
    }
  } catch {
    /* not JSON — treat as raw output */
  }
  return null;
}
