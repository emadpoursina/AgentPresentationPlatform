// F1 dashboard: mission state + real SSE events only. No fabricated progress.
(() => {
  const connEl = document.getElementById("conn");
  const titleEl = document.getElementById("mission-title");
  const statusEl = document.getElementById("mission-status");
  const stepEl = document.getElementById("mission-step");
  const progressEl = document.getElementById("mission-progress");
  const resultEl = document.getElementById("mission-result");
  const eventsEl = document.getElementById("events");

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
      "vote_recorded",
      "audience_decision_applied",
      "agent_started",
      "tool_started",
      "tool_completed",
      "agent_handoff",
      "agent_completed",
      "agent_failed",
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
  }

  async function action(suffix, body) {
    if (!missionId && suffix !== "") return;
    await api(`/api/missions/${missionId}${suffix}`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
    await refreshMission();
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

  setConn(false);
  ensureMission().catch(() => setConn(false));
})();
