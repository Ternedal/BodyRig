(() => {
  const $ = (id) => document.getElementById(id);
  let requestSerial = 0;

  function escapeText(value, fallback = "—") {
    const text = String(value ?? "").trim();
    return text || fallback;
  }

  function bounded(value, limit = 8000) {
    const text = String(value ?? "").trim();
    return text.length > limit ? text.slice(0, limit - 1) + "…" : text;
  }

  function ensureDialog() {
    let dialog = $("personRevisionEvidenceDialog");
    if (dialog) return dialog;

    dialog = document.createElement("dialog");
    dialog.id = "personRevisionEvidenceDialog";
    dialog.className = "person-revision-evidence-dialog";
    dialog.setAttribute("aria-labelledby", "personRevisionEvidenceTitle");
    dialog.innerHTML = `
      <div class="person-revision-evidence-shell">
        <div class="person-revision-evidence-head">
          <div>
            <div class="eyebrow">PERSON REVISION EVIDENCE</div>
            <h3 id="personRevisionEvidenceTitle">Verificerer…</h3>
          </div>
          <button class="icon-button" type="button" data-evidence-close aria-label="Luk">×</button>
        </div>
        <div id="personRevisionEvidenceStatus" class="person-revision-evidence-status muted-text">Henter canonical evidence…</div>
        <div id="personRevisionEvidenceBody" class="person-revision-evidence-body"></div>
      </div>
    `;
    document.body.appendChild(dialog);
    dialog.querySelector("[data-evidence-close]")?.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    return dialog;
  }

  function field(label, value, { mono = false } = {}) {
    const row = document.createElement("div");
    row.className = "person-revision-evidence-field";

    const name = document.createElement("span");
    name.className = "person-revision-evidence-label";
    name.textContent = label;

    const val = document.createElement(mono ? "code" : "span");
    val.className = mono ? "person-revision-evidence-value mono" : "person-revision-evidence-value";
    val.textContent = escapeText(value);

    row.append(name, val);
    return row;
  }

  function section(title) {
    const node = document.createElement("section");
    node.className = "person-revision-evidence-section";
    const heading = document.createElement("h4");
    heading.textContent = title;
    node.appendChild(heading);
    return node;
  }

  function reviewGrid(review) {
    const grid = document.createElement("div");
    grid.className = "person-revision-evidence-review-grid";
    const checks = [
      ["Krop ↔ stemme", review?.body_voice_match],
      ["Stemme ↔ personality", review?.voice_personality_match],
      ["Krop ↔ personality", review?.body_personality_match],
      ["Samlet kohærens", review?.overall_coherent],
    ];
    for (const [label, passed] of checks) {
      const item = document.createElement("div");
      item.className = `person-revision-evidence-check ${passed === true ? "pass" : "fail"}`;
      item.textContent = `${passed === true ? "PASS" : "FAIL"} · ${label}`;
      grid.appendChild(item);
    }
    return grid;
  }

  function renderEvidence(payload) {
    const title = $("personRevisionEvidenceTitle");
    const status = $("personRevisionEvidenceStatus");
    const host = $("personRevisionEvidenceBody");
    if (!title || !status || !host) return;

    title.textContent = escapeText(payload.person_revision, "Person Revision");
    host.replaceChildren();

    const verified = payload.verified === true;
    status.textContent = payload.legacy === true
      ? "Legacy receipt · ingen audition-binding · ikke reaktiverbar under aktuel policy"
      : (verified
          ? "Canonical assembly + audition receipt + WAV er revalideret"
          : "Evidence kunne ikke verificeres");
    status.classList.toggle("verified", verified);
    status.classList.toggle("legacy", payload.legacy === true);

    const overview = section("Binding");
    overview.append(
      field("Aktiv", payload.active === true ? "Ja" : "Nej"),
      field("Body", payload.body_revision),
      field("Voice", payload.voice_revision),
      field("Personality", payload.personality_revision),
      field("Assembly receipt", `v${payload.assembly_receipt_version ?? "?"}`),
      field("Assembly fingerprint", payload.assembly_fingerprint, { mono: true }),
    );
    host.appendChild(overview);

    const review = section("Compatibility review");
    review.appendChild(reviewGrid(payload.compatibility_review || {}));
    review.appendChild(field("Review-note", bounded(payload.compatibility_review?.note || "")));
    if (payload.feedback) review.appendChild(field("Revision feedback", bounded(payload.feedback)));
    host.appendChild(review);

    if (payload.audition && typeof payload.audition === "object") {
      const audition = section("Audition authority");
      audition.append(
        field("Audition", payload.audition.audition_id, { mono: true }),
        field("Oprettet", payload.audition.created_utc),
        field("Model", payload.audition.model),
        field("ModelRig", `${payload.audition.modelrig_service || "—"} · ${payload.audition.modelrig_version || "—"}`),
        field("VoiceRig", `${payload.audition.voicerig_service || "—"} · ${payload.audition.voicerig_version || "—"}`),
        field("Prompt SHA-256", payload.audition.prompt_sha256, { mono: true }),
        field("Reply SHA-256", payload.audition.reply_sha256, { mono: true }),
        field("Audio SHA-256", payload.audition.audio_sha256, { mono: true }),
        field("Receipt SHA-256", payload.audition.receipt_sha256, { mono: true }),
      );

      if (payload.audition.audio_url) {
        const audioLabel = document.createElement("div");
        audioLabel.className = "person-revision-evidence-label";
        audioLabel.textContent = "Audition audio";
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.preload = "none";
        audio.className = "full";
        audio.src = String(payload.audition.audio_url);
        audition.append(audioLabel, audio);
      }
      host.appendChild(audition);
    } else if (payload.reason) {
      const legacy = section("Authority status");
      legacy.appendChild(field("Årsag", bounded(payload.reason)));
      host.appendChild(legacy);
    }
  }

  async function openEvidence(revisionId) {
    const personId = String($("personId")?.textContent || "").trim();
    if (!personId || !revisionId) return;

    const dialog = ensureDialog();
    const title = $("personRevisionEvidenceTitle");
    const status = $("personRevisionEvidenceStatus");
    const host = $("personRevisionEvidenceBody");
    if (title) title.textContent = revisionId;
    if (status) {
      status.textContent = "Revaliderer assembly receipt, audition receipt og WAV…";
      status.classList.remove("verified", "legacy");
    }
    host?.replaceChildren();
    if (!dialog.open) dialog.showModal();

    const serial = ++requestSerial;
    try {
      const response = await fetch(
        `/api/v1/people/${encodeURIComponent(personId)}/revisions/${encodeURIComponent(revisionId)}/evidence`,
        { headers: { Accept: "application/json" }, cache: "no-store" }
      );
      let payload = null;
      try { payload = await response.json(); } catch { payload = null; }
      if (serial !== requestSerial || !dialog.open) return;
      if (!response.ok) {
        throw new Error(payload?.detail || `HTTP ${response.status}`);
      }
      renderEvidence(payload || {});
    } catch (error) {
      if (serial !== requestSerial) return;
      if (status) {
        status.textContent = `Fail-closed: ${error.message}`;
        status.classList.remove("verified", "legacy");
      }
      host?.replaceChildren();
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.(".inspect-person-revision");
    if (!button) return;
    event.preventDefault();
    void openEvidence(String(button.dataset.revision || ""));
  });
})();