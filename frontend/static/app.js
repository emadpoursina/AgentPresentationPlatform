// F1 dashboard: mission state + real SSE events only. No fabricated progress.
(() => {
  const connEl = document.getElementById("conn");
  const titleEl = document.getElementById("mission-title");
  const statusEl = document.getElementById("mission-status");
  const stepEl = document.getElementById("mission-step");
  const progressEl = document.getElementById("mission-progress");
  const resultEl = document.getElementById("mission-result");
  const eventsEl = document.getElementById("events");
  const presenceEl = document.getElementById("presence-count");

  let missionId = null;
  let eventSource = null;
  let lastEventId = 0;

  function setConn(connected) {
    connEl.className = connected ? "connected" : "disconnected";
    connEl.textContent = connected
      ? "Connected — live."
      : "Disconnected — showing last known state, not live.";
  }

  function renderMission(m) {
    missionId = m.id;
    titleEl.textContent = m.title;
    statusEl.textContent = m.status;
    const step = m.steps[Math.min(m.current_step_index, m.steps.length - 1)];
    stepEl.textContent = step ? `${step.title} (${step.agent_profile || "unassigned"})` : "—";
    const pct = Math.round((m.progress ?? 0) * 100);
    progressEl.textContent = `${pct}%`;
    const bits = [];
    if (m.result_summary) bits.push(`Result: ${m.result_summary}`);
    if (m.outcome) bits.push(`Outcome: ${m.outcome}`);
    if (m.error) bits.push(`Error: ${m.error}`);
    resultEl.textContent = bits.join(" · ");
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
    const h = await api(`/api/missions/${missionId}/events?limit=100`);
    for (const ev of h.events) {
      renderEvent(ev);
      lastEventId = Math.max(lastEventId, ev.id);
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
        lastEventId = Math.max(lastEventId, ev.id);
        renderEvent(ev);
        refreshMission().catch(() => {});
        if (ev.type === "participant_joined" || ev.type === "participant_left") {
          refreshPresence().catch(() => {});
        }
        if (typeof ev.type === "string" && (ev.type.startsWith("poll") || ev.type === "audience_decision_applied")) {
          refreshPollPanel().catch(() => {});
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
  }

  async function action(suffix, body) {
    if (!missionId && suffix !== "") return;
    await api(`/api/missions/${missionId}${suffix}`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
    await refreshMission();
    await refreshPollPanel();
  }

  document.getElementById("btn-create").onclick = async () => {
    const m = await api("/api/missions", {
      method: "POST",
      body: JSON.stringify({ title: "Investigate AI agents" }),
    });
    lastEventId = 0;
    renderMission(m);
    await loadHistory();
    connectStream();
    await refreshPresence();
    await refreshPollPanel();
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
    } catch {
      // Keep the last known poll state; the banner already shows staleness.
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
