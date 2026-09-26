(() => {
  const $ = (id) => document.getElementById(id);

  function text(id) {
    return ($(id)?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function selected(id) {
    const node = $(id);
    return Boolean(node && node.value);
  }

  function setChip(id, state, active) {
    const chip = $(id);
    if (!chip) return;
    const stateNode = chip.querySelector(".chip-state");
    if (stateNode) stateNode.textContent = state || "—";
    chip.classList.toggle("active", Boolean(active));
  }

  function refresh() {
    const completeSelection = selected("assembleBody") && selected("assembleVoice") && selected("assemblePersonality");
    const fingerprint = text("assemblyFingerprint");
    const bodyState = text("assemblyBodyState");
    const voiceState = text("assemblyVoiceState");
    const personalityState = text("assemblyPersonalityState");
    const readyBadge = text("assemblyReadyBadge");
    const reviewStatus = text("assemblyReviewStatus");

    setChip(
      "assemblyControlSelection",
      completeSelection ? "3/3 valgt" : "Vælg body + voice + personality",
      completeSelection
    );

    const auditionComplete =
      fingerprint && !/ingen audition/i.test(fingerprint)
      && !/ikke loadet/i.test(bodyState)
      && !/ikke hørt/i.test(voiceState)
      && !/ikke vist/i.test(personalityState);

    setChip(
      "assemblyControlAudition",
      auditionComplete ? "Audition komplet" : (fingerprint || "Ikke kørt"),
      auditionComplete
    );

    const reviewReady = /^Klar til review$/i.test(readyBadge);
    setChip(
      "assemblyControlReview",
      readyBadge || "Låst",
      reviewReady
    );

    const next = $("assemblyControlNext");
    if (!next) return;
    if (!completeSelection) next.textContent = "Vælg body, voice og personality.";
    else if (!auditionComplete) next.textContent = "Kør samlet ModelRig + VoiceRig audition.";
    else if (!reviewReady) next.textContent = reviewStatus || "Gennemfør compatibility review.";
    else next.textContent = "Review er klar · godkend kun efter eksplicit menneskelig vurdering.";
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

  for (const id of [
    "assembleBody","assembleVoice","assemblePersonality",
    "assemblyFingerprint","assemblyBodyState","assemblyVoiceState",
    "assemblyPersonalityState","assemblyReadyBadge","assemblyReviewStatus"
  ]) {
    const node = $(id);
    if (!node) continue;
    new MutationObserver(refresh).observe(node, { childList: true, characterData: true, subtree: true, attributes: true });
    if (node instanceof HTMLSelectElement) node.addEventListener("change", refresh);
  }

  refresh();
})();