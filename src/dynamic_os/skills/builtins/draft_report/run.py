from __future__ import annotations

import json

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


_SURVEY_SYSTEM_PROMPT_EN = (
    "You are an academic survey paper writer. Based ONLY on the provided artifacts "
    "(paper notes, evidence maps, source sets), draft a comprehensive survey paper "
    "in ENGLISH as a COMPLETE, COMPILABLE LaTeX document.\n"
    "CRITICAL: The entire paper — title, abstract, all section headings, all body text — "
    "MUST be written in English. Do NOT include any Chinese characters anywhere in the output.\n\n"
)

_SURVEY_SYSTEM_PROMPT_ZH = (
    "You are an academic survey paper writer. Based ONLY on the provided artifacts "
    "(paper notes, evidence maps, source sets), draft a comprehensive survey paper "
    "in CHINESE as a COMPLETE, COMPILABLE LaTeX document.\n"
    "CRITICAL: The entire paper — title, abstract, all section headings, all body text — "
    "MUST be written in Chinese. Section headings MUST use Chinese, NOT English.\n\n"
)

_SURVEY_PREAMBLE = (
    "Output the FULL LaTeX source code starting with \\documentclass and ending with \\end{document}.\n"
    "Do NOT wrap it in ```latex``` code fences. Output raw LaTeX only.\n\n"
    "\\documentclass{article}\n"
    "\\usepackage[utf8]{inputenc}\n"
    "\\usepackage[T1]{fontenc}\n"
    "\\usepackage{times}\n"
    "\\usepackage[margin=1in]{geometry}\n"
    "\\usepackage[numbers,sort&compress]{natbib}\n"
    "\\usepackage{hyperref}\n"
    "\\usepackage{booktabs}\n"
    "\\usepackage{amsmath}\n"
    "\\usepackage{graphicx}\n\n"
)

_SURVEY_STRUCTURE = (
    "Document structure:\n"
    "- Start with \\title, \\author{Research Agent}, \\date{}, \\begin{document}, \\maketitle.\n"
    "- Include \\begin{abstract} ... \\end{abstract}.\n"
    "- Design your own section structure (\\section, \\subsection) based on the research topic. "
    "Choose section titles that best fit the content — do NOT use a generic fixed outline. "
    "For example, a methods-comparison survey might use sections like 'Transformer-Based Approaches' "
    "and 'Diffusion Models', while a domain survey might use 'Applications in Healthcare' and "
    "'Applications in Finance'.\n"
    "- The paper MUST include at minimum: an introduction, a main body with logical subdivisions, "
    "and a conclusion. Beyond that, organize freely.\n"
    "- End with \\bibliographystyle{unsrtnat}, \\bibliography{references}, \\end{document}.\n\n"
)

_SURVEY_TEMPLATE_EN = (
    _SURVEY_STRUCTURE
    + "Example skeleton (adapt section titles to the actual topic):\n\n"
    "\\title{[Descriptive Survey Title]}\n"
    "\\author{Research Agent}\n"
    "\\date{}\n"
    "\\begin{document}\n"
    "\\maketitle\n"
    "\\begin{abstract} ... \\end{abstract}\n"
    "\\section{Introduction}\n"
    "\\section{[Topic-Specific Section Title]} ...\n"
    "\\subsection{[Subtopic]} ...\n"
    "\\section{[Another Topic-Specific Section]} ...\n"
    "\\section{Discussion} ...\n"
    "\\section{Conclusion} ...\n"
    "\\bibliographystyle{unsrtnat}\n"
    "\\bibliography{references}\n"
    "\\end{document}\n\n"
)

_SURVEY_TEMPLATE_ZH = (
    "\\usepackage{ctex}\n\n"
    + _SURVEY_STRUCTURE
    + "Example skeleton (adapt section titles to the actual topic — ALL titles in Chinese):\n\n"
    "\\title{[根据主题拟定的中文标题]}\n"
    "\\author{Research Agent}\n"
    "\\date{}\n"
    "\\begin{document}\n"
    "\\maketitle\n"
    "\\begin{abstract} ... \\end{abstract}\n"
    "\\section{引言}\n"
    "\\section{[根据主题自定的章节标题]} ...\n"
    "\\subsection{[子主题]} ...\n"
    "\\section{[根据主题自定的章节标题]} ...\n"
    "\\section{讨论} ...\n"
    "\\section{结论} ...\n"
    "\\bibliographystyle{unsrtnat}\n"
    "\\bibliography{references}\n"
    "\\end{document}\n\n"
)

_SURVEY_REQUIREMENTS = (
    "Requirements:\n"
    "- A references.bib file is provided separately. Use \\cite{citekey} to cite papers. "
    "Citations will render as numbered references like [1], [2, 3], etc.\n"
    "- EVERY paper listed in the available cite keys MUST be cited at least once using \\cite{}. Do not skip any.\n"
    "- Do NOT include \\begin{thebibliography}. Use \\bibliography{references} instead.\n"
    "- Be thorough and detailed. Each section should have substantive content.\n"
    "- Ensure the LaTeX compiles without errors.\n\n"
    "Writing style (CRITICAL):\n"
    "- Write in continuous, flowing academic prose. NEVER use bullet points (\\begin{itemize}), numbered lists (\\begin{enumerate}), or dash-prefixed lists.\n"
    "- Each paragraph should be a coherent block of text with topic sentences, supporting evidence, and transitions.\n"
    "- Integrate citations naturally into sentences, e.g. 'Recent work \\cite{key} demonstrated that...' or 'as shown in \\cite{key1, key2}', rather than listing papers.\n"
    "- Use connective phrases to link ideas: 'furthermore', 'in contrast', 'building upon this', 'notably', etc.\n"
    "- Mimic the writing style of top-venue survey papers (NeurIPS, ICML, ACL). No informal language, no AI-generated patterns like 'Here are the key findings:' or 'Let us discuss'.\n"
    "- Vary sentence structure and length. Avoid repetitive sentence openings."
)


def _serialize_artifact(artifact) -> str:
    if artifact.artifact_type == "SourceSet":
        sources = artifact.payload.get("sources", [])
        paper_list = [
            {
                "title": s.get("title", ""),
                "paper_id": s.get("paper_id", ""),
                "authors": s.get("authors", []),
                "year": s.get("year", ""),
                "abstract": s.get("abstract", s.get("content", ""))[:300],
            }
            for s in sources
        ]
        return json.dumps({"paper_count": len(paper_list), "papers": paper_list}, ensure_ascii=False, indent=2)
    return json.dumps(artifact.payload, ensure_ascii=False, indent=2)


async def run(ctx: SkillContext) -> SkillOutput:
    language = str(ctx.config.get("agent", {}).get("language", "en")).strip().lower()
    is_zh = language in ("zh", "cn", "chinese")

    if is_zh:
        system_prompt = _SURVEY_SYSTEM_PROMPT_ZH + _SURVEY_PREAMBLE + _SURVEY_TEMPLATE_ZH + _SURVEY_REQUIREMENTS
    else:
        system_prompt = _SURVEY_SYSTEM_PROMPT_EN + _SURVEY_PREAMBLE + _SURVEY_TEMPLATE_EN + _SURVEY_REQUIREMENTS

    artifact_text = "\n\n".join(
        f"{artifact.artifact_type}:\n{_serialize_artifact(artifact)}"
        for artifact in ctx.input_artifacts
    )

    review_feedback = ""
    for art in ctx.input_artifacts:
        if art.artifact_type == "ReviewVerdict" and art.payload.get("verdict") == "needs_revision":
            suggestions = str(art.payload.get("modification_suggestions", ""))
            issues = art.payload.get("issues", [])
            review_feedback = f"\n\nREVISION REQUIRED based on prior review:\nSuggestions: {suggestions}\nIssues: {', '.join(issues)}"
            break

    user_guidance = ""
    for art in ctx.input_artifacts:
        if art.artifact_type == "UserGuidance":
            user_guidance = f"\n\nUser guidance: {art.payload.get('response', '')}"
            break

    figure_info = ""
    for art in ctx.input_artifacts:
        if art.artifact_type == "FigureSet":
            paths = list(art.payload.get("figure_paths", []))
            descriptions = list(art.payload.get("descriptions", []))
            if paths:
                figure_lines = []
                for i, path in enumerate(paths):
                    desc = descriptions[i] if i < len(descriptions) else f"Figure {i + 1}"
                    filename = path.rsplit("/", 1)[-1] if "/" in path else path
                    figure_lines.append(f"  - {filename}: {desc}")
                figure_info = (
                    "\n\nAvailable figures (include ALL of them in the paper using \\includegraphics):\n"
                    + "\n".join(figure_lines)
                    + "\n\nFor each figure, use this LaTeX pattern:\n"
                    + "\\begin{figure}[htbp]\n"
                    + "  \\centering\n"
                    + "  \\includegraphics[width=0.8\\textwidth]{figures/FILENAME}\n"
                    + "  \\caption{DESCRIPTION}\n"
                    + "  \\label{fig:LABEL}\n"
                    + "\\end{figure}\n"
                    + "\nPlace each figure in a relevant section and reference it in the text using \\ref{fig:LABEL}."
                )
            break

    cite_keys_info = ""
    if ctx.config.get("_cite_keys_map"):
        key_map = ctx.config["_cite_keys_map"]
        lines = [f"  \\cite{{{k}}} → {t}" for k, t in key_map.items()]
        cite_keys_info = (
            "\n\nCite key reference table (use ONLY these exact keys with \\cite{}, do NOT invent or modify keys):\n"
            + "\n".join(lines)
        )
    elif ctx.config.get("_cite_keys"):
        keys = ctx.config["_cite_keys"]
        cite_keys_info = f"\n\nAvailable cite keys (use ONLY these exact keys, do NOT modify them): {', '.join(keys)}"

    user_content = (
        f"Research topic: {ctx.user_request}\n\nArtifacts:\n{artifact_text}{cite_keys_info}"
        if artifact_text
        else ctx.user_request or ctx.goal
    )
    user_content += review_feedback
    user_content += user_guidance
    user_content += figure_info
    report_text = await ctx.tools.llm_chat(
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
        temperature=0.3,
        max_tokens=32768,
    )
    artifact = make_artifact(
        node_id=ctx.node_id,
        artifact_type="ResearchReport",
        producer_role=RoleId(ctx.role_id),
        producer_skill=ctx.skill_id,
        payload={
            "report": report_text,
            "artifact_count": len(ctx.input_artifacts),
        },
        source_inputs=source_input_refs(ctx.input_artifacts),
    )
    return SkillOutput(success=True, output_artifacts=[artifact])
