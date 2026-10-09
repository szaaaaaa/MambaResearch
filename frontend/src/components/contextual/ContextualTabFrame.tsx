import React, { Suspense } from 'react';
import { useActiveRuntimeTab } from '../../runtime/appRuntime';

const LiteratureTab = React.lazy(() =>
  import('./literature/LiteratureTab').then((m) => ({ default: m.LiteratureTab })),
);
const ExperimentRunTab = React.lazy(() =>
  import('./experiment/ExperimentRunTab').then((m) => ({ default: m.ExperimentRunTab })),
);
const AssetWorkspace = React.lazy(() =>
  import('./asset/AssetWorkspace').then((m) => ({ default: m.AssetWorkspace })),
);

const Loading: React.FC<{ label: string }> = ({ label }) => (
  <div
    className="flex h-full w-full items-center justify-center"
    style={{ fontSize: 13, color: 'var(--fg-3)' }}
  >
    加载 {label}…
  </div>
);

/**
 * 渲染当前 active contextual tab 的内容；无 active tab 返回 null
 * （让 App 回到当前 Registry view）。
 *
 * Suspense 等待各视图模块，构建时全部内联到同一 MCP UI 资源。
 * 素材页复用 AssetWorkspace 的资料与研究记录双栏。
 */
export const ContextualTabFrame: React.FC = () => {
  const active = useActiveRuntimeTab();
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
        <Suspense fallback={<Loading label="实验记录" />}>
          <ExperimentRunTab key={active.id} {...(active.props as any)} />
        </Suspense>
      );
    case 'asset':
      return (
        <Suspense fallback={<Loading label="素材工作台" />}>
          <AssetWorkspace key={active.id} {...(active.props as any)} />
        </Suspense>
      );
    default:
      return null;
  }
};
