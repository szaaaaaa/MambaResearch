from __future__ import annotations

import io
import logging
import math
import re
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".pdf", ".eps")
_DISPLAY_MATH_ENVS = ("equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*")


@dataclass
class ArxivSource:
    arxiv_id: str
    source_dir: Path
    tex_files: List[Path]
    main_tex: Path
    image_files: List[Path]


@dataclass
class LatexFigure:
    figure_id: str
    caption: str
    image_ref: str
    image_path: Path | None
    context_paragraphs: List[str]


@dataclass
class ParsedLatex:
    text: str
    num_pages: int
    figures: List[LatexFigure]


def download_arxiv_source(
    arxiv_id: str,
    source_dir: str,
    polite_delay_sec: float = 1.0,
) -> ArxivSource | None:
    base_dir = Path(source_dir) / arxiv_id
    base_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    try:
        response = requests.get(
            url,
            timeout=90,
            headers={"User-Agent": "auto-research-agent/0.2"},
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to download arXiv source for %s: %s", arxiv_id, exc)
        return None

    data = response.content
    if polite_delay_sec > 0:
        time.sleep(polite_delay_sec)

    extracted = False
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            tf.extractall(base_dir)
            extracted = True
    except tarfile.TarError:
        extracted = False

    if not extracted:
        text_path = base_dir / "main.tex"
        try:
            text_path.write_bytes(data)
        except Exception as exc:
            logger.warning("Failed to persist raw arXiv source for %s: %s", arxiv_id, exc)
            return None

    tex_files = sorted(p for p in base_dir.rglob("*.tex") if p.is_file())
    if not tex_files:
        logger.warning("No .tex files found in arXiv source for %s", arxiv_id)
        return None
    main_tex = _pick_main_tex(tex_files, arxiv_id)
    image_files = sorted(p for p in base_dir.rglob("*") if p.suffix.lower() in _IMAGE_EXTS)
    return ArxivSource(
        arxiv_id=arxiv_id,
        source_dir=base_dir,
        tex_files=tex_files,
        main_tex=main_tex,
        image_files=image_files,
    )


def parse_latex(source: ArxivSource) -> ParsedLatex:
    expanded = _expand_tex_file(source.main_tex, source.source_dir, seen=set())
    if not expanded.strip():
        raise ValueError(f"Expanded LaTeX is empty for {source.main_tex}")
    expanded = _expand_simple_newcommands(expanded)
    body = _extract_document_body(expanded)
    figures = _extract_figures(body, source)
    text = _latex_to_markdown(body)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return ParsedLatex(
        text=text,
        num_pages=max(1, int(math.ceil(max(1, len(text)) / 3000.0))),
        figures=figures,
    )


def _pick_main_tex(tex_files: List[Path], arxiv_id: str) -> Path:
    candidates: List[Path] = []
    for path in tex_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        if "\\documentclass" in text:
            candidates.append(path)
    if candidates:
        return sorted(candidates)[0]

    arxiv_name = arxiv_id.split("/")[-1].split("v", 1)[0]
    for path in tex_files:
        if path.stem == arxiv_name:
            return path
    for name in ("main.tex", "paper.tex"):
        for path in tex_files:
            if path.name.lower() == name:
                return path
    if len(tex_files) == 1:
        return tex_files[0]
    return sorted(tex_files)[0]


def _expand_tex_file(path: Path, root: Path, seen: set[Path]) -> str:
    resolved = path.resolve()
    if resolved in seen or not path.exists():
        return ""
    seen.add(resolved)
    text = path.read_text(encoding="utf-8", errors="ignore")

    def _replace(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        if not target:
            return ""
        rel = Path(target)
        candidates = [rel]
        if not rel.suffix:
            candidates.append(rel.with_suffix(".tex"))
        for candidate in candidates:
            full = (path.parent / candidate).resolve()
            if full.exists():
                return _expand_tex_file(full, root, seen)
            root_full = (root / candidate).resolve()
            if root_full.exists():
                return _expand_tex_file(root_full, root, seen)
        return ""

    return re.sub(r"\\(?:input|include)\{([^}]+)\}", _replace, text)


def _expand_simple_newcommands(text: str) -> str:
    macros: Dict[str, tuple[int, str]] = {}
    for name, argc, body in re.findall(
        r"\\newcommand\{\\([A-Za-z]+)\}(?:\[(\d+)\])?\{((?:[^{}]|\{[^{}]*\})*)\}",
        text,
        flags=re.DOTALL,
    ):
        macros[name] = (int(argc or "0"), body)

    cleaned = re.sub(
        r"\\newcommand\{\\([A-Za-z]+)\}(?:\[(\d+)\])?\{((?:[^{}]|\{[^{}]*\})*)\}",
        "",
        text,
        flags=re.DOTALL,
    )

    for name, (argc, body) in macros.items():
        if argc == 0:
            cleaned = re.sub(rf"\\{name}\b", body, cleaned)
        elif argc == 1:
            cleaned = re.sub(
                rf"\\{name}\{{([^{{}}]+)\}}",
                lambda m: body.replace("#1", m.group(1)),
                cleaned,
            )
    return cleaned


def _extract_document_body(text: str) -> str:
    start = re.search(r"\\begin\{document\}", text)
    end = re.search(r"\\end\{document\}", text)
    if start:
        text = text[start.end():]
    if end:
        text = text[: end.start()]
    return text


def _extract_figures(body: str, source: ArxivSource) -> List[LatexFigure]:
    figures: List[LatexFigure] = []
    for idx, match in enumerate(re.finditer(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", body, re.DOTALL), start=1):
        block = match.group(1)
        caption = _extract_braced_command(block, "caption")
        image_ref = _extract_includegraphics(block)
        figure_id = _extract_braced_command(block, "label") or f"fig_{idx}"
        image_path = _resolve_image_path(source, image_ref) if image_ref else None
        contexts = _find_ref_contexts(body, figure_id)
        figures.append(
            LatexFigure(
                figure_id=figure_id,
                caption=_latex_inline_to_text(caption),
                image_ref=image_ref,
                image_path=image_path,
                context_paragraphs=contexts,
            )
        )
    return figures


def _extract_braced_command(block: str, command: str) -> str:
    match = re.search(rf"\\{command}\{{((?:[^{{}}]|\{{[^{{}}]*\}})*)\}}", block, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_includegraphics(block: str) -> str:
    match = re.search(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", block)
    return match.group(1).strip() if match else ""


def _resolve_image_path(source: ArxivSource, image_ref: str) -> Path | None:
    rel = Path(image_ref)
    candidates = [rel]
    if not rel.suffix:
        candidates.extend(rel.with_suffix(ext) for ext in _IMAGE_EXTS)
    for candidate in list(candidates):
        candidates.append(Path("figures") / candidate)
    for candidate in candidates:
        full = (source.source_dir / candidate).resolve()
        if full.exists():
            return full
    return None


def _find_ref_contexts(body: str, label: str) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    patterns = (
        rf"\\ref\{{{re.escape(label)}\}}",
        rf"\\cref\{{{re.escape(label)}\}}",
        rf"\\autoref\{{{re.escape(label)}\}}",
    )
    out: List[str] = []
    seen = set()
    for paragraph in paragraphs:
        if any(re.search(pattern, paragraph) for pattern in patterns):
            cleaned = _latex_inline_to_text(_latex_to_markdown(paragraph))
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(cleaned)
    return out


def _latex_to_markdown(text: str) -> str:
    out = text
    out = re.sub(r"\\section\*?\{([^}]+)\}", lambda m: f"\n## {m.group(1).strip()}\n", out)
    out = re.sub(r"\\subsection\*?\{([^}]+)\}", lambda m: f"\n### {m.group(1).strip()}\n", out)
    out = re.sub(r"\\subsubsection\*?\{([^}]+)\}", lambda m: f"\n#### {m.group(1).strip()}\n", out)

    for env in _DISPLAY_MATH_ENVS:
        out = re.sub(
            rf"\\begin\{{{re.escape(env)}\}}(.*?)\\end\{{{re.escape(env)}\}}",
            lambda m: "\n$$\n" + _normalize_display_math(m.group(1)) + "\n$$\n",
            out,
            flags=re.DOTALL,
        )

    out = re.sub(
        r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}",
        lambda m: "\n" + _table_env_to_markdown(m.group(1)) + "\n",
        out,
        flags=re.DOTALL,
    )
    out = re.sub(r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", "", out, flags=re.DOTALL)
    out = re.sub(r"\\cite[t|p]?\{([^}]+)\}", lambda m: "[" + m.group(1).strip() + "]", out)
    out = re.sub(r"\\(?:label|ref|cref|autoref)\{([^}]+)\}", lambda m: m.group(1), out)
    out = re.sub(r"\\(?:usepackage|documentclass)(?:\[[^\]]*\])?\{[^}]+\}", "", out)
    out = re.sub(r"\\begin\{abstract\}|\s*\\end\{abstract\}", "", out)
    out = re.sub(r"\\item\s+", "- ", out)
    out = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", "", out)
    out = out.replace("~", " ")
    out = re.sub(r"\{([^{}]+)\}", r"\1", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _normalize_display_math(content: str) -> str:
    out = content.strip()
    out = out.replace("&", " ")
    out = out.replace("\\\\", "\n")
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _table_env_to_markdown(block: str) -> str:
    caption = _latex_inline_to_text(_extract_braced_command(block, "caption"))
    tabular_match = re.search(r"\\begin\{tabular\}.*?(.*?)\\end\{tabular\}", block, re.DOTALL)
    if not tabular_match:
        return caption
    rows = []
    for raw_row in tabular_match.group(1).split("\\\\"):
        row = [re.sub(r"\\hline", "", cell).strip() for cell in raw_row.split("&")]
        row = [_latex_inline_to_text(cell) for cell in row if cell.strip()]
        if row:
            rows.append(row)
    if not rows:
        return caption
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header = "| " + " | ".join(rows[0]) + " |"
    sep = "| " + " | ".join(["---"] * width) + " |"
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows[1:])
    table_md = "\n".join(x for x in (caption, header, sep, body) if x)
    return table_md.strip()


def _latex_inline_to_text(text: str) -> str:
    out = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{([^}]*)\}", r"\1", text)
    out = out.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", out).strip()
