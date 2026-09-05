(() => {
  const $ = (id) => document.getElementById(id);
  const VIEW_LABELS = {
    "front-full": "Front · helfigur",
    "three-quarter-full": "¾ · helfigur",
    "side-full": "Side · helfigur",
    "face-front": "Ansigt · front",
    "face-zoom": "Ansigt · tæt på",
    "eyes-closeup": "Øjne · tæt på",
  };
  const FINAL = new Set(["succeeded", "failed", "interrupted"]);
  let timer = null;
  let serial = 0;

  function currentPersonId() {
    return ($("personId")?.textContent || "").trim();
  }

  function currentBodyRevision() {
    const value = ($("bodyRevisionLabel")?.textContent || "").trim();
    return value.startsWith("body-r") ? value : "";
  }

  async function request(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body !== undefined && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const response = await fetch(path, { ...options, headers, cache: "no-store" });
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const detail = payload && typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`;
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function ensureCard() {
    let card = $("highFidelityPreviewCard");
    if (card) return card;
    const tab = $("tab-body");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "highFidelityPreviewCard";
    card.className = "card space-top";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">High-fidelity source review · 6 views</div>
          <div id="highFidelityPreviewSummary" class="muted-text">Vælg en body-revision.</div>
        </div>
        <span id="highFidelityPreviewBadge" class="badge muted">Ikke kørt</span>
      </div>
      <p class="muted-text">Fortsætter fra den bevarede source-anatomi uden at køre SiTH-rekonstruktionen igen. Model-family skal vælges eksplicit; BodyRig gætter ikke personens anatomy-family.</p>
      <div class="form-grid">
        <label>
          <span>SMPL-X target family</span>
          <select id="highFidelityTargetFamily">
            <option value="">Vælg eksplicit…</option>
            <option value="female">female</option>
            <option value="male">male</option>
            <option value="neutral">neutral</option>
          </select>
        </label>
      </div>
      <button id="highFidelityPreviewStart" class="primary full">Byg anatomy + hår + øjne review-preview</button>
      <div id="highFidelityPreviewProgress" class="space-top" hidden>
        <progress id="highFidelityPreviewProgressBar" max="100" value="0" style="width:100%"></progress>
        <div id="highFidelityPreviewProgressText" class="fine-print"></div>
      </div>
      <div id="highFidelityPreviewGrid" class="body-review-grid"></div>
      <p id="highFidelityPreviewDetail" class="fine-print">Comparison-only. Hår/øjne/cornea kan vurderes visuelt her, men billederne giver ikke component PASS, human-review PASS eller production activation.</p>`;
    const baseline = $("bodyReviewGalleryCard");
    if (baseline) baseline.insertAdjacentElement("afterend", card);
    else tab.appendChild(card);
    $("highFidelityPreviewStart")?.addEventListener("click", () => void startPreview());
    return card;
  }

  function nodes() {
    ensureCard();
    return {
      summary: $("highFidelityPreviewSummary"),
      badge: $("highFidelityPreviewBadge"),
      family: $("highFidelityTargetFamily"),
      button: $("highFidelityPreviewStart"),
      progress: $("highFidelityPreviewProgress"),
      progressBar: $("highFidelityPreviewProgressBar"),
      progressText: $("highFidelityPreviewProgressText"),
      grid: $("highFidelityPreviewGrid"),
      detail: $("highFidelityPreviewDetail"),
    };
  }

  function clearImages() {
    const { grid } = nodes();
    if (grid) grid.replaceChildren();
  }

  function renderIdle(message) {
    const { summary, badge, button, progress, detail } = nodes();
    if (summary) summary.textContent = message;
    if (badge) {
      badge.textContent = "Ikke kørt";
      badge.classList.add("muted");
    }
    if (button) button.disabled = false;
    if (progress) progress.hidden = true;
    if (detail) detail.textContent = "Comparison-only. Vælg target family eksplicit og kør previewet fra den eksisterende source-bound body-build.";
    clearImages();
  }

  function renderRunning(job) {
    const { summary, badge, button, family, progress, progressBar, progressText, detail } = nodes();
    if (summary) summary.textContent = `${job.body_revision} · ${job.target_family} · ${job.message || job.stage || "kører"}`;
    if (badge) {
      badge.textContent = `${Number(job.progress || 0)}%`;
      badge.classList.add("muted");
    }
    if (button) button.disabled = true;
    if (family && job.target_family) family.value = job.target_family;
    if (progress) progress.hidden = false;
    if (progressBar) progressBar.value = Math.max(0, Math.min(100, Number(job.progress || 0)));
    if (progressText) progressText.textContent = `${job.stage || "kører"} · ${job.message || ""}`;
    if (detail) detail.textContent = "Baseline body revision er allerede registreret. Hvis denne continuation stopper, bliver baseline ikke rullet tilbage eller promoted.";
    clearImages();
  }

  function renderFailed(job) {
    const { summary, badge, button, family, progress, progressBar, progressText, detail } = nodes();
    if (summary) summary.textContent = `${job.body_revision || currentBodyRevision()} · high-fidelity continuation stoppede fail-closed.`;
    if (badge) {
      badge.textContent = "Stoppet";
      badge.classList.add("muted");
    }
    if (button) button.disabled = false;
    if (family && job.target_family) family.value = job.target_family;
    if (progress) progress.hidden = false;
    if (progressBar) progressBar.value = Math.max(0, Math.min(100, Number(job.progress || 0)));
    if (progressText) progressText.textContent = job.error || job.message || "High-fidelity preview fejlede.";
    if (detail) detail.textContent = "Baseline body revision er bevaret. Ret fejlårsagen og retry eksplicit; ingen component- eller production-authority blev givet.";
    clearImages();
  }

  function renderReady(job, currentSerial) {
    const { summary, badge, button, family, progress, progressBar, progressText, grid, detail } = nodes();
    const views = Array.isArray(job.views) ? job.views : [];
    if (views.length !== 6 || !views.every((view) => VIEW_LABELS[view.view] && typeof view.url === "string" && typeof view.sha256 === "string")) {
      return renderFailed({ ...job, error: "Preview-kontrakten returnerede ikke seks canonical/diagnostic views." });
    }
    if (summary) summary.textContent = `${job.body_revision} · target ${job.target_family} · review VRM ${String(job.review_vrm_sha256 || "").slice(0, 16)}…`;
    if (badge) {
      badge.textContent = "6 views klar";
      badge.classList.remove("muted");
    }
    if (button) button.disabled = false;
    if (family && job.target_family) family.value = job.target_family;
    if (progress) progress.hidden = false;
    if (progressBar) progressBar.value = 100;
    if (progressText) progressText.textContent = "Exact-hash preview-evidence er genvalideret.";
    if (!grid || !detail) return;
    grid.replaceChildren();
    let loaded = 0;
    let failed = false;
    for (const view of views) {
      const figure = document.createElement("figure");
      figure.className = "body-review-view";
      const image = document.createElement("img");
      image.alt = `${VIEW_LABELS[view.view]} · ${job.body_revision}`;
      image.loading = "lazy";
      image.decoding = "async";
      image.src = `${view.url}?v=${encodeURIComponent(view.sha256)}`;
      const caption = document.createElement("figcaption");
      const title = document.createElement("strong");
      title.textContent = VIEW_LABELS[view.view];
      const meta = document.createElement("span");
      meta.textContent = `${view.sha256.slice(0, 12)}…`;
      caption.append(title, meta);
      figure.append(image, caption);
      grid.appendChild(figure);
      image.addEventListener("load", () => {
        if (currentSerial !== serial || failed) return;
        loaded += 1;
        if (loaded === views.length && badge) badge.textContent = "6/6 hash-bundet";
      });
      image.addEventListener("error", () => {
        if (currentSerial !== serial) return;
        failed = true;
        if (badge) {
          badge.textContent = "Image ugyldigt";
          badge.classList.add("muted");
        }
        detail.textContent = "Fail-closed: mindst ét preview-image kunne ikke genvalideres eller indlæses.";
      });
    }
    detail.textContent = `Source hair + source-baket eye surface + runtime cornea. Iris: ${job.iris_identity_status || "review-pending"}. Eyelashes: ${job.eyelash_status || "missing"}. Human review kræves stadig; production activation=false.`;
  }

  async function latest(personId, revision) {
    return request(`/api/v1/people/${encodeURIComponent(personId)}/body/high-fidelity-preview?revision=${encodeURIComponent(revision)}`);
  }

  async function findBodyJob(personId, revision) {
    const payload = await request(`/api/v1/jobs?person_id=${encodeURIComponent(personId)}`);
    const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
    return jobs
      .filter((job) => job?.kind === "body-build" && job.status === "succeeded" && job.body_revision === revision)
      .sort((a, b) => String(b.completed_utc || b.created_utc || "").localeCompare(String(a.completed_utc || a.created_utc || "")))[0] || null;
  }

  async function startPreview() {
    const personId = currentPersonId();
    const revision = currentBodyRevision();
    const { family, button, summary } = nodes();
    const targetFamily = String(family?.value || "");
    if (!personId || !revision) return renderIdle("Vælg en person med en registreret body revision først.");
    if (!targetFamily) {
      if (summary) summary.textContent = "Vælg female, male eller neutral eksplicit. BodyRig gætter ikke target family.";
      return;
    }
    if (button) button.disabled = true;
    try {
      const bodyJob = await findBodyJob(personId, revision);
      if (!bodyJob) throw new Error("Denne body revision har ingen succeeded fysisk UI body-build med retained anatomy-source.");
      const job = await request(`/api/v1/people/${encodeURIComponent(personId)}/body/high-fidelity-preview`, {
        method: "POST",
        body: JSON.stringify({ body_job_id: bodyJob.job_id, target_family: targetFamily }),
      });
      renderRunning(job);
      schedule(1000);
    } catch (error) {
      renderFailed({ body_revision: revision, target_family: targetFamily, error: error.message, progress: 0 });
    }
  }

  async function refresh() {
    ensureCard();
    const personId = currentPersonId();
    const revision = currentBodyRevision();
    const currentSerial = ++serial;
    if (!personId || !revision) {
      renderIdle("Vælg en person med en registreret body revision.");
      return;
    }
    try {
      const job = await latest(personId, revision);
      if (currentSerial !== serial || personId !== currentPersonId() || revision !== currentBodyRevision()) return;
      if (job.status === "succeeded") renderReady(job, currentSerial);
      else if (job.status === "failed" || job.status === "interrupted") renderFailed(job);
      else renderRunning(job);
      if (!FINAL.has(job.status)) schedule(2000);
    } catch (error) {
      if (currentSerial !== serial) return;
      if (error.status === 404) renderIdle(`${revision} har endnu ingen high-fidelity hair+eye preview.`);
      else renderFailed({ body_revision: revision, error: error.message, progress: 0 });
    }
  }

  function schedule(delay = 2000) {
    clearTimeout(timer);
    timer = setTimeout(() => void refresh(), delay);
  }

  for (const id of ["personId", "bodyRevisionLabel"]) {
    const node = $(id);
    if (node) {
      new MutationObserver(() => schedule(0)).observe(node, { childList: true, characterData: true, subtree: true });
    }
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) schedule(0);
  });
  window.addEventListener("DOMContentLoaded", () => {
    ensureCard();
    schedule(0);
  }, { once: true });
})();
