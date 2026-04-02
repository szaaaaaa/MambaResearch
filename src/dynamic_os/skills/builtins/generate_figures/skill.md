模板驱动的图表生成技能。LLM 分析输入 artifact 数据并输出 JSON 图表规格，
由内置模板渲染器（matplotlib / networkx / mermaid-cli）生成 PDF + PNG 图表，
输出 `FigureSet` 供 `draft_report` 嵌入论文。

支持的图表类型：bar_chart, grouped_bar_chart, line_chart, scatter_plot,
heatmap, pie_chart, network_graph, flowchart, sequence_diagram, class_diagram, timeline。

使用 `ctx.tools.llm_chat()` 获取图表规格。
