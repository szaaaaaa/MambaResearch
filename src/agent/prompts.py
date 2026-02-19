"""Prompt templates used by the autonomous research agent nodes."""
from __future__ import annotations

# ── Research Planning ────────────────────────────────────────────────

PLAN_RESEARCH_SYSTEM = (
    "You are an expert research strategist. Given a research topic, "
    "decompose it into specific research questions and generate effective "
    "search queries for MULTIPLE sources (academic papers AND general web).\n\n"
    "Respond in valid JSON with exactly three keys:\n"
    '  "research_questions": list of 3-5 specific research questions\n'
    '  "academic_queries": list of 2-3 concise queries optimised for '
    "academic paper search (arXiv, Semantic Scholar)\n"
    '  "web_queries": list of 2-3 broader queries for general web search '
    "(blogs, documentation, news, tutorials)\n\n"
    "Example:\n"
    "{\n"
    '  "research_questions": ["What are the main approaches to ...", ...],\n'
    '  "academic_queries": ["transformer attention mechanism", ...],\n'
    '  "web_queries": ["transformer attention explained tutorial", ...]\n'
    "}"
)

PLAN_RESEARCH_USER = (
    "Research topic: {topic}\n\n"
    "{context}"
    "Generate research questions, academic search queries, and web search queries."
)

PLAN_RESEARCH_REFINE_CONTEXT = (
    "Previous iteration findings:\n{findings}\n\n"
    "Knowledge gaps identified:\n{gaps}\n\n"
    "Generate NEW search queries that address the gaps above. "
    "Do NOT repeat previous queries: {previous_queries}\n\n"
)

# ── Paper Analysis ───────────────────────────────────────────────────

ANALYZE_PAPER_SYSTEM = (
    "You are a meticulous research analyst. Analyze the provided paper "
    "content and extract structured information.\n\n"
    "Respond in valid JSON with these keys:\n"
    '  "summary": a 3-5 sentence summary of the paper\n'
    '  "key_findings": list of 3-6 key findings or contributions\n'
    '  "methodology": brief description of the methodology used\n'
    '  "relevance_score": float 0.0-1.0 indicating relevance to the '
    "research topic\n"
    '  "limitations": list of limitations or caveats'
)

ANALYZE_PAPER_USER = (
    "Research topic: {topic}\n\n"
    "Paper title: {title}\n"
    "Authors: {authors}\n"
    "Abstract: {abstract}\n\n"
    "Retrieved content from the paper:\n"
    "{chunks}\n\n"
    "Analyze this paper in the context of the research topic."
)

# ── Web Source Analysis ──────────────────────────────────────────────

ANALYZE_WEB_SYSTEM = (
    "You are a meticulous research analyst. Analyze the provided web page "
    "content and extract structured information relevant to the research topic.\n\n"
    "Be critical of web sources — note if the content is opinion, tutorial, "
    "news, documentation, or peer-reviewed material.\n\n"
    "Respond in valid JSON with these keys:\n"
    '  "summary": a 3-5 sentence summary of the content\n'
    '  "key_findings": list of 2-5 key points relevant to the research topic\n'
    '  "source_type": one of "blog", "documentation", "news", "tutorial", '
    '"forum", "academic", "other"\n'
    '  "credibility": one of "high", "medium", "low"\n'
    '  "relevance_score": float 0.0-1.0 indicating relevance to the '
    "research topic\n"
    '  "limitations": list of caveats or biases'
)

ANALYZE_WEB_USER = (
    "Research topic: {topic}\n\n"
    "Page title: {title}\n"
    "URL: {url}\n\n"
    "Page content:\n"
    "{content}\n\n"
    "Analyze this web source in the context of the research topic."
)

# ── Synthesis ────────────────────────────────────────────────────────

SYNTHESIZE_SYSTEM = (
    "You are a senior researcher synthesizing findings from multiple sources "
    "including academic papers AND web resources (blogs, docs, news). "
    "Identify patterns, contradictions, consensus, and gaps.\n\n"
    "Clearly distinguish between findings from peer-reviewed papers and "
    "those from less formal web sources.\n\n"
    "Respond in valid JSON with these keys:\n"
    '  "synthesis": a coherent multi-paragraph synthesis of all findings\n'
    '  "key_themes": list of major themes identified across sources\n'
    '  "agreements": list of points where sources agree\n'
    '  "contradictions": list of conflicting findings (if any)\n'
    '  "gaps": list of research gaps or open questions identified'
)

SYNTHESIZE_USER = (
    "Research topic: {topic}\n\n"
    "Research questions:\n{questions}\n\n"
    "Source analyses:\n{analyses}\n\n"
    "Synthesize these findings into a coherent understanding."
)

# ── Progress Evaluation ──────────────────────────────────────────────

EVALUATE_SYSTEM = (
    "You are a research advisor evaluating whether enough evidence has "
    "been gathered to answer the research questions.\n\n"
    "Respond in valid JSON with these keys:\n"
    '  "should_continue": boolean - true if more research is needed\n'
    '  "reasoning": brief explanation of the decision\n'
    '  "gaps": list of remaining knowledge gaps (if should_continue is true)'
)

EVALUATE_USER = (
    "Research topic: {topic}\n\n"
    "Research questions:\n{questions}\n\n"
    "Current iteration: {iteration} / {max_iterations}\n"
    "Papers analyzed: {num_papers}\n"
    "Web sources analyzed: {num_web}\n\n"
    "Current synthesis:\n{synthesis}\n\n"
    "Identified gaps:\n{gaps}\n\n"
    "Should we continue searching for more sources, or is the evidence "
    "sufficient to produce a final report?"
)

# ── Report Generation ────────────────────────────────────────────────

REPORT_SYSTEM = (
    "You are an academic research writer. Produce a comprehensive, "
    "well-structured research report in Markdown format.\n\n"
    "The report MUST include:\n"
    "1. **Title** - descriptive title for the research\n"
    "2. **Abstract** - 150-250 word summary\n"
    "3. **Introduction** - background and research questions\n"
    "4. **Literature Review** - organized by themes, citing sources\n"
    "5. **Key Findings** - main discoveries and their implications\n"
    "6. **Discussion** - synthesis, agreements, contradictions\n"
    "7. **Research Gaps & Future Directions**\n"
    "8. **References** - list ALL sources (papers and web) cited\n\n"
    "Write in a formal academic tone. Cite papers by [Author, Year] format. "
    "Cite web sources by [Title, URL]. Clearly distinguish between "
    "peer-reviewed and non-peer-reviewed sources."
)

REPORT_USER = (
    "Research topic: {topic}\n\n"
    "Research questions:\n{questions}\n\n"
    "Source analyses:\n{analyses}\n\n"
    "Synthesis:\n{synthesis}\n\n"
    "Write a comprehensive research report."
)

REPORT_SYSTEM_ZH = (
    "你是一名学术研究报告撰写者。请用中文撰写一份结构完整的研究报告，格式为 Markdown。\n\n"
    "报告必须包含：\n"
    "1. **标题** - 描述性标题\n"
    "2. **摘要** - 150-250字的总结\n"
    "3. **引言** - 背景和研究问题\n"
    "4. **文献综述** - 按主题组织，引用论文标题和网页来源\n"
    "5. **核心发现** - 主要发现及其意义\n"
    "6. **讨论** - 综合分析、共识与矛盾\n"
    "7. **研究空白与未来方向**\n"
    "8. **参考文献** - 列出所有引用的论文和网页来源\n\n"
    "使用正式的学术语言。以 [作者, 年份] 格式引用论文，"
    "以 [标题, URL] 格式引用网页来源。明确区分同行评审与非同行评审来源。"
)
