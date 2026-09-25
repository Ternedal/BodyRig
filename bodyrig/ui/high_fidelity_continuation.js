(() => {
  const FINAL_PREVIEW = new Set(["succeeded", "failed", "interrupted"]);
  let timer = null;
  let serial = 0;
  let lastKey = "";

  const $ = (id) => document.getElementById(id);

  function personId() {
    return ($("personId")?.textContent || "").trim();
  }

  function bodyRevision() {
    const value = ($("bodyRevisionLabel")?.textContent || "").trim();
    return value.startsWith("body-r") ? value : "";
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

  function ensureCard() {
    let card = $("highFidelityContinuationCard");
    if (card) return card;
    const tab = $("tab-body");
    if (!tab) return null;
    card = document.createElement("article");
    card.id = "highFidelityContinuationCard";
    card.className = "card space-top";
    card.innerHTML = `
      <div class="card-row">
        <div>
          <div class="card-label">High-fidelity continuation</div>
          <div id="highFidelityContinuationSummary" class="muted-text">Ingen persisted high-fidelity continuation valgt.</div>
        </div>
        <span id="highFidelityContinuationBadge" class="badge muted">Ikke startet</span>
      </div>
      <div id="highFidelityContinuationPackage" class="proposal muted-text">Package authority: —</div>
      <div id="highFidelityContinuationComponents" class="proposal muted-text space-top"></div>
      <div id="highFidelityContinuationGates" class="revision-list space-top"></div>
      <div id="highFidelityContinuationNext" class="space-top"></div>
      <div id="highFidelityContinuationProduction" class="fine-print space-top"></div>`;
    const anchor = $("highFidelityPreviewCard") || $("bodyReviewGalleryCard");
    if (anchor) anchor.insertAdjacentElement("afterend", card);
    else tab.appendChild(card);
    return card;
  }

  function nodes() {
    ensureCard();
    return {
      summary: $("highFidelityContinuationSummary"),
      badge: $("highFidelityContinuationBadge"),
      packageNode: $("highFidelityContinuationPackage"),
      components: $("highFidelityContinuationComponents"),
      gates: $("highFidelityContinuationGates"),
      next: $("highFidelityContinuationNext"),
      production: $("highFidelityContinuationProduction"),
    };
  }

  function reset(message, badgeText = "Ikke startet") {
    const n = nodes();
    if (!n.summary) return;
    n.summary.textContent = message;
    n.badge.textContent = badgeText;
    n.badge.classList.add("muted");
    n.packageNode.textContent = "Package authority: —";
    n.components.textContent = "";
    n.gates.replaceChildren();
    n.next.replaceChildren();
    n.production.textContent = "High-fidelity package, human review, fysisk acceptance og production authority er separate gates.";
  }

  function stateLabel(state) {
    return ({ pass: "PASS", required: "KRÆVET", blocked: "BLOKERET", invalid: "UGYLDIG" })[state] || String(state || "UKENDT").toUpperCase();
  }

  const QUALITY_GATES = new Set([
    "component_review",
    "hair_deformation_review",
    "iris_review",
    "face_secondary_review",
    "hfn_human_review",
  ]);

  function field(labelText, name, type = "text", placeholder = "") {
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement(type === "textarea" ? "textarea" : "input");
    if (type !== "textarea") input.type = type;
    input.name = name;
    input.placeholder = placeholder;
    label.appendChild(input);
    return { label, input };
  }

  function actionInputs(action, host) {
    const gate = String(action?.gate || "");
    const inputs = {};
    if (QUALITY_GATES.has(gate)) {
      const value = field("Quality note", "quality_note", "textarea", "Beskriv konkret hvad du har verificeret.");
      host.appendChild(value.label);
      inputs.quality_note = value.input;
      return inputs;
    }
    if (gate === "iris_candidate") {
      for (const [labelText, name] of [
        ["Left iris cx", "left_cx"], ["Left iris cy", "left_cy"], ["Left iris radius", "left_radius"],
        ["Right iris cx", "right_cx"], ["Right iris cy", "right_cy"], ["Right iris radius", "right_radius"],
      ]) {
        const value = field(labelText, name, "number");
        host.appendChild(value.label);
        inputs[name] = value.input;
      }
      return inputs;
    }
    if (gate === "hfn_detail_candidate" && action?.operator_input_required === true) {
      const capture = field("HFN capture id", "capture_id", "text", "Exact source-grounded capture id");
      const uv = field("HFN UV evidence", "uv_evidence_path", "text", "Exact UV evidence path");
      host.append(capture.label, uv.label);
      inputs.capture_id = capture.input;
      inputs.uv_evidence_path = uv.input;
      return inputs;
    }
    if (gate === "fine_identity_application") {
      const sweep = field("Fine-identity sweep root", "sweep_root", "text", "Exact private sweep root");
      const adapter = field("Adapter config", "adapter_config", "text", "Pinned local adapter config");
      host.append(sweep.label, adapter.label);
      inputs.sweep_root = sweep.input;
      inputs.adapter_config = adapter.input;
      return inputs;
    }
    return inputs;
  }

  async function runNextAction(previewJobId, action, inputs, button, noteNode) {
    if (!previewJobId || !action?.gate) return;
    const payload = {};
    for (const [name, input] of Object.entries(inputs || {})) payload[name] = input?.value ?? "";
    button.disabled = true;
    const original = button.textContent;
    button.textContent = "Starter…";
    try {
      const result = await apiJson(
        `/api/v1/high-fidelity-preview-jobs/${encodeURIComponent(previewJobId)}/continuation-action`,
        {
          method: "POST",
          body: JSON.stringify({ action: "advance", inputs: payload }),
        }
      );
      if (noteNode) noteNode.textContent = `Canonical gate startet · PID ${result.launch?.pid || "?"}. Status revalideres automatisk.`;
      setTimeout(() => void refresh(true), 2200);
    } catch (error) {
      if (noteNode) noteNode.textContent = `Handling afvist: ${error.message}`;
      button.disabled = false;
      button.textContent = original;
    }
  }

  function render(status) {
    const n = nodes();
    if (!n.summary) return;
    const packageComplete = status.component_package_complete === true || status.high_fidelity_complete === true;
    const humanReviewComplete = status.high_fidelity_human_review_complete === true;
    const softwareReady = status.software_ready_for_physical_acceptance === true;
    const productionReady = status.production_ready === true && status.production_activation === true;
    const blocked = status.state === "blocked";

    if (productionReady) {
      n.badge.textContent = "PRODUCTION READY";
      n.badge.classList.remove("muted");
      n.summary.textContent = "Canonical final release er PASS for den eksakte promoted package efter high-fidelity review, Windows og Quest acceptance.";
    } else if (blocked) {
      n.badge.textContent = "Blokeret";
      n.badge.classList.add("muted");
      const failure = (status.gates || []).find((gate) => gate.state === "invalid" || gate.state === "blocked");
      n.summary.textContent = failure?.reason || "Det gemte testmateriale kunne ikke valideres.";
    } else if (softwareReady) {
      n.badge.textContent = "SOFTWARE READY";
      n.badge.classList.remove("muted");
      n.summary.textContent = `High-fidelity package + package-bound human review er komplette. Næste authority: ${status.next_gate?.gate || "physical acceptance"}.`;
    } else if (packageComplete) {
      n.badge.textContent = "HF PACKAGE COMPLETE";
      n.badge.classList.add("muted");
      n.summary.textContent = `Component-package er komplet; næste gate: ${status.next_gate?.gate || "package-bound human review"}.`;
    } else {
      n.badge.textContent = status.state === "blocked" ? "Blokeret" : "I gang";
      n.badge.classList.add("muted");
      n.summary.textContent = `Næste gate: ${status.next_gate?.gate || "ukendt"}`;
    }

    const packagePath = String(status.current_package_path || "—");
    n.packageNode.textContent = `Package authority: ${packagePath}\nSHA-256: ${status.current_package_sha256 || "—"}`;

    const componentLines = Object.entries(status.components || {}).map(([name, value]) => `${name}: ${value}`);
    n.components.textContent = componentLines.length ? componentLines.join("\n") : "Component authority bliver vist, når en promoted package findes.";

    n.gates.replaceChildren();
    for (const gate of Array.isArray(status.gates) ? status.gates : []) {
      const row = document.createElement("div");
      row.className = "revision-item";
      const reason = String(gate.reason || "").trim();
      const top = document.createElement("div");
      top.className = "revision-top";
      const details = document.createElement("div");
      const label = document.createElement("div");
      label.className = "revision-id";
      label.textContent = gate.label || gate.id;
      const description = document.createElement("div");
      description.className = "revision-meta";
      description.textContent = reason || gate.id;
      const badge = document.createElement("span");
      badge.className = `badge${gate.state === "pass" ? "" : " muted"}`;
      badge.textContent = stateLabel(gate.state);
      details.append(label, description);
      top.append(details, badge);
      row.appendChild(top);
      n.gates.appendChild(row);
    }

    n.next.replaceChildren();
    if (status.next_gate && !blocked && !productionReady) {
      const title = document.createElement("div");
      title.className = "card-label";
      title.textContent = `Næste gate · ${status.next_gate.gate}`;
      n.next.appendChild(title);
      const note = document.createElement("p");
      note.className = "fine-print";
      note.textContent = status.next_gate.reason || (
        status.next_gate.operator_input_required === true
          ? "Denne gate kræver eksplicit menneskelig/operator-input. BodyRig udfylder aldrig review eller iris-annotationer selv."
          : "Kommandoen er en software-gate; den giver ikke i sig selv fysisk eller production authority."
      );
      if (status.next_gate.command) {
        const command = document.createElement("pre");
        command.className = "proposal";
        command.textContent = status.next_gate.command;
        n.next.appendChild(command);

        const controls = document.createElement("div");
        controls.className = "high-fidelity-continuation-controls";
        const inputs = actionInputs(status.next_gate, controls);
        const knownTypedInput =
          status.next_gate.operator_input_required !== true ||
          QUALITY_GATES.has(status.next_gate.gate) ||
          status.next_gate.gate === "iris_candidate" ||
          status.next_gate.gate === "hfn_detail_candidate" ||
          status.next_gate.gate === "fine_identity_application";
        if (knownTypedInput) {
          const run = document.createElement("button");
          run.type = "button";
          run.className = "primary";
          run.textContent = "Kør næste canonicale gate";
          run.addEventListener("click", () => {
            void runNextAction(status.preview_job_id, status.next_gate, inputs, run, note);
          });
          controls.appendChild(run);
        }
        const copy = document.createElement("button");
        copy.type = "button";
        copy.className = "secondary";
        copy.textContent = "Kopiér operator-kommando";
        copy.addEventListener("click", async () => {
          try {
            await navigator.clipboard.writeText(status.next_gate.command);
            copy.textContent = "Kopieret";
            setTimeout(() => { copy.textContent = "Kopiér operator-kommando"; }, 1400);
          } catch {
            copy.textContent = "Kunne ikke kopiere";
          }
        });
        controls.appendChild(copy);
        n.next.appendChild(controls);
      }
      n.next.appendChild(note);
    }

    if (productionReady) {
      n.production.textContent = "PRODUCTION READY · CANONICAL FINAL RELEASE PASS. Den eksakte promoted package er bundet til high-fidelity human review, Windows- og Quest-acceptance samt final release authority.";
    } else if (blocked) {
      n.production.textContent = "Forløbet er blokeret, indtil det gemte testmateriale kan valideres. Produktionsaktivering er fortsat låst.";
    } else if (softwareReady) {
      n.production.textContent = `SOFTWARE READY FOR PHYSICAL ACCEPTANCE · PRODUCTION LOCKED. Næste gate er ${status.next_gate?.gate || "physical acceptance"}; production_ready=false indtil canonical final release PASS.`;
    } else if (packageComplete && !humanReviewComplete) {
      n.production.textContent = "HIGH-FIDELITY PACKAGE COMPLETE · HUMAN REVIEW REQUIRED · PRODUCTION LOCKED. Component completion alene er ikke fysisk acceptance. production_ready=false.";
    } else {
      n.production.textContent = "PRODUCTION LOCKED. production_ready=false gennem hele continuation-flowet; CI og component promotion kan ikke erstatte human/Windows/Quest/final release authority.";
    }
  }

  async function refresh(force = false) {
    clearTimeout(timer);
    const person = personId();
    const revision = bodyRevision();
    const key = `${person}|${revision}`;
    if (!force && key === lastKey) {
      timer = setTimeout(() => void refresh(true), 5000);
      return;
    }
    const selectionChanged = key !== lastKey;
    lastKey = key;
    const current = ++serial;

    if (!person || !revision) {
      reset("Vælg en body-revision for at se high-fidelity continuation.");
      timer = setTimeout(() => void refresh(true), 5000);
      return;
    }

    if (selectionChanged) reset("Henter status for den valgte body-revision.", "Indlæser");
    let nextPollMs = 5000;
    try {
      const preview = await apiJson(`/api/v1/people/${encodeURIComponent(person)}/body/high-fidelity-preview?revision=${encodeURIComponent(revision)}`);
      if (current !== serial || personId() !== person || bodyRevision() !== revision) return;
      if (!preview?.job_id) {
        reset("Ingen persisted high-fidelity preview-job for denne body revision.", "Preview mangler");
        return;
      }
      if (!FINAL_PREVIEW.has(preview.status)) {
        reset(`${preview.job_id} · ${preview.stage || preview.status || "kører"}`, "Preview kører");
        nextPollMs = 2000;
        return;
      }
      const status = await apiJson(`/api/v1/high-fidelity-preview-jobs/${encodeURIComponent(preview.job_id)}/continuation-status`);
      if (current !== serial || personId() !== person || bodyRevision() !== revision) return;
      render(status);
    } catch (error) {
      if (current !== serial) return;
      if (error.status === 404) reset("Ingen high-fidelity continuation endnu.", "Ikke startet");
      else reset(`Continuation-status kunne ikke valideres: ${error.message}`, "Statusfejl");
    } finally {
      if (current === serial) timer = setTimeout(() => void refresh(true), nextPollMs);
    }
  }

  for (const id of ["personId", "bodyRevisionLabel"]) {
    const node = $(id);
    if (node) new MutationObserver(() => { lastKey = ""; void refresh(true); }).observe(node, { childList: true, characterData: true, subtree: true });
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) void refresh(true); });
  ensureCard();
  void refresh(true);
})();
