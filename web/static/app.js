(() => {
  "use strict";

  const API = "/api";
  const SESSION_KEY = "aria_session_id";

  const els = {
    messages: document.getElementById("messages"),
    form: document.getElementById("chat-form"),
    input: document.getElementById("message-input"),
    send: document.getElementById("btn-send"),
    typing: document.getElementById("typing"),
    newChat: document.getElementById("btn-new"),
    download: document.getElementById("btn-download"),
    error: document.getElementById("error-banner"),
    status: document.getElementById("status-text"),
    statusDot: document.querySelector(".dot"),
    chips: document.getElementById("chips"),
  };

  let sessionId = sessionStorage.getItem(SESSION_KEY);
  let inFlight = false;

  function setError(message) {
    if (message) {
      els.error.textContent = message;
      els.error.hidden = false;
    } else {
      els.error.textContent = "";
      els.error.hidden = true;
    }
  }

  function setStatus(text, online) {
    els.status.textContent = text;
    els.statusDot.style.background = online ? "#22c55e" : "#ef4444";
  }

  function formatTime(value) {
    try {
      const d = value ? new Date(value) : new Date();
      return d.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      return "";
    }
  }

  function scrollToBottom() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function addMessage(role, text, timestamp) {
    const wrap = document.createElement("div");
    wrap.className = `message message--${role}`;

    const bubble = document.createElement("div");
    bubble.className = "message__bubble";
    bubble.textContent = text;

    const meta = document.createElement("div");
    meta.className = "message__meta";
    meta.textContent = formatTime(timestamp);

    wrap.append(bubble, meta);
    els.messages.append(wrap);
    scrollToBottom();
  }

  function setBusy(busy) {
    inFlight = busy;
    els.send.disabled = busy;
    els.input.disabled = busy;
    els.typing.hidden = !busy;
    if (!busy) {
      els.input.focus();
    }
  }

  async function ensureSession() {
    if (sessionId) return sessionId;
    try {
      const r = await fetch(`${API}/session`, { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      sessionId = data.session_id;
      sessionStorage.setItem(SESSION_KEY, sessionId);
      setStatus("Online", true);
      setError("");
      return sessionId;
    } catch (err) {
      setStatus("Offline", false);
      setError("Could not connect to the Aria server. Please try again.");
      throw err;
    }
  }

  async function postChat(sid, message) {
    const r = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sid, message }),
    });
    return r;
  }

  async function sendMessage(text) {
    if (!text || inFlight) return;

    setError("");
    addMessage("user", text);
    els.input.value = "";
    setBusy(true);

    try {
      let sid = await ensureSession();
      let r = await postChat(sid, text);

      if (r.status === 404) {
        // Session expired server-side: forget it and retry once.
        sessionStorage.removeItem(SESSION_KEY);
        sessionId = null;
        sid = await ensureSession();
        r = await postChat(sid, text);
      }

      if (r.status === 409) {
        addMessage(
          "bot",
          "This conversation has ended. Click 'New chat' to keep going."
        );
      } else if (!r.ok) {
        throw new Error(`HTTP ${r.status}`);
      } else {
        const data = await r.json();
        addMessage("bot", data.reply, data.timestamp);
      }
    } catch (err) {
      console.error(err);
      setError("Network error. Check that the Aria server is running.");
    } finally {
      setBusy(false);
    }
  }

  async function resetSession() {
    if (inFlight) return;
    const old = sessionId;
    sessionId = null;
    sessionStorage.removeItem(SESSION_KEY);
    els.messages.innerHTML = "";
    setError("");
    setStatus("Online", true);
    if (old) {
      try {
        await fetch(`${API}/session/${old}`, { method: "DELETE" });
      } catch (_) {
        /* ignore */
      }
    }
    addMessage("bot", "Hi, I'm Aria. Ask me anything!");
    try {
      await ensureSession();
    } catch (_) {
      /* error banner already shown */
    }
  }

  async function downloadTranscript() {
    if (!sessionId) {
      setError("No active conversation to download.");
      return;
    }
    try {
      const r = await fetch(`${API}/history/${sessionId}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const payload = {
        exported_at: new Date().toISOString(),
        session_id: sessionId,
        ...data,
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aria_transcript_${Date.now()}.json`;
      document.body.append(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      setError("Could not download the transcript.");
    }
  }

  els.form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const text = els.input.value.trim();
    if (text) sendMessage(text);
  });

  els.chips.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".chip");
    if (!btn) return;
    const text = btn.dataset.message;
    if (text) sendMessage(text);
  });

  els.newChat.addEventListener("click", resetSession);
  els.download.addEventListener("click", downloadTranscript);

  // Deferred script: DOM is fully parsed, safe to touch elements.
  addMessage("bot", "Hi, I'm Aria. Ask me anything!");
  ensureSession().catch(() => {
    /* setError already called */
  });
  els.input.focus();
})();