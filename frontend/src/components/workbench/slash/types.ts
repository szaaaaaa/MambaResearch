/**
 * Slash 命令类型契约。
 *
 * 所有命令元数据集中在 ``registry.ts``，实际 handler 由 ``dispatch.ts`` 解析执行。
 * 面板组件（``HelpPanel`` 等）按 scope 字段分组展示。
 */

export type SlashScope =
  /** 纯前端命令，handler 当场执行（打开 Panel / 发特殊 prompt / 改本地 store） */
  | 'frontend'
  /** 依赖后端端点的命令，handler 需调后端 */
  | 'backend'
  /** 待后续子任务（6b / 6c / 6d）实现，当前点击弹 deferred 提示 */
  | 'deferred'
  /** 仅原生 CLI 可用，Web 下只能提示用户去终端执行 */
  | 'cli-only';

/**
 * Slash 命令定义。
 *
 * id 是斜杠后的主命令名（如 ``help``），aliases 是同义词（一般不用）。
 * scope 决定 dispatch 走哪条路径，handlerKey 是 dispatch 查表用的键。
 */
export interface SlashCommand {
  /** 命令主名（不含前导 /） */
  id: string;
  /** 额外同义词（不含前导 /） */
  aliases?: string[];
  /** 简述，HelpPanel 与 autocomplete 下拉里展示 */
  description: string;
  /** 分组维度，HelpPanel 按此分段 */
  scope: SlashScope;
  /** dispatch 查表键（frontend / backend 命令指向具体 handler；deferred / cli-only 此字段可选） */
  handlerKey?: string;
  /** cli-only 或 info 类命令可附加说明正文（会传给 InfoPanel） */
  infoBody?: string;
  /** 关联的外链（可选，InfoPanel 渲染一个跳转） */
  infoLink?: { text: string; url: string };
}
