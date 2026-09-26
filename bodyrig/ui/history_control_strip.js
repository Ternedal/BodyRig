(() => {
  const $ = (id) => document.getElementById(id);

  function setChip(id, state, active) {
    const chip = $(id);
    if (!chip) return;
    const stateNode = chip.querySelector(".chip-state");
    if (stateNode) stateNode.textContent = state || "—";
    chip.classList.toggle("active", Boolean(active));
  }

  function integerDataset(host, key) {
    const value = Number(host?.dataset?.[key]);
    return Number.isInteger(value) && value >= 0 ? value : null;
  }

  function strictHistoryState() {
    const host = $("historyList");
    if (!host || host.dataset.historyLoaded !== "true") {
      return {
        loaded: false,
        integrityValid: false,
        revisionCount: 0,
        activeRevisionId: "",
        activeState: "unknown",
        activeComponentCount: 0,
      };
    }
    return {
      loaded: true,
      integrityValid: host.dataset.historyIntegrity === "valid",
      revisionCount: integerDataset(host, "historyRevisionCount") ?? 0,
      activeRevisionId: String(host.dataset.historyActiveRevision || "").trim(),
      activeState: String(host.dataset.historyActiveState || "unknown"),
      activeComponentCount: integerDataset(host, "historyActiveComponentCount") ?? 0,
    };
  }

  function refresh() {
    const state = strictHistoryState();
    const activeReady =
      state.integrityValid
      && state.activeState === "ready"
      && Boolean(state.activeRevisionId)
      && state.activeComponentCount === 3;

    setChip(
      "historyControlActive",
      activeReady
        ? state.activeRevisionId
        : (state.activeState === "none" ? "Ingen aktiv" : "Ugyldig binding"),
      activeReady
    );
    setChip(
      "historyControlRevisions",
      state.loaded && state.integrityValid
        ? (state.revisionCount ? `${state.revisionCount} revision(er)` : "Ingen historik")
        : "Historik ukendt",
      state.loaded && state.integrityValid && state.revisionCount > 0
    );
    setChip(
      "historyControlComponents",
      `${state.activeComponentCount}/3`,
      activeReady
    );

    const next = $("historyControlNext");
    if (!next) return;
    if (!state.loaded) {
      next.textContent = "Historik-authority afventer den valgte person.";
    } else if (!state.integrityValid) {
      next.textContent = "Historik-evidence er inkonsistent; ingen readiness antages.";
    } else if (state.activeState === "missing") {
      next.textContent = "Aktiv Person Revision findes ikke entydigt i personhistorikken.";
    } else if (state.activeState === "incomplete") {
      next.textContent = `Aktiv Person Revision har kun ${state.activeComponentCount}/3 entydige component bindings.`;
    } else if (state.activeState === "none") {
      next.textContent = state.revisionCount
        ? `${state.revisionCount} revision(er) registreret · ingen aktiv Person Revision.`
        : "Ingen revisioner registreret endnu.";
    } else if (activeReady) {
      next.textContent = `${state.revisionCount} revision(er) · aktiv revision ${state.activeRevisionId} · 3/3 bindings verificeret.`;
    } else {
      next.textContent = "Historik-readiness kunne ikke verificeres.";
    }
  }

  $("historyControlActive")?.addEventListener("click", () =>
    document.querySelector('.tab[data-tab="overview"]')?.click()
  );
  $("historyControlRevisions")?.addEventListener("click", () =>
    $("historyList")?.scrollIntoView({ behavior: "smooth", block: "start" })
  );
  $("historyControlComponents")?.addEventListener("click", () =>
    document.querySelector('.tab[data-tab="assemble"]')?.click()
  );

  const history = $("historyList");
  if (history) {
    new MutationObserver(refresh).observe(history, {
      childList: true,
      characterData: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        "data-history-loaded",
        "data-history-integrity",
        "data-history-revision-count",
        "data-history-active-revision",
        "data-history-active-state",
        "data-history-active-component-count",
      ],
    });
  }
  refresh();
})();
