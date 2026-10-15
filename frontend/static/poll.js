// F3 voter view: current poll + cast/change vote. Server data via textContent only.
(() => {
  const connEl = document.getElementById("conn");
  const questionEl = document.getElementById("poll-question");
  const stateEl = document.getElementById("poll-state");
  const countdownEl = document.getElementById("poll-countdown");
  const revealEl = document.getElementById("poll-reveal");
  const optionsEl = document.getElementById("poll-options");
  const resultsEl = document.getElementById("poll-results");
  const outcomeEl = document.getElementById("poll-outcome");
  const messageEl = document.getElementById("vote-message");

  const ID_KEY = "lap-participant-id";
  let missionId = null;
  let currentPoll = null;
  let myVote = null;
  let eventSource = null;
  let lastEventId = 0;
  let countdownTimer = null;

  function participantId() {
    try {
      return localStorage.getItem(ID_KEY);
    } catch {
      return null;
    }
  }

  function setConn(connected) {
    connEl.className = connected ? "connected" : "disconnected";
    connEl.textContent = connected
      ? "Connected — live."
      : "Disconnected — showing last known state, not live.";
  }

  function showMessage(kind, text) {
    messageEl.className = kind;
    messageEl.textContent = text;
  }

  async function api(path, options) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
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
    return res.status === 204 ? null : res.json();
  }

  function renderCountdown() {
    if (!currentPoll || currentPoll.state !== "open") {
      countdownEl.textContent = "";
      return;
    }
    const ms = Date.parse(currentPoll.deadline_at) - Date.now();
    if (ms <= 0) {
      countdownEl.textContent = "voting ended — refreshing…";
      refreshPoll().catch(() => {});
      return;
    }
    countdownEl.textContent = `closes in ${Math.ceil(ms / 1000)}s`;
  }

  function renderPoll(poll) {
    currentPoll = poll;
    if (!poll) {
      questionEl.textContent = "No open poll";
      stateEl.textContent = "—";
      countdownEl.textContent = "";
      revealEl.textContent = "";
      optionsEl.replaceChildren();
      resultsEl.textContent = "";
      outcomeEl.textContent = "";
      return;
    }
    questionEl.textContent = poll.question;
    stateEl.textContent = poll.state;
    revealEl.textContent =
      poll.reveal_mode === "controlled" && poll.state !== "completed"
        ? "Counts are hidden until the poll closes — your vote is still counted."
        : "Live counts are shown.";
    optionsEl.replaceChildren();
    const votingOpen = poll.state === "open";
    for (const opt of poll.options) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = opt.label;
      btn.disabled = !votingOpen;
      btn.setAttribute("aria-pressed", myVote === opt.id ? "true" : "false");
      btn.onclick = () => castVote(opt.id);
      optionsEl.appendChild(btn);
    }
    if (poll.tally) {
      const parts = poll.options.map((o) => `${o.label}: ${poll.tally[o.id] ?? 0}`);
      resultsEl.textContent = `Counts: ${parts.join(" · ")} (total ${poll.total_votes})`;
    } else {
      resultsEl.textContent = `Votes so far: ${poll.total_votes} (counts hidden until close)`;
    }
    outcomeEl.textContent = poll.outcome
      ? `Outcome: ${labelFor(poll.outcome.winning_option_id)} (${poll.outcome.decided_by})`
      : "";
  }

  function labelFor(optionId) {
    const opt = (currentPoll?.options || []).find((o) => o.id === optionId);
    return opt ? opt.label : optionId;
  }

  async function castVote(optionId) {
    const pid = participantId();
    if (!pid) {
      showMessage("err", "Please join first — only joined participants can vote.");
      return;
    }
    if (!currentPoll) return;
    try {
      const res = await api(`/api/missions/${missionId}/polls/${currentPoll.id}/vote`, {
        method: "POST",
        body: JSON.stringify({ participant_id: pid, option_id: optionId }),
      });
      myVote = optionId;
      showMessage("ok", "Vote recorded.");
      renderPoll({ ...currentPoll, tally: res.tally ?? currentPoll.tally, total_votes: res.total_votes });
    } catch (e) {
      showMessage("err", e.message);
    }
  }

  async function refreshPoll() {
    if (!missionId) return;
    const data = await api(`/api/missions/${missionId}/polls/current`);
    renderPoll(data.poll);
    renderCountdown();
  }

  function connectStream() {
    if (!missionId) return;
    if (eventSource) eventSource.close();
    setConn(false);
    const url = `/api/missions/${missionId}/events/stream${lastEventId ? `?lastEventId=${lastEventId}` : ""}`;
    const es = new EventSource(url);
    eventSource = es;
    es.onopen = () => setConn(true);
    es.onerror = () => setConn(false);
    const handle = (msg) => {
      try {
        const ev = JSON.parse(msg.data);
        lastEventId = Math.max(lastEventId, ev.id);
        if (typeof ev.type === "string" && ev.type.startsWith("poll")) {
          myVote = null;
          refreshPoll().catch(() => {});
        }
        if (ev.type === "audience_decision_applied") refreshPoll().catch(() => {});
      } catch {
        // Ignore malformed rows; keep the stream open.
      }
    };
    es.onmessage = handle;
    for (const t of ["poll_opened", "poll_closing", "poll_closed", "vote_recorded", "audience_decision_applied"]) {
      es.addEventListener(t, handle);
    }
  }

  async function ensureMission() {
    const list = await api("/api/missions");
    if (list.length === 0) {
      questionEl.textContent = "No mission yet — ask the presenter to start one.";
      return;
    }
    missionId = list[list.length - 1].id;
    await refreshPoll();
    connectStream();
  }

  setConn(false);
  ensureMission().catch(() => setConn(false));
  countdownTimer = setInterval(renderCountdown, 1000);
  void countdownTimer;
})();
