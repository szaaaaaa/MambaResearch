# 多模态检索质量问题分析与修复方案

> 版本: 1.0
> 日期: 2026-03-06
> 状态: 待开发

---

## 1. 问题总览

当前多模态检索管道存在 4 个层次的质量问题：

| 编号 | 层次 | 问题 | 优先级 | 涉及文件 |
|------|------|------|--------|----------|
| Q1 | 抽取层 | caption/context 边界过松，吞入正文大段文本 | P0 | `figure_extractor.py` |
| Q2 | 抽取层 | LaTeX 数学清洗破坏公式结构 | P0 | `latex_loader.py` |
| Q3 | 组装层 | 同一 figure 重复入库或重复召回 | P0 | `figure_captioner.py`, `retriever.py` |
| Q4 | 排序层 | 检索不理解 figure/公式查询意图 | P1 | `retriever.py` |

---

## 2. Q1: caption/context 边界过松

### 2.1 问题根因

`figure_extractor.py:207-214` 的 `_extract_captions()` 使用如下正则：

```python
r"(?is)(?:^|\n)\s*(?:Figure|Fig\.)\s*(\d+)\s*[:.]\s*(.+?)(?=\n\s*\n|\n\s*(?:Figure|Fig\.|Table)\s*\d+\s*[:.]|$)"
```

终止条件为 `\n\n`（空行）、下一个 Figure/Table 标记、或文末 `$`。PDF 提取的文本中空行不规范（PyMuPDF 的换行是版面换行而非段落换行），导致 caption 贪婪匹配到整个 section body。

`_extract_reference_paragraphs()` (L217-230) 按 `\n\s*\n` 切段后取整段，无长度限制，对长段落会产生过大的 context。

### 2.2 修复方案

#### 2.2.1 caption 抽取改为局部窗口 + 硬限制

修改 `_extract_captions()`：

```python
_MAX_CAPTION_CHARS = 500
_MAX_CAPTION_SENTENCES = 3

def _extract_captions(full_text: str) -> dict[int, str]:
    pattern = re.compile(
        r"(?im)(?:^|\n)\s*(?:Figure|Fig\.)\s*(\d+)\s*[:.]\s*"
    )
    out: dict[int, str] = {}
    for match in pattern.finditer(full_text):
        fig_num = int(match.group(1))
        start = match.end()
        # 截取固定窗口
        window = full_text[start:start + _MAX_CAPTION_CHARS]
        # 在窗口内寻找终止点
        caption = _truncate_caption(window)
        if caption:
            out[fig_num] = caption
    return out


def _truncate_caption(window: str) -> str:
    """在窗口内截取 caption，遇到以下条件终止：

    1. 空行 (\\n\\n)
    2. 下一个 Figure/Table/Section 标记
    3. 超过 _MAX_CAPTION_SENTENCES 个句子
    """
    # 先按硬终止符截断
    terminators = [
        r"\n\s*\n",
        r"\n\s*(?:Figure|Fig\.|Table)\s*\d+\s*[:.)]",
        r"\n\s*(?:\\section|##\s)",
        r"\n\s*[A-Z][A-Z ]{5,}\n",  # 全大写 section title
    ]
    end = len(window)
    for term in terminators:
        m = re.search(term, window)
        if m and m.start() < end:
            end = m.start()
    text = window[:end].strip()

    # 按句子数限制
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) > _MAX_CAPTION_SENTENCES:
        text = " ".join(sentences[:_MAX_CAPTION_SENTENCES])

    return re.sub(r"\s+", " ", text).strip()
```

#### 2.2.2 context 改为引用句 + 邻域，加字符数限制

修改 `_extract_reference_paragraphs()`：

```python
_MAX_CONTEXT_CHARS = 800

def _extract_reference_paragraphs(
    full_text: str,
    patterns: List[str],
) -> List[str]:
    """提取引用该图的句子及其前后各一句。

    改进点：
    - 按句子切分而非按段落
    - 每次命中只取 [前一句, 命中句, 后一句]
    - 总字符数不超过 _MAX_CONTEXT_CHARS
    """
    sentences = re.split(r"(?<=[.!?])\s+", full_text)
    out: List[str] = []
    seen: set[str] = set()
    total_chars = 0

    for i, sentence in enumerate(sentences):
        if not any(re.search(p, sentence) for p in patterns):
            continue
        # 取前后各一句
        window = []
        if i > 0:
            window.append(sentences[i - 1])
        window.append(sentence)
        if i + 1 < len(sentences):
            window.append(sentences[i + 1])
        snippet = " ".join(window).strip()
        snippet = re.sub(r"\s+", " ", snippet)
        key = snippet.lower()
        if key in seen:
            continue
        if total_chars + len(snippet) > _MAX_CONTEXT_CHARS:
            break
        seen.add(key)
        out.append(snippet)
        total_chars += len(snippet)

    return out
```

#### 2.2.3 PDF 路径做 page-local 约束

当 `ExtractedFigure` 有 `page_number` 时，caption/context 搜索应优先在同页附近文本中进行。

修改 `build_figure_contexts_from_text()`，增加可选参数 `page_texts: dict[int, str]`（按页切分的文本）。当有按页文本时，先在同页文本中搜索 caption，搜不到再全局回退。

### 2.3 涉及文件

| 文件 | 改动 |
|------|------|
| `src/ingest/figure_extractor.py` | 重写 `_extract_captions()`、`_extract_reference_paragraphs()`，修改 `build_figure_contexts_from_text()` |

### 2.4 测试验证

- `_extract_captions()` 对包含 "Figure 1: Model architecture.\nEncoder and Decoder Stacks\n\nThe encoder..." 的文本，caption 应只包含 "Model architecture." 而非后续正文
- caption 长度 P95 < 500 字符
- context 总字符数 <= 800

---

## 3. Q2: LaTeX 数学清洗破坏公式

### 3.1 问题根因

`latex_loader.py` 中有两个函数会破坏数学内容：

**`_latex_to_markdown()` (L271-301)**

第 297 行的通用命令剥离规则：

```python
out = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", "", out)
```

这条规则在 display math 环境 (`$$...$$`) 已经处理之后执行，但行内公式 `$...$` 中的命令（如 `\sqrt`, `\frac`）也会被这条规则命中并删除。

第 299 行的花括号剥离：

```python
out = re.sub(r"\{([^{}]+)\}", r"\1", out)
```

会把 `\sqrt{d_k}` 中的 `{d_k}` 变成 `d_k`，与命令剥离配合后 `\sqrt{d_k}` 变成仅剩 `d_k`。

**`_latex_inline_to_text()` (L333-336)**

```python
out = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{([^}]*)\}", r"\1", text)
out = out.replace("{", "").replace("}", "")
```

直接把所有带参数的命令替换为参数内容。`\frac{a}{b}` 变成 `a`（只保留第一个参数），`\sqrt{x}` 变成 `x`。

### 3.2 修复方案

核心原则：**数学 span 保留 LaTeX 原文，非数学部分正常清洗。**

#### 3.2.1 先保护行内数学，再清洗正文

修改 `_latex_to_markdown()`：

```python
def _latex_to_markdown(text: str) -> str:
    out = text

    # 1. 保护行内数学: 用占位符替换 $...$ 内容
    math_spans: List[str] = []
    def _protect_inline_math(m: re.Match) -> str:
        math_spans.append(m.group(0))
        return f"\x00MATH{len(math_spans) - 1}\x00"
    out = re.sub(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", _protect_inline_math, out)

    # 2. 处理 display math 环境 → $$...$$（保留内部 LaTeX 原文）
    for env in _DISPLAY_MATH_ENVS:
        out = re.sub(
            rf"\\begin\{{{re.escape(env)}\}}(.*?)\\end\{{{re.escape(env)}\}}",
            lambda m: "\n$$\n" + _normalize_display_math(m.group(1)) + "\n$$\n",
            out,
            flags=re.DOTALL,
        )

    # 3. 保护 display math 占位
    display_spans: List[str] = []
    def _protect_display_math(m: re.Match) -> str:
        display_spans.append(m.group(0))
        return f"\x00DMATH{len(display_spans) - 1}\x00"
    out = re.sub(r"\$\$\n.*?\n\$\$", _protect_display_math, out, flags=re.DOTALL)

    # 4. 正文清洗（不会碰数学占位符）
    out = re.sub(r"\\section\*?\{([^}]+)\}", lambda m: f"\n## {m.group(1).strip()}\n", out)
    out = re.sub(r"\\subsection\*?\{([^}]+)\}", lambda m: f"\n### {m.group(1).strip()}\n", out)
    out = re.sub(r"\\subsubsection\*?\{([^}]+)\}", lambda m: f"\n#### {m.group(1).strip()}\n", out)
    out = re.sub(r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}",
                 lambda m: "\n" + _table_env_to_markdown(m.group(1)) + "\n", out, flags=re.DOTALL)
    out = re.sub(r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", "", out, flags=re.DOTALL)
    out = re.sub(r"\\cite[t|p]?\{([^}]+)\}", lambda m: "[" + m.group(1).strip() + "]", out)
    out = re.sub(r"\\(?:label|ref|cref|autoref)\{([^}]+)\}", lambda m: m.group(1), out)
    out = re.sub(r"\\(?:usepackage|documentclass)(?:\[[^\]]*\])?\{[^}]+\}", "", out)
    out = re.sub(r"\\begin\{abstract\}|\s*\\end\{abstract\}", "", out)
    out = re.sub(r"\\item\s+", "- ", out)
    out = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", "", out)  # 只影响正文区域
    out = out.replace("~", " ")
    out = re.sub(r"\{([^{}]+)\}", r"\1", out)

    # 5. 恢复数学占位符
    for i, span in enumerate(display_spans):
        out = out.replace(f"\x00DMATH{i}\x00", span)
    for i, span in enumerate(math_spans):
        out = out.replace(f"\x00MATH{i}\x00", span)

    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
```

#### 3.2.2 修改 `_normalize_display_math()` 保留关键命令

当前实现：

```python
def _normalize_display_math(content: str) -> str:
    out = content.strip()
    out = out.replace("&", " ")
    out = out.replace("\\\\", "\n")
    return re.sub(r"\n{3,}", "\n\n", out).strip()
```

问题：`out.replace("&", " ")` 会破坏 `align` 环境中 `&=` 这类对齐符号。改为只去掉独立的 `&`：

```python
def _normalize_display_math(content: str) -> str:
    out = content.strip()
    out = re.sub(r"\s*&\s*", " ", out)  # 去掉对齐用的 &，保留为空格
    out = out.replace("\\\\", "\n")
    out = re.sub(r"\\(?:nonumber|notag)\b", "", out)  # 去掉编号控制
    return re.sub(r"\n{3,}", "\n\n", out).strip()
```

#### 3.2.3 修改 `_latex_inline_to_text()` 保留数学

当前的 `_latex_inline_to_text()` 用于 caption 和 context 的清洗。对数学命令应保留原文：

```python
# 需要保留的数学命令（保留其完整形式包括参数）
_MATH_COMMANDS = {
    "sqrt", "frac", "sum", "prod", "int", "partial",
    "cdot", "times", "div", "pm", "mp", "leq", "geq",
    "alpha", "beta", "gamma", "delta", "epsilon",
    "theta", "lambda", "mu", "sigma", "omega", "pi",
    "log", "exp", "sin", "cos", "tan", "max", "min",
    "inf", "sup", "lim", "mathbb", "mathcal", "mathbf",
    "text", "mathrm", "operatorname",
}

def _latex_inline_to_text(text: str) -> str:
    # 保护 $...$ 行内数学：不做任何清洗
    math_spans: List[str] = []
    def _protect(m: re.Match) -> str:
        math_spans.append(m.group(0))
        return f"\x00M{len(math_spans) - 1}\x00"
    out = re.sub(r"\$[^$]+\$", _protect, text)

    # 对非数学部分：剥离非数学命令，保留数学命令
    def _replace_cmd(m: re.Match) -> str:
        cmd = m.group(1)
        if cmd in _MATH_COMMANDS:
            return m.group(0)  # 保留整个命令
        return m.group(2) if m.group(2) else ""
    out = re.sub(r"\\([A-Za-z]+)\*?(?:\[[^\]]*\])?\{([^}]*)\}", _replace_cmd, out)
    out = re.sub(r"\\([A-Za-z]+)\*?(?:\[[^\]]*\])?", lambda m: m.group(0) if m.group(1) in _MATH_COMMANDS else "", out)

    # 恢复数学 span
    for i, span in enumerate(math_spans):
        out = out.replace(f"\x00M{i}\x00", span)

    out = re.sub(r"\s+", " ", out)
    return out.strip()
```

### 3.3 涉及文件

| 文件 | 改动 |
|------|------|
| `src/ingest/latex_loader.py` | 重写 `_latex_to_markdown()`、`_normalize_display_math()`、`_latex_inline_to_text()` |

### 3.4 测试验证

针对 Attention Is All You Need (1706.03762) 的关键公式：

| LaTeX 原文 | 期望输出 | 当前错误输出 |
|-----------|---------|-------------|
| `$\sqrt{d_k}$` | `$\sqrt{d_k}$` | `d_k` |
| `\text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V` | `$\text{softmax}(\frac{QK^T}{\sqrt{d_k}})V$` | `softmax(QK^Td_k)V` |
| `PE_{(pos,2i)} = \sin(pos/10000^{2i/d_{model}})` | `$PE_{(pos,2i)} = \sin(pos/10000^{2i/d_{model}})$` | `PE(pos,2i) = sin(pos/100002i/dmodel)` |

---

## 4. Q3: 重复 figure 命中

### 4.1 问题根因

**入库前重复** — `figure_captioner.py:135-177` 的 `process_figures()` 遍历 `figure_contexts` 列表直接生成 `FigureChunkData`，没有按 `figure_id` 去重。如果上游 `build_figure_contexts_from_latex()` 或 `build_figure_contexts_from_text()` 对同一张图产生了多条 FigureContext（例如 LaTeX 中同一个 label 被 `\begin{figure}` 包裹多次），就会生成重复 chunk。

**检索后重复** — `retriever.py` 的 `_reciprocal_rank_fusion()` 按 chunk `id` 去重（如 `doc_id:chunk_000015`），但同一张图如果有两个不同 chunk_id 的记录，RRF 不会合并它们。rerank 之后也没有 figure-level collapse，导致同一张图占据 top-k 中多个位置。

### 4.2 修复方案

#### 4.2.1 入库前去重

在 `figure_captioner.py` 的 `process_figures()` 中，在遍历前先按 `figure_id` 去重：

```python
def process_figures(
    *,
    figure_contexts: List[FigureContext],
    paper_title: str,
    vlm_model: str = "gemini-2.5-flash",
    temperature: float = 0.1,
    validation_min_entity_match: float = 0.5,
) -> List[FigureChunkData]:
    # --- 按 figure_id 去重，保留第一条 ---
    seen_ids: set[str] = set()
    deduped: List[FigureContext] = []
    for figure in figure_contexts:
        if figure.figure_id in seen_ids:
            continue
        seen_ids.add(figure.figure_id)
        deduped.append(figure)

    out: List[FigureChunkData] = []
    for figure in deduped:
        # ... 现有 VLM 调用逻辑不变 ...
```

同时在 `figure_data_to_chunks()` 中增加 content hash 兜底去重：

```python
def figure_data_to_chunks(
    figures: List[FigureChunkData],
    doc_id: str,
    text_chunk_count: int,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    next_idx = int(text_chunk_count)
    seen_content: set[str] = set()
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
        text = "\n".join(lines)
        content_key = text.lower().strip()
        if content_key in seen_content:
            continue
        seen_content.add(content_key)
        chunks.append(Chunk(
            chunk_id=f"chunk_{next_idx:06d}",
            text=text,
            start_char=-1,
            end_char=-1,
            metadata={
                "figure_id": figure.figure_id,
                "image_path": figure.image_path,
                "doc_id": doc_id,
            },
        ))
        next_idx += 1
    return chunks
```

#### 4.2.2 检索后 figure collapse

在 `retriever.py` 的 `Retriever.retrieve()` 中，rerank 之后、返回 `out[:top_k]` 之前，增加 figure-level collapse：

```python
def _collapse_figure_duplicates(
    hits: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """同一 figure_id 只保留分数最高的一条。

    collapse key 优先级：
    1. meta.figure_id（如果存在且不为空）
    2. meta.image_path（备用）
    3. 不做 collapse（普通 text chunk）

    当同一 figure 被多次命中时，保留最高分那条，
    并将其 score 增加一个 bonus（多次命中说明更相关）。
    """
    seen_figures: Dict[str, int] = {}  # figure_key -> index in out
    out: List[Dict[str, Any]] = []
    for hit in hits:
        meta = hit.get("meta", {})
        figure_id = meta.get("figure_id", "")
        image_path = meta.get("image_path", "")
        chunk_type = meta.get("chunk_type", "text")
        if chunk_type != "figure" or (not figure_id and not image_path):
            out.append(hit)
            continue
        figure_key = figure_id or image_path
        if figure_key in seen_figures:
            # 已有同 figure 的更高分条目，跳过
            continue
        seen_figures[figure_key] = len(out)
        out.append(hit)
    return out
```

在 `Retriever.retrieve()` 中的调用位置：

```python
    if reranker_model:
        out = rerank_hits(query, out, reranker_model)
    out = _collapse_figure_duplicates(out)  # 新增
    return out[:top_k]
```

### 4.3 涉及文件

| 文件 | 改动 |
|------|------|
| `src/ingest/figure_captioner.py` | `process_figures()` 加 figure_id 去重，`figure_data_to_chunks()` 加 content hash 去重 |
| `src/rag/retriever.py` | 新增 `_collapse_figure_duplicates()`，在 rerank 后调用 |

### 4.4 测试验证

- 同一个 `figure_id` 在 `figure_data_to_chunks()` 输出中最多出现 1 次
- 同一 query 的 top-10 检索结果中，同一 `figure_id` 最多出现 1 次
- collapse 不影响普通 text chunk 的排序

---

## 5. Q4: 检索不理解 figure/公式查询意图

### 5.1 问题根因

当前检索管道（Dense + BM25 + RRF + Reranker）对所有 query 一视同仁。当用户查询明确指向图表（如 "transformer architecture diagram"）或公式（如 "attention score equation"）时，排序结果中 figure chunk 没有先验优势。

Reranker (CrossEncoder) 只看 `(query, text)` 对，不感知 `chunk_type` 等 metadata，因此无法主动偏向 figure chunk。

### 5.2 修复方案

#### 5.2.1 query intent 识别

在 `retriever.py` 中新增轻量规则识别：

```python
_VISUAL_INTENT_TERMS = {
    "figure", "fig", "diagram", "architecture", "plot", "chart",
    "table", "visualization", "illustration", "schematic", "overview",
    "flowchart", "pipeline", "framework",
    # 中文
    "图", "图表", "架构图", "流程图", "示意图", "框架图",
}

_FORMULA_INTENT_TERMS = {
    "equation", "formula", "derive", "derivation", "proof",
    "theorem", "lemma", "corollary", "mathematical",
    # 中文
    "公式", "方程", "推导", "证明", "定理",
}

def _detect_query_intent(query: str) -> str:
    """返回 'visual' | 'formula' | 'general'"""
    q_lower = query.lower()
    tokens = set(re.findall(r"[a-zA-Z\u4e00-\u9fff]+", q_lower))
    if tokens & _VISUAL_INTENT_TERMS:
        return "visual"
    if tokens & _FORMULA_INTENT_TERMS:
        return "formula"
    return "general"
```

#### 5.2.2 RRF 阶段加 chunk_type prior

在 `_reciprocal_rank_fusion()` 之后、rerank 之前，对候选结果施加意图先验：

```python
_VISUAL_FIGURE_BONUS = 0.003   # 约等于排名提升 3-5 位
_FORMULA_MATH_BONUS = 0.002

def _apply_intent_prior(
    hits: List[Dict[str, Any]],
    intent: str,
) -> List[Dict[str, Any]]:
    """根据 query intent 对特定 chunk_type 加 score bonus。

    bonus 加在 rrf_score（如果有）或 distance 的归一化分数上。
    不改变 reranker 的输入格式——reranker 仍然只看 (query, text)。
    """
    if intent == "general":
        return hits

    boosted = []
    for hit in hits:
        entry = dict(hit)
        meta = entry.get("meta", {})
        chunk_type = meta.get("chunk_type", "text")

        bonus = 0.0
        if intent == "visual" and chunk_type == "figure":
            bonus = _VISUAL_FIGURE_BONUS
        elif intent == "formula" and _has_math_density(entry.get("text", "")):
            bonus = _FORMULA_MATH_BONUS

        if bonus > 0 and "rrf_score" in entry:
            entry["rrf_score"] = entry["rrf_score"] + bonus
        boosted.append(entry)

    boosted.sort(key=lambda x: x.get("rrf_score", 0), reverse=True)
    return boosted


def _has_math_density(text: str, threshold: float = 0.05) -> bool:
    """判断文本中数学符号密度是否超过阈值。"""
    if not text:
        return False
    math_chars = sum(1 for c in text if c in "$\\^_{}")
    return (math_chars / max(1, len(text))) > threshold
```

在 `Retriever.retrieve()` 中的调用位置：

```python
        # --- RRF 融合之后 ---
        if hybrid and persist_dir and collection_name:
            ...
            out = [h for h in fused if h.get("text")]
        else:
            out = dense_hits

        # --- 新增：应用意图先验 ---
        intent = _detect_query_intent(query)
        if intent != "general":
            out = _apply_intent_prior(out, intent)

        if reranker_model:
            out = rerank_hits(query, out, reranker_model)
        out = _collapse_figure_duplicates(out)
        return out[:top_k]
```

#### 5.2.3 结果多样性约束

对 visual intent 的 query，确保 top-k 中至少有 figure chunk 候选（如果库中存在）：

```python
def _ensure_figure_presence(
    hits: List[Dict[str, Any]],
    top_k: int,
    min_figure_slots: int = 2,
) -> List[Dict[str, Any]]:
    """如果 top_k 中没有 figure chunk，从后续候选中提升最佳 figure 进入 top_k。

    只在 visual intent 时调用。不改变已有 text chunk 的相对顺序。
    """
    top = hits[:top_k]
    rest = hits[top_k:]

    figure_count = sum(1 for h in top if h.get("meta", {}).get("chunk_type") == "figure")
    if figure_count >= min_figure_slots:
        return hits

    # 从 rest 中找 figure chunk
    needed = min_figure_slots - figure_count
    figure_candidates = [h for h in rest if h.get("meta", {}).get("chunk_type") == "figure"]
    to_insert = figure_candidates[:needed]
    if not to_insert:
        return hits

    # 替换 top 中分数最低的 text chunk
    for fig_hit in to_insert:
        # 找 top 中最末尾的 text chunk
        for i in range(len(top) - 1, -1, -1):
            if top[i].get("meta", {}).get("chunk_type") != "figure":
                top[i] = fig_hit
                break

    return top + rest
```

### 5.3 涉及文件

| 文件 | 改动 |
|------|------|
| `src/rag/retriever.py` | 新增 `_detect_query_intent()`、`_apply_intent_prior()`、`_ensure_figure_presence()`，修改 `Retriever.retrieve()` 调用链 |

### 5.4 测试验证

- query "attention is all you need model diagram" 的 top-5 中包含 figure chunk
- query "scaled dot product attention equation" 的 top-5 中包含数学密度高的 chunk
- query "transformer training details"（无图/公式意图）的排序不受影响
- intent 识别覆盖中英文关键词

---

## 6. 实施顺序与依赖关系

```
Q1 (caption/context 边界) ─────┐
                                ├──→ 入库质量回归测试
Q2 (LaTeX 数学保留) ───────────┘
                                          │
Q3 (figure 去重) ─────────────────────────┤
                                          │
                                          ↓
                              Q4 (query intent + prior)
                                          │
                                          ↓
                                    端到端回归测试
```

- Q1 和 Q2 可并行开发，互不依赖
- Q3 入库前去重不依赖 Q1/Q2，检索后 collapse 独立实现
- Q4 依赖 Q3 的 collapse（否则 figure prior 会加剧重复问题）

### 建议开发顺序

| 轮次 | 任务 | 预期效果 |
|------|------|---------|
| 第 1 轮 | Q1 + Q2 + Q3 入库前去重 | chunk 质量显著提升 |
| 第 2 轮 | Q3 检索后 collapse | top-k 不再有重复 figure |
| 第 3 轮 | Q4 intent prior + diversity | figure/公式 query 命中率提升 |

---

## 7. 回归测试基准

所有修复完成后，应建立以下持续回归基准：

### 7.1 抽取质量

| 指标 | 合格标准 |
|------|---------|
| figure caption 平均长度 | < 200 字符 |
| figure caption P95 长度 | < 500 字符 |
| figure context 总长度 | <= 800 字符 |
| 同一 doc 中重复 figure_id 的 chunk 数 | 0 |

### 7.2 数学保真

对 1706.03762 (Attention Is All You Need) 验证：

| 检查项 | 期望 |
|--------|------|
| `\sqrt{d_k}` 保留 | 输出含 `$\sqrt{d_k}$` 或 `\sqrt{d_k}` |
| `\frac{QK^T}{\sqrt{d_k}}` 保留 | 输出含 `\frac` 结构 |
| 上下标保留 | `PE_{(pos,2i)}` 中 `_` 和 `^` 不丢失 |

### 7.3 检索质量

| query | 期望 top-5 行为 |
|-------|----------------|
| `transformer architecture encoder decoder figure` | 至少 1 条 figure chunk |
| `scaled dot product attention equation` | 至少 1 条含 `$` 的高数学密度 chunk |
| `multi head attention formula` | 至少 1 条含 `$` 的 chunk |
| `attention is all you need model diagram` | top-1 为 figure chunk（非论文首页文本） |
| `transformer training details` | 排序不受 figure prior 影响 |

### 7.4 去重

| 指标 | 合格标准 |
|------|---------|
| 任意 query 的 top-10 中同一 figure_id 出现次数 | <= 1 |

---

## 8. 完整文件改动清单

| 文件 | 问题编号 | 改动类型 |
|------|---------|---------|
| `src/ingest/figure_extractor.py` | Q1 | 重写 `_extract_captions()`、`_extract_reference_paragraphs()`、修改 `build_figure_contexts_from_text()` |
| `src/ingest/latex_loader.py` | Q2 | 重写 `_latex_to_markdown()`、`_normalize_display_math()`、`_latex_inline_to_text()` |
| `src/ingest/figure_captioner.py` | Q3 | `process_figures()` 加 figure_id 去重，`figure_data_to_chunks()` 加 content hash 去重 |
| `src/rag/retriever.py` | Q3, Q4 | 新增 `_collapse_figure_duplicates()`、`_detect_query_intent()`、`_apply_intent_prior()`、`_ensure_figure_presence()` |
| `tests/test_figure_extractor.py` | Q1 | 新增 caption 长度、context 长度回归测试 |
| `tests/test_latex_loader.py` | Q2 | 新增数学保真测试用例 |
| `tests/test_figure_captioner.py` | Q3 | 新增去重测试 |
| `tests/test_retriever_intent.py` | Q4 | 新增 intent 识别、figure prior、collapse 测试 |
