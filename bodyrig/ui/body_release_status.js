(() => {
  const STAGE_LABELS = {
    gate_a: "Gate A",
    windows: "Windows",
    quest: "Quest",
    release: "Release",
  };
  const STATE_LABELS = {
    pass: "PASS",
    pending: "Afventer",
    unknown: "Ukendt",
    blocked: "Blokeret",
    "machine-probe-required": "Probe kræves",
    "human-review-required": "Human review",
    "release-gate-required": "Release gate",
  };
  const GATE_LABELS = {
    "origin-evidence": "Oprindelsesevidence",
    "windows-probe": "Windows fysisk probe",
    "windows-attestation": "Windows human quality review",
    "quest-probe": "Quest fysisk probe",
    "quest-attestation": "Quest human quality review",
    "reference-layout": "Canonical renderer-layout",
    "reference-contract": "Reference renderer-contract",
    release: "Final release gate",
  };
  const FIDELITY_LABELS = {
    body_anatomy: "Anatomi",
    skin_appearance: "Hud / overflade",
    hair: "Hår",
    eyes: "Øjne",
    face_secondary: "Ansigtsdetaljer",
  };
  const FACE_LABELS = {
    eyebrow_appearance: "Øjenbryn",
    lip_boundary: "Læbekant",
    mouth_interior: "Mundinteriør",
    teeth: "Tænder",
    eyelashes: "Øjenvipper",
  };
  const FIDELITY_STATE_LABELS = {
    complete: "Komplet",
    partial: "Delvis",
    missing: "Mangler",
    "not-evaluated": "Ikke evalueret",
    unknown: "Ukendt",
  };
  let requestSerial = 0;
  let lastKey = "";

  function currentPersonId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function currentBodyRevision() {
    const value = (document.getElementById("bodyRevisionLabel")?.textContent || "").trim();
    return value.startsWith("body-r") ? value : "";
  }

  function ensureCard() {
    let card = document.getElementById("bodyReleaseStatusCard");
    if (card) return card;
    const tab = document.getElementById("tab-body");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "bodyReleaseStatusCard";
    card.className = "card space-top";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">Fysisk release authority</div>
          <div id="bodyReleaseSummary" class="muted-text">Ingen body-revision valgt.</div>
        </div>
        <span id="bodyReleaseBadge" class="badge muted">Production låst</span>
      </div>
      <div id="bodyReleaseStages" class="body-release-stages"></div>
      <div id="bodyReleaseNext" class="body-release-next fine-print"></div>
      <pre id="bodyReleaseCommand" class="proposal body-release-command hidden"></pre>
      <div class="divider"></div>
      <div class="card-row">
        <div>
          <div class="card-label">High-fidelity komponenter</div>
          <div id="bodyFidelitySummary" class="muted-text">Ingen fidelity-evidence læst.</div>
        </div>
        <span id="bodyFidelityBadge" class="badge muted">Ukendt</span>
      </div>
      <div id="bodyFidelityComponents" class="body-release-stages"></div>
      <div id="bodyFaceFidelitySummary" class="fine-print"></div>
      <div id="bodyFaceFidelityComponents" class="body-release-stages"></div>
      <div class="card-row space-top">
        <div>
          <div class="card-label">High-fidelity human review</div>
          <div id="bodyFidelityReviewSummary" class="muted-text">Review authority er ikke læst.</div>
        </div>
        <span id="bodyFidelityReviewBadge" class="badge muted">Ukendt</span>
      </div>
      <div id="bodyFidelityReviewNext" class="body-release-next fine-print"></div>
      <pre id="bodyFidelityReviewCommand" class="proposal body-release-command hidden"></pre>
      <p class="fine-print">Read-only status. En aktiv Person Revision betyder kun, at body + voice + personality er valgt som den aktive samlede Person; det er ikke production authority. Production kræver tre uafhængige led: komplette high-fidelity component receipts, et eksplicit package-/component-state-bundet high-fidelity human review og den fysiske Windows + Quest final release authority.</p>`;
    const gallery = document.getElementById("bodyReviewGalleryCard");
    if (gallery) gallery.insertAdjacentElement("afterend", card);
    else {
      const candidates = tab.querySelector(":scope > .card.space-top");
      if (candidates) candidates.insertAdjacentElement("beforebegin", card);
      else tab.appendChild(card);
    }
    return card;
  }

  function nodes() {
    ensureCard();
    return {
      summary: document.getElementById("bodyReleaseSummary"),
      badge: document.getElementById("bodyReleaseBadge"),
      stages: document.getElementById("bodyReleaseStages"),
      next: document.getElementById("bodyReleaseNext"),
      command: document.getElementById("bodyReleaseCommand"),
      fidelitySummary: document.getElementById("bodyFidelitySummary"),
      fidelityBadge: document.getElementById("bodyFidelityBadge"),
      fidelityComponents: document.getElementById("bodyFidelityComponents"),
      faceSummary: document.getElementById("bodyFaceFidelitySummary"),
      faceComponents: document.getElementById("bodyFaceFidelityComponents"),
      fidelityReviewSummary: document.getElementById("bodyFidelityReviewSummary"),
      fidelityReviewBadge: document.getElementById("bodyFidelityReviewBadge"),
      fidelityReviewNext: document.getElementById("bodyFidelityReviewNext"),
      fidelityReviewCommand: document.getElementById("bodyFidelityReviewCommand"),
    };
  }

  function renderStages(stagesValue) {
    const { stages } = nodes();
    if (!stages) return;
    stages.replaceChildren();
    const value = stagesValue && typeof stagesValue === "object" ? stagesValue : {};
    for (const key of ["gate_a", "windows", "quest", "release"]) {
      const state = typeof value[key] === "string" ? value[key] : "unknown";
      const item = document.createElement("div");
      item.className = `body-release-stage ${state === "pass" ? "pass" : "pending"}`;
      const name = document.createElement("strong");
      name.textContent = STAGE_LABELS[key];
      const status = document.createElement("span");
      status.textContent = STATE_LABELS[state] || state;
      item.append(name, status);
      stages.appendChild(item);
    }
  }

  function renderComponentSet(container, components, labels) {
    if (!container) return;
    container.replaceChildren();
    const value = components && typeof components === "object" ? components : {};
    for (const key of Object.keys(labels)) {
      const state = typeof value[key] === "string" ? value[key] : "unknown";
      const item = document.createElement("div");
      item.className = `body-release-stage ${state === "complete" ? "pass" : "pending"}`;
      const name = document.createElement("strong");
      name.textContent = labels[key];
      const status = document.createElement("span");
      status.textContent = FIDELITY_STATE_LABELS[state] || state;
      item.append(name, status);
      container.appendChild(item);
    }
  }

  function renderHumanFidelityReview(review, bodyId) {
    const { fidelityReviewSummary, fidelityReviewBadge, fidelityReviewNext, fidelityReviewCommand } = nodes();
    if (!fidelityReviewSummary || !fidelityReviewBadge || !fidelityReviewNext || !fidelityReviewCommand) return;
    const value = review && typeof review === "object" ? review : {};
    const state = typeof value.state === "string" ? value.state : "unavailable";
    fidelityReviewNext.textContent = "";
    fidelityReviewCommand.textContent = "";
    fidelityReviewCommand.classList.add("hidden");
    if (state === "pass" && value.passed === true) {
      fidelityReviewBadge.textContent = "Review PASS";
      fidelityReviewBadge.classList.remove("muted");
      const when = value.reviewed_utc ? ` · ${value.reviewed_utc}` : "";
      fidelityReviewSummary.textContent = `Eksakt package + component-state review er revalideret${when}.`;
      return;
    }
    fidelityReviewBadge.classList.add("muted");
    if (state === "required") {
      fidelityReviewBadge.textContent = "Review kræves";
      const safeBodyId = typeof bodyId === "string" && /^[A-Za-z0-9._-]{3,160}$/.test(bodyId);
      if (safeBodyId) {
        fidelityReviewNext.textContent = "Kør den canonicale wrapper fra den rene BodyRig operator-checkout efter den fysiske multiview + face-closeup review. Wrapperen beviser Windows, PowerShell 7+ og clean Git authority igen ved execution.";
        fidelityReviewCommand.textContent = `& ".\\record-high-fidelity-human-review.ps1" -BodyId "${bodyId}" -ConfirmQualityChecklist -QualityNote "<din fysiske high-fidelity review>"`;
        fidelityReviewCommand.classList.remove("hidden");
      } else {
        fidelityReviewNext.textContent = "Review-kommando tilbageholdt: body-id er ikke canonical.";
      }
    } else if (state === "blocked") {
      fidelityReviewBadge.textContent = "Review blokeret";
      fidelityReviewNext.textContent = "High-fidelity component gates skal være komplette, før et human review kan få authority.";
    } else {
      fidelityReviewBadge.textContent = "Review mangler";
    }
    fidelityReviewSummary.textContent = value.reason || "High-fidelity human review authority er ikke tilgængelig.";
  }

  function renderFidelity(fidelity, bodyId) {
    const { fidelitySummary, fidelityBadge, fidelityComponents, faceSummary, faceComponents } = nodes();
    if (!fidelitySummary || !fidelityBadge || !fidelityComponents || !faceSummary || !faceComponents) return;
    if (!fidelity || typeof fidelity !== "object" || fidelity.state === "unavailable") {
      fidelityBadge.textContent = "Evidence mangler";
      fidelityBadge.classList.add("muted");
      fidelitySummary.textContent = fidelity?.reason || "High-fidelity package-evidence kunne ikke revalideres.";
      faceSummary.textContent = "Nested face-secondary authority er ikke tilgængelig.";
      renderComponentSet(fidelityComponents, {}, FIDELITY_LABELS);
      renderComponentSet(faceComponents, {}, FACE_LABELS);
      renderHumanFidelityReview(fidelity?.human_review, bodyId);
      return;
    }

    const ready = fidelity.high_fidelity_ready === true;
    fidelityBadge.textContent = ready ? "HF-komponenter komplette" : "HF blokeret";
    fidelityBadge.classList.toggle("muted", !ready);
    const blockers = Array.isArray(fidelity.blockers) ? fidelity.blockers : [];
    fidelitySummary.textContent = ready
      ? "Alle krævede high-fidelity component receipts er komplette; det eksplicitte human review verificeres separat nedenfor."
      : `Blockers: ${blockers.length ? blockers.map((key) => FIDELITY_LABELS[key] || key).join(", ") : "ukendt fidelity-blocker"}.`;
    renderComponentSet(fidelityComponents, fidelity.components, FIDELITY_LABELS);

    const face = fidelity.face_secondary && typeof fidelity.face_secondary === "object" ? fidelity.face_secondary : {};
    const faceBlockers = Array.isArray(face.blockers) ? face.blockers : [];
    const semantic = face.semantic_vertex_map_authority || "unavailable";
    faceSummary.textContent = face.ready === true
      ? `Ansigtsdetaljer komplette · semantic vertex-map authority: ${semantic}.`
      : `Ansigtsdetaljer blokeret: ${faceBlockers.length ? faceBlockers.map((key) => FACE_LABELS[key] || key).join(", ") : "ukendt"} · semantic vertex-map authority: ${semantic}.`;
    renderComponentSet(faceComponents, face.components, FACE_LABELS);
    renderHumanFidelityReview(fidelity.human_review, bodyId);
  }

  function reset(message) {
    const { summary, badge, next, command } = nodes();
    if (summary) summary.textContent = message;
    if (badge) {
      badge.textContent = "Production låst";
      badge.classList.add("muted");
    }
    if (next) next.textContent = "";
    if (command) {
      command.textContent = "";
      command.classList.add("hidden");
    }
    renderStages({ gate_a: "unknown", windows: "unknown", quest: "unknown", release: "unknown" });
    renderFidelity(null, "");
  }

  async function apiJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
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

  function render(value) {
    const { summary, badge, next, command } = nodes();
    if (!summary || !badge || !next || !command) return;
    renderStages(value.stages);
    renderFidelity(value.fidelity, value.body_id);
    const physicalProduction = value.production_activation === true && value.state === "complete" && value.gate === "release";
    const fidelityReady = value.fidelity?.high_fidelity_ready === true;
    const fidelityReviewReady = value.fidelity?.human_review?.passed === true;
    const production = value.production_ready === true;
    const operator = value.operator_checkout && typeof value.operator_checkout === "object" ? value.operator_checkout : {};
    badge.textContent = production ? "Production klar" : "Production låst";
    badge.classList.toggle("muted", !production);
    const gate = GATE_LABELS[value.gate] || value.gate || "Ukendt gate";
    summary.textContent = `${value.body_revision || "?"} · ${gate} · ${value.message || "Ingen statusbesked"}`;
    if (value.state === "unavailable") {
      next.textContent = "Denne body har ingen verificerbar UI physical-build acceptance chain. Ingen fysisk release-status antages.";
    } else if (production) {
      next.textContent = "High-fidelity component gate, eksplicit high-fidelity human review og fysisk final release er alle revalideret som PASS for denne eksakte body revision.";
    } else if (physicalProduction && fidelityReady && !fidelityReviewReady) {
      next.textContent = "Fysisk final release og high-fidelity komponenter er PASS, men production er stadig låst indtil det eksplicitte high-fidelity human review er registreret for den eksakte package/component-state.";
    } else if (physicalProduction) {
      next.textContent = "Fysisk final release er PASS, men production er stadig låst af high-fidelity component evidence.";
    } else if (value.state === "blocked") {
      next.textContent = `Fysisk acceptance er blokeret ved ${gate}. Ret evidence/contract-driften før næste trin.`;
    } else if (operator.required === true && operator.ready !== true) {
      next.textContent = `Operator checkout blokerer næste kommando: ${operator.reason || "checkout-authority kunne ikke bevises"}.`;
    } else {
      next.textContent = `Næste authority: ${gate}. Person Studio kan kun vise status; den kan ikke selv attestere fysisk kvalitet.`;
    }
    if (typeof value.next_command === "string" && value.next_command.trim()) {
      command.textContent = value.next_command;
      command.classList.remove("hidden");
    } else {
      command.textContent = "";
      command.classList.add("hidden");
    }
  }

  async function refresh(force = false) {
    ensureCard();
    const personId = currentPersonId();
    const revision = currentBodyRevision();
    const key = `${personId}|${revision}`;
    if (!force && key === lastKey) return;
    lastKey = key;
    const serial = ++requestSerial;
    if (!personId) return reset("Ingen person valgt.");
    if (!revision) return reset("Ingen body-revision endnu.");

    const { summary, badge } = nodes();
    if (summary) summary.textContent = `${revision} · revaliderer fysisk acceptance + high-fidelity evidence…`;
    if (badge) {
      badge.textContent = "Kontrollerer";
      badge.classList.add("muted");
    }
    try {
      const value = await apiJson(`/api/v1/people/${encodeURIComponent(personId)}/body/release-status?revision=${encodeURIComponent(revision)}`);
      if (serial !== requestSerial || currentPersonId() !== personId || currentBodyRevision() !== revision) return;
      render(value);
    } catch (error) {
      if (serial !== requestSerial) return;
      reset(`Fail-closed: release/fidelity evidence kunne ikke valideres for ${revision}: ${error.message}`);
    }
  }

  for (const id of ["personId", "bodyRevisionLabel"]) {
    const node = document.getElementById(id);
    if (node) {
      new MutationObserver(() => { void refresh(); }).observe(node, {
        childList: true,
        characterData: true,
        subtree: true,
      });
    }
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) void refresh(true);
  });
  ensureCard();
  void refresh(true);
})();
