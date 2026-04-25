import React from 'react';
import { LucideIcon } from 'lucide-react';

interface PlaceholderViewProps {
  icon: LucideIcon;
  title: string;
  description: string;
  /** 后续接入计划——直白告诉用户后端能力是否已具备、UI 何时落地。 */
  plannedSource?: string;
}

/**
 * PlaceholderView —— 暂未接入页面的占位视图。
 *
 * 不造假数据，明确告知"后端能力 / UI 状态"——避免演示性 UI 误导用户。
 */
export const PlaceholderView: React.FC<PlaceholderViewProps> = ({
  icon: Icon,
  title,
  description,
  plannedSource,
}) => {
  return (
    <div className="rb-placeholder">
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 16,
          background: 'var(--clay-50)',
          color: 'var(--clay-700)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Icon size={26} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {plannedSource ? (
        <div
          className="rb-placeholder-card"
          style={{ marginTop: 12 }}
        >
          <div className="type-eyebrow" style={{ marginBottom: 8 }}>
            后续接入
          </div>
          <p style={{ color: 'var(--fg-2)', textAlign: 'left' }}>{plannedSource}</p>
        </div>
      ) : null}
    </div>
  );
};
