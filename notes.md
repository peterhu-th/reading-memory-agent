# 第一阶段剩余文件编写指南

本文只覆盖尚未完成的第一阶段文件。已完成的 `app/models/schemas.py` 和 `app/config.py` 不再展开。

当前目标是把这条链路跑通：

```text
data/raw/epub/*.epub
  -> app/ingestion/load_epub.py
  -> app/ingestion/chunking.py
  -> scripts/ingest_books.py
  -> data/processed/chunks_jsonl/chunks.jsonl
  -> scripts/rebuild_index.py
  -> app/retrieval/vector_retriever.py
  -> scripts/run_cli.py
```

## 3. `app/ingestion/chunking.py`

### 这个文件做什么

这个文件把很多段落合并成 chunk。

为什么要合并：

- 一个段落可能太短。
- embedding 需要相对完整的语义片段。
- LLM 回答需要上下文。

### 建议写哪些 import

```python
from collections import defaultdict

from app.models.schemas import BookParagraph, TextChunk
```

### 函数 1：`group_paragraphs`

函数签名：

```python
def group_paragraphs(paragraphs: list[BookParagraph]) -> dict[tuple[str, int], list[BookParagraph]]:
```

作用：

- 按“书 + 章节”分组。
- 避免一个 chunk 跨书或跨章节。

key 用：

```python
(paragraph.book_id, paragraph.chapter_index)
```

### 函数 2：`make_chunk`

函数签名：

```python
def make_chunk(
    paragraphs: list[BookParagraph],
    chunk_index: int,
    text: str,
) -> TextChunk:
```

作用：

- 从一组段落和合并后的文本创建一个 `TextChunk`。

来源信息从第一段和最后一段取：

```text
first = paragraphs[0]
last = paragraphs[-1]
start_paragraph_index = first.paragraph_index
end_paragraph_index = last.paragraph_index
```

chunk_id 建议：

```text
book_id:chapter_index:chunk_index
```

### 函数 3：`chunk_chapter`

函数签名：

```python
def chunk_chapter(
    paragraphs: list[BookParagraph],
    chunk_size: int = 600,
    overlap: int = 100,
) -> list[TextChunk]:
```

作用：

- 把同一章节的段落切成多个 chunk。

第一版简单算法：

```text
current_paragraphs = []
current_text = ""
chunks = []

for paragraph in paragraphs:
    如果 current_text 加上新段落还没超过 chunk_size：
        加进去
    否则：
        把 current_text 保存为 chunk
        新开一个 current_text

循环结束后保存最后一个 chunk
```

关于 overlap：

初学者第一版可以先不做复杂 overlap，只保留函数参数。等基础 chunking 跑通后，再加 overlap。

如果要加 overlap，建议先用字符 overlap：

```text
上一个 chunk 的最后 overlap 个字符
作为下一个 chunk 的开头
```

但注意：overlap 文本没有准确 paragraph_index，所以第一版可以先不启用 overlap。

### 函数 4：`chunk_paragraphs`

函数签名：

```python
def chunk_paragraphs(
    paragraphs: list[BookParagraph],
    chunk_size: int = 600,
    overlap: int = 100,
) -> list[TextChunk]:
```

作用：

- 对外主函数。
- 先分组。
- 再对每个章节调用 `chunk_chapter`。
- 返回全部 chunks。

### 验收命令

```powershell
conda run -n reading-agent python -m py_compile app/ingestion/chunking.py
conda run -n reading-agent python -c "from app.ingestion.load_epub import load_epub; from app.ingestion.chunking import chunk_paragraphs; ps=load_epub('data/raw/epub/Walden.epub'); cs=chunk_paragraphs(ps); print(len(cs)); print(cs[0].chunk_id); print(cs[0].text[:200])"
```

合格标准：

- chunks 数量大于 0。
- `chunk_id` 类似 `xxxx:0:0`。
- chunk 文本可读。

## 4. `scripts/ingest_books.py`

### 这个文件做什么

这是“入库前处理”的命令脚本。

它负责：

```text
扫描 EPUB -> load_epub -> chunk_paragraphs -> 写 books.jsonl 和 chunks.jsonl
```

### 建议写哪些 import

```python
import json
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings
from app.ingestion.chunking import chunk_paragraphs
from app.ingestion.load_epub import load_epub
```

### 函数 1：`write_jsonl`

函数签名：

```python
def write_jsonl(path: str, records: list[BaseModel]) -> None:
```

作用：

- 把 pydantic 对象写成 JSONL。

核心逻辑：

```text
创建父目录
打开文件，encoding="utf-8"
循环 records
每个 record.model_dump()
json.dumps(..., ensure_ascii=False)
一行写一个
```

### 函数 2：`main`

函数签名：

```python
def main() -> None:
```

流程：

```text
settings = get_settings()
raw_dir = Path(settings.RAW_EPUB_DIR)
epub_paths = sorted(raw_dir.glob("*.epub"))

all_paragraphs = []
for epub_path in epub_paths:
    paragraphs = load_epub(epub_path)
    all_paragraphs.extend(paragraphs)

chunks = chunk_paragraphs(all_paragraphs)
write_jsonl(settings.BOOKS_JSONL_PATH, all_paragraphs)
write_jsonl(settings.CHUNKS_JSONL_PATH, chunks)
print 处理了多少本书、多少段落、多少 chunks
```

文件末尾写：

```python
if __name__ == "__main__":
    main()
```

### 验收命令

```powershell
conda run -n reading-agent python -m py_compile scripts/ingest_books.py
conda run -n reading-agent python scripts/ingest_books.py
```

然后检查：

```powershell
Get-ChildItem data/processed -Recurse
```

合格标准：

- 生成 `books.jsonl`
- 生成 `chunks.jsonl`
- 控制台打印书籍数、段落数、chunk 数

## 5. `scripts/inspect_chunking.py`

### 这个文件做什么

这个脚本用来人工抽查 chunk 质量。

它不参与主流程，但很重要。RAG 质量差，很多时候不是模型问题，而是 chunk 很乱。

### 建议写哪些 import

```python
import json
import random
from pathlib import Path

from app.config import get_settings
from app.models.schemas import TextChunk
```

### 函数 1：`load_jsonl`

函数签名：

```python
def load_jsonl(path: str) -> list[TextChunk]:
```

逻辑：

```text
逐行读取 chunks.jsonl
json.loads(line)
TextChunk(**data)
加入列表
```

### 函数 2：`main`

流程：

```text
读取 chunks
如果为空，打印提示
随机抽 10 条
打印 chunk_id/title/chapter_title/text[:500]
```

### 验收命令

```powershell
conda run -n reading-agent python -m py_compile scripts/inspect_chunking.py
conda run -n reading-agent python scripts/inspect_chunking.py
```

合格标准：

- 能看到随机 chunk。
- 文本不是乱码。
- 不是目录、版权页、空内容占多数。

## 6. `app/ingestion/build_index.py`

### 这个文件做什么

把 `chunks.jsonl` 写入 Chroma 向量数据库。

### 建议写哪些 import

```python
import json
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from app.config import get_settings
from app.models.schemas import TextChunk
```

注意：

如果 `langchain_core.documents` 导入失败，说明间接依赖版本有变化。先运行：

```powershell
conda run -n reading-agent python -c "from langchain_core.documents import Document; print('ok')"
```

### 函数 1：`load_chunks`

函数签名：

```python
def load_chunks(path: str) -> list[TextChunk]:
```

作用：

- 读取 `chunks.jsonl`。
- 转成 `TextChunk` 对象。

### 函数 2：`make_embeddings`

函数签名：

```python
def make_embeddings() -> OpenAIEmbeddings:
```

逻辑：

```text
settings = get_settings()
return OpenAIEmbeddings(
    model=settings.EMBEDDING_MODEL,
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
)
```

注意：

有些版本参数名可能是 `openai_api_key` / `openai_api_base`。如果报参数错误，再按报错调整。

### 函数 3：`chunk_to_document`

函数签名：

```python
def chunk_to_document(chunk: TextChunk) -> Document:
```

逻辑：

```text
metadata = chunk.model_dump()
从 metadata 删除 text
Document(page_content=chunk.text, metadata=metadata)
```

为什么删除 `text`：

- `page_content` 已经保存正文。
- metadata 只放来源信息。
- 避免重复存一份大文本。

### 函数 4：`rebuild_index`

函数签名：

```python
def rebuild_index(chunks_path: str | None = None) -> int:
```

流程：

```text
settings = get_settings()
读取 chunks
创建 embeddings
创建 documents
ids = [chunk.chunk_id for chunk in chunks]
创建 Chroma collection
写入 documents 和 ids
返回 len(chunks)
```

Chroma 创建建议：

```python
vectorstore = Chroma(
    collection_name=settings.CHROMA_COLLECTION,
    embedding_function=embeddings,
    persist_directory=settings.VECTOR_DB_PATH,
)
```

重建索引注意：

- 第一版可以先直接 add。
- 如果重复运行导致 ID 冲突，再加清空 collection 的逻辑。
- 不要手动删除整个 `data/`。

## 7. `scripts/rebuild_index.py`

### 这个文件做什么

命令入口，调用 `app/ingestion/build_index.py`。

### 建议写哪些 import

```python
from app.ingestion.build_index import rebuild_index
```

### main

```python
def main() -> None:
    count = rebuild_index()
    print(f"Indexed {count} chunks")


if __name__ == "__main__":
    main()
```

### 验收命令

```powershell
conda run -n reading-agent python -m py_compile app/ingestion/build_index.py scripts/rebuild_index.py
conda run -n reading-agent python scripts/rebuild_index.py
```

合格标准：

- 控制台打印 indexed chunks 数量。
- `data/index/chroma` 下出现 Chroma 文件。

如果失败，先判断是哪类错误：

```text
FileNotFoundError: chunks.jsonl 还没生成
Connection error: AIClient2API 没启动
Authentication error: OPENAI_API_KEY/通路配置不对
BadRequest: EMBEDDING_MODEL 模型名不支持
```

## 8. `app/retrieval/vector_retriever.py`

### 这个文件做什么

从 Chroma 中按问题检索最相关 chunks。

### 建议写哪些 import

```python
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from app.config import get_settings
from app.models.schemas import RetrievedChunk, TextChunk
```

### 类：`VectorRetriever`

建议写成类，因为初始化 Chroma 有成本，后面 CLI 可以复用。

```python
class VectorRetriever:
    def __init__(self) -> None:
        ...

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        ...
```

### `__init__`

职责：

```text
读取 settings
创建 embeddings
创建 Chroma vectorstore
```

注意 collection name、persist directory、embedding model 必须和建索引时一致。

### `search`

流程：

```text
如果 query 为空，返回 []
调用 similarity_search_with_score(query, k=top_k)
遍历 Document 和 score
用 Document.metadata + page_content 还原 TextChunk
包装成 RetrievedChunk
返回列表
```

还原 TextChunk 时：

```text
data = dict(doc.metadata)
data["text"] = doc.page_content
chunk = TextChunk(**data)
```

### 验收命令

```powershell
conda run -n reading-agent python -m py_compile app/retrieval/vector_retriever.py
conda run -n reading-agent python -c "from app.retrieval.vector_retriever import VectorRetriever; r=VectorRetriever(); xs=r.search('孤独', 3); print(len(xs)); print(xs[0].chunk.title if xs else 'empty')"
```

## 9. `app/agent/citation_builder.py`

### 这个文件做什么

把检索结果转换成 prompt 上下文和引用列表。

它不调用模型。

### 建议写哪些 import

```python
from app.models.schemas import RetrievedChunk
```

### 函数 1：`build_context`

函数签名：

```python
def build_context(retrieved: list[RetrievedChunk]) -> str:
```

输出格式建议：

```text
[1]
书名：Walden
作者：Henry David Thoreau
章节：Economy
chunk_id：abc:0:0
正文：
...
```

每个 chunk 之间用空行隔开。

### 函数 2：`build_citations`

函数签名：

```python
def build_citations(retrieved: list[RetrievedChunk]) -> list[str]:
```

输出格式：

```text
[1]《Walden》/ Henry David Thoreau / Economy / abc:0:0
```

如果 author 或 chapter_title 为空，可以用：

```text
未知作者
未知章节
```

### 验收命令

先写测试更方便验收，见后面的 `tests/test_citations.py`。

## 10. `app/prompts/answer_with_citations.md`

### 这个文件做什么

这是发给 chat model 的指令模板。

建议内容：

```text
你是一个阅读记忆助手。

你只能根据用户问题和给定上下文回答。
如果上下文不足，请回答“当前书库证据不足”，不要编造。

要求：
1. 回答必须简洁、自然。
2. 涉及书籍内容的判断必须带引用编号，例如 [1]。
3. 引用编号只能来自上下文中出现的编号。
4. 不要编造书名、作者、章节、页码或 chunk_id。

用户问题：
{question}

上下文：
{context}
```

注意：

- `{question}` 和 `{context}` 是后面代码要替换的占位符。
- 不要在 prompt 里写真实 API key。

## 11. `app/agent/answer_generator.py`

### 这个文件做什么

调用 chat model，生成最终回答。

### 建议写哪些 import

```python
from pathlib import Path

from langchain_openai import ChatOpenAI

from app.agent.citation_builder import build_citations, build_context
from app.config import get_settings
from app.models.schemas import AnswerWithCitations, RetrievedChunk
```

### 函数 1：`load_prompt`

函数签名：

```python
def load_prompt() -> str:
```

读取：

```text
app/prompts/answer_with_citations.md
```

建议用：

```python
Path("app/prompts/answer_with_citations.md").read_text(encoding="utf-8")
```

### 函数 2：`generate_answer`

函数签名：

```python
def generate_answer(question: str, retrieved: list[RetrievedChunk]) -> AnswerWithCitations:
```

流程：

```text
如果 retrieved 为空：
    返回 AnswerWithCitations(answer="当前书库证据不足。", citations=[])

settings = get_settings()
context = build_context(retrieved)
citations = build_citations(retrieved)
prompt = load_prompt().format(question=question, context=context)

llm = ChatOpenAI(
    model=settings.CHAT_MODEL,
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
)
response = llm.invoke(prompt)
return AnswerWithCitations(answer=response.content, citations=citations)
```

注意：

- 第一版引用列表由程序生成，不完全依赖模型。
- 如果模型回答里没带 `[1]`，后面再加校验。

### 验收方式

先保证 AIClient2API 已启动。

```powershell
conda run -n reading-agent python -m py_compile app/agent/answer_generator.py
```

完整调用等 `VectorRetriever` 完成后通过 CLI 验收。

## 12. `scripts/run_cli.py`

### 这个文件做什么

最终命令行入口。

### 建议写哪些 import

```python
from app.agent.answer_generator import generate_answer
from app.retrieval.vector_retriever import VectorRetriever
```

### main

流程：

```text
打印欢迎语
创建 VectorRetriever
debug = False
while True:
    question = input("> ").strip()
    如果为空，continue
    如果是 /exit，break
    如果是 /debug on，debug = True
    如果是 /debug off，debug = False
    retrieved = retriever.search(question, top_k=5)
    如果 debug，打印检索到的 title/chapter/score/chunk_id
    result = generate_answer(question, retrieved)
    打印 result.answer
    打印 result.citations
```

### 验收命令

```powershell
conda run -n reading-agent python -m py_compile scripts/run_cli.py
conda run -n reading-agent python scripts/run_cli.py
```

测试输入：

```text
/debug on
孤独是什么？
/exit
```

## 13. `tests/test_chunking.py`

### 这个文件测什么

测试 chunking 不依赖 EPUB 文件，用手写假数据即可。

### 建议 import

```python
from app.ingestion.chunking import chunk_paragraphs
from app.models.schemas import BookParagraph
```

### 建议写辅助函数

```python
def make_paragraph(index: int, text: str) -> BookParagraph:
```

返回固定书名、作者、章节，只变化 index 和 text。

### 测试 1：空输入

```python
def test_chunk_paragraphs_empty():
    assert chunk_paragraphs([]) == []
```

### 测试 2：能生成 chunk

```python
def test_chunk_paragraphs_creates_chunks():
    paragraphs = [make_paragraph(i, "text " * 50) for i in range(5)]
    chunks = chunk_paragraphs(paragraphs, chunk_size=100)
    assert len(chunks) > 0
    assert chunks[0].chunk_id
    assert chunks[0].text
```

### 验收命令

```powershell
conda run -n reading-agent pytest tests/test_chunking.py
```

## 14. `tests/test_citations.py`

### 这个文件测什么

测试引用构造，不调用模型。

### 建议 import

```python
from app.agent.citation_builder import build_citations, build_context
from app.models.schemas import RetrievedChunk, TextChunk
```

### 测试内容

构造一个假的 `TextChunk`：

```text
title = "Test Book"
author = "Test Author"
chapter_title = "Chapter 1"
chunk_id = "book1:0:0"
```

再包装成 `RetrievedChunk`。

断言：

```text
build_citations 输出包含 Test Book
build_citations 输出包含 book1:0:0
build_context 输出包含 正文 text
build_context 输出包含 [1]
```

### 验收命令

```powershell
conda run -n reading-agent pytest tests/test_citations.py
```

## 15. `tests/test_retrieval.py`

### 这个文件第一版怎么写

检索依赖 Chroma、embedding、AIClient2API，不适合一开始写成强单元测试。

第一版只做导入测试：

```python
def test_vector_retriever_importable():
    from app.retrieval.vector_retriever import VectorRetriever

    assert VectorRetriever is not None
```

后面等索引稳定后，再加集成测试。

### 验收命令

```powershell
conda run -n reading-agent pytest tests/test_retrieval.py
```

## 16. 完整运行顺序

当所有文件写完后，按这个顺序跑：

```powershell
conda run -n reading-agent python scripts/ingest_books.py
conda run -n reading-agent python scripts/inspect_chunking.py
conda run -n reading-agent python scripts/rebuild_index.py
conda run -n reading-agent python scripts/run_cli.py
```

最后跑测试：

```powershell
conda run -n reading-agent pytest
```

## 17. 遇到报错先看这几类

### `SyntaxError`

语法错误。

重点检查：

- 冒号 `:`
- 缩进
- 括号是否成对
- 字符串引号是否闭合

### `ModuleNotFoundError`

导入失败。

重点检查：

- 文件名是否拼错。
- 是否从项目根目录运行命令。
- `pyproject.toml` 里是否有 `pythonpath = ["."]`。

### `ValidationError`

Pydantic 数据校验失败。

重点检查：

- 是否少传字段。
- 字段是否为空。
- index 是否小于 0。

### `FileNotFoundError`

文件不存在。

重点检查：

- EPUB 是否在 `data/raw/epub/`。
- 是否已经运行 `scripts/ingest_books.py` 生成 JSONL。

### API 或连接错误

通常出现在 embedding 或 chat 调用阶段。

重点检查：

- AIClient2API 是否启动。
- `.env` 的 `OPENAI_BASE_URL` 是否正确。
- `CHAT_MODEL` 和 `EMBEDDING_MODEL` 是否可用。

## 18. GitHub 提交前检查

确认不会提交本地数据和密钥：

```powershell
git status --short --ignored
```

应该看到：

```text
!! .env
!! data/
```

这表示它们被忽略了。

确认 `.env.example` 会提交：

```powershell
git status --short .env.example
```

应该看到：

```text
?? .env.example
```

或者如果已经 add：

```text
A  .env.example
```
