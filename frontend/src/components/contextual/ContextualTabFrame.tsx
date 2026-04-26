import React, { Suspense } from 'react';
import { useActiveContextualTab } from '../../store/contextual';

const LiteratureTab = React.lazy(() =>
  import('./literature/LiteratureTab').then((m) => ({ default: m.LiteratureTab })),
);
const ExperimentRunTab = React.lazy(() =>
  import('./experiment/ExperimentRunTab').then((m) => ({ default: m.ExperimentRunTab })),
);
const ThinkingTab = React.lazy(() =>
  import('./thinking/ThinkingTab').then((m) => ({ default: m.ThinkingTab })),
);

const Loading: React.FC<{ label: string }> = ({ label }) => (
  <div className="flex h-full w-full items-center justify-center text-sm text-slate-500">
    加载 {label}…
  </div>
);

/**
 * 渲染当前 active contextual tab 的内容；无 active tab 返回 null
 * （让 App.renderMain 走原 sidebar nav 路径）。
 *
 * 三种 tab 都 React.lazy 异步加载，主 App 启动不背重渲染包；
 * Suspense 兜底显示 "加载…" 文本。
 */
export const ContextualTabFrame: React.FC = () => {
  const active = useActiveContextualTab();
  if (active === null) return null;

  switch (active.type) {
    case 'literature':
      return (
        <Suspense fallback={<Loading label="文献阅读" />}>
          <LiteratureTab key={active.id} {...(active.props as any)} />
        </Suspense>
      );
    case 'experiment_run':
      return (
        <Suspense fallback={<Loading label="实验执行" />}>
          <ExperimentRunTab key={active.id} {...(active.props as any)} />
        </Suspense>
      );
    case 'thinking':
      return (
        <Suspense fallback={<Loading label="Agent 思考" />}>
          <ThinkingTab key={active.id} {...(active.props as any)} />
        </Suspense>
      );
    default:
      return null;
  }
};
