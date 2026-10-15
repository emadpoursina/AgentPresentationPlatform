// F2 join page: join-info + join + heartbeat. Server data via textContent only.
(() => {
  const qrEl = document.getElementById("join-qr");
  const urlEl = document.getElementById("join-url");
  const notReadyEl = document.getElementById("not-ready");
  const formEl = document.getElementById("join-form");
  const nameEl = document.getElementById("display-name");
  const confirmEl = document.getElementById("join-confirmation");

  const ID_KEY = "lap-participant-id";
  let participantId = null;
  let heartbeatTimer = null;

  function showMessage(kind, text) {
    confirmEl.className = kind;
    confirmEl.textContent = text;
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

  async function loadJoinInfo() {
    const info = await api("/api/join-info");
    urlEl.textContent = info.join_url;
    if (info.ready) {
      qrEl.src = info.qr_url;
    } else {
      qrEl.removeAttribute("src");
      notReadyEl.classList.add("show");
    }
  }

  function startHeartbeat() {
    stopHeartbeat();
    heartbeatTimer = setInterval(async () => {
      if (!participantId) return;
      try {
        await api(`/api/participants/${participantId}/heartbeat`, { method: "POST" });
      } catch {
        stopHeartbeat();
        participantId = null;
        try {
          localStorage.removeItem(ID_KEY);
        } catch {
          // Storage may be unavailable; joining still works for this session.
        }
        showMessage("err", "Your session expired. Please join again.");
      }
    }, 15000);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }

  async function join(displayName) {
    const body = displayName ? { display_name: displayName } : {};
    const p = await api("/api/participants/join", {
      method: "POST",
      body: JSON.stringify(body),
    });
    participantId = p.id;
    try {
      localStorage.setItem(ID_KEY, p.id);
    } catch {
      // Storage may be unavailable; heartbeat keeps this tab counted.
    }
    const who = p.anonymous ? "anonymously" : `as ${p.display_name}`;
    showMessage("ok", `You have joined ${who}.`);
    startHeartbeat();
  }

  formEl.addEventListener("submit", (ev) => {
    ev.preventDefault();
    join(nameEl.value).catch((e) => showMessage("err", e.message));
  });
  document.getElementById("btn-anon").addEventListener("click", () => {
    join("").catch((e) => showMessage("err", e.message));
  });

  loadJoinInfo().catch(() => {
    urlEl.textContent = "unavailable — check your network connection";
  });
})();
