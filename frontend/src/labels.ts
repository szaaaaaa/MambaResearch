/**
 * 共享标签映射 —— 与后端 contracts / roles.yaml / skills 保持一致。
 *
 * 所有前端组件统一从此文件 import，避免多处重复定义。
 */

// ─── 角色 ────────────────────────────────────────────────────────
// 对应 RoleId 枚举 (src/dynamic_os/contracts/route_plan.py)
export const ROLE_LABELS: Record<string, string> = {
  conductor: '统筹',
  researcher: '研究',
  experimenter: '实验',
  analyst: '分析',
  writer: '写作',
  reviewer: '审阅',
  hitl: '人工',
};

export function roleLabel(id: string): string {
  return ROLE_LABELS[id] || id;
}

// ─── 产物类型 ────────────────────────────────────────────────────
// 对应 roles.yaml 中各角色的 produces / consumes
export const ARTIFACT_LABELS: Record<string, string> = {
  TopicBrief: '主题简报',
  SearchPlan: '检索计划',
  SourceSet: '来源集合',
  PaperNotes: '论文笔记',
  EvidenceMap: '证据图谱',
  GapMap: '缺口图谱',
  TrendAnalysis: '趋势分析',
  ExperimentPlan: '实验方案',
  ExperimentResults: '实验结果',
  ExperimentAnalysis: '实验分析',
  ExperimentIteration: '实验迭代',
  PerformanceMetrics: '性能指标',
  MethodComparison: '方法对比',
  FigureSet: '图表集合',
  ResearchReport: '研究报告',
  ReviewVerdict: '审阅结论',
  SkillPatch: '技能补丁',
  SkillCreation: '新建技能',
  UserGuidance: '用户指引',
  ReflectionReport: '反思报告',
};

export function artifactLabel(type: string): string {
  return ARTIFACT_LABELS[type] || type;
}

// ─── 技能 ────────────────────────────────────────────────────────
// 对应 src/dynamic_os/skills/builtins/ 下注册的技能
export const SKILL_LABELS: Record<string, string> = {
  plan_research: '规划研究',
  search_papers: '检索论文',
  fetch_fulltext: '抓取全文',
  extract_notes: '提取笔记',
  build_evidence_map: '构建证据图谱',
  analyze_trends: '趋势分析',
  analyze_metrics: '分析指标',
  compare_methods: '方法对比',
  design_experiment: '设计实验',
  run_experiment: '执行实验',
  optimize_experiment: '优化实验',
  optimize_skill: '优化技能',
  create_skill: '创建技能',
  draft_report: '撰写报告',
  generate_figures: '生成图表',
  review_artifact: '审阅产出',
  reflect_on_failure: '失败反思',
  hitl: '人工介入',
};

export function skillLabel(id: string): string {
  return SKILL_LABELS[id] || id;
}

// ─── 工具 ────────────────────────────────────────────────────────
// MCP 工具 ID 格式: mcp.{server_id}.{tool_name}
export const TOOL_LABELS: Record<string, string> = {
  'mcp.llm.chat': '模型对话',
  'mcp.search.papers': '论文搜索',
  'mcp.retrieval.store': '全文检索',
  'mcp.retrieval.indexer': '索引写入',
  'mcp.exec.execute_code': '代码执行',
  'mcp.exec.remote_execute_code': '远程代码执行',
  'mcp.filesystem.read_file': '读取文件',
  'mcp.filesystem.write_file': '写入文件',
};

export function toolLabel(id: string): string {
  return TOOL_LABELS[id] || id;
}

// ─── 节点状态 ────────────────────────────────────────────────────
export const NODE_STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '执行中',
  success: '成功',
  partial: '部分完成',
  needs_replan: '需要重规划',
  failed: '失败',
  skipped: '已跳过',
  stopped: '已停止',
};

export function nodeStatusLabel(status: string): string {
  return NODE_STATUS_LABELS[status] || status || '等待中';
}

// ─── 运行状态 ────────────────────────────────────────────────────
export const RUN_STATUS_LABELS: Record<string, string> = {
  Running: '运行中',
  Stopping: '停止中',
  Stopped: '已停止',
  Failed: '失败',
  Completed: '已完成',
};

export function runStatusLabel(status: string): string {
  return RUN_STATUS_LABELS[status] || '待命';
}

// ─── 事件类型 ────────────────────────────────────────────────────
// 对应 src/dynamic_os/contracts/events.py
export const EVENT_TYPE_LABELS: Record<string, string> = {
  plan_update: '规划',
  node_status: '节点',
  skill_invoke: '技能',
  tool_invoke: '工具',
  observation: '观察',
  replan: '重规划',
  artifact_created: '产物',
  policy_block: '策略',
  run_terminate: '终止',
  hitl_request: '人工暂停',
  hitl_response: '人工回应',
};

export function eventTypeLabel(type: string): string {
  return EVENT_TYPE_LABELS[type] || type;
}

// ─── 时间戳格式化 ────────────────────────────────────────────────

export function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value));
}

export function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value));
}
