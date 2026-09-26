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

  function unseenAttentionCount() {
    const badge = $("operatorAttentionBadge");
    const declared = Number(badge?.dataset?.unseenCount);
    if (Number.isInteger(declared) && declared >= 0) return declared;
    return [...document.querySelectorAll("#operatorAttentionItems .new-attention")].length;
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
    const unseen = unseenAttentionCount();

    if ($("personHudName")) $("personHudName").textContent = name;
    if ($("personHudRevision")) $("personHudRevision").textContent = person && person !== "—" ? person : "Ingen aktiv revision";
    if ($("personHudPipeline")) $("personHudPipeline").textContent = `${pipeline.complete}/${pipeline.total}`;
    if ($("personHudMeterFill")) $("personHudMeterFill").style.width = `${pct}%`;

    setSignal("personHudBody", body && body !== "—");
    setSignal("personHudVoice", voice && voice !== "—");
    setSignal("personHudPersonality", personality && personality !== "—");
    setSignal("personHudAttention", attention > 0);
    $("personHudAttention")?.classList.toggle("has-new", unseen > 0);

    if ($("personHudAttentionText")) {
      $("personHudAttentionText").textContent = attention > 0
        ? `Drift · ${attention}${unseen ? ` · NY ${unseen}` : ""}`
        : "Drift";
    }
    if ($("personHudAttention")) {
      $("personHudAttention").title = unseen > 0
        ? `${unseen} nye operator-punkt${unseen === 1 ? "" : "er"} siden sidste Live Activity-visning`
        : (attention > 0 ? `${attention} aktive operator-punkter` : "Ingen aktive operator-punkter");
    }
  }

  for (const button of document.querySelectorAll(".person-hud-signal[data-target-tab]")) {
    button.addEventListener("click", () => {
      if (button.id === "personHudAttention" && attentionCount() > 0 && $("personActivityToggle")) {
        $("personActivityToggle").click();
        return;
      }
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
    if (node) new MutationObserver(refresh).observe(node, {
      childList: true,
      characterData: true,
      attributes: id === "operatorAttentionBadge",
      attributeFilter: id === "operatorAttentionBadge" ? ["data-unseen-count", "class"] : undefined,
      subtree: true,
    });
  }

  window.addEventListener("bodyrig:attention-delta", refresh);
  window.addEventListener("bodyrig:attention-seen", refresh);
  refresh();
})();