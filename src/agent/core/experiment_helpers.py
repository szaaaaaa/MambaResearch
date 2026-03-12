"""Experiment planning helpers shared by facade wrappers and tests."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List

from src.agent.prompts import (
    DOMAIN_DETECT_SYSTEM,
    DOMAIN_DETECT_USER,
    EXPERIMENT_RESULTS_NORMALIZE_SYSTEM,
    EXPERIMENT_RESULTS_NORMALIZE_USER,
)

logger = logging.getLogger(__name__)

_ML_DOMAIN_KEYWORDS = {
    "transformer", "attention", "finetune", "fine-tune", "fine-tuning",
    "pretrain", "pre-train", "pretraining", "pre-training",
    "benchmark", "dataset", "baseline", "ablation",
    "backpropagation", "gradient descent", "stochastic gradient",
    "neural network", "deep learning", "machine learning",
    "convolutional", "recurrent", "lstm", "gru", "bert", "gpt",
    "diffusion", "generative", "gan", "vae", "autoencoder",
    "reinforcement learning", "reward", "policy gradient", "q-learning",
    "classification", "detection", "segmentation", "recognition",
    "embedding", "tokenizer", "tokenization",
    "huggingface", "pytorch", "tensorflow", "jax",
    "epoch", "batch size", "learning rate", "optimizer",
    "loss function", "cross-entropy", "dropout", "regularization",
    "convolution", "pooling", "softmax", "activation",
    "retrieval-augmented", "rag", "prompt tuning", "lora", "qlora",
    "knowledge distillation", "model compression", "quantization",
    "object detection", "image classification", "named entity",
    "text classification", "sentiment analysis", "question answering",
    "language model", "vision transformer", "multimodal",
    "contrastive learning", "self-supervised", "semi-supervised",
    "federated learning", "meta-learning", "few-shot", "zero-shot",
    "hyperparameter", "grid search", "random search", "bayesian optimization",
    "time series", "time-series", "forecasting", "streaming", "online learning",
    "continual learning", "concept drift", "drift adaptation",
    "replay", "experience replay", "prioritized replay", "prototype replay", "prototype",
}

_EXPERIMENT_ELIGIBLE_DOMAINS = {
    "machine_learning", "deep_learning", "cv", "nlp", "rl",
}


def _detect_domain_by_rules(topic: str, research_questions: List[str]) -> bool:
    combined_text = " ".join([str(topic or "")] + [str(question or "") for question in research_questions]).lower()
    hit_count = sum(1 for keyword in _ML_DOMAIN_KEYWORDS if keyword in combined_text)
    return hit_count >= 2


def _detect_domain_by_llm(
    topic: str,
    research_questions: List[str],
    cfg: Dict[str, Any],
    *,
    llm_call: Callable[..., str],
    parse_json: Callable[[str], Dict[str, Any]],
) -> Dict[str, str]:
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.1)
    rq_text = "\n".join(f"- {question}" for question in research_questions) if research_questions else "(none)"
    prompt = DOMAIN_DETECT_USER.format(topic=topic, research_questions=rq_text)
    raw = llm_call(
        DOMAIN_DETECT_SYSTEM,
        prompt,
        cfg=cfg,
        model=model,
        temperature=temperature,
    )
    try:
        result = parse_json(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Domain detector returned invalid JSON") from exc
    return {
        "domain": str(result.get("domain", "other")).strip().lower(),
        "subfield": str(result.get("subfield", "")).strip(),
        "task_type": str(result.get("task_type", "")).strip(),
    }


def _limit_experiment_groups_per_rq(
    plan: Dict[str, Any],
    *,
    max_per_rq: int,
) -> tuple[Dict[str, Any], int]:
    if not isinstance(plan, dict):
        return {}, 0

    rq_experiments = plan.get("rq_experiments", [])
    if not isinstance(rq_experiments, list):
        plan["rq_experiments"] = []
        return plan, 0

    cap = max(1, int(max_per_rq))
    seen: Dict[str, int] = {}
    limited: List[Dict[str, Any]] = []
    dropped = 0
    for experiment in rq_experiments:
        if not isinstance(experiment, dict):
            dropped += 1
            continue
        rq = re.sub(r"\s+", " ", str(experiment.get("research_question", "")).strip()).lower()
        key = rq or "__missing_rq__"
        count = seen.get(key, 0)
        if count >= cap:
            dropped += 1
            continue
        seen[key] = count + 1
        limited.append(experiment)

    plan["rq_experiments"] = limited
    return plan, dropped


def _normalize_experiment_results_with_llm(
    *,
    raw_results: Any,
    research_questions: List[str],
    experiment_plan: Dict[str, Any],
    cfg: Dict[str, Any],
    llm_call: Callable[..., str],
    parse_json: Callable[[str], Dict[str, Any]],
) -> Dict[str, Any]:
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.0)
    rq_text = "\n".join(f"- {question}" for question in research_questions) if research_questions else "(none)"
    try:
        plan_text = json.dumps(experiment_plan or {}, ensure_ascii=False, indent=2)
    except Exception:
        plan_text = "{}"
    if isinstance(raw_results, str):
        raw_text = raw_results
    else:
        try:
            raw_text = json.dumps(raw_results, ensure_ascii=False, indent=2)
        except Exception:
            raw_text = str(raw_results)

    prompt = EXPERIMENT_RESULTS_NORMALIZE_USER.format(
        research_questions=rq_text,
        experiment_plan=plan_text,
        raw_results=raw_text,
    )
    raw = llm_call(
        EXPERIMENT_RESULTS_NORMALIZE_SYSTEM,
        prompt,
        cfg=cfg,
        model=model,
        temperature=temperature,
    )
    try:
        parsed = parse_json(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Experiment results normalizer returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Experiment results normalizer returned an invalid payload")
    return parsed
