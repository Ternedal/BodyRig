(() => {
  const $ = (id) => document.getElementById(id);
  const ACTIVE_STATES = new Set(["unknown", "unbound", "bound"]);
  const LAB_STATES = new Set(["checking", "ready", "blocked"]);
  const LAB_MODES = new Set(["guided", "suite"]);

  function setChip(id, state, active) {
    const chip = $(id);
    if (!chip) return;
    const stateNode = chip.querySelector(".chip-state");
    if (stateNode) stateNode.textContent = state || "—";
    chip.classList.toggle("active", Boolean(active));
  }

  function nonNegativeInteger(value) {
    const text = String(value ?? "").trim();
    if (!/^(0|[1-9]\d*)$/.test(text)) return null;
    const parsed = Number(text);
    return Number.isSafeInteger(parsed) ? parsed : null;
  }

  function structuredState() {
    const root = $("personalityControlStrip");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const personId = String(root.dataset.personId || "").trim();
    const candidateCount = nonNegativeInteger(root.dataset.candidateCount);
    const active = String(root.dataset.activeState || "");
    const activeLabel = String(root.dataset.activeLabel || "").trim();
    const lab = String(root.dataset.labState || "");
    const labMode = String(root.dataset.labMode || "");
    const labLabel = String(root.dataset.labLabel || "").trim();
    const labPersonId = String(root.dataset.labPersonId || "").trim();

    if (candidateCount === null || !ACTIVE_STATES.has(active) || !LAB_STATES.has(lab)) return null;
    if (active === "bound" && !activeLabel) return null;
    if (lab === "ready") {
      if (!personId || labPersonId !== personId || !LAB_MODES.has(labMode) || !labLabel) return null;
    }
    if (lab === "blocked" && labPersonId && personId && labPersonId !== personId) return null;

    return {
      personId,
      candidateCount,
      active,
      activeLabel,
      lab,
      labMode,
      labLabel,
    };
  }

  function refresh() {
    const state = structuredState();
    const next = $("personalityControlNext");

    if (!state) {
      setChip("personalityControlDraft", "Ukendt", false);
      setChip("personalityControlLab", "Ukendt", false);
      setChip("personalityControlActive", "Ukendt", false);
      if (next) next.textContent = "Afventer struktureret Personality-state.";
      return;
    }

    setChip(
      "personalityControlDraft",
      state.candidateCount ? `${state.candidateCount} kandidat(er)` : "Ingen kandidater",
      state.candidateCount > 0
    );
    setChip(
      "personalityControlLab",
      state.lab === "ready"
        ? (state.labMode === "suite" ? "6-scenarie audition" : "Guided Personality")
        : (state.lab === "blocked" ? "Blokeret" : "Kontrollerer…"),
      state.lab === "ready"
    );
    setChip(
      "personalityControlActive",
      state.active === "bound" ? state.activeLabel : (state.active === "unknown" ? "Ukendt" : "Ingen aktiv"),
      state.active === "bound"
    );

    if (!next) return;
    if (!state.personId) next.textContent = "Vælg en person.";
    else if (state.lab !== "ready") next.textContent = "Personality Lab er ikke klar for den valgte person.";
    else if (state.candidateCount === 0) next.textContent = "Opret en personality-kandidat eller brug Guided Personality.";
    else if (state.active !== "bound") next.textContent = `${state.candidateCount} kandidat(er) klar · kør audition og fortsæt til Saml person.`;
    else next.textContent = `Aktiv personality bundet · ${state.candidateCount} kandidat(er) tilgængelige.`;
  }

  $("personalityControlDraft")?.addEventListener("click", () => {
    $("personalityRevisions")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("personalityControlLab")?.addEventListener("click", () => {
    document.querySelector(".personality-workspace-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("personalityControlActive")?.addEventListener("click", () => {
    document.querySelector('.tab[data-tab="assemble"]')?.click();
  });

  const root = $("personalityControlStrip");
  if (root) {
    new MutationObserver(refresh).observe(root, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-person-id",
        "data-candidate-count",
        "data-active-state",
        "data-active-label",
        "data-lab-state",
        "data-lab-mode",
        "data-lab-label",
        "data-lab-person-id",
      ],
    });
  }

  refresh();
})();
