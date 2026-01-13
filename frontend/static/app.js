const thread = document.getElementById("thread");
const analysisStack = document.getElementById("analysisStack");
const thinkingCard = document.getElementById("thinkingCard");
const testsCard = document.getElementById("testsCard");
const testsBar = document.getElementById("testsBar");
const testsPercent = document.getElementById("testsPercent");
const testsDetail = document.getElementById("testsDetail");
const iterationsCard = document.getElementById("iterationsCard");
const iterationsList = document.getElementById("iterationsList");
const downloadCard = document.getElementById("downloadCard");
const downloadButton = document.getElementById("downloadButton");

const workflowName = document.getElementById("workflowName");
const fileInput = document.getElementById("fileInput");
const uploadButton = document.getElementById("uploadButton");
const uploadPreview = document.getElementById("uploadPreview");
const uploadHint = document.getElementById("uploadHint");
const chatInput = document.getElementById("chatInput");
const sendChat = document.getElementById("sendChat");

const SESSION_KEY = "lemonSessionId";
const PREVIEW_KEY = "lemonWorkflowPreview";
const DEFAULT_PREVIEW_HTML = uploadPreview ? uploadPreview.innerHTML : "";
function getSessionId() {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      id = window.crypto.randomUUID();
    } else {
      id = `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    }
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

const SESSION_ID = getSessionId();

function withSession(headers = {}) {
  return { ...headers, "X-Session-Id": SESSION_ID };
}
const historyBack = document.getElementById("historyBack");
const historyForward = document.getElementById("historyForward");
const snapshotFlowchart = document.getElementById("snapshotFlowchart");
const runPipeline = document.getElementById("runPipeline");
const clearState = document.getElementById("clearState");
const connectToggle = document.getElementById("connectToggle");
const connectStatus = document.getElementById("connectStatus");
const clearCanvas = document.getElementById("clearCanvas");
const exportPreview = document.getElementById("exportPreview");
const paletteColors = document.getElementById("paletteColors");
const nodeColorRow = document.getElementById("nodeColorRow");
const nodeLabelInput = document.getElementById("nodeLabelInput");
const nodeTypeSelect = document.getElementById("nodeTypeSelect");
const deleteNode = document.getElementById("deleteNode");
const selectedNodeHint = document.getElementById("selectedNodeHint");
const autoLayout = document.getElementById("autoLayout");

const flowchartCanvas = document.getElementById("flowchartCanvas");
const edgeLayer = document.getElementById("edgeLayer");
const nodeLayer = document.getElementById("nodeLayer");

const COLOR_MAP = {
  teal: "#1f6e68",
  amber: "#c98a2c",
  green: "#3e7c4d",
  slate: "#4b5563",
  rose: "#b4533d",
  sky: "#2b6cb0",
};

const NODE_SIZES = {
  start: { w: 160, h: 64 },
  end: { w: 160, h: 64 },
  process: { w: 180, h: 80 },
  decision: { w: 160, h: 100 },
  subprocess: { w: 200, h: 90 },
};

const state = {
  conversation: [],
  inputs: [],
  outputs: [],
  revision: 0,
  workflowName: "",
  flowchart: null,
};

let flowchart = { nodes: [], edges: [] };
let history = [];
let historyIndex = -1;
let selectedNodeId = null;
let connectMode = false;
let connectFromId = null;
let activeColor = "teal";
let dragState = null;
let dragDirty = false;

function ensureVisible(el) {
  if (!el.classList.contains("is-visible")) {
    el.classList.add("is-visible");
  }
  const wrapper = el.closest(".message-stage");
  if (wrapper) {
    wrapper.classList.remove("is-hidden");
  }
  if (wrapper && wrapper.parentElement === thread) {
    thread.append(wrapper);
  }
}

function hideVisible(el) {
  if (el.classList.contains("is-visible")) {
    el.classList.remove("is-visible");
  }
  const wrapper = el.closest(".message-stage");
  if (wrapper) {
    wrapper.classList.add("is-hidden");
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(text) {
  if (!text) return "";
  const lines = String(text).split(/\r?\n/);
  const output = [];
  let inCode = false;
  let listType = null;
  let paragraph = [];
  let inBlockquote = false;
  let blockquoteLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    output.push(`<p>${paragraph.join("<br>")}</p>`);
    paragraph = [];
  };

  const flushBlockquote = () => {
    if (!inBlockquote) return;
    if (blockquoteLines.length) {
      output.push(`<blockquote><p>${blockquoteLines.join("<br>")}</p></blockquote>`);
    }
    inBlockquote = false;
    blockquoteLines = [];
  };

  const closeList = () => {
    if (!listType) return;
    output.push(`</${listType}>`);
    listType = null;
  };

  const inlineFormat = (value) => {
    const escaped = escapeHtml(value);
    let formatted = escaped
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
    formatted = formatted.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, url) => {
      const safeUrl = url.trim();
      if (!/^https?:\/\//i.test(safeUrl)) {
        return label;
      }
      return `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    });
    return formatted;
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      flushParagraph();
      closeList();
      flushBlockquote();
      if (!inCode) {
        output.push("<pre><code>");
        inCode = true;
      } else {
        output.push("</code></pre>");
        inCode = false;
      }
      return;
    }

    if (inCode) {
      output.push(`${escapeHtml(rawLine)}\n`);
      return;
    }

    if (!line.trim()) {
      flushParagraph();
      closeList();
      flushBlockquote();
      return;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      closeList();
      flushBlockquote();
      const level = Math.min(6, headingMatch[1].length);
      output.push(`<h${level}>${inlineFormat(headingMatch[2])}</h${level}>`);
      return;
    }

    if (/^([-*_])\1\1+\s*$/.test(line.trim())) {
      flushParagraph();
      closeList();
      flushBlockquote();
      output.push("<hr />");
      return;
    }

    if (line.trim().startsWith(">")) {
      flushParagraph();
      closeList();
      if (!inBlockquote) {
        inBlockquote = true;
        blockquoteLines = [];
      }
      blockquoteLines.push(inlineFormat(line.replace(/^>\s?/, "")));
      return;
    }

    if (inBlockquote) {
      flushBlockquote();
    }

    const unordered = line.match(/^\s*[-*]\s+(.*)$/);
    const ordered = line.match(/^\s*\d+\.\s+(.*)$/);
    if (unordered || ordered) {
      flushParagraph();
      const desired = unordered ? "ul" : "ol";
      if (listType !== desired) {
        closeList();
        listType = desired;
        output.push(`<${listType}>`);
      }
      const itemText = unordered ? unordered[1] : ordered[1];
      output.push(`<li>${inlineFormat(itemText)}</li>`);
      return;
    }

    if (listType) {
      closeList();
    }
    paragraph.push(inlineFormat(line));
  });

  flushParagraph();
  closeList();
  flushBlockquote();
  if (inCode) {
    output.push("</code></pre>");
  }
  return output.join("");
}

function renderMessage(msg) {
  if (!shouldRenderMessage(msg)) {
    return;
  }
  const wrapper = document.createElement("div");
  wrapper.className = `message ${msg.role}`;
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = msg.role === "user" ? "You" : "Orchestrator";
  const body = document.createElement("div");
  body.className = "message-body";
  body.innerHTML = renderMarkdown(msg.content);
  wrapper.append(meta, body);
  thread.append(wrapper);
}

function renderConversation(messages) {
  const stageWrappers = Array.from(thread.querySelectorAll(".message-stage"));
  stageWrappers.forEach((wrapper) => wrapper.remove());
  thread.innerHTML = "";
  messages.forEach(renderMessage);
  stageWrappers.forEach((wrapper) => thread.append(wrapper));
}

function shouldRenderMessage(msg) {
  if (!msg || !msg.content) {
    return false;
  }
  if (msg.role === "orchestrator" && msg.content === "Analyzing the workflow diagram.") {
    return false;
  }
  return true;
}

function mountStageInThread(stageEl, id) {
  if (!stageEl) return;
  if (stageEl.closest(".message-stage")) return;
  const wrapper = document.createElement("div");
  wrapper.className = "message orchestrator message-stage is-hidden";
  wrapper.dataset.stageId = id;
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = "Orchestrator";
  wrapper.append(meta, stageEl);
  thread.append(wrapper);
}

function buildRangeText(input) {
  const type = input.input_type || "unknown";
  if (!input.range) {
    return `Type: ${type} | Range: unbounded`;
  }
  if (Array.isArray(input.range)) {
    return `Type: ${type} | Values: ${input.range.length}`;
  }
  const min = input.range.min;
  const max = input.range.max;
  const value = input.range.value;
  if (value !== undefined && value !== null) {
    return `Type: ${type} | Value: ${value}`;
  }
  if (min !== undefined && max !== undefined && min !== null && max !== null) {
    return `Type: ${type} | Range: ${min} to ${max}`;
  }
  if (min !== undefined && min !== null) {
    return `Type: ${type} | Range: >= ${min}`;
  }
  if (max !== undefined && max !== null) {
    return `Type: ${type} | Range: <= ${max}`;
  }
  return `Type: ${type} | Range: unbounded`;
}

function groupInputsByType(inputs) {
  const groups = {
    numeric: [],
    text: [],
    boolean: [],
    date: [],
    other: [],
  };

  inputs.forEach((input) => {
    const type = (input.input_type || "").toLowerCase();
    if (type === "int" || type === "float") {
      groups.numeric.push(input);
    } else if (type === "str") {
      groups.text.push(input);
    } else if (type === "bool") {
      groups.boolean.push(input);
    } else if (type === "date") {
      groups.date.push(input);
    } else {
      groups.other.push(input);
    }
  });

  const output = [];
  if (groups.numeric.length) output.push({ title: "Numeric", items: groups.numeric });
  if (groups.text.length) output.push({ title: "Text", items: groups.text });
  if (groups.boolean.length) output.push({ title: "Boolean", items: groups.boolean });
  if (groups.date.length) output.push({ title: "Date", items: groups.date });
  if (groups.other.length) output.push({ title: "Other", items: groups.other });
  return output;
}

function renderAnalysisRevision(inputs, outputs, revision) {
  Array.from(analysisStack.children).forEach((card) => {
    card.classList.add("is-collapsed");
  });

  const card = document.createElement("div");
  card.className = "stage analysis-card is-visible";

  const header = document.createElement("div");
  header.className = "stage-header";

  const headerText = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "ANALYSIS REVIEW";
  const title = document.createElement("h3");
  title.textContent = "Inputs and outputs";
  headerText.append(eyebrow, title);

  const headerActions = document.createElement("div");
  headerActions.className = "analysis-header-actions";

  const badge = document.createElement("div");
  badge.className = "badge";
  badge.textContent = `Revision ${revision}`;

  const collapseButton = document.createElement("button");
  collapseButton.className = "ghost collapse-toggle";
  collapseButton.textContent = "Collapse";
  collapseButton.addEventListener("click", () => {
    card.classList.toggle("is-collapsed");
    collapseButton.textContent = card.classList.contains("is-collapsed")
      ? "Expand"
      : "Collapse";
  });

  headerActions.append(badge, collapseButton);
  header.append(headerText, headerActions);

  const body = document.createElement("div");
  body.className = "analysis-body";

  const inputsColumn = document.createElement("div");
  const inputsTitle = document.createElement("h4");
  inputsTitle.textContent = "Inputs";
  inputsColumn.append(inputsTitle);

  const groups = groupInputsByType(inputs);
  groups.forEach((group) => {
    const section = document.createElement("div");
    section.className = "input-group";

    const groupTitle = document.createElement("h5");
    groupTitle.textContent = `${group.title} (${group.items.length})`;

    const list = document.createElement("div");
    list.className = "input-group-list";

    group.items.forEach((input) => {
      const row = document.createElement("div");
      row.className = "input-row";

      const name = document.createElement("div");
      name.className = "input-name";
      name.textContent = input.input_name || "Unnamed input";

      const meta = document.createElement("div");
      meta.className = "input-meta";
      meta.textContent = buildRangeText(input);

      const desc = document.createElement("div");
      desc.className = "input-desc";
      desc.textContent = input.description || "No description";

      row.append(name, meta, desc);
      list.append(row);
    });

    section.append(groupTitle, list);
    inputsColumn.append(section);
  });

  const outputsColumn = document.createElement("div");
  const outputsTitle = document.createElement("h4");
  outputsTitle.textContent = "Outputs";
  const outputsWrap = document.createElement("div");
  outputsWrap.className = "outputs";
  outputs.forEach((output) => {
    const chip = document.createElement("div");
    chip.className = "output-chip";
    chip.textContent = output;
    outputsWrap.append(chip);
  });
  outputsColumn.append(outputsTitle, outputsWrap);

  body.append(inputsColumn, outputsColumn);

  const actions = document.createElement("div");
  actions.className = "analysis-actions";

  const approveButton = document.createElement("button");
  approveButton.className = "primary";
  approveButton.textContent = "Looks good, run tests";
  approveButton.addEventListener("click", async () => {
    approveButton.disabled = true;
    collapseLatestAnalysis();
    await fetch("/api/analysis/approve", {
      method: "POST",
      headers: withSession(),
    });
    approveButton.disabled = false;
  });

  const feedbackToggle = document.createElement("button");
  feedbackToggle.className = "ghost";
  feedbackToggle.textContent = "Needs refinement";

  actions.append(approveButton, feedbackToggle);

  const feedbackPanel = document.createElement("div");
  feedbackPanel.className = "feedback";

  const feedbackHint = document.createElement("p");
  feedbackHint.className = "muted";
  feedbackHint.textContent = "Tell the orchestrator what feels wrong. It will re-run the analysis.";

  const feedbackChips = document.createElement("div");
  feedbackChips.className = "chips";
  [
    "Ranges are wrong",
    "Missing input",
    "Outputs are mislabeled",
    "Decision logic seems off",
  ].forEach((chipText) => {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.dataset.chip = chipText;
    chip.textContent = chipText;
    feedbackChips.append(chip);
  });

  const feedbackInput = document.createElement("textarea");
  feedbackInput.placeholder = "Describe the issue...";

  const feedbackActions = document.createElement("div");
  feedbackActions.className = "actions-row";

  const sendFeedback = document.createElement("button");
  sendFeedback.className = "primary";
  sendFeedback.textContent = "Send feedback";

  const cancelFeedback = document.createElement("button");
  cancelFeedback.className = "ghost";
  cancelFeedback.textContent = "Cancel";

  feedbackActions.append(sendFeedback, cancelFeedback);
  feedbackPanel.append(feedbackHint, feedbackChips, feedbackInput, feedbackActions);

  feedbackToggle.addEventListener("click", () => {
    feedbackPanel.classList.toggle("is-visible");
  });

  cancelFeedback.addEventListener("click", () => {
    feedbackPanel.classList.remove("is-visible");
    feedbackInput.value = "";
  });

  feedbackChips.addEventListener("click", (event) => {
    if (!event.target.classList.contains("chip")) return;
    const text = event.target.dataset.chip;
    feedbackInput.value = feedbackInput.value ? `${feedbackInput.value} ${text}` : text;
  });

  sendFeedback.addEventListener("click", async () => {
    const feedback = feedbackInput.value.trim();
    if (!feedback) return;
    sendFeedback.disabled = true;
    await fetch("/api/analysis/feedback", {
      method: "POST",
      headers: withSession({ "Content-Type": "application/json" }),
      body: JSON.stringify({ feedback }),
    });
    sendFeedback.disabled = false;
    feedbackInput.value = "";
    feedbackPanel.classList.remove("is-visible");
  });

  card.append(header, body, actions, feedbackPanel);
  analysisStack.append(card);

  ensureVisible(card);
  const wrapper = analysisStack.closest(".message-stage");
  if (wrapper && wrapper.parentElement === thread) {
    thread.append(wrapper);
  }
}

function collapseLatestAnalysis() {
  const latest = analysisStack.lastElementChild;
  if (!latest) return;
  latest.classList.add("is-collapsed");
  const toggle = latest.querySelector(".collapse-toggle");
  if (toggle) {
    toggle.textContent = "Expand";
  }
}

function updateTestsProgress(progress) {
  ensureVisible(testsCard);
  const percent = Math.min(100, progress.percent || 0);
  testsBar.style.width = `${percent}%`;
  testsPercent.textContent = `${percent}%`;
  testsDetail.textContent = `Labeling batches: ${progress.current || 0}/${progress.total || 0}`;
}

function addIteration(iteration) {
  ensureVisible(iterationsCard);
  const row = document.createElement("div");
  row.className = "iteration";
  row.innerHTML = `<span>Iteration ${iteration.iteration}</span><strong>${(
    iteration.score * 100
  ).toFixed(1)}%</strong>`;
  iterationsList.append(row);
}

function showDownload(url) {
  downloadButton.href = `${url}?session_id=${SESSION_ID}`;
  const name = state.workflowName;
  downloadButton.textContent = name ? `Download ${name}.py` : "Download workflow.py";
}

function showThinking(show) {
  if (show) {
    ensureVisible(thinkingCard);
  } else {
    hideVisible(thinkingCard);
  }
}

function applyStage(stage) {
  if (stage === "idle") {
    hideVisible(thinkingCard);
    hideVisible(testsCard);
    hideVisible(iterationsCard);
    hideVisible(downloadCard);
    return;
  }

  if (stage === "analyzing") {
    showThinking(true);
    hideVisible(testsCard);
    hideVisible(iterationsCard);
    hideVisible(downloadCard);
    return;
  }

  if (stage === "awaiting_approval") {
    showThinking(false);
    hideVisible(testsCard);
    hideVisible(iterationsCard);
    hideVisible(downloadCard);
    return;
  }

  if (stage === "tests_running") {
    ensureVisible(testsCard);
    hideVisible(downloadCard);
    collapseLatestAnalysis();
  }

  if (stage === "code_refining") {
    ensureVisible(iterationsCard);
  }

  if (stage === "done") {
    ensureVisible(downloadCard);
  }
}

function handleEvent(event) {
  if (event.type === "message") {
    state.conversation.push(event.data);
    renderMessage(event.data);
  }
  if (event.type === "analysis_ready") {
    state.inputs = event.data.inputs || [];
    state.outputs = event.data.outputs || [];
    state.revision = event.data.revision || 0;
    renderAnalysisRevision(state.inputs, state.outputs, state.revision);
    showThinking(false);
    if (event.data.flowchart) {
      setFlowchart(event.data.flowchart, { push: true });
      if (needsAutoLayout(event.data.flowchart)) {
        autoLayoutFlowchart({ push: true });
      }
    }
  }
  if (event.type === "flowchart_updated") {
    if (event.data.flowchart) {
      setFlowchart(event.data.flowchart, { push: true });
      if (needsAutoLayout(event.data.flowchart)) {
        autoLayoutFlowchart({ push: true });
      }
    }
  }
  if (event.type === "approval_requested") {
    showThinking(false);
  }
  if (event.type === "stage_started") {
    if (event.data.stage === "analyzing") {
      showThinking(true);
    }
    applyStage(event.data.stage);
  }
  if (event.type === "tests_progress") {
    updateTestsProgress(event.data);
  }
  if (event.type === "iteration_result") {
    addIteration(event.data);
    showDownload("/api/download");
    ensureVisible(downloadCard);
  }
  if (event.type === "artifact_ready") {
    showDownload(event.data.download_url);
  }
  if (event.type === "state_reset") {
    window.location.reload();
  }
}

function cloneFlowchart(data) {
  return JSON.parse(JSON.stringify(data));
}

function pushHistory(data) {
  const snapshot = cloneFlowchart(data);
  if (historyIndex < history.length - 1) {
    history = history.slice(0, historyIndex + 1);
  }
  history.push(snapshot);
  historyIndex = history.length - 1;
  updateHistoryButtons();
}

function updateHistoryButtons() {
  historyBack.disabled = historyIndex <= 0;
  historyForward.disabled = historyIndex >= history.length - 1;
}

function setFlowchart(data, { push = false } = {}) {
  flowchart = cloneFlowchart(data);
  if (push) {
    pushHistory(flowchart);
  }
  renderFlowchart();
  updateInspector();
}

function getNodeSize(type) {
  return NODE_SIZES[type] || NODE_SIZES.process;
}

function getNodeCenter(node) {
  const size = getNodeSize(node.type);
  return { x: node.x + size.w / 2, y: node.y + size.h / 2 };
}

function getConnectionPoint(node, target) {
  const size = getNodeSize(node.type);
  const center = getNodeCenter(node);
  const targetCenter = getNodeCenter(target);
  const dx = targetCenter.x - center.x;
  const dy = targetCenter.y - center.y;
  if (!dx && !dy) {
    return { x: center.x, y: center.y };
  }

  const rx = size.w / 2;
  const ry = size.h / 2;
  if (node.type === "decision") {
    const scale = 1 / ((Math.abs(dx) / rx) + (Math.abs(dy) / ry));
    return { x: center.x + dx * scale, y: center.y + dy * scale };
  }

  const scale = 1 / Math.max(Math.abs(dx) / rx, Math.abs(dy) / ry);
  return { x: center.x + dx * scale, y: center.y + dy * scale };
}

function computeFlowchartBounds(data) {
  const nodes = data.nodes || [];
  if (!nodes.length) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  for (const node of nodes) {
    if (typeof node.x !== "number" || typeof node.y !== "number") {
      return null;
    }
    const size = getNodeSize(node.type);
    minX = Math.min(minX, node.x);
    minY = Math.min(minY, node.y);
    maxX = Math.max(maxX, node.x + size.w);
    maxY = Math.max(maxY, node.y + size.h);
  }

  if (!Number.isFinite(minX) || !Number.isFinite(minY)) {
    return null;
  }

  const padding = 120;
  return {
    x: minX - padding,
    y: minY - padding,
    width: Math.max(1, maxX - minX + padding * 2),
    height: Math.max(1, maxY - minY + padding * 2),
  };
}

function applyAutoFitViewBox() {
  const bounds = computeFlowchartBounds(flowchart);
  if (!bounds) return;
  const minWidth = 1200;
  const minHeight = 800;
  let { x, y, width, height } = bounds;

  if (width < minWidth) {
    x -= (minWidth - width) / 2;
    width = minWidth;
  }
  if (height < minHeight) {
    y -= (minHeight - height) / 2;
    height = minHeight;
  }

  flowchartCanvas.setAttribute("viewBox", `${x} ${y} ${width} ${height}`);
}

function getNodeById(nodeId) {
  return flowchart.nodes.find((node) => node.id === nodeId);
}

function needsAutoLayout(data) {
  const nodes = data.nodes || [];
  return nodes.some(
    (node) => typeof node.x !== "number" || typeof node.y !== "number"
  );
}

function getIncoming(nodeId) {
  return flowchart.edges.filter((edge) => edge.to === nodeId).map((edge) => edge.from);
}

function autoLayoutFlowchart({ push = false } = {}) {
  if (!flowchart.nodes.length) return;

  const levels = {};
  flowchart.nodes.forEach((node) => {
    levels[node.id] = 0;
  });

  for (let i = 0; i < flowchart.nodes.length; i += 1) {
    let changed = false;
    flowchart.edges.forEach((edge) => {
      const fromLevel = levels[edge.from] ?? 0;
      const nextLevel = fromLevel + 1;
      if ((levels[edge.to] ?? 0) < nextLevel) {
        levels[edge.to] = nextLevel;
        changed = true;
      }
    });
    if (!changed) break;
  }

  const maxLevel = Math.max(...Object.values(levels));
  const levelGroups = Array.from({ length: maxLevel + 1 }, () => []);
  flowchart.nodes.forEach((node) => {
    const lvl = levels[node.id] ?? 0;
    levelGroups[lvl].push(node);
  });

  const orderIndex = {};
  levelGroups.forEach((group, levelIdx) => {
    group.sort((a, b) => {
      if (levelIdx === 0) {
        return a.label.localeCompare(b.label);
      }
      const parentsA = getIncoming(a.id);
      const parentsB = getIncoming(b.id);
      const fallbackA = typeof a.x === "number" ? a.x : 0;
      const fallbackB = typeof b.x === "number" ? b.x : 0;
      const avgA =
        parentsA.length === 0
          ? fallbackA
          : parentsA.reduce((sum, id) => sum + (orderIndex[id] ?? 0), 0) / parentsA.length;
      const avgB =
        parentsB.length === 0
          ? fallbackB
          : parentsB.reduce((sum, id) => sum + (orderIndex[id] ?? 0), 0) / parentsB.length;
      return avgA - avgB;
    });
    group.forEach((node, idx) => {
      orderIndex[node.id] = idx;
    });
  });

  const spacingX = 240;
  const spacingY = 150;
  const paddingX = 120;
  const paddingY = 120;
  const maxGroupSize = Math.max(...levelGroups.map((group) => group.length));
  const width = Math.max(1200, paddingX * 2 + (maxGroupSize - 1) * spacingX);
  const height = Math.max(800, paddingY * 2 + maxLevel * spacingY);

  flowchartCanvas.setAttribute("viewBox", `0 0 ${width} ${height}`);

  levelGroups.forEach((group, levelIdx) => {
    const groupWidth = (group.length - 1) * spacingX;
    const startX = Math.max(paddingX, (width - groupWidth) / 2);
    const y = paddingY + levelIdx * spacingY;
    group.forEach((node, idx) => {
      node.x = startX + idx * spacingX;
      node.y = y;
    });
  });

  setFlowchart(flowchart, { push });
}

function setConnectMode(enabled) {
  connectMode = enabled;
  connectFromId = null;
  connectToggle.classList.toggle("is-active", connectMode);
  connectStatus.textContent = connectMode ? "Connect: select two nodes" : "Connect: off";
}

function setSelectedNode(nodeId) {
  selectedNodeId = nodeId;
  updateInspector();
  renderFlowchart();
}

function updateInspector() {
  const node = selectedNodeId ? getNodeById(selectedNodeId) : null;
  if (!node) {
    nodeLabelInput.value = "";
    nodeLabelInput.disabled = true;
    nodeTypeSelect.disabled = true;
    deleteNode.disabled = true;
    selectedNodeHint.textContent = "None";
    nodeColorRow.querySelectorAll(".color-chip").forEach((chip) => {
      chip.classList.remove("is-active");
    });
    return;
  }

  nodeLabelInput.disabled = false;
  nodeTypeSelect.disabled = false;
  deleteNode.disabled = false;
  nodeLabelInput.value = node.label;
  nodeTypeSelect.value = node.type;
  selectedNodeHint.textContent = node.id;
  nodeColorRow.querySelectorAll(".color-chip").forEach((chip) => {
    chip.classList.toggle("is-active", chip.dataset.color === node.color);
  });
}

function renderFlowchart() {
  edgeLayer.innerHTML = "";
  nodeLayer.innerHTML = "";
  applyAutoFitViewBox();

  const nodePositions = {};
  const nodeMap = {};
  flowchart.nodes.forEach((node) => {
    nodeMap[node.id] = node;
    const size = getNodeSize(node.type);
    nodePositions[node.id] = {
      x: node.x,
      y: node.y,
      w: size.w,
      h: size.h,
    };
  });

  flowchart.edges.forEach((edge) => {
    const fromNode = nodeMap[edge.from];
    const toNode = nodeMap[edge.to];
    if (!fromNode || !toNode) return;
    const start = getConnectionPoint(fromNode, toNode);
    const end = getConnectionPoint(toNode, fromNode);

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${start.x} ${start.y} L ${end.x} ${end.y}`);
    path.setAttribute("stroke", "#2b2d2a");
    path.setAttribute("stroke-width", "2");
    path.setAttribute("fill", "none");
    path.setAttribute("marker-end", "url(#arrowhead)");
    edgeLayer.append(path);

    if (edge.label) {
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.textContent = edge.label;
      label.setAttribute("x", (start.x + end.x) / 2);
      label.setAttribute("y", (start.y + end.y) / 2 - 6);
      label.setAttribute("font-size", "12");
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("fill", "#3a3d3b");
      label.setAttribute("font-family", "Space Grotesk, sans-serif");
      edgeLayer.append(label);
    }
  });

  flowchart.nodes.forEach((node) => {
    const size = getNodeSize(node.type);
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.classList.add("flow-node");
    if (node.id === selectedNodeId) {
      group.classList.add("is-selected");
    }
    group.dataset.id = node.id;
    group.setAttribute("transform", `translate(${node.x}, ${node.y})`);

    const stroke = COLOR_MAP[node.color] || COLOR_MAP.teal;

    if (node.type === "decision") {
      const diamond = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      const points = [
        `${size.w / 2},0`,
        `${size.w},${size.h / 2}`,
        `${size.w / 2},${size.h}`,
        `0,${size.h / 2}`,
      ].join(" ");
      diamond.setAttribute("points", points);
      diamond.setAttribute("fill", stroke);
      diamond.setAttribute("fill-opacity", "0.16");
      diamond.setAttribute("stroke", stroke);
      diamond.setAttribute("stroke-width", "2");
      group.append(diamond);
    } else {
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("width", size.w);
      rect.setAttribute("height", size.h);
      rect.setAttribute("rx", node.type === "start" || node.type === "end" ? size.h / 2 : 16);
      rect.setAttribute("fill", stroke);
      rect.setAttribute("fill-opacity", "0.16");
      rect.setAttribute("stroke", stroke);
      rect.setAttribute("stroke-width", "2");
      group.append(rect);

      if (node.type === "subprocess") {
        const inner = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        inner.setAttribute("x", 8);
        inner.setAttribute("y", 8);
        inner.setAttribute("width", size.w - 16);
        inner.setAttribute("height", size.h - 16);
        inner.setAttribute("rx", 12);
        inner.setAttribute("fill", "none");
        inner.setAttribute("stroke", stroke);
        inner.setAttribute("stroke-width", "1.5");
        group.append(inner);
      }
    }

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.textContent = node.label;
    text.setAttribute("x", size.w / 2);
    text.setAttribute("y", size.h / 2 + 5);
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("font-size", "14");
    text.setAttribute("font-family", "Space Grotesk, sans-serif");
    text.setAttribute("fill", "#1f2422");
    group.append(text);

    nodeLayer.append(group);
  });
}

function addNode(type) {
  const size = getNodeSize(type);
  const viewBox = flowchartCanvas.viewBox.baseVal;
  const x = viewBox.x + viewBox.width / 2 - size.w / 2 + Math.random() * 40 - 20;
  const y = viewBox.y + viewBox.height / 2 - size.h / 2 + Math.random() * 40 - 20;
  const id = `n${Date.now().toString(36).slice(-5)}`;
  flowchart.nodes.push({ id, type, label: "New step", x, y, color: activeColor });
  setSelectedNode(id);
  setFlowchart(flowchart, { push: true });
}

function removeNode(nodeId) {
  flowchart.nodes = flowchart.nodes.filter((node) => node.id !== nodeId);
  flowchart.edges = flowchart.edges.filter(
    (edge) => edge.from !== nodeId && edge.to !== nodeId
  );
  selectedNodeId = null;
  setFlowchart(flowchart, { push: true });
}

function addEdge(fromId, toId) {
  if (fromId === toId) return;
  const exists = flowchart.edges.some(
    (edge) => edge.from === fromId && edge.to === toId
  );
  if (exists) return;
  flowchart.edges.push({ from: fromId, to: toId, label: "" });
  setFlowchart(flowchart, { push: true });
}

function exportFlowchartImage() {
  return new Promise((resolve, reject) => {
    const svgClone = flowchartCanvas.cloneNode(true);
    svgClone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    svgClone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");

    const bounds = computeFlowchartBounds(flowchart);
    if (bounds) {
      svgClone.setAttribute(
        "viewBox",
        `${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`
      );
    }

    const serializer = new XMLSerializer();
    const svgString = serializer.serializeToString(svgClone);
    const svgBlob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);

    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      const vb = bounds || flowchartCanvas.viewBox.baseVal;
      canvas.width = vb.width || 1200;
      canvas.height = vb.height || 800;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#fffaf0";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/png"));
    };
    img.onerror = (err) => {
      URL.revokeObjectURL(url);
      reject(err);
    };
    img.src = url;
  });
}

async function sendChatMessage() {
  if (!chatInput || !sendChat) return;
  const message = chatInput.value.trim();
  if (!message) return;
  sendChat.disabled = true;
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: withSession({ "Content-Type": "application/json" }),
      body: JSON.stringify({ message, flowchart }),
    });
    if (!res.ok) {
      return;
    }
    chatInput.value = "";
  } finally {
    sendChat.disabled = false;
  }
}

function resetRunView() {
  state.conversation = [];
  renderConversation([]);
  analysisStack.innerHTML = "";
}

function setUploadPreview(src) {
  if (!uploadPreview) return;
  uploadPreview.innerHTML = `<img src="${src}" alt="Workflow preview" />`;
}

function clearUploadPreview() {
  if (!uploadPreview) return;
  uploadPreview.innerHTML = DEFAULT_PREVIEW_HTML;
  try {
    sessionStorage.removeItem(PREVIEW_KEY);
  } catch (err) {
    // Ignore storage failures.
  }
}

function restoreUploadPreview() {
  if (!uploadPreview) return;
  const stored = sessionStorage.getItem(PREVIEW_KEY);
  if (stored) {
    setUploadPreview(stored);
  }
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("FileReader failed"));
    reader.readAsDataURL(file);
  });
}

async function runFlowchartPipeline() {
  runPipeline.disabled = true;
  resetRunView();
  clearUploadPreview();
  try {
    const imageData = await exportFlowchartImage();
    const nameValue = workflowName ? workflowName.value.trim() : "";
    const res = await fetch("/api/flowchart/run", {
      method: "POST",
      headers: withSession({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        image_data: imageData,
        workflow_name: nameValue,
        flowchart,
      }),
    });
  if (!res.ok) {
    runPipeline.disabled = false;
    return;
  }
  const data = await res.json();
    if (data.workflow_name) {
      state.workflowName = data.workflow_name;
    }
    applyStage("idle");
  } finally {
    runPipeline.disabled = false;
  }
}

async function uploadFile(file) {
  resetRunView();
  const formData = new FormData();
  formData.append("file", file);
  const nameValue = workflowName ? workflowName.value.trim() : "";
  if (nameValue) {
    formData.append("workflow_name", nameValue);
  }
  uploadHint.textContent = "Uploading...";
  const res = await fetch("/api/upload", {
    method: "POST",
    headers: withSession(),
    body: formData,
  });
  if (!res.ok) {
    uploadHint.textContent = "Upload failed.";
    fetchState();
    return;
  }
  const data = await res.json();
  if (data.workflow_name) {
    state.workflowName = data.workflow_name;
    if (workflowName) {
      workflowName.value = data.workflow_name;
    }
  }
  try {
    const dataUrl = await readFileAsDataUrl(file);
    if (typeof dataUrl === "string") {
      setUploadPreview(dataUrl);
      sessionStorage.setItem(PREVIEW_KEY, dataUrl);
    }
  } catch (err) {
    const url = URL.createObjectURL(file);
    setUploadPreview(url);
  }
  uploadHint.textContent = "Upload complete. Ask the orchestrator to analyze.";
  applyStage("idle");
}

async function fetchState() {
  const res = await fetch("/api/state", { headers: withSession() });
  if (!res.ok) return;
  const payload = await res.json();
  state.conversation = payload.conversation || [];
  state.workflowName = payload.workflow_name || "";
  if (workflowName) {
    workflowName.value = state.workflowName;
  }
  renderConversation(state.conversation);
  const hasAnalysis = payload.analysis || payload.revision;
  if (hasAnalysis) {
    renderAnalysisRevision(
      payload.inputs || [],
      payload.outputs || [],
      payload.revision || 0
    );
  }
  if (payload.test_progress && payload.test_progress.total) {
    updateTestsProgress(payload.test_progress);
  }
  if (payload.iterations && payload.iterations.length) {
    payload.iterations.forEach(addIteration);
  }
  if (payload.generated_code_path) {
    showDownload("/api/download");
  }
  if (payload.stage === "analyzing") {
    showThinking(true);
  }
  if (payload.flowchart) {
    setFlowchart(payload.flowchart, { push: true });
  } else if (!history.length) {
    const starter = {
      nodes: [
        { id: "start", type: "start", label: "Start", x: 160, y: 120, color: "teal" },
      ],
      edges: [],
    };
    setFlowchart(starter, { push: true });
  }
  if (payload.workflow_image) {
    restoreUploadPreview();
  } else {
    clearUploadPreview();
  }
  applyStage(payload.stage || "idle");
}

flowchartCanvas.addEventListener("pointerdown", (event) => {
  const target = event.target.closest(".flow-node");
  if (!target) {
    setSelectedNode(null);
    return;
  }
  const nodeId = target.dataset.id;
  if (!nodeId) return;

  if (connectMode) {
    if (!connectFromId) {
      connectFromId = nodeId;
      connectStatus.textContent = `Connect: ${nodeId} selected`;
    } else {
      addEdge(connectFromId, nodeId);
      connectFromId = null;
      connectStatus.textContent = "Connect: select two nodes";
    }
    return;
  }

  const node = getNodeById(nodeId);
  if (!node) return;
  setSelectedNode(nodeId);

  dragState = {
    nodeId,
    startX: event.clientX,
    startY: event.clientY,
    originX: node.x,
    originY: node.y,
  };
  dragDirty = false;
  flowchartCanvas.setPointerCapture(event.pointerId);
});

flowchartCanvas.addEventListener("pointermove", (event) => {
  if (!dragState) return;
  const node = getNodeById(dragState.nodeId);
  if (!node) return;
  const dx = event.clientX - dragState.startX;
  const dy = event.clientY - dragState.startY;
  node.x = dragState.originX + dx;
  node.y = dragState.originY + dy;
  dragDirty = true;
  renderFlowchart();
});

flowchartCanvas.addEventListener("pointerup", (event) => {
  if (!dragState) return;
  flowchartCanvas.releasePointerCapture(event.pointerId);
  dragState = null;
  if (dragDirty) {
    setFlowchart(flowchart, { push: true });
  }
  dragDirty = false;
});

nodeLabelInput.addEventListener("input", () => {
  if (!selectedNodeId) return;
  const node = getNodeById(selectedNodeId);
  if (!node) return;
  node.label = nodeLabelInput.value;
  renderFlowchart();
});

nodeLabelInput.addEventListener("change", () => {
  if (selectedNodeId) {
    setFlowchart(flowchart, { push: true });
  }
});

nodeTypeSelect.addEventListener("change", () => {
  if (!selectedNodeId) return;
  const node = getNodeById(selectedNodeId);
  if (!node) return;
  node.type = nodeTypeSelect.value;
  setFlowchart(flowchart, { push: true });
});

nodeColorRow.addEventListener("click", (event) => {
  const chip = event.target.closest(".color-chip");
  if (!chip) return;
  const color = chip.dataset.color;
  if (!color) return;
  if (selectedNodeId) {
    const node = getNodeById(selectedNodeId);
    if (!node) return;
    node.color = color;
    setFlowchart(flowchart, { push: true });
  }
});

paletteColors.addEventListener("click", (event) => {
  const chip = event.target.closest(".color-chip");
  if (!chip) return;
  const color = chip.dataset.color;
  if (!color) return;
  activeColor = color;
  paletteColors.querySelectorAll(".color-chip").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.color === color);
  });
});

document.querySelectorAll(".palette-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    addNode(btn.dataset.type || "process");
  });
});

historyBack.addEventListener("click", () => {
  if (historyIndex <= 0) return;
  historyIndex -= 1;
  setFlowchart(history[historyIndex]);
  updateHistoryButtons();
});

historyForward.addEventListener("click", () => {
  if (historyIndex >= history.length - 1) return;
  historyIndex += 1;
  setFlowchart(history[historyIndex]);
  updateHistoryButtons();
});

snapshotFlowchart.addEventListener("click", () => {
  pushHistory(flowchart);
});

connectToggle.addEventListener("click", () => {
  setConnectMode(!connectMode);
});

autoLayout.addEventListener("click", () => {
  autoLayoutFlowchart({ push: true });
});

clearCanvas.addEventListener("click", () => {
  flowchart = { nodes: [], edges: [] };
  setSelectedNode(null);
  setFlowchart(flowchart, { push: true });
});

exportPreview.addEventListener("click", async () => {
  const dataUrl = await exportFlowchartImage();
  window.open(dataUrl, "_blank", "noopener");
});

deleteNode.addEventListener("click", () => {
  if (selectedNodeId) {
    removeNode(selectedNodeId);
  }
});

if (sendChat) {
  sendChat.addEventListener("click", sendChatMessage);
}
if (chatInput) {
  chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendChatMessage();
    }
  });
}

runPipeline.addEventListener("click", runFlowchartPipeline);
clearState.addEventListener("click", async () => {
  clearState.disabled = true;
  try {
    await fetch("/api/reset", { method: "POST", headers: withSession() });
  } finally {
    clearState.disabled = false;
  }
});

uploadButton.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) uploadFile(file);
});

mountStageInThread(thinkingCard, "thinking");
mountStageInThread(analysisStack, "analysis");
mountStageInThread(testsCard, "tests");
mountStageInThread(iterationsCard, "iterations");
mountStageInThread(downloadCard, "download");

fetchState();

const source = new EventSource(`/events?session_id=${SESSION_ID}`);
source.onmessage = (event) => {
  const payload = JSON.parse(event.data);
  if (payload.type === "ping") return;
  handleEvent(payload);
};
