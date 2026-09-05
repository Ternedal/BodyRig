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
    let card = $("highFidelityComponentReviewCard");
    if (card) return card;
    const tab = $("tab-body");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "highFidelityComponentReviewCard";
    card.className = "card space-top";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">Component visual review authority</div>
          <div id="highFidelityComponentReviewSummary" class="muted-text">Kræver et validt 6-view high-fidelity preview.</div>
        </div>
        <span id="highFidelityComponentReviewBadge" class="badge muted">Ikke klar</span>
      </div>
      <pre id="highFidelityComponentReviewCommand" class="proposal" hidden></pre>
      <p id="highFidelityComponentReviewDetail" class="fine-print">Reviewet er create-only og exact-hash-bundet. Det kan kun gøre anatomy promotion-eligible; hair kræver stadig runtime deformation review, og eyes kræver stadig iris authority. production_activation=false.</p>`;
    const preview = $("highFidelityPreviewCard");
    if (preview) preview.insertAdjacentElement("afterend", card);
    else tab.appendChild(card);
    return card;
  }

  function nodes() {
    ensureCard();
    return {
      summary: $("highFidelityComponentReviewSummary"),
      badge: $("highFidelityComponentReviewBadge"),
      command: $("highFidelityComponentReviewCommand"),
      detail: $("highFidelityComponentReviewDetail"),
    };
  }

  function reset(message, badgeText = "Ikke klar") {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = message;
    if (badge) {
      badge.textContent = badgeText;
      badge.classList.add("muted");
    }
    if (command) {
      command.textContent = "";
      command.hidden = true;
    }
    if (detail) detail.textContent = "Kræver et succeeded exact-hash 6-view preview. Ingen component- eller production-authority gættes eller auto-promotes.";
  }

  function renderRequired(job, status) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${job.body_revision} · review af anatomy, hår-silhouette og face/eyes close-up mangler.`;
    if (badge) {
      badge.textContent = "Review kræves";
      badge.classList.add("muted");
    }
    if (command) {
      command.hidden = false;
      command.textContent = `& ".\\record-high-fidelity-component-review.ps1" -PreviewJobId "${job.job_id}" -ConfirmVisualChecklist -QualityNote "<din fysiske anatomy/hair/eye-review>"`;
    }
    if (detail) {
      const eligible = status?.promotion_eligibility?.body_anatomy === true ? "Anatomy kan blive promotion-eligible efter receipt." : "Anatomy promotion er låst.";
      detail.textContent = `${eligible} Hair forbliver låst af runtime deformation review; eyes forbliver låst af iris authority. Kør kommandoen fra den clean exact BodyRig checkout, efter at alle seks views er fysisk vurderet.`;
    }
  }

  function renderPass(job, status, promotion) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${job.body_revision} · visual component review ${status.reviewed_utc || "PASS"}.`;
    if (badge) {
      badge.textContent = promotion?.state === "pass" ? "Anatomy promoted" : "Visual review PASS";
      badge.classList.remove("muted");
    }
    if (command) {
      command.textContent = "";
      command.hidden = true;
      if (promotion?.state === "required") {
        command.hidden = false;
        command.textContent = `& ".\\promote-high-fidelity-anatomy.ps1" -PreviewJobId "${job.job_id}"`;
      }
    }
    if (!detail) return;
    if (promotion?.state === "pass") {
      detail.textContent = "Exact reviewed anatomy er materialiseret i en ny hash-bundet candidate package med body_anatomy=complete. Baseline-pakken er urørt; hair kræver stadig runtime deformation authority, eyes kræver stadig iris authority, og production_activation=false.";
    } else if (promotion?.state === "required") {
      detail.textContent = "Exact preview-evidence er reviewet. body_anatomy er nu promotion-eligible; kør den viste clean-checkout kommando for at skabe en NY candidate package. Hair/eyes forbliver låst og ændres ikke af anatomy promotion.";
    } else if (promotion?.state === "invalid") {
      detail.textContent = `Anatomy promotion authority er ugyldig og fail-closed: ${promotion.reason || "ukendt mismatch"}. Ingen package må behandles som promoted.`;
      if (badge) {
        badge.textContent = "Promotion ugyldig";
        badge.classList.add("muted");
      }
    } else {
      detail.textContent = "Exact preview-evidence er reviewet, men anatomy promotion er stadig blokeret. Hair er kun visual-pass og mangler runtime deformation review; eyes er kun visual-pass og mangler iris authority.";
    }
  }

  async function refresh() {
    ensureCard();
    const personId = currentPersonId();
    const revision = currentBodyRevision();
    const currentSerial = ++serial;
    if (!personId || !revision) return reset("Vælg en person med en body revision.");
    try {
      const preview = await request(`/api/v1/people/${encodeURIComponent(personId)}/body/high-fidelity-preview?revision=${encodeURIComponent(revision)}`);
      if (currentSerial !== serial || personId !== currentPersonId() || revision !== currentBodyRevision()) return;
      if (preview.status !== "succeeded") return reset(`${revision} · high-fidelity preview er ikke færdigt endnu.`);
      const status = await request(`/api/v1/high-fidelity-preview-jobs/${encodeURIComponent(preview.job_id)}/component-review`);
      if (currentSerial !== serial || personId !== currentPersonId() || revision !== currentBodyRevision()) return;
      if (status.state === "pass" && status.passed === true) {
        const promotion = await request(`/api/v1/high-fidelity-preview-jobs/${encodeURIComponent(preview.job_id)}/anatomy-promotion`);
        if (currentSerial !== serial || personId !== currentPersonId() || revision !== currentBodyRevision()) return;
        renderPass(preview, status, promotion);
      } else if (status.state === "required") renderRequired(preview, status);
      else reset(`${revision} · component review authority er ikke tilgængelig.`, "Review ugyldigt");
    } catch (error) {
      if (currentSerial !== serial) return;
      if (error.status === 404) reset(`${revision} · kræver først et validt high-fidelity preview.`);
      else reset(`${revision} · component review kunne ikke valideres: ${error.message}`, "Review ugyldigt");
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
