import React from 'react';
import { RefreshCw } from 'lucide-react';
import { getConversationMessages, type ConversationMessage, type ConversationSummary } from '../../api/conversations';
import type { Project } from '../../api/projects';
import { getTasks, sendTask, type ResearchTask } from '../../api/workbench';
import { getExperimentRuns, type RunStatus } from '../../api/experiments';
import { useAppRuntime } from '../../runtime/appRuntime';
import { ClassifyHintBar } from '../workbench/ClassifyHintBar';
import { MarkdownBlock } from '../workbench/MarkdownBlock';

export interface WorkbenchTabProps {
  activeProject: Project;
  conversation?: ConversationSummary;
}

export const WorkbenchTab: React.FC<WorkbenchTabProps> = ({ activeProject, conversation }) => {
  const runtime = useAppRuntime();
  const [tasks, setTasks] = React.useState<ResearchTask[]>([]);
  const [messages, setMessages] = React.useState<ConversationMessage[]>([]);
  const [experiments, setExperiments] = React.useState<RunStatus[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshTick, setRefreshTick] = React.useState(0);
  const attempted = React.useRef(new Set<string>());
  const command = runtime.state.workbenchCommands.find((entry) => entry.projectId === activeProject.id);

  React.useEffect(() => {
    if (!command || command.status !== 'queued' || attempted.current.has(command.id)) return;
    attempted.current.add(command.id);
    runtime.markCommandDelivering(command.id);
    void sendTask(command.projectId, command.text, command.conversationId ?? null)
      .then(() => runtime.acknowledgeCommand(command.id))
      .catch((reason) => runtime.failCommand(command.id, `投递结果未确认，请核对当前聊天：${reason.message}`));
  }, [command, conversation?.id, runtime]);

  const refresh = React.useCallback(async () => {
    const [values, runs] = await Promise.all([getTasks(activeProject.id), getExperimentRuns()]);
    const history = conversation ? await getConversationMessages(conversation.id) : [];
    return { values, history, runs };
  }, [activeProject.id, conversation?.id]);

  React.useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = async () => {
      try {
        const result = await refresh();
        if (disposed) return;
        setTasks(result.values);
        setMessages(result.history);
        setExperiments(result.runs);
        setError(null);
      } catch (reason) {
        if (!disposed) setError(String(reason));
      }
      if (!disposed) timer = setTimeout(check, 4000);
    };
    void check();
    return () => { disposed = true; clearTimeout(timer); };
  }, [refresh, refreshTick]);

  return (
    <div className="flex h-full flex-col bg-[var(--bg-2)]">
      <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
        <div><h2 className="text-base font-semibold">{conversation?.asset_label ?? conversation?.title ?? '科研工作台'}</h2><p className="mt-1 text-xs text-slate-500">任务在当前 Codex 聊天执行，结果和研究产物留在此项目。</p></div>
        <button type="button" aria-label="检查任务结果" onClick={() => setRefreshTick((tick) => tick + 1)}><RefreshCw size={16} /></button>
      </header>
      <ClassifyHintBar onAccept={runtime.openWorkbench} />
      {error ? <div role="alert" className="bg-rose-50 px-6 py-2 text-sm text-rose-700">{error}</div> : null}
      {command ? <div className="flex items-center justify-between gap-4 bg-amber-50 px-6 py-2 text-xs text-amber-800"><span>{command.error ?? (command.status === 'delivering' ? '正在向当前聊天投递任务' : '等待投递')} · {command.text}</span><button type="button" onClick={() => runtime.cancelCommand(command.id)}>移除提示</button></div> : null}
      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-6 py-4">
        {experiments.map((run) => <button key={run.run_id} type="button" className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-white p-3 text-left text-sm" onClick={() => runtime.openTab({ type: 'experiment_run', key: run.run_id, title: run.script_path.split(/[\\/]/).pop() ?? run.run_id, props: { runId: run.run_id, scriptPath: run.script_path } })}><span>{run.script_path.split(/[\\/]/).pop()} · 查看已保存的实验记录</span><span className="text-xs text-slate-500">{run.status}</span></button>)}
        {messages.map((message) => <article key={message.id} className="rounded-lg border border-slate-200 bg-white p-4"><div className="mb-2 text-xs text-slate-500">{message.role} · {message.served_by}</div><MarkdownBlock>{message.text}</MarkdownBlock></article>)}
        {tasks.filter((task) => !conversation || task.conversation_id === conversation.id).map((task) => (
          <article key={task.id} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between gap-4"><span className="text-sm font-medium">{task.prompt}</span><span className="shrink-0 text-xs text-slate-500">{task.status === 'waiting' ? '已保存，等待当前聊天处理' : task.status === 'completed' ? '模型结果已返回' : '执行问题已返回'}</span></div>
            {task.summary ? <div className="mt-3"><MarkdownBlock>{task.summary}</MarkdownBlock></div> : null}
            {task.artifacts.length ? <ul className="mt-2 text-xs text-slate-600">{task.artifacts.map((path) => <li key={path}>{path}</li>)}</ul> : null}
          </article>
        ))}
        {!messages.length && !tasks.length ? <p className="py-12 text-center text-sm text-slate-500">在 Codex 当前聊天发起科研任务，或使用文件和文献操作。</p> : null}
      </div>

    </div>
  );
};
