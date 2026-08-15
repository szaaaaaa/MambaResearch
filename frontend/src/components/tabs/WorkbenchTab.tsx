import React from 'react';
import { LogOut, MessagesSquare, RefreshCw, Terminal } from 'lucide-react';
import { API_BASE } from '../../store';
import {
  type ConversationSummary,
} from '../../api/conversations';
import { getAuthStatus, type AuthStatus, type Project } from '../../api/projects';
import {
  getCapabilityInventory,
  type BackendDescriptor,
  type CapabilityInventory,
} from '../../api/terminal';
import { useContextualTabs } from '../../store/contextual';
import { ClassifyHintBar } from '../workbench/ClassifyHintBar';
import { TerminalPane } from '../workbench/TerminalPane';
import { SessionsPanel } from '../workbench/shell/activities/SessionsPanel';

export interface WorkbenchTabProps {
  activeProject: Project;
  conversation?: ConversationSummary;
}

interface TerminalInput {
  sequence: number;
  text: string;
}

async function getResumeId(conversation: ConversationSummary): Promise<string | null> {
  const response = await fetch(`${API_BASE}/api/conversations/${conversation.id}/segments`);
  if (!response.ok) throw new Error(await response.text());
  const body = (await response.json()) as {
    segments: Array<{ backend: string; cli_session_id: string; segment_index: number }>;
  };
  const matches = body.segments.filter((segment) => segment.backend === conversation.backend);
  const latest = matches.reduce<typeof matches[number] | null>(
    (current, segment) => (!current || segment.segment_index > current.segment_index ? segment : current),
    null,
  );
  return latest?.cli_session_id ?? null;
}

export const WorkbenchTab: React.FC<WorkbenchTabProps> = ({ activeProject, conversation }) => {
  const [inventory, setInventory] = React.useState<CapabilityInventory | null>(null);
  const [authStatus, setAuthStatus] = React.useState<AuthStatus | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [backendId, setBackendId] = React.useState<string | null>(conversation?.backend ?? null);
  const [activeConversation, setActiveConversation] = React.useState<ConversationSummary | null>(null);
  const [resumeId, setResumeId] = React.useState<string | null>(null);
  const [cwd, setCwd] = React.useState(activeProject.path);
  const [restartTick, setRestartTick] = React.useState(0);
  const [terminalError, setTerminalError] = React.useState<string | null>(null);
  const [sessionsOpen, setSessionsOpen] = React.useState(false);
  const [cwdModalOpen, setCwdModalOpen] = React.useState(false);
  const [cwdDraft, setCwdDraft] = React.useState(activeProject.path);
  const [terminalInput, setTerminalInput] = React.useState<TerminalInput | null>(null);
  const creationPending = React.useRef(false);
  const inputSequence = React.useRef(0);
  const { pendingComposerPrompt, consumeComposerPrompt } = useContextualTabs();

  const refreshRuntime = React.useCallback(async () => {
    const [capabilities, auth] = await Promise.allSettled([
      getCapabilityInventory(),
      getAuthStatus(),
    ]);
    if (capabilities.status === 'fulfilled') {
      setInventory(capabilities.value);
      setLoadError(null);
    } else {
      setInventory(null);
      setLoadError(String(capabilities.reason));
    }
    setAuthStatus(auth.status === 'fulfilled' ? auth.value : null);
  }, []);

  React.useEffect(() => {
    void refreshRuntime();
  }, [refreshRuntime]);

  React.useEffect(() => {
    let cancelled = false;
    setCwd(activeProject.path);
    setResumeId(null);
    setTerminalError(null);
    setActiveConversation(null);
    if (conversation) {
      setBackendId(conversation.backend);
      void getResumeId(conversation)
        .then((nextResumeId) => {
          if (cancelled) return;
          setResumeId(nextResumeId);
          setActiveConversation(conversation);
          setLoadError(null);
          setRestartTick((tick) => tick + 1);
        })
        .catch((error) => {
          if (!cancelled) setLoadError(`加载会话失败：${String(error)}`);
        });
    } else {
      setBackendId(null);
    }
    return () => { cancelled = true; };
  }, [activeProject.id, activeProject.path, conversation]);

  React.useEffect(() => {
    if (pendingComposerPrompt === null) return;
    const text = consumeComposerPrompt();
    if (text === null) return;
    inputSequence.current += 1;
    setTerminalInput({ sequence: inputSequence.current, text });
  }, [consumeComposerPrompt, pendingComposerPrompt]);

  const enabledBackends = inventory?.backends ?? [];
  const enabledBackend = enabledBackends.find((backend) => backend.id === backendId) ?? null;
  const activeBackend = activeConversation?.backend ?? backendId;

  React.useEffect(() => {
    if (conversation || enabledBackends.length === 0 || backendId !== null) return;
    setBackendId(enabledBackends[0].id);
  }, [backendId, conversation, enabledBackends]);

  const createConversation = React.useCallback(async (backend: BackendDescriptor, nextCwd = cwd) => {
    if (creationPending.current) return;
    creationPending.current = true;
    try {
      const response = await fetch(`${API_BASE}/api/conversations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: activeProject.id, backend: backend.id }),
      });
      if (!response.ok) throw new Error(await response.text());
      const created = (await response.json()) as ConversationSummary;
      setActiveConversation(created);
      setBackendId(created.backend);
      setCwd(nextCwd);
      setResumeId(null);
      setTerminalError(null);
      setRestartTick((tick) => tick + 1);
    } catch (error) {
      setLoadError(`新建会话失败：${String(error)}`);
    } finally {
      creationPending.current = false;
    }
  }, [activeProject.id, cwd]);

  React.useEffect(() => {
    if (conversation || !enabledBackend || activeConversation !== null) return;
    void createConversation(enabledBackend);
  }, [activeConversation, conversation, createConversation, enabledBackend]);

  const switchConversation = React.useCallback(async (next: ConversationSummary) => {
    if (!enabledBackends.some((backend) => backend.id === next.backend)) return;
    setActiveConversation(null);
    try {
      const nextResumeId = await getResumeId(next);
      setBackendId(next.backend);
      setResumeId(nextResumeId);
      setTerminalError(null);
      setLoadError(null);
      setActiveConversation(next);
      setRestartTick((tick) => tick + 1);
    } catch (error) {
      setLoadError(`加载会话失败：${String(error)}`);
    }
  }, [enabledBackends]);

  const submitCwdChange = React.useCallback(async () => {
    const next = cwdDraft.trim();
    if (!next || !enabledBackend) return;
    await createConversation(enabledBackend, next);
    setCwdModalOpen(false);
  }, [createConversation, cwdDraft, enabledBackend]);

  const auth = enabledBackend ? authStatus?.backends[enabledBackend.id] : undefined;
  const authLabel = auth
    ? auth.status === 'logged_in'
      ? `${enabledBackend?.label} CLI 已登录`
      : auth.status === 'not_logged_in'
        ? `${enabledBackend?.label} CLI 未登录`
        : auth.status === 'cli_not_found'
          ? `未检测到 ${enabledBackend?.label} CLI`
          : `${enabledBackend?.label} CLI 状态未知`
    : '认证状态未加载';

  if (!inventory) {
    return <WorkbenchMessage text={loadError ?? '正在加载可用 backend…'} />;
  }

  if (enabledBackends.length === 0) {
    return <WorkbenchMessage text="未启用 backend" />;
  }

  if (!enabledBackend || (activeConversation && activeConversation.backend !== enabledBackend.id)) {
    return <WorkbenchMessage text={`${activeBackend ?? '当前'} 插件未启用；历史元数据仍可查看，但不能启动或 resume。`} />;
  }

  return (
    <div className="rb-chat" style={{ position: 'relative' }}>
      {cwdModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" onClick={() => setCwdModalOpen(false)}>
          <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl" onClick={(event) => event.stopPropagation()}>
            <h4 className="text-sm font-semibold text-slate-900">修改工作目录</h4>
            <p className="mt-1 text-[12px] leading-5 text-slate-600">将在新目录创建一条新的 {enabledBackend.label} 会话。</p>
            <input
              type="text"
              autoFocus
              value={cwdDraft}
              onChange={(event) => setCwdDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void submitCwdChange();
                if (event.key === 'Escape') setCwdModalOpen(false);
              }}
              className="mt-4 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-[13px]"
            />
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setCwdModalOpen(false)} className="rounded-md border border-slate-200 px-3 py-1 text-[12px] text-slate-700">取消</button>
              <button type="button" onClick={() => void submitCwdChange()} disabled={!cwdDraft.trim()} className="rounded-md bg-slate-900 px-3 py-1 text-[12px] font-medium text-white">切换 cwd</button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="rb-chat-head">
        <div className="rb-chat-title" style={{ minWidth: 0, flex: 1 }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Terminal size={16} style={{ color: 'var(--fg-3)' }} />
            {resumeId ? `Workbench · ${enabledBackend.label} ${resumeId.slice(0, 8)} (resumed)` : `Workbench · ${enabledBackend.label} PTY`}
          </h2>
          <div className="rb-chat-meta">
            <button type="button" className="rb-cli-pill mono" onClick={() => { setCwdDraft(cwd); setCwdModalOpen(true); }}>
              cwd={cwd.length > 28 ? `…${cwd.slice(-28)}` : cwd}
            </button>
            <button type="button" className="rb-cli-pill" onClick={() => setSessionsOpen((open) => !open)}>
              <MessagesSquare size={11} /> 会话列表
            </button>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className="rb-backend">
            <span className="rb-backend-lbl">后端</span>
            <span className="rb-backend-tab on"><Terminal size={12} />{enabledBackend.label}</span>
          </div>
          <button
            type="button"
            onClick={() => { setTerminalError(null); setRestartTick((tick) => tick + 1); }}
            title="重启 PTY"
            className="rb-icon-btn"
            style={{ color: 'var(--danger-fg)' }}
          >
            <LogOut size={14} />
          </button>
        </div>
      </div>

      {sessionsOpen ? (
        <>
          <div onClick={() => setSessionsOpen(false)} style={{ position: 'absolute', inset: 0, zIndex: 25, background: 'transparent' }} />
          <div style={{ position: 'absolute', top: 70, left: 24, zIndex: 30, width: 320, maxHeight: 480, background: 'var(--bg-3)', border: '1px solid var(--line-1)', borderRadius: 12, boxShadow: 'var(--shadow-modal)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <SessionsPanel
              projectId={activeProject.id}
              activeConversationId={activeConversation?.id ?? null}
              enabledBackends={enabledBackends}
              onSwitchConversation={async (next) => { setSessionsOpen(false); await switchConversation(next); }}
              onCreateConversation={async (backend) => { setSessionsOpen(false); await createConversation(backend); }}
              onActiveConversationDeleted={() => { setActiveConversation(null); setResumeId(null); setRestartTick((tick) => tick + 1); }}
            />
          </div>
        </>
      ) : null}

      <ClassifyHintBar onAccept={(text) => { inputSequence.current += 1; setTerminalInput({ sequence: inputSequence.current, text }); }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 24px', borderBottom: '1px solid var(--line-1)', background: 'var(--bg-2)', color: 'var(--fg-2)', fontSize: 12 }}>
        <span style={{ color: auth?.status === 'logged_in' ? 'var(--ok-fg)' : 'var(--danger-fg)', fontWeight: 600 }}>{authLabel}</span>
        <button type="button" className="rb-icon-btn" title="刷新 capability 与认证状态" onClick={() => void refreshRuntime()}><RefreshCw size={13} /></button>
      </div>

      <div className="rb-chat-body">
        <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          {terminalError ? (
            <div className="absolute left-2 right-2 top-2 z-10 flex items-center justify-between gap-2 rounded bg-rose-900 px-3 py-2 text-[12px] text-rose-100">
              <span>{terminalError}</span>
              <button type="button" onClick={() => { setTerminalError(null); setRestartTick((tick) => tick + 1); }}>重启 PTY</button>
            </div>
          ) : null}
          {activeConversation ? (
            <TerminalPane
              key={`${enabledBackend.id}|${activeProject.id}|${resumeId ?? 'fresh'}|${cwd}|${activeConversation.id}|${restartTick}`}
              backend={enabledBackend.id}
              cwd={cwd}
              resumeId={enabledBackend.supports_resume ? resumeId ?? undefined : undefined}
              conversationId={activeConversation.id}
              input={terminalInput ?? undefined}
              onInputSent={(sequence) => setTerminalInput((current) => current?.sequence === sequence ? null : current)}
              className="h-full w-full bg-[var(--bg-2)] p-2"
              onClose={(reason) => setTerminalError(`${enabledBackend.label} PTY 已断开（${reason}）。`)}
            />
          ) : <WorkbenchMessage text={loadError ?? '正在创建对话…'} />}
        </div>
      </div>
    </div>
  );
};

const WorkbenchMessage: React.FC<{ text: string }> = ({ text }) => (
  <div className="flex h-full items-center justify-center bg-[var(--bg-2)] text-[13px] text-[var(--fg-3)]">{text}</div>
);
