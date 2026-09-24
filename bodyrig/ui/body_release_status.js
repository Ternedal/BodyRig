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
    "runtime-visual-authority": "Visuel runtime-authority (blokeret)",
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
      <div id="bodyReleaseControl" class="body-release-control hidden">
        <label id="bodyReleaseQuestLabel" class="hidden">Quest-headset
          <select id="bodyReleaseQuestSerial"><option value="">Henter tilsluttede Quest-headsets…</option></select>
        </label>
        <label id="bodyReleaseQualityLabel" class="hidden">Fysisk review-note
          <textarea id="bodyReleaseQualityNote" rows="3" placeholder="Beskriv konkret hvad du fysisk har verificeret."></textarea>
        </label>
        <button id="bodyReleaseAction" class="primary" type="button">Kør næste fysiske trin</button>
      </div>
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
      <div id="bodyFidelityReviewControl" class="body-release-control hidden">
        <label>High-fidelity review-note
          <textarea id="bodyFidelityReviewQualityNote" rows="3" placeholder="Beskriv den konkrete multiview/face-closeup kvalitet du har verificeret."></textarea>
        </label>
        <button id="bodyFidelityReviewAction" class="primary" type="button">Registrér high-fidelity review</button>
      </div>
      <pre id="bodyFidelityReviewCommand" class="proposal body-release-command hidden"></pre>
      <p class="fine-print">Statuslæsning er read-only. Muterende handlinger starter kun efter et eksplicit klik og går gennem canonical backend/PowerShell authority. Human reviews kræver en konkret review-note og kan ikke auto-godkendes. En aktiv Person Revision er ikke production authority; production kræver komplette high-fidelity components, eksplicit high-fidelity human review og fysisk Windows + Quest final release.</p>`;
    const gallery = document.getElementById("bodyReviewGalleryCard");
    if (gallery) gallery.insertAdjacentElement("afterend", card);
    else {
      const candidates = tab.querySelector(":scope > .card.space-top");
      if (candidates) candidates.insertAdjacentElement("beforebegin", card);
      else tab.appendChild(card);
    }
    document.getElementById("bodyReleaseAction")?.addEventListener("click", () => {
      void runReleaseAction("physical-next");
    });
    document.getElementById("bodyFidelityReviewAction")?.addEventListener("click", () => {
      void runReleaseAction("high-fidelity-review");
    });
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
      releaseControl: document.getElementById("bodyReleaseControl"),
      releaseQuestLabel: document.getElementById("bodyReleaseQuestLabel"),
      releaseQuestSerial: document.getElementById("bodyReleaseQuestSerial"),
      releaseQualityLabel: document.getElementById("bodyReleaseQualityLabel"),
      releaseQualityNote: document.getElementById("bodyReleaseQualityNote"),
      releaseAction: document.getElementById("bodyReleaseAction"),
      fidelityReviewControl: document.getElementById("bodyFidelityReviewControl"),
      fidelityReviewQualityNote: document.getElementById("bodyFidelityReviewQualityNote"),
      fidelityReviewAction: document.getElementById("bodyFidelityReviewAction"),
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

  function renderHumanFidelityReview(review, bodyId, fidelityReady = false) {
    const { fidelityReviewSummary, fidelityReviewBadge, fidelityReviewNext, fidelityReviewCommand, fidelityReviewControl, fidelityReviewQualityNote } = nodes();
    if (!fidelityReviewSummary || !fidelityReviewBadge || !fidelityReviewNext || !fidelityReviewCommand) return;
    fidelityReviewControl?.classList.add("hidden");
    if (fidelityReviewQualityNote) fidelityReviewQualityNote.value = "";
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
        if (fidelityReady) {
          fidelityReviewControl?.classList.remove("hidden");
          const action = document.getElementById("bodyFidelityReviewAction");
          if (action) {
            action.disabled = false;
            action.textContent = "Registrér high-fidelity review";
          }
        }
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
      renderHumanFidelityReview(fidelity?.human_review, bodyId, false);
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
    renderHumanFidelityReview(fidelity.human_review, bodyId, ready);
  }

  function reset(message) {
    const { summary, badge, next, command, releaseControl, fidelityReviewControl } = nodes();
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
    releaseControl?.classList.add("hidden");
    fidelityReviewControl?.classList.add("hidden");
    renderStages({ gate_a: "unknown", windows: "unknown", quest: "unknown", release: "unknown" });
    renderFidelity(null, "");
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
      cache: "no-store",
    });
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
      next.textContent = `Næste authority: ${gate}. Person Studio kan starte den canonicale handling; fysisk kvalitet kan kun attesteres efter din eksplicitte review-note.`;
    }
    if (typeof value.next_command === "string" && value.next_command.trim()) {
      command.textContent = value.next_command;
      command.classList.remove("hidden");
    } else {
      command.textContent = "";
      command.classList.add("hidden");
    }

    const { releaseControl, releaseQuestLabel, releaseQualityLabel, releaseAction } = nodes();
    const physicalActionReady = typeof value.next_command === "string" && value.next_command.trim() && operator.ready === true;
    releaseControl?.classList.toggle("hidden", !physicalActionReady);
    releaseQuestLabel?.classList.toggle("hidden", value.gate !== "quest-probe");
    const needsPhysicalNote = ["windows-attestation", "quest-attestation"].includes(value.gate);
    releaseQualityLabel?.classList.toggle("hidden", !needsPhysicalNote);
    if (releaseAction) {
      releaseAction.disabled = !physicalActionReady;
      releaseAction.textContent =
        value.gate === "windows-probe" ? "Kør Windows probe" :
        value.gate === "windows-attestation" ? "Registrér Windows review" :
        value.gate === "quest-probe" ? "Kør Quest probe" :
        value.gate === "quest-attestation" ? "Registrér Quest review" :
        value.gate === "release" ? "Kør final release" :
        "Kør næste fysiske trin";
    }
  }

  async function runReleaseAction(action) {
    const personId = currentPersonId();
    const revision = currentBodyRevision();
    if (!personId || !revision) return;
    const {
      releaseAction,
      releaseQualityNote,
      releaseQuestSerial,
      fidelityReviewAction,
      fidelityReviewQualityNote,
      next,
      fidelityReviewNext,
    } = nodes();
    const isPhysical = action === "physical-next";
    const button = isPhysical ? releaseAction : fidelityReviewAction;
    const noteNode = isPhysical ? releaseQualityNote : fidelityReviewQualityNote;
    if (button) {
      button.disabled = true;
      button.textContent = "Starter…";
    }
    try {
      const result = await apiJson(
        `/api/v1/people/${encodeURIComponent(personId)}/body/release-control/action?revision=${encodeURIComponent(revision)}`,
        {
          method: "POST",
          body: JSON.stringify({
            action,
            quality_note: noteNode?.value || "",
            quest_serial: isPhysical ? (releaseQuestSerial?.value || "") : "",
          }),
        }
      );
      const target = isPhysical ? next : fidelityReviewNext;
      if (target) {
        target.textContent = `Canonical operator startet · PID ${result.launch?.pid || "?"}. Status revalideres automatisk.`;
      }
      setTimeout(() => void refresh(true), 2500);
    } catch (error) {
      const target = isPhysical ? next : fidelityReviewNext;
      if (target) target.textContent = `Handling afvist: ${error.message}`;
      if (button) button.disabled = false;
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
      if (value.gate === "quest-probe") {
        try {
          const readiness = await apiJson("/api/v1/operator/system-readiness");
          if (serial !== requestSerial || currentPersonId() !== personId || currentBodyRevision() !== revision) return;
          const select = nodes().releaseQuestSerial;
          if (select) {
            select.replaceChildren();
            const devices = Array.isArray(readiness.quest?.devices)
              ? readiness.quest.devices.filter((item) => item?.quest_class === true)
              : [];
            if (!devices.length) {
              const option = document.createElement("option");
              option.value = "";
              option.textContent = "Ingen online Quest/Oculus";
              select.appendChild(option);
              select.disabled = true;
              nodes().releaseAction.disabled = true;
            } else {
              for (const device of devices) {
                const option = document.createElement("option");
                option.value = device.serial || "";
                option.textContent = `${device.model || "Quest"} · ${device.serial || "ukendt serial"}`;
                select.appendChild(option);
              }
              select.disabled = false;
              if (devices.length === 1) select.selectedIndex = 0;
            }
          }
        } catch (error) {
          const select = nodes().releaseQuestSerial;
          if (select) {
            select.replaceChildren();
            const option = document.createElement("option");
            option.value = "";
            option.textContent = `Quest-readiness fejlede: ${error.message}`;
            select.appendChild(option);
            select.disabled = true;
            nodes().releaseAction.disabled = true;
          }
        }
      }
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
