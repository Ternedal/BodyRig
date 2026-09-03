(() => {
  const FINAL_FAILURE = new Set(["failed", "interrupted"]);
  let timer = null;
  let currentSourceJobId = "";

  function personId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { Accept: "application/json", ...(options.headers || {}) },
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload?.detail || payload);
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return payload;
  }

  function ensureControls() {
    const card = document.getElementById("bodyJobCard");
    if (!card) return null;
    let wrap = document.getElementById("bodyResumeControls");
    if (wrap) return wrap;
    wrap = document.createElement("div");
    wrap.id = "bodyResumeControls";
    wrap.className = "space-top";
    wrap.innerHTML = `
      <button id="bodyResumeButton" class="secondary full" type="button" hidden>Genoptag fra bevaret reconstruction</button>
      <div id="bodyResumeStatus" class="fine-print"></div>`;
    card.appendChild(wrap);
    document.getElementById("bodyResumeButton")?.addEventListener("click", () => void startResume());
    return wrap;
  }

  function setState({ visible = false, disabled = false, text = "", sourceJobId = "" } = {}) {
    ensureControls();
    const button = document.getElementById("bodyResumeButton");
    const status = document.getElementById("bodyResumeStatus");
    currentSourceJobId = sourceJobId;
    if (button) {
      button.hidden = !visible;
      button.disabled = disabled;
    }
    if (status) status.textContent = text;
  }

  function reconnectAutoWorkflow(id, sourceJobId, resumeJobId) {
    const key = `bodyrig-person-auto-v1:${id}`;
    try {
      const workflow = JSON.parse(localStorage.getItem(key) || "null");
      if (!workflow || workflow.version !== 1 || workflow.person_id !== id) return;
      if (workflow.body_job_id !== sourceJobId && workflow.state !== "failed") return;
      workflow.state = "body";
      workflow.body_job_id = resumeJobId;
      workflow.body_revision = null;
      delete workflow.error;
      localStorage.setItem(key, JSON.stringify(workflow));
    } catch {
      // A corrupt/absent local workflow must never block the persisted backend recovery job.
    }
  }

  async function startResume() {
    const id = personId();
    const sourceJobId = currentSourceJobId;
    if (!id || !sourceJobId) return;
    setState({
      visible: true,
      disabled: true,
      sourceJobId,
      text: "Revaliderer session, reconstruction og source authority før genoptagelse …",
    });
    try {
      const job = await apiJson(`/api/v1/jobs/${encodeURIComponent(sourceJobId)}/resume`, { method: "POST" });
      reconnectAutoWorkflow(id, sourceJobId, job.job_id);
      setState({
        visible: false,
        sourceJobId: "",
        text: `Resume-job ${job.job_id} er startet. PHALP/4D-Humans reconstruction genkøres ikke.`,
      });
      clearTimeout(timer);
      timer = setTimeout(() => void refresh(), 1000);
    } catch (error) {
      setState({
        visible: true,
        disabled: false,
        sourceJobId,
        text: `Genoptagelse blev afvist fail-closed: ${error.message}`,
      });
    }
  }

  async function refresh() {
    clearTimeout(timer);
    ensureControls();
    const id = personId();
    if (!id) {
      setState();
      timer = setTimeout(() => void refresh(), 3000);
      return;
    }
    try {
      const payload = await apiJson(`/api/v1/jobs?person_id=${encodeURIComponent(id)}`);
      const latest = Array.isArray(payload.jobs)
        ? payload.jobs.find((item) => item?.kind === "body-build") || null
        : null;
      if (!latest || !FINAL_FAILURE.has(latest.status)) {
        setState();
        timer = setTimeout(() => void refresh(), latest?.status === "running" ? 3000 : 7000);
        return;
      }

      const status = await apiJson(`/api/v1/jobs/${encodeURIComponent(latest.job_id)}/resume-status`);
      if (status.available === true) {
        setState({
          visible: true,
          disabled: false,
          sourceJobId: latest.job_id,
          text: "Bevaret SiTH reconstruction er hash-verificeret. Genoptagelse kører kun den afbrudte fitter og fortsætter derefter Gate A/fidelity.",
        });
      } else {
        setState({
          visible: false,
          sourceJobId: "",
          text: status.reason ? `Late-fit resume ikke tilgængelig: ${status.reason}` : "",
        });
      }
      timer = setTimeout(() => void refresh(), 10000);
    } catch (error) {
      setState({ visible: false, text: `Kunne ikke kontrollere late-fit resume: ${error.message}` });
      timer = setTimeout(() => void refresh(), 10000);
    }
  }

  const idNode = document.getElementById("personId");
  if (idNode) {
    new MutationObserver(() => {
      clearTimeout(timer);
      void refresh();
    }).observe(idNode, { childList: true, characterData: true, subtree: true });
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      clearTimeout(timer);
      void refresh();
    }
  });
  window.addEventListener("DOMContentLoaded", () => void refresh(), { once: true });
})();
