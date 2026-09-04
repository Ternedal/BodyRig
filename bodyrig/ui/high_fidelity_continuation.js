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

  function shortSha(value) {
    const text = String(value || "");
    return text ? `${text.slice(0, 16)}…` : "—";
  }

  async function apiJson(url) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
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
    n.production.textContent = "High-fidelity component status og production authority er separate gates.";
  }

  function stateLabel(state) {
    return ({ pass: "PASS", required: "KRÆVET", blocked: "BLOKERET", invalid: "UGYLDIG" })[state] || String(state || "UKENDT").toUpperCase();
  }

  function render(status) {
    const n = nodes();
    if (!n.summary) return;
    const complete = status.high_fidelity_complete === true;
    n.badge.textContent = complete ? "HF COMPLETE" : (status.state === "blocked" ? "Blokeret" : "I gang");
    n.badge.classList.toggle("muted", !complete);
    n.summary.textContent = complete
      ? "Alle high-fidelity component gates er komplette på den eksakte auditerede package."
      : `Næste gate: ${status.next_gate?.gate || "ukendt"}`;

    const packagePath = String(status.current_package_path || "—");
    n.packageNode.textContent = `Package authority: ${packagePath}\nSHA-256: ${status.current_package_sha256 || "—"}`;

    const componentLines = Object.entries(status.components || {}).map(([name, value]) => `${name}: ${value}`);
    n.components.textContent = componentLines.length ? componentLines.join("\n") : "Component authority bliver vist, når en promoted package findes.";

    n.gates.replaceChildren();
    for (const gate of Array.isArray(status.gates) ? status.gates : []) {
      const row = document.createElement("div");
      row.className = "revision-item";
      const reason = String(gate.reason || "").trim();
      row.innerHTML = `
        <div class="revision-top">
          <div><div class="revision-id">${gate.label || gate.id}</div><div class="revision-meta">${reason || gate.id}</div></div>
          <span class="badge${gate.state === "pass" ? "" : " muted"}">${stateLabel(gate.state)}</span>
        </div>`;
      n.gates.appendChild(row);
    }

    n.next.replaceChildren();
    if (!complete && status.next_gate) {
      const title = document.createElement("div");
      title.className = "card-label";
      title.textContent = `Næste gate · ${status.next_gate.gate}`;
      n.next.appendChild(title);
      if (status.next_gate.command) {
        const command = document.createElement("pre");
        command.className = "proposal";
        command.textContent = status.next_gate.command;
        n.next.appendChild(command);
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
        n.next.appendChild(copy);
      }
      const note = document.createElement("p");
      note.className = "fine-print";
      note.textContent = status.next_gate.operator_input_required === true
        ? "Denne gate kræver eksplicit menneskelig/operator-input. BodyRig udfylder aldrig review eller iris-annotationer selv."
        : "Kommandoen er en software-gate; den giver ikke i sig selv fysisk eller production authority.";
      n.next.appendChild(note);
    }

    if (complete) {
      n.production.textContent = "HIGH-FIDELITY COMPONENTS COMPLETE · PRODUCTION LOCKED. Package-bound high-fidelity human review, real Windows acceptance, Quest acceptance og final release gate er stadig påkrævet. production_ready=false.";
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
    lastKey = key;
    const current = ++serial;

    if (!person || !revision) {
      reset("Vælg en body-revision for at se high-fidelity continuation.");
      timer = setTimeout(() => void refresh(true), 5000);
      return;
    }

    try {
      const preview = await apiJson(`/api/v1/people/${encodeURIComponent(person)}/body/high-fidelity-preview?revision=${encodeURIComponent(revision)}`);
      if (current !== serial || personId() !== person || bodyRevision() !== revision) return;
      if (!preview?.job_id) {
        reset("Ingen persisted high-fidelity preview-job for denne body revision.", "Preview mangler");
        return;
      }
      if (!FINAL_PREVIEW.has(preview.status)) {
        reset(`${preview.job_id} · ${preview.stage || preview.status || "kører"}`, "Preview kører");
        timer = setTimeout(() => void refresh(true), 2000);
        return;
      }
      const status = await apiJson(`/api/v1/high-fidelity-preview-jobs/${encodeURIComponent(preview.job_id)}/continuation-status`);
      if (current !== serial || personId() !== person || bodyRevision() !== revision) return;
      render(status);
      timer = setTimeout(() => void refresh(true), 5000);
    } catch (error) {
      if (current !== serial) return;
      if (error.status === 404) reset("Ingen high-fidelity continuation endnu.", "Ikke startet");
      else reset(`Continuation-status kunne ikke valideres: ${error.message}`, "Statusfejl");
      timer = setTimeout(() => void refresh(true), 5000);
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
