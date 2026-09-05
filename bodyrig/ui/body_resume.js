(() => {
  const FINAL_FAILURE = new Set(["failed", "interrupted"]);
  const ADOPT = "adopt-complete-package";
  const FIT_ONLY = "resume-fit-only";
  let timer = null;
  let currentSourceJobId = "";
  let currentRecoveryMode = "";

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
      <button id="bodyResumeButton" class="secondary full" type="button" hidden>Genoptag recovery</button>
      <div id="bodyResumeStatus" class="fine-print"></div>`;
    card.appendChild(wrap);
    document.getElementById("bodyResumeButton")?.addEventListener("click", () => void startResume());
    return wrap;
  }

  function labelForMode(mode) {
    if (mode === ADOPT) return "Adoptér allerede færdig package";
    if (mode === FIT_ONLY) return "Genoptag fitter fra bevaret reconstruction";
    return "Genoptag recovery";
  }

  function setState({ visible = false, disabled = false, text = "", sourceJobId = "", recoveryMode = "" } = {}) {
    ensureControls();
    const button = document.getElementById("bodyResumeButton");
    const status = document.getElementById("bodyResumeStatus");
    currentSourceJobId = sourceJobId;
    currentRecoveryMode = recoveryMode;
    if (button) {
      button.hidden = !visible;
      button.disabled = disabled;
      button.textContent = labelForMode(recoveryMode);
    }
    if (status) status.textContent = text;
  }

  function reconnectAutoWorkflow(id, sourceJobId, resumeJobId) {
    const key = `bodyrig-person-auto-v1:${id}`;
    try {
      const workflow = JSON.parse(localStorage.getItem(key) || "null");
      if (!workflow || workflow.version !== 1 || workflow.person_id !== id) return;
      if (workflow.body_job_id !== sourceJobId) return;
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
    const recoveryMode = currentRecoveryMode;
    if (!id || !sourceJobId || ![ADOPT, FIT_ONLY].includes(recoveryMode)) return;
    const preparing = recoveryMode === ADOPT
      ? "Revaliderer session, package og source authority før adoption …"
      : "Revaliderer session, reconstruction og source authority før fit-only recovery …";
    setState({
      visible: true,
      disabled: true,
      sourceJobId,
      recoveryMode,
      text: preparing,
    });
    try {
      const job = await apiJson(`/api/v1/jobs/${encodeURIComponent(sourceJobId)}/resume`, { method: "POST" });
      if (job.resume_mode !== recoveryMode) throw new Error("backend returned a different recovery mode");
      reconnectAutoWorkflow(id, sourceJobId, job.job_id);
      const started = recoveryMode === ADOPT
        ? `Recovery-job ${job.job_id} er startet. Den færdige package adopteres kun efter frisk readiness/session; fitter og reconstruction genkøres ikke.`
        : `Recovery-job ${job.job_id} er startet. Kun fitteren må genkøres; PHALP/4D-Humans reconstruction genkøres ikke.`;
      setState({ visible: false, sourceJobId: "", recoveryMode: "", text: started });
      clearTimeout(timer);
      timer = setTimeout(() => void refresh(), 1000);
    } catch (error) {
      setState({
        visible: true,
        disabled: false,
        sourceJobId,
        recoveryMode,
        text: `Recovery blev afvist fail-closed: ${error.message}`,
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
      if (status.available === true && status.recovery_mode === ADOPT) {
        setState({
          visible: true,
          disabled: false,
          sourceJobId: latest.job_id,
          recoveryMode: ADOPT,
          text: `Færdig package ${String(status.package_sha256 || "").slice(0, 16)}… er hash-verificeret. Adoption genkører hverken fitter eller reconstruction; frisk session, Gate A og fidelity-review kræves stadig.`,
        });
      } else if (status.available === true && status.recovery_mode === FIT_ONLY) {
        setState({
          visible: true,
          disabled: false,
          sourceJobId: latest.job_id,
          recoveryMode: FIT_ONLY,
          text: "Bevaret SiTH reconstruction er hash-verificeret. Recovery kører kun den afbrudte fitter og fortsætter derefter Gate A/fidelity.",
        });
      } else if (status.available === true) {
        setState({
          visible: false,
          sourceJobId: "",
          recoveryMode: "",
          text: "Recovery-planen returnerede en ukendt mode og er skjult fail-closed.",
        });
      } else {
        setState({
          visible: false,
          sourceJobId: "",
          recoveryMode: "",
          text: status.reason ? `Recovery ikke tilgængelig: ${status.reason}` : "",
        });
      }
      timer = setTimeout(() => void refresh(), 10000);
    } catch (error) {
      setState({ visible: false, text: `Kunne ikke kontrollere recovery: ${error.message}` });
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
