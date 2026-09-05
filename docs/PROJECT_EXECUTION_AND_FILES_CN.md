# TestTeller 项目文件职责与运行链路报告

> 本文针对项目学习路径中列出的 10 个文件，说明各自负责什么、接收和产出什么数据、与其他模块如何协作，以及项目如何从输入资料走到测试用例和自动化测试代码。
>
> 说明：本项目的“跑通”分为两个层次。第一层是程序链路跑通，即资料被检索、模型生成文本、文件写入输出目录；第二层是真实测试跑通，即生成的测试在目标应用和测试环境中安装依赖后能执行通过。传统 `automate` 命令仍只生成文件；新增 `agent-run` 命令提供受限执行、失败分析和自动修复闭环。

## 1. 全局结构：两条主业务链路

项目由两个 Agent 组成，它们共用模型管理器和 Chroma 向量数据库：

```text
                       文档 / 本地代码 / Git 仓库
                                  |
                                  v
testteller/main.py -> TestTellerAgent -> UnifiedDocumentParser / CodeLoader
                                  |
                                  v
                      ChromaDBManager（向量化并持久化）
                                  |
          +-----------------------+-----------------------+
          |                                               |
          v                                               v
  generate：生成 Markdown 测试用例               automate：生成 pytest/Jest 等代码
          |                                               |
          v                                               v
  LLMManager + prompts.py                         ApplicationKnowledgeExtractor
          |                                               |
          v                                               v
  用例 Markdown / txt / docx / xlsx               RAGEnhancedTestGenerator -> 输出测试工程
                                                          |
                                                          v
                                           人工或 CI 安装依赖并运行生成的测试
```

### 1.1 测试用例生成链路

1. 运行 `testteller ingest-docs <路径>` 或 `testteller ingest-code <路径或仓库地址>`。
2. `main.py` 创建 `TestTellerAgent`，由它解析文档或读取代码，并写入指定 Chroma collection。
3. 运行 `testteller generate "<测试需求>"`。
4. Agent 用需求作为检索词，从向量库取回相似片段，把“检索上下文 + 当前需求”装入提示词。
5. `LLMManager` 将提示词交给配置好的 Gemini、OpenAI、Claude 或 Llama，返回测试用例文本。
6. CLI 将文本显示在终端，必要时保存成 `.md`、`.txt`、`.docx`、`.xlsx` 或 `.pdf`。

### 1.2 自动化代码生成链路

1. 准备上一步生成的测试用例文件，或自行编写符合格式的 Markdown / Word / PDF / Excel 用例文档。
2. 运行 `testteller automate <用例文件> --language python --framework pytest`。
3. 自动化 CLI 解析用例为 `TestCase` 对象；若通用解析不足，会尝试 Markdown、DOCX、PDF 的兜底解析。
4. `ApplicationKnowledgeExtractor` 从同一个 collection 中找 API、页面选择器、认证方式、数据模型和既有测试写法，形成 `ApplicationContext`。
5. `RAGEnhancedTestGenerator` 把“结构化用例 + 应用上下文 + 已有测试样例 + 框架约束”组成代码生成提示词，调用 LLM 生成分组后的测试文件。
6. 生成器清理 Markdown 代码围栏、补充部分 import / 结构，并额外生成 `requirements.txt`、`conftest.py` 或 `package.json` 等支撑文件。
7. CLI 将文件写到 `--output-dir`。之后需要进入该目录安装依赖并执行对应框架命令，例如 `pytest`；项目主流程不会替用户连接目标系统或判定生成测试全部通过。

## 2. 文件职责总览

| 序号 | 文件 | 所属层 | 核心职责 | 主要产物 |
|---|---|---|---|---|
| 1 | `README.md` | 使用说明 | 定义项目能力、安装、命令与示例 | 人类可读的操作入口 |
| 2 | `testteller/main.py` | 主 CLI / 编排层 | 提供入库、生成、状态、清理、配置命令 | 用例文件或终端结果 |
| 3 | `generator_agent/agent/testteller_agent.py` | 用例生成业务层 | 组织资料入库、RAG 检索、模型生成与反馈回写 | 测试用例文本 / 向量记录 |
| 4 | `core/data_ingestion/unified_document_parser.py` | 文档解析基础层 | 识别文档、抽取元数据、分块、解析用例 | `ParsedDocument` |
| 5 | `core/vector_store/chromadb_manager.py` | 向量基础设施层 | 管理 Chroma collection、写入、检索、清理 | 相似文档与元数据 |
| 6 | `core/llm/llm_manager.py` | 模型适配层 | 根据配置选择模型客户端并统一生成/嵌入接口 | 文本或 embedding |
| 7 | `automator_agent/cli.py` | 自动化 CLI / 编排层 | 将用例文档转成可写出的自动化工程 | 输出目录中的代码文件 |
| 8 | `automator_agent/rag_enhanced_generator.py` | 自动化代码生成层 | 结合 RAG 上下文生成、清理、校验、兜底代码 | 按类别拆分的测试文件 |
| 9 | `automator_agent/application_context.py` | 应用知识发现层 | 从向量库抽取 API、UI、认证、模型、框架信息 | `ApplicationContext` |
| 10 | `automator_agent/parser/markdown_parser.py` | 用例结构化层 | 把 Markdown 用例转为结构化 `TestCase` | `List[TestCase>` |

## 3. 逐文件说明

### 3.1 `README.md`：项目的使用合同与操作导航

**它解决什么问题**

README 不参与 Python 运行，但它定义了使用者应如何配置项目、输入什么资料、执行什么命令以及预期看到什么输出。项目的 `pyproject.toml` 也将它声明为包的说明文档，因此它同时服务于 GitHub/PyPI 展示。

**内容职责**

- 解释 TestTeller 的目标：从需求文档和代码上下文生成测试用例，再进一步生成自动化测试代码。
- 列出支持的模型供应商、文件格式、语言和测试框架。
- 给出环境变量、Docker、安装依赖与 `testteller configure` 的准备步骤。
- 定义用户最常使用的命令：`ingest-docs`、`ingest-code`、`generate`、`automate`、`status`、`clear-data`。
- 通过 `sample-outputs` 的样例让用户理解输入和输出格式。

**它如何接入执行链路**

README 本身不被代码调用；它把使用者引导到 `testteller` 命令。这个命令在 `pyproject.toml` 的 `[project.scripts]` 中映射到 `testteller.main:app_runner`，因此 README 是“人为入口”，`main.py` 才是“程序入口”。

**阅读时应关注的点**

- README 中的“支持”通常表示生成器能输出对应语言或框架的代码结构，不等同于所有项目都能零修改运行。
- 实际效果高度依赖入库资料的质量：接口文档、OpenAPI、已有测试、前端选择器和环境配置越完整，RAG 提供给模型的上下文越可靠。

### 3.2 `testteller/main.py`：主命令行入口和测试用例工作流编排器

**它解决什么问题**

这是普通用户最先真正执行的 Python 文件。它基于 Typer 注册命令，负责参数校验、配置检查、异步任务调度、终端提示、结果输出与资源清理。它不承担复杂解析或模型细节，而是把请求交给 `TestTellerAgent`。

**关键组成**

| 区域 | 作用 |
|---|---|
| `app = typer.Typer(...)` | 创建 CLI 应用对象。 |
| `check_settings` / `check_api_key_configured` | 加载并检查配置，避免未配 API Key 就开始模型调用。 |
| `_get_agent` | 创建带 collection 名称的 Agent，并将初始化错误转换为清晰的 CLI 错误。 |
| `ingest_docs_async` | 调用 Agent 文档入库，等待写库完成并显示 collection 数量。 |
| `ingest_code_async` | 调用 Agent 从本地目录或 Git 仓库读取代码并入库。 |
| `generate_async` | 执行 RAG 用例生成、可选地回写高质量结果、保存输出。 |
| `status_async` / `clear_data_async` | 查询 collection 规模或删除 collection 与临时克隆仓库。 |
| `ingest_docs`、`ingest_code`、`generate` 等装饰器命令 | 将 Typer 命令参数转交给相应 async 函数。 |
| `app_runner` | 打包后的 console script 最终调用的位置。 |

**典型运行过程：`ingest-docs`**

```text
shell: testteller ingest-docs docs/ -c demo
  -> main.ingest_docs(...)
  -> asyncio.run(main.ingest_docs_async(...))
  -> _get_agent("demo")
  -> TestTellerAgent.ingest_documents_from_path(...)
  -> 文档解析、切块、向量写入
  -> get_ingested_data_count()
  -> CLI 打印 collection 中的记录数
```

**典型运行过程：`generate`**

`generate_async` 会先检查 collection 是否为空；为空时仍允许继续，但模型只能依靠通用知识而不是项目资料。生成成功后，若 `ENABLE_TEST_CASE_FEEDBACK=true`，它会调用 `store_generated_test_cases`，将满足最低质量分的结果再次写入向量库，作为后续检索资料。

**边界与注意事项**

- 此文件为了避免 Chroma 遥测和后台线程导致命令悬挂，会设置遥测环境变量、使用 spinner，并在结束时显式清理对象和垃圾回收。
- `clear-data` 是破坏性操作：删除 collection 的同时会清理代码加载器克隆的仓库。
- `main.py` 不直接负责 `automate` 的业务实现；自动化命令逻辑由 `automator_agent/cli.py` 提供，再由主 CLI 注册或调用。

### 3.3 `generator_agent/agent/testteller_agent.py`：RAG 测试用例生成的核心业务对象

**它解决什么问题**

`TestTellerAgent` 是“把资料变成测试用例”的主业务对象。它把文档加载、代码加载、统一解析器、向量库和 LLM 管理器组合为一个面向业务的接口，避免 CLI 直接依赖所有底层实现。

**初始化时创建的依赖**

```text
TestTellerAgent
  |- LLMManager：决定使用哪个模型，以及怎样生成 embedding / 文本
  |- ChromaDBManager：持久化和检索项目知识
  |- DocumentLoader：基础文档读取兜底
  |- CodeLoader：本地目录与 Git 仓库代码读取
  `- UnifiedDocumentParser：增强解析、分块、元数据抽取
```

**主要方法与数据流**

- `ingest_documents_from_path(path, enhanced_parsing, chunk_size)`：判断路径是文件还是目录。
  - 文件走 `_ingest_single_document`；优先 `parse_for_rag`，得到分块和丰富元数据；异常或没有分块时退回 `DocumentLoader`。
  - 目录走 `_ingest_directory`；递归筛选 `.md`、`.txt`、`.pdf`、`.docx`、`.xlsx` 与常见代码格式，并最多 3 个并发任务批量解析。
  - 每个 chunk 配有 `source`、`document_type`、标题、分块序号、词数等 metadata；ID 由路径和 chunk 序号的 SHA-256 生成，减少重复写入。
- `ingest_code_from_source(source_path)`：识别远程 Git 地址或本地路径，调用 `CodeLoader` 收集代码文件，以 `type=code` 元数据写入同一 collection。
- `generate_test_cases(code_context, n_retrieved_docs)`：先以用户需求检索相似内容，再调用 `get_test_case_generation_prompt` 生成供应商适配的提示词，最后交给 `LLMManager.generate_text_async`。
- `store_generated_test_cases(...)`：根据 TODO/FIXME、结构标记、篇幅、步骤数、预期结果等规则计算质量分；只有达到环境变量 `MIN_QUALITY_SCORE_FOR_STORAGE`（默认 0.7）的内容才会回写库中。
- `close()`：关闭向量库，供 CLI 的 `finally` 块释放资源。

**为什么要把生成结果再入库**

这形成了一个轻量“反馈库”：后续生成时，历史高质量用例也可能被检索到。它不是模型训练，也不会改变大模型参数；只是增加 RAG 的可检索上下文。

**风险点**

- 质量分是基于文本规则，不会验证测试用例是否真的覆盖需求或能执行。
- 文档和代码写入同一个 collection，检索时可能混入不同类型的内容；metadata 已记录类型，但当前主生成查询未显式做类型过滤。

### 3.4 `core/data_ingestion/unified_document_parser.py`：统一文档理解、切块和用例提取器

**它解决什么问题**

不同输入文件的读取方式不同，但上层不应为 PDF、Word、Excel、Markdown 分别写一套流程。该文件将它们归一成 `ParsedDocument`，使“入库”和“自动化生成”都能面向统一的数据结构编程。

**核心数据结构**

- `DocumentType`：文档语义类型，例如需求、API 文档、测试用例、技术文档、代码等。
- `ParseMode`：解析目的，主要包括 RAG 入库、自动化生成、内容分析。
- `DocumentMetadata`：文件路径、格式、标题、词数、章节、质量信息等。
- `ParsedDocument`：包含原始文本 `content`、切块 `chunks`、`metadata`、自动化上下文与解析得到的 `test_cases`。

**主要方法与模式差异**

| 方法 | 用途 | 关键输出 |
|---|---|---|
| `parse_document` | 总入口：读取、识别类型、抽取元数据并按模式处理 | `ParsedDocument` |
| `parse_for_rag` | 为语义检索准备文本 | 较均衡的智能 chunks |
| `parse_for_automation` | 为代码生成准备测试用例 | `test_cases` 与自动化上下文 |
| `parse_for_analysis` | 为文档分析准备结构信息 | 标题、列表、代码块、表格等 |
| `batch_parse` | 并发解析多个文件 | `List[ParsedDocument]` |

**RAG 入库时发生什么**

`_process_for_rag` 会调用 `_create_smart_chunks`。该算法优先按章节切分，尽量避免在中间截断语义单元；过长内容再按 chunk 大小细切。这样写入向量库的不是整份大文档，而是更适合检索的片段。

**自动化时发生什么**

`_process_for_automation` 侧重 `_create_automation_chunks` 与 `_extract_automation_context`，并尝试将内容提取成 `TestCase`。由于不同来源格式差异较大，自动化 CLI 后面还保留了 Markdown、DOCX、PDF 的专用兜底解析。

**内容分析能力**

它还能提取标题、列表、代码块、表格、关键术语，并计算复杂度、可读性和文档质量。这些信息主要用于 metadata 和辅助理解，不是严格的 NLP 质量评估模型。

### 3.5 `core/vector_store/chromadb_manager.py`：项目知识库的持久化与检索接口

**它解决什么问题**

RAG 需要在模型生成前从项目资料中找出相关上下文。该文件封装 ChromaDB，屏蔽本地/远程客户端、collection 管理、embedding、重复 ID、异步调用等细节。

**初始化职责**

- 根据 `settings.chromadb` 选择本地 `PersistentClient` 或远程 HTTP 客户端。
- 获取或创建以 collection 名称标识的 Chroma collection。
- 创建 embedding 函数；embedding 的来源由 `LLMManager` 统一提供，因此不同模型供应商对上层透明。

**关键接口**

- `add_documents(documents, metadatas, ids)`：写入文本、metadata 和唯一 ID。写入前进行输入长度校验，并处理 Chroma 元数据仅支持简单类型的限制。
- `query_similar(query_text, n_results)`：按照查询文本的语义相似度取回 documents、metadatas、distances、ids。
- `query_collection(...)`：异步友好包装，将 Chroma 同步 API 放到线程中运行，输出更易使用的字典列表。
- `get_collection_count` / `get_collection_count_async`：查询已入库记录数。
- `clear_collection` / `clear_collection_async`：清空当前 collection。
- `generate_id_from_text_and_source`：基于文本和来源生成稳定哈希 ID。
- `close`：清理客户端引用。

**它在两条链路中的位置**

- 用例生成前：保存需求文档和代码片段，并按用户 query 检索相似资料。
- 自动化生成前：保存可被分析的 API 文档、源代码、已有测试和前端代码；`ApplicationKnowledgeExtractor` 再从中发现实际系统信息。

**为什么 collection 名很重要**

collection 相当于一个知识库命名空间。若资料入库时使用 `demo`，生成或 automate 时也必须使用 `demo`；如果名字不同，程序不会报“资料不存在”，而是会在另一个空库里生成，导致 RAG 上下文缺失。

### 3.6 `core/llm/llm_manager.py`：多模型统一门面

**它解决什么问题**

不同模型 SDK 的初始化方式、API Key 名称、文本生成和 embedding 接口都不同。`LLMManager` 用一个统一接口包住这些差异，让业务层只关心“生成文本”和“生成向量”。

**运行机制**

1. 构造函数从参数或配置中取得 provider。
2. `_get_provider` 验证 provider 是否受支持。
3. `_initialize_client` 创建 `GeminiClient`、`OpenAIClient`、`ClaudeClient` 或 `LlamaClient`。
4. 业务层调用 `generate_text` / `generate_text_async`，请求被转发到当前客户端。
5. 向量库需要 embedding 时调用 `get_embedding_sync` 或批量版本。

**提供的统一能力**

| 接口 | 调用者 | 用途 |
|---|---|---|
| `generate_text_async(prompt)` | `TestTellerAgent` | 生成测试用例文本。 |
| `generate_text(prompt)` | 自动化生成器 | 生成完整测试代码。 |
| `get_embedding_sync(text)` | `ChromaDBManager` | 为文档或查询创建向量。 |
| `get_provider_info()` | CLI / 调试 | 显示当前模型信息。 |
| `validate_provider_config()` | 配置流程 | 预检查供应商配置。 |

**异常处理**

该类会识别常见 API Key 错误，给出配置提示，而不是直接暴露底层 SDK 的异常。它只是适配层：模型是否能访问、额度是否足够、网络是否可达仍由供应商和环境决定。

### 3.7 `automator_agent/cli.py`：自动化代码生成的命令行总控

**它解决什么问题**

这是从“测试用例文档”走向“测试源代码目录”的命令行编排器。它接收测试用例文件和目标语言/框架，完成初始化、解析、可选筛选、生成、写盘、质量提示和下一步运行说明。

**输入参数**

- `input_file`：支持 `.md`、`.txt`、`.pdf`、`.docx`、`.xlsx`。
- `--collection-name`：必须与之前入库使用的 collection 对应。
- `--language`：Python、JavaScript、TypeScript 或 Java。
- `--framework`：如 pytest、unittest、Playwright、Jest、Mocha、Cypress、JUnit、TestNG。
- `--output-dir`：生成工程目录。
- `--interactive`：是否让使用者选择具体哪些用例。
- `--num-context`：每类知识发现检索的上下文数量。

**`automate_command` 的八个阶段**

1. 校验输入文件是否存在，解析 collection、语言、框架和输出目录。
2. 用 `initialize_vector_store` 打开应用知识库。
3. 创建 `LLMManager`，确认模型供应商可用。
4. 使用 `UnifiedDocumentParser.parse_for_automation` 解析用例；Markdown、DOCX、PDF 都有额外 fallback。
5. 可选地由 `interactive_select_tests` 展示并筛选用例。
6. 创建 `RAGEnhancedTestGenerator`，调用 `generate(test_cases)`。
7. 调用继承自 `BaseTestGenerator` 的 `write_files` 写出生成文件。
8. 打印文件清单、框架运行建议，并由 `assess_generated_quality` 统计 TODO、import、测试函数等静态迹象。

**它为什么不直接执行测试**

生成的代码往往依赖目标服务地址、数据库、账号、令牌、浏览器驱动和测试数据。当前 CLI 只生成工程并提示后续命令，没有替用户执行 `pytest`、`npm test` 或 Maven/Gradle 测试。因此“命令正常结束”只证明生成流程成功，不证明业务测试已经通过。

### 3.8 `automator_agent/rag_enhanced_generator.py`：把测试用例和项目知识变成测试代码

**它解决什么问题**

`RAGEnhancedTestGenerator` 是自动化链路的核心。相较于只把用例丢给模型，它先构建应用上下文、检索类似已有测试、按测试类别分文件，并对生成文本执行结构性修补和静态校验。

**主流程：`generate(test_cases)`**

```text
List[TestCase]
  -> ApplicationKnowledgeExtractor.extract_app_context()
  -> categorize_tests()（来自 BaseTestGenerator）
  -> 每个非空类别调用 _generate_complete_test_file()
  -> _validate_and_fix_code()
  -> _generate_supporting_files()
  -> 回写自动化结果 metadata
  -> Dict[文件名, 文件内容]
```

**生成提示词包含什么**

`_build_generation_prompt` 会组合以下信息：

- 当前类别下每一个 `TestCase` 的目标、前置条件、步骤、预期结果、接口契约等。
- `ApplicationContext` 中实际发现的 API endpoint、请求/响应 schema、UI selector、认证方式、数据模型和 base URL。
- `_find_similar_test_implementations` 从向量库检索到的既有测试实现。
- `_get_framework_specific_instructions` 提供 pytest/Jest/Playwright 等框架的结构要求。
- 强制要求模型生成完整文件，不输出 Markdown 围栏，不保留 TODO 占位。

**生成后的处理**

- `_clean_generated_code`：移除代码块标记和多余说明。
- `_ensure_proper_structure`：按 Python 或 JS/TS 的基础要求补充部分必要结构。
- `_validate_and_fix_code`：`TestCodeValidator` 检查语法、必需 import、测试结构和 TODO/FIXME；必要时可让模型修复。
- `_generate_supporting_files`：Python 方向生成依赖与 `conftest.py`，JS/TS 方向生成依赖清单。

**输出组织方式**

测试会按类别生成类似 `test_e2e.py`、`test_integration.py`、`test_technical.py` 的文件名，随后合并支撑文件。实际类别取决于解析得到的 `TestCase.category`。

**必须如实看待的兜底行为**

当 RAG 生成整体失败，或单个模型调用失败时，代码会走 `_generate_fallback_files` / `_generate_minimal_working_file`。Python pytest 的最小文件中仍包含 `# TODO: Implement specific test logic`，仅断言 `base_url` 非空。这保证“有一个可写出的文件”，但不是可用的业务自动化测试。因此输出中出现 TODO 时，应视为生成质量失败并重新检查模型、资料和提示词，而不是认为自动化已完成。

### 3.9 `automator_agent/application_context.py`：从项目知识库还原被测应用轮廓

**它解决什么问题**

仅有“登录成功”的自然语言用例，不足以写出可执行代码；生成器还需要知道登录接口、字段名、认证头、前端输入框选择器、服务地址等。该文件尝试从此前入库的文档和代码中发现这些信息。

**核心数据模型**

| 数据类 | 表达的信息 |
|---|---|
| `APIEndpoint` | 路径、HTTP 方法、描述、请求/响应 schema、是否需要认证。 |
| `UIPattern` | CSS/XPath/测试 ID 等 selector、元素类型、所在页面。 |
| `AuthPattern` | JWT/session/basic/oauth、登录接口、token header、登录控件。 |
| `DataSchema` | 模型名、字段、必填字段。 |
| `ApplicationContext` | 将上述信息加 base URL、既有测试模式和框架配置汇总。 |

**`extract_app_context` 的六步发现过程**

1. `_discover_api_endpoints(test_cases)`：从测试目标构造查询，检索相关文档和代码，用正则与 OpenAPI 解析识别 URL、方法及 schema。
2. `_discover_ui_patterns(test_cases)`：检索前端组件和测试代码，识别 `data-testid`、CSS selector、XPath 或常见测试框架定位方式。
3. `_discover_auth_patterns()`：检索认证相关资料，推断 JWT、session、OAuth 等模式及登录信息。
4. `_discover_data_schemas(test_cases)`：从后端模型、类型定义或接口示例提取字段和类型。
5. `_find_existing_test_patterns(test_cases)`：找项目已有的测试写法，为新代码生成提供风格参考。
6. `_discover_framework_patterns()` 与 `_infer_base_url()`：从项目配置中找框架约定和服务地址。

**失败语义**

任何发现过程异常时，`extract_app_context` 会返回空的 `ApplicationContext`，而不是阻断自动化生成。这样流程更稳定，但模型会退化为根据用例和通用知识猜测实现。若生成的 endpoint 或 selector 不正确，应优先检查相关项目资料是否已用同一 collection 成功入库。

### 3.10 `automator_agent/parser/markdown_parser.py`：测试用例 Markdown 的语法适配器

**它解决什么问题**

LLM 输出是文本，但自动化生成器需要可遍历、可分类的对象。该文件把约定格式的测试用例 Markdown 转换为 `TestCase` 和 `TestStep` 数据类，是“自然语言用例”进入代码生成器前的结构化关口。

**数据模型**

- `TestStep`：动作、技术细节、验证方式和验证细节。
- `TestCase`：ID、功能、类型、类别、目标、引用、前置条件、步骤、预期状态、异常场景。
- 对集成测试扩展了 integration、请求 payload、响应预期、技术契约；对技术测试扩展了技术区域、假设和 setup。

**支持的两种格式**

1. **表格摘要格式**：检测到 `| S.No | Test ID |` 表头时，读取行数据；根据 E2E、Integration、Technical、Mocked System 分区填充不同字段。
2. **传统详细格式**：以 `Test Case E2E_...`、`INT_...`、`TECH_...`、`MOCK_...` 为标题边界，逐行识别 Feature、Objective、Prerequisites、Steps、Expected Result、Contract 等字段。

**解析过程**

```text
parse_file() -> UTF-8 读取文件 -> parse_content()
  -> 如果有表格，_parse_tabular_format()
  -> _parse_traditional_format()
  -> 按 TestCase.id 去重
  -> List[TestCase]
```

之后，`RAGEnhancedTestGenerator` 会用这些结构化字段拼接提示词，并依据类别拆分输出文件。也就是说，这个文件不生成代码，但决定了代码生成器到底能拿到多少清晰、准确的测试语义。

**格式约束与常见失败原因**

- 传统格式的 ID 需要符合 `E2E_`、`INT_`、`TECH_`、`MOCK_` 前缀，否则不会进入对应专用解析逻辑。
- 表格格式至少要提供 `Test ID` 和 `Objective`；缺失时该行会被跳过。
- 非结构化叙述即使人能读懂，也可能解析不出用例；这时应调整生成用例的提示词或套用项目样例格式。

## 4. 一次推荐的完整跑通示例

以下示例假设：已完成 `testteller configure`，配置了一个可用模型；目标项目的需求、接口文档、源码和已有测试可以被读取。

```powershell
# 1. 将需求/API 文档与被测项目源码写入同一个知识库
testteller ingest-docs .\input-docs -c shop_demo
testteller ingest-code D:\workspace\shop-service -c shop_demo

# 2. 基于知识库生成结构化测试用例
testteller generate "为用户登录、下单、支付失败和库存不足设计测试用例" `
  -c shop_demo --output-file .\artifacts\shop-test-cases.md

# 3. 将用例转换为 pytest 自动化工程
testteller automate .\artifacts\shop-test-cases.md `
  -c shop_demo -l python -F pytest -o .\artifacts\shop-pytest

# 4. 进入生成目录，按生成的 requirements 安装依赖，再执行测试
Set-Location .\artifacts\shop-pytest
pip install -r requirements.txt
pytest -v
```

### 4.1 上述示例真正依赖的条件

- `shop_demo` 名称必须在步骤 1、2、3 完全一致，否则知识库无法复用。
- 模型 API Key、网络和模型额度必须可用；否则 `LLMManager` 无法生成文本或代码。
- 被测应用需要已启动，且生成的 `base_url`、令牌、账号、数据库、接口路径和选择器需要与真实环境匹配。
- 若步骤 3 生成结果含 TODO、只包含空断言或没有定位到真实接口/选择器，应回到步骤 1 补充资料，并重新生成；这不是步骤 4 能自动修复的问题。

## 5. 结论：这些文件如何共同把项目跑起来

`README.md` 让人知道如何使用项目；`main.py` 把人类命令变成可执行工作流；`TestTellerAgent` 将解析、向量库和模型连接为测试用例生成业务；`UnifiedDocumentParser` 将各种资料归一；`ChromaDBManager` 让资料能按语义被找回；`LLMManager` 隔离不同模型供应商的差异。

在第二条链路中，`automator_agent/cli.py` 接收测试用例文件并编排流程，`markdown_parser.py` 将文本用例变成结构化对象，`application_context.py` 从知识库中还原目标应用信息，`rag_enhanced_generator.py` 最终生成测试代码和支撑文件。最后一步的真实执行仍在项目外部完成：用户或 CI 必须在真实测试环境中运行生成目录中的 pytest/Jest/Playwright/JUnit 等命令，才能证明测试确实通过。
