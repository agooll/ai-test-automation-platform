/**
 * TestTeller Web Console
 * Handles Context Ingestion, Test Generation, Quality Gate, and Agentic Workflow execution.
 */

(() => {
  // DOM Elements - Global & Context
  const healthDot = document.getElementById("health-dot");
  const healthText = document.getElementById("health-text");
  const collectionInput = document.getElementById("collection");
  const refreshStatusBtn = document.getElementById("refresh-status");
  const docCount = document.getElementById("document-count");

  const docsPathInput = document.getElementById("docs-path");
  const ingestDocsBtn = document.getElementById("ingest-docs");
  const codePathInput = document.getElementById("code-path");
  const ingestCodeBtn = document.getElementById("ingest-code");

  // DOM Elements - Generation
  const queryInput = document.getElementById("query");
  const limitInput = document.getElementById("result-limit");
  const generateBtn = document.getElementById("generate");
  const resultPre = document.getElementById("result");
  const copyResultBtn = document.getElementById("copy-result");
  const toast = document.getElementById("toast");

  // DOM Elements - Agent Runner
  const agentInputFile = document.getElementById("agent-input-file");
  const useGeneratedBtn = document.getElementById("use-generated-btn");
  const loadSampleBtn = document.getElementById("load-sample-btn");
  const agentFramework = document.getElementById("agent-framework");
  const agentLanguage = document.getElementById("agent-language");
  const agentMaxRepair = document.getElementById("agent-max-repair");
  const agentCommand = document.getElementById("agent-command");
  const agentHumanReview = document.getElementById("agent-human-review");
  const startAgentBtn = document.getElementById("start-agent-run");

  // DOM Elements - Timeline & Diff & HITL
  const currentTaskId = document.getElementById("current-task-id");
  const taskStatusBadge = document.getElementById("task-status-badge");
  const hitlBanner = document.getElementById("hitl-banner");
  const hitlApproveBtn = document.getElementById("hitl-approve");
  const hitlRejectBtn = document.getElementById("hitl-reject");
  const timelineNodes = document.querySelectorAll(".timeline-node");
  const repairTabButtons = document.getElementById("repair-tab-buttons");
  const diffMeta = document.getElementById("diff-meta");
  const diffOutcome = document.getElementById("diff-outcome");
  const evidenceBox = document.getElementById("evidence-box");
  const evidenceContent = document.getElementById("evidence-content");
  const diffContent = document.getElementById("diff-content");
  const agentEventsLog = document.getElementById("agent-events-log");

  let currentEventSource = null;
  let activeTaskId = null;
  let activeRepairHistory = [];

  // -------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------
  function showToast(message, duration = 3000) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), duration);
  }

  async function apiRequest(url, method = "GET", body = null) {
    const options = {
      method,
      headers: { "Content-Type": "application/json" }
    };
    if (body) options.body = JSON.stringify(body);
    const res = await fetch(url, options);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || `请求失败 (${res.status})`);
    }
    return data;
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // -------------------------------------------------------------
  // Health & Status
  // -------------------------------------------------------------
  async function checkHealth() {
    try {
      const data = await apiRequest("/api/health");
      const healthDiv = healthDot?.parentElement;
      if (healthDiv) healthDiv.className = "health online";
      if (healthText) healthText.textContent = `在线 (${data.provider})`;
    } catch {
      const healthDiv = healthDot?.parentElement;
      if (healthDiv) healthDiv.className = "health";
      if (healthText) healthText.textContent = "本地服务离线";
    }
  }

  async function refreshStatus() {
    const col = collectionInput.value.trim();
    if (!col) return;
    try {
      const data = await apiRequest("/api/status", "POST", { collection_name: col });
      if (docCount) docCount.textContent = data.count ?? 0;
    } catch (e) {
      showToast(e.message);
    }
  }

  // -------------------------------------------------------------
  // Context Ingestion
  // -------------------------------------------------------------
  async function ingestDocs() {
    const path = docsPathInput.value.trim();
    const col = collectionInput.value.trim();
    if (!path) return showToast("请输入文档路径");
    ingestDocsBtn.disabled = true;
    try {
      showToast("正在解析并入库文档...");
      const data = await apiRequest("/api/ingest-docs", "POST", { path, collection_name: col });
      showToast(`文档入库成功，当前共有 ${data.count} 条记录`);
      refreshStatus();
    } catch (e) {
      showToast(e.message);
    } finally {
      ingestDocsBtn.disabled = false;
    }
  }

  async function ingestCode() {
    const sourcePath = codePathInput.value.trim();
    const col = collectionInput.value.trim();
    if (!sourcePath) return showToast("请输入代码路径或 Git 地址");
    ingestCodeBtn.disabled = true;
    try {
      showToast("正在分析并入库代码...");
      const data = await apiRequest("/api/ingest-code", "POST", { source_path: sourcePath, collection_name: col });
      showToast(`代码入库成功，当前共有 ${data.count} 条记录`);
      refreshStatus();
    } catch (e) {
      showToast(e.message);
    } finally {
      ingestCodeBtn.disabled = false;
    }
  }

  // -------------------------------------------------------------
  // Test Generation
  // -------------------------------------------------------------
  async function generateTestCases() {
    const query = queryInput.value.trim();
    const col = collectionInput.value.trim();
    const numRetrievedDocs = parseInt(limitInput.value, 10) || 5;
    if (!query) return showToast("请输入测试需求");

    generateBtn.disabled = true;
    resultPre.textContent = "正在检索相关上下文并调用大模型生成用例...";
    try {
      const data = await apiRequest("/api/generate", "POST", {
        collection_name: col,
        query,
        num_retrieved_docs: numRetrievedDocs
      });
      resultPre.textContent = data.content;
      showToast("测试用例生成完成");
    } catch (e) {
      resultPre.textContent = `生成失败: ${e.message}`;
      showToast(e.message);
    } finally {
      generateBtn.disabled = false;
    }
  }

  function copyResult() {
    const content = resultPre.textContent;
    if (!content || content.startsWith("等待输入") || content.startsWith("正在检索")) {
      return showToast("无内容可复制");
    }
    navigator.clipboard.writeText(content).then(() => {
      showToast("结果已复制到剪贴板");
    }).catch(() => {
      showToast("复制失败，请手动选取");
    });
  }

  // -------------------------------------------------------------
  // Agent Runner & Timeline
  // -------------------------------------------------------------
  function resetTimeline() {
    timelineNodes.forEach(node => {
      node.className = "timeline-node";
    });
  }

  function setNodeState(nodeName, state) {
    // state: 'running' | 'passed' | 'failed'
    const target = Array.from(timelineNodes).find(
      n => n.getAttribute("data-node")?.toLowerCase() === nodeName.toLowerCase()
    );
    if (target) {
      target.className = `timeline-node ${state}`;
    }
  }

  function updateStatusBadge(status) {
    if (!taskStatusBadge) return;
    taskStatusBadge.textContent = status;
    taskStatusBadge.className = `status-badge ${status}`;
  }

  function appendEventLog(ev) {
    if (!agentEventsLog) return;
    const timeStr = new Date((ev.timestamp || Date.now() / 1000) * 1000).toLocaleTimeString();
    const line = `[${timeStr}] ${ev.event || "EVENT"}: ${JSON.stringify(ev)}\n`;
    agentEventsLog.textContent += line;
    agentEventsLog.scrollTop = agentEventsLog.scrollHeight;
  }

  function renderUnifiedDiff(diffText) {
    if (!diffContent) return;
    if (!diffText || !diffText.trim()) {
      diffContent.innerHTML = '<span class="diff-line-normal">// 本轮无文件差异修改</span>';
      return;
    }
    const lines = diffText.split("\n");
    const formatted = lines.map(line => {
      const esc = escapeHtml(line);
      if (line.startsWith("+++") || line.startsWith("---")) {
        return `<span class="diff-line-info">${esc}</span>`;
      }
      if (line.startsWith("+")) {
        return `<span class="diff-line-add">${esc}</span>`;
      }
      if (line.startsWith("-")) {
        return `<span class="diff-line-del">${esc}</span>`;
      }
      if (line.startsWith("@@")) {
        return `<span class="diff-line-info">${esc}</span>`;
      }
      return `<span class="diff-line-normal">${esc}</span>`;
    }).join("\n");
    diffContent.innerHTML = formatted;
  }

  function displayRepairRound(roundIndex) {
    const entry = activeRepairHistory[roundIndex];
    if (!entry) return;

    // Update active tab button
    const buttons = repairTabButtons.querySelectorAll(".tab-btn");
    buttons.forEach((btn, idx) => {
      btn.classList.toggle("active", idx === roundIndex);
    });

    diffMeta.textContent = `第 ${entry.round} 轮修复 | 根因: ${entry.failure_type || "未知"} | 失败用例: ${(entry.failed_tests || []).join(", ") || "无"}`;

    if (entry.re_execution_passed !== null && entry.re_execution_passed !== undefined) {
      diffOutcome.textContent = entry.re_execution_passed ? "验证通过 (PASS)" : "仍未通过 (FAIL)";
      diffOutcome.className = `outcome-badge ${entry.re_execution_passed ? "passed" : "failed"}`;
    } else {
      diffOutcome.textContent = "执行中 / 待验证";
      diffOutcome.className = "outcome-badge";
    }

    if (entry.failure_evidence) {
      evidenceBox.style.display = "block";
      evidenceContent.textContent = entry.failure_evidence;
    } else {
      evidenceBox.style.display = "none";
    }

    // Combine diffs for all files in this round
    const files = entry.files || {};
    const fileNames = Object.keys(files);
    if (fileNames.length === 0) {
      renderUnifiedDiff("");
    } else {
      const allDiffs = fileNames.map(fn => {
        const fileDiff = files[fn]?.diff || "";
        return `# File: ${fn}\n${fileDiff}`;
      }).join("\n\n");
      renderUnifiedDiff(allDiffs);
    }
  }

  function updateRepairTabs(history) {
    activeRepairHistory = history || [];
    if (!repairTabButtons) return;
    if (activeRepairHistory.length === 0) {
      repairTabButtons.innerHTML = '<span class="empty-hint">暂无修复记录</span>';
      return;
    }
    repairTabButtons.innerHTML = "";
    activeRepairHistory.forEach((item, idx) => {
      const btn = document.createElement("button");
      btn.className = `tab-btn ${idx === activeRepairHistory.length - 1 ? "active" : ""}`;
      btn.textContent = `Round ${item.round || idx + 1}`;
      btn.addEventListener("click", () => displayRepairRound(idx));
      repairTabButtons.appendChild(btn);
    });
    // Display latest round by default
    displayRepairRound(activeRepairHistory.length - 1);
  }

  function connectAgentEvents(taskId) {
    if (currentEventSource) {
      currentEventSource.close();
    }
    const es = new EventSource(`/api/agent-runs/${taskId}/events`);
    currentEventSource = es;

    const handleEvent = (evData) => {
      appendEventLog(evData);
      const evType = evData.event;

      if (evType === "RUN_STARTED") {
        updateStatusBadge("RUNNING");
        setNodeState("plan", "running");
      } else if (evType === "PLAN_COMPLETED") {
        setNodeState("plan", "passed");
        setNodeState("retrieve", "running");
      } else if (evType === "RETRIEVE_COMPLETED") {
        setNodeState("retrieve", "passed");
        setNodeState("generate", "running");
      } else if (evType === "GENERATE_COMPLETED") {
        setNodeState("generate", "passed");
        setNodeState("execute", "running");
      } else if (evType === "EXECUTE_COMPLETED") {
        if (evData.passed) {
          setNodeState("execute", "passed");
          setNodeState("review", "running");
        } else {
          setNodeState("execute", "failed");
          setNodeState("analyze_failure", "running");
        }
      } else if (evType === "ANALYZE_FAILURE_COMPLETED") {
        setNodeState("analyze_failure", "passed");
        setNodeState("repair", "running");
      } else if (evType === "REPAIR_COMPLETED") {
        setNodeState("repair", "passed");
        setNodeState("execute", "running");
        if (evData.latest_repair) {
          const currentHist = [...activeRepairHistory, evData.latest_repair];
          updateRepairTabs(currentHist);
        }
      } else if (evType === "WAITING_REVIEW") {
        updateStatusBadge("WAITING_REVIEW");
        hitlBanner.style.display = "flex";
        if (evData.repair_history) {
          updateRepairTabs(evData.repair_history);
        }
        showToast("自动修复轮次耗尽，请进行人工裁决");
      } else if (evType === "RUN_RESUMED") {
        hitlBanner.style.display = "none";
        updateStatusBadge("RUNNING");
        setNodeState("review", "running");
        showToast(`已提交决策: ${evData.decision}`);
      } else if (evType === "REVIEW_COMPLETED" || evType === "RUN_COMPLETED") {
        hitlBanner.style.display = "none";
        const verdict = evData.final_verdict || "COMPLETED";
        updateStatusBadge(verdict);
        if (verdict === "PASS" || verdict === "APPROVED") {
          setNodeState("review", "passed");
        } else {
          setNodeState("review", "failed");
        }
        if (evData.repair_history) {
          updateRepairTabs(evData.repair_history);
        }
        showToast(`Agent 执行完成: ${verdict}`);
        es.close();
      } else if (evType === "RUN_ERROR") {
        updateStatusBadge("ERROR");
        showToast(`执行发生异常: ${evData.error}`);
        es.close();
      }
    };

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        handleEvent(data);
      } catch (err) {
        console.warn("Parse SSE error:", err);
      }
    };

    // Also register specific named event listeners
    [
      "RUN_STARTED", "PLAN_COMPLETED", "RETRIEVE_COMPLETED", "GENERATE_COMPLETED",
      "EXECUTE_COMPLETED", "ANALYZE_FAILURE_COMPLETED", "REPAIR_COMPLETED",
      "WAITING_REVIEW", "RUN_RESUMED", "REVIEW_COMPLETED", "RUN_COMPLETED", "RUN_ERROR"
    ].forEach(eventName => {
      es.addEventListener(eventName, (e) => {
        try {
          const data = JSON.parse(e.data);
          handleEvent(data);
        } catch (err) {
          console.warn("Parse SSE event error:", err);
        }
      });
    });

    es.onerror = () => {
      // EventSource reconnects automatically on network drop
    };
  }

  async function startAgentRun() {
    let inputFile = agentInputFile.value.trim();
    const framework = agentFramework.value;
    const language = agentLanguage.value;
    const maxRepairRounds = parseInt(agentMaxRepair.value, 10) || 0;
    const testCommand = agentCommand.value.trim();
    const humanReview = agentHumanReview.checked;
    const col = collectionInput.value.trim() || "test_collection";

    let markdownContent = null;
    if (!inputFile) {
      const generated = resultPre.textContent.trim();
      if (generated && !generated.startsWith("等待输入") && !generated.startsWith("正在检索") && !generated.startsWith("生成失败")) {
        markdownContent = generated;
      } else {
        return showToast("请指定测试用例文件路径，或先在 02/03 生成测试用例");
      }
    }

    startAgentBtn.disabled = true;
    resetTimeline();
    updateStatusBadge("QUEUED");
    hitlBanner.style.display = "none";
    activeRepairHistory = [];
    updateRepairTabs([]);
    agentEventsLog.textContent = "";

    try {
      const payload = {
        input_file: inputFile || null,
        markdown_content: markdownContent,
        framework,
        language,
        max_repair_rounds: maxRepairRounds,
        test_command: testCommand,
        human_review: humanReview,
        collection_name: col
      };
      const res = await apiRequest("/api/agent-runs", "POST", payload);
      activeTaskId = res.task_id;
      currentTaskId.textContent = activeTaskId;
      showToast(`任务已启动: ${activeTaskId}`);
      connectAgentEvents(activeTaskId);
      document.getElementById("timeline-section")?.scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      showToast(e.message);
      updateStatusBadge("ERROR");
    } finally {
      startAgentBtn.disabled = false;
    }
  }

  async function handleHitlDecision(decision) {
    if (!activeTaskId) return;
    hitlApproveBtn.disabled = true;
    hitlRejectBtn.disabled = true;
    try {
      await apiRequest(`/api/agent-runs/${activeTaskId}/resume`, "POST", { decision });
      showToast(`决策 [${decision}] 已提交`);
    } catch (e) {
      showToast(e.message);
    } finally {
      hitlApproveBtn.disabled = false;
      hitlRejectBtn.disabled = false;
    }
  }

  // -------------------------------------------------------------
  // Event Bindings
  // -------------------------------------------------------------
  refreshStatusBtn?.addEventListener("click", refreshStatus);
  ingestDocsBtn?.addEventListener("click", ingestDocs);
  ingestCodeBtn?.addEventListener("click", ingestCode);
  generateBtn?.addEventListener("click", generateTestCases);
  copyResultBtn?.addEventListener("click", copyResult);

  useGeneratedBtn?.addEventListener("click", () => {
    const text = resultPre.textContent.trim();
    if (!text || text.startsWith("等待输入") || text.startsWith("正在检索")) {
      return showToast("上方 03 尚无生成结果");
    }
    agentInputFile.value = "";
    agentInputFile.placeholder = "使用上方 03 结果 (内存传递)";
    showToast("已设为使用上方生成的测试用例");
  });

  loadSampleBtn?.addEventListener("click", () => {
    agentInputFile.value = "sample-outputs/sample-testcases/sample-test-cases.md";
    showToast("已填充示例用例路径");
  });

  startAgentBtn?.addEventListener("click", startAgentRun);
  hitlApproveBtn?.addEventListener("click", () => handleHitlDecision("approve"));
  hitlRejectBtn?.addEventListener("click", () => handleHitlDecision("reject"));

  // Init
  checkHealth();
  refreshStatus();
})();
