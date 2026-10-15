// F4 dashboard: mission state + real SSE events only. No fabricated progress.
// Snapshot reducer: history seed + live tail share one applyEvent path.
// Reconnect replays via Last-Event-ID (?lastEventId=); server sends retry: 3000.
(() => {
  const connEl = document.getElementById("conn");
  const titleEl = document.getElementById("mission-title");
  const statusEl = document.getElementById("mission-status");
  const stepEl = document.getElementById("mission-step");
  const progressEl = document.getElementById("mission-progress");
  const progressBarEl = document.getElementById("mission-progress-bar");
  const resultEl = document.getElementById("mission-result");
  const eventsEl = document.getElementById("events");
  const presenceEl = document.getElementById("presence-count");

  // F4 sections (may be absent in old cached HTML — guard each lookup).
  const agentsListEl = document.getElementById("agents-list");
  const agentsEmptyEl = document.getElementById("agents-empty");
  const toolsListEl = document.getElementById("tools-list");
  const toolsEmptyEl = document.getElementById("tools-empty");
  const handoffsListEl = document.getElementById("handoffs-list");
  const handoffsEmptyEl = document.getElementById("handoffs-empty");
  const influenceEmptyEl = document.getElementById("influence-empty");
  const influenceBodyEl = document.getElementById("influence-body");
  const influenceQuestionEl = document.getElementById("influence-question");
  const influenceStateEl = document.getElementById("influence-state");
  const influenceCountsEl = document.getElementById("influence-counts");
  const influenceOutcomeEl = document.getElementById("influence-outcome");
  const influenceBranchEl = document.getElementById("influence-branch");
  const influenceHistoryEl = document.getElementById("influence-history");
  const resultSectionEl = document.getElementById("result");
  const resultEmptyEl = document.getElementById("result-empty");
  const resultBodyEl = document.getElementById("result-body");
  const resultSummaryEl = document.getElementById("result-summary");
  const resultOutcomeEl = document.getElementById("result-outcome");
  const resultErrorEl = document.getElementById("result-error");

  let missionId = null;
  let eventSource = null;
  let lastEventId = 0;
  let currentMission = null;

  // Client-derived snapshot (never persisted). Every row traces to one real event.
  const snapshot = {
    agents: new Map(),
    tools: [],
    handoffs: [],
    lastDecision: null,
  };

  function setConn(connected) {
    connEl.className = connected ? "connected" : "disconnected";
    connEl.textContent = connected
      ? "Connected — live."
      : "Disconnected — showing last known state, not live.";
  }

  function truncate(s, n = 300) {
    const t = String(s ?? "");
    return t.length > n ? `${t.slice(0, n)}…` : t;
  }

  function pick(obj, keys, fallback = "") {
    for (const k of keys) {
      const v = obj[k];
      if (typeof v === "string" && v.trim()) return v;
    }
    return fallback;
  }

  function agentKey(data) {
    return (
      pick(data, ["agent_id", "agent_name", "name"]) ||
      pick(data, ["profile", "role"]) ||
      "agent"
    );
  }

  // Single reducer for history seed + live tail (T045). Unknown/future types
  // are ignored here but still appended to the raw log (forward-compatible).
  function applyEvent(ev) {
    if (!ev || typeof ev.id !== "number" || ev.id <= lastEventId) return false;
    lastEventId = Math.max(lastEventId, ev.id);
    const d = ev.data && typeof ev.data === "object" ? ev.data : {};
    const ts = ev.timestamp || "";
    switch (ev.type) {
      case "agent_started": {
        const key = agentKey(d);
        snapshot.agents.set(key, {
          name: key,
          profile: pick(d, ["profile", "role", "agent_profile"], key),
          status: "running",
          task: pick(d, ["task", "description", "summary"], "running"),
          ts,
          eventId: ev.id,
        });
        break;
      }
      case "agent_completed": {
        const key = agentKey(d);
        snapshot.agents.set(key, {
          name: key,
          profile: pick(d, ["profile", "role", "agent_profile"], key),
          status: "completed",
          task: pick(d, ["summary", "result", "task"], "completed"),
          ts,
          eventId: ev.id,
        });
        break;
      }
      case "agent_failed": {
        const key = agentKey(d);
        snapshot.agents.set(key, {
          name: key,
          profile: pick(d, ["profile", "role", "agent_profile"], key),
          status: "failed",
          task: pick(d, ["error", "summary", "task"], "failed"),
          ts,
          eventId: ev.id,
        });
        break;
      }
      case "tool_started": {
        snapshot.tools.push({
          name: pick(d, ["tool_name", "name", "tool"], "tool"),
          action: pick(d, ["action", "task"], "started"),
          status: "running",
          summary: "",
          ts,
          eventId: ev.id,
        });
        break;
      }
      case "tool_completed": {
        snapshot.tools.push({
          name: pick(d, ["tool_name", "name", "tool"], "tool"),
          action: pick(d, ["action", "task"], ""),
          status: pick(d, ["status"], "completed"),
          summary: truncate(pick(d, ["summary", "result", "output", "error"], "")),
          ts,
          eventId: ev.id,
        });
        break;
      }
      case "agent_handoff": {
        snapshot.handoffs.push({
          from: pick(d, ["from_agent", "from", "source"], "?"),
          to: pick(d, ["to_agent", "to", "destination"], "?"),
          summary: truncate(pick(d, ["summary", "handoff", "task"], "")),
          reason: truncate(pick(d, ["reason"], "")),
          ts,
          eventId: ev.id,
        });
        break;
      }
      case "audience_decision_applied": {
        snapshot.lastDecision = {
          pollId: pick(d, ["poll_id"], ""),
          winner: pick(d, ["winning_option_id"], ""),
          decidedBy: pick(d, ["decided_by"], ""),
          nextStep: pick(d, ["next_step"], ""),
          ts,
          eventId: ev.id,
        };
        break;
      }
      default:
        break;
    }
    return true;
  }

  function rowLine(parts) {
    // textContent only: event payloads are untrusted, never HTML.
    return parts.filter(Boolean).join(" · ");
  }

  function renderAgents() {
    if (!agentsListEl) return;
    agentsListEl.replaceChildren();
    const rows = [...snapshot.agents.values()];
    if (agentsEmptyEl) agentsEmptyEl.hidden = rows.length > 0;
    for (const a of rows) {
      const li = document.createElement("li");
      li.textContent = rowLine([
        `${a.name} (${a.profile})`,
        `status: ${a.status}`,
        a.task ? `task: ${truncate(a.task, 200)}` : "",
        a.ts,
        `#${a.eventId}`,
      ]);
      agentsListEl.appendChild(li);
    }
  }

  function renderTools() {
    if (!toolsListEl) return;
    toolsListEl.replaceChildren();
    if (toolsEmptyEl) toolsEmptyEl.hidden = snapshot.tools.length > 0;
    for (const t of snapshot.tools.slice(-50)) {
      const li = document.createElement("li");
      li.textContent = rowLine([
        t.name,
        t.action ? `action: ${truncate(t.action, 140)}` : "",
        `status: ${t.status}`,
        t.summary ? `summary: ${t.summary}` : "",
        t.ts,
        `#${t.eventId}`,
      ]);
      toolsListEl.appendChild(li);
    }
  }

  function renderHandoffs() {
    if (!handoffsListEl) return;
    handoffsListEl.replaceChildren();
    if (handoffsEmptyEl) handoffsEmptyEl.hidden = snapshot.handoffs.length > 0;
    for (const h of snapshot.handoffs.slice(-50)) {
      const li = document.createElement("li");
      li.textContent = rowLine([
        `${h.from} → ${h.to}`,
        h.summary ? `summary: ${h.summary}` : "",
        h.reason ? `reason: ${h.reason}` : "",
        h.ts,
        `#${h.eventId}`,
      ]);
      handoffsListEl.appendChild(li);
    }
  }

  function renderSnapshotSections() {
    renderAgents();
    renderTools();
    renderHandoffs();
  }

  function honestProgress(m) {
    // Mirrors backend Mission.progress: terminal → 1.0, else index/steps.
    // Server does not serialize the property today, so derive client-side
    // from the same inputs. Never simulated, never time-based.
    if (typeof m.progress === "number") return m.progress;
    if (m.status === "completed" || m.status === "failed") return 1.0;
    const n = Array.isArray(m.steps) && m.steps.length > 0 ? m.steps.length : 0;
    if (!n) return 0.0;
    const idx = Math.max(0, Math.min(m.current_step_index ?? 0, n));
    return Math.min(1.0, Math.max(0.0, idx / n));
  }

  function renderMission(m) {
    currentMission = m;
    missionId = m.id;
    titleEl.textContent = m.title;
    statusEl.textContent = m.status;
    const step = m.steps[Math.min(m.current_step_index, m.steps.length - 1)];
    stepEl.textContent = step ? `${step.title} (${step.agent_profile || "unassigned"})` : "—";
    const pct = Math.round(honestProgress(m) * 100);
    progressEl.textContent = `${pct}%`;
    if (progressBarEl) progressBarEl.style.width = `${pct}%`;
    const bits = [];
    if (m.result_summary) bits.push(`Result: ${m.result_summary}`);
    if (m.outcome) bits.push(`Outcome: ${m.outcome}`);
    if (m.error) bits.push(`Error: ${m.error}`);
    resultEl.textContent = bits.join(" · ");
    renderResult(m);
    renderInfluenceFromMission(m);
  }

  function renderResult(m) {
    if (!resultBodyEl) return;
    const hasResult = Boolean(m.result_summary || m.outcome || m.error);
    if (resultEmptyEl) resultEmptyEl.hidden = hasResult;
    resultBodyEl.hidden = !hasResult;
    if (!hasResult) {
      if (resultSectionEl) resultSectionEl.className = "card";
      return;
    }
    if (resultSummaryEl) resultSummaryEl.textContent = m.result_summary || "—";
    if (resultOutcomeEl) resultOutcomeEl.textContent = m.outcome || "—";
    if (resultErrorEl) resultErrorEl.textContent = m.error ? `Error: ${m.error}` : "";
    if (resultSectionEl) {
      resultSectionEl.className = `card ${m.outcome === "failed" ? "failed" : "success"}`;
    }
  }

  function renderInfluenceFromMission(m) {
    // Branch linkage lives on the mission; poll question/counts come from
    // refreshPollPanel/refreshInfluence. Show branch even after the poll
    // leaves `current` so the decision stays visible.
    const decisions = (m.branch_context && m.branch_context.applied_decisions) || [];
    const branch = m.branch_context && m.branch_context.current_branch_instruction;
    if (!influenceBodyEl) return;
    if (!currentPoll && decisions.length === 0 && !snapshot.lastDecision) {
      if (influenceEmptyEl) influenceEmptyEl.hidden = false;
      influenceBodyEl.hidden = true;
      return;
    }
    if (influenceEmptyEl) influenceEmptyEl.hidden = true;
    influenceBodyEl.hidden = false;
    if (influenceBranchEl) {
      const text =
        branch ||
        (snapshot.lastDecision && snapshot.lastDecision.nextStep) ||
        "";
      influenceBranchEl.textContent = text ? `Selected branch: ${text}` : "Selected branch: —";
    }
    if (influenceHistoryEl) {
      influenceHistoryEl.replaceChildren();
      const all = decisions.length > 0 ? decisions : snapshot.lastDecision ? [{
        poll_id: snapshot.lastDecision.pollId,
        winning_option_id: snapshot.lastDecision.winner,
        decided_by: snapshot.lastDecision.decidedBy,
      }] : [];
      for (const d of all) {
        const li = document.createElement("li");
        li.textContent = rowLine([
          `poll ${(d.poll_id || "")}`,
          `winner: ${(d.winning_option_id || "")}`,
          `decided_by: ${(d.decided_by || "")}`,
        ]);
        influenceHistoryEl.appendChild(li);
      }
    }
    if (snapshot.lastDecision && influenceOutcomeEl && !currentPoll) {
      influenceOutcomeEl.textContent =
        `Outcome: ${snapshot.lastDecision.winner} (${snapshot.lastDecision.decidedBy})`;
    }
  }

  function renderEvent(ev) {
    const li = document.createElement("li");
    // textContent only: event payloads are untrusted, never HTML.
    const ts = ev.timestamp || "";
    li.textContent = `#${ev.id} ${ev.type} · ${ts} · ${JSON.stringify(ev.data || {})}`;
    eventsEl.prepend(li);
    while (eventsEl.children.length > 200) eventsEl.lastChild.remove();
  }

  async function api(path, options) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`${res.status} ${body}`);
    }
    return res.status === 204 ? null : res.json();
  }

  async function refreshMission() {
    if (!missionId) return;
    const m = await api(`/api/missions/${missionId}`);
    renderMission(m);
    await refreshInfluence().catch(() => {});
  }

  async function refreshPresence() {
    try {
      const roster = await api("/api/participants");
      presenceEl.textContent = String(roster.count);
    } catch {
      // Keep the last known count; the banner already shows staleness.
    }
  }

  async function loadHistory() {
    if (!missionId) return;
    eventsEl.replaceChildren();
    snapshot.agents.clear();
    snapshot.tools = [];
    snapshot.handoffs = [];
    snapshot.lastDecision = null;
    const h = await api(`/api/missions/${missionId}/events?limit=100`);
    // History arrives oldest→newest; log shows newest first.
    for (const ev of h.events) {
      applyEvent(ev);
      renderEvent(ev);
    }
    renderSnapshotSections();
    // lastEventId tracks the max seen id for Last-Event-ID replay dedup.
    for (const ev of h.events) {
      if (typeof ev.id === "number") lastEventId = Math.max(lastEventId, ev.id);
    }
  }

  function connectStream() {
    if (!missionId) return;
    if (eventSource) eventSource.close();
    setConn(false);
    const url = `/api/missions/${missionId}/events/stream${
      lastEventId ? `?lastEventId=${lastEventId}` : ""
    }`;
    const es = new EventSource(url);
    eventSource = es;
    es.onopen = () => setConn(true);
    es.onerror = () => setConn(false);
    const handle = (msg) => {
      try {
        const ev = JSON.parse(msg.data);
        if (typeof ev.id === "number" && ev.id <= lastEventId) return; // replay dedup
        applyEvent(ev);
        if (typeof ev.id === "number") lastEventId = Math.max(lastEventId, ev.id);
        renderEvent(ev);
        renderSnapshotSections();
        if (ev.type && typeof ev.type === "string" && ev.type.startsWith("mission")) {
          refreshMission().catch(() => {});
        }
        if (ev.type === "participant_joined" || ev.type === "participant_left") {
          refreshPresence().catch(() => {});
        }
        if (typeof ev.type === "string" && (ev.type.startsWith("poll") || ev.type === "audience_decision_applied")) {
          refreshPollPanel().catch(() => {});
          refreshInfluence().catch(() => {});
          refreshMission().catch(() => {});
        }
        if (typeof ev.type === "string" && (ev.type.startsWith("agent") || ev.type.startsWith("tool"))) {
          renderSnapshotSections();
        }
      } catch {
        // Ignore malformed rows; keep the stream open.
      }
    };
    es.onmessage = handle;
    // Server sends `event: <type>` so EventSource dispatches to named
    // listeners, not onmessage. Subscribe to all known types (F1 lifecycle
    // + canonical F3/F5 types) so future slices stream without a client change.
    const allTypes = [
      "mission_created",
      "mission_started",
      "mission_paused",
      "mission_resumed",
      "mission_completed",
      "mission_failed",
      "mission_reset",
      "poll_opened",
      "poll_closing",
      "poll_closed",
      "vote_recorded",
      "audience_decision_applied",
      "agent_started",
      "tool_started",
      "tool_completed",
      "agent_handoff",
      "agent_completed",
      "agent_failed",
      "participant_joined",
      "participant_left",
    ];
    for (const t of allTypes) es.addEventListener(t, handle);
  }

  async function ensureMission() {
    const list = await api("/api/missions");
    if (list.length > 0) {
      renderMission(list[list.length - 1]);
    } else {
      const m = await api("/api/missions", {
        method: "POST",
        body: JSON.stringify({ title: "Investigate AI agents" }),
      });
      renderMission(m);
    }
    await loadHistory();
    connectStream();
    await refreshPresence();
    await refreshPollPanel();
    await refreshInfluence();
  }

  async function action(suffix, body) {
    if (!missionId && suffix !== "") return;
    await api(`/api/missions/${missionId}${suffix}`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
    await refreshMission();
    await refreshPollPanel();
    await refreshInfluence();
  }

  document.getElementById("btn-create").onclick = async () => {
    const m = await api("/api/missions", {
      method: "POST",
      body: JSON.stringify({ title: "Investigate AI agents" }),
    });
    lastEventId = 0;
    snapshot.agents.clear();
    snapshot.tools = [];
    snapshot.handoffs = [];
    snapshot.lastDecision = null;
    renderSnapshotSections();
    renderMission(m);
    await loadHistory();
    connectStream();
    await refreshPresence();
    await refreshPollPanel();
    await refreshInfluence();
  };
  document.getElementById("btn-start").onclick = () => action("/start").catch((e) => alert(e.message));
  document.getElementById("btn-pause").onclick = () => action("/pause").catch((e) => alert(e.message));
  document.getElementById("btn-resume").onclick = () => action("/resume").catch((e) => alert(e.message));
  document.getElementById("btn-complete").onclick = () =>
    action("/complete", { summary: "Demo complete", outcome: "success" }).catch((e) =>
      alert(e.message),
    );
  document.getElementById("btn-fail").onclick = () =>
    action("/fail", { error: "Demo failure" }).catch((e) => alert(e.message));
  document.getElementById("btn-reset").onclick = () => action("/reset").catch((e) => alert(e.message));

  // -- F3 presenter poll panel (textContent-only; server data is untrusted) --
  const pollSummaryEl = document.getElementById("poll-current-summary");
  const pollActionsEl = document.getElementById("poll-current-actions");
  const pollTallyEl = document.getElementById("poll-current-tally");
  const pollOutcomeEl = document.getElementById("poll-current-outcome");
  const pollMessageEl = document.getElementById("poll-message");
  const pollRowsEl = document.getElementById("poll-option-rows");
  let currentPoll = null;
  let pollCountdownTimer = null;

  function pollMessage(text) {
    pollMessageEl.textContent = text;
  }

  function addOptionRow(idVal = "", labelVal = "", branchVal = "") {
    const row = document.createElement("p");
    const idInput = document.createElement("input");
    idInput.placeholder = "option id";
    idInput.value = idVal;
    idInput.size = 12;
    const labelInput = document.createElement("input");
    labelInput.placeholder = "label shown to voters";
    labelInput.value = labelVal;
    labelInput.size = 24;
    const branchInput = document.createElement("input");
    branchInput.placeholder = "next-step instructions if this wins";
    branchInput.value = branchVal;
    branchInput.size = 36;
    row.append(idInput, document.createTextNode(" "), labelInput, document.createTextNode(" "), branchInput);
    pollRowsEl.appendChild(row);
  }

  function renderPollPanel(poll) {
    currentPoll = poll;
    if (!poll) {
      pollSummaryEl.textContent = "No open poll";
      pollActionsEl.hidden = true;
      pollTallyEl.textContent = "";
      pollOutcomeEl.textContent = "";
      return;
    }
    const secs = Math.max(0, Math.ceil((Date.parse(poll.deadline_at) - Date.now()) / 1000));
    pollSummaryEl.textContent =
      `Open poll: ${poll.question} · state ${poll.state} · ${poll.reveal_mode} reveal` +
      (poll.state === "open" ? ` · closes in ${secs}s` : "");
    pollActionsEl.hidden = false;
    if (poll.tally) {
      const parts = poll.options.map((o) => `${o.label}: ${poll.tally[o.id] ?? 0}`);
      pollTallyEl.textContent = `Counts: ${parts.join(" · ")} (total ${poll.total_votes})`;
    } else {
      pollTallyEl.textContent = `Votes so far: ${poll.total_votes} (counts hidden until close)`;
    }
    pollOutcomeEl.textContent = poll.outcome
      ? `Outcome: ${poll.outcome.winning_option_id} (${poll.outcome.decided_by})`
      : "";
  }

  async function refreshPollPanel() {
    if (!missionId) return;
    try {
      const data = await api(`/api/missions/${missionId}/polls/current`);
      renderPollPanel(data.poll);
      await refreshInfluence(data.poll);
    } catch {
      // Keep the last known poll state; the banner already shows staleness.
    }
  }

  // Read-only audience-influence summary (distinct from the control panel above).
  async function refreshInfluence(knownPoll) {
    if (!missionId || !influenceBodyEl) return;
    try {
      const poll = knownPoll !== undefined
        ? knownPoll
        : (await api(`/api/missions/${missionId}/polls/current`)).poll;
      currentPoll = poll;
      const hasInfluence = Boolean(poll || (currentMission
        && currentMission.branch_context
        && (currentMission.branch_context.applied_decisions || []).length > 0)
        || snapshot.lastDecision);
      if (influenceEmptyEl) influenceEmptyEl.hidden = hasInfluence;
      influenceBodyEl.hidden = !hasInfluence;
      if (!hasInfluence) return;
      if (poll) {
        if (influenceQuestionEl) influenceQuestionEl.textContent = poll.question;
        if (influenceStateEl) {
          const secs = Math.max(0, Math.ceil((Date.parse(poll.deadline_at) - Date.now()) / 1000));
          influenceStateEl.textContent =
            `State: ${poll.state} · ${poll.reveal_mode} reveal` +
            (poll.state === "open" ? ` · closes in ${secs}s` : "");
        }
        if (influenceCountsEl) {
          if (poll.tally) {
            const parts = poll.options.map((o) => `${o.label}: ${poll.tally[o.id] ?? 0}`);
            influenceCountsEl.textContent = `Counts: ${parts.join(" · ")} (total ${poll.total_votes})`;
          } else {
            influenceCountsEl.textContent =
              `Votes so far: ${poll.total_votes} (counts hidden until close)`;
          }
        }
        if (influenceOutcomeEl) {
          influenceOutcomeEl.textContent = poll.outcome
            ? `Outcome: ${poll.outcome.winning_option_id} (${poll.outcome.decided_by})`
            : "Outcome: pending";
        }
      } else if (snapshot.lastDecision && influenceOutcomeEl) {
        influenceOutcomeEl.textContent =
          `Outcome: ${snapshot.lastDecision.winner} (${snapshot.lastDecision.decidedBy})`;
        if (influenceQuestionEl) influenceQuestionEl.textContent = "Completed poll (see event log)";
        if (influenceStateEl) influenceStateEl.textContent = "State: completed";
        if (influenceCountsEl) influenceCountsEl.textContent = "";
      }
      if (currentMission) renderInfluenceFromMission(currentMission);
    } catch {
      // Keep the last known influence state; the banner already shows staleness.
    }
  }

  document.getElementById("btn-poll-add-option").onclick = () => addOptionRow();
  document.getElementById("poll-open-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const options = [];
    for (const row of pollRowsEl.children) {
      const [idInput, labelInput, branchInput] = row.querySelectorAll("input");
      options.push({
        id: idInput.value.trim(),
        label: labelInput.value.trim(),
        branch_instruction: branchInput.value.trim(),
      });
    }
    try {
      const body = {
        question: document.getElementById("poll-question").value,
        options,
        deadline_seconds: Number(document.getElementById("poll-deadline").value) || 60,
        reveal_mode: document.getElementById("poll-reveal").value,
      };
      const res = await fetch(`/api/missions/${missionId}/polls`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail = res.statusText;
        try {
          detail = (await res.json()).detail || detail;
        } catch {
          // Keep status text when the body is not JSON.
        }
        throw new Error(detail);
      }
      pollMessage("Poll opened.");
      await refreshPollPanel();
    } catch (e) {
      pollMessage(`Could not open poll: ${e.message}`);
    }
  };
  document.getElementById("btn-poll-close").onclick = async () => {
    if (!currentPoll) return;
    try {
      await action(`/polls/${currentPoll.id}/close`);
      pollMessage("Poll closed.");
      await refreshPollPanel();
    } catch (e) {
      pollMessage(`Could not close poll: ${e.message}`);
    }
  };
  document.getElementById("btn-poll-resolve").onclick = async () => {
    if (!currentPoll) return;
    const choice = document.getElementById("poll-resolve-choice").value.trim();
    try {
      await action(`/polls/${currentPoll.id}/resolve`, { winning_option_id: choice });
      pollMessage("Decision applied — the mission's next step follows the winner.");
      await refreshPollPanel();
    } catch (e) {
      pollMessage(`Could not resolve poll: ${e.message}`);
    }
  };

  addOptionRow("deep", "Go deeper", "Critic verifies cited sources.");
  addOptionRow("wide", "Counterarguments", "Critic finds counterarguments.");
  pollCountdownTimer = setInterval(() => {
    if (currentPoll) renderPollPanel(currentPoll);
  }, 1000);
  void pollCountdownTimer;

  setConn(false);
  ensureMission().catch(() => setConn(false));
})();
