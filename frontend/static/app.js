const thread = document.getElementById("thread");
const analysisCard = document.getElementById("analysisCard");
const inputsList = document.getElementById("inputsList");
const outputsList = document.getElementById("outputsList");
const analysisRevision = document.getElementById("analysisRevision");
const approveButton = document.getElementById("approveButton");
const feedbackToggle = document.getElementById("feedbackToggle");
const feedbackPanel = document.getElementById("feedbackPanel");
const feedbackInput = document.getElementById("feedbackInput");
const sendFeedback = document.getElementById("sendFeedback");
const cancelFeedback = document.getElementById("cancelFeedback");
const feedbackChips = document.getElementById("feedbackChips");
const thinkingCard = document.getElementById("thinkingCard");
const testsCard = document.getElementById("testsCard");
const testsBar = document.getElementById("testsBar");
const testsPercent = document.getElementById("testsPercent");
const testsDetail = document.getElementById("testsDetail");
const iterationsCard = document.getElementById("iterationsCard");
const iterationsList = document.getElementById("iterationsList");
const downloadCard = document.getElementById("downloadCard");
const downloadButton = document.getElementById("downloadButton");
const edgeCard = document.getElementById("edgeCard");
const edgeInput = document.getElementById("edgeInput");
const sendEdgeCase = document.getElementById("sendEdgeCase");
const fileInput = document.getElementById("fileInput");
const uploadButton = document.getElementById("uploadButton");
const uploadGrid = document.getElementById("uploadGrid");
const uploadPanel = document.getElementById("uploadPanel");
const uploadPreview = document.getElementById("uploadPreview");
const uploadHint = document.getElementById("uploadHint");
const workflowName = document.getElementById("workflowName");

const state = {
  conversation: [],
  analysis: null,
  inputs: [],
  outputs: [],
  revision: 0,
  workflowName: "",
};

function ensureVisible(el) {
  if (!el.classList.contains("is-visible")) {
    el.classList.add("is-visible");
  }
}

function hideElement(el) {
  if (!el.classList.contains("is-hidden")) {
    el.classList.add("is-hidden");
  }
}

function showElement(el) {
  el.classList.remove("is-hidden");
}

function hideVisible(el) {
  if (el.classList.contains("is-visible")) {
    el.classList.remove("is-visible");
  }
}

function renderMessage(msg) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${msg.role}`;
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = msg.role === "user" ? "You" : "Orchestrator";
  const body = document.createElement("div");
  body.textContent = msg.content;
  wrapper.append(meta, body);
  thread.append(wrapper);
}

function renderConversation(messages) {
  thread.innerHTML = "";
  messages.forEach(renderMessage);
}

function renderAnalysis(inputs, outputs, revision) {
  inputsList.innerHTML = "";
  outputsList.innerHTML = "";
  analysisRevision.textContent = `Revision ${revision}`;

  inputs.forEach((input) => {
    const card = document.createElement("div");
    card.className = "input-card";
    const name = document.createElement("h5");
    name.textContent = input.input_name || "Unnamed input";
    const meta = document.createElement("div");
    meta.className = "input-meta";
    meta.textContent = buildRangeText(input);
    card.append(name, meta);

    if (Array.isArray(input.range)) {
      const values = document.createElement("div");
      values.className = "outputs";
      input.range.slice(0, 8).forEach((value) => {
        const chip = document.createElement("div");
        chip.className = "output-chip";
        chip.textContent = value;
        values.append(chip);
      });
      card.append(values);
    } else {
      const desc = document.createElement("div");
      desc.className = "input-meta";
      desc.textContent = input.description || "No description";
      card.append(desc);
    }
    inputsList.append(card);
  });

  outputs.forEach((output) => {
    const chip = document.createElement("div");
    chip.className = "output-chip";
    chip.textContent = output;
    outputsList.append(chip);
  });

  ensureVisible(analysisCard);
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
  const unit = input.range.unit ? ` ${input.range.unit}` : "";
  if (value !== undefined && value !== null) {
    return `Type: ${type} | Value: ${value}${unit}`;
  }
  if (min !== undefined && max !== undefined && min !== null && max !== null) {
    return `Type: ${type} | Range: ${min}${unit} to ${max}${unit}`;
  }
  if (min !== undefined && min !== null) {
    return `Type: ${type} | Range: >= ${min}${unit}`;
  }
  if (max !== undefined && max !== null) {
    return `Type: ${type} | Range: <= ${max}${unit}`;
  }
  return `Type: ${type} | Range: unbounded`;
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
  row.innerHTML = `<span>Iteration ${iteration.iteration}</span><strong>${(iteration.score * 100).toFixed(1)}%</strong>`;
  iterationsList.append(row);
}

function showDownload(url) {
  downloadButton.href = url;
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

function resetUi() {
  state.conversation = [];
  renderConversation([]);
  inputsList.innerHTML = "";
  outputsList.innerHTML = "";
  iterationsList.innerHTML = "";
  testsBar.style.width = "0%";
  testsPercent.textContent = "0%";
  testsDetail.textContent = "Waiting to start.";
  hideVisible(analysisCard);
  hideVisible(testsCard);
  hideVisible(iterationsCard);
  hideVisible(downloadCard);
  hideVisible(edgeCard);
  showElement(uploadPanel);
}

function applyStage(stage) {
  if (stage === "idle") {
    showElement(uploadPanel);
    hideVisible(thinkingCard);
    hideVisible(analysisCard);
    hideVisible(testsCard);
    hideVisible(iterationsCard);
    hideVisible(downloadCard);
    hideVisible(edgeCard);
    approveButton.classList.remove("is-hidden");
    feedbackToggle.classList.remove("is-hidden");
    return;
  }

  if (stage === "analyzing") {
    showElement(uploadPanel);
    showThinking(true);
    hideVisible(testsCard);
    hideVisible(iterationsCard);
    hideVisible(downloadCard);
    hideVisible(edgeCard);
    return;
  }

  if (stage === "awaiting_approval") {
    showThinking(false);
    ensureVisible(analysisCard);
    showElement(uploadPanel);
    approveButton.classList.remove("is-hidden");
    feedbackToggle.classList.remove("is-hidden");
    hideVisible(testsCard);
    hideVisible(iterationsCard);
    hideVisible(downloadCard);
    hideVisible(edgeCard);
    return;
  }

  if (stage === "tests_running") {
    hideElement(uploadPanel);
    ensureVisible(analysisCard);
    approveButton.classList.add("is-hidden");
    feedbackToggle.classList.add("is-hidden");
    feedbackPanel.classList.remove("is-visible");
    ensureVisible(testsCard);
    hideVisible(downloadCard);
    hideVisible(edgeCard);
  }

  if (stage === "code_refining") {
    ensureVisible(iterationsCard);
    hideVisible(edgeCard);
  }

  if (stage === "done") {
    ensureVisible(downloadCard);
    ensureVisible(edgeCard);
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
    renderAnalysis(state.inputs, state.outputs, state.revision);
    showThinking(false);
  }
  if (event.type === "approval_requested") {
    ensureVisible(analysisCard);
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
  }
  if (event.type === "artifact_ready") {
    showDownload(event.data.download_url);
  }
  if (event.type === "state_reset") {
    window.location.reload();
  }
}

async function fetchState() {
  const res = await fetch("/api/state");
  if (!res.ok) return;
  const payload = await res.json();
  state.conversation = payload.conversation || [];
  state.workflowName = payload.workflow_name || "";
  renderConversation(state.conversation);
  if (payload.inputs && payload.outputs && payload.inputs.length) {
    renderAnalysis(payload.inputs, payload.outputs, payload.revision || 0);
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
  applyStage(payload.stage || "idle");
}

async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  const nameValue = workflowName ? workflowName.value.trim() : "";
  if (nameValue) {
    formData.append("workflow_name", nameValue);
  }
  uploadHint.textContent = "Uploading...";
  const res = await fetch("/api/upload", { method: "POST", body: formData });
  if (!res.ok) {
    uploadHint.textContent = "Upload failed.";
    return;
  }
  const data = await res.json();
  if (data.workflow_name) {
    state.workflowName = data.workflow_name;
  }
  resetUi();
  applyStage("analyzing");
  const url = URL.createObjectURL(file);
  uploadPreview.innerHTML = `<img src="${url}" alt="Workflow preview" />`;
  uploadHint.textContent = "Upload complete. Running analysis...";
}

uploadButton.addEventListener("click", () => fileInput.click());
uploadGrid.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) uploadFile(file);
});

uploadGrid.addEventListener("dragover", (event) => {
  event.preventDefault();
  uploadGrid.classList.add("dragging");
});

uploadGrid.addEventListener("dragleave", () => {
  uploadGrid.classList.remove("dragging");
});

uploadGrid.addEventListener("drop", (event) => {
  event.preventDefault();
  uploadGrid.classList.remove("dragging");
  const file = event.dataTransfer.files[0];
  if (file) uploadFile(file);
});

approveButton.addEventListener("click", async () => {
  approveButton.disabled = true;
  approveButton.classList.add("is-hidden");
  feedbackToggle.classList.add("is-hidden");
  hideElement(uploadPanel);
  await fetch("/api/analysis/approve", { method: "POST" });
  approveButton.disabled = false;
});

feedbackToggle.addEventListener("click", () => {
  feedbackPanel.classList.toggle("is-visible");
});

cancelFeedback.addEventListener("click", () => {
  feedbackPanel.classList.remove("is-visible");
  feedbackInput.value = "";
});

sendFeedback.addEventListener("click", async () => {
  const feedback = feedbackInput.value.trim();
  if (!feedback) return;
  sendFeedback.disabled = true;
  await fetch("/api/analysis/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
  sendFeedback.disabled = false;
  feedbackInput.value = "";
  feedbackPanel.classList.remove("is-visible");
});

feedbackChips.addEventListener("click", (event) => {
  if (!event.target.classList.contains("chip")) return;
  const text = event.target.dataset.chip;
  feedbackInput.value = feedbackInput.value ? `${feedbackInput.value} ${text}` : text;
});

sendEdgeCase.addEventListener("click", async () => {
  const message = edgeInput.value.trim();
  if (!message) return;
  sendEdgeCase.disabled = true;
  await fetch("/api/edge-case", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  sendEdgeCase.disabled = false;
  edgeInput.value = "";
});

fetchState();

const source = new EventSource("/events");
source.onmessage = (event) => {
  const payload = JSON.parse(event.data);
  if (payload.type === "ping") return;
  handleEvent(payload);
};
