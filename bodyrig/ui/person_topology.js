(() => {
  const $ = (id) => document.getElementById(id);

  function value(id) {
    return ($ (id)?.textContent || "").trim();
  }

  function setNode(id, active, stateText) {
    const node = $(id);
    if (!node) return;
    node.classList.toggle("active", Boolean(active));
    node.classList.toggle("inactive", !active);
    const state = node.querySelector(".node-state");
    if (state) state.textContent = stateText || "—";
  }

  function refresh() {
    const source = value("personSource");
    const person = value("personActive").replace(/^Person\s+/, "");
    const body = value("bodyActive").replace(/^Krop\s+/, "");
    const voice = value("voiceActive").replace(/^Stemme\s+/, "");
    const personality = value("personalityActive").replace(/^Personlighed\s+/, "");
    const twinBadge = value("operator-digital-twin-badge");
    const twinSummary = value("operator-digital-twin-summary");

    const hasSource = Boolean(source && !source.includes("Ingen Stash-binding"));
    const hasPerson = Boolean(person && person !== "—");
    const hasBody = Boolean(body && body !== "—");
    const hasVoice = Boolean(voice && voice !== "—");
    const hasPersonality = Boolean(personality && personality !== "—");
    const twinReady = /^M6 klar$/i.test(twinBadge);

    setNode("personTopologySource", hasSource, hasSource ? source.replace(/^Stash:\s*/, "") : "Ingen binding");
    setNode("personTopologyBody", hasBody, hasBody ? body : "Ingen aktiv binding");
    setNode("personTopologyVoice", hasVoice, hasVoice ? voice : "Ingen aktiv binding");
    setNode("personTopologyPersonality", hasPersonality, hasPersonality ? personality : "Ingen aktiv binding");
    setNode("personTopologyCore", hasPerson, hasPerson ? "Aktiv canonical revision" : "Ikke samlet");
    setNode("personTopologyTwin", twinReady, twinSummary || twinBadge || "Ukendt");

    const coreName = $("personTopologyCoreName");
    if (coreName) coreName.textContent = hasPerson ? person : "Ikke samlet";

    const completed = [hasSource, hasBody, hasVoice, hasPersonality, hasPerson, twinReady].filter(Boolean).length;
    const badge = $("personTopologyBadge");
    if (badge) {
      badge.textContent = twinReady ? "Topology locked" : `${completed}/6 linked`;
      badge.classList.toggle("muted", !twinReady);
    }
  }

  for (const button of document.querySelectorAll("[data-topology-tab]")) {
    button.addEventListener("click", () => {
      document.querySelector(`.tab[data-tab="${button.dataset.topologyTab}"]`)?.click();
    });
  }

  const observed = [
    "personSource",
    "personActive",
    "bodyActive",
    "voiceActive",
    "personalityActive",
    "operator-digital-twin-badge",
    "operator-digital-twin-summary",
  ];
  for (const id of observed) {
    const node = $(id);
    if (node) new MutationObserver(refresh).observe(node, { childList: true, characterData: true, subtree: true });
  }

  refresh();
})();