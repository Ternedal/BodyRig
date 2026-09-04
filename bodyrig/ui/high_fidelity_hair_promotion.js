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
    let card = $("highFidelityHairPromotionCard");
    if (card) return card;
    const tab = $("tab-body");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "highFidelityHairPromotionCard";
    card.className = "card space-top";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">Hair promotion · exact hair-only materialization</div>
          <div id="highFidelityHairPromotionSummary" class="muted-text">Kræver anatomy promotion + exact hair deformation review PASS.</div>
        </div>
        <span id="highFidelityHairPromotionBadge" class="badge muted">Ikke klar</span>
      </div>
      <pre id="highFidelityHairPromotionCommand" class="proposal" hidden></pre>
      <p id="highFidelityHairPromotionDetail" class="fine-print">Promotion rekonstruerer den hair-only runtime og kræver canonical bridge-hash match mod den fysisk reviewede combined preview. Combined hair+eye VRM bruges aldrig som package authority. Eyes forbliver låst, og production_activation=false.</p>`;
    const deformation = $("highFidelityHairDeformationReviewCard");
    if (deformation) deformation.insertAdjacentElement("afterend", card);
    else tab.appendChild(card);
    return card;
  }

  function nodes() {
    ensureCard();
    return {
      summary: $("highFidelityHairPromotionSummary"),
      badge: $("highFidelityHairPromotionBadge"),
      command: $("highFidelityHairPromotionCommand"),
      detail: $("highFidelityHairPromotionDetail"),
    };
  }

  function renderBlocked(revision, status) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${revision} · hair promotion er blokeret.`;
    if (badge) { badge.textContent = "Blokeret"; badge.classList.add("muted"); }
    if (command) { command.textContent = ""; command.hidden = true; }
    if (detail) detail.textContent = `${status?.reason || "Anatomy/hair review authority er ikke komplet."} Ingen package materialiseres eller gættes.`;
  }

  function renderRequired(job, status) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${job.body_revision} · anatomy + hair deformation authority er PASS; materialization mangler.`;
    if (badge) { badge.textContent = "Promotion kræves"; badge.classList.add("muted"); }
    if (command) {
      command.hidden = false;
      command.textContent = `& ".\\promote-high-fidelity-hair.ps1" -PreviewJobId "${job.job_id}"`;
    }
    if (detail) {
      const bridge = status?.expected_hair_review_bridge_sha256 || "ukendt";
      detail.textContent = `Kør fra en clean exact BodyRig checkout på Windows/PowerShell 7+. Wrapperen reconstruerer hair-only runtime og kræver exact reviewed bridge hash ${bridge}. Den combined hair+eye VRM kopieres aldrig. Eyes forbliver uændrede; production_activation=false.`;
    }
  }

  function renderPass(job, status) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${job.body_revision} · hair er materialiseret som separat hash-bundet component authority.`;
    if (badge) { badge.textContent = "Hair complete"; badge.classList.remove("muted"); }
    if (command) { command.textContent = ""; command.hidden = true; }
    if (detail) {
      detail.textContent = `body_anatomy=complete + hair=complete. Promoted package SHA: ${status.promoted_package_sha256 || "ukendt"}. Eye review runtime er ikke importeret; iris/eyes og face-secondary er fortsat separate blockers. production_activation=false.`;
    }
  }

  function renderInvalid(revision, status) {
    const { summary, badge, command, detail } = nodes();
    if (summary) summary.textContent = `${revision} · hair promotion authority er ugyldig.`;
    if (badge) { badge.textContent = "Promotion ugyldig"; badge.classList.add("muted"); }
    if (command) { command.textContent = ""; command.hidden = true; }
    if (detail) detail.textContent = `Fail-closed: ${status?.reason || "promotion evidence matcher ikke exact authority"}. Hair regnes ikke som complete.`;
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
      const status = await request(`/api/v1/high-fidelity-preview-jobs/${encodeURIComponent(preview.job_id)}/hair-promotion`);
      if (currentSerial !== serial || personId !== currentPersonId() || revision !== currentBodyRevision()) return;
      if (status.state === "pass" && status.passed === true && status.hair_complete === true && status.eyes_imported === false && status.production_activation === false) {
        renderPass(preview, status);
      } else if (status.state === "required" && status.production_activation === false) {
        renderRequired(preview, status);
      } else if (status.state === "invalid") {
        renderInvalid(revision, status);
      } else {
        renderBlocked(revision, status);
      }
    } catch (error) {
      if (currentSerial !== serial) return;
      renderBlocked(revision, { reason: `Hair promotion kunne ikke valideres: ${error.message}` });
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
