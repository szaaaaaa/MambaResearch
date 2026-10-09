import React from 'react';
import type { LucideIcon } from 'lucide-react';

/**
 * 空态分级——Stage 2 Task 7。
 *
 * 区分 4 种"为什么没东西可看"，让用户精确知道下一步该干什么：
 *
 * - ``no_source_dirs``         workspace 还没配置任何源目录 → 引导去设置
 * - ``never_scanned``          有 source_dirs 但 classification.db 全空 → 引导扫描
 * - ``awaiting_classification`` 已扫描但该栏目为空，unknown 可能包含科研无关文件
 *                                → 可由 ChatGPT 检查用途，不要求填满栏目
 * - ``genuinely_empty``        全部已分类、单纯就是该类型 0 个文件 → 单纯告知
 */
export type BucketEmptyTier =
  | 'no_source_dirs'
  | 'never_scanned'
  | 'awaiting_classification'
  | 'genuinely_empty';

interface Props {
  icon: LucideIcon;
  title: string;
  /** 可覆盖默认 description；不给则按 tier 给一个标准文案。 */
  description?: string;
  /** 可覆盖默认 hint；不给则按 tier 给一个标准提示。 */
  hint?: string;
  /** 4 种空态。默认 ``never_scanned``，向后兼容老调用。 */
  tier?: BucketEmptyTier;
  /** 行动按钮 slot——按 tier 由父组件决定渲染什么；可空。 */
  actions?: React.ReactNode;
}

const DEFAULTS: Record<BucketEmptyTier, { description: string; hint: string }> = {
  no_source_dirs: {
    description: '该项目还没配置任何源目录。',
    hint: 'MambaResearch 不会自动扫描整个磁盘——请到设置里添加你想纳入工作区的目录（例如某个论文文件夹、实验代码 repo）。',
  },
  never_scanned: {
    description: '已配置源目录，但还没扫描过。',
    hint: '点击"扫描 workspace"建立文件索引，再由 ChatGPT 判断实际科研用途；无关文件保留在栏目之外。',
  },
  awaiting_classification: {
    description: '此栏目尚未发现已确认相关的科研文件。',
    hint: '可运行 classify-workspace，由 ChatGPT 阅读内容并判断科研用途。无关或用途不明的文件不进入科研栏目，栏目为空也可能是正确结果。',
  },
  genuinely_empty: {
    description: '全部已分类——这个类型确实没有文件。',
    hint: '不是每个项目都有四种文件；切到其他 bucket 看一下吧。',
  },
};

export const BucketEmptyState: React.FC<Props> = ({
  icon: Icon,
  title,
  description,
  hint,
  tier = 'never_scanned',
  actions,
}) => {
  const defaults = DEFAULTS[tier];
  return (
    <div className="flex h-full items-center justify-center bg-slate-50 px-6">
      <div className="max-w-md text-center">
        <Icon size={48} className="mx-auto text-slate-300" />
        <div className="mt-4 text-lg font-medium text-slate-700">{title}</div>
        <div className="mt-2 text-sm text-slate-500">{description ?? defaults.description}</div>
        <div className="mt-4 rounded bg-white border border-slate-200 px-4 py-3 text-xs text-slate-500">
          {hint ?? defaults.hint}
        </div>
        {actions ? <div className="mt-4 flex justify-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
};
