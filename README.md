# TestTeller Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/testteller.svg)](https://pypi.org/project/testteller/)
[![Docker](https://img.shields.io/docker/v/iavipro/testteller?label=docker&logo=docker)](https://hub.docker.com/r/iavipro/testteller)
[![Tests](https://github.com/iAviPro/testteller-agent/actions/workflows/test-unit.yml/badge.svg)](https://github.com/iAviPro/testteller-agent/actions/workflows/test-unit.yml)
[![Downloads](https://pepy.tech/badge/testteller)](https://pepy.tech/project/testteller)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**TestTeller** 是一个由 AI 驱动的测试代理，能够把你的文档转换成完整的测试套件和可执行的自动化代码。它基于**双反馈 RAG 架构**，支持多种 GenAI/LLM（Google Gemini、OpenAI、Anthropic Claude、本地 Llama），可以分析你的需求、设计文档和现有代码，生成具有策略性的测试用例，并在**多种编程语言**和**支持的测试框架**上完成自动化。

## 为什么选择 TestTeller？

TestTeller 能把文档和代码转换成完整的测试策略与可执行自动化脚本。与传统测试工具不同，TestTeller 使用双反馈 RAG 架构来理解你的需求，并生成更智能的测试场景。

### 可生成的测试类型
- **端到端测试（E2E）**：覆盖前端、中间件和后端服务的完整用户旅程
- **集成测试**：覆盖组件集成（前后端、服务间、事件驱动）和契约校验
- **技术测试**：聚焦基础设施层面的性能、安全、弹性测试
- **Mock 系统测试**：基于模拟依赖的隔离式组件测试

### 关键能力
- **双反馈 RAG 增强**：将通过质量门禁的输出作为可检索样本，增强后续上下文
- **多 LLM 提供商支持**：支持 Google Gemini、OpenAI、Anthropic Claude 和本地 Llama/Ollama
- **通用文档智能解析**：支持 PDF、DOCX、XLSX、MD、TXT 的高级解析，并理解上下文
- **代码仓库分析**：可摄取并分析 GitHub 仓库或本地文件夹中的代码

### 支持的语言与框架
**测试生成**：支持所有测试类型，并可输出表格摘要和详细规格说明
**自动化生成**：支持 Python（pytest、unittest）、JavaScript/TypeScript（Jest、Mocha、Cypress、Playwright）、Java（JUnit、TestNG）等

**真实工作流**：摄取项目文档（PRD/契约/设计/Schema 等）和项目代码 -> 生成覆盖认证、错误处理和边界场景的测试用例 -> 生成带有正确初始化和断言的 Selenium/Playwright 自动化代码 -> 提交你的代码。

## 核心特性

- **Generator Agent**：虚拟测试架构师，结合双反馈 RAG 增强，分析文档并按类别智能生成测试用例（E2E、集成、安全、边界场景）
- **Automator Agent**：支持 **Python、JavaScript、TypeScript、Java** 的多语言代码生成，兼容 **20+ 测试框架**（pytest、Jest、JUnit、Playwright、Cypress、Cucumber 等）
- **多提供商 GenAI/LLM**：可选择 **Google Gemini、OpenAI、Anthropic Claude**，也可以完全在本地通过 **Llama/Ollama** 运行
- **通用文档智能**：基于高级 RAG 的文档摄取，支持 **PDF、DOCX、XLSX、MD、TXT**，能够理解上下文并生成合适的测试重点
- **反馈检索系统**：保存高质量生成结果和 Agent 执行轨迹，支持后续分析与回归评测

-> **[查看详细特性](docs/FEATURES.md)** | **[技术架构](docs/ARCHITECTURE.md)**

### Agent 闭环运行

项目提供基于 LangGraph 的 `agent-run` 工作流：Planner 规划任务，RAG 检索项目上下文，Generator 生成测试代码，Executor 在受限工作区运行测试，Repairer 根据失败日志修复并复跑，Reviewer 输出最终结论。运行轨迹保存为 JSONL；生成成功不等于测试通过。

```bash
testteller agent-run test-cases.md --language python --framework pytest \
  --output-dir ./agent-run-001 --test-command "python -m pytest -q"
```

-> **[Agent 工作流说明](docs/AGENT_WORKFLOW.md)**

## 快速开始

### 前置要求
- Python 3.11+
- 至少一个 LLM 提供商的 API Key：
  - [Google Gemini](https://aistudio.google.com/)（推荐）
  - [OpenAI](https://platform.openai.com/api-keys)
  - [Anthropic Claude](https://console.anthropic.com/)
  - [Ollama](https://ollama.ai/)（本地或可访问环境中运行）

### 安装

#### 方式 1：通过 PyPI 安装
```bash
# 从 PyPI 安装
pip install testteller
```

#### 方式 2：通过 Docker 安装

**快速体验（Docker Hub 镜像）：**
```bash
# 从 Docker Hub 拉取并运行，适合快速测试
docker pull iavipro/testteller:latest

# 运行单条命令
docker run -it \
  -e GOOGLE_API_KEY=your_api_key \
  -v $(pwd)/docs:/app/docs \
  -v $(pwd)/output:/app/output \
  iavipro/testteller:latest testteller --help

# 示例：生成测试用例
docker run -it \
  -e GOOGLE_API_KEY=your_api_key \
  -v $(pwd):/app/workspace \
  iavipro/testteller:latest testteller generate "API tests" --output-file /app/workspace/tests.pdf --collection-name my_collection
```

**完整开发环境（Docker Compose）：**
```bash
# 克隆仓库，使用包含 ChromaDB 的完整环境
git clone https://github.com/iAviPro/testteller-agent.git
cd testteller-agent

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件并填入你的 API Key（GOOGLE_API_KEY、OPENAI_API_KEY、CLAUDE_API_KEY）

# 启动所有服务（TestTeller + ChromaDB）
docker-compose up -d

# 配置并使用
docker-compose exec app testteller configure
docker-compose exec app testteller ingest-docs /path/to/document.pdf --collection-name project
docker-compose exec app testteller generate "API integration tests" --collection-name project

# 停止服务
docker-compose down
```

#### 方式 3：从源码安装
```bash
# 从源码安装
git clone https://github.com/iAviPro/testteller-agent.git
cd testteller-agent
pip install -e .
```

### 基本使用：2 分钟上手

```bash
# 1. 配置你的 LLM 提供商（交互式向导）
testteller configure

# 2. 摄取你的文档（支持 PDF、DOCX、XLSX、MD、TXT）
testteller ingest-docs requirements.pdf --collection-name my_project

# 3. 从仓库或本地文件夹摄取代码
testteller ingest-code https://github.com/user/repo --collection-name my_project
# 或者：testteller ingest-code ./src --collection-name my_project

# 4. 基于 RAG 上下文生成测试用例
testteller generate "Create comprehensive API integration tests" --collection-name my_project --output-file tests.pdf

# 5. 生成可执行的自动化代码
testteller automate tests.pdf --language python --framework pytest --output-dir ./tests
```

**增强示例：**

```bash
# E2E 测试流程
testteller ingest-docs user_stories.pdf --collection-name webapp
testteller ingest-code ./frontend --collection-name webapp
testteller generate "E2E user registration and checkout flow" --collection-name webapp
testteller automate output.pdf --language javascript --framework cypress

# 带安全重点的 API 测试
testteller ingest-docs api_spec.pdf --collection-name api
testteller generate "API security and integration tests" --collection-name api --output-format pdf
testteller automate tests.pdf --language python --framework pytest

# 微服务测试
testteller ingest-code ./services --collection-name microservices
testteller generate "Inter-service communication and resilience tests" --collection-name microservices
testteller automate output.pdf --language java --framework junit
```

**背后发生了什么？** TestTeller 的双反馈 RAG 会分析你摄取的文档和代码，基于结构化模板（E2E、集成、技术、Mock）生成具有策略性的测试用例，然后创建具备正确初始化、数据管理和 CI/CD 集成能力的生产级自动化代码。

### 立即试用 TestTeller

**没有 API Key？** 没问题，可以使用本地 Llama：
```bash
# 安装 Ollama（macOS/Linux）
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.2

# 将 TestTeller 配置为本地模式
testteller configure --provider llama
```

## Docker 支持

```bash
# 克隆并初始化
git clone https://github.com/iAviPro/testteller-agent.git
cd testteller-agent
cp .env.example .env  # 填入你的 API Key
docker-compose up -d

# 在 Docker 中使用
docker-compose exec app testteller configure
docker-compose exec app testteller ingest-docs document.pdf --collection-name project
```

## 文档

- **[完整特性说明](docs/FEATURES.md)** - 详细功能说明与能力介绍
- **[技术架构](docs/ARCHITECTURE.md)** - 系统设计与技术细节
- **[命令参考](docs/COMMANDS.md)** - 完整 CLI 命令文档
- **[测试指南](docs/TESTING.md)** - 测试套件与校验说明

## 常见问题

如果你遇到 API Key 相关错误，请运行 `testteller configure`。如果遇到 Docker 问题，请通过 `docker-compose logs app` 查看日志。


---

## 许可证

本项目基于 Apache-2.0 License 开源，详情请参见 [LICENSE](LICENSE) 文件。
