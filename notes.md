# 第一阶段实现笔记：MVP RAG 管线

## 目标

第一阶段只做最小可用版本，不做长期记忆、不做 LangGraph、不做 Web UI。

目标链路：

```text
EPUB 原始书籍 -> 解析正文 -> 规范化文本 -> 切分 chunks -> 写入 JSONL -> 构建 Chroma 索引 -> 检索 -> CLI 生成带引用回答
```

完成后应支持：

- 把 `data/raw/epub/` 下的 EPUB 解析为结构化文本。
- 把结构化文本切分为带来源信息的 chunks。
- 用 chunks 构建本地 Chroma 向量索引。
- 在 CLI 中输入问题，检索相关片段，并调用 AIClient2API 后端生成回答。
- 回答中的引用必须来自检索到的 chunk metadata，不能由模型自由编造。

## 第一阶段建议数据格式

### 书籍记录 JSONL

输出路径建议：

```text
data/processed/books_jsonl/books.jsonl
```

每一行是一段从 EPUB 解析出的章节或段落记录：

```json
{
  "book_id": "sha1-or-stem",
  "title": "书名",
  "author": "作者",
  "source_path": "data/raw/epub/example.epub",
  "chapter_index": 3,
  "chapter_title": "章节标题",
  "paragraph_index": 12,
  "text": "规范化后的正文段落"
}
```

说明：

- `book_id` 用文件路径或元数据生成稳定 ID，避免同名书冲突。
- `title`、`author` 优先从 EPUB metadata 读取；缺失时用文件名和空字符串兜底。
- `chapter_title` 不可靠时允许为空，但 `chapter_index` 和 `paragraph_index` 必须保留。
- `text` 不保存 HTML，只保存可读纯文本。

### Chunk JSONL

输出路径建议：

```text
data/processed/chunks_jsonl/chunks.jsonl
```

每一行是一个可检索 chunk：

```json
{
  "chunk_id": "book_id:chapter_index:chunk_index",
  "book_id": "sha1-or-stem",
  "title": "书名",
  "author": "作者",
  "chapter_index": 3,
  "chapter_title": "章节标题",
  "chunk_index": 5,
  "start_paragraph_index": 12,
  "end_paragraph_index": 18,
  "text": "用于 embedding 和回答的 chunk 文本"
}
```

Chunk 规则：

- 中文正文建议每个 chunk 约 `300-800` 个中文字符。
- overlap 建议 `80-120` 个字符起步。
- 不要把引用信息拼进 `text`，引用应放在 metadata 中。
- 切分时优先按段落累积，不要粗暴按固定字符数截断。

## 模块拆分

### 1. 配置层

文件：

```text
app/config.py
```

职责：

- 从 `.env` 读取配置。
- 提供统一的 `Settings` 对象。
- 配置项至少包括：
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `CHAT_MODEL`
  - `EMBEDDING_MODEL`
  - `VECTOR_DB_PATH`
  - `RAW_EPUB_DIR`
  - `BOOKS_JSONL_PATH`
  - `CHUNKS_JSONL_PATH`

实现建议：

- 使用 `pydantic` 或 `pydantic-settings` 风格的结构化配置。
- 当前 requirements 没有 `pydantic-settings`，为了避免新增依赖，可以先用 `python-dotenv + pydantic.BaseModel`。

### 2. Schema 层

文件：

```text
app/models/schemas.py
```

职责：

- 定义核心数据结构，避免各模块之间传 dict。
- 第一阶段至少定义：
  - `BookParagraph`
  - `TextChunk`
  - `RetrievedChunk`
  - `AnswerWithCitations`

建议：

- 用 `pydantic.BaseModel`。
- metadata 字段保持简单、可 JSON 序列化。

### 3. EPUB 解析

文件：

```text
app/ingestion/load_epub.py
app/ingestion/normalize.py
```

职责：

- 读取单个 EPUB。
- 提取书名、作者、章节顺序、章节标题和正文段落。
- 清理 HTML、脚注噪音、连续空白、导航目录残留。

实现建议：

- 用 `ebooklib.epub.read_epub()` 读取文件。
- 用 `BeautifulSoup(..., "lxml")` 提取文本。
- 只处理 `ebooklib.ITEM_DOCUMENT` 类型内容。
- 对每个 HTML document：
  - 尝试从 `h1/h2/h3/title` 获取章节标题。
  - 从 `p`、`div` 等正文节点提取文本。
  - 过滤过短文本，例如少于 10 个字符的孤立导航项。
- 保留解析顺序，先不要做复杂目录映射。

注意：

- EPUB 内部可能包含图片、CSS、字体、封面、目录文件，所以文件大小不只由字数决定。
- 第一阶段不处理图片 OCR。
- 第一阶段不尝试恢复精确页码，因为 EPUB 通常没有固定页码。

### 4. 入库前 JSONL 生成

文件：

```text
scripts/ingest_books.py
```

职责：

- 扫描 `data/raw/epub/*.epub`。
- 调用 EPUB loader。
- 写出 `books.jsonl`。
- 调用 chunker。
- 写出 `chunks.jsonl`。

命令目标：

```powershell
conda run -n reading-agent python scripts/ingest_books.py
```

建议参数：

```text
--raw-dir data/raw/epub
--books-out data/processed/books_jsonl/books.jsonl
--chunks-out data/processed/chunks_jsonl/chunks.jsonl
--chunk-size 600
--overlap 100
```

第一版可以使用默认参数，后续再补 CLI 参数。

### 5. Chunking

文件：

```text
app/ingestion/chunking.py
tests/test_chunking.py
scripts/inspect_chunking.py
```

职责：

- 将 `BookParagraph` 列表切成 `TextChunk`。
- 保留来源 metadata。
- 支持人工抽查 chunk 质量。

实现建议：

- 按同一本书、同一章节聚合段落。
- 累积段落直到接近目标 chunk size。
- 超过上限时输出当前 chunk。
- overlap 可以从上一 chunk 尾部截取若干字符，也可以保留末尾若干段落。
- 第一阶段优先保证可读性，宁可 chunk 长度略不均匀，也不要把句子切得太碎。

测试重点：

- 空输入返回空列表。
- chunk_id 稳定。
- chunk metadata 包含书名、作者、章节、段落范围。
- chunk 文本长度大致在预期范围内。

人工检查命令目标：

```powershell
conda run -n reading-agent python scripts/inspect_chunking.py
```

输出应随机打印若干 chunk 的：

- `chunk_id`
- `title`
- `chapter_title`
- 前后 200 字文本

### 6. 构建 Chroma 索引

文件：

```text
app/ingestion/build_index.py
scripts/rebuild_index.py
```

职责：

- 读取 `chunks.jsonl`。
- 调用 OpenAI-compatible embedding。
- 写入本地 Chroma collection。

实现建议：

- 使用 `langchain-openai` 的 `OpenAIEmbeddings`。
- 使用 `langchain-chroma` 的 `Chroma`。
- collection name 建议固定为 `reading_memory_chunks`。
- Chroma 持久化路径使用 `.env` 中的 `VECTOR_DB_PATH`，默认 `data/index/chroma`。
- 写入 documents 时：
  - `page_content` = chunk text
  - `metadata` = 除 text 外的 chunk 字段
  - `ids` = chunk_id

命令目标：

```powershell
conda run -n reading-agent python scripts/rebuild_index.py
```

注意：

- 重建索引前可以清空 collection，但不要删除整个 `data/index/` 目录。
- 如果 embedding 模型不可用，应明确报错：是 AIClient2API 通路失败、模型名错误，还是 provider 不支持 embedding。

### 7. 基础向量检索

文件：

```text
app/retrieval/vector_retriever.py
tests/test_retrieval.py
```

职责：

- 接收用户 query。
- 从 Chroma 检索 top-k chunks。
- 返回 `RetrievedChunk` 列表。

实现建议：

- 默认 `top_k=5`。
- 使用 similarity search with score。
- 分数、chunk_id、书名、章节都要保留，方便调试。
- 第一阶段先不做 hybrid retrieval、BM25、reranking。

调试输出建议：

```text
[1] score=0.23 title=... chapter=... chunk_id=...
```

### 8. 带引用回答生成

文件：

```text
app/agent/answer_generator.py
app/agent/citation_builder.py
app/prompts/answer_with_citations.md
tests/test_citations.py
```

职责：

- 把检索到的 chunks 整理为上下文。
- 调用 chat model 生成回答。
- 要求模型只能使用提供的上下文。
- 输出答案和引用列表。

引用格式建议：

```text
[1]《书名》/ 作者 / 章节标题 / chunk_id
```

Prompt 约束：

- 如果上下文不足，回答“当前书库证据不足”，不要编造。
- 回答必须包含“引用”部分。
- 引用编号只能来自输入上下文编号。

工程侧校验：

- `citation_builder.py` 负责把 retrieved chunks 转为编号引用。
- 生成后检查引用编号是否存在。
- 第一阶段可以先做轻量校验：若回答没有引用编号，则追加“引用不足”提示或重新生成一次。

### 9. CLI

文件：

```text
scripts/run_cli.py
```

职责：

- 启动交互式命令行。
- 用户输入问题。
- 调用 vector retriever。
- 调用 answer generator。
- 打印答案和引用。

命令目标：

```powershell
conda run -n reading-agent python scripts/run_cli.py
```

交互设计：

```text
Reading Memory Agent
输入问题，输入 /exit 退出。

> 为什么这本书认为记忆是不可靠的？
...
```

建议支持的调试开关：

```text
/debug on
/debug off
```

debug 开启时打印检索结果列表。

## 推荐实现顺序

### Step 1：先定义 schema 和配置

修改文件：

```text
app/models/schemas.py
app/config.py
```

验收：

```powershell
conda run -n reading-agent python -c "from app.config import get_settings; from app.models.schemas import TextChunk; print(get_settings().CHAT_MODEL)"
```

### Step 2：实现 EPUB loader 和 normalize

修改文件：

```text
app/ingestion/load_epub.py
app/ingestion/normalize.py
```

验收：

```powershell
conda run -n reading-agent python -c "from app.ingestion.load_epub import load_epub; print('ok')"
```

然后用一本 EPUB 手动跑解析，确认能输出段落数量、书名和作者。

### Step 3：实现 chunking 和测试

修改文件：

```text
app/ingestion/chunking.py
tests/test_chunking.py
```

验收：

```powershell
conda run -n reading-agent pytest tests/test_chunking.py
```

### Step 4：实现 ingest_books.py

修改文件：

```text
scripts/ingest_books.py
scripts/inspect_chunking.py
```

验收：

```powershell
conda run -n reading-agent python scripts/ingest_books.py
conda run -n reading-agent python scripts/inspect_chunking.py
```

检查：

- `data/processed/books_jsonl/books.jsonl` 存在且非空。
- `data/processed/chunks_jsonl/chunks.jsonl` 存在且非空。
- 随机 20 个 chunk 文本可读，来源可追踪。

### Step 5：实现 Chroma 索引构建

修改文件：

```text
app/ingestion/build_index.py
scripts/rebuild_index.py
```

验收：

```powershell
conda run -n reading-agent python scripts/rebuild_index.py
```

检查：

- `data/index/chroma/` 下出现 Chroma 持久化文件。
- collection 中 document 数量等于或接近 chunks 数量。

### Step 6：实现 vector retriever

修改文件：

```text
app/retrieval/vector_retriever.py
tests/test_retrieval.py
```

验收：

```powershell
conda run -n reading-agent pytest tests/test_retrieval.py
```

手动检查：

```powershell
conda run -n reading-agent python -c "from app.retrieval.vector_retriever import VectorRetriever; r=VectorRetriever(); print(r.search('记忆', top_k=3))"
```

### Step 7：实现回答生成和引用校验

修改文件：

```text
app/agent/answer_generator.py
app/agent/citation_builder.py
app/prompts/answer_with_citations.md
tests/test_citations.py
```

验收：

```powershell
conda run -n reading-agent pytest tests/test_citations.py
```

检查：

- 回答引用编号只来自检索 chunks。
- 上下文不足时不会编造书名、章节或作者。

### Step 8：实现 run_cli.py

修改文件：

```text
scripts/run_cli.py
```

验收：

```powershell
conda run -n reading-agent python scripts/run_cli.py
```

完成标准：

- CLI 能接收问题。
- 能打印检索结果和最终回答。
- 最终回答包含引用。
- `/exit` 可以正常退出。

## 最小可执行命令顺序

首次完整运行：

```powershell
conda activate reading-agent
python scripts/ingest_books.py
python scripts/inspect_chunking.py
python scripts/rebuild_index.py
python scripts/run_cli.py
```

如果不进入 conda shell：

```powershell
conda run -n reading-agent python scripts/ingest_books.py
conda run -n reading-agent python scripts/inspect_chunking.py
conda run -n reading-agent python scripts/rebuild_index.py
conda run -n reading-agent python scripts/run_cli.py
```

测试：

```powershell
conda run -n reading-agent pytest
```

## 常见失败点和排查

### EPUB 解析后文本很少

可能原因：

- 正文不在 `p` 标签里，而是在 `div` 中。
- EPUB 是图片扫描版，正文实际是图片。
- 解析到了目录、版权页，但没有进入正文 spine。

排查：

- 打印每个 document 的 href、标题、提取文本长度。
- 随机输出前几个 HTML document 的纯文本预览。

### Chunk 不可读

可能原因：

- HTML 清理不足，残留目录、脚注、页眉页脚。
- 按固定字符硬切，破坏句子。
- overlap 太大导致重复严重。

排查：

- 运行 `scripts/inspect_chunking.py`。
- 人工检查 20 个 chunk。
- 优先改 normalize 和段落聚合策略。

### Chroma 写入失败

可能原因：

- `VECTOR_DB_PATH` 不存在或无权限。
- embedding 模型名错误。
- AIClient2API 不支持当前 embedding endpoint。
- `.env` 没有被正确加载。

排查：

- 单独调用 embedding，确认能返回向量。
- 打印 `OPENAI_BASE_URL`、`EMBEDDING_MODEL`，但不要打印真实密钥。
- 确认 `data/index/chroma/` 可写。

### CLI 回答没有引用

可能原因：

- prompt 约束不够明确。
- 引用编号没有传入上下文。
- 检索结果为空。

排查：

- debug 模式打印 retrieved chunks。
- 检查 prompt 中是否明确要求只能引用给定编号。
- 在工程侧校验引用编号，不完全依赖模型自觉。

## 第一阶段不做的事

- 不做 Gemini。
- 不做长期记忆。
- 不做 LangGraph。
- 不做 BM25/hybrid retrieval。
- 不做 reranking。
- 不做 Web UI。
- 不做复杂权限和多用户系统。
- 不处理图片 OCR 版 EPUB。

这些内容放到后续阶段，避免第一阶段范围失控。

## 第一阶段最终验收清单

- [ ] `scripts/ingest_books.py` 能从 `data/raw/epub/` 生成 `books.jsonl` 和 `chunks.jsonl`。
- [ ] `scripts/inspect_chunking.py` 能随机打印可读 chunk。
- [ ] `scripts/rebuild_index.py` 能构建 Chroma 索引。
- [ ] `vector_retriever.py` 能返回 top-k chunks 和 metadata。
- [ ] `answer_generator.py` 能基于检索上下文生成回答。
- [ ] 回答中的引用都能对应到真实 chunk。
- [ ] `scripts/run_cli.py` 能完成一次完整问答。
- [ ] `pytest` 至少覆盖 chunking、retrieval、citation 三类核心行为。

## 面向 Python 初学者的逐文件编写指南

这一节按“先能跑，再变好”的原则写。不要一次写完所有文件。每写完一个小文件，马上运行对应命令验证。

### 编写顺序总览

推荐顺序：

```text
1. app/models/schemas.py
2. app/config.py
3. app/ingestion/normalize.py
4. app/ingestion/load_epub.py
5. app/ingestion/chunking.py
6. scripts/ingest_books.py
7. scripts/inspect_chunking.py
8. app/ingestion/build_index.py
9. scripts/rebuild_index.py
10. app/retrieval/vector_retriever.py
11. app/agent/citation_builder.py
12. app/agent/answer_generator.py
13. scripts/run_cli.py
14. tests/*.py
```

原因：

- `schemas.py` 是数据结构，后面所有文件都要用。
- `config.py` 是配置入口，后面调用模型和索引都要用。
- 先完成 EPUB 到 chunk，再做向量库。
- 最后再做 CLI，因为 CLI 只是把前面的功能串起来。

### 1. `app/models/schemas.py`

先写这个文件，因为它不依赖其他业务代码。

需要写入的内容：

- 导入 `BaseModel`。
- 定义 4 个类：
  - `BookParagraph`
  - `TextChunk`
  - `RetrievedChunk`
  - `AnswerWithCitations`

字段建议：

```text
BookParagraph:
  book_id: str
  title: str
  author: str
  source_path: str
  chapter_index: int
  chapter_title: str
  paragraph_index: int
  text: str

TextChunk:
  chunk_id: str
  book_id: str
  title: str
  author: str
  chapter_index: int
  chapter_title: str
  chunk_index: int
  start_paragraph_index: int
  end_paragraph_index: int
  text: str

RetrievedChunk:
  chunk: TextChunk
  score: float | None = None

AnswerWithCitations:
  answer: str
  citations: list[str]
```

验收命令：

```powershell
conda run -n reading-agent python -c "from app.models.schemas import BookParagraph, TextChunk; print('schemas ok')"
```

如果这里失败，先不要写后面的文件。

### 2. `app/config.py`

这个文件负责读取 `.env`。

需要写入的内容：

- 导入 `os`、`Path`、`load_dotenv`、`BaseModel`。
- 调用 `load_dotenv()`。
- 定义 `Settings` 类。
- 定义 `get_settings()` 函数，返回一个 `Settings` 对象。

建议字段：

```text
OPENAI_API_KEY
OPENAI_BASE_URL
CHAT_MODEL
EMBEDDING_MODEL
VECTOR_DB_PATH
RAW_EPUB_DIR
BOOKS_JSONL_PATH
CHUNKS_JSONL_PATH
CHROMA_COLLECTION
```

初学者注意：

- `.env` 里的内容都是字符串。
- 路径可以先用字符串，不必一开始就封装成 `Path`。
- 不要在代码里写死真实 API key。

验收命令：

```powershell
conda run -n reading-agent python -c "from app.config import get_settings; s=get_settings(); print(s.CHAT_MODEL); print(s.VECTOR_DB_PATH)"
```

### 3. `app/ingestion/normalize.py`

这个文件只处理文本清洗，不读 EPUB。

建议先写 2 个函数：

```text
normalize_whitespace(text: str) -> str
is_useful_paragraph(text: str, min_length: int = 10) -> bool
```

职责：

- 把连续空白变成一个空格。
- 去掉首尾空白。
- 过滤太短的文本。

先不要做复杂规则。第一版只要让文本干净可读。

验收命令：

```powershell
conda run -n reading-agent python -c "from app.ingestion.normalize import normalize_whitespace; print(normalize_whitespace('  hello    world  '))"
```

期望输出：

```text
hello world
```

### 4. `app/ingestion/load_epub.py`

这个文件负责把一个 EPUB 变成很多 `BookParagraph`。

建议先写 4 个函数：

```text
make_book_id(path: str) -> str
get_metadata(book, fallback_title: str) -> tuple[str, str]
extract_paragraphs_from_html(html: bytes | str) -> tuple[str, list[str]]
load_epub(path: str) -> list[BookParagraph]
```

函数解释：

- `make_book_id`：根据文件路径生成稳定 ID，可以用 sha1。
- `get_metadata`：从 EPUB 里读取标题和作者。
- `extract_paragraphs_from_html`：从单个 HTML 文档中提取章节标题和段落。
- `load_epub`：主函数，循环读取 EPUB 内部文档，返回段落列表。

初学者注意：

- 一个 EPUB 不是一个纯文本文件，而是一个 zip 包。
- `ebooklib` 会把 EPUB 内部的 HTML 文件逐个读出来。
- `BeautifulSoup` 是用来从 HTML 中抽取文本的。

最小调试命令：

```powershell
conda run -n reading-agent python -c "from app.ingestion.load_epub import load_epub; ps=load_epub('data/raw/epub/Walden.epub'); print(len(ps)); print(ps[0])"
```

如果没有 `Walden.epub`，换成 `data/raw/epub/` 下任意一本书。

### 5. `app/ingestion/chunking.py`

这个文件把很多段落合并成适合检索的 chunk。

建议先写 2 个函数：

```text
chunk_paragraphs(paragraphs: list[BookParagraph], chunk_size: int = 600, overlap: int = 100) -> list[TextChunk]
_make_chunk(...) -> TextChunk
```

简单算法：

```text
准备一个 current_texts 列表
依次读取段落
把段落 text 加入 current_texts
如果总长度超过 chunk_size：
  生成一个 TextChunk
  保存到 chunks
  从当前文本末尾截取 overlap 字符作为下一个 chunk 的开头
循环结束后，如果 current_texts 还有内容，再生成最后一个 chunk
```

初学者注意：

- chunk 不需要长度完全一样。
- 第一版先按书籍和章节分组，避免一个 chunk 跨两本书。
- `chunk_id` 必须稳定，不要用随机数。

验收命令：

```powershell
conda run -n reading-agent python -c "from app.ingestion.load_epub import load_epub; from app.ingestion.chunking import chunk_paragraphs; ps=load_epub('data/raw/epub/Walden.epub'); cs=chunk_paragraphs(ps); print(len(cs)); print(cs[0].chunk_id); print(cs[0].text[:200])"
```

### 6. `scripts/ingest_books.py`

这是第一个真正的命令脚本。

它应该做 5 件事：

```text
1. 读取配置
2. 扫描 data/raw/epub/*.epub
3. 对每本书调用 load_epub
4. 对所有段落调用 chunk_paragraphs
5. 写出 books.jsonl 和 chunks.jsonl
```

建议先写辅助函数：

```text
write_jsonl(path: str, records: list[BaseModel]) -> None
```

写 JSONL 的关键点：

- 一行一个 JSON。
- 每个 pydantic 对象可以用 `model_dump()` 转成 dict。
- 写文件时使用 `encoding="utf-8"`。
- `ensure_ascii=False`，否则中文会变成转义字符。

验收命令：

```powershell
conda run -n reading-agent python scripts/ingest_books.py
```

然后检查文件是否生成：

```powershell
Get-ChildItem data/processed -Recurse
```

### 7. `scripts/inspect_chunking.py`

这个脚本用于人工检查 chunk 是否可读。

它应该做：

```text
1. 读取 chunks.jsonl
2. 随机选 10-20 条
3. 打印 title、chapter_title、chunk_id、文本前 300 字
```

初学者注意：

- 这个文件不需要复杂逻辑。
- 它的价值是帮你发现 EPUB 解析质量问题。

验收命令：

```powershell
conda run -n reading-agent python scripts/inspect_chunking.py
```

### 8. `app/ingestion/build_index.py`

这个文件负责把 chunks 写入 Chroma。

建议先写 3 个函数：

```text
load_chunks_jsonl(path: str) -> list[TextChunk]
create_vectorstore()
rebuild_index(chunks_path: str) -> int
```

实现逻辑：

```text
读取 chunks.jsonl
创建 OpenAIEmbeddings
创建 Chroma
把每个 chunk 转成 Document
写入 Chroma
返回写入数量
```

初学者注意：

- `Document.page_content` 放 chunk 文本。
- `Document.metadata` 放来源信息，不要放太复杂的对象。
- Chroma 的 `ids` 用 `chunk_id`。

### 9. `scripts/rebuild_index.py`

这个脚本只负责调用 `rebuild_index()`。

它应该：

```text
1. 读取 settings
2. 调用 rebuild_index(settings.CHUNKS_JSONL_PATH)
3. 打印写入了多少 chunks
```

验收命令：

```powershell
conda run -n reading-agent python scripts/rebuild_index.py
```

如果这里失败，优先检查：

- AIClient2API 是否启动。
- `.env` 的 `OPENAI_BASE_URL` 是否正确。
- `EMBEDDING_MODEL` 是否可用。

### 10. `app/retrieval/vector_retriever.py`

这个文件负责查询 Chroma。

建议写一个类：

```text
class VectorRetriever:
    def __init__(self) -> None
    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]
```

实现逻辑：

```text
初始化时创建同一个 Chroma collection
search 时调用 similarity_search_with_score
把返回的 Document + score 转成 RetrievedChunk
```

初学者注意：

- 检索用的 embedding 配置必须和建索引用的一样。
- 如果 collection 名字不一致，会查不到数据。

验收命令：

```powershell
conda run -n reading-agent python -c "from app.retrieval.vector_retriever import VectorRetriever; r=VectorRetriever(); print(r.search('孤独', 3))"
```

### 11. `app/agent/citation_builder.py`

这个文件不要调用模型，只处理引用。

建议写 2 个函数：

```text
build_context(retrieved: list[RetrievedChunk]) -> str
build_citations(retrieved: list[RetrievedChunk]) -> list[str]
```

上下文格式建议：

```text
[1]
书名：...
作者：...
章节：...
chunk_id：...
正文：...
```

引用格式建议：

```text
[1]《书名》/ 作者 / 章节 / chunk_id
```

初学者注意：

- 编号 `[1]`、`[2]` 应该由程序生成。
- 不要让模型自己决定有哪些引用。

### 12. `app/agent/answer_generator.py`

这个文件调用 chat model。

建议写一个函数：

```text
generate_answer(question: str, retrieved: list[RetrievedChunk]) -> AnswerWithCitations
```

实现逻辑：

```text
如果 retrieved 为空：
  直接返回“当前书库证据不足”
否则：
  用 citation_builder 生成 context 和 citations
  读取 prompt
  调用 ChatOpenAI
  返回 AnswerWithCitations
```

初学者注意：

- prompt 里必须明确说“只能使用给定上下文”。
- 不要把整本书塞给模型，只塞 top-k chunks。
- 模型回答完后，引用列表仍然使用程序生成的 `citations`。

### 13. `app/prompts/answer_with_citations.md`

这个文件写给模型看。

建议内容包含：

```text
你是一个阅读记忆助手。
只能使用下面提供的上下文回答问题。
如果上下文不足，请明确说“当前书库证据不足”。
回答中必须使用 [1]、[2] 这样的编号引用。
不要编造书名、作者、章节或页码。
```

### 14. `scripts/run_cli.py`

这是最终入口。

它应该做：

```text
1. 打印欢迎语
2. 循环读取用户输入
3. 输入 /exit 时退出
4. 调用 VectorRetriever.search
5. 调用 generate_answer
6. 打印答案
7. 打印引用
```

伪代码：

```text
retriever = VectorRetriever()
while True:
    question = input("> ")
    if question == "/exit":
        break
    retrieved = retriever.search(question)
    result = generate_answer(question, retrieved)
    print(result.answer)
    print("引用：")
    for c in result.citations:
        print(c)
```

验收命令：

```powershell
conda run -n reading-agent python scripts/run_cli.py
```

### 15. 测试文件怎么写

先写简单测试，不要一开始追求覆盖所有情况。

#### `tests/test_chunking.py`

测试目标：

- 输入几段假文本。
- 调用 `chunk_paragraphs()`。
- 确认返回不为空。
- 确认每个 chunk 有 `chunk_id` 和 `text`。

#### `tests/test_citations.py`

测试目标：

- 构造两个假的 `RetrievedChunk`。
- 调用 `build_citations()`。
- 确认输出里有书名、章节和 chunk_id。

#### `tests/test_retrieval.py`

第一阶段可以先写成轻量测试：

- 测试 `VectorRetriever` 可以被导入。
- 真正依赖 Chroma 和 embedding 的测试后面再加。

原因：

- 检索测试依赖外部模型服务，不适合作为最早期的单元测试。

## 初学者每次写代码后的固定检查

每改完一个文件，先运行：

```powershell
conda run -n reading-agent python -m py_compile 路径\到\文件.py
```

例如：

```powershell
conda run -n reading-agent python -m py_compile app/models/schemas.py
```

然后再运行对应的导入测试：

```powershell
conda run -n reading-agent python -c "from app.models.schemas import TextChunk; print('ok')"
```

最后运行 pytest：

```powershell
conda run -n reading-agent pytest
```

如果报错，优先看最下面几行：

- `SyntaxError`：语法写错，通常是括号、冒号、缩进。
- `ModuleNotFoundError`：导入路径或包名错。
- `ValidationError`：pydantic 字段缺失或类型不对。
- `FileNotFoundError`：路径错或文件还没生成。

## 不建议初学者一开始做的写法

- 不要在一个函数里写 200 行。
- 不要到处传裸 dict，优先用 `schemas.py` 里的模型。
- 不要把 API key 写进代码。
- 不要一边写 EPUB 解析，一边写 Chroma，一边写 CLI。
- 不要先优化 prompt，先确认检索出来的 chunk 是对的。
- 不要提交 `data/`、`.env`、Chroma 索引。
