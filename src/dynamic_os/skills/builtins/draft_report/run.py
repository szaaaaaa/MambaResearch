from __future__ import annotations

import json
import re

from src.dynamic_os.artifact_refs import make_artifact, source_input_refs
from src.dynamic_os.contracts.route_plan import RoleId
from src.dynamic_os.contracts.skill_io import SkillContext, SkillOutput


_SURVEY_SYSTEM_PROMPT_EN = (
    "You are an academic survey paper writer. Based ONLY on the provided artifacts "
    "(paper notes, evidence maps, source sets), draft a comprehensive survey paper "
    "in ENGLISH as a COMPLETE, COMPILABLE LaTeX document.\n\n"
)

_SURVEY_SYSTEM_PROMPT_ZH = (
    "You are an academic survey paper writer. Based ONLY on the provided artifacts "
    "(paper notes, evidence maps, source sets), draft a comprehensive survey paper "
    "in CHINESE as a COMPLETE, COMPILABLE LaTeX document.\n\n"
)

_SURVEY_TEMPLATE = (
    "Output the FULL LaTeX source code starting with \\documentclass and ending with \\end{document}.\n"
    "Do NOT wrap it in ```latex``` code fences. Output raw LaTeX only.\n\n"
    "Use this exact template structure:\n\n"
    "\\documentclass{article}\n"
    "\\usepackage[utf8]{inputenc}\n"
    "\\usepackage[T1]{fontenc}\n"
    "\\usepackage{times}\n"
    "\\usepackage[margin=1in]{geometry}\n"
    "\\usepackage{natbib}\n"
    "\\usepackage{hyperref}\n"
    "\\usepackage{booktabs}\n"
    "\\usepackage{amsmath}\n"
    "% For NeurIPS: replace the above with \\usepackage{neurips_2024} on Overleaf\n\n"
    "\\title{[Survey Title]}\n"
    "\\author{Research Agent}\n"
    "\\date{}\n\n"
    "\\begin{document}\n"
    "\\maketitle\n\n"
    "\\begin{abstract} ... \\end{abstract}\n\n"
    "\\section{Introduction} ...\n"
    "\\section{Background} ...\n"
    "\\section{Taxonomy} ...\n"
    "\\section{Review of Methods}\n"
    "\\subsection{Category 1} ...\n"
    "\\subsection{Category 2} ...\n"
    "\\section{Comparison and Discussion} ...\n"
    "\\section{Future Directions} ...\n"
    "\\section{Conclusion} ...\n\n"
    "\\bibliographystyle{plainnat}\n"
    "\\bibliography{references}\n\n"
    "\\end{document}\n\n"
    "Requirements:\n"
    "- A references.bib file is provided separately. Use \\cite{citekey} to cite papers.\n"
    "- EVERY paper listed in the available cite keys MUST be cited at least once using \\cite{}. Do not skip any.\n"
    "- Do NOT include \\begin{thebibliography}. Use \\bibliography{references} instead.\n"
    "- Use \\subsection for each category in the Review of Methods section.\n"
    "- Be thorough and detailed. Each section should have substantive content.\n"
    "- Ensure the LaTeX compiles without errors.\n\n"
    "Writing style (CRITICAL):\n"
    "- Write in continuous, flowing academic prose. NEVER use bullet points (\\begin{itemize}), numbered lists (\\begin{enumerate}), or dash-prefixed lists.\n"
    "- Each paragraph should be a coherent block of text with topic sentences, supporting evidence, and transitions.\n"
    "- Integrate citations naturally into sentences, e.g. 'Recent work by \\cite{key} demonstrated that...' rather than listing papers.\n"
    "- Use connective phrases to link ideas: 'furthermore', 'in contrast', 'building upon this', 'notably', etc.\n"
    "- Mimic the writing style of top-venue survey papers (NeurIPS, ICML, ACL). No informal language, no AI-generated patterns like 'Here are the key findings:' or 'Let us discuss'.\n"
    "- Vary sentence structure and length. Avoid repetitive sentence openings."
)

_SURVEY_ZH_EXTRA = (
    "\n- Add \\usepackage{ctex} right after \\documentclass{article} for Chinese support."
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

    system_prompt = (_SURVEY_SYSTEM_PROMPT_ZH if is_zh else _SURVEY_SYSTEM_PROMPT_EN) + _SURVEY_TEMPLATE
    if is_zh:
        system_prompt += _SURVEY_ZH_EXTRA

    artifact_text = "\n\n".join(
        f"{artifact.artifact_type}:\n{_serialize_artifact(artifact)}"
        for artifact in ctx.input_artifacts
    )

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
