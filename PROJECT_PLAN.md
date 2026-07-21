# 阅读记忆助手项目计划

## 项目目标

构建一个以个人藏书为知识库的阅读记忆助手。助手需要理解用户输入，区分不同类型的请求，检索相关书籍片段，自然地回答问题，并提供可靠引用。

## 推荐技术栈

- Python 3.12
- LangChain，用于连接 LLM、embedding、检索器和向量库
- 后期使用 LangGraph 构建显式 Agent 工作流
- Chroma 作为第一阶段向量数据库
- 通过 AIClient2API 本地接入 ChatGPT/Codex，用于对话生成
- OpenAI 兼容 embedding 服务，用于向量化文本
- EbookLib + BeautifulSoup，用于 EPUB 解析
- 后期可使用 FastAPI 或 Streamlit 构建 UI
- pytest 用于测试

## 第一阶段：MVP RAG 管线

目标：构建最小可用版本。用户可以在 CLI 中提问，系统从少量书籍中检索相关片段，并返回带引用的回答。

范围：

- 使用 Chroma 作为向量数据库。
- 暂不加入长期记忆。
- 暂不加入复杂 Agent 循环。

任务：

4. 实现 EPUB 加载器：
   - `load_epub.py`
5. 将 EPUB 解析结果转换为统一 JSONL 记录。
6. 实现文本切分：
   - 每个 chunk 约 300-800 个中文字符
   - overlap 约 50-150 个字符
   - 保留书名、作者、章节、段落索引等来源信息
7. 基于 chunks 构建向量索引。
8. 实现基础向量检索。
9. 实现带引用的答案生成。
10. 实现 `scripts/run_cli.py`。

完成标准：

- `python scripts/ingest_books.py` 可以解析 EPUB 并生成 chunks。
- `python scripts/rebuild_index.py` 可以构建 Chroma 向量索引。
- `python scripts/run_cli.py` 可以接受用户输入并返回回答。
- 每条回答中的引用都必须来自检索到的 chunk metadata。
- 随机检查 20 个 chunks，文本应可读，来源应可追踪。

关键学习目标：

- 理解从原始书籍文件到结构化记录的数据流。
- 理解 chunk 质量为什么会直接影响检索质量。
- 学会如何把检索上下文传入 LLM prompt。

## 第二阶段：意图路由与更好的检索

预计时间：2-3 周

目标：处理不同类型的用户输入，而不是假设每个问题都只是情绪表达。

支持的输入类型：

- 情绪表达
- 场景描述
- 直接书籍问题
- 指定书籍查询
- 作者观点问题
- 阅读推荐
- 跨书比较

任务：

1. 在 `models/schemas.py` 中设计意图 schema。
2. 实现 `intent_analyzer.py`。
3. 支持多标签意图分析。
4. 提取用户明确提到的书籍、作者、主题、情绪和需求。
5. 实现 `query_planner.py`。
6. 为复杂输入生成多个检索 query。
7. 当用户指定书籍或作者时，添加书籍/作者过滤条件。
8. 添加关键词检索或 BM25。
9. 实现混合检索：
   - 向量检索
   - 关键词检索
   - 合并并去重结果
10. 如果检索质量仍不够，再加入 reranking。

完成标准：

- 具体问题可以被直接回答，不会被强行当作情绪问题分析。
- 情绪类输入可以被转换为多个有用的检索 query。
- 指定书籍问题只在相关书籍中检索。
- 搜索结果相关性明显优于第一阶段。
- 检索输出可调试：可以打印 queries、filters、scores 和选中的 chunks。

关键学习目标：

- 理解意图路由。
- 理解语义检索和关键词检索的差异。
- 学会检查检索失败原因，而不是只修改 prompt。

## 第三阶段：基于 LangGraph 的 Agent 工作流

预计时间：2-3 周

目标：将固定管线改造成显式图工作流。系统需要根据用户输入和中间结果决定下一步路径。

建议图节点：

```text
analyze_intent
plan_retrieval
retrieve_books
rerank_results
decide_answer_strategy
generate_answer
verify_citations
```

可能流程：

```text
用户输入
  -> analyze_intent
  -> plan_retrieval
  -> retrieve_books
  -> rerank_results
  -> decide_answer_strategy
  -> generate_answer
  -> verify_citations
  -> 最终回答
```

任务：

1. 将 pipeline 状态迁移到结构化 state object。
2. 逐个实现 LangGraph 节点。
3. 添加条件路由：
   - 不需要检索时直接回答
   - 用户指定书籍时执行书籍过滤检索
   - 情绪或场景类输入执行多 query 检索
   - 用户请求过于模糊时追问
4. 添加引用校验。
5. 如果引用无效，则重新生成，或返回证据不足的回答。
6. 为每个节点添加日志。

完成标准：

- 每个图节点都可以独立测试。
- 完整图流程至少能处理 5 类输入。
- 引用校验可以发现编造来源或缺失来源。
- 调试时系统可以说明自己选择了哪条路径。

关键学习目标：

- 理解 Agent 是受控工作流，不是魔法式自主性。
- 理解 state 如何在 Agent 图中流动。
- 学会在 LLM 灵活性和工程约束之间取得平衡。

## 第四阶段：记忆与个性化

预计时间：1-2 周

目标：加入受控长期记忆，而不是盲目保存所有对话。

记忆类型：

- 用户阅读偏好
- 喜欢的书籍或作者
- 反复出现的主题
- 有用的历史引用
- 用户明确批准保存的个人笔记

任务：

1. 设计 memory schema。
2. 实现 `user_profile.py`。
3. 实现 `conversation_memory.py`。
4. 添加明确保存机制：
   - 只有用户要求时保存
   - 或只保存低风险偏好数据
5. 回答前检索相关记忆。
6. 添加查看和删除记忆的命令。

完成标准：

- 助手可以在推荐中使用已知阅读偏好。
- 用户可以查看已保存记忆。
- 用户可以删除已保存记忆。
- 敏感信息不会被静默保存。

关键学习目标：

- 理解模型上下文、外部知识库和用户记忆的区别。
- 理解记忆如何影响回答质量和隐私风险。

## 第五阶段：产品化、UI 与评估

预计时间：3-6 周

目标：让项目变得可用、可衡量、可交接。

任务：

1. 添加简单 UI：
   - 最快路径：Streamlit
   - 全栈练习：FastAPI + Next.js
2. 添加书籍上传和入库控制。
3. 在 UI 中支持展开引用。
4. 添加聊天历史。
5. 构建 30-100 条测试 prompt 作为评估集。
6. 跟踪指标：
   - 检索命中率
   - 引用正确性
   - 回答有用性
   - 幻觉引用
   - 延迟
   - token 成本
7. 编写项目文档。
8. 为 chunking、retrieval 和 citation handling 添加测试。

完成标准：

- 用户可以上传书籍并重建索引。
- 用户可以在 UI 中与助手聊天。
- 引用可以展开并显示原文。
- 评估 prompts 可以重复运行。
- 另一位开发者仅通过 README 就能理解项目。

关键学习目标：

- 学会将原型转化为可用应用。
- 学会用指标评估 AI 系统，而不是只靠主观感觉。
- 学会记录架构和信息流。

## 推荐里程碑

适合具备 Python 基础的人：

```text
第 1 周：项目骨架、EPUB 加载器、统一 JSONL
第 2 周：chunking、索引构建、基础检索
第 3 周：CLI 回答生成与引用
第 4 周：意图路由与多 query 检索
第 5 周：混合检索与 reranking
第 6 周：LangGraph 工作流
第 7 周：记忆与个性化
第 8 周以后：UI、评估、文档
```

## 最先实现的文件

从这些文件开始：

```text
app/ingestion/load_epub.py
app/ingestion/chunking.py
app/ingestion/build_index.py
app/retrieval/vector_retriever.py
scripts/ingest_books.py
scripts/rebuild_index.py
scripts/run_cli.py
```

不要一开始就做 Web UI。不要一开始就训练模型。不要一开始就构建复杂自主 Agent。

先让这条核心链路工作：

```text
书籍文件 -> 解析文本 -> chunks -> 检索 -> 带引用回答
```

这是项目的核心。
