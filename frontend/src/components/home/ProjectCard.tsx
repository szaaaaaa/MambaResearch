import React from 'react';
import { Folder, MoreVertical, Trash2 } from 'lucide-react';
import type { Project } from '../../api/projects';

interface Props {
  project: Project;
  onOpen: () => void;
  onDelete: () => void;
}

/**
 * Home 屏中的单个项目卡片——点卡片本体激活并进入 IDE，右上角"⋮"菜单含删除。
 */
export const ProjectCard: React.FC<Props> = ({ project, onOpen, onDelete }) => {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const lastActive = new Date(project.last_active_at * 1000);

  return (
    <div
      className="group relative cursor-pointer rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-400 hover:shadow-sm"
      onClick={onOpen}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <Folder size={20} className="text-slate-500 shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="font-medium text-slate-900 truncate">{project.name}</div>
            <div className="text-xs text-slate-500 truncate mt-0.5" title={project.path}>
              {project.path}
            </div>
          </div>
        </div>
        <button
          type="button"
          className="p-1 rounded hover:bg-slate-100 opacity-0 group-hover:opacity-100 transition"
          onClick={(e) => {
            e.stopPropagation();
            setMenuOpen((v) => !v);
          }}
          aria-label="项目操作"
        >
          <MoreVertical size={16} className="text-slate-500" />
        </button>
      </div>

      <div className="mt-3 text-xs text-slate-400">
        最近激活 {lastActive.toLocaleString('zh-CN')}
      </div>

      {menuOpen ? (
        <div
          className="absolute right-2 top-12 z-10 w-32 rounded-md border border-slate-200 bg-white shadow-lg"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-rose-600 hover:bg-rose-50"
            onClick={() => {
              setMenuOpen(false);
              if (
                window.confirm(
                  `删除项目"${project.name}"？\n\n` +
                    `会清除：项目注册项 + 该项目下所有对话历史 / 消息 / MCP 调用记录 / 实验运行记录。\n\n` +
                    `不会动：物理目录及其文件、项目内 .mambaresearch/ 工作区元数据、` +
                    `Claude/Codex 自己的会话存储（仍能用 CLI --resume 打开）。`,
                )
              ) {
                onDelete();
              }
            }}
          >
            <Trash2 size={14} />
            删除
          </button>
        </div>
      ) : null}
    </div>
  );
};
