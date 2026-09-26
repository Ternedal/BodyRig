(() => {
  const $ = (id) => document.getElementById(id);

  function text(id) {
    return ($(id)?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function setChip(id, state, active) {
    const chip = $(id);
    if (!chip) return;
    const stateNode = chip.querySelector(".chip-state");
    if (stateNode) stateNode.textContent = state || "—";
    chip.classList.toggle("active", Boolean(active));
  }

  function scrollToCard(id, fallbackId) {
    const target = $(id) || $(fallbackId)?.closest(".card");
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function refresh() {
    const revision = text("bodyRevisionLabel");
    const reviewBadge = text("bodyReviewGalleryBadge");
    const releaseBadge = text("bodyReleaseBadge");
    const releaseNext = text("bodyReleaseNext");
    const fidelityBadge = text("bodyFidelityBadge");
    const fidelityReview = text("bodyFidelityReviewBadge");

    setChip("bodyControlPreview", revision || "Ingen revision", Boolean(revision && revision !== "Ingen revision"));

    const reviewButton = $("bodyControlReview");
    if (reviewButton) reviewButton.disabled = !$("bodyReviewGalleryCard");
    setChip(
      "bodyControlReview",
      reviewBadge || "Afventer review",
      /^4\/4 hash-bundet$/i.test(reviewBadge)
    );

    const releaseButton = $("bodyControlRelease");
    if (releaseButton) releaseButton.disabled = !$("bodyReleaseStatusCard");
    setChip(
      "bodyControlRelease",
      releaseBadge || "Production låst",
      /^Production klar$/i.test(releaseBadge)
    );

    const next = $("bodyControlNext");
    if (next) {
      if (releaseNext) next.textContent = releaseNext;
      else if (fidelityReview && !/^Review PASS$/i.test(fidelityReview)) next.textContent = `High-fidelity review · ${fidelityReview}`;
      else if (fidelityBadge && !/^HF-komponenter komplette$/i.test(fidelityBadge)) next.textContent = `High-fidelity komponenter · ${fidelityBadge}`;
      else if (reviewBadge && !/^4\/4 hash-bundet$/i.test(reviewBadge)) next.textContent = `4-view review · ${reviewBadge}`;
      else if (revision) next.textContent = "Følg næste canonical release gate nedenfor.";
      else next.textContent = "Byg eller vælg en body-revision.";
    }
  }

  $("bodyControlPreview")?.addEventListener("click", () => scrollToCard("", "bodyPreview"));
  $("bodyControlReview")?.addEventListener("click", () => scrollToCard("bodyReviewGalleryCard"));
  $("bodyControlRelease")?.addEventListener("click", () => scrollToCard("bodyReleaseStatusCard"));

  const tab = $("tab-body");
  if (tab) {
    new MutationObserver(refresh).observe(tab, {
      childList: true,
      characterData: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "disabled"],
    });
  }

  refresh();
})();