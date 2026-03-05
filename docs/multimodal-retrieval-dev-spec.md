# 多模态检索开发规范文档

> 版本: 1.0
> 日期: 2026-03-05
> 状态: 待开发

---

## 1. 背景与目标

当前 ingest 管道使用 PyMuPDF 做纯文本提取（`src/ingest/pdf_loader.py`），存在三个核心信息损失：

1. **图表完全丢失** — `page.get_text("text")` 不提取图片
2. **数学公式乱码** — 复杂 LaTeX 公式被转为残缺 Unicode 字符
3. **表格结构丢失** — 表格变成无序散乱文字

本需求的目标是在不改变现有检索链路（Dense + BM25 + Reranker）的前提下，通过改进 ingest 管道来解决上述问题。改进后的 chunk 仍然进入同一个 Chroma collection + BM25 sidecar，检索代码无需改动。

---

## 2. 总体架构

```
论文入库流程
  │
  ├─ 来源判断: has_latex_source(uid)?
  │   │
  │   ├─ Yes ──→ S1: LaTeX 源码解析
  │   │           ├─ 正文 + 公式 → Markdown 文本
  │   │           └─ \begin{figure} → 原始图片 + caption + \ref 上下文
  │   │
  │   └─ No ───→ S2: Marker PDF 提取
  │               ├─ 正文 + 公式 + 表格 → Markdown 文本
  │               └─ S3: PyMuPDF 提取嵌入图片 + 正则匹配 caption
  │
  ├─ 文本 chunks（来自 S1 或 S2）
  │   └─ 走现有 chunking → indexer 管道，无改动
  │
  ├─ 图片处理（S1/S2 的图片输出汇合）
  │   ├─ S4: 提取 caption + 正文引用上下文
  │   ├─ S5: VLM 约束描述 + 自验证
  │   └─ S6: 组装 figure chunk → 入 Chroma + BM25
  │
  └─ 完成
```

---

## 3. 配置设计

在 `configs/agent.yaml` 和 `configs/rag.yaml` 中新增 `ingest` 配置节：

```yaml
ingest:
  # 文本提取策略: "auto" | "latex_first" | "marker_only" | "pymupdf_only"
  #   auto         — 有 LaTeX 源码时用 LaTeX 解析，否则用 Marker
  #   latex_first  — 同 auto（语义相同，显式声明）
  #   marker_only  — 始终用 Marker，忽略 LaTeX 源码
  #   pymupdf_only — 使用原始 PyMuPDF（向后兼容）
  text_extraction: auto

  latex:
    # 是否在 fetch 阶段自动下载 arXiv 源码 tarball
    download_source: true
    # 源码存储目录
    source_dir: ${project.data_dir}/sources

  figure:
    # 是否启用图表提取和描述
    enabled: true
    # 图片存储目录
    image_dir: ${project.data_dir}/figures
    # 图片最小尺寸（像素），低于此值视为 icon/logo，跳过
    min_width: 100
    min_height: 100
    # VLM 描述
    vlm_model: gemini-2.5-flash
    vlm_temperature: 0.1
    # 自验证: VLM 描述与 caption 关键实体的最低匹配率
    # 低于此值时丢弃 VLM 描述，仅保留 caption + 上下文
    validation_min_entity_match: 0.5
```

### 3.1 配置解析

在 `src/common/rag_config.py` 中新增以下辅助函数：

```python
def ingest_text_extraction(cfg, override=None) -> str:
    """返回 'auto' | 'latex_first' | 'marker_only' | 'pymupdf_only'"""

def ingest_latex_download_source(cfg) -> bool:

def ingest_latex_source_dir(root, cfg) -> Path:

def ingest_figure_enabled(cfg) -> bool:

def ingest_figure_image_dir(root, cfg) -> Path:

def ingest_figure_vlm_model(cfg) -> str:
```

---

## 4. S1: LaTeX 源码解析器

### 4.1 目标

对于有 LaTeX 源码的论文（主要是 arXiv），直接解析 `.tex` 文件提取正文、公式、图表信息，获得零损失的结构化内容。

### 4.2 新建文件

**`src/ingest/latex_loader.py`**

### 4.3 源码下载

arXiv 源码 tarball 下载地址为 `https://arxiv.org/e-print/{arxiv_id}`（无文件扩展名），返回 `.tar.gz` 或单个 `.tex` 文件。

```python
@dataclass
class ArxivSource:
    arxiv_id: str
    source_dir: Path          # 解压后的目录
    tex_files: List[Path]     # 所有 .tex 文件
    main_tex: Path            # 主 .tex 文件
    image_files: List[Path]   # .png, .pdf, .eps, .jpg 等

def download_arxiv_source(
    arxiv_id: str,
    source_dir: str,
    polite_delay_sec: float = 1.0,
) -> ArxivSource | None:
    """下载并解压 arXiv 源码。

    下载 URL: https://arxiv.org/e-print/{arxiv_id}
    解压到:   {source_dir}/{arxiv_id}/

    主 .tex 文件识别策略（按优先级）:
      1. 包含 \\documentclass 的 .tex 文件
      2. 与 arxiv_id 同名的 .tex 文件
      3. main.tex / paper.tex
      4. 目录中唯一的 .tex 文件

    返回 None 如果下载失败或内容不是 LaTeX 源码。
    """
```

**集成点**: 在 `src/ingest/fetchers.py` 的 `fetch_arxiv()` 中，当 `download_source=True` 时，在下载 PDF 之后额外调用 `download_arxiv_source()`。将 `source_dir` 路径写入 `PaperRecord` 的新字段 `source_path`。

### 4.4 LaTeX 解析

```python
@dataclass
class ParsedLatex:
    text: str                   # 全文 Markdown（公式保留为 $...$, $$...$$）
    num_pages: int              # 估算页数（基于字符数，约 3000 字符/页）
    figures: List[LatexFigure]  # 提取的图表信息

@dataclass
class LatexFigure:
    figure_id: str              # LaTeX label, e.g. "fig:architecture"
    caption: str                # \caption{...} 的完整文本
    image_ref: str              # \includegraphics 的文件路径（相对于源码目录）
    image_path: Path | None     # 解析后的图片绝对路径（如果文件存在）
    context_paragraphs: List[str]  # 正文中引用此图的段落（通过 \ref{label} 定位）

def parse_latex(source: ArxivSource) -> ParsedLatex:
    """解析 LaTeX 源码，提取结构化内容。

    处理流程:
      1. 读取 main_tex，递归展开 \\input{} / \\include{}
      2. 展开用户自定义 \\newcommand（仅处理简单的无参/单参宏）
      3. 移除 \\usepackage, \\documentclass 等 preamble
      4. 数学环境处理:
         - 行内公式 $...$ → 保留原样
         - display 公式 \\begin{equation}...\\end{equation} → $$...$$
         - align, gather, multline 等 → $$...$$（去掉对齐符号 & 和 \\\\）
      5. 章节结构: \\section{X} → ## X, \\subsection{X} → ### X
      6. 图表提取: 识别 \\begin{figure}...\\end{figure} 块
         - 提取 \\caption{...}
         - 提取 \\includegraphics[...]{path}
         - 提取 \\label{...}
         - 通过 label 在全文中搜索 \\ref{label} / \\cref{label}，
           提取引用所在段落作为 context_paragraphs
      7. 表格: \\begin{table}...\\end{table} 尝试转为 Markdown 表格
      8. 引用: \\cite{key} → [key]（保留引用标记供后续分析）
    """
```

**解析工具**: 使用 `TexSoup` 做 AST 级解析。`TexSoup` 可以处理嵌套环境、宏调用等结构。对于 `TexSoup` 无法处理的边界情况（如复杂宏定义），退回正则匹配。

**依赖**: `pyproject.toml` 新增 `TexSoup>=0.3.3`。

### 4.5 与现有管道对接

`parse_latex()` 返回的 `ParsedLatex.text` 将替代 `LoadedPDF.text` 传入现有的 `chunk_text()` → `build_chroma_index()` 管道。`ParsedLatex.figures` 将进入 S4-S6 的图表处理管道。

### 4.6 回退机制

以下情况自动回退到 S2（Marker PDF 提取）：
- 源码下载失败（网络错误、非 LaTeX 格式）
- 找不到主 `.tex` 文件
- `parse_latex()` 抛出异常
- 解析结果文本长度 < 500 字符（可能是不完整的解析）

回退时记录 warning 日志，不中断流程。

---

## 5. S2: Marker PDF 提取

### 5.1 目标

当没有 LaTeX 源码时，使用 Marker 替代 PyMuPDF 进行 PDF 文本提取，获得 Markdown 格式的输出（公式保留为 LaTeX、表格保留结构）。

### 5.2 修改文件

**`src/ingest/pdf_loader.py`**

### 5.3 接口设计

保持现有 `LoadedPDF` 数据结构和 `load_pdf_text()` 函数签名不变，通过新增 `backend` 参数切换实现：

```python
@dataclass
class LoadedPDF:
    pdf_path: str
    text: str
    num_pages: int

def load_pdf_text(
    pdf_path: str,
    max_pages: int | None = None,
    backend: str = "pymupdf",       # "pymupdf" | "marker"
) -> LoadedPDF:
    """加载 PDF 文本。

    backend:
      - "pymupdf": 原始实现（向后兼容，默认值）
      - "marker":  使用 marker-pdf，输出 Markdown + LaTeX 公式
    """
```

### 5.4 Marker 后端实现

```python
def _load_with_marker(pdf_path: str, max_pages: int | None = None) -> LoadedPDF:
    """使用 marker-pdf 提取 PDF 内容。

    调用 marker 的 convert_single_pdf() API:
      - 输出格式: Markdown
      - 公式: 保留为 $...$ / $$...$$
      - 表格: 转为 Markdown table
      - 图片: marker 会识别图片区域但不提取图片文件
               （图片提取由 S3 的 PyMuPDF 路径处理）

    max_pages 处理:
      - marker 原生支持 page 范围参数
      - 传入 max_pages 时限制处理的页面数

    输出:
      - text: Markdown 格式的全文
      - num_pages: PDF 实际总页数
    """
```

### 5.5 PyMuPDF 后端保留

原有的 PyMuPDF 实现保持不变，作为 `backend="pymupdf"` 的实现。配置为 `ingest.text_extraction: pymupdf_only` 时使用此路径。

### 5.6 依赖

`pyproject.toml` 新增 `marker-pdf>=1.0.0`。

注意: marker-pdf 依赖 PyTorch。项目已通过 sentence-transformers 间接依赖 PyTorch，无需额外安装。

---

## 6. S3: 图片提取

### 6.1 目标

从论文中提取图片文件，包括两个来源路径的统一处理。

### 6.2 新建文件

**`src/ingest/figure_extractor.py`**

### 6.3 数据结构

```python
@dataclass
class ExtractedFigure:
    figure_id: str             # 标识符: "fig_0", "fig_1", ... 或 LaTeX label
    image_path: Path           # 提取后的图片文件路径
    width: int                 # 图片宽度 (px)
    height: int                # 图片高度 (px)
    page_number: int | None    # 所在 PDF 页码（仅 PDF 提取时有值）
    source: str                # "latex" | "pdf"
```

### 6.4 LaTeX 路径 — 从源码 tarball 提取图片

```python
def extract_figures_from_latex(
    source: ArxivSource,
    figures: List[LatexFigure],
    image_dir: str,
    doc_id: str,
    min_width: int = 100,
    min_height: int = 100,
) -> List[ExtractedFigure]:
    """从 LaTeX 源码包中提取图片文件。

    处理流程:
      1. 遍历 LatexFigure 列表中的 image_ref（\includegraphics 路径）
      2. 在 source.source_dir 中查找对应文件
         - 尝试原始路径
         - 尝试补充扩展名 (.pdf, .png, .eps, .jpg)
         - 尝试在 figures/ 子目录中查找
      3. 格式转换:
         - .eps → .png（使用 PyMuPDF 的 fitz.open() 转换）
         - .pdf (单页) → .png（使用 PyMuPDF 渲染为图片）
         - .png / .jpg → 直接复制
      4. 过滤: 跳过小于 min_width x min_height 的图片
      5. 保存到 {image_dir}/{doc_id}/fig_N.png

    返回 ExtractedFigure 列表，其中 figure_id 使用 LaTeX label。
    """
```

### 6.5 PDF 路径 — 从 PDF 文件提取嵌入图片

```python
def extract_figures_from_pdf(
    pdf_path: str,
    image_dir: str,
    doc_id: str,
    min_width: int = 100,
    min_height: int = 100,
) -> List[ExtractedFigure]:
    """从 PDF 中提取嵌入图片。

    处理流程:
      1. 使用 fitz.open() 打开 PDF
      2. 遍历每一页，调用 page.get_images(full=True)
      3. 对每张图片:
         a. 提取原始图片字节 (fitz.Pixmap)
         b. 检查尺寸，跳过小于阈值的图片
         c. 转为 PNG 保存到 {image_dir}/{doc_id}/fig_N.png
         d. 记录所在页码
      4. 去重: 基于图片字节的 hash 去除重复图片
         （PDF 中同一张图可能在多处引用）

    返回 ExtractedFigure 列表，figure_id 为 "fig_0", "fig_1", ...
    """
```

### 6.6 统一入口

```python
def extract_figures(
    *,
    pdf_path: str,
    doc_id: str,
    image_dir: str,
    latex_source: ArxivSource | None = None,
    latex_figures: List[LatexFigure] | None = None,
    min_width: int = 100,
    min_height: int = 100,
) -> List[ExtractedFigure]:
    """统一图片提取入口。

    有 LaTeX 源码时优先从 tarball 提取（质量更高），
    否则从 PDF 提取。
    """
```

---

## 7. S4: Caption 和上下文提取

### 7.1 目标

为每张图提取两种零幻觉的文本信息：作者写的 caption，以及正文中引用该图的段落。

### 7.2 实现位置

在 `src/ingest/figure_extractor.py` 中新增函数。

### 7.3 数据结构

```python
@dataclass
class FigureContext:
    figure_id: str
    image_path: Path
    caption: str                     # 作者原始 caption
    context_paragraphs: List[str]    # 引用该图的正文段落
    source: str                      # "latex" | "pdf_regex"
```

### 7.4 LaTeX 路径

当来源为 LaTeX 时，caption 和 context 已经在 S1 的 `LatexFigure` 中提取完成，直接使用：

```python
def build_figure_contexts_from_latex(
    figures: List[LatexFigure],
    extracted: List[ExtractedFigure],
) -> List[FigureContext]:
    """将 LatexFigure（S1 输出）和 ExtractedFigure（S3 输出）合并。

    按 figure_id 匹配，组装 FigureContext。
    """
```

### 7.5 PDF 路径 — 正则匹配

当来源为 PDF 时，需要从提取的文本中匹配 caption 和引用：

```python
def build_figure_contexts_from_text(
    full_text: str,
    extracted: List[ExtractedFigure],
) -> List[FigureContext]:
    """从 PDF 提取的全文中匹配图表 caption 和引用上下文。

    Caption 匹配策略:
      1. 正则匹配: Figure\s+(\d+)[.:]\s*(.+?)(?=\n\n|\nFigure\s|\nTable\s|$)
         - 支持 "Figure 1:", "Figure 1.", "Fig. 1:" 等变体
         - caption 可能跨多行，以空行或下一个 Figure/Table 标记为终止
      2. 按 page_number 关联:
         - 将 caption 中的编号 N 与 extracted[N-1] 关联
         - 如果编号不连续，按页码就近匹配

    上下文提取策略:
      1. 在全文中搜索引用模式:
         - "Figure N", "Fig. N", "figure N", "fig. N"
         - "(see Figure N)", "as shown in Figure N"
         - "Figures N and M", "Figs. N-M"
      2. 对每个匹配位置，提取所在段落（前后各扩展到空行边界）
      3. 去重（同一段落引用多次只保留一份）

    注意:
      - 如果完全匹配不到 caption（某些论文格式特殊），
        FigureContext.caption 设为空字符串，不编造内容
      - context_paragraphs 可能为空列表（有的图在正文中未被引用）
    """
```

---

## 8. S5: VLM 约束描述与自验证

### 8.1 目标

使用 Gemini Vision API 为图片生成结构化描述，同时通过 caption 锚点和自验证机制最大限度减少幻觉。

### 8.2 新建文件

**`src/ingest/figure_captioner.py`**

### 8.3 VLM 调用

```python
def describe_figure(
    *,
    image_path: Path,
    caption: str,
    context_paragraphs: List[str],
    paper_title: str,
    vlm_model: str = "gemini-2.5-flash",
    temperature: float = 0.1,
) -> str:
    """调用 Gemini Vision API 生成图片的结构化描述。

    Prompt 设计:
      system: |
        You are an academic figure analyst. Describe ONLY what is
        directly visible in the image. Do not speculate or add
        information not present in the image.

      user: |
        Paper title: {paper_title}

        Author's caption for this figure:
        {caption}

        Relevant paragraphs from the paper that reference this figure:
        {context_paragraphs}

        Analyze the figure image and provide a structured description:
        1. CHART TYPE: (bar chart / line plot / table / diagram / ...)
        2. AXES: X-axis label and range, Y-axis label and range
           (if applicable)
        3. DATA SERIES: List each series/group with its legend label
        4. KEY VALUES: Notable data points, peaks, or trends that are
           clearly readable from the figure
        5. VISUAL ELEMENTS: Arrows, annotations, color coding, etc.

        Rules:
        - Only report values you can clearly read from the figure.
        - If a value is not clearly readable, say "not clearly readable"
          instead of guessing.
        - If the caption mentions something not visible in the image,
          note: "mentioned in caption but not visible in image".
        - Do NOT interpret or explain the results. Only describe what
          you see.

    API 调用:
      使用 google.genai SDK，传入图片字节 + 上述 prompt。
      复用 src/agent/infra/llm/gemini_chat_client.py 中的 API key
      获取逻辑，但使用多模态 contents 格式:

        contents = [
            Part(text=user_prompt),
            Part(inline_data=Blob(mime_type="image/png", data=image_bytes)),
        ]

    温度设为 0.1 以减少创造性输出。

    返回: VLM 生成的结构化描述文本。
    """
```

### 8.4 自验证

```python
@dataclass
class ValidationResult:
    passed: bool
    entity_match_rate: float     # caption 关键实体在 VLM 描述中的匹配率
    matched_entities: List[str]
    missing_entities: List[str]
    description: str             # 验证通过时为 VLM 描述，否则为空字符串

def validate_description(
    vlm_description: str,
    caption: str,
    min_entity_match: float = 0.5,
) -> ValidationResult:
    """验证 VLM 描述与 caption 的一致性。

    验证流程:
      1. 从 caption 中提取关键实体:
         a. 数值 + 单位: 正则匹配 \d+\.?\d*\s*(%|ms|sec|accuracy|...)
         b. 方法名/模型名: 连续大写字母 + 数字的 token (e.g., BERT, GPT-4, ResNet-50)
         c. 趋势词: "increase", "decrease", "outperform", "better", "worse"
         d. 比较关系: "A > B", "A vs B"
      2. 检查每个实体是否出现在 VLM 描述中（大小写不敏感）
      3. 计算匹配率 = matched / total
      4. 如果匹配率 < min_entity_match:
         - passed = False
         - description 设为空字符串（后续仅使用 caption + context）
         - 记录 warning 日志: 哪些实体不匹配
      5. 如果 caption 为空（未匹配到 caption）:
         - 无法验证，直接 passed = True（保留 VLM 描述，
           因为这是唯一的信息来源）

    此机制确保: 当 VLM 产生与作者 caption 矛盾的内容时，
    宁可丢弃 VLM 描述也不引入幻觉。
    """
```

### 8.5 批量处理入口

```python
def process_figures(
    *,
    figure_contexts: List[FigureContext],
    paper_title: str,
    vlm_model: str = "gemini-2.5-flash",
    temperature: float = 0.1,
    validation_min_entity_match: float = 0.5,
) -> List[FigureChunkData]:
    """批量处理所有图表: VLM 描述 + 自验证。

    对每个 FigureContext:
      1. 调用 describe_figure() 获取 VLM 描述
      2. 调用 validate_description() 自验证
      3. 组装 FigureChunkData

    错误处理:
      - 单张图片的 VLM 调用失败不中断整体流程
      - 失败时 visual_description 设为空，仅保留 caption + context
      - 记录 warning 日志

    返回 FigureChunkData 列表。
    """
```

---

## 9. S6: Figure Chunk 入库

### 9.1 目标

将图表信息组装为 chunk，进入现有的 Chroma + BM25 索引管道。

### 9.2 数据结构

```python
@dataclass
class FigureChunkData:
    figure_id: str
    caption: str                  # 作者原始 caption（零幻觉）
    context: str                  # 引用上下文拼接（零幻觉）
    visual_description: str       # VLM 验证后的描述（可能为空）
    image_path: str               # 图片文件路径
    validation_passed: bool       # 自验证是否通过
```

### 9.3 Chunk 组装

```python
def figure_data_to_chunks(
    figures: List[FigureChunkData],
    doc_id: str,
    text_chunk_count: int,
) -> List[Chunk]:
    """将 FigureChunkData 转为 Chunk 对象，准备入库。

    对每个 FigureChunkData，生成的 chunk 文本格式:

      [Figure {figure_id}]
      Caption: {caption}
      Context: {context}
      Description: {visual_description}

    规则:
      - caption 为空时省略 Caption 行
      - visual_description 为空时省略 Description 行
      - 如果三个字段全为空，跳过该图（不生成 chunk）
      - chunk_id 从 text_chunk_count 开始编号，避免与文本 chunk 冲突
        e.g., chunk_000015 (如果文本有 15 个 chunk)

    Metadata 扩展:
      Chunk 对象当前只有 chunk_id, text, start_char, end_char。
      Figure chunk 的 start_char 和 end_char 设为 -1（非文本来源）。
      在 indexer.py 的 metadatas 中增加:
        - chunk_type: "figure"        （文本 chunk 为 "text"）
        - figure_id: LatexFigure 的 label 或 "fig_N"
        - image_path: 图片文件路径

    返回 Chunk 列表，可直接传入 build_chroma_index()。
    """
```

### 9.4 Indexer 改动

`src/ingest/indexer.py` 的 `build_chroma_index()` 中，metadatas 构建需要支持 figure chunk 的额外字段：

```python
# 现有 metadata 字段不变，新增 chunk_type 区分:
metas: List[Dict[str, Any]] = [
    {
        "doc_id": doc_id,
        "chunk_id": c.chunk_id,
        "start_char": c.start_char,
        "end_char": c.end_char,
        "run_id": run_id,
        "chunk_type": "figure" if c.start_char == -1 else "text",
    }
    for c in chunks
]
```

这是 `indexer.py` 唯一的改动点。检索侧无需改动 — figure chunk 和 text chunk 在同一个 collection 中，检索逻辑完全一致。

### 9.5 整合到 index_pdfs

`src/workflows/traditional_rag.py` 的 `index_pdfs()` 中，在现有文本 chunk 之后追加 figure chunk：

```python
# 现有文本处理（不变）
loaded = load_pdf_text(str(pdf), max_pages=max_pages, backend=backend)
text_chunks = chunk_text(loaded.text, chunk_size=chunk_size, overlap=overlap)

# 新增: 图表处理
figure_chunks = []
if figure_enabled:
    extracted = extract_figures(
        pdf_path=str(pdf),
        doc_id=doc_id,
        image_dir=image_dir,
        latex_source=latex_source,          # S1 的输出，可能为 None
        latex_figures=parsed.figures if parsed else None,
    )
    contexts = build_figure_contexts(...)    # S4
    figure_data = process_figures(...)        # S5
    figure_chunks = figure_data_to_chunks(   # S6
        figure_data, doc_id, len(text_chunks)
    )

# 合并入库
all_chunks = text_chunks + figure_chunks
added = build_chroma_index(
    persist_dir=persist_dir,
    collection_name=collection_name,
    chunks=all_chunks,
    doc_id=doc_id,
    run_id=run_id,
    embedding_model=embedding_model,
    build_bm25=build_bm25,
)
```

---

## 10. 依赖变更

`pyproject.toml` 新增:

```toml
"TexSoup>=0.3.3",        # S1: LaTeX AST 解析
"marker-pdf>=1.0.0",     # S2: PDF → Markdown 提取
```

已有依赖（无需修改）:
- `pymupdf>=1.23.0` — S3 图片提取 + S1 格式转换
- `google-genai>=0.8.0` — S5 Gemini Vision API

---

## 11. 文件清单

| 步骤 | 操作 | 文件路径 |
|------|------|----------|
| S1 | 新建 | `src/ingest/latex_loader.py` |
| S2 | 修改 | `src/ingest/pdf_loader.py` |
| S3 | 新建 | `src/ingest/figure_extractor.py` |
| S4 | 在 S3 文件中 | `src/ingest/figure_extractor.py` |
| S5 | 新建 | `src/ingest/figure_captioner.py` |
| S6 | 修改 | `src/ingest/indexer.py`（metadata 增加 chunk_type） |
| S6 | 修改 | `src/workflows/traditional_rag.py`（整合 figure chunks） |
| S6 | 修改 | `src/agent/infra/indexing/chroma_indexing.py`（透传参数） |
| S6 | 修改 | `src/agent/executors/index_executor.py`（透传配置） |
| 配置 | 修改 | `configs/agent.yaml`（新增 ingest 节） |
| 配置 | 修改 | `configs/rag.yaml`（新增 ingest 节） |
| 配置 | 修改 | `src/common/rag_config.py`（新增配置读取函数） |
| 依赖 | 修改 | `pyproject.toml`（新增 TexSoup, marker-pdf） |

---

## 12. 测试计划

### 12.1 单元测试

| 测试文件 | 覆盖内容 |
|----------|----------|
| `tests/test_latex_loader.py` | 主 tex 识别、宏展开、公式提取、figure 提取、\input 展开、回退机制 |
| `tests/test_pdf_loader_marker.py` | Marker 后端基本功能、backend 参数切换、pymupdf 向后兼容 |
| `tests/test_figure_extractor.py` | LaTeX 路径图片提取、PDF 路径图片提取、尺寸过滤、去重、caption 正则匹配 |
| `tests/test_figure_captioner.py` | VLM prompt 组装、自验证逻辑（mock VLM 响应）、实体提取、边界情况（空 caption） |
| `tests/test_figure_chunk_assembly.py` | chunk 文本格式、chunk_id 编号连续性、空字段跳过、metadata chunk_type |

### 12.2 集成测试

使用一篇真实 arXiv 论文（含公式 + 图表）做端到端验证：

1. 下载源码 + PDF
2. LaTeX 路径提取 → 验证公式完整性
3. Marker 路径提取 → 验证公式完整性
4. 图表提取 → 验证图片数量和质量
5. VLM 描述 → 验证自验证通过率
6. 入库后检索 → 验证图表相关 query 能命中 figure chunk

### 12.3 回归测试

- 配置 `ingest.text_extraction: pymupdf_only` + `ingest.figure.enabled: false` 时，行为与改动前完全一致
- 现有 157 个测试全部通过

---

## 13. 开发顺序与依赖关系

```
S1 (LaTeX 解析器)  ──────────────┐
                                  ├──→ S3 (图片提取) → S4 (caption/上下文)
S2 (Marker PDF 提取) ────────────┘           │
                                              ↓
                                        S5 (VLM 描述 + 自验证)
                                              │
                                              ↓
                                        S6 (入库整合)
```

- S1 和 S2 **可并行开发**，互不依赖
- S3 依赖 S1 的 `ArxivSource` / `LatexFigure` 数据结构
- S4 依赖 S3 的 `ExtractedFigure` 输出
- S5 依赖 S4 的 `FigureContext` 输出
- S6 依赖 S5 的 `FigureChunkData` 输出，以及 S1/S2 的文本输出

建议开发顺序: **S1 → S2 → S3+S4 → S5 → S6**，每步完成后运行对应单元测试 + 全量回归测试。
