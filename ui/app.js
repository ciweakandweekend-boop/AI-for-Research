const AGENTS = [
  { id: "planner", name: "Planner", model: "Qwen3.8-Max", icon: "⌁", accent: "violet" },
  { id: "loader", name: "PDF Loader", model: "Python / PyPDF2", icon: "▤", accent: "cyan" },
  { id: "reader", name: "Paper Reader", model: "Qwen3.8-Max", icon: "◫", accent: "blue" },
  { id: "hypothesis", name: "Hypothesis Generator", model: "GPT-OSS-120B", icon: "✦", accent: "orange" },
  { id: "critic", name: "Critical Reviewer", model: "Claude Sonnet 4.6", icon: "◇", accent: "pink" },
  { id: "director", name: "Scientific Director", model: "Claude Sonnet 4.6", icon: "◈", accent: "green" },
];

const $ = (selector) => document.querySelector(selector);
let selectedMode = "live";
let currentRunId = null;
let currentData = null;
let pollTimer = null;
let activeTab = "evidence";
let selectedStage = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortText(value, max = 150) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function formatMs(ms) {
  if (ms === undefined || ms === null || ms === "") return "—";
  const value = Number(ms);
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
}

function formatTime(timestamp) {
  if (!timestamp) return "";
  try { return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
  catch { return ""; }
}

function latestEvent(data, id) {
  return [...(data?.events || [])].reverse().find((event) => event.phase === id);
}

function latestTrace(data, id) {
  return [...(data?.trace || [])].reverse().find((entry) => entry.agent === id);
}

function stageStatus(data, id) {
  const event = latestEvent(data, id);
  if (event) return event.status;
  if (data?.status === "error" && data.phase === id) return "error";
  return "queued";
}

function countSummary(data) {
  const state = data?.state;
  const lastEvent = [...(data?.events || [])].reverse().find((event) => event.counts);
  return {
    papers: state?.papers ? new Set(state.papers.map((p) => p.paper_id)).size : (lastEvent?.counts?.papers || 0),
    evidence: state?.evidence?.length ?? (lastEvent?.counts?.evidence || 0),
    hypotheses: state?.hypotheses?.length ?? (lastEvent?.counts?.hypotheses || 0),
  };
}

function resultFor(id, data) {
  const state = data?.state;
  const event = latestEvent(data, id);
  const liveResult = event?.result || {};
  if (id === "loader") return `${countSummary(data).papers || 5} local PDFs indexed`;
  if (id === "planner") {
    const plan = state?.plan || liveResult;
    return shortText((plan.subquestions || []).join(" · ") || "Research plan structured", 115);
  }
  if (id === "reader") {
    const evidence = state?.evidence || liveResult.evidence || [];
    const first = evidence[0];
    return `${evidence.length || 0} evidence records${first ? ` · ${shortText(first.claim, 72)}` : ""}`;
  }
  if (id === "hypothesis") {
    const hypotheses = state?.hypotheses || liveResult.hypotheses || [];
    const first = hypotheses[0];
    return `${hypotheses.length || 0} hypotheses${first ? ` · ${shortText(first.hypothesis, 70)}` : ""}`;
  }
  if (id === "critic") {
    const critique = state?.critique || liveResult;
    return `${String(critique.status || "reviewed").toUpperCase()} · ${(critique.findings || []).length} findings`;
  }
  if (id === "director") return shortText(state?.final_report?.summary || liveResult.summary || "Final report assembled", 115);
  return event?.label || "";
}

function renderPipeline(data) {
  $("#pipeline").innerHTML = AGENTS.map((agent) => {
    const status = stageStatus(data, agent.id);
    const trace = latestTrace(data, agent.id);
    const event = latestEvent(data, agent.id);
    const retry = trace?.retry_count ? `<span class="retry-pill">↻ ${trace.retry_count}</span>` : "";
    const timing = trace ? formatMs(trace.latency_ms) : (agent.id === "loader" ? "local" : "—");
    const statusLabel = status === "completed" ? "complete" : status === "running" ? "working" : status === "repairing" ? "repairing" : status === "error" ? "failed" : "waiting";
    return `<article class="stage ${escapeHtml(status)}" style="--accent: var(--${agent.accent})" data-stage="${agent.id}">
      <div class="stage-icon">${agent.icon}</div>
      <div class="stage-name">${agent.name}</div>
      <div class="stage-model">${agent.model}</div>
      <div class="stage-status"><i></i>${statusLabel}</div>
      <div class="stage-timing"><span>${timing}</span>${retry}</div>
      <div class="stage-result">${escapeHtml(resultFor(agent.id, data))}</div>
    </article>`;
  }).join("");
  const done = AGENTS.filter((agent) => stageStatus(data, agent.id) === "completed").length;
  $("#pipeline-caption").textContent = data?.status === "completed" ? "All stages complete · state persisted to runs/" : `${done} / ${AGENTS.length} stages complete · click a run mode to begin`;
  document.querySelectorAll(".stage").forEach((stage) => stage.addEventListener("click", () => showStageDetail(stage.dataset.stage, currentData || data)));
}

function renderActivity(data) {
  const events = data?.events || [];
  const list = $("#activity-list");
  if (!events.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon">⌁</span><strong>No run yet</strong><span>Every stage will narrate its work here.</span></div>`;
    return;
  }
  list.innerHTML = events.slice(-24).reverse().map((event) => {
    const status = event.status || "queued";
    const name = AGENTS.find((agent) => agent.id === event.phase)?.name || event.phase;
    return `<div class="activity-item ${escapeHtml(status)}"><i class="activity-dot"></i><div class="activity-main"><strong>${escapeHtml(name)}</strong><span>${escapeHtml(event.label || status)}</span></div><time class="activity-time">${formatTime(event.timestamp)}</time></div>`;
  }).join("");
}

function renderTrace(data) {
  const trace = data?.trace || [];
  $("#trace-count").textContent = `${trace.length} call${trace.length === 1 ? "" : "s"}`;
  if (!trace.length) {
    $("#trace-summary").innerHTML = `<div class="trace-empty">Latency and retry telemetry will appear after the first model call.</div>`;
    return;
  }
  $("#trace-summary").innerHTML = trace.slice().reverse().map((entry) => `<div class="trace-row">
    <div><div class="trace-agent">${escapeHtml(entry.agent)}</div><div class="trace-model">${escapeHtml(entry.model)} · ${entry.cache_hit ? "cache hit" : "provider call"}</div></div>
    <div class="trace-latency">${formatMs(entry.latency_ms)}</div>
    ${entry.retry_count ? `<span class="retry-pill">↻ ${entry.retry_count}</span>` : `<i class="${entry.status === "success" ? "trace-ok" : "trace-fail"}"></i>`}
  </div>`).join("");
}

function evidenceHtml(state) {
  const evidence = state?.evidence || [];
  if (!evidence.length) return `<div class="empty-state"><span class="empty-icon">◌</span><strong>No evidence yet</strong><span>The Paper Reader will populate this gate.</span></div>`;
  return `<div class="evidence-list">${evidence.map((item) => `<article class="evidence-item">
    <div class="item-meta"><strong>${escapeHtml(item.claim_id)}</strong><span class="confidence">confidence ${(Number(item.confidence) * 100).toFixed(0)}%</span></div>
    <div class="item-title">${escapeHtml(item.claim)}</div>
    <div class="quote">“${escapeHtml(item.quote)}”</div>
    <div class="item-meta" style="margin-top:10px"><span>${escapeHtml(item.paper_id)} · page ${escapeHtml(item.page)}</span><span>source locked</span></div>
  </article>`).join("")}</div>`;
}

function hypothesesHtml(state) {
  const hypotheses = state?.hypotheses || [];
  if (!hypotheses.length) return `<div class="empty-state"><span class="empty-icon">✦</span><strong>No hypotheses yet</strong><span>Hypotheses are generated only from extracted evidence.</span></div>`;
  return `<div class="hypothesis-list">${hypotheses.map((item) => `<article class="hypothesis-item">
    <div class="item-meta"><strong>${escapeHtml(item.hypothesis_id)}</strong><span>${escapeHtml((item.evidence_ids || []).join(", ") || "no refs")}</span></div>
    <div class="item-title">${escapeHtml(item.hypothesis)}</div>
    <div class="quote"><b>Mechanism:</b> ${escapeHtml(item.mechanism || "—")}<br /><b>Predictions:</b> ${escapeHtml((item.predictions || []).join(" · ") || "—")}</div>
  </article>`).join("")}</div>`;
}

function critiqueHtml(state) {
  const critique = state?.critique || {};
  if (!Object.keys(critique).length) return `<div class="empty-state"><span class="empty-icon">◇</span><strong>Review pending</strong><span>The Critical Reviewer will challenge unsupported claims.</span></div>`;
  const status = String(critique.status || "reviewed").toLowerCase();
  return `<div class="critique-block"><span class="status-ribbon ${escapeHtml(status)}">${escapeHtml(status.toUpperCase())}</span>
    <h3 style="margin-top:17px">Findings</h3><p>${escapeHtml((critique.findings || []).join("\n") || "No findings returned.")}</p>
    <h3 style="margin-top:17px">Unsupported claims</h3><p>${escapeHtml((critique.unsupported_claims || []).join("\n") || "None flagged.")}</p>
    <h3 style="margin-top:17px">Required repairs</h3><p>${escapeHtml((critique.required_repairs || []).join("\n") || "No repair requested.")}</p></div>`;
}

function reportHtml(state) {
  const report = state?.final_report;
  if (!report || !Object.keys(report).length) return `<div class="empty-state"><span class="empty-icon">◈</span><strong>Final report pending</strong><span>The Scientific Director will synthesize the checked state.</span></div>`;
  const list = (value) => Array.isArray(value) ? value.map((item) => `• ${escapeHtml(item)}`).join("<br />") : escapeHtml(value);
  return `<div class="report-block"><h1 class="report-title">${escapeHtml(report.title || "Research report")}</h1><h3>Answer</h3><p>${escapeHtml(report.summary || "")}</p></div>
    <div class="report-block"><h3>Evidence used</h3><p>${(report.evidence || []).map((ref) => `• ${escapeHtml(ref.claim_id)} · ${escapeHtml(ref.paper_id)}, p. ${escapeHtml(ref.page)}`).join("<br />") || "None"}</p></div>
    <div class="report-block"><h3>Limitations</h3><p>${list(report.limitations || [])}</p></div>
    <div class="report-block"><h3>Next experiment</h3><p>${list(report.next_experiment || "")}</p></div>`;
}

function fullTraceHtml(data) {
  const trace = data?.trace || [];
  if (!trace.length) return `<div class="empty-state"><span class="empty-icon">⌁</span><strong>No trace records</strong><span>Every model call will appear here.</span></div>`;
  return `<div class="full-trace"><table class="trace-table"><thead><tr><th>Agent</th><th>Model</th><th>Source</th><th>Latency</th><th>Retries</th><th>Status</th></tr></thead><tbody>${trace.map((entry) => `<tr><td>${escapeHtml(entry.agent)}</td><td>${escapeHtml(entry.model)}</td><td>${entry.cache_hit ? "cache" : escapeHtml(entry.mode || "live")}</td><td>${formatMs(entry.latency_ms)}</td><td>${escapeHtml(entry.retry_count || 0)}</td><td class="status-${escapeHtml(entry.status)}">${escapeHtml(entry.status)}</td></tr>`).join("")}</tbody></table></div>`;
}

function showStageDetail(id, data) {
  selectedStage = id;
  const agent = AGENTS.find((item) => item.id === id) || { name: id, model: "" };
  const event = latestEvent(data, id);
  const trace = latestTrace(data, id);
  const result = event?.result || {};
  $("#tab-content").innerHTML = `<div class="report-block"><div class="item-meta"><strong>${escapeHtml(agent.name)}</strong><span>${escapeHtml(agent.model)}</span></div><h3 style="margin-top:17px">What this stage did</h3><p>${escapeHtml(event?.label || "Waiting for this stage")}</p><h3 style="margin-top:17px">Provider round-trip</h3><p>${trace ? `${formatMs(trace.latency_ms)} · ${trace.retry_count || 0} retries · ${trace.cache_hit ? "cache replay" : "provider call"}` : "No completed call yet."}</p><h3 style="margin-top:17px">Structured result</h3><pre class="json-result">${escapeHtml(JSON.stringify(result, null, 2) || "Waiting for result")}</pre></div>`;
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
}

function renderInspector(data) {
  const state = data?.state || {};
  const content = { evidence: evidenceHtml(state), hypotheses: hypothesesHtml(state), critique: critiqueHtml(state), report: reportHtml(state), trace: fullTraceHtml(data) };
  $("#tab-content").innerHTML = content[activeTab];
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === activeTab));
  if (selectedStage) showStageDetail(selectedStage, data);
}

function render(data) {
  currentData = data;
  const summary = countSummary(data);
  $("#paper-count").textContent = summary.papers;
  $("#evidence-count").textContent = summary.evidence;
  $("#hypothesis-count").textContent = summary.hypotheses;
  $("#metric-mode").textContent = data?.mode ? data.mode.toUpperCase() : "STANDBY";
  $("#metric-id").textContent = data?.run_id ? data.run_id.slice(-7) : "—";
  $("#metric-mode").style.color = data?.mode === "replay" ? "var(--cyan)" : "var(--violet)";
  $("#feed-badge").textContent = data?.status ? data.status.toUpperCase() : "IDLE";
  $("#feed-badge").className = `live-badge ${data?.status === "running" ? "active" : data?.status === "completed" ? "done" : ""}`;
  const status = $("#run-status");
  status.className = `run-status ${data?.status || ""}`;
  $("#status-text").textContent = data?.error ? shortText(data.error, 80) : data?.status === "running" ? `Working · ${data.phase}` : data?.status === "completed" ? "Research run complete" : data?.status === "queued" ? "Queued" : "Ready for a research run";
  $("#hero-metric")?.classList.toggle("active", data?.status === "running");
  $(".hero-metric").classList.toggle("active", data?.status === "running");
  renderPipeline(data || {});
  renderActivity(data || {});
  renderTrace(data || {});
  renderInspector(data || {});
  $("#run-button").disabled = data?.status === "running" || data?.status === "queued";
  if (data?.status === "completed") $("#run-button").innerHTML = `<span class="run-button-icon">↻</span><span>Run again</span><span class="button-arrow">↗</span>`;
  else if (data?.status === "error") $("#run-button").innerHTML = `<span class="run-button-icon">↻</span><span>Retry run</span><span class="button-arrow">↗</span>`;
}

async function poll() {
  if (!currentRunId) return;
  try {
    const response = await fetch(`/api/run/${encodeURIComponent(currentRunId)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Run not found");
    render(data);
    if (data.status === "running" || data.status === "queued") pollTimer = setTimeout(poll, 750);
  } catch (error) {
    $("#status-text").textContent = error.message;
  }
}

async function startRun() {
  const button = $("#run-button");
  button.disabled = true;
  button.innerHTML = `<span class="run-button-icon">⋯</span><span>Starting run</span><span class="button-arrow">↗</span>`;
  try {
    const response = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: $("#question").value, mode: selectedMode, timeout: Number($("#timeout").value), retries: Number($("#retries").value) }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Unable to start run");
    currentRunId = result.run_id;
    await poll();
  } catch (error) {
    render({ status: "error", error: error.message, mode: selectedMode, events: [], trace: [] });
    button.disabled = false;
  }
}

document.querySelectorAll(".mode-btn").forEach((button) => button.addEventListener("click", () => {
  selectedMode = button.dataset.mode;
  document.querySelectorAll(".mode-btn").forEach((item) => item.classList.toggle("active", item === button));
  $("#mode-note").textContent = selectedMode === "live" ? "Live calls providers, retries transient failures, and writes cache + trace." : "Replay reads matching structured cache entries only — no provider call is made.";
}));
document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => { selectedStage = null; activeTab = button.dataset.tab; renderInspector(currentData || {}); }));
$("#run-button").addEventListener("click", startRun);
render({ status: "idle", mode: selectedMode, events: [], trace: [], state: null });
