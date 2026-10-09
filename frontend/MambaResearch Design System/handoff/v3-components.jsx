// MambaResearch v2 — Coze sidebar + chat-style main (CLI as backend tab indicator)
const { useState, useEffect, useRef } = React;

const Icon = ({ c, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">{c}</svg>
);
const I = {
  flask:  <Icon c={<><path d="M9 2h6"/><path d="M10 2v7L4 20a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-11V2"/><line x1="7" y1="15" x2="17" y2="15"/></>}/>,
  skill:  <Icon c={<><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></>}/>,
  paper:  <Icon c={<><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="15" y2="17"/></>}/>,
  idea:   <Icon c={<><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2v.3h6V17c0-.8.4-1.5 1-2A7 7 0 0 0 12 2z"/></>}/>,
  history:<Icon c={<><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/></>}/>,
  data:   <Icon c={<><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></>}/>,
  roles:  <Icon c={<><circle cx="9" cy="8" r="3"/><path d="M3 21v-1a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v1"/><circle cx="17" cy="6" r="2.5"/><path d="M14 14a4 4 0 0 1 4-3 4 4 0 0 1 4 3"/></>}/>,
  bench:  <Icon c={<><polyline points="4 17 10 11 14 15 20 9"/><polyline points="14 9 20 9 20 15"/></>}/>,
  claude: <Icon c={<><path d="M4 17l4-4-4-4"/><line x1="11" y1="19" x2="20" y2="19"/></>}/>,
  codex:  <Icon c={<><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></>}/>,
  mcp:    <Icon c={<><path d="M12 2L4 6v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V6z"/></>}/>,
  setting:<Icon c={<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4"/></>}/>,
  plus:   <Icon c={<><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></>}/>,
  send:   <Icon c={<><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></>}/>,
  attach: <Icon c={<><path d="M21.4 11l-9.2 9.2a5 5 0 0 1-7.1-7.1l9.2-9.2a3.3 3.3 0 0 1 4.7 4.7L9.9 17.7a1.7 1.7 0 0 1-2.4-2.4l8.5-8.5"/></>}/>,
  chip:   <Icon c={<><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 4v-2"/><path d="M15 4v-2"/><path d="M9 22v-2"/><path d="M15 22v-2"/><path d="M4 9h-2"/><path d="M4 15h-2"/><path d="M22 9h-2"/><path d="M22 15h-2"/></>}/>,
};

const NAV_GROUPS_A = [
  { items: [
    { id: 'exp',  glyph: I.flask,  label: '实验' },
    { id: 'pap',  glyph: I.paper,  label: '文献' },
    { id: 'data', glyph: I.data,   label: '数据集' },
    { id: 'idea', glyph: I.idea,   label: '灵感' },
  ]},
  { label: '能力', items: [
    { id: 'skill', glyph: I.skill, label: '技能' },
    { id: 'roles', glyph: I.roles, label: 'Agent 角色' },
    { id: 'mcp',   glyph: I.mcp,   label: 'MCP 工具' },
    { id: 'bench', glyph: I.bench, label: '工作台' },
  ]},
  { label: '运行', items: [
    { id: 'hist', glyph: I.history, label: '运行历史' },
    { id: 'set',  glyph: I.setting, label: '设置' },
  ]},
];

function SidebarA({ active, onPick, conversations, activeConv, onPickConv, onNew }) {
  return (
    <aside className="rb-sb rb-sb-a">
      <div className="rb-sb-head">
        <div className="rb-brand"><div className="rb-mark">M</div><div><div className="rb-eyebrow">MAMBARESEARCH</div><div className="rb-brand-name">研究助手</div></div></div>
        <button className="rb-icon-btn" title="新建" onClick={onNew}>{I.plus}</button>
      </div>
      <nav className="rb-nav">
        {NAV_GROUPS_A.map((g, gi) => (
          <div className="rb-group" key={gi}>
            {g.label && <div className="rb-group-h">{g.label}</div>}
            {g.items.map(it => (
              <button key={it.id} className={`rb-nav-item ${active === it.id ? 'on' : ''}`} onClick={() => onPick(it.id)}>
                <span className="rb-nav-ico">{it.glyph}</span>
                <span className="rb-nav-lbl">{it.label}</span>
              </button>
            ))}
          </div>
        ))}
      </nav>
      <div className="rb-sb-foot">
        <div className="rb-eyebrow">最近会话</div>
        <div className="rb-conv-list">
          {conversations.map(c => (
            <button key={c.id} className={`rb-conv ${activeConv === c.id ? 'on' : ''}`} onClick={() => onPickConv(c.id)}>
              <span className={`rb-conv-dot s-${c.status}`} />
              <span className="rb-conv-title">{c.title}</span>
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}

// ---- Chat main area (with backend selector at top) ----
const CONV_SEED = [
  { id: 'k1', title: 'Transformer 注意力改进', status: 'Running' },
  { id: 'k2', title: 'RAG 召回率对比', status: 'Completed' },
  { id: 'k3', title: 'Mamba 长文本', status: 'Failed' },
  { id: 'k4', title: '扩散采样加速', status: 'Idle' },
];

const TRANSCRIPT_SEED = [
  { kind: 'user', text: '研究 Transformer 注意力机制最新改进，对比不同 attention 变体的效率。' },
  { kind: 'agent', tag: 'conductor', sub: 'plan_research',
    text: '已为本次研究生成 5 节点的 RoutePlan，覆盖检索 → 笔记 → 实验设计 → 迭代 → 撰写。开始按拓扑分发节点。',
    steps: [
      { name: 'plan_research', status: 'done', meta: '5 nodes · 3 roles' },
      { name: 'search_papers', status: 'done', meta: 'arxiv · hits=128 · selected=12' },
      { name: 'extract_notes', status: 'running', meta: '7 / 12 papers' },
    ]
  },
  { kind: 'user', text: '聚焦在 linear attention 与 sparse attention 这两类。' },
  { kind: 'agent', tag: 'researcher', sub: 'extract_notes',
    text: '已限定主题，重新筛选出 8 篇核心论文：4 篇 linear attention（Performer / Linformer / RFA / Cosformer），4 篇 sparse（Longformer / BigBird / Reformer / Routing Transformer）。',
    artifacts: [
      { name: 'sources_v2.json', kind: 'data', size: '24 KB' },
      { name: 'method_summary.md', kind: 'doc', size: '6.1 KB' },
    ]
  },
  { kind: 'tool', tag: 'experimenter', sub: 'design_experiment',
    text: '在 sandbox 中初始化对比实验：dataset=wikitext-103, seq_len=4096, baseline=full-attn。指标方向：throughput ↑, perplexity ↓。'
  },
];

const PROMPTS = [
  '为动态研究智能体的主题生成最小研究闭环。',
  '比较 planner → executor → skill → tool 与旧固定流水线。',
  '分析 RAG 系统在 reviewer 按需插入下的运行路径。',
];

function Chat({ conv }) {
  const [history, setHistory] = useState(TRANSCRIPT_SEED);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(null);
  const [backend, setBackend] = useState('claude');
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView?.({ block: 'end' }); }, [history.length, streaming]);

  const send = (text) => {
    const v = (text ?? input).trim(); if (!v) return;
    setHistory(h => [...h, { kind: 'user', text: v }]);
    setInput('');
    const full = '已生成局部 RoutePlan，分发首批节点至 researcher。开始按拓扑执行，预计 2 分钟内返回首批笔记。';
    let i = 0; setStreaming({ kind: 'agent', tag: 'conductor', sub: 'plan_research', text: '' });
    const iv = setInterval(() => { i += 3;
      if (i >= full.length) { clearInterval(iv); setHistory(h => [...h, { kind: 'agent', tag: 'conductor', sub: 'plan_research', text: full }]); setStreaming(null); }
      else setStreaming({ kind: 'agent', tag: 'conductor', sub: 'plan_research', text: full.slice(0, i) });
    }, 28);
  };

  return (
    <div className="rb-chat">
      <div className="rb-chat-head">
        <div className="rb-chat-title">
          <h2>{conv?.title || '新会话'}</h2>
          <div className="rb-chat-meta">
            <span className="rb-cli-status"><i /> 运行中</span>
            <span className="rb-cli-pill mono">run_20260425_1051</span>
            <span className="rb-cli-pill mono">5 节点 · 3 角色</span>
          </div>
        </div>
        <div className="rb-backend">
          <span className="rb-backend-lbl">后端</span>
          <div className="rb-backend-tabs">
            <button className={`rb-backend-tab ${backend === 'claude' ? 'on' : ''}`} onClick={() => setBackend('claude')}>{I.claude}<span>claude code cli</span><em>●</em></button>
            <button className={`rb-backend-tab ${backend === 'codex' ? 'on' : ''}`} onClick={() => setBackend('codex')}>{I.codex}<span>codex cli</span></button>
          </div>
        </div>
      </div>

      <div className="rb-chat-body">
        <div className="rb-chat-stream">
          {history.map((m, i) => <Bubble key={i} m={m} />)}
          {streaming && <Bubble m={streaming} streaming />}
          <div ref={endRef} />
          {history.length === 0 && (
            <div className="rb-prompts">
              <div className="rb-eyebrow">从这里开始</div>
              {PROMPTS.map((p, i) => (
                <button key={i} className="rb-prompt" onClick={() => send(p)}>
                  <span className="rb-prompt-arrow">→</span>{p}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="rb-composer-wrap">
          <form className="rb-composer" onSubmit={e => { e.preventDefault(); send(); }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="向研究助手提问，或描述一个研究主题…"
              rows={2}
            />
            <div className="rb-composer-bar">
              <div className="rb-composer-tools">
                <button type="button" className="rb-tool-btn" title="附加文件">{I.attach}</button>
                <span className="rb-composer-pill">{backend === 'claude' ? 'claude-sonnet-4' : 'gpt-5-codex'}</span>
                <span className="rb-composer-pill ghost">max_iters · 3</span>
              </div>
              <button type="submit" className="rb-send" title="发送">{I.send}</button>
            </div>
          </form>
          <div className="rb-composer-hint">Enter 发送 · Shift+Enter 换行 · 后端为 {backend === 'claude' ? 'Claude Code CLI' : 'Codex CLI'}（由后端代理转发）</div>
        </div>
      </div>
    </div>
  );
}

function Bubble({ m, streaming }) {
  if (m.kind === 'user') {
    return (
      <div className="bb bb-user">
        <div className="bb-body">
          <div className="bb-meta">你</div>
          <div className="bb-text">{m.text}</div>
        </div>
        <div className="bb-av">你</div>
      </div>
    );
  }
  if (m.kind === 'tool') {
    return (
      <div className="bb bb-tool">
        <div className="bb-tool-rule" />
        <div className="bb-tool-card">
          <div className="bb-tool-h">
            <span className="bb-tool-ico">{I.chip}</span>
            <span className="bb-tool-tag">{m.tag} · {m.sub}</span>
            <span className="bb-tool-status">tool call</span>
          </div>
          <div className="bb-tool-text">{m.text}</div>
        </div>
      </div>
    );
  }
  return (
    <div className="bb bb-agent">
      <div className="bb-av agent">M</div>
      <div className="bb-body">
        <div className="bb-meta">{m.tag}{m.sub ? ` · ${m.sub}` : ''}</div>
        <div className="bb-text">{m.text}{streaming && <span className="cl-cur" />}</div>
        {m.steps && (
          <div className="bb-steps">
            {m.steps.map((s, i) => (
              <div key={i} className={`bb-step st-${s.status}`}>
                <span className={`bb-step-dot d-${s.status}`} />
                <span className="bb-step-name">{s.name}</span>
                <span className="bb-step-meta">{s.meta}</span>
                <span className="bb-step-status">{s.status}</span>
              </div>
            ))}
          </div>
        )}
        {m.artifacts && (
          <div className="bb-arts">
            {m.artifacts.map((a, i) => (
              <div key={i} className="bb-art">
                <div className="bb-art-ico">{a.kind === 'data' ? I.chip : I.paper}</div>
                <div><div className="bb-art-name">{a.name}</div><div className="bb-art-size">{a.size}</div></div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { SidebarA, Chat, CONV_SEED });
