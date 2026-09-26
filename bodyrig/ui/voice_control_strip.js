(() => {
  const $ = (id) => document.getElementById(id);
  const ALLOWED = {
    library: new Set(["ready", "blocked", "checking"]),
    selected: new Set(["ready", "none"]),
    active: new Set(["bound", "unbound"]),
  };

  function setChip(id, state, active) {
    const chip = $(id);
    if (!chip) return;
    const stateNode = chip.querySelector(".chip-state");
    if (stateNode) stateNode.textContent = state || "Ukendt";
    chip.classList.toggle("active", Boolean(active));
  }

  function integerDataset(root, key) {
    const raw = String(root?.dataset?.[key] || "").trim();
    if (!/^\d+$/.test(raw)) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) ? value : null;
  }

  function structuredState() {
    const root = $("voiceControlStrip");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const library = String(root.dataset.libraryState || "").trim();
    const selected = String(root.dataset.selectedState || "").trim();
    const active = String(root.dataset.activeState || "").trim();
    const libraryLabel = String(root.dataset.libraryLabel || "").trim();
    const selectedLabel = String(root.dataset.selectedLabel || "").trim();
    const activeLabel = String(root.dataset.activeLabel || "").trim();
    const candidateCount = integerDataset(root, "candidateCount");

    if (
      !ALLOWED.library.has(library)
      || !ALLOWED.selected.has(selected)
      || !ALLOWED.active.has(active)
      || candidateCount === null
      || libraryLabel.length > 240
      || selectedLabel.length > 240
      || activeLabel.length > 240
    ) {
      return null;
    }

    return { library, selected, active, libraryLabel, selectedLabel, activeLabel, candidateCount };
  }

  function refresh() {
    const state = structuredState();
    if (!state) {
      setChip("voiceControlLibrary", "Ukendt", false);
      setChip("voiceControlSelected", "Ukendt", false);
      setChip("voiceControlActive", "Ukendt", false);
      if ($("voiceControlNext")) {
        $("voiceControlNext").textContent = "Afventer struktureret VoiceRig-status…";
      }
      return;
    }

    setChip(
      "voiceControlLibrary",
      state.libraryLabel || "VoiceRig status ukendt",
      state.library === "ready"
    );
    setChip(
      "voiceControlSelected",
      state.selected === "ready" ? (state.selectedLabel || "Valgt") : "Ingen valgt",
      state.selected === "ready"
    );
    setChip(
      "voiceControlActive",
      state.active === "bound" ? (state.activeLabel || "Aktiv binding") : "Ingen aktiv",
      state.active === "bound"
    );

    const next = $("voiceControlNext");
    if (!next) return;
    if (state.selected !== "ready" && state.candidateCount === 0) {
      next.textContent = "Vælg en VoiceRig-stemme og gem den som kandidat.";
    } else if (state.selected === "ready" && state.candidateCount === 0) {
      next.textContent = "Gem den valgte VoiceRig-stemme som kandidat.";
    } else if (state.candidateCount > 0 && state.active !== "bound") {
      next.textContent = `${state.candidateCount} voice-kandidat(er) klar · fortsæt til Saml person.`;
    } else {
      next.textContent = `Aktiv stemme bundet · ${state.candidateCount} kandidat(er) tilgængelige.`;
    }
  }

  $("voiceControlLibrary")?.addEventListener("click", () => {
    $("voiceLibrarySelect")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("voiceControlSelected")?.addEventListener("click", () => {
    $("voiceLibrarySelect")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("voiceControlActive")?.addEventListener("click", () => {
    document.querySelector('.tab[data-tab="assemble"]')?.click();
  });

  const root = $("voiceControlStrip");
  if (root) {
    new MutationObserver(refresh).observe(root, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-library-state",
        "data-library-label",
        "data-selected-state",
        "data-selected-label",
        "data-candidate-count",
        "data-active-state",
        "data-active-label",
      ],
    });
  }

  refresh();
})();