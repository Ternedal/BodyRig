(() => {
  const $ = (id) => document.getElementById(id);
  const ALLOWED = {
    draft: new Set(["ready", "empty"]),
    lab: new Set(["ready", "unknown"]),
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
    const root = $("personalityControlStrip");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const draft = String(root.dataset.draftState || "").trim();
    const lab = String(root.dataset.labState || "").trim();
    const active = String(root.dataset.activeState || "").trim();
    const count = integerDataset(root, "draftCount");
    const labLabel = String(root.dataset.labLabel || "").trim();
    const activeLabel = String(root.dataset.activeLabel || "").trim();

    if (
      !ALLOWED.draft.has(draft)
      || !ALLOWED.lab.has(lab)
      || !ALLOWED.active.has(active)
      || count === null
      || labLabel.length > 240
      || activeLabel.length > 240
    ) {
      return null;
    }

    return { draft, lab, active, count, labLabel, activeLabel };
  }

  function refresh() {
    const state = structuredState();
    if (!state) {
      setChip("personalityControlDraft", "Ukendt", false);
      setChip("personalityControlLab", "Ukendt", false);
      setChip("personalityControlActive", "Ukendt", false);
      if ($("personalityControlNext")) {
        $("personalityControlNext").textContent = "Afventer struktureret Personality-status…";
      }
      return;
    }

    setChip(
      "personalityControlDraft",
      state.count ? `${state.count} kandidat(er)` : "Ingen kandidater",
      state.draft === "ready"
    );
    setChip(
      "personalityControlLab",
      state.labLabel || "Guided + Audition",
      state.lab === "ready"
    );
    setChip(
      "personalityControlActive",
      state.active === "bound" ? (state.activeLabel || "Aktiv binding") : "Ingen aktiv",
      state.active === "bound"
    );

    const next = $("personalityControlNext");
    if (!next) return;
    if (state.count === 0) {
      next.textContent = "Opret en personality-kandidat eller brug Guided Personality.";
    } else if (state.active !== "bound") {
      next.textContent = `${state.count} kandidat(er) klar · kør audition og fortsæt til Saml person.`;
    } else {
      next.textContent = `Aktiv personality bundet · ${state.count} kandidat(er) tilgængelige.`;
    }
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
        "data-draft-state",
        "data-draft-count",
        "data-lab-state",
        "data-lab-label",
        "data-active-state",
        "data-active-label",
      ],
    });
  }

  refresh();
})();