(() => {
  const $ = (id) => document.getElementById(id);
  let serial = 0;
  let timer = null;

  function currentPersonId() {
    return ($("personId")?.textContent || "").trim();
  }

  function currentBodyRevision() {
    const value = ($("bodyRevisionLabel")?.textContent || "").trim();
    return value.startsWith("body-r") ? value : "";
  }

  async function request(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) {
      const detail = payload && typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`;
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function ensureCard() {
    let card = $("highFidelityHairDeformationReviewCard");
    if (card) return card;
    const tab = $("tab-body");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "highFidelityHairDeformationReviewCard";
    card.className = "card space-top";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">Hair deformation review authority</div>
          <div id="highFidelityHairDeformationReviewSummary" class="muted-text">Kræver canonical component review og machine deformation PASS.</div>
        </div>
        <span id="highFidelityHairDeformationReviewBadge" class="badge muted">Ikke klar</span>
      </div>
      <pre id="highFidelityHairDeformationReviewCommand" class="proposal" hidden></pre>
      <p id="highFidelityHairDeformationReviewDetail" class="fine-print">Reviewet er create-only og exact-hash-bundet til machine probe, comparison authority, component review, VRM og candidate package. Det kan kun gøre hair promotion-eligible. Det promoter ikke hair, ændrer ingen package og production_activation=false.</p>`;
    const component = $("highFidelityComponentReviewCard");
    if (component) component.insertAdjacentElement("afterend", card);
    else tab.appendChild(card);
    return card;
  }

  function nodes() {
    ensureCard();
    return {
      summary: $("highFidelityHairDeformationReviewSummary"),
      badge: $("highFidelityHairDeformationReviewBadge"),
      command: $("highFidelityHairDeformationReviewCommand"),
      detail: $("highFidelityHairDeformationReviewDetail"),
    };
  }

  function renderBlocked(revision, status) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${revision} · hair deformation authority er blokeret.`;
    if (badge) {
      badge.textContent = "Blokeret";
      badge.classList.add("muted");
    }
    if (command) {
      command.textContent = "";
      command.hidden = true;
    }
    if (detail) detail.textContent = `${status?.reason || "Canonical machine deformation authority er endnu ikke klar."} Ingen hair promotion authority gættes eller auto-promotes.`;
  }

  function renderRequired(job, status) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${job.body_revision} · machine deformation PASS; fysisk hair review mangler.`;
    if (badge) {
      badge.textContent = "Review kræves";
      badge.classList.add("muted");
    }
    if (command) {
      command.hidden = false;
      command.textContent = `& ".\\record-high-fidelity-hair-deformation-review.ps1" -PreviewJobId "${job.job_id}" -ConfirmHairDeformationChecklist -QualityNote "<review head-turn, attachment, clipping, silhouette og neutral restoration>"`;
    }
    if (detail) {
      detail.textContent = `${status?.reason || "Explicit physical review required."} Kør kommandoen fra den clean exact BodyRig checkout efter fysisk vurdering af hele head-turn-sekvensen. Receipt gør kun hair promotion-eligible; den ændrer ingen candidate package.`;
    }
  }

  function renderPass(job, status) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${job.body_revision} · hair deformation review ${status.reviewed_utc || "PASS"}.`;
    if (badge) {
      badge.textContent = "Hair promotion-eligible";
      badge.classList.remove("muted");
    }
    if (command) {
      command.textContent = "";
      command.hidden = true;
    }
    if (detail) {
      detail.textContent = "Exact machine deformation evidence og fysisk clipping/attachment/deformation review er PASS. Hair er promotion-eligible, men er endnu ikke promoted; ingen package er muteret. Eyes er fortsat låst af iris authority, og production_activation=false.";
    }
  }

  function renderInvalid(revision, status) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${revision} · hair deformation review authority er ugyldig.`;
    if (badge) {
      badge.textContent = "Review ugyldigt";
      badge.classList.add("muted");
    }
    if (command) {
      command.textContent = "";
      command.hidden = true;
    }
    if (detail) detail.textContent = `Fail-closed: ${status?.reason || "receipt matcher ikke længere exact authority"}. Hair er ikke promotion-eligible.`;
  }

  async function refresh() {
    ensureCard();
    const personId = currentPersonId();
    const revision = currentBodyRevision();
    const currentSerial = ++serial;
    if (!personId || !revision) return renderBlocked(revision || "Ingen body revision", { reason: "Vælg en person med en body revision." });
    try {
      const preview = await request(`/api/v1/people/${encodeURIComponent(personId)}/body/high-fidelity-preview?revision=${encodeURIComponent(revision)}`);
      if (currentSerial !== serial || personId !== currentPersonId() || revision !== currentBodyRevision()) return;
      if (preview.status !== "succeeded") return renderBlocked(revision, { reason: "High-fidelity preview er ikke færdigt endnu." });
      const status = await request(`/api/v1/high-fidelity-preview-jobs/${encodeURIComponent(preview.job_id)}/hair-deformation-review`);
      if (currentSerial !== serial || personId !== currentPersonId() || revision !== currentBodyRevision()) return;
      if (status.state === "pass" && status.passed === true && status.hair_promotion_eligible === true && status.production_activation === false) {
        renderPass(preview, status);
      } else if (status.state === "required" && status.machine_pass === true) {
        renderRequired(preview, status);
      } else if (status.state === "invalid") {
        renderInvalid(revision, status);
      } else {
        renderBlocked(revision, status);
      }
    } catch (error) {
      if (currentSerial !== serial) return;
      renderBlocked(revision, { reason: `Hair deformation review kunne ikke valideres: ${error.message}` });
    }
  }

  function schedule(delay = 500) {
    clearTimeout(timer);
    timer = setTimeout(() => void refresh(), delay);
  }

  for (const id of ["personId", "bodyRevisionLabel"]) {
    const node = $(id);
    if (node) new MutationObserver(() => schedule(0)).observe(node, { childList: true, characterData: true, subtree: true });
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) schedule(0); });
  window.addEventListener("DOMContentLoaded", () => { ensureCard(); schedule(0); }, { once: true });
  ensureCard();
  schedule(0);
})();
