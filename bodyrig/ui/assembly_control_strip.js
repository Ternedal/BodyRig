(() => {
  const $ = (id) => document.getElementById(id);
  const ALLOWED = {
    selection: new Set(["ready", "incomplete"]),
    audition: new Set(["ready", "running", "idle"]),
    review: new Set(["ready", "locked"]),
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
    const root = $("assemblyControlStrip");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const selection = String(root.dataset.selectionState || "").trim();
    const audition = String(root.dataset.auditionState || "").trim();
    const review = String(root.dataset.reviewState || "").trim();
    const selectionCount = integerDataset(root, "selectionCount");
    const auditionLabel = String(root.dataset.auditionLabel || "").trim();
    const reviewLabel = String(root.dataset.reviewLabel || "").trim();

    if (
      !ALLOWED.selection.has(selection)
      || !ALLOWED.audition.has(audition)
      || !ALLOWED.review.has(review)
      || selectionCount === null
      || selectionCount < 0
      || selectionCount > 3
      || auditionLabel.length > 240
      || reviewLabel.length > 240
    ) {
      return null;
    }

    return { selection, audition, review, selectionCount, auditionLabel, reviewLabel };
  }

  function refresh() {
    const state = structuredState();
    if (!state) {
      setChip("assemblyControlSelection", "Ukendt", false);
      setChip("assemblyControlAudition", "Ukendt", false);
      setChip("assemblyControlReview", "Ukendt", false);
      if ($("assemblyControlNext")) {
        $("assemblyControlNext").textContent = "Afventer struktureret assembly-status…";
      }
      return;
    }

    setChip(
      "assemblyControlSelection",
      state.selection === "ready" ? "3/3 valgt" : `${state.selectionCount}/3 valgt`,
      state.selection === "ready"
    );
    setChip(
      "assemblyControlAudition",
      state.audition === "ready"
        ? (state.auditionLabel || "Audition komplet")
        : (state.audition === "running" ? "Audition i gang" : "Ikke kørt"),
      state.audition === "ready"
    );
    setChip(
      "assemblyControlReview",
      state.reviewLabel || (state.review === "ready" ? "Klar til review" : "Låst"),
      state.review === "ready"
    );

    const next = $("assemblyControlNext");
    if (!next) return;
    if (state.selection !== "ready") {
      next.textContent = "Vælg body, voice og personality.";
    } else if (state.audition !== "ready") {
      next.textContent = state.audition === "running"
        ? "Samlet ModelRig + VoiceRig audition kører."
        : "Kør samlet ModelRig + VoiceRig audition.";
    } else if (state.review !== "ready") {
      next.textContent = "Gennemfør compatibility review.";
    } else {
      next.textContent = "Review er klar · godkend kun efter eksplicit menneskelig vurdering.";
    }
  }

  $("assemblyControlSelection")?.addEventListener("click", () => {
    $("assembleBody")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("assemblyControlAudition")?.addEventListener("click", () => {
    $("prepareAssemblyButton")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("assemblyControlReview")?.addEventListener("click", () => {
    $("assemblyReviewStatus")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  const root = $("assemblyControlStrip");
  if (root) {
    new MutationObserver(refresh).observe(root, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-selection-state",
        "data-selection-count",
        "data-audition-state",
        "data-audition-label",
        "data-review-state",
        "data-review-label",
      ],
    });
  }

  refresh();
})();