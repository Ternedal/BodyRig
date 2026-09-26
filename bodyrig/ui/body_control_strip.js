(() => {
  const $ = (id) => document.getElementById(id);
  const ALLOWED = {
    preview: new Set(["ready", "missing", "unknown"]),
    review: new Set(["ready", "missing", "blocked", "checking", "unknown"]),
    release: new Set(["ready", "blocked", "checking", "unknown"]),
    fidelity: new Set(["ready", "blocked", "checking", "unknown"]),
    fidelityReview: new Set(["ready", "required", "blocked", "checking", "unknown"]),
  };

  function setChip(id, state, active) {
    const chip = $(id);
    if (!chip) return;
    const stateNode = chip.querySelector(".chip-state");
    if (stateNode) stateNode.textContent = state || "Ukendt";
    chip.classList.toggle("active", Boolean(active));
  }

  function scrollToCard(id, fallbackId) {
    const target = $(id) || $(fallbackId)?.closest(".card");
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function readState(root, key) {
    const value = String(root?.dataset?.[key + "State"] || "").trim();
    return ALLOWED[key]?.has(value) ? value : null;
  }

  function structuredState() {
    const root = $("bodyControlStrip");
    if (!root || root.dataset.stateVersion !== "1") return null;

    const preview = readState(root, "preview");
    const review = readState(root, "review");
    const release = readState(root, "release");
    const fidelity = readState(root, "fidelity");
    const fidelityReview = readState(root, "fidelityReview");
    const previewLabel = String(root.dataset.previewLabel || "").trim();
    const reviewLabel = String(root.dataset.reviewLabel || "").trim();
    const releaseLabel = String(root.dataset.releaseLabel || "").trim();
    const nextLabel = String(root.dataset.nextLabel || "").trim();

    if (
      !preview
      || !review
      || !release
      || !fidelity
      || !fidelityReview
      || previewLabel.length > 240
      || reviewLabel.length > 240
      || releaseLabel.length > 240
      || nextLabel.length > 1000
    ) {
      return null;
    }

    return {
      preview,
      review,
      release,
      fidelity,
      fidelityReview,
      previewLabel,
      reviewLabel,
      releaseLabel,
      nextLabel,
    };
  }

  function refresh() {
    const state = structuredState();
    const reviewButton = $("bodyControlReview");
    const releaseButton = $("bodyControlRelease");

    if (!state) {
      setChip("bodyControlPreview", "Ukendt", false);
      setChip("bodyControlReview", "Ukendt", false);
      setChip("bodyControlRelease", "Ukendt", false);
      if (reviewButton) reviewButton.disabled = !$("bodyReviewGalleryCard");
      if (releaseButton) releaseButton.disabled = !$("bodyReleaseStatusCard");
      if ($("bodyControlNext")) {
        $("bodyControlNext").textContent = "Afventer struktureret body-status…";
      }
      return;
    }

    setChip(
      "bodyControlPreview",
      state.previewLabel || (state.preview === "ready" ? "Body klar" : "Ingen revision"),
      state.preview === "ready"
    );

    if (reviewButton) reviewButton.disabled = !$("bodyReviewGalleryCard");
    setChip(
      "bodyControlReview",
      state.reviewLabel || "Afventer review",
      state.review === "ready"
    );

    if (releaseButton) releaseButton.disabled = !$("bodyReleaseStatusCard");
    setChip(
      "bodyControlRelease",
      state.releaseLabel || "Production låst",
      state.release === "ready"
    );

    const next = $("bodyControlNext");
    if (!next) return;

    if (state.nextLabel) {
      next.textContent = state.nextLabel;
    } else if (state.fidelityReview !== "ready") {
      next.textContent = state.fidelityReview === "required"
        ? "High-fidelity human review kræves."
        : "High-fidelity human review er ikke klar.";
    } else if (state.fidelity !== "ready") {
      next.textContent = "High-fidelity komponenter er ikke komplette.";
    } else if (state.review !== "ready") {
      next.textContent = "4-view review er ikke komplet.";
    } else if (state.preview === "ready") {
      next.textContent = "Følg næste canonical release gate nedenfor.";
    } else {
      next.textContent = "Byg eller vælg en body-revision.";
    }
  }

  $("bodyControlPreview")?.addEventListener("click", () => scrollToCard("", "bodyPreview"));
  $("bodyControlReview")?.addEventListener("click", () => scrollToCard("bodyReviewGalleryCard"));
  $("bodyControlRelease")?.addEventListener("click", () => scrollToCard("bodyReleaseStatusCard"));

  const root = $("bodyControlStrip");
  if (root) {
    new MutationObserver(refresh).observe(root, {
      attributes: true,
      attributeFilter: [
        "data-state-version",
        "data-preview-state",
        "data-preview-label",
        "data-review-state",
        "data-review-label",
        "data-release-state",
        "data-release-label",
        "data-fidelity-state",
        "data-fidelity-review-state",
        "data-next-label",
      ],
    });
  }

  refresh();
})();