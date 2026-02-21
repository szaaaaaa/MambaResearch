# Experimental Blueprint -- Extension Development Guide

> **Feature**: When the research topic falls within ML/DL/CV/NLP/RL domains, the agent automatically generates a structured **Experimental Blueprint** chapter in the final report, providing actionable experiment plans including datasets, code frameworks, environment configs, hyperparameters, run commands, and evaluation protocols.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Step 1 -- Extend State Schema (`schemas.py`)](#2-step-1----extend-state-schema)
3. [Step 2 -- Add Prompt Templates (`prompts.py`)](#3-step-2----add-prompt-templates)
4. [Step 3 -- Implement `recommend_experiments` Node (`nodes.py`)](#4-step-3----implement-recommend_experiments-node)
5. [Step 4 -- Register Node and Edges (`graph.py`)](#5-step-4----register-node-and-edges)
6. [Step 5 -- Integrate into Report Generation (`nodes.py :: generate_report`)](#6-step-5----integrate-into-report-generation)
7. [Step 6 -- Quality Gate Enhancement](#7-step-6----quality-gate-enhancement)
8. [Step 7 -- State Access Layer Update (`state_access.py`)](#8-step-7----state-access-layer-update)
9. [Step 8 -- Configuration Support (`config.py`)](#9-step-8----configuration-support)
10. [Output Schema Reference](#10-output-schema-reference)
11. [Testing Strategy](#11-testing-strategy)
12. [Checklist](#12-checklist)

---

## 1. Architecture Overview

### Current Graph Topology

```
plan_research -> fetch_sources -> index_sources -> analyze_sources
    -> synthesize -> evaluate_progress --(loop)--> plan_research
                                       --(done)--> generate_report -> END
```

### New Graph Topology (after this change)

```
plan_research -> fetch_sources -> index_sources -> analyze_sources
    -> synthesize -> recommend_experiments -> evaluate_progress --(loop)--> plan_research
                                                                --(done)--> generate_report -> END
```

The new `recommend_experiments` node is inserted between `synthesize` and `evaluate_progress`. It reads the synthesized research context, performs domain detection, and conditionally generates experiment plans. When the topic does not fall in ML/DL/CV/NLP/RL, it passes through as a no-op.

### Key Design Principles

- **Rule + LLM dual detection**: First apply keyword-based rules for domain classification, then confirm with LLM. Only trigger when both agree the domain is experimental.
- **Fixed output schema**: The experiment plan follows a strict JSON schema with mandatory fields for reproducibility.
- **Per-RQ experiments**: Each research question gets 1-2 experiment proposals.
- **Non-invasive**: For non-ML topics, the node is a no-op and adds no content to the report.

---

## 2. Step 1 -- Extend State Schema

**File**: `src/agent/core/schemas.py`

### 2.1 Add `ExperimentPlan` TypedDict

Add the following type definitions after the existing `RunMetrics` class:

```python
class DatasetInfo(TypedDict, total=False):
    name: str
    url: str
    license: str
    reason: str

class CodeFramework(TypedDict, total=False):
    stack: str
    starter_repo: str
    notes: str

class EnvironmentSpec(TypedDict, total=False):
    python: str
    cuda: str
    pytorch: str
    gpu: str
    deps: List[str]

class HyperparamBaseline(TypedDict, total=False):
    lr: float
    batch_size: int
    epochs: int
    seed: List[int]

class HyperparamSearchSpace(TypedDict, total=False):
    lr: List[float]
    warmup_ratio: List[float]

class Hyperparameters(TypedDict, total=False):
    baseline: HyperparamBaseline
    search_space: HyperparamSearchSpace

class RunCommands(TypedDict, total=False):
    train: str
    eval: str

class EvaluationProtocol(TypedDict, total=False):
    metrics: List[str]
    protocol: str

class EvidenceRef(TypedDict, total=False):
    uid: str
    url: str

class RQExperiment(TypedDict, total=False):
    research_question: str
    task: str
    datasets: List[DatasetInfo]
    code_framework: CodeFramework
    environment: EnvironmentSpec
    hyperparameters: Hyperparameters
    run_commands: RunCommands
    evaluation: EvaluationProtocol
    evidence_refs: List[EvidenceRef]

class ExperimentPlan(TypedDict, total=False):
    domain: str
    subfield: str
    task_type: str
    rq_experiments: List[RQExperiment]
```

### 2.2 Add `experiment_plan` to `ResearchState`

Add the field to both the `ResearchNamespace` and the legacy flat fields section of `ResearchState`:

```python
class ResearchNamespace(TypedDict, total=False):
    # ... existing fields ...
    experiment_plan: ExperimentPlan          # <-- ADD

class ResearchState(TypedDict, total=False):
    # ... existing fields ...
    experiment_plan: ExperimentPlan          # <-- ADD (legacy flat)
```

### 2.3 Export the new types

Update `src/agent/state.py` to re-export the new types:

```python
from src.agent.core.schemas import (
    # ... existing imports ...
    ExperimentPlan,
    RQExperiment,
)

__all__ = [
    # ... existing exports ...
    "ExperimentPlan",
    "RQExperiment",
]
```

---

## 3. Step 2 -- Add Prompt Templates

**File**: `src/agent/prompts.py`

Add the following two prompt constants at the end of the file:

```python
# -- Experiment Recommendation (Experimental Blueprint) -------------------

EXPERIMENT_PLAN_SYSTEM = (
    "You are an expert ML research engineer. Given a research topic, research "
    "questions, and evidence from analyzed papers, you produce a concrete, "
    "reproducible experiment plan.\n\n"
    "Rules:\n"
    "- For each research question, propose 1-2 experiment groups.\n"
    "- Every dataset MUST include a real, resolvable URL and license.\n"
    "- The code framework MUST reference a real, existing GitHub starter repo.\n"
    "- Environment specs MUST include python version, CUDA version, PyTorch version, and GPU recommendation.\n"
    "- Hyperparameters MUST include a concrete baseline AND a search space.\n"
    "- Run commands MUST be executable shell commands (train + eval).\n"
    "- Evaluation MUST specify metrics and statistical protocol (e.g. seed count, bootstrap).\n"
    "- evidence_refs MUST link back to paper UIDs/DOIs from the provided analyses.\n"
    "- Do NOT invent datasets or repos that do not exist.\n"
    "- Output valid JSON only, no markdown fences.\n\n"
    "Output schema:\n"
    "{\n"
    '  "domain": "<machine_learning|deep_learning|cv|nlp|rl>",\n'
    '  "subfield": "<e.g. retrieval-augmented generation>",\n'
    '  "task_type": "<e.g. text classification, object detection>",\n'
    '  "rq_experiments": [\n'
    "    {\n"
    '      "research_question": "...",\n'
    '      "task": "...",\n'
    '      "datasets": [{"name":"...","url":"...","license":"...","reason":"..."}],\n'
    '      "code_framework": {"stack":"...","starter_repo":"https://...","notes":"..."},\n'
    '      "environment": {"python":"...","cuda":"...","pytorch":"...","gpu":"...","deps":["..."]},\n'
    '      "hyperparameters": {\n'
    '        "baseline":{"lr":2e-5,"batch_size":16,"epochs":3,"seed":[42,43,44]},\n'
    '        "search_space":{"lr":[1e-5,2e-5,5e-5],"warmup_ratio":[0.03,0.1]}\n'
    "      },\n"
    '      "run_commands": {"train":"python train.py ...","eval":"python eval.py ..."},\n'
    '      "evaluation": {"metrics":["..."],"protocol":"3 seeds + paired bootstrap"},\n'
    '      "evidence_refs": [{"uid":"...","url":"..."}]\n'
    "    }\n"
    "  ]\n"
    "}\n"
)

EXPERIMENT_PLAN_USER = (
    "Research topic: {topic}\n\n"
    "Detected domain: {domain}\n"
    "Detected subfield: {subfield}\n"
    "Detected task type: {task_type}\n\n"
    "Research questions:\n{research_questions}\n\n"
    "Claim-Evidence Map:\n{claim_evidence_map}\n\n"
    "Source analyses (key papers with methodology and findings):\n{analyses}\n\n"
    "Generate a concrete, reproducible experiment plan for each research question. "
    "Ensure every field in the schema is populated with real, verifiable information."
)

DOMAIN_DETECT_SYSTEM = (
    "You are a research domain classifier. Given a research topic and research questions, "
    "determine the academic domain, subfield, and task type.\n\n"
    "Respond in valid JSON with exactly three keys:\n"
    '  "domain": one of "machine_learning", "deep_learning", "cv", "nlp", "rl", or "other"\n'
    '  "subfield": a specific subfield (e.g. "retrieval-augmented generation", '
    '"object detection", "policy optimization")\n'
    '  "task_type": the specific ML task (e.g. "text classification", '
    '"image segmentation", "reward shaping")\n\n'
    "Only classify as an ML-related domain if the topic genuinely involves "
    "training, evaluating, or benchmarking ML/DL models. Pure theoretical, "
    "social science, or humanities topics should be classified as \"other\"."
)

DOMAIN_DETECT_USER = (
    "Research topic: {topic}\n\n"
    "Research questions:\n{research_questions}\n\n"
    "Classify the domain."
)
```

---

## 4. Step 3 -- Implement `recommend_experiments` Node

**File**: `src/agent/nodes.py`

### 4.1 Add imports

At the top of `nodes.py`, extend the imports from `prompts.py`:

```python
from src.agent.prompts import (
    # ... existing imports ...
    EXPERIMENT_PLAN_SYSTEM,
    EXPERIMENT_PLAN_USER,
    DOMAIN_DETECT_SYSTEM,
    DOMAIN_DETECT_USER,
)
```

### 4.2 Add domain detection keywords

Add after the existing `_STOPWORDS` definition (around line 60):

```python
# Keywords for rule-based ML/DL domain detection (Step 1 of dual detection).
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
}

# Domains that qualify for experiment plan generation.
_EXPERIMENT_ELIGIBLE_DOMAINS = {
    "machine_learning", "deep_learning", "cv", "nlp", "rl",
}
```

### 4.3 Add the rule-based domain detection helper

```python
def _detect_domain_by_rules(topic: str, research_questions: List[str]) -> bool:
    """Return True if rule-based keyword matching suggests an ML/DL domain."""
    combined_text = " ".join([topic] + research_questions).lower()
    hit_count = sum(1 for kw in _ML_DOMAIN_KEYWORDS if kw in combined_text)
    # Require at least 2 keyword hits to reduce false positives.
    return hit_count >= 2
```

### 4.4 Add the LLM-based domain detection helper

```python
def _detect_domain_by_llm(
    topic: str,
    research_questions: List[str],
    cfg: Dict[str, Any],
) -> Dict[str, str]:
    """Use LLM to classify the research domain.

    Returns dict with keys: domain, subfield, task_type.
    """
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.1)
    rq_text = "\n".join(f"- {q}" for q in research_questions)
    prompt = DOMAIN_DETECT_USER.format(
        topic=topic,
        research_questions=rq_text,
    )
    raw = _llm_call(
        DOMAIN_DETECT_SYSTEM, prompt,
        cfg=cfg, model=model, temperature=temperature,
    )
    try:
        result = _parse_json(raw)
    except json.JSONDecodeError:
        result = {"domain": "other", "subfield": "", "task_type": ""}
    return {
        "domain": str(result.get("domain", "other")).strip().lower(),
        "subfield": str(result.get("subfield", "")).strip(),
        "task_type": str(result.get("task_type", "")).strip(),
    }
```

### 4.5 Add experiment plan validation helper

```python
def _validate_experiment_plan(plan: Dict[str, Any]) -> List[str]:
    """Validate experiment plan completeness, return list of issues."""
    issues: List[str] = []
    rq_experiments = plan.get("rq_experiments", [])
    if not rq_experiments:
        issues.append("no_rq_experiments")
        return issues

    for i, exp in enumerate(rq_experiments):
        prefix = f"rq_experiments[{i}]"

        # Check datasets
        datasets = exp.get("datasets", [])
        if not datasets:
            issues.append(f"{prefix}.datasets: missing")
        for j, ds in enumerate(datasets):
            if not ds.get("url"):
                issues.append(f"{prefix}.datasets[{j}].url: missing")
            if not ds.get("name"):
                issues.append(f"{prefix}.datasets[{j}].name: missing")

        # Check environment
        env = exp.get("environment", {})
        if not env.get("python"):
            issues.append(f"{prefix}.environment.python: missing")
        if not env.get("cuda"):
            issues.append(f"{prefix}.environment.cuda: missing")
        if not env.get("pytorch"):
            issues.append(f"{prefix}.environment.pytorch: missing")

        # Check hyperparameters
        hp = exp.get("hyperparameters", {})
        if not hp.get("baseline"):
            issues.append(f"{prefix}.hyperparameters.baseline: missing")
        if not hp.get("search_space"):
            issues.append(f"{prefix}.hyperparameters.search_space: missing")

        # Check run commands
        cmds = exp.get("run_commands", {})
        if not cmds.get("train"):
            issues.append(f"{prefix}.run_commands.train: missing")
        if not cmds.get("eval"):
            issues.append(f"{prefix}.run_commands.eval: missing")

        # Check evidence refs
        refs = exp.get("evidence_refs", [])
        if not refs:
            issues.append(f"{prefix}.evidence_refs: missing")

    return issues
```

### 4.6 Implement the `recommend_experiments` node function

```python
def recommend_experiments(state: ResearchState) -> Dict[str, Any]:
    """Generate experiment recommendations when topic is in ML/DL/CV/NLP/RL domain.

    This node performs two-phase domain detection (rules + LLM), then generates
    a structured experiment plan for each research question.

    Inputs from state:
        - topic
        - research_questions
        - claim_evidence_map
        - analyses
    Outputs:
        - experiment_plan (ExperimentPlan dict, or empty if non-ML domain)
    """
    state = _state_view(state)
    cfg = _get_cfg(state)
    topic = state["topic"]
    research_questions = state.get("research_questions", [])

    # ── Phase 1: Rule-based domain detection ──
    rule_hit = _detect_domain_by_rules(topic, research_questions)

    if not rule_hit:
        logger.info(
            "[recommend_experiments] Rule-based detection: not ML/DL domain, skipping."
        )
        return _ns({
            "experiment_plan": {},
            "status": "Experiment recommendation skipped (non-ML domain by rules)",
        })

    # ── Phase 2: LLM-based domain detection ──
    domain_info = _detect_domain_by_llm(topic, research_questions, cfg)
    domain = domain_info["domain"]
    subfield = domain_info["subfield"]
    task_type = domain_info["task_type"]

    if domain not in _EXPERIMENT_ELIGIBLE_DOMAINS:
        logger.info(
            "[recommend_experiments] LLM domain detection: '%s', not in eligible domains, skipping.",
            domain,
        )
        return _ns({
            "experiment_plan": {},
            "status": f"Experiment recommendation skipped (LLM classified as '{domain}')",
        })

    logger.info(
        "[recommend_experiments] Domain confirmed: %s / %s / %s. Generating experiment plan.",
        domain, subfield, task_type,
    )

    # ── Phase 3: Build context for experiment plan generation ──
    model = cfg.get("llm", {}).get("model", "gpt-4.1-mini")
    temperature = cfg.get("llm", {}).get("temperature", 0.3)

    # Format research questions
    rq_text = "\n".join(f"- {q}" for q in research_questions)

    # Format claim-evidence map
    claim_map = state.get("claim_evidence_map", [])
    claim_map_text = _format_claim_map(claim_map)

    # Format analyses (only top relevant ones with methodology)
    analyses = state.get("analyses", [])
    analyses_parts = []
    for a in analyses[:15]:  # Limit to top 15 to fit context
        source_tag = a.get("source", "unknown")
        part = (
            f"### [{source_tag.upper()}] {a.get('title', 'Unknown')}\n"
            f"UID: {a.get('uid', 'N/A')}\n"
        )
        url = str(a.get("url") or "").strip() or _uid_to_resolvable_url(str(a.get("uid") or ""))
        if url:
            part += f"URL: {url}\n"
        part += (
            f"Summary: {a.get('summary', 'N/A')}\n"
            f"Key findings: {', '.join(a.get('key_findings', []))}\n"
            f"Methodology: {a.get('methodology', 'N/A')}"
        )
        analyses_parts.append(part)
    analyses_text = "\n\n".join(analyses_parts)

    # ── Phase 4: Call LLM to generate experiment plan ──
    prompt = EXPERIMENT_PLAN_USER.format(
        topic=topic,
        domain=domain,
        subfield=subfield,
        task_type=task_type,
        research_questions=rq_text,
        claim_evidence_map=claim_map_text,
        analyses=analyses_text,
    )

    raw = _llm_call(
        EXPERIMENT_PLAN_SYSTEM, prompt,
        cfg=cfg, model=model, temperature=temperature,
    )

    try:
        plan = _parse_json(raw)
    except json.JSONDecodeError:
        logger.warning("[recommend_experiments] Failed to parse experiment plan JSON")
        plan = {
            "domain": domain,
            "subfield": subfield,
            "task_type": task_type,
            "rq_experiments": [],
        }

    # Ensure top-level domain info is present
    plan.setdefault("domain", domain)
    plan.setdefault("subfield", subfield)
    plan.setdefault("task_type", task_type)

    # ── Phase 5: Validate the plan ──
    validation_issues = _validate_experiment_plan(plan)
    if validation_issues:
        logger.warning(
            "[recommend_experiments] Experiment plan has %d validation issues: %s",
            len(validation_issues),
            "; ".join(validation_issues[:5]),
        )

    return _ns({
        "experiment_plan": plan,
        "status": (
            f"Experiment plan generated: domain={domain}, subfield={subfield}, "
            f"{len(plan.get('rq_experiments', []))} experiment groups, "
            f"{len(validation_issues)} validation issues"
        ),
    })
```

---

## 5. Step 4 -- Register Node and Edges

**File**: `src/agent/graph.py`

### 5.1 Import the new node

Update the import block:

```python
from src.agent.nodes import (
    analyze_sources,
    evaluate_progress,
    fetch_sources,
    generate_report,
    index_sources,
    plan_research,
    recommend_experiments,     # <-- ADD
    synthesize,
)
```

### 5.2 Register the node

Inside `build_graph()`, add the node after the `synthesize` node registration:

```python
graph.add_node("recommend_experiments", instrument_node("recommend_experiments", recommend_experiments))
```

### 5.3 Update edges

Replace the edge from `synthesize -> evaluate_progress` with:

```python
# BEFORE:
# graph.add_edge("synthesize", "evaluate_progress")

# AFTER:
graph.add_edge("synthesize", "recommend_experiments")
graph.add_edge("recommend_experiments", "evaluate_progress")
```

### 5.4 Update the docstring

Update the graph topology ASCII art in the module docstring to reflect the new flow:

```
    ┌─────────────────┐
    │  plan_research   │ <──────────────────────────┐
    └────────┬────────┘                              │
             v                                       │
    ┌─────────────────┐                              │
    │  fetch_sources   │  arXiv + S2 + Web           │
    └────────┬────────┘                              │
             v                                       │
    ┌─────────────────┐                              │
    │  index_sources   │  PDFs + web text -> Chroma  │
    └────────┬────────┘                              │
             v                                       │
    ┌──────────────────┐                             │
    │ analyze_sources   │  papers + web pages        │
    └────────┬─────────┘                             │
             v                                       │
    ┌─────────────────┐                              │
    │   synthesize     │                              │
    └────────┬────────┘                              │
             v                                       │
    ┌────────────────────────┐                       │
    │ recommend_experiments   │  ML/DL only           │
    └────────┬───────────────┘                       │
             v                                       │
    ┌──────────────────┐   should_continue=True      │
    │evaluate_progress  │ ──────────────────────────┘
    └────────┬─────────┘
             │ should_continue=False
             v
    ┌─────────────────┐
    │ generate_report  │
    └────────┬────────┘
             v
           [END]
```

---

## 6. Step 5 -- Integrate into Report Generation

**File**: `src/agent/nodes.py`, inside `generate_report()`

### 6.1 Add the experiment blueprint rendering helper

Add the following helper function before `generate_report`:

```python
def _render_experiment_blueprint(plan: Dict[str, Any], language: str = "en") -> str:
    """Render the experiment_plan dict as a Markdown chapter."""
    rq_experiments = plan.get("rq_experiments", [])
    if not rq_experiments:
        return ""

    is_zh = language == "zh"
    header = "## Experimental Blueprint" if not is_zh else "## 实验建议蓝图"
    domain_label = "Domain" if not is_zh else "领域"
    subfield_label = "Subfield" if not is_zh else "子领域"
    task_label = "Task Type" if not is_zh else "任务类型"

    parts: List[str] = [
        header,
        "",
        f"**{domain_label}**: {plan.get('domain', 'N/A')} | "
        f"**{subfield_label}**: {plan.get('subfield', 'N/A')} | "
        f"**{task_label}**: {plan.get('task_type', 'N/A')}",
        "",
    ]

    for i, exp in enumerate(rq_experiments, 1):
        rq = exp.get("research_question", f"RQ {i}")
        parts.append(f"### Experiment {i}: {rq}")
        parts.append("")
        parts.append(f"**Task**: {exp.get('task', 'N/A')}")
        parts.append("")

        # Datasets
        datasets = exp.get("datasets", [])
        if datasets:
            parts.append("#### Datasets")
            parts.append("")
            parts.append("| Name | URL | License | Reason |")
            parts.append("|------|-----|---------|--------|")
            for ds in datasets:
                parts.append(
                    f"| {ds.get('name', 'N/A')} "
                    f"| {ds.get('url', 'N/A')} "
                    f"| {ds.get('license', 'N/A')} "
                    f"| {ds.get('reason', 'N/A')} |"
                )
            parts.append("")

        # Code Framework
        cf = exp.get("code_framework", {})
        if cf:
            parts.append("#### Code Framework")
            parts.append("")
            parts.append(f"- **Stack**: {cf.get('stack', 'N/A')}")
            parts.append(f"- **Starter Repo**: {cf.get('starter_repo', 'N/A')}")
            if cf.get("notes"):
                parts.append(f"- **Notes**: {cf['notes']}")
            parts.append("")

        # Environment
        env = exp.get("environment", {})
        if env:
            parts.append("#### Environment")
            parts.append("")
            parts.append(f"- **Python**: {env.get('python', 'N/A')}")
            parts.append(f"- **CUDA**: {env.get('cuda', 'N/A')}")
            parts.append(f"- **PyTorch**: {env.get('pytorch', 'N/A')}")
            parts.append(f"- **GPU**: {env.get('gpu', 'N/A')}")
            deps = env.get("deps", [])
            if deps:
                parts.append(f"- **Dependencies**: `{', '.join(deps)}`")
            parts.append("")

        # Hyperparameters
        hp = exp.get("hyperparameters", {})
        if hp:
            parts.append("#### Hyperparameters")
            parts.append("")
            baseline = hp.get("baseline", {})
            if baseline:
                parts.append("**Baseline**:")
                parts.append("```json")
                parts.append(json.dumps(baseline, indent=2, ensure_ascii=False))
                parts.append("```")
            search_space = hp.get("search_space", {})
            if search_space:
                parts.append("**Search Space**:")
                parts.append("```json")
                parts.append(json.dumps(search_space, indent=2, ensure_ascii=False))
                parts.append("```")
            parts.append("")

        # Run Commands
        cmds = exp.get("run_commands", {})
        if cmds:
            parts.append("#### Run Commands")
            parts.append("")
            if cmds.get("train"):
                parts.append("**Train**:")
                parts.append(f"```bash\n{cmds['train']}\n```")
            if cmds.get("eval"):
                parts.append("**Eval**:")
                parts.append(f"```bash\n{cmds['eval']}\n```")
            parts.append("")

        # Evaluation
        ev = exp.get("evaluation", {})
        if ev:
            parts.append("#### Evaluation Protocol")
            parts.append("")
            metrics = ev.get("metrics", [])
            if metrics:
                parts.append(f"- **Metrics**: {', '.join(metrics)}")
            if ev.get("protocol"):
                parts.append(f"- **Protocol**: {ev['protocol']}")
            parts.append("")

        # Evidence References
        refs = exp.get("evidence_refs", [])
        if refs:
            parts.append("#### Evidence References")
            parts.append("")
            for ref in refs:
                uid = ref.get("uid", "")
                url = ref.get("url", "")
                if url:
                    parts.append(f"- [{uid}]({url})")
                else:
                    parts.append(f"- {uid}")
            parts.append("")

        parts.append("---")
        parts.append("")

    return "\n".join(parts)
```

### 6.2 Modify `generate_report()` to inject the Experimental Blueprint

Inside `generate_report()`, after the report is generated and cleaned (after `_clean_reference_section`) but before the critic is run, insert the experiment blueprint.

Find the line:

```python
report = _clean_reference_section(report, max_refs=max_report_sources)
```

Add the following **after** that line (the first occurrence, before the critic call):

```python
    # Inject Experimental Blueprint chapter if experiment_plan is available.
    experiment_plan = state.get("experiment_plan", {})
    if experiment_plan and experiment_plan.get("rq_experiments"):
        blueprint_md = _render_experiment_blueprint(experiment_plan, language=language)
        if blueprint_md:
            # Insert before References section if present, otherwise append.
            ref_match = re.search(
                r"^(#{1,6}\s*(?:\d+\.?\s*)?(?:References|参考文献))\s*$",
                report,
                flags=re.MULTILINE | re.IGNORECASE,
            )
            if ref_match:
                insert_pos = ref_match.start()
                report = (
                    report[:insert_pos].rstrip()
                    + "\n\n"
                    + blueprint_md
                    + "\n\n"
                    + report[insert_pos:]
                )
            else:
                report = report.rstrip() + "\n\n" + blueprint_md + "\n"
```

---

## 7. Step 6 -- Quality Gate Enhancement

**File**: `src/agent/nodes.py`

### 7.1 Add experiment plan checks to `_critic_report`

Extend the `_critic_report` function signature to accept the experiment plan, and add validation checks. Modify the function signature:

```python
def _critic_report(
    *,
    topic: str,
    report: str,
    research_questions: List[str],
    claim_map: List[Dict[str, Any]],
    max_refs: int,
    max_sections: int,
    block_terms: List[str],
    experiment_plan: Dict[str, Any] | None = None,  # <-- ADD
) -> Dict[str, Any]:
```

At the end of `_critic_report`, before the `return`, add experiment plan quality checks:

```python
    # Validate experiment plan quality (if present).
    if experiment_plan and experiment_plan.get("rq_experiments"):
        exp_issues = _validate_experiment_plan(experiment_plan)
        for issue in exp_issues:
            issues.append(f"experiment_plan:{issue}")
```

### 7.2 Update all call sites of `_critic_report`

In `generate_report()`, pass the `experiment_plan` to both calls of `_critic_report`:

```python
    critic = _critic_report(
        topic=topic,
        report=report,
        research_questions=state.get("research_questions", []),
        claim_map=claim_map,
        max_refs=max_report_sources,
        max_sections=int(budget.get("max_sections", DEFAULT_MAX_SECTIONS)),
        block_terms=block_terms,
        experiment_plan=experiment_plan,    # <-- ADD
    )
```

(Apply this change to **both** invocations of `_critic_report` inside `generate_report()`.)

### 7.3 Update `_compute_acceptance_metrics`

Add experiment plan metrics. Modify the function signature:

```python
def _compute_acceptance_metrics(
    *,
    evidence_audit_log: List[Dict[str, Any]],
    report_critic: Dict[str, Any],
    experiment_plan: Dict[str, Any] | None = None,  # <-- ADD
) -> Dict[str, Any]:
```

Add to the returned dict:

```python
    # Experiment plan metrics
    exp_plan = experiment_plan or {}
    exp_rqs = exp_plan.get("rq_experiments", [])
    exp_validation_issues = _validate_experiment_plan(exp_plan) if exp_rqs else []
    result["experiment_plan_present"] = bool(exp_rqs)
    result["experiment_plan_rq_count"] = len(exp_rqs)
    result["experiment_plan_issues"] = exp_validation_issues
    result["experiment_plan_valid"] = len(exp_validation_issues) == 0
```

Update the call site in `generate_report()`:

```python
    acceptance_metrics = _compute_acceptance_metrics(
        evidence_audit_log=state.get("evidence_audit_log", []),
        report_critic=critic,
        experiment_plan=experiment_plan,    # <-- ADD
    )
```

---

## 8. Step 7 -- State Access Layer Update

**File**: `src/agent/core/state_access.py`

Add `experiment_plan` to the `_FIELD_NS_MAP`:

```python
_FIELD_NS_MAP = {
    # ... existing entries ...
    "experiment_plan": "research",          # <-- ADD
}
```

This ensures that the namespaced state system correctly reads and writes the field.

---

## 9. Step 8 -- Configuration Support

**File**: `src/agent/core/config.py`

### 9.1 Add default constants

```python
DEFAULT_EXPERIMENT_PLAN_ENABLED = True
DEFAULT_EXPERIMENT_MAX_PER_RQ = 2
```

### 9.2 Add configuration normalization

Inside `normalize_and_validate_config`, add after the `topic_filter_cfg` section:

```python
    experiment_cfg = agent_cfg.setdefault("experiment_plan", {})
    experiment_cfg["enabled"] = _to_bool(
        experiment_cfg.get("enabled"), DEFAULT_EXPERIMENT_PLAN_ENABLED
    )
    experiment_cfg["max_per_rq"] = int(
        experiment_cfg.get("max_per_rq", DEFAULT_EXPERIMENT_MAX_PER_RQ)
    )
```

### 9.3 Usage in the node

In `recommend_experiments()`, check the config before proceeding:

```python
    # Check if experiment plan is enabled in config.
    exp_cfg = cfg.get("agent", {}).get("experiment_plan", {})
    if not exp_cfg.get("enabled", True):
        return _ns({
            "experiment_plan": {},
            "status": "Experiment recommendation disabled by config",
        })
```

### 9.4 YAML config example

Users can control the feature in their `configs/*.yaml`:

```yaml
agent:
  experiment_plan:
    enabled: true        # Set to false to disable experiment suggestions
    max_per_rq: 2        # Max experiment groups per research question
```

---

## 10. Output Schema Reference

### Complete `experiment_plan` JSON Schema

```json
{
  "domain": "deep_learning",
  "subfield": "retrieval-augmented generation",
  "task_type": "retrieval-augmented qa",
  "rq_experiments": [
    {
      "research_question": "How does chunk size affect RAG retrieval accuracy?",
      "task": "retrieval-augmented qa",
      "datasets": [
        {
          "name": "HotpotQA",
          "url": "https://hotpotqa.github.io/",
          "license": "CC BY-SA 4.0",
          "reason": "Multi-hop QA requiring evidence retrieval from multiple documents"
        },
        {
          "name": "Natural Questions",
          "url": "https://ai.google.com/research/NaturalQuestions",
          "license": "CC BY-SA 3.0",
          "reason": "Large-scale QA benchmark with real Google search queries"
        }
      ],
      "code_framework": {
        "stack": "PyTorch + HuggingFace Transformers + LangChain",
        "starter_repo": "https://github.com/langchain-ai/langchain",
        "notes": "Use RetrievalQA chain with configurable chunk_size in text splitter"
      },
      "environment": {
        "python": "3.10",
        "cuda": "12.1",
        "pytorch": "2.3",
        "gpu": "1x A100 40GB",
        "deps": [
          "transformers==4.40.0",
          "datasets==2.19.0",
          "langchain==0.1.16",
          "chromadb==0.4.24",
          "accelerate==0.29.3"
        ]
      },
      "hyperparameters": {
        "baseline": {
          "lr": 2e-5,
          "batch_size": 16,
          "epochs": 3,
          "seed": [42, 43, 44]
        },
        "search_space": {
          "lr": [1e-5, 2e-5, 5e-5],
          "warmup_ratio": [0.03, 0.1]
        }
      },
      "run_commands": {
        "train": "python train.py --model_name facebook/dpr-ctx_encoder-single-nq-base --dataset hotpotqa --chunk_size 512 --lr 2e-5 --epochs 3 --batch_size 16 --seed 42",
        "eval": "python eval.py --model_name facebook/dpr-ctx_encoder-single-nq-base --dataset hotpotqa --chunk_size 512 --metrics em,f1 --seed 42"
      },
      "evaluation": {
        "metrics": ["EM", "F1", "Retrieval Recall@10", "Latency (ms/query)"],
        "protocol": "3 seeds + paired bootstrap test (p<0.05)"
      },
      "evidence_refs": [
        {
          "uid": "arxiv:2005.11401",
          "url": "https://arxiv.org/abs/2005.11401"
        },
        {
          "uid": "doi:10.18653/v1/2020.emnlp-main.550",
          "url": "https://doi.org/10.18653/v1/2020.emnlp-main.550"
        }
      ]
    }
  ]
}
```

### Quality Gate Mandatory Fields Summary

| Check | Required Field | Description |
|-------|---------------|-------------|
| Dataset URL | `datasets[*].url` | Every dataset must have a resolvable URL |
| Python version | `environment.python` | Python version must be specified |
| CUDA version | `environment.cuda` | CUDA version must be specified |
| PyTorch version | `environment.pytorch` | PyTorch version must be specified |
| Baseline HP | `hyperparameters.baseline` | Concrete baseline hyperparameters |
| Search space | `hyperparameters.search_space` | Hyperparameter search range |
| Train command | `run_commands.train` | Executable training command |
| Eval command | `run_commands.eval` | Executable evaluation command |
| Evidence refs | `evidence_refs` | Traceability to source papers |

---

## 11. Testing Strategy

### 11.1 Unit Tests

Create `tests/test_recommend_experiments.py`:

```python
"""Tests for the recommend_experiments node and supporting functions."""
import json
import pytest
from unittest.mock import patch, MagicMock

from src.agent.nodes import (
    _detect_domain_by_rules,
    _validate_experiment_plan,
    recommend_experiments,
    _render_experiment_blueprint,
)


class TestDomainDetection:
    def test_ml_topic_detected(self):
        assert _detect_domain_by_rules(
            "Fine-tuning transformer models for text classification",
            ["How does learning rate affect BERT fine-tuning?"],
        ) is True

    def test_non_ml_topic_not_detected(self):
        assert _detect_domain_by_rules(
            "History of the Roman Empire",
            ["What caused the fall of Rome?"],
        ) is False

    def test_borderline_single_keyword_not_enough(self):
        assert _detect_domain_by_rules(
            "benchmark comparison of databases",
            ["Which database is fastest?"],
        ) is False  # Only 1 keyword hit, need >= 2


class TestExperimentPlanValidation:
    def test_empty_plan(self):
        issues = _validate_experiment_plan({})
        assert "no_rq_experiments" in issues

    def test_valid_plan(self):
        plan = {
            "rq_experiments": [{
                "datasets": [{"name": "X", "url": "https://x.com"}],
                "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3"},
                "hyperparameters": {
                    "baseline": {"lr": 2e-5},
                    "search_space": {"lr": [1e-5, 5e-5]},
                },
                "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                "evidence_refs": [{"uid": "arxiv:1234"}],
            }]
        }
        issues = _validate_experiment_plan(plan)
        assert issues == []

    def test_missing_dataset_url(self):
        plan = {
            "rq_experiments": [{
                "datasets": [{"name": "X"}],
                "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3"},
                "hyperparameters": {
                    "baseline": {"lr": 2e-5},
                    "search_space": {"lr": [1e-5]},
                },
                "run_commands": {"train": "cmd", "eval": "cmd"},
                "evidence_refs": [{"uid": "arxiv:1234"}],
            }]
        }
        issues = _validate_experiment_plan(plan)
        assert any("url" in i for i in issues)


class TestRecommendExperimentsNode:
    @patch("src.agent.nodes._llm_call")
    def test_non_ml_topic_skips(self, mock_llm):
        state = {
            "topic": "History of medieval architecture",
            "research_questions": ["What styles emerged in 12th century?"],
            "_cfg": {"llm": {"model": "gpt-4.1-mini"}},
            "planning": {"research_questions": ["What styles emerged?"]},
            "research": {"analyses": []},
            "evidence": {"claim_evidence_map": []},
        }
        result = recommend_experiments(state)
        # LLM should not be called for experiment generation
        # (may be called 0 or 1 times for domain detection)
        assert not result.get("experiment_plan") or not result["experiment_plan"].get("rq_experiments")

    @patch("src.agent.nodes._llm_call")
    def test_ml_topic_generates_plan(self, mock_llm):
        mock_plan = {
            "domain": "deep_learning",
            "subfield": "NLP",
            "task_type": "text classification",
            "rq_experiments": [{
                "research_question": "test",
                "task": "classification",
                "datasets": [{"name": "SST-2", "url": "https://...", "license": "MIT", "reason": "standard benchmark"}],
                "code_framework": {"stack": "PyTorch", "starter_repo": "https://...", "notes": ""},
                "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3", "gpu": "A100", "deps": []},
                "hyperparameters": {"baseline": {"lr": 2e-5}, "search_space": {"lr": [1e-5, 5e-5]}},
                "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                "evaluation": {"metrics": ["accuracy"], "protocol": "3 seeds"},
                "evidence_refs": [{"uid": "arxiv:1234", "url": "https://arxiv.org/abs/1234"}],
            }],
        }
        # First call: domain detection. Second call: experiment plan generation.
        mock_llm.side_effect = [
            json.dumps({"domain": "deep_learning", "subfield": "NLP", "task_type": "text classification"}),
            json.dumps(mock_plan),
        ]
        state = {
            "topic": "Fine-tuning BERT for text classification using transformer models",
            "research_questions": ["How does learning rate affect BERT fine-tuning?"],
            "_cfg": {"llm": {"model": "gpt-4.1-mini", "temperature": 0.3}},
            "planning": {"research_questions": ["How does learning rate affect BERT?"]},
            "research": {"analyses": []},
            "evidence": {"claim_evidence_map": []},
        }
        result = recommend_experiments(state)
        plan = result.get("experiment_plan") or result.get("research", {}).get("experiment_plan", {})
        assert plan.get("domain") == "deep_learning"


class TestRenderExperimentBlueprint:
    def test_empty_plan_returns_empty(self):
        assert _render_experiment_blueprint({}) == ""

    def test_renders_markdown(self):
        plan = {
            "domain": "deep_learning",
            "subfield": "NLP",
            "task_type": "classification",
            "rq_experiments": [{
                "research_question": "Test RQ",
                "task": "classification",
                "datasets": [{"name": "SST-2", "url": "https://example.com", "license": "MIT", "reason": "test"}],
                "code_framework": {"stack": "PyTorch", "starter_repo": "https://github.com/test", "notes": ""},
                "environment": {"python": "3.10", "cuda": "12.1", "pytorch": "2.3", "gpu": "A100", "deps": ["torch"]},
                "hyperparameters": {"baseline": {"lr": 2e-5}, "search_space": {"lr": [1e-5]}},
                "run_commands": {"train": "python train.py", "eval": "python eval.py"},
                "evaluation": {"metrics": ["accuracy"], "protocol": "3 seeds"},
                "evidence_refs": [{"uid": "arxiv:1234", "url": "https://arxiv.org/abs/1234"}],
            }],
        }
        md = _render_experiment_blueprint(plan)
        assert "## Experimental Blueprint" in md
        assert "SST-2" in md
        assert "python train.py" in md
```

### 11.2 Integration Test

Create a simple integration test that runs the full graph on an ML topic and verifies the experiment plan is present:

```python
# tests/test_experiment_integration.py
"""Integration test: verify experiment plan appears in final state for ML topics."""
import pytest
from unittest.mock import patch

# This test requires mocking all LLM calls and search dispatches.
# See existing integration test patterns in the codebase.
```

### 11.3 Manual Smoke Test

```bash
# Run with an ML topic
python -m src.agent --topic "Fine-tuning large language models for domain-specific tasks" \
    --config configs/default.yaml

# Verify the output report contains "## Experimental Blueprint"
grep -c "Experimental Blueprint" output/report.md

# Run with a non-ML topic (should have no blueprint)
python -m src.agent --topic "Impact of social media on political polarization" \
    --config configs/default.yaml
```

---

## 12. Checklist

Use this checklist to track implementation progress:

### Schema & Types
- [ ] Add `DatasetInfo`, `CodeFramework`, `EnvironmentSpec`, `Hyperparameters`, `RunCommands`, `EvaluationProtocol`, `EvidenceRef`, `RQExperiment`, `ExperimentPlan` TypedDicts to `schemas.py`
- [ ] Add `experiment_plan` field to `ResearchNamespace`
- [ ] Add `experiment_plan` legacy flat field to `ResearchState`
- [ ] Update `state.py` re-exports

### State Access
- [ ] Add `"experiment_plan": "research"` to `_FIELD_NS_MAP` in `state_access.py`

### Configuration
- [ ] Add `DEFAULT_EXPERIMENT_PLAN_ENABLED` and `DEFAULT_EXPERIMENT_MAX_PER_RQ` to `config.py`
- [ ] Add normalization logic for `experiment_plan` config section in `normalize_and_validate_config`

### Prompts
- [ ] Add `EXPERIMENT_PLAN_SYSTEM` to `prompts.py`
- [ ] Add `EXPERIMENT_PLAN_USER` to `prompts.py`
- [ ] Add `DOMAIN_DETECT_SYSTEM` to `prompts.py`
- [ ] Add `DOMAIN_DETECT_USER` to `prompts.py`

### Node Implementation
- [ ] Add `_ML_DOMAIN_KEYWORDS` set to `nodes.py`
- [ ] Add `_EXPERIMENT_ELIGIBLE_DOMAINS` set to `nodes.py`
- [ ] Implement `_detect_domain_by_rules()` in `nodes.py`
- [ ] Implement `_detect_domain_by_llm()` in `nodes.py`
- [ ] Implement `_validate_experiment_plan()` in `nodes.py`
- [ ] Implement `recommend_experiments()` node in `nodes.py`
- [ ] Implement `_render_experiment_blueprint()` in `nodes.py`

### Graph Wiring
- [ ] Import `recommend_experiments` in `graph.py`
- [ ] Register `recommend_experiments` node in `build_graph()`
- [ ] Update edges: `synthesize -> recommend_experiments -> evaluate_progress`
- [ ] Update docstring ASCII art

### Report Integration
- [ ] Insert blueprint Markdown before References in `generate_report()`

### Quality Gates
- [ ] Add `experiment_plan` parameter to `_critic_report()`
- [ ] Add experiment plan validation checks in `_critic_report()`
- [ ] Update both `_critic_report()` call sites in `generate_report()`
- [ ] Add `experiment_plan` parameter to `_compute_acceptance_metrics()`
- [ ] Add experiment plan metrics to acceptance output
- [ ] Update `_compute_acceptance_metrics()` call site

### Testing
- [ ] Unit tests for `_detect_domain_by_rules()`
- [ ] Unit tests for `_validate_experiment_plan()`
- [ ] Unit tests for `recommend_experiments()` node (mock LLM)
- [ ] Unit tests for `_render_experiment_blueprint()`
- [ ] Integration smoke test with ML topic
- [ ] Integration smoke test with non-ML topic (no-op)

### Documentation
- [ ] Update `README.md` to mention the Experimental Blueprint feature
- [ ] Add YAML config example to `configs/` directory

---

## Appendix: File Change Summary

| File | Changes |
|------|---------|
| `src/agent/core/schemas.py` | Add 10 new TypedDicts, add `experiment_plan` to namespaces |
| `src/agent/core/state_access.py` | Add `experiment_plan` to `_FIELD_NS_MAP` |
| `src/agent/core/config.py` | Add 2 default constants, add config normalization |
| `src/agent/prompts.py` | Add 4 new prompt constants |
| `src/agent/nodes.py` | Add 6 new functions, modify `generate_report`, `_critic_report`, `_compute_acceptance_metrics` |
| `src/agent/graph.py` | Import new node, register node, update edges, update docstring |
| `src/agent/state.py` | Re-export new types |
| `tests/test_recommend_experiments.py` | New test file |
