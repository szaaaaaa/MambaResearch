import React from 'react';
import { EditView } from './EditView';
import { WriteView } from './WriteView';
import { BashView } from './BashView';
import { ReadView } from './ReadView';
import { GrepView } from './GrepView';
import { GlobView } from './GlobView';
import { TodoView } from './TodoView';
import { WebFetchView } from './WebFetchView';
import { WebSearchView } from './WebSearchView';
import { TaskView } from './TaskView';
import { GenericToolView } from './GenericToolView';

type ToolView = React.ComponentType<{ input: unknown }>;

/**
 * 工具名 → 专属视图注册表。未命中的走 GenericToolView。
 * 10 个常用工具 + Generic 兜底（Task 4 收口）。
 */
const REGISTRY: Record<string, ToolView> = {
  Edit: EditView,
  Write: WriteView,
  Bash: BashView,
  Read: ReadView,
  Grep: GrepView,
  Glob: GlobView,
  TodoWrite: TodoView,
  WebFetch: WebFetchView,
  WebSearch: WebSearchView,
  Task: TaskView,
};

interface DispatchArgs {
  name: string;
  input: unknown;
}

/**
 * 工具调用视图分发器。按工具名查注册表，未命中走 Generic 兜底。
 */
export function dispatchToolView({ name, input }: DispatchArgs): React.ReactElement {
  const View = REGISTRY[name];
  if (View) {
    return <View input={input} />;
  }
  return <GenericToolView name={name} input={input} />;
}
