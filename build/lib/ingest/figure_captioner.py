from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, TYPE_CHECKING

from src.ingest.chunking import Chunk

if TYPE_CHECKING:
    from src.ingest.figure_extractor import FigureContext


@dataclass
class ValidationResult:
    passed: bool
    entity_match_rate: float
    matched_entities: List[str]
    missing_entities: List[str]
    description: str


@dataclass
class FigureChunkData:
    figure_id: str
    caption: str
    context: str
    visual_description: str
    image_path: str
    validation_passed: bool


def describe_figure(
    *,
    image_path: Path,
    caption: str,
    context_paragraphs: List[str],
    paper_title: str,
    vlm_model: str = "gemini-2.5-flash",
    temperature: float = 0.1,
) -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY) in environment variables.")

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError(
            "Missing dependency 'google-genai'. Install with: pip install -e ."
        ) from exc

    client = genai.Client(api_key=api_key)
    user_prompt = (
        f"Paper title: {paper_title}\n\n"
        "Author's caption for this figure:\n"
        f"{caption or '(none)'}\n\n"
        "Relevant paragraphs from the paper that reference this figure:\n"
        f"{chr(10).join(context_paragraphs) if context_paragraphs else '(none)'}\n\n"
        "Analyze the figure image and provide a structured description:\n"
        "1. CHART TYPE\n"
        "2. AXES\n"
        "3. DATA SERIES\n"
        "4. KEY VALUES\n"
        "5. VISUAL ELEMENTS\n\n"
        "Rules:\n"
        "- Only report values you can clearly read from the figure.\n"
        "- If a value is not clearly readable, say 'not clearly readable'.\n"
        "- If the caption mentions something not visible in the image, note it explicitly.\n"
        "- Do NOT interpret results. Only describe what is visible."
    )
    image_bytes = image_path.read_bytes()
    response = client.models.generate_content(
        model=vlm_model,
        contents=[
            user_prompt,
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        ],
        config={
            "temperature": float(temperature),
            "system_instruction": (
                "You are an academic figure analyst. Describe only what is directly visible "
                "in the image. Do not speculate."
            ),
        },
    )
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    raise RuntimeError("Gemini vision response has no text content.")


def validate_description(
    vlm_description: str,
    caption: str,
    min_entity_match: float = 0.5,
) -> ValidationResult:
    caption = (caption or "").strip()
    description = (vlm_description or "").strip()
    if not caption:
        return ValidationResult(
            passed=True,
            entity_match_rate=1.0,
            matched_entities=[],
            missing_entities=[],
            description=description,
        )

    entities = _extract_caption_entities(caption)
    if not entities:
        return ValidationResult(
            passed=True,
            entity_match_rate=1.0,
            matched_entities=[],
            missing_entities=[],
            description=description,
        )

    desc_lower = description.lower()
    matched = [entity for entity in entities if entity.lower() in desc_lower]
    missing = [entity for entity in entities if entity.lower() not in desc_lower]
    rate = len(matched) / max(1, len(entities))
    passed = rate >= min_entity_match
    return ValidationResult(
        passed=passed,
        entity_match_rate=rate,
        matched_entities=matched,
        missing_entities=missing,
        description=description if passed else "",
    )


def process_figures(
    *,
    figure_contexts: List[FigureContext],
    paper_title: str,
    vlm_model: str = "gemini-2.5-flash",
    temperature: float = 0.1,
    validation_min_entity_match: float = 0.5,
) -> List[FigureChunkData]:
    out: List[FigureChunkData] = []
    for figure in figure_contexts:
        description = ""
        passed = False
        try:
            description = describe_figure(
                image_path=figure.image_path,
                caption=figure.caption,
                context_paragraphs=figure.context_paragraphs,
                paper_title=paper_title,
                vlm_model=vlm_model,
                temperature=temperature,
            )
            validation = validate_description(
                description,
                figure.caption,
                min_entity_match=validation_min_entity_match,
            )
            description = validation.description
            passed = validation.passed
        except Exception:
            description = ""
            passed = False

        out.append(
            FigureChunkData(
                figure_id=figure.figure_id,
                caption=figure.caption,
                context="\n".join(figure.context_paragraphs).strip(),
                visual_description=description,
                image_path=str(figure.image_path),
                validation_passed=passed,
            )
        )
    return out


def figure_data_to_chunks(
    figures: List[FigureChunkData],
    doc_id: str,
    text_chunk_count: int,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    next_idx = int(text_chunk_count)
    for figure in figures:
        lines = [f"[Figure {figure.figure_id}]"]
        if figure.caption:
            lines.append(f"Caption: {figure.caption}")
        if figure.context:
            lines.append(f"Context: {figure.context}")
        if figure.visual_description:
            lines.append(f"Description: {figure.visual_description}")
        if len(lines) == 1:
            continue
        chunks.append(
            Chunk(
                chunk_id=f"chunk_{next_idx:06d}",
                text="\n".join(lines),
                start_char=-1,
                end_char=-1,
                metadata={
                    "figure_id": figure.figure_id,
                    "image_path": figure.image_path,
                    "doc_id": doc_id,
                },
            )
        )
        next_idx += 1
    return chunks


def _extract_caption_entities(caption: str) -> List[str]:
    patterns = [
        r"\b\d+\.?\d*\s*(?:%|ms|sec|s|accuracy|f1|bleu|auc)\b",
        r"\b[A-Z][A-Z0-9-]{1,}\b",
        r"\b(?:increase|decrease|outperform|better|worse|higher|lower)\b",
        r"\b[A-Za-z0-9_-]+\s*(?:>|<|>=|<=|vs\.?)\s*[A-Za-z0-9_-]+\b",
    ]
    seen = set()
    out: List[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, caption, flags=re.IGNORECASE):
            entity = str(match).strip()
            key = entity.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(entity)
    return out
