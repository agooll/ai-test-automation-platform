"""
Stage 3 全流程手动模拟演示脚本 (Manual Walkthrough)
--------------------------------------------------
这个脚本帮助你以单步、可视化的方式，亲身体验 TestTeller 评测与沙箱的每一个细节：
1. 工作区准备（为什么/怎么剔除原有测试，防止作弊）
2. RAG 知识检索（如何从开源代码库中检索出关键实现）
3. 大模型生成测试（基于需求与检索上下文编写 pytest）
4. 沙箱执行原理（Docker 命令是如何构造的，本地安全沙箱是如何隔离执行的）
5. 缺陷变异体验证（如何打入真实代码 Bug，验证测试是否具备真实找错能力）
"""

import os
import sys
import shutil
import subprocess
import time
import io
import warnings
from pathlib import Path

# 屏蔽无关的第三方告警与遥测干扰
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
warnings.filterwarnings("ignore", category=FutureWarning)

if sys.platform == "win32":
    try:
        # 开启 line_buffering=True 保证终端文字实时刷新，不卡顿
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

# 确保项目根目录在 sys.path 中
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from testteller.config import settings
from testteller.core.llm.llm_manager import LLMManager
from testteller.core.vector_store.chromadb_manager import ChromaDBManager
from testteller.benchmark.loader import load_benchmark_case, load_project_manifest
from testteller.benchmark.project import BenchmarkProjectManager
from testteller.agent_runtime.tools.execution import LocalSubprocessExecutor, DockerSandboxExecutor

def print_banner(title: str, step: int = 0):
    print("\n" + "=" * 70)
    if step > 0:
        print(f"[Step {step}]: {title}")
    else:
        print(f"=== {title} ===")
    print("=" * 70 + "\n")

def run_demo():
    print_banner("TestTeller Stage 3 评测与沙箱全流程手动模拟")
    print("本演示将使用真实的开源项目 [cachetools] 和 [case_01: LRUCache 基础功能测试] 进行实操。\n")

    # -------------------------------------------------------------
    # 步骤 1: 准备纯净沙箱工作区 (Workspace Staging)
    # -------------------------------------------------------------
    print_banner("创建独立沙箱工作区 & 剔除已有测试（防作弊）", 1)
    
    project_manifest_path = ROOT_DIR / "evals" / "projects" / "oss_project_1.yaml"
    manifest = load_project_manifest(project_manifest_path)
    print(f"1. 目标开源项目: {manifest.name}")
    print(f"2. 强制锁死 Commit SHA: {manifest.commit_sha}")

    demo_workspace = ROOT_DIR / "evals" / "workspace" / "manual_demo_case_01"
    if demo_workspace.exists():
        shutil.rmtree(demo_workspace)
    demo_workspace.mkdir(parents=True, exist_ok=True)

    pm = BenchmarkProjectManager()
    cached_repo = pm.ensure_project_repo(manifest)
    print(f"3. 复制原始仓库源码: {cached_repo} -> {demo_workspace}")
    
    # 复制文件并严格排除原项目的 tests 目录
    for item in os.listdir(cached_repo):
        if item in [".git", "tests", "test", "__pycache__", ".pytest_cache"]:
            print(f"   🚫 拦截过滤: '{item}' (严格禁止大模型偷看原项目自带测试或历史提交)")
            continue
        src = cached_repo / item
        dst = demo_workspace / item
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    # 注入 conftest.py 保证导入路径正确
    conftest = demo_workspace / "conftest.py"
    conftest.write_text(
        "import sys, os\n"
        "root = os.path.abspath(os.path.dirname(__file__))\n"
        "sys.path.insert(0, root)\n"
        "src = os.path.join(root, 'src')\n"
        "if os.path.exists(src):\n"
        "    sys.path.insert(0, src)\n",
        encoding="utf-8"
    )
    print("4. 沙箱目录准备完毕！沙箱根目录内容:")
    for f in sorted(os.listdir(demo_workspace)):
        print(f"   📁 {f}" if (demo_workspace / f).is_dir() else f"   📄 {f}")

    # -------------------------------------------------------------
    # 步骤 2: 静态只读 RAG 检索 (Code Retrieval)
    # -------------------------------------------------------------
    print_banner("只读 RAG 检索（让模型理解被测模块的真实实现）", 2)
    
    case_path = ROOT_DIR / "evals" / "cases" / "case_01.yaml"
    case = load_benchmark_case(case_path, base_dir=ROOT_DIR)
    print(f"用例需求目标: {case.target_entrypoint}")
    print(f"用例所属分类: {case.category} | 难度: {case.difficulty}\n")

    query = f"LRUCache implementation {case.target_entrypoint}"
    print(f"向只读向量数据库发送检索请求: '{query}'")
    
    # 自动识别模型：优先使用传入的参数或已配置的 Gemini，无则回退至智谱
    selected_model = sys.argv[1] if len(sys.argv) > 1 else ("gemini-3.5-flash" if os.getenv("GOOGLE_API_KEY") else "glm-4-flash")
    selected_provider = "gemini" if "gemini" in selected_model else "zhipu"

    llm_manager = LLMManager(provider=selected_provider, generation_model=selected_model, allow_fallback=False)
    pm = BenchmarkProjectManager()
    collection_name, corpus_hash = pm.build_or_load_static_rag_snapshot(manifest)
    vector_store = ChromaDBManager(llm_manager=llm_manager, collection_name=collection_name)
    
    # 检索相关代码片段
    try:
        results = vector_store.query_similar(query_text=query, n_results=2)
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        print(f"检索到 {len(docs)} 个最相关的源码片段:")
        for idx, (doc, meta) in enumerate(zip(docs, metas), 1):
            file_path = meta.get("file_path", "unknown") if isinstance(meta, dict) else "unknown"
            snippet = doc[:180].replace("\n", " ")
            print(f"   [{idx}] 来源文件: {file_path}")
            print(f"       代码摘录: {snippet}...\n")
    except Exception as e:
        print(f"（提示：向量库维度自适应中，跳过本地 RAG 检索显示）: {e}\n")

    # -------------------------------------------------------------
    # 步骤 3: 大模型基于需求编写测试 (Generation)
    # -------------------------------------------------------------
    print_banner(f"大模型（{selected_provider.upper()} - {selected_model}）编写测试代码", 3)
    
    req_file = ROOT_DIR / case.requirement_path
    req_content = req_file.read_text(encoding="utf-8") if req_file.exists() else ""

    prompt = f"""你是一名资深 Python 自动化测试专家。请为开源库 `cachetools` 中的 `LRUCache` 编写测试用例。

【业务需求规格说明】：
{req_content}

【编写要求】：
1. 覆盖基本的 setitem / getitem 功能；
2. 验证达到 maxsize (例如 maxsize=2) 时的最久未访问淘汰机制（LRU 语义）；
3. 只能使用 pytest 框架，测试文件只包含可执行的测试函数；
4. 必须能真实检测逻辑缺陷。

请直接输出完整的 Python 代码，包裹在 ```python 代码块中。"""

    print(f"⏳ 正在联网调用 {selected_provider.upper()} ({selected_model}) 生成测试代码（预计耗时 10~20 秒，请稍候）...", flush=True)
    t0 = time.time()
    response = llm_manager.generate_text(prompt)
    cost_s = time.time() - t0
    print(f"✅ 生成完毕 (耗时: {cost_s:.2f}s)!\n", flush=True)

    # 提取代码并写入沙箱的 tests/ 目录
    code = response
    if "```python" in code:
        code = code.split("```python", 1)[1].split("```", 1)[0].strip()
    elif "```" in code:
        code = code.split("```", 1)[1].split("```", 1)[0].strip()

    test_dir = demo_workspace / "tests"
    test_dir.mkdir(exist_ok=True)
    test_file = test_dir / "test_lru_demo.py"
    test_file.write_text(code, encoding="utf-8")

    print(f"生成的测试文件已存入沙箱: {test_file.relative_to(ROOT_DIR)}")
    print("--- 测试代码预览 (前 20 行) ---")
    lines = code.splitlines()
    for l in lines[:20]:
        print("  ", l)
    if len(lines) > 20:
        print(f"   ... (共 {len(lines)} 行)")

    # -------------------------------------------------------------
    # 步骤 4: 沙箱执行原理（Docker 与本地沙箱）
    # -------------------------------------------------------------
    print_banner("沙箱安全执行机制（Execution & Sandbox）", 4)
    
    print("💡 【沙箱原理剖析】:")
    print("为什么要沙箱？")
    print("  大模型生成的代码是不可信的（可能包含 rm -rf、死循环、未定义网络外联等）。")
    print("  沙箱的核心三原则：1. 路径隔离 (只准访问工作区) 2. 超时熔断 (死循环强杀) 3. 资源受限。\n")

    print("🐳 如果在 Linux/Docker 环境下，TestTeller 构造的 Docker 执行命令长这样:")
    print(f"  docker run --rm \\")
    print(f"    --network none \\                  # 彻底断开网络，禁止任何外联")
    print(f"    -m 1g --cpus 1.0 \\                # 限制内存 1G，CPU 1核")
    print(f"    -v \"{demo_workspace}\":/workspace \\ # 仅挂载当前的临时沙箱目录")
    print(f"    -w /workspace \\                   # 容器内工作目录")
    print(f"    testteller-runner-python:3.11-v1 \\# 预装所有依赖的固定镜像")
    print(f"    pytest -v tests/test_lru_demo.py   # 执行测试命令\n")

    print("💻 在当前 Windows 本地机器（未安装 Docker 守护进程）时：")
    print("  系统会自动启用 [LocalSubprocessExecutor] 安全本地执行器：")
    print("  - 工作目录锁定 (cwd=demo_workspace)")
    print("  - 超时保护 (timeout=30s)")
    print("  - 环境变量隔离 (剥离敏感主机环境变量，如 TOKEN/KEY 等)\n")

    executor = LocalSubprocessExecutor(workspace_root=demo_workspace, timeout_seconds=30)
    print("▶️ 现在在本地安全沙箱中执行生成的测试...")
    exec_res = executor.run(["pytest", "-v", "tests/test_lru_demo.py"], framework="pytest")
    
    passed = exec_res.get("passed")
    exit_code = exec_res.get("exit_code")
    dur_ms = exec_res.get("duration_ms", 0.0)
    print(f"执行状态: {'✅ 通过 (PASS)' if passed else '❌ 失败 (FAIL)'}")
    print(f"退出码 (Exit Code): {exit_code}")
    print(f"耗时: {dur_ms:.1f} ms")
    print("--- 原始执行输出 (Stdout Snippet) ---")
    for line in (exec_res.get("stdout") or "").splitlines()[-10:]:
        print("  ", line)

    if not passed:
        print_banner("自主修复闭环（Self-Repair Loop）: 根据报错日志自动修复测试", 4)
        print("💡 【自修复原理】:")
        print("初次生成的测试可能因为细微断言偏差失败（例如淘汰后直接下标访问抛出了 KeyError 而不是返回 None）。")
        print("TestTeller 会捕获沙箱报错输出，重新构造提示词让大模型自我修正：\n")
        
        repair_prompt = f"""以下测试在执行时失败了：
代码：
{test_file.read_text(encoding='utf-8')}

错误日志：
{exec_res.get('stdout', '')}

请修复该测试代码，使其能正确在 pytest 下执行通过。注意：在 cachetools 中，淘汰的 key 访问时会报 KeyError，或者可以使用 `key not in cache` 进行断言。
请只输出修复后的完整 Python 代码，包裹在 ```python 代码块中。"""

        print("⏳ 正在请求大模型自我修正测试代码（约需 10~20 秒）...", flush=True)
        repair_res = llm_manager.generate_text(repair_prompt)
        if "```python" in repair_res:
            repaired_code = repair_res.split("```python", 1)[1].split("```", 1)[0].strip()
        elif "```" in repair_res:
            repaired_code = repair_res.split("```", 1)[1].split("```", 1)[0].strip()
        else:
            repaired_code = repair_res.strip()
            
        test_file.write_text(repaired_code, encoding="utf-8")
        print("测试文件已更新，正在沙箱中重新执行...")
        exec_res = executor.run(["pytest", "-v", "tests/test_lru_demo.py"], framework="pytest")
        passed = exec_res.get("passed")
        print(f"自修复后状态: {'✅ 通过 (PASS)' if passed else '❌ 依然失败 (FAIL)'}")
        print(f"退出码: {exec_res.get('exit_code')}\n")

    # -------------------------------------------------------------
    # 步骤 5: 缺陷变异体验证（Dual Oracle 真 Bug 检验）
    # -------------------------------------------------------------
    print_banner("变异体注入与真 Bug 拦截检验 (Dual Oracle)", 5)
    
    print("💡 【为什么需要这一步？】")
    print("如果模型写了一个毫无意义的测试（比如空函数或者 assert 1 == 1），它在干净代码上也能通过。")
    print("怎么证明这个测试是真有找 Bug 的能力？")
    print("答：把被测源码故意搞出一个真实 Bug（注入变异体），测试必须当场报错变红！\n")

    if not case.mutants:
        print("该 Case 无变异体定义，跳过。")
        return

    mutant = case.mutants[0]
    patch_content = (ROOT_DIR / mutant.patch_path).read_text(encoding="utf-8")
    print(f"准备注入的变异体: [{mutant.mutant_id}] - {mutant.description}")
    print("--- 变异代码补丁 (Patch) ---")
    for l in patch_content.strip().splitlines()[:10]:
        print("  ", l)
    print("----------------------------\n")

    print("💉 正在将变异补丁注入源码...")
    # 保存原始文件
    target_src = demo_workspace / "src" / "cachetools" / "__init__.py"
    backup_src = target_src.read_text(encoding="utf-8")
    
    # 打入变异补丁
    patch_file = demo_workspace / "mutant.patch"
    patch_file.write_text(patch_content, encoding="utf-8")
    
    from testteller.benchmark.oracle import apply_patch_to_dir
    applied = apply_patch_to_dir(patch_file, demo_workspace)
    print(f"✅ 变异体注入完成 (applied={applied})！此时源码已存在人为引入的逻辑缺陷。\n")
    
    print("▶️ 再次在沙箱中运行相同的测试用例...")
    mutant_res = executor.run(["pytest", "-v", "tests/test_lru_demo.py"], framework="pytest")
    
    m_passed = mutant_res.get("passed")
    print(f"变异环境退出码: {mutant_res.get('exit_code')}")
    if not m_passed:
        print("\n🎉 【变异体被成功杀死 (Mutant Killed)!】")
        print("👉 测试用例成功捕获了人为注入的代码 Bug，测试报错变红！这证明该测试具备真实的缺陷发现能力，并非虚假断言。")
    else:
        print("\n⚠️ 【变异体存活 (Mutant Survived)】")
        print("👉 源码被破坏后，测试依然全绿通过，说明该测试断言较弱，未能覆盖此边界缺陷。")

    # 恢复源码
    target_src.write_text(backup_src, encoding="utf-8")
    if patch_file.exists():
        patch_file.unlink()
    print("\n🧹 沙箱源码已恢复干净状态。")

    print_banner("手动模拟全流程圆满结束！")
    print("你现在可以随时在终端输入以下命令再次体验：")
    print(f"  .venv\\Scripts\\python scripts/manual_walkthrough.py\n")

if __name__ == "__main__":
    run_demo()
