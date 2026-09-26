(() => {
  const $ = (id) => document.getElementById(id);

  function text(id) {
    return ($(id)?.textContent || "").trim();
  }

  function setSignal(id, active) {
    const el = $(id);
    if (!el) return;
    el.classList.toggle("active", Boolean(active));
  }

  function parsePipeline() {
    const badge = text("overviewCockpitBadge");
    const match = badge.match(/(\d+)\s*\/\s*(\d+)/);
    if (match) return { complete: Number(match[1]), total: Number(match[2]) };
    if (badge === "Komplet") return { complete: 6, total: 6 };
    return { complete: 0, total: 6 };
  }

  function attentionCount() {
    const badge = text("operatorAttentionBadge");
    const match = badge.match(/\d+/);
    return match ? Number(match[0]) : 0;
  }

  function refresh() {
    const name = text("personName") || "—";
    const person = text("personActive").replace(/^Person\s+/, "");
    const body = text("bodyActive").replace(/^Krop\s+/, "");
    const voice = text("voiceActive").replace(/^Stemme\s+/, "");
    const personality = text("personalityActive").replace(/^Personlighed\s+/, "");
    const pipeline = parsePipeline();
    const pct = pipeline.total ? Math.max(0, Math.min(100, pipeline.complete / pipeline.total * 100)) : 0;
    const attention = attentionCount();

    if ($("personHudName")) $("personHudName").textContent = name;
    if ($("personHudRevision")) $("personHudRevision").textContent = person && person !== "—" ? person : "Ingen aktiv revision";
    if ($("personHudPipeline")) $("personHudPipeline").textContent = `${pipeline.complete}/${pipeline.total}`;
    if ($("personHudMeterFill")) $("personHudMeterFill").style.width = `${pct}%`;

    setSignal("personHudBody", body && body !== "—");
    setSignal("personHudVoice", voice && voice !== "—");
    setSignal("personHudPersonality", personality && personality !== "—");
    setSignal("personHudAttention", attention > 0);

    if ($("personHudAttentionText")) {
      $("personHudAttentionText").textContent = attention > 0 ? `Drift · ${attention}` : "Drift";
    }
  }

  for (const button of document.querySelectorAll(".person-hud-signal[data-target-tab]")) {
    button.addEventListener("click", () => {
      const tab = button.dataset.targetTab;
      document.querySelector(`.tab[data-tab="${tab}"]`)?.click();
    });
  }

  const ids = [
    "personName", "personActive", "bodyActive", "voiceActive", "personalityActive",
    "overviewCockpitBadge", "operatorAttentionBadge"
  ];
  for (const id of ids) {
    const node = $(id);
    if (node) new MutationObserver(refresh).observe(node, { childList: true, characterData: true, subtree: true });
  }

  refresh();
})();