/**
 * <TerminalPane> —— 浏览器侧聊天面板的 xterm + WS 客户端（plan task 4）。
 *
 * 设计
 * ----
 * - 一个 ``<div>`` 容器内挂 ``Terminal`` 实例，宽高 100%；container 改尺寸用
 *   ``ResizeObserver`` 触发 ``FitAddon.fit()`` 重排，并把新 cols/rows 通过
 *   控制帧告诉后端，让 PTY size 同步。
 * - WS 协议见 ``../api/terminal.ts``：data 走 binary，control 走 JSON text；
 *   server → client 全是 text（PTY str），偶发 ``{type:"fatal",...}`` 控制帧。
 * - 重连策略：断 1 次自动重连，**断 2 次连续**触发 ``onClose``——避免 PTY
 *   crash 循环重连刷屏。重连成功后 counter 复位。
 * - IME / CJK 渲染：装 ``Unicode11Addon`` 让中文按宽度 2 量列；标准 xterm
 *   ``onData`` 已经处理 IME composition + commit，不需要额外代码。
 *
 * Props 语义
 * ---------
 * 组件**自管 WS 生命周期**——挂载即连，卸载或 backend/cwd 变更触发关闭重开。
 * ``onClose`` 在 PTY 子进程退出 / WS 连续断开时回调，**不**在卸载时调（卸载
 * 是 React 一侧的事，不需要通知父）。
 */

import React from 'react';
import { Terminal, type ITerminalOptions } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { Unicode11Addon } from '@xterm/addon-unicode11';
import '@xterm/xterm/css/xterm.css';

import {
  buildTerminalWsUrl,
  encodeControl,
  tryParseServerFatal,
} from '../../api/terminal';

export interface TerminalPaneProps {
  backend: string;
  /** 不传则由后端用 active project 路径兜底。 */
  cwd?: string;
  /** provider registry 键；不传走默认。 */
  provider?: string;
  /** ``claude --resume <id>``——续上历史 session。 */
  resumeId?: string;
  /** 写 messages 表 mirror 用；不传则不写。 */
  conversationId?: string;
  /** 外部动作注入终端的单次命令。 */
  input?: { sequence: number; text: string };
  onInputSent?: (sequence: number) => void;
  /**
   * 父容器的 className——xterm 会铺满父；外面套自己的卡片样式时改这个。
   * 默认黑底全屏。
   */
  className?: string;
  /**
   * PTY 子进程退出 / WS 连续 2 次断开时回调。React 卸载不会触发——卸载是
   * React 一侧的事，不通过 onClose 报告。
   */
  onClose?: (reason: 'pty_exit' | 'ws_unrecoverable' | 'fatal') => void;
}

const TERM_BACKGROUND = '#fbf8f2';

const DEFAULT_TERM_OPTIONS: ITerminalOptions = {
  cursorBlink: true,
  fontFamily: 'Cascadia Mono, Consolas, "Courier New", monospace',
  fontSize: 14,
  // 关键：CJK 字符宽度按 unicode 11 量，否则中文光标位置会错位
  allowProposedApi: true,
  theme: {
    background: TERM_BACKGROUND,
    foreground: '#1f1b16',
    cursor: '#8c6a3e',
    cursorAccent: TERM_BACKGROUND,
    selectionBackground: '#ece5d4',
    black: '#5a5247',
    red: '#a94335',
    green: '#4f7a4a',
    yellow: '#b6802c',
    blue: '#2f5b6b',
    magenta: '#7a3e5c',
    cyan: '#4a8094',
    white: '#5a5247',
    brightBlack: '#a39a8c',
    brightRed: '#c2633c',
    brightGreen: '#5f8f57',
    brightYellow: '#c3913f',
    brightBlue: '#4a8094',
    brightMagenta: '#8f5570',
    brightCyan: '#5b94a8',
    brightWhite: '#1f1b16',
  },
  // PTY 是子进程的"真终端"；浏览器侧不要回显，让 PTY 全权处理
  convertEol: false,
};

const RECONNECT_LIMIT = 2; // 第 2 次断开（即"断了 1 次重连失败"）后放弃

export const TerminalPane: React.FC<TerminalPaneProps> = ({
  backend,
  cwd,
  provider,
  resumeId,
  conversationId,
  input,
  onInputSent,
  className,
  onClose,
}) => {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const termRef = React.useRef<Terminal | null>(null);
  const fitRef = React.useRef<FitAddon | null>(null);
  const wsRef = React.useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = React.useRef<number>(0);
  const onCloseRef = React.useRef(onClose);
  const closedByEffectRef = React.useRef<boolean>(false);
  const encoderRef = React.useRef<TextEncoder>(new TextEncoder());
  const pendingInputRef = React.useRef<{ sequence: number; text: string } | null>(null);
  const sentInputSequenceRef = React.useRef(0);
  const onInputSentRef = React.useRef(onInputSent);

  React.useEffect(() => {
    onInputSentRef.current = onInputSent;
  }, [onInputSent]);

  const sendInput = React.useCallback((next: { sequence: number; text: string }) => {
    if (!next.text.trim() || next.sequence <= sentInputSequenceRef.current) return;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      pendingInputRef.current = next;
      return;
    }
    ws.send(encoderRef.current.encode(`${next.text}\r`));
    sentInputSequenceRef.current = next.sequence;
    pendingInputRef.current = null;
    onInputSentRef.current?.(next.sequence);
  }, []);

  React.useEffect(() => {
    if (input) sendInput(input);
  }, [input, sendInput]);

  // onClose 通过 ref 持有避免 effect 因 prop 函数变化频繁重连
  React.useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  React.useEffect(() => {
    if (!containerRef.current) return;
    closedByEffectRef.current = false;
    reconnectAttemptsRef.current = 0;

    const term = new Terminal(DEFAULT_TERM_OPTIONS);
    const fit = new FitAddon();
    const links = new WebLinksAddon();
    const unicode11 = new Unicode11Addon();
    term.loadAddon(fit);
    term.loadAddon(links);
    term.loadAddon(unicode11);
    term.unicode.activeVersion = '11';
    term.open(containerRef.current);
    const viewport = containerRef.current.querySelector<HTMLElement>('.xterm-viewport');
    if (viewport) viewport.style.backgroundColor = TERM_BACKGROUND;
    try {
      fit.fit();
    } catch {
      // 容器初始尺寸 0×0 时 fit 抛——下面 ResizeObserver 会再 fit 一次
    }

    termRef.current = term;
    fitRef.current = fit;

    const sendResize = (): void => {
      const ws = wsRef.current;
      const fitter = fitRef.current;
      const t = termRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !fitter || !t) return;
      try {
        fitter.fit();
      } catch {
        return; // 容器尺寸 0 时忽略
      }
      ws.send(encodeControl({ type: 'resize', cols: t.cols, rows: t.rows }));
    };

    // xterm 输入 → 二进制帧
    const onDataDisposable = term.onData((data: string) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(encoderRef.current.encode(data));
    });

    // container resize → fit + 通知后端
    const observer =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => sendResize())
        : null;
    if (observer && containerRef.current) {
      observer.observe(containerRef.current);
    }
    window.addEventListener('resize', sendResize);

    const connect = (): void => {
      const url = buildTerminalWsUrl({
        backend,
        cwd,
        provider,
        resume: resumeId,
        conversationId,
      });
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        // 重连成功后 counter 复位——下次再断不会立刻 onClose
        reconnectAttemptsRef.current = 0;
        sendResize();
        if (pendingInputRef.current) sendInput(pendingInputRef.current);
      };

      ws.onmessage = (event) => {
        const t = termRef.current;
        if (!t) return;
        if (typeof event.data === 'string') {
          const fatal = tryParseServerFatal(event.data);
          if (fatal) {
            t.writeln(`\r\n\x1b[31m[server fatal] ${fatal.message}\x1b[0m`);
            // fatal 表示 server 主动收尾——通知父组件，不再尝试重连
            closedByEffectRef.current = true;
            try {
              ws.close();
            } catch {
              /* ignore */
            }
            onCloseRef.current?.('fatal');
            return;
          }
          t.write(event.data);
        } else {
          // 当前后端只发 text；保留 ArrayBuffer 兜底
          t.write(new Uint8Array(event.data as ArrayBuffer));
        }
      };

      ws.onerror = () => {
        // onerror 后浏览器一定会再触发 onclose，不在这里改 counter
      };

      ws.onclose = (event) => {
        if (closedByEffectRef.current) return;
        if (event.code === 1000) {
          onCloseRef.current?.('pty_exit');
          return;
        }
        reconnectAttemptsRef.current += 1;
        if (reconnectAttemptsRef.current >= RECONNECT_LIMIT) {
          onCloseRef.current?.('ws_unrecoverable');
          return;
        }
        // 第一次断开 → 立刻重连一次
        const t = termRef.current;
        if (t) {
          t.writeln('\r\n\x1b[33m[reconnecting...]\x1b[0m');
        }
        connect();
      };
    };

    connect();

    return () => {
      closedByEffectRef.current = true;
      onDataDisposable.dispose();
      window.removeEventListener('resize', sendResize);
      observer?.disconnect();
      // 关键：把所有 4 个 handler 都 null 掉再 close。
      // closedByEffectRef 在新 effect run 时会被重置为 false，旧 ws 的 onclose
      // 会异步在那之后才 fire——读到 false 就会触发 ghost reconnect，导致同时
      // 起 2 个 PtyProcess 抢 ConPTY 资源。null handlers 是确定性的"切干净"。
      const dyingWs = wsRef.current;
      if (dyingWs) {
        dyingWs.onopen = null;
        dyingWs.onmessage = null;
        dyingWs.onerror = null;
        dyingWs.onclose = null;
        try {
          dyingWs.close();
        } catch {
          /* ignore */
        }
      }
      wsRef.current = null;
      try {
        term.dispose();
      } catch {
        /* ignore */
      }
      termRef.current = null;
      fitRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backend, cwd, provider, resumeId, conversationId, sendInput]);

  return (
    <div
      ref={containerRef}
      className={className ?? 'h-full w-full bg-[var(--bg-2)] p-2'}
    />
  );
};

export default TerminalPane;
