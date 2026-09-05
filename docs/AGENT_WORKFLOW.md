# TestTeller Agent 闭环工作流

TestTeller 的 Agent 运行时以 LangGraph 为编排层，保留现有 ChromaDB + SQLite 混合 RAG。它把“生成成功”和“测试通过”分成两个独立结果，并以真实执行日志作为修复依据。

## 工作流

```text
START -> plan -> retrieve -> generate -> execute
                                      |
                         pass -> review -> persist -> END
                         fail -> analyze_failure
                                      |
                         rounds left -> repair -> execute
                         no rounds   -> review -> persist
```

核心实现位于 `testteller/agent_runtime`：

- `state.py`：共享的 `AgentState`，记录计划、上下文、文件、执行结果、修复轮次和结论。
- `graph.py`：LangGraph 状态图和条件路由，最多修复 2 轮（可由调用方调整到 0～3）。
- `tools/registry.py`：带参数和结果记录的工具注册器。
- `tools/execution.py`：工作区边界、命令白名单、超时和输出限制。
- `tools/artifacts.py`：只允许读写生成工程目录内的文件。
- `adapters.py`：把现有 `RAGEnhancedTestGenerator` 接入 Agent 图。
- `llm_callbacks.py`：可选的 LangChain 结构化 Planner/Reviewer 适配层。
- `trace.py`：以 JSONL 保存节点和工具调用轨迹。

## 工具权限

工具按角色最小化分配：Planner 负责计划，Retriever 负责上下文，Generator 负责产物，Executor 负责测试运行，Repairer 负责修改和复跑，Reviewer 负责结论。任何 Agent 都不能直接执行任意 Python 或 Shell 代码。

执行器还会拒绝 `python -c`、交互模式、shell 运算符和非测试模块；文件写入不能越过 workspace；修复轮数由 `max_repair_rounds` 限制。真实部署仍应使用容器、资源配额、网络策略和独立低权限账号。

`AgentToolRegistry.as_langchain_tools()` 可把 allowlist 转成 LangChain `StructuredTool`，模型只能看到注册的工具和参数 schema，调用结果统一进入 trace。

如果接入 LangChain Chat Model，可使用 `StructuredLLMCallbacks(model)` 替换工作流的 `planner` 和 `reviewer`。模型只输出经过 Pydantic 校验的计划和审核对象，路由、执行权限和修复上限仍由图控制。

## 状态恢复与人工审核

默认使用内存 checkpoint；传入 `checkpoint_path` 时使用 SQLite 持久化 LangGraph 状态。设置 `human_review=True` 后，不确定结果会在 `review` 节点暂停，并可使用同一 thread 恢复：

```python
result = await workflow.run(state, thread_id="case-001")
result = await workflow.resume("case-001", "approve")  # 或 reject
```

## 结果定义

```text
generation_success：是否成功生成文件
execution_success：生成的测试是否实际通过
repair_success：失败后修复并通过的比例
final_verdict：PASS / REJECTED / NEEDS_REVIEW
```

人工批准后的结论会标记为 `MANUAL_APPROVED`，与自动通过区分。

生成目录中的测试仍需要目标应用、依赖和测试数据。只有执行结果为 PASS，才能把该次运行计入可执行率；文件生成成功本身不等于业务测试通过。

## CLI

```text
testteller agent-run test-cases.md \
  --language python \
  --framework pytest \
  --output-dir ./agent-run-001 \
  --test-command "python -m pytest -q" \
  --max-repair-rounds 2 \
  --checkpoint-file ./agent-run-001/state.sqlite
```

当前 CLI 要求先配置模型供应商。执行结果和节点轨迹会写入输出目录的 `agent_trace.jsonl`。

## 评测建议

使用固定测试用例集和本地 Demo 被测应用，同时记录首轮可执行率、最终通过率、自动修复成功率、平均修复轮数、虚构 API 比例、耗时和 Token 成本。简历只使用实际评测结果，不使用架构推测值。
