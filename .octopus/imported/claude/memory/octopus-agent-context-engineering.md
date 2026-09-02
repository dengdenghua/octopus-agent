---
name: octopus-agent-context-engineering
description: 上下文工程栈实情 + composer 不喂代码库的缺口 + wiki 自动检索接线
metadata: 
  node_type: memory
  type: project
  originSessionId: 8aca05ae-c5bd-44e7-a9e0-c11f0ec07fb5
---

**追 Qoder 上下文(commit `37eefb6`)时摸清的栈**:

- **ContextComposer**(`runtime/memory/hemolymph/composer.py`,`.compose(task_info)`)只填 **3 桶:system / suckers / memory**——**完全没有代码库上下文**。`QuotaAllocation`(`platform/models/context.py`)是 4 桶 frozen 模型(system/suckers/memory/history,sum=1.0 校验);`_compress_to_budget` 末尾重组**只保留这 4 个桶名**,塞 `bucket="codebase"` 会被静默丢——所以**别从 composer 桶系统加代码库上下文**。
- **llm_planner 才是注入点**:`plan()` 在 compose 前把 `kg_section`(`_render_kg_section`,已有 KG 注入先例)、`recipe_warning` 追加进 `base_prompt`(=system_prompt)。llm_planner 下游只取 `bucket=="system"` 和 `"suckers"` 进 prompt(memory/history 桶 llm_planner 没用)。
- **WikiCompiler**(`memory/diagnostics/wiki_compiler.py`)编的是**代理活动史 wiki**(从 journal/reflect),**不是源码 wiki**。真源码 wiki 是 **`docs/auto/`**(由 `sensing/gateway/wiki_generic.py` 生成:`index.json`{tree:[{title,path}]} + 分主题 .md 页,overview/tech-stack/backend/skills-graph/hooks/governance)。
- **KnowledgeGraph**(`memory/knowledge_graph/kg.py`)是通用三元组库,非代码符号图。代码符号能力在 `code_intelligence_skills.py`(`code_find_symbol`/`code_dependency_graph`/`code_search`,AST)——但**没接进 composer/planner 上下文**,agent 得手动调。

**我做的(37eefb6)**:`hemolymph/repo_context.py::retrieve_repo_context(query)`——读项目 `docs/auto` wiki(默认 `cwd/docs/auto`,缓存 by index.json mtime),按 goal 关键词 overlap 给页打分取 top≤2,渲染成 prompt 段;`llm_planner._render_codebase_section(intent)` 镜像 `_render_kg_section` 追加进 base_prompt。**自门控**:无 wiki/无 overlap/出错→""。env `OCTOPUS_CODEBASE_CONTEXT=0` 关。默认开。实测中文 goal 真命中 docs/auto 页。**升级(commit `e020ed9`)**:关键词 overlap → **BM25 + 标识符分词**(`_tokenize` 拆 camelCase/snake/缩写:ToolEngine→{tool,engine},CJK 整段留;双语标题 EN/中 任一命中)。BM25 长度归一化修掉实测偏置(同查询从命中长页"All Skills"改为命中"Tool Engine · 执行器")。index(tf/df/avgdl)缓存 by mtime。

**embedding 路径双重休眠(已核)**:`code_intelligence_skills.py:692` 有 `embedder.encode()`(sentence_transformers)+ `index_router.py` 有向量 DB schema,但 **sentence_transformers/torch/numpy 全没装 + 索引 DB 从没建**。装 torch ~2GB 破坏精简基线=用户决定;或走 provider 的 `/v1/embeddings`(httpx 已装、纯 Python cosine)但加规划热路径网络延迟 + 依赖 provider 支持。**纯零依赖天花板=BM25,已到**。真语义桥接(planner→cerebrum 零共享 token)需 embedding。

**已做(commit `b42a122`,源码块检索——用户在岔路选"零依赖")**:`hemolymph/code_index.py::retrieve_code_context(query, root)`——对项目源码建有界 BM25 索引(行窗口 chunk 50 行、**不 AST 解析所以快+语言无关**,复用 repo_context 的 `_bm25`/`_tokenize`),返 top chunk 的 `path:line` 摘录。有界(1200 文件/2500 chunk 上限、剪 noise 目录、>200KB 跳)+ 按 root TTL 120s 缓存(热循环只走一次,本仓首建 ~0.5s)。planner `_render_codebase_section` 现追加 **wiki 摘要 + 真源码块**两段,都 best-effort/自门控/同 `OCTOPUS_CODEBASE_CONTEXT` 闸。实测查 "context composer compose token budget" 直接命中 composer.py:201/:151(ContextComposer 类本身)。**剩余到 Qoder 满分**:仍是真 embedding 语义(零共享词桥接)——岔路另两条(API embeddings via httpx / 本地 torch ~2GB)用户未选,留待。

**本会话大升级(超越上面"零依赖天花板=BM25"的旧结论)** —— 把 grounding 从"开局一注 BM25 行窗"做到接近 RAG 满分:
- **接进 react 聊天**(commit `38658240`):抽 `repo_context.render_codebase_context(goal)` 共享函数(wiki+源码),注进 `react_loop` 的 volatile_parts(code mode)——之前只在 `llm_planner.plan()`,常规聊天根本没用上。
- **语义融合**(`e8b6005b`):`semantic_code_index.search_persisted` 只读复用 work-mode KB 的 `data/code_index.db`(SentenceTransformer 向量),与 BM25 **RRF 文件级融合**;gated 到 cwd 工作区;numpy-free(array 读 float32 + 纯 py cosine)。
- **可配统一嵌入器**(`7455c78d`+`c4ba4813`):`embedding_backend.py` —— `OCTOPUS_EMBED_URL`(OpenAI-兼容/Ollama,零 torch)→ fastembed(ONNX CPU)→ sentence-transformers → None;BUILD(`code_intelligence_skills._get_embedder` 委托它)和 QUERY 共用一个模型。**所以旧记忆的"embedding 双重休眠/装 torch 才行"过时了**:Ollama/fastembed 都是真本地路径。
- **多跳 grounding**(`99084089`):round-0 命中后 `_salient_identifiers` 抽结构化符号(Camel/snake)→ 第二跳 BM25 把它们的定义/使用文件拉进来(标 `(dependency)`);`OCTOPUS_GROUNDING_HOPS=0` 可关。retrieve→follow→retrieve 的确定性那半。
- **AST 切块**(`f74eb971`):`_chunk_file` 用 stdlib `ast` 按函数/类边界切(真实行号、签名完整),大类拆 header+方法,语法错/非 py 回退行窗。替掉定长 50 行窗。
- **到 9 还差的**:真·模型驱动多跳(读→推理→决定下一个读什么,而非盲跟符号)+ 新鲜度(查索引 vs 现读活文件)——这两者本来就有 grep/read 工具覆盖一半,且吃 BYO 模型能力。

相关:[[octopus-agent-multiagent-gap]]、[[octopus-agent-improvement-roadmap]]、[[octopus-family-architecture]]
