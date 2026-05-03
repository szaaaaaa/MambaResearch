import React from 'react';
import {
  FlaskConical,
  FileText,
  Database,
  Lightbulb,
  LayoutGrid,
  Plug,
  LineChart,
  History,
  Settings,
  BookOpen,
  Inbox,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { AuthStatus } from '../api/projects';
import { getAuthStatus } from '../api/projects';

/**
 * NavId — 主导航视图标识。'set' 不是视图而是打开 SettingsModal 的开关，
 * App.tsx 收到该 id 时调用 onOpenSettings 并保留当前 active 不变。
 *
 * 2026-04-29 asset-centric pivot：旧的"会话为中心"侧栏 UI（+ 新建会话、最近
 * 会话、已归档）整体被删除——会话由 WorkbenchTab 在首条消息时隐式创建，
 * 不再作为侧栏一级实体出现；T5 落 DraftsTab、T6 落 run timeline 后会再加
 * "草稿箱""全部产物"两个辅助入口。
 *
 * Stage 5 v3 已删除 'runs'。loadLastNav 在 App.tsx 中把 'runs' 旧值映射 'hist'。
 */
export type NavId =
  | 'exp'
  | 'pap'
  | 'data'
  | 'idea'
  | 'drafts'
  | 'skill'
  | 'mcp'
  | 'bench'
  | 'hist'
  | 'library'
  | 'set';

interface NavItem {
  id: NavId;
  label: string;
  icon: LucideIcon;
}

interface NavGroup {
  label?: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      { id: 'exp', label: '实验', icon: FlaskConical },
      { id: 'pap', label: '文献', icon: FileText },
      { id: 'data', label: '数据集', icon: Database },
      { id: 'idea', label: '灵感', icon: Lightbulb },
    ],
  },
  {
    items: [
      // 2026-04-29 asset-centric pivot：未素材化的 conversation 进草稿箱
      { id: 'drafts', label: '草稿箱', icon: Inbox },
    ],
  },
  {
    label: '能力',
    items: [
      { id: 'skill', label: '技能', icon: LayoutGrid },
      { id: 'mcp', label: 'MCP 工具', icon: Plug },
      { id: 'bench', label: '工作台', icon: LineChart },
      { id: 'library', label: 'Zotero 库', icon: BookOpen },
    ],
  },
  {
    label: '运行',
    items: [
      { id: 'hist', label: '运行历史', icon: History },
      { id: 'set', label: '设置', icon: Settings },
    ],
  },
];

interface MambaSidebarProps {
  active: NavId;
  onNav: (id: NavId) => void;
}

/**
 * BackendStatusBar —— 侧栏底部"被动"连通指示器。
 *
 * 区别于 TopBar 的 AuthStatusChip（点击可管理 OAuth/CLI 登录）：本组件只读，
 * 用一对色点告诉用户哪个 backend 当前可用。绿点=Claude 已登录；
 * 紫点=Codex 已登录；未登录显示成 fg-4 灰点。设计令牌 ok-dot / role-writer-fg
 * 已经是暖色等价，不引入饱和的 SaaS 绿/紫。
 */
const BackendStatusBar: React.FC = () => {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    getAuthStatus()
      .then((s) => {
        if (!cancelled) setAuth(s);
      })
      .catch(() => {
        if (!cancelled) setAuth(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const claudeOn = auth?.claude === 'logged_in';
  const codexOn = auth?.codex === 'logged_in';

  return (
    <div
      style={{
        height: 36,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '0 14px',
        borderTop: '1px solid var(--line-1)',
        fontSize: 11,
        color: 'var(--fg-3)',
        userSelect: 'none',
      }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span
          aria-hidden
          style={{
            width: 7,
            height: 7,
            borderRadius: 999,
            background: claudeOn ? 'var(--ok-dot)' : 'var(--fg-4)',
            boxShadow: claudeOn ? '0 0 0 2px rgba(79, 122, 74, 0.18)' : undefined,
          }}
        />
        <span style={{ color: claudeOn ? 'var(--fg-2)' : 'var(--fg-3)' }}>Claude</span>
      </span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span
          aria-hidden
          style={{
            width: 7,
            height: 7,
            borderRadius: 999,
            background: codexOn ? 'var(--role-writer-fg)' : 'var(--fg-4)',
            boxShadow: codexOn ? '0 0 0 2px rgba(122, 62, 92, 0.18)' : undefined,
          }}
        />
        <span style={{ color: codexOn ? 'var(--fg-2)' : 'var(--fg-3)' }}>Codex</span>
      </span>
    </div>
  );
};

/**
 * MambaSidebar —— 暖色调主侧栏。
 *
 * 2026-04-29 asset-centric pivot：
 *   - 删除 "+ 新建会话" 按钮 / "最近会话" 列表 / "已归档" 折叠区
 *   - 删除 ContextMenu（重命名 / 复制 / 归档 / 删除）
 *   - 底部加 BackendStatusBar（只读连通指示）
 *
 * 结构：
 *   - 顶部：品牌头
 *   - 中部：三组导航（基础视图 / 能力 / 运行）
 *   - 底部：Claude/Codex 连通状态条
 */
export const MambaSidebar: React.FC<MambaSidebarProps> = ({ active, onNav }) => {
  return (
    <aside className="rb-sb rb-sb-a">
      <div className="rb-sb-head">
        <div className="rb-brand">
          <div className="rb-mark">M</div>
          <div>
            <div className="rb-eyebrow">MAMBARESEARCH</div>
            <div className="rb-brand-name">研究助手</div>
          </div>
        </div>
      </div>

      <nav className="rb-nav">
        {NAV_GROUPS.map((group, gi) => (
          <div className="rb-group" key={gi}>
            {group.label ? <div className="rb-group-h">{group.label}</div> : null}
            {group.items.map((item) => {
              const Icon = item.icon;
              const isActive = active === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`rb-nav-item ${isActive ? 'on' : ''}`}
                  onClick={() => onNav(item.id)}
                >
                  <span className="rb-nav-ico">
                    <Icon size={16} />
                  </span>
                  <span className="rb-nav-lbl">{item.label}</span>
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      <BackendStatusBar />
    </aside>
  );
};
