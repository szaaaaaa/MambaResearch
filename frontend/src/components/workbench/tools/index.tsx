import React from 'react';
import { EditView } from './EditView';
import { WriteView } from './WriteView';
import { BashView } from './BashView';
import { ReadView } from './ReadView';
import { GrepView } from './GrepView';
import { GlobView } from './GlobView';
import { GenericToolView } from './GenericToolView';

type ToolView = React.ComponentType<{ input: unknown }>;

/**
 * 工具名 → 专属视图注册表。未命中的走 GenericToolView。
 * 随 Task 4d-4e 推进，逐步把 TodoWrite/WebFetch/WebSearch/Task 填进来。
 */
const REGISTRY: Record<string, ToolView> = {
  Edit: EditView,
  Write: WriteView,
  Bash: BashView,
  Read: ReadView,
  Grep: GrepView,
  Glob: GlobView,
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
